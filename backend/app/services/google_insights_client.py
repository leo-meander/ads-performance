"""Realtime Google Ads insight queries.

Pulls per-campaign segmented metrics (search terms, device, location,
hour-of-day) directly from the Google Ads API for the insight panels on
PMax/Search detail pages. No DB persistence — each call hits GAQL.
"""

import logging
from datetime import date, timedelta
from typing import Any

from google.ads.googleads.errors import GoogleAdsException

from app.services.google_client import (
    _GEO_TARGET_TO_ISO2,
    _enum_name,
    _get_client,
    _micros_to_currency,
    _search_stream,
)

logger = logging.getLogger(__name__)


def _default_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=29)
    return date_from, date_to


def _row_to_metrics(m: Any) -> dict:
    spend = _micros_to_currency(m.cost_micros) or 0.0
    impressions = int(m.impressions or 0)
    clicks = int(m.clicks or 0)
    conversions = float(m.conversions or 0)
    revenue = float(m.conversions_value or 0)
    return {
        "spend": float(spend),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "revenue": revenue,
        "ctr": (clicks / impressions * 100) if impressions > 0 else 0.0,
        "cpc": (float(spend) / clicks) if clicks > 0 else None,
        "cpa": (float(spend) / conversions) if conversions > 0 else None,
        "cvr": (conversions / clicks * 100) if clicks > 0 else 0.0,
        "roas": (revenue / float(spend)) if spend > 0 else 0.0,
    }


# ── Search Terms (Search campaigns) ─────────────────────────


