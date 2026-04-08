from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class SpyTrackedPage(TimestampMixin, Base):
    __tablename__ = "spy_tracked_pages"

    page_id = Column(String(50), nullable=False, unique=True, index=True)
    page_name = Column(String(500), nullable=False)
    category = Column(String(100), nullable=True, index=True)  # International Chain, OTA, Boutique Hotel, Local Competitor
    country = Column(String(10), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
