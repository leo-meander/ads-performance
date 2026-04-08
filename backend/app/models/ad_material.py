from sqlalchemy import Column, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class AdMaterial(TimestampMixin, Base):
    __tablename__ = "ad_materials"

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(String(10), nullable=False, unique=True, index=True)  # MAT-001
    material_type = Column(String(20), nullable=False, index=True)  # image | video | carousel
    file_url = Column(Text, nullable=False)  # Drive/URL link — never uploaded to platform
    description = Column(Text, nullable=True)
    target_audience = Column(String(30), nullable=True, index=True)  # Solo | Couple | Family | Group
    derived_verdict = Column(String(10), nullable=True)  # WIN | TEST | LOSE — READ-ONLY from combos
