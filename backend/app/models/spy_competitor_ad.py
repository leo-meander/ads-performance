from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class SpyCompetitorAd(TimestampMixin, Base):
    """One competitor ad, carried across every crawl that saw it.

    This is the longevity ledger and the reason the monitor exists. Meta tells
    us when an ad started, but not whether it is still worth running - only
    repeated observation does. So two clocks are kept side by side:

    - `ad_delivery_start_time` / `days_running`: Meta's own start date. Longer
      history, but we cannot verify it and it silently disappears when an ad
      is relaunched under a new id.
    - `first_seen_at` / `last_seen_at` / `seen_count`: what we actually
      observed. Shorter at first, but ours, and the only figure that proves
      the ad was still live on a given day.

    They will disagree, and that disagreement is informative - never collapse
    them into one number.
    """

    __tablename__ = "spy_competitor_ads"

    ad_archive_id = Column(String(100), nullable=False, unique=True, index=True)
    tracked_page_id = Column(
        UUIDType, ForeignKey("spy_tracked_pages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    page_id = Column(String(50), nullable=True, index=True)
    page_name = Column(String(500), nullable=True)
    country = Column(String(10), nullable=True, index=True)

    # -- Creative --
    ad_creative_bodies = Column(JSONType, nullable=True)
    ad_creative_link_titles = Column(JSONType, nullable=True)
    ad_creative_link_captions = Column(JSONType, nullable=True)
    cta_text = Column(String(200), nullable=True)
    link_url = Column(Text, nullable=True)
    media_type = Column(String(20), nullable=True, index=True)
    image_urls = Column(JSONType, nullable=True)
    video_urls = Column(JSONType, nullable=True)
    preview_image_url = Column(Text, nullable=True)
    ad_snapshot_url = Column(Text, nullable=True)
    publisher_platforms = Column(JSONType, nullable=True)

    # -- Meta's delivery window --
    ad_delivery_start_time = Column(DateTime(timezone=True), nullable=True, index=True)
    ad_delivery_stop_time = Column(DateTime(timezone=True), nullable=True)
    # Denormalized so the "long-running ads" ranking is a plain ORDER BY
    # instead of a per-row date computation. Recomputed on every crawl.
    days_running = Column(Integer, nullable=False, default=0, index=True)

    # -- What we observed --
    first_seen_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, index=True)
    seen_count = Column(Integer, nullable=False, default=1)
    days_observed = Column(Integer, nullable=False, default=0)
    is_currently_active = Column(Boolean, nullable=False, default=True, index=True)
    # Set the first time a crawl of its page came back without it. Kept rather
    # than deleting the row, so a paused-then-resumed ad reads as one story.
    disappeared_at = Column(DateTime(timezone=True), nullable=True)

    # -- Creative grouping --
    fingerprint = Column(String(64), nullable=True, index=True)
    creative_group_key = Column(String(64), nullable=True, index=True)

    # -- AI breakdown (hook / angle / offer / usp / format / cta / target) --
    ai_breakdown = Column(JSONType, nullable=True)
    ai_analyzed_at = Column(DateTime(timezone=True), nullable=True)

    source = Column(String(30), nullable=True)
    raw_data = Column(JSONType, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)


class SpyCreativeGroup(TimestampMixin, Base):
    """A creative concept - the ads that are really the same idea.

    A competitor duplicating one concept into five ad ids is a stronger signal
    than any single ad's age, so this table carries its own longevity numbers
    rather than deriving them at read time.
    """

    __tablename__ = "spy_creative_groups"

    group_key = Column(String(64), nullable=False, unique=True, index=True)
    label = Column(String(500), nullable=True)
    ad_count = Column(Integer, nullable=False, default=0, index=True)
    active_ad_count = Column(Integer, nullable=False, default=0)
    page_ids = Column(JSONType, nullable=True)
    page_names = Column(JSONType, nullable=True)
    representative_ad_id = Column(String(100), nullable=True)
    preview_image_url = Column(Text, nullable=True)
    media_type = Column(String(20), nullable=True)

    first_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # Longest single-ad run in the group - the concept's best evidence.
    max_days_running = Column(Integer, nullable=False, default=0, index=True)
    is_still_active = Column(Boolean, nullable=False, default=True, index=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)
