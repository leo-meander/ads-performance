"""GA4 sync: pull yesterday's reports per branch → landing_page_ga4_snapshots.

Strategy:
  - One GA4 property per branch (stored in ad_accounts.ga4_property_id).
  - For each branch, run 2 reports:
        A) Core + ecommerce report (split by date × pagePath × source/medium/campaign)
        B) Web Vitals report (split by date × pagePath — web-vitals events)
  - Merge A + B per (page, date, source, medium, campaign), plus an
    aggregate row (source=medium=campaign=NULL).
  - Upsert into landing_page_ga4_snapshots.

Data freshness: GA4 has ~24-48h finalization delay. We run the cron at 04:00
UTC daily to pull yesterday's finalized numbers.

Page matching: GA4 `pagePath` is the URL path (e.g. "/solo-traveler-direct-zh")
and `hostName` is the domain. We match against landing_pages.(domain, slug).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.landing_page import LandingPage
from app.models.landing_page_ga4 import LandingPageGA4Snapshot
from app.services.ga4_client import run_report

logger = logging.getLogger(__name__)


# ── dimension + metric names ──────────────────────────────────────────────

CORE_DIMENSIONS = ["date", "hostName", "pagePath", "sessionSource", "sessionMedium", "sessionCampaignName"]
# GA4 API caps a single runReport at 10 metrics — we split into 2 calls
# and merge by the dimension tuple (which is identical across both).
TRAFFIC_METRICS = [
    "sessions",
    "engagedSessions",
    "engagementRate",
    "activeUsers",
    "newUsers",
    "screenPageViews",
    "averageSessionDuration",
    "bounceRate",
]
ECOMM_METRICS = [
    "checkouts",
    "addToCarts",
    "ecommercePurchases",
    "purchaseRevenue",
]

VITALS_DIMENSIONS = ["date", "hostName", "pagePath", "eventName"]
VITALS_METRICS = ["eventCount", "eventValue"]


# ── helpers ────────────────────────────────────────────────────────────────


def _parse_ga4_date(s: str) -> date:
    """GA4 returns `date` as YYYYMMDD string."""
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def _find_landing_page(db: Session, host: str, path: str) -> LandingPage | None:
    slug = (path or "").lstrip("/").rstrip("/")
    host_norm = (host or "").lower().lstrip("www.")
    host_www = f"www.{host_norm}"
    return (
        db.query(LandingPage)
        .filter(
            LandingPage.domain.in_([host_norm, host_www]),
            LandingPage.slug == slug,
            LandingPage.is_active.is_(True),
        )
        .one_or_none()
    )


def _upsert_snapshot(
    db: Session,
    *,
    landing_page_id: str,
    target_date: date,
    source: str | None,
    medium: str | None,
    campaign: str | None,
    metrics: dict[str, Any],
) -> None:
    q = db.query(LandingPageGA4Snapshot).filter(
        LandingPageGA4Snapshot.landing_page_id == landing_page_id,
        LandingPageGA4Snapshot.date == target_date,
    )
    if source is None:
        q = q.filter(LandingPageGA4Snapshot.source.is_(None))
    else:
        q = q.filter(LandingPageGA4Snapshot.source == source)
    if medium is None:
        q = q.filter(LandingPageGA4Snapshot.medium.is_(None))
    else:
        q = q.filter(LandingPageGA4Snapshot.medium == medium)
    if campaign is None:
        q = q.filter(LandingPageGA4Snapshot.campaign.is_(None))
    else:
        q = q.filter(LandingPageGA4Snapshot.campaign == campaign)
    row = q.one_or_none()

    if row is None:
        row = LandingPageGA4Snapshot(
            landing_page_id=landing_page_id,
            date=target_date,
            source=source,
            medium=medium,
            campaign=campaign,
        )
        db.add(row)

    # Core
    row.sessions = metrics.get("sessions", 0)
    row.engaged_sessions = metrics.get("engaged_sessions", 0)
    row.engagement_rate = metrics.get("engagement_rate")
    row.active_users = metrics.get("active_users", 0)
    row.new_users = metrics.get("new_users", 0)
    row.screen_page_views = metrics.get("screen_page_views", 0)
    row.avg_session_duration_sec = metrics.get("avg_session_duration_sec")
    row.bounce_rate = metrics.get("bounce_rate")

    # Ecommerce
    row.begin_checkout = metrics.get("begin_checkout", 0)
    row.add_payment_info = metrics.get("add_payment_info", 0)
    row.purchases = metrics.get("purchases", 0)
    row.purchase_revenue = metrics.get("purchase_revenue", 0)

    # Web Vitals
    row.lcp_p75_ms = metrics.get("lcp_p75_ms")
    row.inp_p75_ms = metrics.get("inp_p75_ms")
    row.cls_p75 = metrics.get("cls_p75")
    row.fcp_p75_ms = metrics.get("fcp_p75_ms")

    row.raw_data = metrics.get("raw")


def _shape_core(rows: list[dict]) -> dict[tuple, dict[str, Any]]:
    """Transform GA4 report rows into {(date, host, path, src, med, camp): {...}}."""
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        key = (
            _parse_ga4_date(r["date"]),
            r.get("hostName", ""),
            r.get("pagePath", ""),
            r.get("sessionSource") or None,
            r.get("sessionMedium") or None,
            r.get("sessionCampaignName") or None,
        )
        out[key] = {
            "sessions": int(r.get("sessions") or 0),
            "engaged_sessions": int(r.get("engagedSessions") or 0),
            "engagement_rate": float(r["engagementRate"]) if r.get("engagementRate") else None,
            "active_users": int(r.get("activeUsers") or 0),
            "new_users": int(r.get("newUsers") or 0),
            "screen_page_views": int(r.get("screenPageViews") or 0),
            "avg_session_duration_sec": float(r["averageSessionDuration"]) if r.get("averageSessionDuration") else None,
            "bounce_rate": float(r["bounceRate"]) if r.get("bounceRate") else None,
            "begin_checkout": int(r.get("checkouts") or 0),
            "add_payment_info": int(r.get("addToCarts") or 0),
            "purchases": int(r.get("ecommercePurchases") or 0),
            "purchase_revenue": float(r.get("purchaseRevenue") or 0),
            "raw": {"core": r},
        }
    return out


def _shape_vitals(rows: list[dict]) -> dict[tuple, dict[str, Any]]:
    """Summarise web-vitals events into per-(date, host, path) p75-ish aggregates.

    GA4 web-vitals events come as one row per (date, page, event_name=LCP|INP|CLS|FCP).
    `eventValue` is the SUM of values; `eventCount` is the number of events.
    We use the average as a proxy for p75 (GA4 free doesn't expose native percentile).
    Good enough for trending; precise p75 requires BigQuery export.
    """
    grouped: dict[tuple, dict[str, Any]] = defaultdict(lambda: {"raw": {}})
    for r in rows:
        key = (_parse_ga4_date(r["date"]), r.get("hostName", ""), r.get("pagePath", ""))
        ev = (r.get("eventName") or "").upper()
        count = int(r.get("eventCount") or 0)
        value = float(r.get("eventValue") or 0)
        avg = (value / count) if count > 0 else None
        g = grouped[key]
        if ev == "LCP":
            g["lcp_p75_ms"] = int(avg) if avg is not None else None
        elif ev == "INP":
            g["inp_p75_ms"] = int(avg) if avg is not None else None
        elif ev == "CLS":
            g["cls_p75"] = avg
        elif ev == "FCP":
            g["fcp_p75_ms"] = int(avg) if avg is not None else None
        g["raw"].setdefault("vitals", []).append(r)
    return dict(grouped)


# ── entry point ────────────────────────────────────────────────────────────


def run_ga4_sync(
    db: Session,
    *,
    target_date: date | None = None,
    days_back: int = 2,
    branch_filter: str | None = None,
) -> dict[str, Any]:
    """Pull GA4 data for all branches that have a ga4_property_id configured.

    `days_back` (default 2): how many days prior to today to sync. 2 is safer
    than 1 because of GA4's finalization delay — yesterday's data is "mostly"
    final, day-before-yesterday is definitely final.

    `branch_filter`: optional AdAccount.id — sync only that branch (useful
    for testing a single property like Oani before rolling to all branches).
    """
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=days_back)
    end_date = today - timedelta(days=1)

    accounts_q = db.query(AdAccount).filter(
        AdAccount.is_active.is_(True),
        AdAccount.ga4_property_id.isnot(None),
        AdAccount.ga4_property_id != "",
    )
    if branch_filter:
        accounts_q = accounts_q.filter(AdAccount.id == branch_filter)
    accounts = accounts_q.all()

    summary: dict[str, Any] = {
        "date_from": start_date.isoformat(),
        "date_to": end_date.isoformat(),
        "branches": {},
        "errors": 0,
    }

    if not accounts:
        summary["skipped_reason"] = "no branches with ga4_property_id configured"
        return summary

    # Dedupe by property_id — multiple ad_accounts can share a property
    seen_properties: set[str] = set()

    for acc in accounts:
        prop = acc.ga4_property_id.strip()
        if prop in seen_properties:
            continue
        seen_properties.add(prop)

        b_summary = {"pages_touched": 0, "rows": 0}

        # Build a filter restricting the query to only our registered landing
        # pages (by host + path). GA4 property can see many URLs (Cloudbeds
        # booking, CMS admin, static assets, etc.) — we only care about the
        # landing_pages rows. Cuts response size ~80% and avoids noise.
        active_pages = (
            db.query(LandingPage.domain, LandingPage.slug)
            .filter(LandingPage.is_active.is_(True))
            .all()
        )
        if not active_pages:
            logger.warning("[ga4-sync] %s: no active landing pages, skipping", acc.account_name)
            summary["branches"][acc.account_name] = {"skipped": "no landing pages"}
            continue

        hosts: set[str] = set()
        paths: set[str] = set()
        for dom, slug in active_pages:
            host = (dom or "").lower()
            hosts.add(host)
            hosts.add(f"www.{host}")  # GA4 may report with or without www.
            path = "/" + (slug or "").strip("/") if slug else "/"
            paths.add(path)
            paths.add(path + "/")  # GA4 may include trailing slash

        landing_filter = {
            "and_group": {
                "expressions": [
                    {"filter": {"field_name": "hostName", "in_list_filter": {"values": sorted(hosts)}}},
                    {"filter": {"field_name": "pagePath", "in_list_filter": {"values": sorted(paths)}}},
                ]
            }
        }

        try:
            # Only pull traffic metrics on our landing pages. We intentionally
            # skip ecommerce metrics (begin_checkout, purchases, revenue):
            # those events fire on hotels.cloudbeds.com after users leave our
            # landing page, and a pagePath-filtered query would always return
            # zero. True cross-domain attribution requires a different query
            # shape (scoped to landingPagePath + cross-domain session id) —
            # out of scope for Phase 1. Revenue is tracked elsewhere (Meta
            # pixel + Cloudbeds booking matches).
            traffic_rows = run_report(
                prop,
                date_from=start_date,
                date_to=end_date,
                dimensions=CORE_DIMENSIONS,
                metrics=TRAFFIC_METRICS,
                dimension_filter=landing_filter,
            )
            core_rows = [
                {**r, **{m: 0 for m in ECOMM_METRICS}}
                for r in traffic_rows
            ]
            b_summary["traffic_rows"] = len(traffic_rows)
        except Exception as e:
            logger.exception("[ga4-sync] %s: core report failed", acc.account_name)
            summary["branches"][acc.account_name] = {"error": str(e)}
            summary["errors"] += 1
            continue

        vitals_filter = {
            "and_group": {
                "expressions": [
                    {"filter": {"field_name": "hostName", "in_list_filter": {"values": sorted(hosts)}}},
                    {"filter": {"field_name": "pagePath", "in_list_filter": {"values": sorted(paths)}}},
                    {"filter": {"field_name": "eventName", "in_list_filter": {"values": ["LCP", "INP", "CLS", "FCP"]}}},
                ]
            }
        }
        try:
            vitals_rows = run_report(
                prop,
                date_from=start_date,
                date_to=end_date,
                dimensions=VITALS_DIMENSIONS,
                metrics=VITALS_METRICS,
                dimension_filter=vitals_filter,
            )
            b_summary["vitals_rows"] = len(vitals_rows)
        except Exception:
            logger.exception("[ga4-sync] %s: vitals report failed, continuing without vitals",
                             acc.account_name)
            vitals_rows = []
            b_summary["vitals_rows"] = 0

        core_shaped = _shape_core(core_rows)
        vitals_shaped = _shape_vitals(vitals_rows)

        # Group by (page, date): find landing_page, upsert per-UTM rows + aggregate
        per_page_day: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)

        for key, metrics in core_shaped.items():
            dt, host, path, src, med, camp = key
            page = _find_landing_page(db, host, path)
            if page is None:
                continue

            # Merge Web Vitals (aggregate for (page, day) — vitals aren't split by UTM)
            vitals = vitals_shaped.get((dt, host, path), {})
            full = {**metrics, **{k: v for k, v in vitals.items() if k != "raw"}}

            try:
                _upsert_snapshot(
                    db,
                    landing_page_id=page.id,
                    target_date=dt,
                    source=src,
                    medium=med,
                    campaign=camp,
                    metrics=full,
                )
                b_summary["rows"] += 1
                per_page_day[(page.id, dt)].append(full)
            except Exception:
                logger.exception("[ga4-sync] upsert failed page=%s date=%s", page.id, dt)
                summary["errors"] += 1

        # Aggregate rows (source/medium/campaign = NULL) per (page, day)
        for (page_id, day), rows in per_page_day.items():
            agg: dict[str, Any] = {}
            sum_keys = ["sessions", "engaged_sessions", "active_users", "new_users",
                        "screen_page_views", "begin_checkout", "add_payment_info",
                        "purchases", "purchase_revenue"]
            for r in rows:
                for k in sum_keys:
                    agg[k] = (agg.get(k) or 0) + (r.get(k) or 0)
            # Averages — weighted by sessions
            total_sessions = sum(r.get("sessions", 0) for r in rows) or 1
            for avg_key in ("engagement_rate", "avg_session_duration_sec", "bounce_rate"):
                num = sum((r.get(avg_key) or 0) * (r.get("sessions") or 0) for r in rows if r.get(avg_key) is not None)
                agg[avg_key] = num / total_sessions if num else None
            # Web Vitals — same for all UTM splits, take from any row
            for vk in ("lcp_p75_ms", "inp_p75_ms", "cls_p75", "fcp_p75_ms"):
                vals = [r.get(vk) for r in rows if r.get(vk) is not None]
                agg[vk] = vals[0] if vals else None
            agg["raw"] = {"agg": True, "from_rows": len(rows)}

            try:
                _upsert_snapshot(
                    db,
                    landing_page_id=page_id,
                    target_date=day,
                    source=None,
                    medium=None,
                    campaign=None,
                    metrics=agg,
                )
                b_summary["pages_touched"] += 1
            except Exception:
                logger.exception("[ga4-sync] agg upsert failed page=%s date=%s", page_id, day)
                summary["errors"] += 1

        summary["branches"][acc.account_name] = b_summary

    db.commit()
    logger.info("[ga4-sync] done: %s", summary)
    return summary
