from sqlalchemy import Boolean, Column, ForeignKey, Numeric, String

from app.models.base import Base, TimestampMixin, UUIDType


class CampaignAutoConfig(Base, TimestampMixin):
    __tablename__ = "campaign_auto_configs"

    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country = Column(String(2), nullable=False, index=True)  # ISO country code: VN, TW, AU, JP
    ta = Column(String(20), nullable=False, index=True)  # Solo | Couple | Friend | Group | Business
    language = Column(String(10), nullable=False)  # vi | en | zh | ja
    campaign_name_template = Column(String(500), nullable=False)  # e.g. 'Mason_{BRANCH}_{FUNNEL} {TA} {COUNTRY}'
    default_objective = Column(String(100), nullable=False, default="CONVERSIONS")
    default_daily_budget = Column(Numeric(15, 2), nullable=False)
    default_funnel_stage = Column(String(10), nullable=False, default="TOF")  # TOF | MOF
    is_active = Column(Boolean, nullable=False, default=True)
