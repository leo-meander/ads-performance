from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from app.models.base import Base, TimestampMixin, UUIDType


class HypothesisComboLink(Base):
    __tablename__ = "hypothesis_combo_links"

    id = Column(UUIDType, primary_key=True)
    hypothesis_id = Column(String(20), ForeignKey("creative_hypotheses.hypothesis_id", ondelete="CASCADE"), nullable=False, index=True)
    combo_id = Column(String(20), ForeignKey("ad_combos.combo_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(__import__("sqlalchemy").DateTime(timezone=True), server_default=__import__("sqlalchemy").func.now())

    __table_args__ = (UniqueConstraint("hypothesis_id", "combo_id", name="uq_hypothesis_combo"),)
