"""TikTok Ads (Marketing API v1.3) client.

Fetches advertisers, campaigns, ad groups, ads, and metrics from TikTok's
Business API. Pure HTTP wrapper — no DB access, no business logic.

Auth model: a single long-lived `TIKTOK_ACCESS_TOKEN` (set in env / Zeabur)
grants read access to every advertiser_id linked to that token. App ID +
Secret are only required for the advertiser-listing endpoint
(`oauth2/advertiser/get/`); other endpoints accept the token alone.

Platform separation: NO imports from meta_client.py or google_client.py.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)


_BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"
_PAGE_SIZE = 1000
_REQUEST_TIMEOUT = 60  # seconds


# Status normalisation: TikTok operation_status -> internal convention.
_STATUS_MAP = {
    "ENABLE": "ACTIVE",
    "DISABLE": "PAUSED",
    "DELETE": "ARCHIVED",
}


# Metrics requested at every report level. Mirrored across campaign / adgroup /
# ad data_levels so the upsert path treats every row the same.
#
# TikTok exposes pixel + onsite + offline + app totals via `total_*` columns,
# which is the unified deduped metric set (analogous to Meta's omni_*).
_REPORT_METRICS = [
    # --- spend / reach / engagement ---
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "frequency",
    # --- video funnel (TikTok native) ---
    "video_play_actions",
    "video_watched_2s",
    "video_watched_6s",
    "video_views_p25",
    "video_views_p50",
    "video_views_p75",
    "video_views_p100",
    # --- pixel/onsite/app/offline totals (deduped) ---
    "total_search",
    "total_add_to_cart",
    "total_initiate_checkout",
    "total_landing_page_view",
    "total_purchase",
    "total_purchase_value",
    "total_complete_payment",
    "total_complete_payment_value",
]


class TikTokAPIError(RuntimeError):
    """Raised when the TikTok API returns a non-zero error code."""


def _token() -> str:
    tok = settings.TIKTOK_ACCESS_TOKEN
    if not tok:
        raise TikTokAPIError("TIKTOK_ACCESS_TOKEN not configured")
    return tok


def _headers(token: str | None = None) -> dict:
    return {
        "Access-Token": token or _token(),
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict, token: str | None = None) -> dict:
    """GET request to TikTok API. Serialises array/object params to JSON
    strings (TikTok's required encoding) and unwraps the envelope."""
    url = f"{_BASE_URL}{path}"
    encoded: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, (list, dict)):
            encoded[k] = json.dumps(v, separators=(",", ":"))
        else:
            encoded[k] = v
    resp = requests.get(url, headers=_headers(token), params=encoded, timeout=_REQUEST_TIMEOUT)
    try:
        body = resp.json()
    except ValueError:
        raise TikTokAPIError(f"Non-JSON response from {path}: {resp.text[:300]}")

    code = body.get("code")
    if code != 0:
        msg = body.get("message", "unknown error")
        raise TikTokAPIError(f"TikTok API {path} returned code={code}: {msg}")
    return body.get("data") or {}


def _paginate(path: str, params: dict, token: str | None = None) -> list[dict]:
    """Walk through all pages of a list endpoint."""
    out: list[dict] = []
    page = 1
    while True:
        page_params = {**params, "page": page, "page_size": _PAGE_SIZE}
        data = _get(path, page_params, token=token)
        items = data.get("list") or []
        out.extend(items)
        info = data.get("page_info") or {}
        total_page = info.get("total_page") or 1
        if page >= total_page or not items:
            break
        page += 1
    return out


def _normalise_status(operation_status: str | None) -> str:
    if not operation_status:
        return "ACTIVE"
    return _STATUS_MAP.get(operation_status.upper(), operation_status.upper())


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        # TikTok returns "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD"
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- accounts ---


def list_advertisers() -> list[dict]:
    """Return advertiser_ids accessible to the configured access token.

    Requires TIKTOK_APP_ID + TIKTOK_APP_SECRET (the app the token belongs to).
    Without these, callers should add advertisers manually via
    `fetch_advertiser_info` once advertiser_ids are known.
    """
    if not settings.TIKTOK_APP_ID or not settings.TIKTOK_APP_SECRET:
        raise TikTokAPIError(
            "TIKTOK_APP_ID and TIKTOK_APP_SECRET must be set to discover "
            "advertisers — otherwise pass advertiser_ids manually to "
            "fetch_advertiser_info()."
        )
    data = _get(
        "/oauth2/advertiser/get/",
        {"app_id": settings.TIKTOK_APP_ID, "secret": settings.TIKTOK_APP_SECRET},
    )
    return data.get("list") or []


def fetch_advertiser_info(advertiser_ids: list[str]) -> list[dict]:
    """Return basic info (name, currency, timezone, status) for advertisers."""
    if not advertiser_ids:
        return []
    data = _get(
        "/advertiser/info/",
        {
            "advertiser_ids": [str(x) for x in advertiser_ids],
            "fields": [
                "id", "name", "currency", "timezone", "status",
                "advertiser_account_type", "company", "country",
            ],
        },
    )
    # `data` itself is a list under v1.3
    if isinstance(data, list):
        return data
    return data.get("list") or []


