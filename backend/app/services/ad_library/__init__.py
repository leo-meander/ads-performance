"""Ad Library sources behind one interface.

`AD_LIBRARY_PROVIDER` picks the default. Callers may override per-request so
the UI can fall back to the free official API when Apify has no token.
"""

from __future__ import annotations

from app.config import settings
from app.services.ad_library import apify, meta_official
from app.services.ad_library.base import (
    AdLibraryError,
    AdLibraryPage,
    NormalizedAd,
)

PROVIDERS = {
    "apify": apify,
    "meta_official": meta_official,
}

__all__ = [
    "AdLibraryError",
    "AdLibraryPage",
    "NormalizedAd",
    "PROVIDERS",
    "active_provider_name",
    "get_provider",
    "looks_like_page_id",
    "provider_status",
    "resolve_page",
    "search_ads",
    "fetch_page_ads",
]


def active_provider_name(override: str | None = None) -> str:
    name = (override or settings.AD_LIBRARY_PROVIDER or "meta_official").lower()
    return name if name in PROVIDERS else "meta_official"


def get_provider(override: str | None = None):
    return PROVIDERS[active_provider_name(override)]


def provider_status() -> dict:
    """What the UI needs to explain an empty result before the user guesses."""
    name = active_provider_name()
    configured = bool(settings.APIFY_TOKEN) if name == "apify" else True
    return {
        "provider": name,
        "configured": configured,
        "covers_commercial_ads": name == "apify",
        "actor": settings.APIFY_FB_ADS_ACTOR if name == "apify" else None,
        "note": (
            None
            if configured
            else "APIFY_TOKEN is not set, so competitor searches will fail."
        ),
    }


def search_ads(provider: str | None = None, **kwargs) -> AdLibraryPage:
    return get_provider(provider).search(**kwargs)


def fetch_page_ads(page_id: str, provider: str | None = None, **kwargs) -> AdLibraryPage:
    return get_provider(provider).fetch_page_ads(page_id=page_id, **kwargs)


# Imported last: page_resolver calls search_ads above, so importing it any
# earlier would be circular.
from app.services.ad_library.page_resolver import (  # noqa: E402
    looks_like_page_id,
    resolve_page,
)