def fetch_search_terms(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch per-search-term metrics for a Search campaign.

    Returns the raw user query, match type, and aggregate metrics.
    """
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    query = f"""
        SELECT
            search_term_view.search_term,
            segments.search_term_match_type,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM search_term_view
        WHERE campaign.id = {platform_campaign_id}
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """

    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("search_term_view query failed for campaign %s", platform_campaign_id)
        raise

    # Aggregate by (term, match_type) — Google may return per-day rows
    bucket: dict[tuple, dict] = {}
    for row in rows:
        term = (row.search_term_view.search_term or "").strip().lower()
        if not term:
            continue
        match_type = _enum_name(row.segments.search_term_match_type)
        key = (term, match_type)
        m = _row_to_metrics(row.metrics)
        cur = bucket.setdefault(key, {
            "search_term": term, "match_type": match_type,
            "spend": 0.0, "impressions": 0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0,
        })
        cur["spend"] += m["spend"]
        cur["impressions"] += m["impressions"]
        cur["clicks"] += m["clicks"]
        cur["conversions"] += m["conversions"]
        cur["revenue"] += m["revenue"]

    results = []
    for v in bucket.values():
        clicks = v["clicks"]
        impr = v["impressions"]
        conv = v["conversions"]
        spend = v["spend"]
        v["ctr"] = (clicks / impr * 100) if impr > 0 else 0.0
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0.0
        v["cpc"] = (spend / clicks) if clicks > 0 else None
        v["cpa"] = (spend / conv) if conv > 0 else None
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0.0
        results.append(v)
    results.sort(key=lambda r: r["spend"], reverse=True)
    return results


def fetch_pmax_search_categories(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch PMax search-term insight categories.

    PMax doesn't expose raw search terms; campaign_search_term_insight gives
    bucketed category labels (e.g. "boutique hotels", "hostels saigon").
    """
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    query = f"""
        SELECT
            campaign_search_term_insight.category_label,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM campaign_search_term_insight
        WHERE campaign_search_term_insight.campaign_id = '{platform_campaign_id}'
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception(
            "campaign_search_term_insight failed for PMax campaign %s",
            platform_campaign_id,
        )
        return []  # silent fallback — view may be unavailable in some accounts

    bucket: dict[str, dict] = {}
    for row in rows:
        label = (row.campaign_search_term_insight.category_label or "Other").strip()
        cur = bucket.setdefault(label, {
            "category": label, "impressions": 0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0,
        })
        cur["impressions"] += int(row.metrics.impressions or 0)
        cur["clicks"] += int(row.metrics.clicks or 0)
        cur["conversions"] += float(row.metrics.conversions or 0)
        cur["revenue"] += float(row.metrics.conversions_value or 0)

    results = []
    for v in bucket.values():
        clicks = v["clicks"]
        impr = v["impressions"]
        conv = v["conversions"]
        v["ctr"] = (clicks / impr * 100) if impr > 0 else 0.0
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0.0
        results.append(v)
    results.sort(key=lambda r: r["impressions"], reverse=True)
    return results


# ── Device segmentation ─────────────────────────────────────


_DEVICE_LABEL = {
    "MOBILE": "Mobile", "DESKTOP": "Desktop", "TABLET": "Tablet",
    "CONNECTED_TV": "Connected TV", "OTHER": "Other",
}


def fetch_device_metrics(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    query = f"""
        SELECT
            segments.device,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM campaign
        WHERE campaign.id = {platform_campaign_id}
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("device segment query failed for campaign %s", platform_campaign_id)
        raise

    bucket: dict[str, dict] = {}
    for row in rows:
        dev = _enum_name(row.segments.device)
        m = _row_to_metrics(row.metrics)
        cur = bucket.setdefault(dev, {
            "device": _DEVICE_LABEL.get(dev, dev), "device_raw": dev,
            "spend": 0.0, "impressions": 0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0,
        })
        cur["spend"] += m["spend"]
        cur["impressions"] += m["impressions"]
        cur["clicks"] += m["clicks"]
        cur["conversions"] += m["conversions"]
        cur["revenue"] += m["revenue"]

    results = []
    for v in bucket.values():
        clicks = v["clicks"]
        impr = v["impressions"]
        conv = v["conversions"]
        spend = v["spend"]
        v["ctr"] = (clicks / impr * 100) if impr > 0 else 0.0
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0.0
        v["cpc"] = (spend / clicks) if clicks > 0 else None
        v["cpa"] = (spend / conv) if conv > 0 else None
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0.0
        results.append(v)
    results.sort(key=lambda r: r["spend"], reverse=True)
    return results


# ── Location (user country) ─────────────────────────────────


def fetch_location_metrics(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    # user_location_view = where the user PHYSICALLY is (geo quality), not the
    # targeted country. It is INCOMPATIBLE with segments.geo_target_country
    # (that segment only works on geographic_view). The country here comes from
    # user_location_view.country_criterion_id — a bare numeric ID, NOT a
    # "geoTargetConstants/<id>" resource name, so there is no path to split off.
    query = f"""
        SELECT
            user_location_view.country_criterion_id,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM user_location_view
        WHERE campaign.id = {platform_campaign_id}
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("user_location_view failed for campaign %s", platform_campaign_id)
        raise

    bucket: dict[str, dict] = {}
    for row in rows:
        criterion_id = str(row.user_location_view.country_criterion_id or "")
        country = _GEO_TARGET_TO_ISO2.get(criterion_id, criterion_id or "Unknown")
        m = _row_to_metrics(row.metrics)
        cur = bucket.setdefault(country, {
            "country": country, "spend": 0.0, "impressions": 0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0,
        })
        cur["spend"] += m["spend"]
        cur["impressions"] += m["impressions"]
        cur["clicks"] += m["clicks"]
        cur["conversions"] += m["conversions"]
        cur["revenue"] += m["revenue"]

    results = []
    for v in bucket.values():
        clicks = v["clicks"]
        impr = v["impressions"]
        conv = v["conversions"]
        spend = v["spend"]
        v["ctr"] = (clicks / impr * 100) if impr > 0 else 0.0
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0.0
        v["cpc"] = (spend / clicks) if clicks > 0 else None
        v["cpa"] = (spend / conv) if conv > 0 else None
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0.0
        results.append(v)
    results.sort(key=lambda r: r["spend"], reverse=True)
    return results


# ── Hour × Day-of-week ──────────────────────────────────────


_DAY_OF_WEEK_LABEL = {
    "MONDAY": "Mon", "TUESDAY": "Tue", "WEDNESDAY": "Wed",
    "THURSDAY": "Thu", "FRIDAY": "Fri", "SATURDAY": "Sat", "SUNDAY": "Sun",
}
_DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fetch_hourly_metrics(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Per-cell hour×day metrics. 168 cells max (7 days × 24 hours)."""
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    query = f"""
        SELECT
            segments.hour,
            segments.day_of_week,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM campaign
        WHERE campaign.id = {platform_campaign_id}
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("hourly segment query failed for campaign %s", platform_campaign_id)
        raise

    bucket: dict[tuple, dict] = {}
    for row in rows:
        hour = int(row.segments.hour or 0)
        dow_raw = _enum_name(row.segments.day_of_week)
        dow = _DAY_OF_WEEK_LABEL.get(dow_raw, dow_raw)
        key = (dow, hour)
        m = _row_to_metrics(row.metrics)
        cur = bucket.setdefault(key, {
            "day_of_week": dow, "hour": hour,
            "spend": 0.0, "impressions": 0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0,
        })
        cur["spend"] += m["spend"]
        cur["impressions"] += m["impressions"]
        cur["clicks"] += m["clicks"]
        cur["conversions"] += m["conversions"]
        cur["revenue"] += m["revenue"]

    results = []
    for v in bucket.values():
        clicks = v["clicks"]
        impr = v["impressions"]
        conv = v["conversions"]
        spend = v["spend"]
        v["ctr"] = (clicks / impr * 100) if impr > 0 else 0.0
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0.0
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0.0
        results.append(v)
    results.sort(key=lambda r: (_DAY_ORDER.index(r["day_of_week"]) if r["day_of_week"] in _DAY_ORDER else 99, r["hour"]))
    return results


# ── Audiences ───────────────────────────────────────────────


def fetch_audience_metrics(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch audience performance for Search/Display campaigns.

    ad_group_audience_view exposes per-audience metrics when audiences are
    attached at ad-group level (Observation or Targeting mode).
    PMax campaigns don't surface this — use fetch_pmax_audience_signals.
    """
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    query = f"""
        SELECT
            ad_group_criterion.criterion_id,
            ad_group_criterion.display_name,
            ad_group_criterion.type,
            ad_group_criterion.user_list.user_list,
            ad_group_criterion.user_interest.user_interest_category,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM ad_group_audience_view
        WHERE campaign.id = {platform_campaign_id}
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("ad_group_audience_view failed for %s", platform_campaign_id)
        return []

    bucket: dict[str, dict] = {}
    for row in rows:
        crit = row.ad_group_criterion
        crit_type = _enum_name(crit.type_) if crit.type_ else "UNKNOWN"
        display = crit.display_name or _audience_label_from_resource(crit)
        key = display or f"criterion_{crit.criterion_id}"
        m = _row_to_metrics(row.metrics)
        cur = bucket.setdefault(key, {
            "audience": display, "criterion_type": crit_type,
            "spend": 0.0, "impressions": 0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0,
        })
        cur["spend"] += m["spend"]
        cur["impressions"] += m["impressions"]
        cur["clicks"] += m["clicks"]
        cur["conversions"] += m["conversions"]
        cur["revenue"] += m["revenue"]

    results = []
    for v in bucket.values():
        clicks = v["clicks"]
        impr = v["impressions"]
        conv = v["conversions"]
        spend = v["spend"]
        v["ctr"] = (clicks / impr * 100) if impr > 0 else 0.0
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0.0
        v["cpc"] = (spend / clicks) if clicks > 0 else None
        v["cpa"] = (spend / conv) if conv > 0 else None
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0.0
        results.append(v)
    results.sort(key=lambda r: r["spend"], reverse=True)
    return results


def _audience_label_from_resource(crit: Any) -> str:
    """Best-effort label when display_name is empty."""
    if crit.user_list and crit.user_list.user_list:
        return f"Remarketing list {crit.user_list.user_list.split('/')[-1]}"
    if crit.user_interest and crit.user_interest.user_interest_category:
        return f"User interest {crit.user_interest.user_interest_category.split('/')[-1]}"
    return ""


def fetch_pmax_audience_signals(
    customer_id: str,
    platform_campaign_id: str,
) -> list[dict]:
    """List audience signals attached to PMax asset groups (no per-signal metrics).

    PMax doesn't expose per-signal performance — this just shows what's
    attached so the UI can flag PMAX_MISSING_AUDIENCE_SIGNAL.
    """
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = f"""
        SELECT
            asset_group_signal.audience,
            asset_group_signal.search_theme.text,
            asset_group.id,
            asset_group.name
        FROM asset_group_signal
        WHERE campaign.id = {platform_campaign_id}
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("asset_group_signal failed for PMax %s", platform_campaign_id)
        return []

    results = []
    for row in rows:
        ags = row.asset_group_signal
        audience_rn = ags.audience
        search_theme = ags.search_theme.text if ags.search_theme else None
        if audience_rn:
            results.append({
                "asset_group_id": str(row.asset_group.id),
                "asset_group_name": row.asset_group.name,
                "signal_type": "AUDIENCE",
                "value": audience_rn.split("/")[-1] if audience_rn else "",
            })
        elif search_theme:
            results.append({
                "asset_group_id": str(row.asset_group.id),
                "asset_group_name": row.asset_group.name,
                "signal_type": "SEARCH_THEME",
                "value": search_theme,
            })
    return results


# ── Placements (PMax / Display / Video) ─────────────────────


_PLACEMENT_TYPE_LABEL = {
    "WEBSITE": "Website",
    "MOBILE_APPLICATION": "Mobile app",
    "MOBILE_APP_CATEGORY": "Mobile app category",
    "YOUTUBE_VIDEO": "YouTube video",
    "YOUTUBE_CHANNEL": "YouTube channel",
    "GOOGLE_PRODUCTS": "Google products",
}


def fetch_placement_metrics(
    customer_id: str,
    platform_campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Where the ad served — apps, websites, YouTube channels.

    Available for PMax, Display, Video. Search campaigns return [].
    """
    customer_id = customer_id.replace("-", "")
    date_from, date_to = _default_range(date_from, date_to)
    client = _get_client()

    query = f"""
        SELECT
            detail_placement_view.placement,
            detail_placement_view.placement_type,
            detail_placement_view.display_name,
            detail_placement_view.target_url,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM detail_placement_view
        WHERE campaign.id = {platform_campaign_id}
            AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("detail_placement_view failed for %s", platform_campaign_id)
        return []

    results = []
    for row in rows:
        dpv = row.detail_placement_view
        placement = dpv.placement or ""
        ptype_raw = _enum_name(dpv.placement_type) if dpv.placement_type else "UNKNOWN"
        m = _row_to_metrics(row.metrics)
        results.append({
            "placement": placement,
            "display_name": dpv.display_name or placement,
            "target_url": dpv.target_url or "",
            "placement_type": _PLACEMENT_TYPE_LABEL.get(ptype_raw, ptype_raw),
            "placement_type_raw": ptype_raw,
            **{k: m[k] for k in ("spend", "impressions", "clicks", "conversions", "revenue", "ctr", "cvr", "cpc", "cpa", "roas")},
        })
    results.sort(key=lambda r: r["spend"], reverse=True)
    return results
