from sqlalchemy import Column, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class AdCopy(TimestampMixin, Base):
    __tablename__ = "ad_copies"

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    copy_id = Column(String(10), nullable=False, unique=True, index=True)  # CPY-001
    target_audience = Column(String(30), nullable=False, index=True)  # Solo | Couple | Family | Group
    angle_id = Column(String(10), ForeignKey("ad_angles.angle_id", ondelete="SET NULL"), nullable=True, index=True)
    headline = Column(String(500), nullable=False)
    body_text = Column(Text, nullable=False)
    cta = Column(String(200), nullable=True)  # Call to action
    language = Column(String(10), nullable=False, default="en")  # en | vi | zh | ja
    derived_verdict = Column(String(10), nullable=True)  # WIN | TEST | LOSE — READ-ONLY from combos
