from sqlalchemy import Boolean, Column, ForeignKey, String

from app.models.base import Base, TimestampMixin, UUIDType


class BranchKeypoint(TimestampMixin, Base):
    __tablename__ = "branch_keypoints"

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)  # location | amenity | experience | value
    title = Column(String(200), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
