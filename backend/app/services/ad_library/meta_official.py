"""Meta's official Ad Library API (graph.facebook.com/ads_archive).

Coverage warning, straight from Meta's docs: "Ads that did not reach any
location in the EU will only return if they are about social issues, elections
or politics." So a keyword search for hotels in VN/TW/JP legitimately returns
zero rows here — that is the API working as designed, not a bug. Use the Apify
provider for ordinary commercial ads outside the EU.
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from app.config import settings
from app.services.ad_library.base import AdLibraryError, AdLibraryPage, NormalizedAd

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

# ad_reached_countries is a REQUIRED parameter. The page's "All Countries"
# option therefore cannot map to "omit the param" — it has to mean a concrete
# list, or the request 400s and the user sees an unexplained empty grid.
DEFAULT_COUNTRIES = ["VN", "TW", "JP", "KR", "SG", "TH", "US", "AU", "HK", "MY"]

# Ads outside the EU only come back when they are political. Detect the
# hopeless case up front so the UI can say why instead of showing "0 results".
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}

NON_EU_COVERAGE_NOTE = (
    "Meta's official Ad Library API only returns ads outside the EU when they "
    "are about social issues, elections or politics — commercial ads such as "
    "hotel promos are never included. Switch AD_LIBRARY_PROVIDER to 'apify' "
    "to search ordinary ads in this country."
)


def _resolve_token(access_token: str | None) -> str:
    token = access_token or settings.META_ACCESS_TOKEN_SAIGON
    if not token:
        raise AdLibraryError(
            "No Meta access token available for Ad Library search. Add an "
            "active Meta account with a token on the Accounts page, or set "
            "META_ACCESS_TOKEN_SAIGON."
        )
    return token


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_ad(raw: dict, country: str) -> NormalizedAd:
    start = _parse_dt(raw.get("ad_delivery_start_time"))
    stop = _parse_dt(raw.get("ad_delivery_stop_time"))
    return NormalizedAd(
        ad_archive_id=str(raw.get("id", "")),
        page_id=str(raw.get("page_id", "")),
        page_name=raw.get("page_name", "") or "",
        bylines=raw.get("bylines", "") or "",
        ad_creative_bodies=raw.get("ad_creative_bodies") or [],
        ad_creative_link_titles=raw.get("ad_creative_link_titles") or [],
        ad_creative_link_captions=raw.get("ad_creative_link_captions") or [],
        ad_snapshot_url=raw.get("ad_snapshot_url", "") or "",
        publisher_platforms=[p.lower() for p in (raw.get("publisher_platforms") or [])],
        country=country,
        ad_delivery_start_time=start,
        ad_delivery_stop_time=stop,
        is_active=stop is None,
        source="meta_official",
        raw_data=raw,
    )


def search(
    query: str = "",
    country: str = "ALL",
    active_status: str = "ACTIVE",
    publisher_platform: str = "ALL",
    media_type: str = "ALL",
    page_id: str = "",
    limit: int = 25,
    after: str | None = None,
    access_token: str | None = None,
    **_ignored,
) -> AdLibraryPage:
    token = _resolve_token(access_token)

    countries = DEFAULT_COUNTRIES if (not country or country == "ALL") else [country.upper()]

    params: dict = {
        "access_token": token,
        "ad_type": "ALL",
        "fields": AD_LIBRARY_FIELDS,
        "limit": min(limit, 50),
        "ad_reached_countries": "[" + ",".join(f'"{c}"' for c in countries) + "]",
    }
    if query:
        params["search_terms"] = query
    if active_status and active_status != "ALL":
        params["ad_active_status"] = active_status
    if publisher_platform and publisher_platform != "ALL":
        params["publisher_platforms"] = f'["{publisher_platform.upper()}"]'
    if media_type and media_type != "ALL":
        params["media_type"] = media_type.upper()
    if page_id:
        params["search_page_ids"] = f'["{page_id}"]'
    if after:
        params["after"] = after

    try:
        resp = requests.get(AD_LIBRARY_URL, params=params, timeout=30)
    except requests.RequestException as e:
        logger.error("Ad Library API request failed: %s", e)
        raise AdLibraryError(f"Ad Library API connection error: {e}") from e

    try:
        data = resp.json()
    except ValueError:
        logger.error("Ad Library non-JSON response [%s]: %s", resp.status_code, resp.text[:500])
        raise AdLibraryError(
            f"Ad Library API error: HTTP {resp.status_code} — {resp.text[:200]}"
        ) from None

    if "error" in data:
        err = data["error"]
        logger.error(
            "Ad Library API error [code=%s subcode=%s]: %s",
            err.get("code"), err.get("error_subcode"), err.get("message"),
        )
        raise AdLibraryError(f"Ad Library API error: {err.get('message', 'Unknown error')}")

    label = country.upper() if country and country != "ALL" else ""
    ads = [_parse_ad(a, label) for a in data.get("data", [])]

    paging = data.get("paging", {})
    after_cursor = paging.get("cursors", {}).get("after") if "next" in paging else None

    note = None
    if not ads and not (set(countries) & EU_COUNTRIES):
        note = NON_EU_COVERAGE_NOTE

    return AdLibraryPage(ads=ads, after=after_cursor, source="meta_official", coverage_note=note)


def fetch_page_ads(
    page_id: str,
    country: str = "ALL",
    active_status: str = "ACTIVE",
    limit: int = 25,
    after: str | None = None,
    access_token: str | None = None,
    **_ignored,
) -> AdLibraryPage:
    return search(
        query="",
        country=country,
        active_status=active_status,
        page_id=page_id,
        limit=limit,
        after=after,
        access_token=access_token,
    )
