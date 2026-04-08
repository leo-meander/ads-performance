from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class AutomationRule(TimestampMixin, Base):
    __tablename__ = "automation_rules"

    name = Column(String(200), nullable=False)
    platform = Column(String(20), nullable=False, index=True)  # meta | google | tiktok | all
    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conditions = Column(JSONType, nullable=False)  # [{metric, operator, threshold}]
    action = Column(String(50), nullable=False)  # pause_campaign | enable_campaign | adjust_budget | send_alert
    action_params = Column(JSONType, nullable=True)  # e.g. {budget_multiplier: 0.5}
    entity_level = Column(
        String(20), nullable=False, default="campaign", index=True,
    )  # campaign | ad_set | ad
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(100), nullable=True)
