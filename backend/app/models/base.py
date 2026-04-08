import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Use String(36) for UUID to be SQLite-compatible
# On PostgreSQL, you can switch to native UUID type
UUIDType = String(36)


class TimestampMixin:
    id = Column(UUIDType, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# Re-export JSON for models to use (works on both SQLite and PostgreSQL)
JSONType = JSON