# --------------------------------------------------------------- campaigns ---


def fetch_campaigns(advertiser_id: str) -> list[dict]:
    """Pull every (non-deleted) campaign for an advertiser."""
    raw = _paginate(
        "/campaign/get/",
        {
            "advertiser_id": str(advertiser_id),
            "fields": [
                "campaign_id", "campaign_name", "objective_type", "operation_status",
                "secondary_status", "budget", "budget_mode", "schedule_start_time",
                "schedule_end_time", "create_time", "modify_time",
            ],
        },
    )
    out = []
    for c in raw:
        op = c.get("operation_status")
        if op == "DELETE":
            continue
        budget = c.get("budget") or 0
        budget_mode = c.get("budget_mode") or ""
        # TikTok budget_mode: BUDGET_MODE_DAY / BUDGET_MODE_TOTAL / BUDGET_MODE_INFINITE
        daily = float(budget) if "DAY" in budget_mode and budget else None
        lifetime = float(budget) if "TOTAL" in budget_mode and budget else None
        out.append({
            "platform_campaign_id": str(c.get("campaign_id")),
            "name": c.get("campaign_name") or "",
            "status": _normalise_status(op),
            "objective": c.get("objective_type"),
            "daily_budget": daily,
            "lifetime_budget": lifetime,
            "start_date": _parse_date(c.get("schedule_start_time")),
            "end_date": _parse_date(c.get("schedule_end_time")),
            "raw_data": c,
        })
    logger.info("Fetched %d TikTok campaigns for advertiser %s", len(out), advertiser_id)
    return out


def fetch_adgroups(advertiser_id: str) -> list[dict]:
    """Pull every (non-deleted) adgroup. Adgroups map to ad_sets in our schema."""
    raw = _paginate(
        "/adgroup/get/",
        {
            "advertiser_id": str(advertiser_id),
            "fields": [
                "adgroup_id", "adgroup_name", "campaign_id", "operation_status",
                "secondary_status", "optimization_goal", "billing_event",
                "budget", "budget_mode", "schedule_start_time", "schedule_end_time",
                "location_ids", "targeting_expansion", "create_time",
            ],
        },
    )
    out = []
    for ag in raw:
        op = ag.get("operation_status")
        if op == "DELETE":
            continue
        budget = ag.get("budget") or 0
        budget_mode = ag.get("budget_mode") or ""
        daily = float(budget) if "DAY" in budget_mode and budget else None
        lifetime = float(budget) if "TOTAL" in budget_mode and budget else None
        out.append({
            "platform_adset_id": str(ag.get("adgroup_id")),
            "campaign_id": str(ag.get("campaign_id")),
            "name": ag.get("adgroup_name") or "",
            "status": _normalise_status(op),
            "optimization_goal": ag.get("optimization_goal"),
            "billing_event": ag.get("billing_event"),
            "daily_budget": daily,
            "lifetime_budget": lifetime,
            # location_ids stashed in raw_data — country prefix in name remains
            # the source of truth for our country dashboard.
            "targeting": {"location_ids": ag.get("location_ids")} if ag.get("location_ids") else None,
            "start_date": _parse_date(ag.get("schedule_start_time")),
            "end_date": _parse_date(ag.get("schedule_end_time")),
            "raw_data": ag,
        })
    logger.info("Fetched %d TikTok adgroups for advertiser %s", len(out), advertiser_id)
    return out


def fetch_ads(advertiser_id: str) -> list[dict]:
    raw = _paginate(
        "/ad/get/",
        {
            "advertiser_id": str(advertiser_id),
            "fields": [
                "ad_id", "ad_name", "adgroup_id", "campaign_id",
                "operation_status", "secondary_status", "ad_format",
                "creative_type", "video_id", "image_ids", "landing_page_url",
                "ad_text", "call_to_action", "create_time", "modify_time",
            ],
        },
    )
    out = []
    for a in raw:
        op = a.get("operation_status")
        if op == "DELETE":
            continue
        out.append({
            "platform_ad_id": str(a.get("ad_id")),
            "platform_adset_id": str(a.get("adgroup_id")),
            "platform_campaign_id": str(a.get("campaign_id")),
            "name": a.get("ad_name") or "",
            "status": _normalise_status(op),
            "creative_id": str(a.get("video_id") or "") or None,
            "raw_data": a,
        })
    logger.info("Fetched %d TikTok ads for advertiser %s", len(out), advertiser_id)
    return out


# ---------------------------------------------------------------- reports ---


