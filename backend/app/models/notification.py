from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    user_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(50), nullable=False)  # REVIEW_REQUESTED | COMBO_APPROVED | COMBO_REJECTED | LAUNCH_FAILED
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    reference_id = Column(UUIDType, nullable=True, index=True)  # combo_approval.id
    reference_type = Column(String(50), nullable=True)  # "combo_approval"
    is_read = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
