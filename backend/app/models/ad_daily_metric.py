from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint

from app.models.base import Base, TimestampMixin, UUIDType


class AdDailyMetric(TimestampMixin, Base):
    """One row per (account, ad_id, day) of Meta ad-level insights.

    Stores RAW counts only — derived rates (roas, ctr, cpp, cost_per_lead,
    hook_rate, ...) are computed at read time in the ad_performance router so
    window aggregation (sum raw counts, then recompute) is always correct.

    Grain is ad_id (the Meta platform ad id, stored as a string — NOT an
    internal FK) so ads sharing an ad_name across different campaigns/adsets
    stay distinct, and each row carries the full Campaign → Ad Set → Ad name.
    """

    __tablename__ = "ad_daily_metrics"
    __table_args__ = (
        UniqueConstraint("account_id", "ad_id", "date", name="uq_ad_daily_metrics_acc_ad_date"),
    )

    account_id = Column(
        UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Meta platform identity (3 levels). Stored as strings, not FKs.
    campaign_id = Column(String(64), nullable=True, index=True)
    campaign_name = Column(String(500), nullable=True)
    adset_id = Column(String(64), nullable=True)
    adset_name = Column(String(500), nullable=True)
    ad_id = Column(String(64), nullable=False, index=True)
    ad_name = Column(String(500), nullable=True, index=True)

    date = Column(Date, nullable=False)

    # Raw counts
    spend = Column(Numeric(15, 2), nullable=True)
    impressions = Column(Integer, nullable=True)
    clicks = Column(Integer, nullable=True)
    conversions = Column(Integer, nullable=True)  # omni_purchase = bookings
    revenue = Column(Numeric(15, 2), nullable=True)
    leads = Column(Integer, nullable=True)  # lead action types
    engagement = Column(Integer, nullable=True)  # inline_post_engagement
    video_plays = Column(Integer, nullable=True)  # video_play_actions — ANY play incl. autoplay starts
    video_3s = Column(Integer, nullable=True)  # actions:video_view — 3-second plays (hook_rate numerator)
    thruplay = Column(Integer, nullable=True)
    video_p100 = Column(Integer, nullable=True)
