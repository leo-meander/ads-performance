from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from app.models.base import Base, TimestampMixin, UUIDType


class MetricsCache(TimestampMixin, Base):
    __tablename__ = "metrics_cache"

    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ad_set_id = Column(
        UUIDType,
        ForeignKey("ad_sets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ad_id = Column(
        UUIDType,
        ForeignKey("ads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    platform = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    spend = Column(Numeric(15, 2), nullable=False, default=0)
    impressions = Column(Integer, nullable=False, default=0)
    clicks = Column(Integer, nullable=False, default=0)
    # Meta only: clicks that specifically went to the destination link. Meta
    # returns this as `inline_link_clicks` in the Insights API. For landing-
    # page traffic analysis this is the correct denominator (clicks inflates
    # with video plays, profile taps, likes). Google Ads doesn't distinguish
    # — we mirror `clicks` into this column during sync so reads are uniform.
    link_clicks = Column(Integer, nullable=False, default=0)
    ctr = Column(Numeric(8, 6), nullable=True)  # clicks / impressions
    conversions = Column(Integer, nullable=False, default=0)
    revenue = Column(Numeric(15, 2), nullable=False, default=0)
    revenue_website = Column(Numeric(15, 2), nullable=False, default=0)
    revenue_offline = Column(Numeric(15, 2), nullable=False, default=0)
    roas = Column(Numeric(8, 4), nullable=True)  # revenue / spend
    cpa = Column(Numeric(15, 2), nullable=True)  # spend / conversions
    cpc = Column(Numeric(15, 2), nullable=True)  # spend / clicks
    frequency = Column(Numeric(8, 4), nullable=True)  # impressions / reach (Meta only)
    add_to_cart = Column(Integer, nullable=False, default=0)
    checkouts = Column(Integer, nullable=False, default=0)  # initiate_checkout
    searches = Column(Integer, nullable=False, default=0)
    leads = Column(Integer, nullable=False, default=0)
    landing_page_views = Column(Integer, nullable=False, default=0)
    computed_at = Column(DateTime(timezone=True), nullable=True)
