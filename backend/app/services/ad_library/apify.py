"""Apify-backed Ad Library source.

Meta's official API cannot see ordinary commercial ads outside the EU, so
competitor hotel ads in VN/TW/JP are only reachable through the public Ad
Library web surface. This provider drives an Apify actor over that surface.

Cost is per ad returned, so every call is bounded by an explicit results limit
and the monitor crawls only when someone asks it to.

The actor's item shape is not a contract we control, so parsing is
deliberately forgiving: every field is looked up under several plausible
names, and the untouched item is kept in `raw_data` so a mapping mistake can
be corrected later without paying to re-crawl.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from app.config import settings
from app.services.ad_library.base import AdLibraryError, AdLibraryPage, NormalizedAd

logger = logging.getLogger(__name__)

APIFY_API = "https://api.apify.com/v2"
AD_LIBRARY_WEB = "https://www.facebook.com/ads/library/"

# The web UI needs a concrete country. "All countries" in our UI maps to a
# single default market rather than a worldwide sweep, which would multiply
# the per-ad cost for no benefit.
DEFAULT_COUNTRY = "VN"

_TERMINAL_OK = {"SUCCEEDED"}
_TERMINAL_BAD = {"FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"}


# The actor's own `activeStatus` input accepts ONLY "", "active" or
# "inactive" -- it answers anything else with HTTP 400 and spends nothing.
# Our UI's "ALL" means "don't filter by delivery state", and the empty string
# is how the actor spells that. Note this is NARROWER than the Ad Library web
# URL, where `active_status=all` is a value Meta itself understands, so only
# the actor input gets squeezed through here.
_ACTOR_ACTIVE_STATUS = {"active": "active", "inactive": "inactive"}


def actor_active_status(active_status: str) -> str:
    return _ACTOR_ACTIVE_STATUS.get((active_status or "").strip().lower(), "")


# -- URL building -------------------------------------------------------


def build_library_url(
    query: str = "",
    country: str = "VN",
    active_status: str = "ACTIVE",
    page_id: str = "",
    media_type: str = "ALL",
) -> str:
    """Compose the public Ad Library URL the actor will crawl."""
    params = {
        "active_status": (active_status or "ACTIVE").lower(),
        "ad_type": "all",
        "country": (country or DEFAULT_COUNTRY).upper(),
        "media_type": (media_type or "ALL").lower(),
    }
    if page_id:
        params["view_all_page_id"] = page_id
        params["search_type"] = "page"
    else:
        params["q"] = query
        params["search_type"] = "keyword_unordered"
    return f"{AD_LIBRARY_WEB}?{urlencode(params)}"


# -- Apify run lifecycle ------------------------------------------------


def _token() -> str:
    if not settings.APIFY_TOKEN:
        raise AdLibraryError(
            "APIFY_TOKEN is not set. Create a token at apify.com (Settings -> "
            "Integrations) and add it to the backend service variables, or set "
            "AD_LIBRARY_PROVIDER=meta_official to use the free EU-only API."
        )
    return settings.APIFY_TOKEN


def _run_actor(actor_input: dict) -> list[dict]:
    """Start the actor, wait for it, return its dataset items.

    Deliberately async-start-then-poll rather than Apify's run-sync endpoint:
    run-sync has its own ceiling and returns a bare 408 on overrun, which would
    throw away a run we already paid for.
    """
    token = _token()
    actor = settings.APIFY_FB_ADS_ACTOR.replace("/", "~")
    deadline = time.monotonic() + settings.APIFY_TIMEOUT_SECONDS

    try:
        start = requests.post(
            f"{APIFY_API}/acts/{actor}/runs",
            params={"token": token},
            json=actor_input,
            timeout=60,
        )
    except requests.RequestException as e:
        raise AdLibraryError(f"Could not reach Apify: {e}") from e

    if start.status_code >= 400:
        raise AdLibraryError(
            f"Apify rejected the run (HTTP {start.status_code}): {start.text[:300]}"
        )

    run = (start.json() or {}).get("data") or {}
    run_id = run.get("id")
    if not run_id:
        raise AdLibraryError("Apify did not return a run id.")

    status = run.get("status", "READY")
    while status not in _TERMINAL_OK and status not in _TERMINAL_BAD:
        if time.monotonic() > deadline:
            raise AdLibraryError(
                f"Apify run {run_id} still {status} after "
                f"{settings.APIFY_TIMEOUT_SECONDS}s - try a smaller result limit."
            )
        time.sleep(settings.APIFY_POLL_SECONDS)
        try:
            poll = requests.get(
                f"{APIFY_API}/actor-runs/{run_id}", params={"token": token}, timeout=30
            )
            status = ((poll.json() or {}).get("data") or {}).get("status", status)
        except (requests.RequestException, ValueError) as e:
            logger.warning("Apify poll for run %s failed, retrying: %s", run_id, e)

    if status in _TERMINAL_BAD:
        raise AdLibraryError(f"Apify run {run_id} finished as {status}.")

    try:
        items = requests.get(
            f"{APIFY_API}/actor-runs/{run_id}/dataset/items",
            params={"token": token, "clean": "true", "format": "json"},
            timeout=120,
        )
        return items.json() or []
    except (requests.RequestException, ValueError) as e:
        raise AdLibraryError(f"Could not read Apify results for run {run_id}: {e}") from e


# -- Item normalization -------------------------------------------------


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return default


def _as_dt(value) -> datetime | None:
    """Accept epoch seconds, epoch ms, or an ISO / YYYY-MM-DD string."""
    if value in (None, "", 0):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        for parse in (
            datetime.fromisoformat,
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
            lambda s: datetime.strptime(s, "%b %d, %Y"),
        ):
            try:
                dt = parse(text)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _text_of(value) -> str:
    """Snapshot text fields arrive as either a string or a {"text": ...} dict."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        markup = value.get("markup")
        if isinstance(markup, dict) and isinstance(markup.get("__html"), str):
            return markup["__html"]
    return ""


