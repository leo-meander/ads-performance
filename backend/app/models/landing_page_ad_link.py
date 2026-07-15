from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class LandingPageAdLink(TimestampMixin, Base):
    """Join row connecting a landing page to the ad(s) driving traffic to it.

    Populated in two ways:
    1. Auto-discovery: landing_page_importer scans ad destination URLs
       (Meta ads' raw_data.creative.link + Google asset_groups.final_urls),
       normalizes them, matches to a landing_pages row (creating an
       `external` landing page if none exists), and writes an ad-link row.
    2. Manual link: user picks a landing page for a new ad combo; UI writes
       an ad-link row plus appends UTMs to the destination URL.

    The (campaign_id, ad_id) foreign keys let the metrics endpoint JOIN
    metrics_cache and roll up spend / impressions / clicks / conversions
    per landing page.
    """

    __tablename__ = "landing_page_ad_links"

    landing_page_id = Column(
        UUIDType,
        ForeignKey("landing_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = Column(String(20), nullable=False, index=True)  # meta | google | tiktok
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ad_id = Column(
        UUIDType,
        ForeignKey("ads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    asset_group_id = Column(UUIDType, nullable=True)  # Google PMax asset_groups.id
    ad_set_id = Column(
        UUIDType,
        ForeignKey("ad_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # Google Search: ad group driving traffic to this page
    destination_url = Column(Text, nullable=False)
    utm_source = Column(String(100), nullable=True)
    utm_medium = Column(String(100), nullable=True)
    utm_campaign = Column(String(200), nullable=True)
    utm_content = Column(String(200), nullable=True)
    utm_term = Column(String(200), nullable=True)
    discovered_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
