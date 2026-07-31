"""GA4 analytics router — diagnostics probe + the live /analytics endpoints.

Everything here reads the GA4 Data API live. No tables, no sync, no cron:
GA4 keeps 14 months of history and answers any dimension combination we ask
for, so storing a copy would only add staleness. Responses are memoised for
`_CACHE_TTL_SECONDS` so flipping between tabs doesn't re-bill the quota.

Two facts about our properties, established by the diagnostics probe on
2026-07-31, that shape every query below:

1. `hotels.cloudbeds.com` appears as a *hostname with its own sessions* in
   every property. Cross-domain measurement is on (purchases are visible)
   but the referral exclusion is incomplete, so a booking-engine hop can
   start a fresh session attributed to Referral. Channel-level conversion
   counts are therefore directional, not settlement-grade — ROAS still
   belongs to the ads platform + booking matches.
2. Property 514380737 (registered as Oani) is also tagged on the 1948 and
   Osaka sites, so its property-wide totals double-count those branches.
   That's why every endpoint accepts `host_scope` and why `site` scope
   exists: it pins a branch to its own subdomain.

Phase 0 (diagnostics): before building anything we needed to know, per
property, what GA4 actually measures:

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
import time
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

# ── host scoping ───────────────────────────────────────────────────────────
# Each branch owns exactly one subdomain. `staymeander.com` (the group site)
# is tagged into *every* property, so it is deliberately excluded from `site`
# scope — counting it per branch would multiply the same sessions five times.
BRANCH_SITE_HOSTS: dict[str, list[str]] = {
    "Saigon": ["sgn.staymeander.com"],
    "Taipei": ["tpe.staymeander.com"],
    "1948": ["1948.staymeander.com"],
    "Osaka": ["osk.staymeander.com"],
    "Oani": ["oani-taipei.staymeander.com"],
}

BOOKING_HOSTS = ["hotels.cloudbeds.com", "meander.cloudbeds.com", "api.cloudbeds.com"]

# Properties whose tag is deployed on more than one branch's site. Reported to
# the client so the page can warn instead of quietly showing inflated totals.
SHARED_PROPERTIES: dict[str, list[str]] = {
    "514380737": ["1948", "Osaka"],
}

# The funnel our sites actually emit. The generic GA4 retail steps
# (view_item / select_item / add_payment_info) are never fired by Cloudbeds,
# so using them would draw four empty bars. `cb_booking_engine_load` is the
# Cloudbeds widget booting — the real "entered the booking flow" moment.
SITE_FUNNEL = [
    {"event": "session_start", "label": "Sessions"},
    {"event": "cb_booking_engine_load", "label": "Booking engine opened"},
    {"event": "add_to_cart", "label": "Room selected"},
    {"event": "begin_checkout", "label": "Checkout started"},
    {"event": "purchase", "label": "Booking completed"},
]

_CACHE_TTL_SECONDS = 600
_cache: dict[str, tuple[float, Any]] = {}
_metadata_cache: dict[str, tuple[float, set[str]]] = {}
_METADATA_TTL_SECONDS = 3600


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


# ── analytics helpers ──────────────────────────────────────────────────────


def _cache_get(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL_SECONDS:
        return hit[1]
    return None


def _cache_put(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)
    # Bounded so a long-lived process can't grow the dict without limit.
    if len(_cache) > 200:
        oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:50]
        for k, _ in oldest:
            _cache.pop(k, None)


def _supported_metrics(property_id: str) -> set[str]:
    """Metric names this property accepts, cached for an hour.

    A property's metric list only changes when someone edits the GA4 config,
    so re-fetching it on every request would be pure latency.
    """
    hit = _metadata_cache.get(property_id)
    if hit and (time.monotonic() - hit[0]) < _METADATA_TTL_SECONDS:
        return hit[1]
    from app.services.ga4_client import get_metadata

    try:
        names = set(get_metadata(property_id).get("metrics") or [])
    except Exception:
        logger.warning("[ga4] metadata lookup failed for %s", property_id, exc_info=True)
        names = set()
    _metadata_cache[property_id] = (time.monotonic(), names)
    return names


def _resolve_branch_property(db: Session, branch: str) -> dict[str, Any] | None:
    """Canonical branch key → its GA4 property (or None if not configured)."""
    for prop in _configured_properties(db):
        if prop["branch"] == branch:
            return prop
    return None


def _host_filter(branch: str, host_scope: str) -> dict[str, Any] | None:
    """Build the hostName dimension filter for the requested scope.

    `all`     — everything the property sees. Correct for four of the five
                branches; inflated for a shared property (see SHARED_PROPERTIES).
    `site`    — the branch's own subdomain only. Excludes the booking engine,
                so conversions will be near-zero — this scope answers "how is
                my landing site doing", not "how many bookings".
    `booking` — the Cloudbeds hosts only.
    """
    hosts: list[str] = []
    if host_scope == "site":
        hosts = BRANCH_SITE_HOSTS.get(branch, [])
    elif host_scope == "booking":
        hosts = BOOKING_HOSTS
    if not hosts:
        return None
    return {"filter": {"field_name": "hostName", "in_list_filter": {"values": hosts}}}


# Cross-filter dimensions. Clicking a row on the page pins that value and every
# other section re-queries with it applied — the same "one segment, all charts"
# behaviour as a Looker Studio cross-filter. Filtering has to happen at the API
# because each section is its own aggregation; you cannot intersect pre-summed
# rows client-side.
SEGMENT_DIMENSIONS: dict[str, str] = {
    "device": "deviceCategory",
    "channel": "sessionDefaultChannelGroup",
    "source": "sessionSource",
    "medium": "sessionMedium",
    "campaign": "sessionCampaignName",
    "country": "country",
    "landing_page": "landingPage",
    "host": "hostName",
}


def _combined_filter(
    branch: str, host_scope: str, segments: dict[str, str]
) -> dict[str, Any] | None:
    """AND together the host scope and every pinned segment."""
    expressions: list[dict[str, Any]] = []

    host = _host_filter(branch, host_scope)
    if host:
        expressions.append(host)

    for key, value in segments.items():
        field = SEGMENT_DIMENSIONS.get(key)
        if not field or value in (None, ""):
            continue
        expressions.append({
            "filter": {
                "field_name": field,
                "string_filter": {"match_type": "EXACT", "value": value},
            }
        })

    if not expressions:
        return None
    if len(expressions) == 1:
        return expressions[0]
    return {"and_group": {"expressions": expressions}}


def _window(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Requested window, defaulting to the last 28 full days ending yesterday."""
    today = datetime.now(timezone.utc).date()
    end = date.fromisoformat(date_to) if date_to else today - timedelta(days=1)
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=27)
    if start > end:
        start, end = end, start
    return start, end


