from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class SpySavedAd(TimestampMixin, Base):
    __tablename__ = "spy_saved_ads"

    ad_archive_id = Column(String(100), nullable=False, unique=True, index=True)
    page_id = Column(String(50), nullable=True, index=True)
    page_name = Column(String(500), nullable=True)

    # Creative content
    ad_creative_bodies = Column(JSONType, nullable=True)  # Array of body texts
    ad_creative_link_titles = Column(JSONType, nullable=True)
    ad_creative_link_captions = Column(JSONType, nullable=True)
    ad_snapshot_url = Column(String(2000), nullable=True)

    # Delivery info
    publisher_platforms = Column(JSONType, nullable=True)  # ["facebook", "instagram"]
    ad_delivery_start_time = Column(DateTime(timezone=True), nullable=True, index=True)
    ad_delivery_stop_time = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    country = Column(String(10), nullable=True, index=True)
    media_type = Column(String(20), nullable=True)  # image / video / carousel / mixin

    # User-assigned
    tags = Column(JSONType, nullable=True)  # Array of strings
    notes = Column(Text, nullable=True)
    collection = Column(String(100), nullable=True, index=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    raw_data = Column(JSONType, nullable=True)  # Full API response
