from sqlalchemy import Column, Date, ForeignKey, Numeric, String

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"

    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = Column(String(20), nullable=False, index=True)
    platform_campaign_id = Column(String(100), nullable=False, unique=True)
    name = Column(String(500), nullable=False)
    status = Column(String(30), nullable=False, index=True)  # ACTIVE | PAUSED | ARCHIVED
    objective = Column(String(100), nullable=True)
    daily_budget = Column(Numeric(15, 2), nullable=True)
    lifetime_budget = Column(Numeric(15, 2), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    ta = Column(String(50), nullable=True, index=True)  # Parsed: Solo/Couple/Friend/Group/Business/Unknown
    funnel_stage = Column(String(10), nullable=True, index=True)  # Parsed: TOF/MOF/BOF/Unknown
    raw_data = Column(JSONType, nullable=True)
