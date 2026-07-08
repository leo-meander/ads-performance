from sqlalchemy import Boolean, Column, Integer, Numeric, String, Text

from app.models.base import Base, JSONType, TimestampMixin


class CreativePrinciple(TimestampMixin, Base):
    __tablename__ = "creative_principles"

    principle_id = Column(String(20), nullable=False, unique=True, index=True)
    branch_name = Column(String(100), nullable=True, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    anti_principle = Column(Text, nullable=True)  # the opposite / what NOT to do
    human_desire = Column(String(100), nullable=True, index=True)
    applicable_markets = Column(JSONType, nullable=True)   # [] = all markets
    applicable_ta = Column(JSONType, nullable=True)        # [] = all TAs
    confidence_score = Column(Numeric(5, 2), nullable=True, default=0)
    experiment_count = Column(Integer, nullable=True, default=0)
    validated_count = Column(Integer, nullable=True, default=0)
    refuted_count = Column(Integer, nullable=True, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(200), nullable=True)
