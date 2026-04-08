from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class ActionLog(TimestampMixin, Base):
    """Immutable record of every action the system has taken. Never deleted."""

    __tablename__ = "action_logs"

    rule_id = Column(
        UUIDType,
        ForeignKey("automation_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ad_set_id = Column(
        UUIDType,
        ForeignKey("ad_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ad_id = Column(
        UUIDType,
        ForeignKey("ads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform = Column(String(20), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    action_params = Column(JSONType, nullable=True)
    triggered_by = Column(String(20), nullable=False)  # rule | manual | api
    metrics_snapshot = Column(JSONType, nullable=True)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=False)