def _rate(numerator: float, denominator: float) -> float | None:
    return (numerator / denominator) if denominator else None


def _parse_ga4_date(s: str) -> date:
    """GA4 returns the `date` dimension as a YYYYMMDD string."""
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


class _Ctx:
    """Everything the section endpoints need, resolved once per request."""

    def __init__(self, db: Session, branch: str, date_from, date_to, host_scope: str,
                 segments: dict[str, str] | None = None):
        self.branch = branch
        self.prop = _resolve_branch_property(db, branch)
        self.date_from, self.date_to = _window(date_from, date_to)
        self.host_scope = host_scope
        self.segments = {k: v for k, v in (segments or {}).items() if v}
        self.filter = _combined_filter(branch, host_scope, self.segments)
        self.property_id = self.prop["property_id"] if self.prop else None
        supported = _supported_metrics(self.property_id) if self.property_id else set()
        self.conv = _pick_supported(CONVERSION_METRIC_CANDIDATES, supported) or "keyEvents"
        self.rev = _pick_supported(REVENUE_METRIC_CANDIDATES, supported) or "purchaseRevenue"

    @property
    def shared_with(self) -> list[str]:
        return SHARED_PROPERTIES.get(self.property_id or "", [])

    def key(self, section: str, *extra: Any) -> str:
        seg = ",".join(f"{k}={v}" for k, v in sorted(self.segments.items()))
        return "|".join([
            section, self.property_id or "-", self.branch, self.host_scope, seg,
            self.date_from.isoformat(), self.date_to.isoformat(), *[str(e) for e in extra],
        ])

    def run(self, dimensions: list[str], metrics: list[str], *, limit: int = 100,
            date_from: date | None = None, date_to: date | None = None) -> list[dict]:
        from app.services.ga4_client import run_report

        return run_report(
            self.property_id,
            date_from=date_from or self.date_from,
            date_to=date_to or self.date_to,
            dimensions=dimensions,
            metrics=metrics,
            dimension_filter=self.filter,
            limit=limit,
        )

    def envelope(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "property_id": self.property_id,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "host_scope": self.host_scope,
            "conversion_metric": self.conv,
            "shared_property_with": self.shared_with,
            "segments": self.segments,
            **payload,
        }


