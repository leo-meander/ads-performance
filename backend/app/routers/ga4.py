"""GA4 analytics router.

Phase 0 (this file): **diagnostics only**. Before building the /analytics
overview page we need to know, per property, what GA4 actually measures:

  - which hostnames the property sees (is the Cloudbeds booking engine
    tracked cross-domain, or does the session end at our landing page?)
  - which events fire, and with what volume (do the funnel steps exist?)
  - which conversion metric name this property accepts (`keyEvents` is the
    2024+ name; older properties still expose `conversions`)
  - device + channel splits, to confirm the two questions we care about
    ("mobile vs desktop" and "which traffic source") are answerable

Everything here is a live read against the GA4 Data API — no tables, no
sync, no cron. Reports are capped at a handful of calls per property.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.branches import resolve_branch_for_account_name
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.landing_page import LandingPage
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _api(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Standard GA4 ecommerce funnel, in order. We report which of these the
# property actually emits — a missing step means either the event isn't
# implemented or it fires on a domain the property can't see.
FUNNEL_STEPS = [
    "session_start",
    "page_view",
    "view_item",
    "view_item_list",
    "select_item",
    "add_to_cart",
    "begin_checkout",
    "add_payment_info",
    "purchase",
]

# Substrings that identify a third-party booking engine host. If one of these
# shows up in the property's hostName list, cross-domain measurement is live
# and purchase-side metrics are trustworthy.
BOOKING_ENGINE_HINTS = ["cloudbeds", "bookingengine", "secure-booking", "reservations"]

# Preferred conversion metric first — we use whichever the property supports.
CONVERSION_METRIC_CANDIDATES = ["keyEvents", "conversions"]
REVENUE_METRIC_CANDIDATES = ["purchaseRevenue", "totalRevenue"]


def _configured_properties(db: Session, branch_filter: str | None = None) -> list[dict[str, Any]]:
    """Ad accounts that have a GA4 property attached, deduped by property id."""
    q = db.query(AdAccount).filter(
        AdAccount.is_active.is_(True),
        AdAccount.ga4_property_id.isnot(None),
        AdAccount.ga4_property_id != "",
    )
    if branch_filter:
        q = q.filter(AdAccount.id == branch_filter)

    seen: dict[str, dict[str, Any]] = {}
    for acc in q.all():
        prop = (acc.ga4_property_id or "").strip()
        if not prop:
            continue
        if prop in seen:
            seen[prop]["account_names"].append(acc.account_name)
            continue
        seen[prop] = {
            "property_id": prop,
            "account_id": acc.id,
            "account_names": [acc.account_name],
            "branch": resolve_branch_for_account_name(acc.account_name),
        }
    return list(seen.values())


def _date_window(days: int) -> tuple[date, date]:
    """Last `days` full days, ending yesterday (GA4 finalization delay)."""
    today = datetime.now(timezone.utc).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=max(days, 1) - 1)
    return start, end


def _pick_supported(candidates: list[str], supported: set[str]) -> str | None:
    for name in candidates:
        if name in supported:
            return name
    return None


@router.get("/ga4/properties")
def list_ga4_properties(
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Which branches have a GA4 property configured, and are creds present.

    Pure DB + env read — makes no GA4 API call, so it answers "is this even
    set up?" without burning quota or waiting on the network.
    """
    try:
        from app.config import settings

        creds_configured = bool(
            (settings.GA4_SERVICE_ACCOUNT_JSON_B64 or "").strip()
            or (settings.GA4_SERVICE_ACCOUNT_JSON or "").strip()
        )

        configured = _configured_properties(db)
        missing = [
            {"account_id": a.id, "account_name": a.account_name,
             "branch": resolve_branch_for_account_name(a.account_name)}
            for a in db.query(AdAccount)
            .filter(AdAccount.is_active.is_(True))
            .filter((AdAccount.ga4_property_id.is_(None)) | (AdAccount.ga4_property_id == ""))
            .all()
        ]

        return _api({
            "credentials_configured": creds_configured,
            "properties": configured,
            "accounts_without_property": missing,
        })
    except Exception as e:
        logger.exception("[ga4] list properties failed")
        return _api(error=str(e))