def _to_float(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(v) -> int:
    try:
        return int(float(v)) if v not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def _normalise_report_row(metrics: dict, dimensions: dict) -> dict:
    """Translate a TikTok integrated-report row into our internal insight dict.

    Shape mirrors what `_upsert_metrics_row` (Meta) and `_upsert_google_metrics`
    expect, so the sync engine stays uniform across platforms.
    """
    spend = _to_float(metrics.get("spend"))
    impressions = _to_int(metrics.get("impressions"))
    clicks = _to_int(metrics.get("clicks"))
    # TikTok ctr is returned as a percent (e.g. "1.52" = 1.52%). Our column
    # stores ratio (clicks / impressions), so divide by 100.
    raw_ctr = _to_float(metrics.get("ctr"))
    ctr = raw_ctr / 100.0 if raw_ctr else (clicks / impressions if impressions else 0.0)

    # Conversions / revenue — prefer the deduped totals; fall back to
    # complete_payment when total_purchase is zero (some advertisers track
    # only the payment event).
    purchases = _to_int(metrics.get("total_purchase"))
    purchase_value = _to_float(metrics.get("total_purchase_value"))
    if purchases == 0 and purchase_value == 0:
        purchases = _to_int(metrics.get("total_complete_payment"))
        purchase_value = _to_float(metrics.get("total_complete_payment_value"))

    cpc = spend / clicks if clicks else 0.0
    cpa = spend / purchases if purchases else 0.0
    roas = purchase_value / spend if spend else 0.0

    return {
        "campaign_id": str(dimensions.get("campaign_id") or ""),
        "entity_id": str(
            dimensions.get("ad_id")
            or dimensions.get("adgroup_id")
            or dimensions.get("campaign_id")
            or ""
        ),
        "date": _parse_date(dimensions.get("stat_time_day")),
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        # TikTok has no separate "link_clicks" — mirror clicks like Google does
        # so the landing-page rollup can read a single column.
        "link_clicks": clicks,
        "ctr": ctr,
        "cpc": cpc,
        "frequency": _to_float(metrics.get("frequency")),
        "conversions": purchases,
        "revenue": purchase_value,
        "revenue_website": purchase_value,
        "revenue_offline": 0.0,
        "roas": roas,
        "cpa": cpa,
        # Funnel events (pixel + onsite + app + offline totals)
        "searches": _to_int(metrics.get("total_search")),
        "add_to_cart": _to_int(metrics.get("total_add_to_cart")),
        "checkouts": _to_int(metrics.get("total_initiate_checkout")),
        "landing_page_views": _to_int(metrics.get("total_landing_page_view")),
        "leads": 0,
        # Video engagement
        "video_views": _to_int(metrics.get("video_play_actions")),
        "video_3s_views": _to_int(metrics.get("video_watched_2s")),
        "video_thru_plays": _to_int(metrics.get("video_watched_6s")),
        "video_p25_views": _to_int(metrics.get("video_views_p25")),
        "video_p50_views": _to_int(metrics.get("video_views_p50")),
        "video_p75_views": _to_int(metrics.get("video_views_p75")),
        "video_p100_views": _to_int(metrics.get("video_views_p100")),
    }


def _fetch_report(
    advertiser_id: str,
    data_level: str,
    dimensions: list[str],
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Run /report/integrated/get/ for a single (advertiser, data_level)."""
    out: list[dict] = []
    page = 1
    while True:
        data = _get(
            "/report/integrated/get/",
            {
                "advertiser_id": str(advertiser_id),
                "service_type": "AUCTION",
                "report_type": "BASIC",
                "data_level": data_level,
                "dimensions": dimensions,
                "metrics": _REPORT_METRICS,
                "start_date": date_from.isoformat(),
                "end_date": date_to.isoformat(),
                "page": page,
                "page_size": _PAGE_SIZE,
            },
        )
        rows = data.get("list") or []
        for row in rows:
            metrics = row.get("metrics") or {}
            dim = row.get("dimensions") or {}
            normalised = _normalise_report_row(metrics, dim)
            if normalised["date"] is None:
                continue
            out.append(normalised)
        info = data.get("page_info") or {}
        total_page = info.get("total_page") or 1
        if page >= total_page or not rows:
            break
        page += 1
    return out


def fetch_campaign_metrics(advertiser_id: str, date_from: date, date_to: date) -> list[dict]:
    return _fetch_report(
        advertiser_id, "AUCTION_CAMPAIGN",
        ["campaign_id", "stat_time_day"], date_from, date_to,
    )


def fetch_adgroup_metrics(advertiser_id: str, date_from: date, date_to: date) -> list[dict]:
    return _fetch_report(
        advertiser_id, "AUCTION_ADGROUP",
        ["adgroup_id", "campaign_id", "stat_time_day"], date_from, date_to,
    )


def fetch_ad_metrics(advertiser_id: str, date_from: date, date_to: date) -> list[dict]:
    return _fetch_report(
        advertiser_id, "AUCTION_AD",
        ["ad_id", "adgroup_id", "campaign_id", "stat_time_day"], date_from, date_to,
    )
