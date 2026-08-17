from sqlalchemy import (
    Column, DateTime, ForeignKey, String, UniqueConstraint,
)

from app.models.base import Base, TimestampMixin, UUIDType


class MetaAdState(TimestampMixin, Base):
    """Current delivery state of one Meta ad — status + shareable preview link.

    One row per (account, ad_id). This is a SNAPSHOT of "right now", not a
    time series: ad_daily_metrics answers "what did this ad spend on day X",
    this table answers "is that ad still running, and where do I look at it".

    Kept separate from ad_daily_metrics on purpose — status/preview belong to
    the ad, not to a day, so duplicating them across every daily row would be
    wrong the moment an ad is paused.

    Refreshed by services/meta_ad_state_sync.py, which runs alongside the daily
    ad-metrics sync (manual button + cron).
    """

    __tablename__ = "meta_ad_states"
    __table_args__ = (
        UniqueConstraint("account_id", "ad_id", name="uq_meta_ad_states_acc_ad"),
    )

    account_id = Column(
        UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Meta platform ad id, stored as a string (matches ad_daily_metrics.ad_id).
    ad_id = Column(String(64), nullable=False, index=True)
    ad_name = Column(String(500), nullable=True, index=True)

    # The ad's own switch (ACTIVE / PAUSED / ARCHIVED / DELETED).
    status = Column(String(40), nullable=True)
    # What Meta actually delivers — folds in the parent adset/campaign switch
    # and review state (ACTIVE, PAUSED, ADSET_PAUSED, CAMPAIGN_PAUSED,
    # DISAPPROVED, PENDING_REVIEW, ARCHIVED, ...). This is the one the UI shows.
    effective_status = Column(String(40), nullable=True, index=True)

    # ad.preview_shareable_link — opens Meta's own render of the ad. Long-lived
    # (unlike the CDN asset URLs), but only viewable by someone with access to
    # the ad account.
    preview_url = Column(String(1000), nullable=True)

    synced_at = Column(DateTime(timezone=True), nullable=True)