@router.get("/ga4/diagnostics")
def ga4_diagnostics(
    days: int = Query(28, ge=1, le=365),
    branch_id: str | None = Query(None, description="AdAccount.id — probe a single branch"),
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Probe every configured GA4 property and report what is measurable.

    One metadata call + up to five small reports per property. Each report is
    isolated: a property that rejects one dimension still returns everything
    else, and a property the service account can't read is reported with its
    error rather than failing the whole response.
    """
    try:
        from app.services.ga4_client import get_metadata, run_report
    except Exception as e:  # pragma: no cover - import guard
        return _api(error=f"GA4 SDK unavailable: {e}")

    try:
        date_from, date_to = _date_window(days)
        properties = _configured_properties(db, branch_filter=branch_id)

        if not properties:
            return _api({
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "properties": [],
                "note": "No active ad_accounts have ga4_property_id set.",
            })

        # Our own landing page domains — anything else the property sees is an
        # external host (booking engine, blog, CMS, ...).
        own_domains: set[str] = set()
        for (dom,) in db.query(LandingPage.domain).filter(LandingPage.is_active.is_(True)).all():
            d = (dom or "").lower().lstrip("www.")
            if d:
                own_domains.add(d)
                own_domains.add(f"www.{d}")

        results: list[dict[str, Any]] = []

        for prop in properties:
            pid = prop["property_id"]
            entry: dict[str, Any] = {**prop, "ok": False, "errors": {}}

            # ── 1) metadata: which metric names this property accepts ──────
            supported: set[str] = set()
            try:
                meta = get_metadata(pid)
                supported = set(meta.get("metrics") or [])
                entry["custom_dimensions"] = [
                    d for d in (meta.get("dimensions") or []) if d.startswith("customEvent:")
                ][:30]
            except Exception as e:
                entry["errors"]["metadata"] = str(e)

            conv_metric = _pick_supported(CONVERSION_METRIC_CANDIDATES, supported)
            rev_metric = _pick_supported(REVENUE_METRIC_CANDIDATES, supported)
            entry["conversion_metric"] = conv_metric
            entry["revenue_metric"] = rev_metric

            def _report(label: str, **kwargs) -> list[dict[str, Any]]:
                """Run one report; record the error and return [] on failure."""
                try:
                    return run_report(pid, date_from=date_from, date_to=date_to, **kwargs)
                except Exception as e:
                    logger.warning("[ga4-diag] %s: %s report failed: %s", pid, label, e)
                    entry["errors"][label] = str(e)
                    return []

            # ── 2) totals ──────────────────────────────────────────────────
            total_metrics = ["sessions", "activeUsers", "newUsers", "screenPageViews"]
            if conv_metric:
                total_metrics.append(conv_metric)
            if rev_metric:
                total_metrics.append(rev_metric)
            totals_rows = _report("totals", dimensions=[], metrics=total_metrics)
            entry["totals"] = totals_rows[0] if totals_rows else {}

            # ── 3) hostnames — the cross-domain question ───────────────────
            host_rows = _report("hostnames", dimensions=["hostName"], metrics=["sessions"], limit=50)
            host_rows.sort(key=lambda r: r.get("sessions", 0), reverse=True)
            hosts = [
                {
                    "host": r.get("hostName", ""),
                    "sessions": r.get("sessions", 0),
                    "is_own": (r.get("hostName", "") or "").lower() in own_domains,
                }
                for r in host_rows[:25]
            ]
            entry["hostnames"] = hosts
            entry["booking_engine_hosts"] = [
                h["host"] for h in hosts
                if any(hint in h["host"].lower() for hint in BOOKING_ENGINE_HINTS)
            ]

            # ── 4) events — the funnel question ────────────────────────────
            event_rows = _report(
                "events", dimensions=["eventName"], metrics=["eventCount", "totalUsers"], limit=200
            )
            event_rows.sort(key=lambda r: r.get("eventCount", 0), reverse=True)
            entry["events"] = [
                {
                    "event": r.get("eventName", ""),
                    "count": r.get("eventCount", 0),
                    "users": r.get("totalUsers", 0),
                }
                for r in event_rows[:60]
            ]
            counts = {r.get("eventName", ""): r.get("eventCount", 0) for r in event_rows}
            entry["funnel_steps"] = [
                {"event": step, "count": counts.get(step, 0), "present": counts.get(step, 0) > 0}
                for step in FUNNEL_STEPS
            ]

            # ── 5) device split — the mobile-vs-PC question ────────────────
            device_metrics = ["sessions", "engagedSessions", "engagementRate"]
            if conv_metric:
                device_metrics.append(conv_metric)
            if rev_metric:
                device_metrics.append(rev_metric)
            device_rows = _report(
                "devices", dimensions=["deviceCategory"], metrics=device_metrics, limit=10
            )
            entry["devices"] = sorted(
                device_rows, key=lambda r: r.get("sessions", 0), reverse=True
            )

            # ── 6) channel split — the traffic-source question ─────────────
            channel_rows = _report(
                "channels",
                dimensions=["sessionDefaultChannelGroup"],
                metrics=["sessions"] + ([conv_metric] if conv_metric else []),
                limit=30,
            )
            entry["channels"] = sorted(
                channel_rows, key=lambda r: r.get("sessions", 0), reverse=True
            )

            # ── verdict ────────────────────────────────────────────────────
            has_purchase = counts.get("purchase", 0) > 0
            entry["verdict"] = {
                "traffic_source_ready": bool(entry["channels"]),
                "device_split_ready": bool(entry["devices"]),
                "funnel_ready": has_purchase,
                "cross_domain_booking_tracked": bool(entry["booking_engine_hosts"]),
                "conversion_source": (
                    "ga4_purchase" if has_purchase
                    else ("ga4_key_events" if (entry["totals"].get(conv_metric or "") or 0) > 0
                          else "none — needs a proxy event (outbound click to booking engine)")
                ),
            }
            entry["ok"] = not entry["errors"] or bool(entry["totals"])
            results.append(entry)

        return _api({
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "days": days,
            "properties": results,
        })
    except Exception as e:
        logger.exception("[ga4] diagnostics failed")
        return _api(error=str(e))
