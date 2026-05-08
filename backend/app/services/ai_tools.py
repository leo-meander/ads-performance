"""AI tool definitions for the chatbot.

These tools let Claude pull live hotel + ads data on-demand instead of
receiving a single pre-baked context dump. Each tool is one round-trip to
either the HID public API (via pms_client) or the local ads-platform DB.

The tools are organised around the 6-step recommendation framework:

    1. Lead time per country         → get_lead_time
    2. Target stay period            → get_target_period
    3. Occupancy + KPI achievement   → get_branch_metrics, get_kpi_achievement
    4. Holidays / demand drivers     → get_demand_drivers
    5. Current campaign setup        → get_campaign_setup, get_ad_performance,
                                       get_country_intel, get_ota_mix
    6. Optimization recommendations  → Claude composes from the above

`TOOLS` is the list passed to the Anthropic API; `execute_tool()` is the
dispatcher called from the multi-turn chat loop.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.keypoint import BranchKeypoint
from app.models.metrics import MetricsCache
from app.services import pms_client

logger = logging.getLogger(__name__)


# ── Branch resolution ────────────────────────────────────────────────────────
# Branches live in two places: HID (canonical OCC/ADR data) and ads-platform
# (campaigns/ads/keypoints). We accept a fuzzy human name like "saigon" or
# "Meander Taipei" and resolve it to (hid_branch_id, ads_account_id) lazily.

_BRANCH_HID_CACHE: dict[str, dict] = {}  # normalised_name -> branch dict
_BRANCH_HID_CACHE_AT: datetime | None = None
_BRANCH_HID_CACHE_TTL_S = 300


def _normalise_branch_key(name: str) -> str:
    """Lowercase, strip 'meander', collapse whitespace — used for fuzzy match."""
    n = name.lower().strip()
    n = n.replace("meander", "").replace("hostel", "")
    return " ".join(n.split())


def _refresh_hid_branch_cache():
    """Pull /branches once and index by normalised name."""
    global _BRANCH_HID_CACHE, _BRANCH_HID_CACHE_AT
    rows = pms_client.fetch_branches()
    cache: dict[str, dict] = {}
    for b in rows:
        key = _normalise_branch_key(b.get("name", ""))
        if key:
            cache[key] = b
    _BRANCH_HID_CACHE = cache
    _BRANCH_HID_CACHE_AT = datetime.utcnow()


def _resolve_branch_hid(name: str | None) -> dict | None:
    """Return HID branch dict for a fuzzy name, or None if unspecified/unmatched."""
    if not name:
        return None
    cache_age = (
        (datetime.utcnow() - _BRANCH_HID_CACHE_AT).total_seconds()
        if _BRANCH_HID_CACHE_AT
        else 1e9
    )
    if cache_age > _BRANCH_HID_CACHE_TTL_S or not _BRANCH_HID_CACHE:
        _refresh_hid_branch_cache()
    key = _normalise_branch_key(name)
    if key in _BRANCH_HID_CACHE:
        return _BRANCH_HID_CACHE[key]
    # Fallback: substring match (e.g. "Taipei" matches "meander taipei")
    for k, v in _BRANCH_HID_CACHE.items():
        if key in k or k in key:
            return v
    return None


def _resolve_branch_ads(db: Session, name: str | None) -> AdAccount | None:
    """Return the ads-platform AdAccount whose account_name matches the fuzzy name."""
    if not name:
        return None
    key = _normalise_branch_key(name)
    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    for a in accounts:
        if _normalise_branch_key(a.account_name) == key:
            return a
    for a in accounts:
        ak = _normalise_branch_key(a.account_name)
        if key in ak or ak in key:
            return a
    return None


# ── Country resolution ───────────────────────────────────────────────────────
# Source-country names (from booking guests) map to ISO-2 codes used by the
# /lead-time and /holidays endpoints. We accept English / Vietnamese / native
# spellings to keep the chat forgiving.

_COUNTRY_ALIASES = {
    "vn": "VN", "vietnam": "VN", "viet nam": "VN", "việt nam": "VN", "viet": "VN",
    "tw": "TW", "taiwan": "TW", "đài loan": "TW", "dai loan": "TW",
    "jp": "JP", "japan": "JP", "nhat ban": "JP", "nhật bản": "JP",
    "kr": "KR", "korea": "KR", "south korea": "KR", "han quoc": "KR", "hàn quốc": "KR",
    "hk": "HK", "hong kong": "HK", "hồng kông": "HK", "hong kong sar": "HK",
    "sg": "SG", "singapore": "SG",
    "us": "US", "usa": "US", "united states": "US", "america": "US",
    "au": "AU", "australia": "AU",
    "cn": "CN", "china": "CN", "trung quoc": "CN", "trung quốc": "CN",
    "th": "TH", "thailand": "TH", "thai lan": "TH", "thái lan": "TH",
    "my": "MY", "malaysia": "MY",
    "ph": "PH", "philippines": "PH",
    "id": "ID", "indonesia": "ID",
    "in": "IN", "india": "IN", "an do": "IN", "ấn độ": "IN",
    "uk": "GB", "united kingdom": "GB", "britain": "GB", "england": "GB",
    "fr": "FR", "france": "FR",
    "de": "DE", "germany": "DE",
    "ca": "CA", "canada": "CA",
    "nz": "NZ", "new zealand": "NZ",
}


def _resolve_country_code(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if len(v) == 2:
        return v.upper()
    return _COUNTRY_ALIASES.get(v)


# ── Date helpers ─────────────────────────────────────────────────────────────

def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _today() -> date:
    return datetime.utcnow().date()


# ── Tool executors ───────────────────────────────────────────────────────────

def _tool_get_lead_time(db: Session, args: dict) -> dict:
    branch_name = args.get("branch")
    country = _resolve_country_code(args.get("country"))
    days_back = int(args.get("days_back") or 180)

    branch = _resolve_branch_hid(branch_name)
    branch_id = branch["id"] if branch else None

    result = pms_client.fetch_lead_time(
        branch_id=branch_id, country_code=country, days_back=days_back,
    )
    countries = result.get("countries", []) if isinstance(result, dict) else []
    # If a specific country was requested, surface its single row. If not,
    # return top 15 by sample count to keep the response model-friendly.
    if country:
        match = next((c for c in countries if c.get("country_code") == country), None)
        return {
            "branch": branch["name"] if branch else "All branches",
            "country_code": country,
            "lead_time": match,
            "days_back": days_back,
        }
    return {
        "branch": branch["name"] if branch else "All branches",
        "top_countries": countries[:15],
        "days_back": days_back,
    }


def _tool_get_target_period(db: Session, args: dict) -> dict:
    """Compute target stay window from lead time, per the framework:

        target_period = today + lead_time +/- buffer_days
    """
    branch_name = args.get("branch")
    country = _resolve_country_code(args.get("country"))
    if not country:
        return {"error": "country is required"}
    buffer_days = int(args.get("buffer_days") or 7)
    today = _parse_date(args.get("today")) or _today()

    branch = _resolve_branch_hid(branch_name)
    branch_id = branch["id"] if branch else None

    lt = pms_client.fetch_lead_time(
        branch_id=branch_id, country_code=country, days_back=180,
    )
    countries = lt.get("countries", []) if isinstance(lt, dict) else []
    match = next((c for c in countries if c.get("country_code") == country), None)
    if not match or match.get("avg_lead_days") is None:
        return {
            "error": f"No lead-time data for {country}"
                     + (f" at {branch['name']}" if branch else ""),
            "country_code": country,
        }

    avg_days = match["avg_lead_days"]
    median_days = match.get("median_lead_days")
    center = today + timedelta(days=int(round(avg_days)))
    return {
        "branch": branch["name"] if branch else "All branches",
        "country_code": country,
        "today": today.isoformat(),
        "avg_lead_days": avg_days,
        "median_lead_days": median_days,
        "samples": match.get("samples"),
        "buffer_days": buffer_days,
        "target_period_start": (center - timedelta(days=buffer_days)).isoformat(),
        "target_period_center": center.isoformat(),
        "target_period_end": (center + timedelta(days=buffer_days)).isoformat(),
    }


def _tool_get_branch_metrics(db: Session, args: dict) -> dict:
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name)
    if not branch:
        return {"error": f"Unknown branch: {branch_name!r}"}

    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if not date_to:
        date_to = _today()
    if not date_from:
        date_from = date_to - timedelta(days=29)

    rows = pms_client.fetch_daily_metrics(
        branch_id=branch["id"], date_from=date_from, date_to=date_to,
    )

    # Summarise: avg/min/max OCC + ADR + RevPAR — full daily array would
    # blow up the tool_result. Daily series is useful for trend questions
    # but the chat usually asks for a holistic read.
    occs = [r.get("occ_pct") for r in rows if r.get("occ_pct") is not None]
    adrs = [r.get("adr_native") for r in rows if r.get("adr_native") is not None]
    revpars = [r.get("revpar_native") for r in rows if r.get("revpar_native") is not None]
    revs = [r.get("revenue_native") for r in rows if r.get("revenue_native") is not None]

    return {
        "branch": branch["name"],
        "currency": branch.get("currency"),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "days": len(rows),
        "avg_occ_pct": round(sum(occs) / len(occs), 4) if occs else None,
        "min_occ_pct": min(occs) if occs else None,
        "max_occ_pct": max(occs) if occs else None,
        "avg_adr": round(sum(adrs) / len(adrs), 2) if adrs else None,
        "avg_revpar": round(sum(revpars) / len(revpars), 2) if revpars else None,
        "total_revenue_native": round(sum(revs), 2) if revs else 0,
        "daily": rows[-7:] if len(rows) > 7 else rows,  # last week for trend hints
    }


def _tool_get_country_intel(db: Session, args: dict) -> dict:
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name) if branch_name else None
    branch_id = branch["id"] if branch else None
    rows = pms_client.fetch_country_intel(branch_id=branch_id)
    return {"branches": rows, "scope": branch["name"] if branch else "All branches"}


def _tool_get_country_ranking(db: Session, args: dict) -> dict:
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name) if branch_name else None
    branch_id = branch["id"] if branch else None
    top_n = int(args.get("top_n") or 15)
    rows = pms_client.fetch_country_ranking(branch_id=branch_id, top_n=top_n)
    return {
        "branch": branch["name"] if branch else "All branches",
        "top_n": top_n,
        "countries": rows,
    }


def _tool_get_country_trend(db: Session, args: dict) -> dict:
    country = _resolve_country_code(args.get("country"))
    if not country:
        return {"error": "country is required"}
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name) if branch_name else None
    months = int(args.get("months") or 12)
    data = pms_client.fetch_country_trend(
        country_code=country,
        branch_id=branch["id"] if branch else None,
        months=months,
    )
    return data


def _tool_get_country_yoy(db: Session, args: dict) -> dict:
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name) if branch_name else None
    return pms_client.fetch_country_yoy_insights(
        year=args.get("year"),
        month=args.get("month"),
        branch_id=branch["id"] if branch else None,
        date_type=args.get("date_type") or "check_in",
    )


def _tool_get_demand_drivers(db: Session, args: dict) -> dict:
    """Pull holidays for the source country + local events at the branch city."""
    branch_name = args.get("branch")
    country = _resolve_country_code(args.get("country"))
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if not date_to:
        date_to = _today() + timedelta(days=60)
    if not date_from:
        date_from = _today()

    branch = _resolve_branch_hid(branch_name) if branch_name else None
    out: dict[str, Any] = {
        "branch": branch["name"] if branch else None,
        "city": branch.get("city") if branch else None,
        "country_code": country,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }

    # Local events at branch city
    try:
        out["local_events"] = pms_client.fetch_events(
            branch_id=branch["id"] if branch else None,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception:
        logger.exception("fetch_events failed")
        out["local_events"] = []

    # Source-country holidays — full calendar for the country (frequency cap to
    # the date window happens in Claude).
    if country:
        try:
            out["source_country_holidays"] = pms_client.fetch_country_holidays(country)
        except Exception:
            logger.exception("fetch_country_holidays failed")
            out["source_country_holidays"] = {}

    # Always include upcoming windows across all markets — useful for
    # "which countries are about to start booking?" questions.
    try:
        days_ahead = max((date_to - _today()).days, 1)
        out["upcoming_windows"] = pms_client.fetch_upcoming_holidays(days=min(days_ahead, 365))
    except Exception:
        logger.exception("fetch_upcoming_holidays failed")
        out["upcoming_windows"] = []

    return out


def _tool_get_kpi_achievement(db: Session, args: dict) -> dict:
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if not date_from or not date_to:
        return {"error": "date_from and date_to are required (YYYY-MM-DD)"}
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name) if branch_name else None
    rows = pms_client.fetch_kpi_achievement(
        date_from=date_from, date_to=date_to,
        branch_id=branch["id"] if branch else None,
    )
    return {
        "scope": branch["name"] if branch else "All branches",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "branches": rows,
    }


def _tool_get_ota_mix(db: Session, args: dict) -> dict:
    branch_name = args.get("branch")
    branch = _resolve_branch_hid(branch_name) if branch_name else None
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if not date_to:
        date_to = _today()
    if not date_from:
        date_from = date_to - timedelta(days=29)
    rows = pms_client.fetch_ota_mix(
        branch_id=branch["id"] if branch else None,
        date_from=date_from, date_to=date_to,
    )
    return {
        "scope": branch["name"] if branch else "All branches",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "channels": rows,
    }


# ── Local DB tools (ads-platform) ────────────────────────────────────────────

def _tool_get_campaign_setup(db: Session, args: dict) -> dict:
    """Pull the user's current ads setup for the branch — angles, keypoints,
    winning combos, active campaigns. This is the input to step 5 of the
    framework (review current campaign setup)."""
    branch_name = args.get("branch")
    account = _resolve_branch_ads(db, branch_name)
    if not account:
        return {"error": f"Unknown branch: {branch_name!r}"}

    country = _resolve_country_code(args.get("country"))
    ta = args.get("ta")
    funnel = args.get("funnel")
    platform = args.get("platform")  # meta | google | tiktok | None=all

    # Active campaigns matching filters
    cq = db.query(Campaign).filter(
        Campaign.account_id == account.id,
        Campaign.status == "ACTIVE",
    )
    if platform:
        cq = cq.filter(Campaign.platform == platform.lower())
    if ta:
        cq = cq.filter(Campaign.ta == ta)
    if funnel:
        cq = cq.filter(func.upper(Campaign.funnel_stage) == funnel.upper())

    # Country filter: Meta uses adset.country, Google uses campaign.country.
    # We OR-match: campaigns whose own country matches, or have an adset with
    # the country.
    campaigns = cq.order_by(Campaign.created_at.desc()).limit(40).all()
    if country:
        matched = []
        for c in campaigns:
            if c.country and c.country.upper() == country:
                matched.append(c)
                continue
            adset_match = (
                db.query(AdSet.id)
                .filter(
                    AdSet.campaign_id == c.id,
                    func.upper(AdSet.country) == country,
                )
                .first()
            )
            if adset_match:
                matched.append(c)
        campaigns = matched

    campaign_summary = [
        {
            "name": c.name,
            "platform": c.platform,
            "status": c.status,
            "ta": c.ta,
            "funnel_stage": c.funnel_stage,
            "country": c.country,
            "daily_budget": float(c.daily_budget) if c.daily_budget else None,
        }
        for c in campaigns[:25]
    ]

    # Angles (global to branch via memory rule + per-branch overrides)
    aq = db.query(AdAngle).filter(
        (AdAngle.branch_id == account.id) | (AdAngle.branch_id.is_(None))
    )
    if ta:
        aq = aq.filter(AdAngle.target_audience == ta)
    angles = aq.order_by(AdAngle.status.desc()).all()
    angle_summary = {
        "WIN": [], "TEST": [], "LOSE": [],
    }
    for a in angles:
        bucket = (a.status or "TEST").upper()
        if bucket not in angle_summary:
            continue
        if len(angle_summary[bucket]) >= 5:
            continue
        hooks = a.hook_examples or []
        angle_summary[bucket].append({
            "angle_id": a.angle_id,
            "angle_type": a.angle_type,
            "target_audience": a.target_audience,
            "explain": a.angle_explain,
            "hooks": hooks[:3] if isinstance(hooks, list) else [],
        })

    # Keypoints (selling points)
    keypoints = (
        db.query(BranchKeypoint)
        .filter(BranchKeypoint.branch_id == account.id, BranchKeypoint.is_active.is_(True))
        .all()
    )
    kp_by_cat: dict[str, list[str]] = {}
    for k in keypoints:
        kp_by_cat.setdefault(k.category, []).append(k.title)

    # Winning combos (top 5 by ROAS)
    combos_q = db.query(AdCombo).filter(
        AdCombo.branch_id == account.id,
        AdCombo.verdict == "WIN",
    )
    if ta:
        combos_q = combos_q.filter(AdCombo.target_audience == ta)
    if country:
        combos_q = combos_q.filter(func.upper(AdCombo.country) == country)
    winning_combos = (
        combos_q.order_by(AdCombo.roas.desc().nullslast()).limit(5).all()
    )
    combo_summary = [
        {
            "combo_id": c.combo_id,
            "ad_name": c.ad_name,
            "ta": c.target_audience,
            "country": c.country,
            "angle_id": c.angle_id,
            "roas": float(c.roas) if c.roas is not None else None,
            "ctr": float(c.ctr) if c.ctr is not None else None,
            "hook_rate": float(c.hook_rate) if c.hook_rate is not None else None,
            "spend": float(c.spend) if c.spend is not None else None,
            "conversions": c.conversions,
        }
        for c in winning_combos
    ]

    return {
        "branch": account.account_name,
        "filters": {
            "country": country, "ta": ta, "funnel": funnel, "platform": platform,
        },
        "active_campaigns": campaign_summary,
        "active_campaign_count": len(campaigns),
        "angles": angle_summary,
        "keypoints_by_category": kp_by_cat,
        "winning_combos": combo_summary,
    }


def _tool_get_ad_performance(db: Session, args: dict) -> dict:
    """Aggregate MetricsCache rows by branch + filters for the date window.

    Returns spend / impressions / clicks / conversions / revenue / ROAS / CTR /
    CPA. Country/TA/funnel filters fall through to AdSet / Campaign as
    appropriate."""
    branch_name = args.get("branch")
    account = _resolve_branch_ads(db, branch_name)
    if not account:
        return {"error": f"Unknown branch: {branch_name!r}"}
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))
    if not date_to:
        date_to = _today()
    if not date_from:
        date_from = date_to - timedelta(days=29)

    country = _resolve_country_code(args.get("country"))
    ta = args.get("ta")
    funnel = args.get("funnel")
    platform = args.get("platform")

    q = (
        db.query(
            func.coalesce(func.sum(MetricsCache.spend), 0).label("spend"),
            func.coalesce(func.sum(MetricsCache.impressions), 0).label("impressions"),
            func.coalesce(func.sum(MetricsCache.clicks), 0).label("clicks"),
            func.coalesce(func.sum(MetricsCache.conversions), 0).label("conversions"),
            func.coalesce(func.sum(MetricsCache.revenue), 0).label("revenue"),
        )
        .join(Campaign, Campaign.id == MetricsCache.campaign_id)
        .filter(
            Campaign.account_id == account.id,
            MetricsCache.date >= date_from,
            MetricsCache.date <= date_to,
        )
    )
    if platform:
        q = q.filter(MetricsCache.platform == platform.lower())
    if ta:
        q = q.filter(Campaign.ta == ta)
    if funnel:
        q = q.filter(func.upper(Campaign.funnel_stage) == funnel.upper())
    if country:
        q = (
            q.outerjoin(AdSet, AdSet.id == MetricsCache.ad_set_id)
            .filter(
                (func.upper(AdSet.country) == country)
                | (func.upper(Campaign.country) == country)
            )
        )

    row = q.one()
    spend = float(row.spend or 0)
    revenue = float(row.revenue or 0)
    clicks = int(row.clicks or 0)
    impressions = int(row.impressions or 0)
    conversions = int(row.conversions or 0)
    return {
        "branch": account.account_name,
        "currency": account.currency,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "filters": {
            "country": country, "ta": ta, "funnel": funnel, "platform": platform,
        },
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "revenue": revenue,
        "roas": round(revenue / spend, 4) if spend > 0 else None,
        "ctr": round(clicks / impressions, 6) if impressions > 0 else None,
        "cpa": round(spend / conversions, 2) if conversions > 0 else None,
        "cpc": round(spend / clicks, 2) if clicks > 0 else None,
    }


# ── Tool registry ────────────────────────────────────────────────────────────

_EXECUTORS = {
    "get_lead_time": _tool_get_lead_time,
    "get_target_period": _tool_get_target_period,
    "get_branch_metrics": _tool_get_branch_metrics,
    "get_country_intel": _tool_get_country_intel,
    "get_country_ranking": _tool_get_country_ranking,
    "get_country_trend": _tool_get_country_trend,
    "get_country_yoy": _tool_get_country_yoy,
    "get_demand_drivers": _tool_get_demand_drivers,
    "get_kpi_achievement": _tool_get_kpi_achievement,
    "get_ota_mix": _tool_get_ota_mix,
    "get_campaign_setup": _tool_get_campaign_setup,
    "get_ad_performance": _tool_get_ad_performance,
}


# Anthropic tool schemas — keep descriptions short but specific so the model
# picks the right tool. Branch names accept fuzzy strings ("saigon", "Meander
# Taipei", "1948"). Country accepts ISO-2 ("VN") or English/Vietnamese names.

_BRANCH_DESC = (
    "Branch name. Accepts fuzzy match: 'saigon', 'taipei', '1948', 'oani', "
    "'osaka', 'bread', or full 'Meander Saigon'. Omit for all branches."
)
_COUNTRY_DESC = (
    "Source country (where the guest comes from). Accepts ISO-2 code "
    "('VN','TW','JP','KR','HK') or name ('Vietnam','Taiwan','Đài Loan')."
)

TOOLS: list[dict] = [
    {
        "name": "get_lead_time",
        "description": (
            "Average + median booking lead time per source country, computed "
            "from past reservations. Use this to figure out how far ahead a "
            "given market books — input to target stay period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "country": {"type": "string", "description": _COUNTRY_DESC},
                "days_back": {
                    "type": "integer",
                    "description": "Window of past reservations to sample (30-730).",
                    "default": 180,
                },
            },
        },
    },
    {
        "name": "get_target_period",
        "description": (
            "Compute the target stay window for ads aimed at a country: "
            "today + lead_time +/- buffer_days. Returns start/center/end "
            "dates. Use as the first step before checking OCC and holidays."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "country": {"type": "string", "description": _COUNTRY_DESC},
                "today": {"type": "string", "description": "YYYY-MM-DD; defaults to today."},
                "buffer_days": {
                    "type": "integer", "default": 7,
                    "description": "Buffer either side of the lead-time center.",
                },
            },
            "required": ["country"],
        },
    },
    {
        "name": "get_branch_metrics",
        "description": (
            "Daily OCC, ADR, RevPAR, revenue for a branch over a date range. "
            "Returns averages + last-7-day series. Use for step 3 of the "
            "framework: check occupancy during the target stay period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["branch"],
        },
    },
    {
        "name": "get_country_intel",
        "description": (
            "Per-branch country intelligence: top countries by volume + "
            "growth, KOL coverage, current Ads coverage (running/stopped/none), "
            "government visitor forecast for the next 2 months, room-type "
            "stats. Single richest source for step 5 of the framework."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
            },
        },
    },
    {
        "name": "get_country_ranking",
        "description": (
            "Country potential ranking with Hot/Warm/Cold tiers, sorted by a "
            "composite score (recent bookings + WoW/MoM growth)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "top_n": {"type": "integer", "default": 15},
            },
        },
    },
    {
        "name": "get_country_trend",
        "description": (
            "Monthly booking count + revenue trend for a specific country "
            "over the past N months."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": _COUNTRY_DESC},
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "months": {"type": "integer", "default": 12},
            },
            "required": ["country"],
        },
    },
    {
        "name": "get_country_yoy",
        "description": (
            "Country YoY comparison: nights / revenue / guests this year vs "
            "previous year for a given month."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "year": {"type": "integer"},
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "date_type": {
                    "type": "string", "enum": ["check_in", "booked"],
                    "description": "Group by check-in date (default) or booking date.",
                },
            },
        },
    },
    {
        "name": "get_demand_drivers",
        "description": (
            "Holidays in the source country + local events at the branch "
            "city, within a date range. Use for step 4: check holidays / "
            "long weekends / festivals that lift demand."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "country": {"type": "string", "description": _COUNTRY_DESC + " — for source-country holidays."},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "get_kpi_achievement",
        "description": (
            "Revenue actual vs target for a date range, per branch. Use to "
            "judge whether the branch is on/ahead/behind plan during the "
            "target stay period — feeds the budget allocation decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "get_ota_mix",
        "description": (
            "Channel mix — Direct vs each OTA (Booking, Agoda, Expedia ...) "
            "by booking count and revenue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "get_campaign_setup",
        "description": (
            "Current ads setup for a branch: active campaigns, ad angles "
            "(WIN/TEST/LOSE), keypoints by category, top winning combos. "
            "Filters by country, target audience (Solo/Couple/Friend/Group/"
            "Business), funnel stage (TOF/MOF/BOF), platform "
            "(meta/google/tiktok). Use for step 5 of the framework."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "country": {"type": "string", "description": _COUNTRY_DESC},
                "ta": {
                    "type": "string",
                    "enum": ["Solo", "Couple", "Friend", "Group", "Business"],
                },
                "funnel": {"type": "string", "enum": ["TOF", "MOF", "BOF"]},
                "platform": {"type": "string", "enum": ["meta", "google", "tiktok"]},
            },
            "required": ["branch"],
        },
    },
    {
        "name": "get_ad_performance",
        "description": (
            "Aggregate ads performance for a branch over a date range: "
            "spend, impressions, clicks, conversions, revenue, ROAS, CTR, "
            "CPA, CPC. Same filters as get_campaign_setup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": _BRANCH_DESC},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "country": {"type": "string", "description": _COUNTRY_DESC},
                "ta": {
                    "type": "string",
                    "enum": ["Solo", "Couple", "Friend", "Group", "Business"],
                },
                "funnel": {"type": "string", "enum": ["TOF", "MOF", "BOF"]},
                "platform": {"type": "string", "enum": ["meta", "google", "tiktok"]},
            },
            "required": ["branch"],
        },
    },
]


def execute_tool(name: str, args: dict, db: Session) -> dict:
    """Dispatch a tool call to its executor. Errors are caught and returned
    as {"error": ...} so the chat loop can surface them to Claude without
    breaking the stream."""
    fn = _EXECUTORS.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(db, args or {})
    except Exception as exc:
        logger.exception("Tool %s failed with args=%s", name, args)
        return {"error": f"{type(exc).__name__}: {exc}"}
