"""Shared shape every Ad Library source normalizes into.

Two sources exist and they are NOT interchangeable in coverage:

- `meta_official` — graph.facebook.com/ads_archive. Free, but Meta only
  returns ads that reached the EU unless the ad is about social issues,
  elections or politics. For MEANDER's markets (VN/TW/JP) that means hotel
  competitors return zero rows. Kept for EU/political lookups and as the
  no-credentials fallback.
- `apify` — the Meta Ad Library web surface via an Apify actor. Covers
  ordinary commercial ads in every country, which is the only way to see
  hotel competitors. Costs per ad returned.

Providers hand back `NormalizedAd`; everything downstream (longevity,
fingerprinting, AI analysis, UI) reads only this shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


class AdLibraryError(Exception):
    """A provider could not answer. Message is safe to show a user."""


@dataclass
class NormalizedAd:
    ad_archive_id: str
    page_id: str = ""
    page_name: str = ""
    bylines: str = ""

    ad_creative_bodies: list[str] = field(default_factory=list)
    ad_creative_link_titles: list[str] = field(default_factory=list)
    ad_creative_link_captions: list[str] = field(default_factory=list)

    cta_text: str = ""
    link_url: str = ""
    # image | video | carousel | dco | unknown
    media_type: str = "unknown"
    # Stable-ish creative asset URLs, used for fingerprinting.
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)
    preview_image_url: str = ""

    ad_snapshot_url: str = ""
    publisher_platforms: list[str] = field(default_factory=list)
    country: str = ""

    ad_delivery_start_time: datetime | None = None
    ad_delivery_stop_time: datetime | None = None
    is_active: bool = True

    source: str = ""
    raw_data: dict = field(default_factory=dict)

    @property
    def days_active(self) -> int:
        """Whole days between first delivery and today (or the stop date).

        This is the provider's own start date, not our observation window —
        it is the better number when available. `spy_competitor_ads` keeps our
        observed first/last-seen separately so the two can disagree visibly.
        """
        if not self.ad_delivery_start_time:
            return 0
        from datetime import timezone
        end = self.ad_delivery_stop_time or datetime.now(timezone.utc)
        return max(0, (end.date() - self.ad_delivery_start_time.date()).days)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ad_delivery_start_time"] = (
            self.ad_delivery_start_time.isoformat() if self.ad_delivery_start_time else None
        )
        d["ad_delivery_stop_time"] = (
            self.ad_delivery_stop_time.isoformat() if self.ad_delivery_stop_time else None
        )
        d["days_active"] = self.days_active
        # raw_data is bulky and only useful server-side; drop from API payloads.
        d.pop("raw_data", None)
        return d


@dataclass
class AdLibraryPage:
    """One page of provider results."""

    ads: list[NormalizedAd] = field(default_factory=list)
    after: str | None = None
    source: str = ""
    # Set when a provider answered but its coverage makes the empty result
    # expected rather than informative (e.g. official API outside the EU).
    coverage_note: str | None = None