def _collect_media(snapshot: dict) -> tuple[list[str], list[str], str, str]:
    """Return (image_urls, video_urls, preview_image_url, media_type)."""
    images: list[str] = []
    videos: list[str] = []
    preview = ""

    blocks: list[dict] = [snapshot]
    blocks.extend(c for c in (snapshot.get("cards") or []) if isinstance(c, dict))

    for block in blocks:
        for img in block.get("images") or []:
            url = (
                _first(img, "original_image_url", "resized_image_url", "url")
                if isinstance(img, dict)
                else img
            )
            if url:
                images.append(url)
        for vid in block.get("videos") or []:
            if isinstance(vid, dict):
                url = _first(vid, "video_hd_url", "video_sd_url", "url")
                thumb = _first(vid, "video_preview_image_url", "thumbnail_url")
                if thumb and not preview:
                    preview = thumb
            else:
                url = vid
            if url:
                videos.append(url)
        if block is not snapshot:
            # Carousel cards usually carry flat asset urls instead of lists.
            for key in ("original_image_url", "resized_image_url", "image_url"):
                if block.get(key):
                    images.append(block[key])
            for key in ("video_hd_url", "video_sd_url"):
                if block.get(key):
                    videos.append(block[key])

    if not preview and images:
        preview = images[0]

    declared = str(_first(snapshot, "display_format", "displayFormat", default="")).lower()
    if declared in ("video", "dpa_video", "dco"):
        media_type = "video" if videos else "image"
    elif declared in ("carousel", "dpa_carousel", "multi_images"):
        media_type = "carousel"
    elif declared in ("image", "dpa_image", "single_image"):
        media_type = "image"
    elif videos:
        media_type = "video"
    elif len(images) > 1:
        media_type = "carousel"
    elif images:
        media_type = "image"
    else:
        media_type = "unknown"

    # De-duplicate while preserving order - carousels repeat assets.
    return list(dict.fromkeys(images)), list(dict.fromkeys(videos)), preview, media_type


def _truthy(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "active", "1", "yes")
    return bool(value)


