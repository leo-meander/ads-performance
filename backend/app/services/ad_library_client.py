"""Meta Ad Library API client for competitor ad research."""

import logging
from datetime import date, datetime, timezone

import requests

from app.config import settings

logger = logging.getLogger(__name__)

AD_LIBRARY_URL = "https://graph.facebook.com/v21.0/ads_archive"

AD_LIBRARY_FIELDS = ",".join([
    "id",
    "ad_creative_bodies",
    "ad_creative_link_captions",
    "ad_creative_link_titles",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "page_id",
    "page_name",
    "publisher_platforms",
    "bylines",
    "ad_snapshot_url",
])


def _get_access_token() -> str:
    """Get access token for Ad Library API — reuses META_ACCESS_TOKEN_SAIGON."""
    token = settings.META_ACCESS_TOKEN_SAIGON
    if not token:
        raise ValueError("META_ACCESS_TOKEN_SAIGON is not configured. Required for Ad Library API.")
    return token


def _parse_ad_result(raw: dict) -> dict:
    """Normalize a single Ad Library API result into a clean dict."""
    start_str = raw.get("ad_delivery_start_time")
    stop_str = raw.get("ad_delivery_stop_time")

    start_dt = None
    stop_dt = None
    days_active = 0

    if start_str:
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            start_dt = None

    if stop_str:
        try:
            stop_dt = datetime.fromisoformat(stop_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            stop_dt = None

    if start_dt:
        end = stop_dt or datetime.now(timezone.utc)
        days_active = max(0, (end.date() - start_dt.date()).days)

    return {
        "ad_archive_id": raw.get("id", ""),
        "page_id": raw.get("page_id", ""),
        "page_name": raw.get("page_name", ""),
        "bylines": raw.get("bylines", ""),
        "ad_creative_bodies": raw.get("ad_creative_bodies", []),
        "ad_creative_link_titles": raw.get("ad_creative_link_titles", []),
        "ad_creative_link_captions": raw.get("ad_creative_link_captions", []),
        "ad_snapshot_url": raw.get("ad_snapshot_url", ""),
        "publisher_platforms": raw.get("publisher_platforms", []),
        "ad_delivery_start_time": start_dt.isoformat() if start_dt else None,
        "ad_delivery_stop_time": stop_dt.isoformat() if stop_dt else None,
        "days_active": days_active,
        "is_active": stop_dt is None,
    }


def search_ads(
    query: str = "",
    country: str = "ALL",
    active_status: str = "ACTIVE",
    publisher_platform: str = "ALL",
    media_type: str = "ALL",
    search_page_ids: str = "",
    limit: int = 25,
    after: str | None = None,
) -> dict:
    """Search the Meta Ad Library API.

    Returns: {"ads": [parsed_ad_dicts], "paging": {"after": cursor_or_none}}
    """
    token = _get_access_token()

    params: dict = {
        "access_token": token,
        "ad_type": "ALL",
        "fields": AD_LIBRARY_FIELDS,
        "limit": min(limit, 50),
    }

    if query:
        params["search_terms"] = query
    if country and country != "ALL":
        params["ad_reached_countries"] = f'["{country}"]'
    if active_status and active_status != "ALL":
        params["ad_active_status"] = active_status
    if publisher_platform and publisher_platform != "ALL":
        params["publisher_platform"] = f'["{publisher_platform.upper()}"]'
    if media_type and media_type != "ALL":
        params["media_type"] = media_type
    if search_page_ids:
        params["search_page_ids"] = search_page_ids
    if after:
        params["after"] = after

    try:
        resp = requests.get(AD_LIBRARY_URL, params=params, timeout=30)
    except requests.RequestException as e:
        logger.error("Ad Library API request failed: %s", e)
        raise ValueError(f"Ad Library API connection error: {e}") from e

    try:
        data = resp.json()
    except Exception:
        logger.error("Ad Library API non-JSON response [%s]: %s", resp.status_code, resp.text[:500])
        raise ValueError(f"Ad Library API error: HTTP {resp.status_code} - {resp.text[:200]}")

    if "error" in data:
        error_msg = data["error"].get("message", "Unknown error")
        error_code = data["error"].get("code", "")
        error_subcode = data["error"].get("error_subcode", "")
        logger.error("Ad Library API error [code=%s, subcode=%s]: %s", error_code, error_subcode, error_msg)
        raise ValueError(f"Ad Library API error: {error_msg}")

    raw_ads = data.get("data", [])
    parsed_ads = [_parse_ad_result(ad) for ad in raw_ads]

    # Extract pagination cursor
    paging = data.get("paging", {})
    cursors = paging.get("cursors", {})
    after_cursor = cursors.get("after") if "next" in paging else None

    return {
        "ads": parsed_ads,
        "paging": {"after": after_cursor},
    }


def fetch_page_ads(
    page_id: str,
    country: str = "ALL",
    active_status: str = "ACTIVE",
    limit: int = 25,
    after: str | None = None,
) -> dict:
    """Fetch ads for a specific page from the Ad Library."""
    return search_ads(
        query="",
        country=country,
        active_status=active_status,
        search_page_ids=page_id,
        limit=limit,
        after=after,
    )
