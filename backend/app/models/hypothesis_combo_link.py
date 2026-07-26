import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, func

from app.models.base import Base, UUIDType


class HypothesisComboLink(Base):
    """Junction table — a hypothesis can be tested by many combos and a combo
    can serve many hypotheses."""

    __tablename__ = "hypothesis_combo_links"

    # The PG table (migration 061) has a gen_random_uuid() column default; the
    # id is generated Python-side so create_all also works on the SQLite test DB
    # (sqlite can't parse a function call in DEFAULT).
    id = Column(UUIDType, primary_key=True, default=lambda: str(uuid.uuid4()))
    hypothesis_id = Column(String(20), ForeignKey("creative_hypotheses.hypothesis_id", ondelete="CASCADE"), nullable=False, index=True)
    combo_id = Column(String(20), ForeignKey("ad_combos.combo_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("hypothesis_id", "combo_id", name="uq_hypothesis_combo"),)