def _ctx_or_error(db: Session, branch: str, date_from, date_to, host_scope: str,
                  segments: dict[str, str] | None = None):
    """Returns (ctx, error_response). Exactly one of the two is None."""
    if host_scope not in ("all", "site", "booking"):
        return None, _api(error="host_scope must be one of: all, site, booking")
    ctx = _Ctx(db, branch, date_from, date_to, host_scope, segments)
    if not ctx.property_id:
        return None, _api(error=f"No GA4 property configured for branch '{branch}'")
    return ctx, None


def _enrich(rows: list[dict], ctx: _Ctx, key_field: str, label: str,
            carry: dict[str, str] | None = None) -> list[dict]:
    """Attach derived rates to a breakdown, sorted by sessions desc.

    Conversion rate and revenue-per-session are computed here rather than in
    the frontend so every table derives them the same way — from raw sums,
    never by averaging pre-computed rates.
    """
    out = []
    for r in rows:
        sessions = r.get("sessions", 0) or 0
        conv = r.get(ctx.conv, 0) or 0
        rev = r.get(ctx.rev, 0) or 0
        out.append({
            label: r.get(key_field, ""),
            # Raw dimension values the page needs to build a cross-filter from
            # a row the user clicks (a "source / medium" label can't be split
            # reliably — the source itself may contain a slash).
            **{out_key: r.get(in_key, "") for out_key, in_key in (carry or {}).items()},
            "sessions": sessions,
            "engaged_sessions": r.get("engagedSessions", 0) or 0,
            "engagement_rate": r.get("engagementRate"),
            "key_events": conv,
            "revenue": rev,
            "conversion_rate": _rate(conv, sessions),
            "revenue_per_session": _rate(rev, sessions),
        })
    out.sort(key=lambda r: r["sessions"], reverse=True)
    return out


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


# ── /analytics page sections ───────────────────────────────────────────────
# Five endpoints instead of one so the page can fetch them in parallel — a
# single combined call would serialise ~12 GA4 reports behind one spinner.

_COMMON = dict(
    branch=Query(..., description="Canonical branch key, e.g. Saigon / Taipei / 1948 / Osaka / Oani"),
    date_from=Query(None, description="ISO date. Defaults to 28 days before date_to."),
    date_to=Query(None, description="ISO date. Defaults to yesterday (GA4 finalization delay)."),
    host_scope=Query("all", description="all | site | booking"),
)


def segment_params(
    device: str | None = Query(None, description="deviceCategory, e.g. mobile"),
    channel: str | None = Query(None, description="sessionDefaultChannelGroup, e.g. Paid Social"),
    source: str | None = Query(None, description="sessionSource"),
    medium: str | None = Query(None, description="sessionMedium"),
    campaign: str | None = Query(None, description="sessionCampaignName"),
    country: str | None = Query(None),
    landing_page: str | None = Query(None, description="landingPage path"),
    host: str | None = Query(None, description="hostName"),
) -> dict[str, str]:
    """Cross-filter segment, shared by every section endpoint.

    Each value is ANDed into the dimension filter of every report, so pinning
    one row on the page narrows all the others to that slice.
    """
    raw = {
        "device": device, "channel": channel, "source": source, "medium": medium,
        "campaign": campaign, "country": country, "landing_page": landing_page, "host": host,
    }
    return {k: v for k, v in raw.items() if v}


