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
    creative_id = Column(String(100), nullable=True)
    raw_data = Column(JSONType, nullable=True)
