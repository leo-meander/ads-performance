from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

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

    # Crawl roll call. A cron that returns 202 tells you nothing about
    # whether a page actually yielded ads, and a competitor silently
    # returning zero looks identical to one that stopped advertising --
    # the same trap that hid a dead Meta token on the sync side. Record
    # the outcome per page so /monitor/status can name the broken one.
    last_crawl_ad_count = Column(Integer, nullable=True)
    last_crawl_error = Column(Text, nullable=True)
    monitor_enabled = Column(Boolean, nullable=False, default=True)
