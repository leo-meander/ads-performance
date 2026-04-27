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

    query = f"""
        SELECT
            segments.geo_target_country,
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
        geo_resource = row.segments.geo_target_country or ""
        criterion_id = geo_resource.split("/")[-1] if geo_resource else ""
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