@router.get("/ga4/overview")
def ga4_overview(
    branch: str = _COMMON["branch"],
    date_from: str | None = _COMMON["date_from"],
    date_to: str | None = _COMMON["date_to"],
    host_scope: str = _COMMON["host_scope"],
    compare: bool = Query(True, description="Also return the preceding equal-length period"),
    segments: dict = Depends(segment_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Headline KPIs + daily trend, with an optional previous-period delta."""
    try:
        ctx, err = _ctx_or_error(db, branch, date_from, date_to, host_scope, segments)
        if err:
            return err

        cache_key = ctx.key("overview", compare)
        cached = _cache_get(cache_key)
        if cached is not None:
            return _api(cached)

        totals_metrics = [
            "sessions", "activeUsers", "newUsers", "screenPageViews",
            "engagedSessions", "engagementRate", "averageSessionDuration",
            "bounceRate", ctx.conv, ctx.rev,
        ]
        totals_rows = ctx.run([], totals_metrics)
        totals = totals_rows[0] if totals_rows else {}

        sessions = totals.get("sessions", 0) or 0
        conv = totals.get(ctx.conv, 0) or 0
        rev = totals.get(ctx.rev, 0) or 0
        summary = {
            "sessions": sessions,
            "active_users": totals.get("activeUsers", 0),
            "new_users": totals.get("newUsers", 0),
            "page_views": totals.get("screenPageViews", 0),
            "engaged_sessions": totals.get("engagedSessions", 0),
            "engagement_rate": totals.get("engagementRate"),
            "avg_session_duration_sec": totals.get("averageSessionDuration"),
            "bounce_rate": totals.get("bounceRate"),
            "key_events": conv,
            "revenue": rev,
            "conversion_rate": _rate(conv, sessions),
            "revenue_per_session": _rate(rev, sessions),
        }

        previous = None
        if compare:
            span = (ctx.date_to - ctx.date_from).days + 1
            prev_to = ctx.date_from - timedelta(days=1)
            prev_from = prev_to - timedelta(days=span - 1)
            prev_rows = ctx.run([], totals_metrics, date_from=prev_from, date_to=prev_to)
            prev = prev_rows[0] if prev_rows else {}
            p_sessions = prev.get("sessions", 0) or 0
            p_conv = prev.get(ctx.conv, 0) or 0
            p_rev = prev.get(ctx.rev, 0) or 0
            previous = {
                "date_from": prev_from.isoformat(),
                "date_to": prev_to.isoformat(),
                "sessions": p_sessions,
                "active_users": prev.get("activeUsers", 0),
                "key_events": p_conv,
                "revenue": p_rev,
                "conversion_rate": _rate(p_conv, p_sessions),
                "revenue_per_session": _rate(p_rev, p_sessions),
                "engagement_rate": prev.get("engagementRate"),
            }

        trend_rows = ctx.run(["date"], ["sessions", "activeUsers", ctx.conv, ctx.rev], limit=400)
        trend = sorted(
            (
                {
                    "date": _parse_ga4_date(r["date"]).isoformat(),
                    "sessions": r.get("sessions", 0),
                    "active_users": r.get("activeUsers", 0),
                    "key_events": r.get(ctx.conv, 0),
                    "revenue": r.get(ctx.rev, 0),
                }
                for r in trend_rows if r.get("date")
            ),
            key=lambda r: r["date"],
        )

        payload = ctx.envelope({"summary": summary, "previous": previous, "trend": trend})
        _cache_put(cache_key, payload)
        return _api(payload)
    except Exception as e:
        logger.exception("[ga4] overview failed")
        return _api(error=str(e))


@router.get("/ga4/acquisition")
def ga4_acquisition(
    branch: str = _COMMON["branch"],
    date_from: str | None = _COMMON["date_from"],
    date_to: str | None = _COMMON["date_to"],
    host_scope: str = _COMMON["host_scope"],
    segments: dict = Depends(segment_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Where traffic comes from: channel group, source/medium, campaign."""
    try:
        ctx, err = _ctx_or_error(db, branch, date_from, date_to, host_scope, segments)
        if err:
            return err

        cache_key = ctx.key("acquisition")
        cached = _cache_get(cache_key)
        if cached is not None:
            return _api(cached)

        breakdown_metrics = ["sessions", "engagedSessions", "engagementRate", ctx.conv, ctx.rev]

        channels = _enrich(
            ctx.run(["sessionDefaultChannelGroup"], breakdown_metrics, limit=50),
            ctx, "sessionDefaultChannelGroup", "channel",
        )

        sm_rows = ctx.run(["sessionSource", "sessionMedium"], breakdown_metrics, limit=200)
        sources = _enrich(
            [{**r, "_sm": f"{r.get('sessionSource', '')} / {r.get('sessionMedium', '')}"} for r in sm_rows],
            ctx, "_sm", "source_medium",
            carry={"source": "sessionSource", "medium": "sessionMedium"},
        )[:30]

        campaigns = _enrich(
            ctx.run(["sessionCampaignName"], breakdown_metrics, limit=100),
            ctx, "sessionCampaignName", "campaign",
        )[:30]

        # Self-referral check: booking-engine hosts showing up as a traffic
        # *source* means the cross-domain referral exclusion is leaking, and
        # channel-level conversion credit is being stolen from the real source.
        leaked = [
            s for s in sources
            if any(hint in (s["source_medium"] or "").lower() for hint in BOOKING_ENGINE_HINTS)
        ]

        payload = ctx.envelope({
            "channels": channels,
            "sources": sources,
            "campaigns": campaigns,
            "self_referral": {
                "detected": bool(leaked),
                "rows": leaked,
                "note": (
                    "Booking-engine hosts appear as a traffic source. GA4 is "
                    "starting a new session on the Cloudbeds hop, so these "
                    "conversions were really earned by the original channel."
                ) if leaked else None,
            },
        })
        _cache_put(cache_key, payload)
        return _api(payload)
    except Exception as e:
        logger.exception("[ga4] acquisition failed")
        return _api(error=str(e))


@router.get("/ga4/devices")
def ga4_devices(
    branch: str = _COMMON["branch"],
    date_from: str | None = _COMMON["date_from"],
    date_to: str | None = _COMMON["date_to"],
    host_scope: str = _COMMON["host_scope"],
    segments: dict = Depends(segment_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Mobile vs desktop vs tablet — and the same split crossed with channel."""
    try:
        ctx, err = _ctx_or_error(db, branch, date_from, date_to, host_scope, segments)
        if err:
            return err

        cache_key = ctx.key("devices")
        cached = _cache_get(cache_key)
        if cached is not None:
            return _api(cached)

        devices = _enrich(
            ctx.run(
                ["deviceCategory"],
                ["sessions", "engagedSessions", "engagementRate", ctx.conv, ctx.rev],
                limit=10,
            ),
            ctx, "deviceCategory", "device",
        )

        # Revenue per session is the honest comparator here: mobile always
        # wins on volume, so raw session share says nothing about which
        # device actually books.
        best = max(
            (d for d in devices if d["sessions"]),
            key=lambda d: d["revenue_per_session"] or 0,
            default=None,
        )
        mobile = next((d for d in devices if d["device"] == "mobile"), None)
        desktop = next((d for d in devices if d["device"] == "desktop"), None)
        ratio = None
        if mobile and desktop and (mobile["revenue_per_session"] or 0) > 0:
            ratio = (desktop["revenue_per_session"] or 0) / mobile["revenue_per_session"]

        matrix_rows = ctx.run(
            ["deviceCategory", "sessionDefaultChannelGroup"],
            ["sessions", ctx.conv, ctx.rev],
            limit=200,
        )
        matrix = [
            {
                "device": r.get("deviceCategory", ""),
                "channel": r.get("sessionDefaultChannelGroup", ""),
                "sessions": r.get("sessions", 0),
                "key_events": r.get(ctx.conv, 0),
                "revenue": r.get(ctx.rev, 0),
                "conversion_rate": _rate(r.get(ctx.conv, 0) or 0, r.get("sessions", 0) or 0),
            }
            for r in matrix_rows
        ]
        matrix.sort(key=lambda r: r["sessions"], reverse=True)

        payload = ctx.envelope({
            "devices": devices,
            "device_channel_matrix": matrix,
            "verdict": {
                "best_revenue_per_session": best["device"] if best else None,
                "desktop_vs_mobile_rps_ratio": ratio,
            },
        })
        _cache_put(cache_key, payload)
        return _api(payload)
    except Exception as e:
        logger.exception("[ga4] devices failed")
        return _api(error=str(e))


@router.get("/ga4/funnel")
def ga4_funnel(
    branch: str = _COMMON["branch"],
    date_from: str | None = _COMMON["date_from"],
    date_to: str | None = _COMMON["date_to"],
    host_scope: str = _COMMON["host_scope"],
    segments: dict = Depends(segment_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Booking funnel, overall and per device.

    NOTE: the GA4 Data API exposes no sequential-funnel report — Explorations
    are UI-only. These are independent per-step event counts, so a step can
    exceed the one above it (a user reopening the booking engine, for
    instance). Read the drop-off as a ratio, not as a strict path.
    """
    try:
        ctx, err = _ctx_or_error(db, branch, date_from, date_to, host_scope, segments)
        if err:
            return err

        cache_key = ctx.key("funnel")
        cached = _cache_get(cache_key)
        if cached is not None:
            return _api(cached)

        wanted = [s["event"] for s in SITE_FUNNEL]
        rows = ctx.run(["eventName"], ["eventCount", "totalUsers"], limit=300)
        by_event = {r.get("eventName", ""): r for r in rows}

        steps: list[dict[str, Any]] = []
        first_users = None
        prev_users = None
        for spec in SITE_FUNNEL:
            r = by_event.get(spec["event"], {})
            users = r.get("totalUsers", 0) or 0
            count = r.get("eventCount", 0) or 0
            if first_users is None:
                first_users = users
            steps.append({
                "event": spec["event"],
                "label": spec["label"],
                "users": users,
                "count": count,
                "pct_of_top": _rate(users, first_users or 0),
                "step_conversion": _rate(users, prev_users) if prev_users else None,
                "dropoff": (1 - (users / prev_users)) if prev_users else None,
                "present": count > 0,
            })
            prev_users = users if users else prev_users

        device_rows = ctx.run(["eventName", "deviceCategory"], ["eventCount", "totalUsers"], limit=500)
        per_device: dict[str, dict[str, int]] = {}
        for r in device_rows:
            ev = r.get("eventName", "")
            if ev not in wanted:
                continue
            per_device.setdefault(r.get("deviceCategory", ""), {})[ev] = r.get("totalUsers", 0) or 0

        by_device = [
            {
                "device": dev,
                "steps": [
                    {"event": s["event"], "label": s["label"], "users": counts.get(s["event"], 0)}
                    for s in SITE_FUNNEL
                ],
                "top_to_purchase": _rate(
                    counts.get("purchase", 0), counts.get("session_start", 0)
                ),
            }
            for dev, counts in sorted(
                per_device.items(),
                key=lambda kv: kv[1].get("session_start", 0),
                reverse=True,
            )
        ]

        # Everything else the property emits, so a new event someone adds in
        # GTM shows up here instead of being silently invisible.
        other_events = sorted(
            (
                {"event": r.get("eventName", ""), "count": r.get("eventCount", 0),
                 "users": r.get("totalUsers", 0)}
                for r in rows if r.get("eventName") not in wanted
            ),
            key=lambda r: r["count"], reverse=True,
        )[:40]

        payload = ctx.envelope({
            "steps": steps,
            "by_device": by_device,
            "other_events": other_events,
            "caveat": (
                "Independent event counts, not a sequential funnel — the GA4 "
                "Data API has no Explorations endpoint."
            ),
        })
        _cache_put(cache_key, payload)
        return _api(payload)
    except Exception as e:
        logger.exception("[ga4] funnel failed")
        return _api(error=str(e))


@router.get("/ga4/pages")
def ga4_pages(
    branch: str = _COMMON["branch"],
    date_from: str | None = _COMMON["date_from"],
    date_to: str | None = _COMMON["date_to"],
    host_scope: str = _COMMON["host_scope"],
    segments: dict = Depends(segment_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_section("analytics")),
):
    """Top landing pages, countries, and the hostname split.

    The hostname table is not decoration: it is how you catch a property
    whose tag is deployed on another branch's site.
    """
    try:
        ctx, err = _ctx_or_error(db, branch, date_from, date_to, host_scope, segments)
        if err:
            return err

        cache_key = ctx.key("pages")
        cached = _cache_get(cache_key)
        if cached is not None:
            return _api(cached)

        metrics = ["sessions", "engagedSessions", "engagementRate", ctx.conv, ctx.rev]

        pages = _enrich(ctx.run(["landingPage"], metrics, limit=200), ctx, "landingPage", "page")[:30]
        countries = _enrich(ctx.run(["country"], metrics, limit=200), ctx, "country", "country")[:30]
        hosts = _enrich(ctx.run(["hostName"], metrics, limit=100), ctx, "hostName", "host")

        own = set(BRANCH_SITE_HOSTS.get(ctx.branch, []))
        foreign = [
            h for h in hosts
            if h["host"] not in own
            and not any(b in h["host"] for b in BOOKING_ENGINE_HINTS)
            and any(
                other_host in h["host"]
                for b, other_hosts in BRANCH_SITE_HOSTS.items() if b != ctx.branch
                for other_host in other_hosts
            )
        ]

        payload = ctx.envelope({
            "pages": pages,
            "countries": countries,
            "hosts": hosts,
            "foreign_branch_hosts": foreign,
        })
        _cache_put(cache_key, payload)
        return _api(payload)
    except Exception as e:
        logger.exception("[ga4] pages failed")
        return _api(error=str(e))
