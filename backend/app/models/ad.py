from sqlalchemy import Column, ForeignKey, String

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class Ad(TimestampMixin, Base):
    __tablename__ = "ads"

    ad_set_id = Column(
        UUIDType,
        ForeignKey("ad_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = Column(String(20), nullable=False, index=True)
    platform_ad_id = Column(String(100), nullable=False, unique=True)
    name = Column(String(500), nullable=False)
    status = Column(String(30), nullable=False, index=True)

    # Meta only (nullable for Google/TikTok). `status` above is the ad's own
    # switch; effective_status is what the platform actually delivers — it
    # folds in the parent ad set / campaign switch and the review state, so an
    # ad can read ACTIVE here while its ad set is off. That distinction is
    # usually the answer to "why did this live-looking ad stop spending".
    effective_status = Column(String(40), nullable=True, index=True)
    # ad.preview_shareable_link — the platform's own render of the whole ad
    # (creative + copy + CTA). Long-lived, unlike the CDN asset URLs, and it is
    # the link to hand a reviewer: Meta issues it as a SHARE link (fb.me/...)
    # for people who do not administer the ad account, where an Ads Manager
    # deep link would drop them on an account picker. Meta can rotate it, so it
    # is refreshed (not appended) on every platform sync, and it dies with the
    # ad — fetch_ads stops returning archived/deleted ads, so the column simply
    # goes stale-then-absent rather than pointing at a dead page.
    preview_url = Column(String(1000), nullable=True)

    creative_id = Column(String(100), nullable=True)
    raw_data = Column(JSONType, nullable=True)
