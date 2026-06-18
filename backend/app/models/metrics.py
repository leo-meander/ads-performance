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
    # Numeric, not Integer: Google attributes FRACTIONAL conversions (e.g. 0.33,
    # 6.33). An Integer column rounded every daily row toward zero and wiped out
    # low-volume accounts' conversions. Meta/TikTok still write whole numbers
    # here (stored as x.00). Read paths that int()/round the SUMMED total are
    # fine — only the per-row storage needed the extra precision.
    conversions = Column(Numeric(15, 2), nullable=False, default=0)
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
    # Video engagement funnel (Meta only; Google/TikTok fills NULL or 0).
    # video_views = video_play_actions (plays triggered by an impression, Meta's
    # hook-stage counter). video_3s_views = 3s+ watchers. video_thru_plays =
    # thruplay (≥15s or full for short videos). p25/p50/p75/p100 = % watched.
    video_views = Column(Integer, nullable=False, default=0)
    video_3s_views = Column(Integer, nullable=False, default=0)
    video_thru_plays = Column(Integer, nullable=False, default=0)
    video_p25_views = Column(Integer, nullable=False, default=0)
    video_p50_views = Column(Integer, nullable=False, default=0)
    video_p75_views = Column(Integer, nullable=False, default=0)
    video_p100_views = Column(Integer, nullable=False, default=0)
    computed_at = Column(DateTime(timezone=True), nullable=True)
