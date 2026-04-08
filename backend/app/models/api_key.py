from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String

from app.models.base import Base, TimestampMixin


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    name = Column(String(200), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hex
    key_prefix = Column(String(8), nullable=False)  # First 8 chars for identification
    is_active = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    daily_request_count = Column(Integer, nullable=False, default=0)
    daily_count_reset_at = Column(Date, nullable=True)
    created_by = Column(String(100), nullable=True)