def _parse_item(item: dict, country: str) -> NormalizedAd | None:
    archive_id = _first(item, "adArchiveID", "adArchiveId", "ad_archive_id", "adId", "id")
    if not archive_id:
        return None

    snapshot = item.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    body = _text_of(_first(snapshot, "body", "bodyText", default="")) or _text_of(
        _first(item, "body", "adText", default="")
    )
    title = _text_of(_first(snapshot, "title", "linkTitle", default=""))
    caption = _text_of(_first(snapshot, "caption", "linkDescription", default=""))

    # Carousel cards each carry their own copy; keep them all so the AI pass
    # and the fingerprint see the whole creative, not just the first frame.
    bodies = [body] if body else []
    titles = [title] if title else []
    captions = [caption] if caption else []
    for card in snapshot.get("cards") or []:
        if not isinstance(card, dict):
            continue
        for value, bucket in (
            (_text_of(card.get("body")), bodies),
            (_text_of(card.get("title")), titles),
            (_text_of(card.get("caption")), captions),
        ):
            if value and value not in bucket:
                bucket.append(value)

    images, videos, preview, media_type = _collect_media(snapshot)

    start = _as_dt(
        _first(item, "startDate", "start_date", "startDateFormatted", "adDeliveryStartTime")
    )
    stop = _as_dt(
        _first(item, "endDate", "end_date", "endDateFormatted", "adDeliveryStopTime")
    )

    is_active = _truthy(_first(item, "isActive", "is_active", "active", default=None))
    if is_active is None:
        is_active = stop is None
    # An ad Meta still lists as active has no meaningful stop date, even if the
    # actor echoed one back; leaving it set would freeze days-running.
    if is_active:
        stop = None

    platforms = _first(
        item, "publisherPlatform", "publisherPlatforms", "publisher_platform", default=[]
    )
    if isinstance(platforms, str):
        platforms = [platforms]

    return NormalizedAd(
        ad_archive_id=str(archive_id),
        page_id=str(_first(item, "pageID", "pageId", "page_id", default="") or ""),
        page_name=str(
            _first(item, "pageName", "page_name", default="")
            or snapshot.get("page_name")
            or ""
        ),
        bylines=str(_first(item, "byline", "bylines", default="") or ""),
        ad_creative_bodies=bodies,
        ad_creative_link_titles=titles,
        ad_creative_link_captions=captions,
        cta_text=str(_first(snapshot, "cta_text", "ctaText", default="") or ""),
        link_url=str(_first(snapshot, "link_url", "linkUrl", default="") or ""),
        media_type=media_type,
        image_urls=images[:10],
        video_urls=videos[:10],
        preview_image_url=preview,
        ad_snapshot_url=f"{AD_LIBRARY_WEB}?id={archive_id}",
        publisher_platforms=[str(p).lower() for p in platforms],
        country=country.upper() if country and country != "ALL" else "",
        ad_delivery_start_time=start,
        ad_delivery_stop_time=stop,
        is_active=bool(is_active),
        source="apify",
        raw_data=item,
    )


# -- Public interface ---------------------------------------------------


def search(
    query: str = "",
    country: str = "ALL",
    active_status: str = "ACTIVE",
    publisher_platform: str = "ALL",
    media_type: str = "ALL",
    page_id: str = "",
    limit: int = 25,
    after: str | None = None,
    **_ignored,
) -> AdLibraryPage:
    """One Apify run.

    `after` is unsupported: the actor pages internally, so the UI raises
    `limit` instead of walking a cursor.
    """
    resolved_country = DEFAULT_COUNTRY if (not country or country == "ALL") else country.upper()

    if not query and not page_id:
        raise AdLibraryError("Enter a keyword or pick a tracked competitor to search.")

    url = build_library_url(
        query=query,
        country=resolved_country,
        active_status=active_status,
        page_id=page_id,
        media_type=media_type,
    )
    items = _run_actor(
        {
            "startUrls": [{"url": url}],
            "resultsLimit": max(1, min(limit, settings.APIFY_MAX_RESULTS)),
            "activeStatus": actor_active_status(active_status),
        }
    )

    ads = [ad for ad in (_parse_item(i, resolved_country) for i in items) if ad]

    if publisher_platform and publisher_platform != "ALL":
        want = publisher_platform.lower()
        ads = [a for a in ads if want in a.publisher_platforms]

    return AdLibraryPage(ads=ads, after=None, source="apify")


def fetch_page_ads(
    page_id: str,
    country: str = "ALL",
    active_status: str = "ACTIVE",
    limit: int = 25,
    after: str | None = None,
    **_ignored,
) -> AdLibraryPage:
    return search(
        query="",
        country=country,
        active_status=active_status,
        page_id=page_id,
        limit=limit,
    )
