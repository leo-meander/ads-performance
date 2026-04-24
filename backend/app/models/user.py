from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class User(Base, TimestampMixin):
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(200), nullable=False)
    password_hash = Column(Text, nullable=False)
    roles = Column(JSONType, nullable=False, default=list)  # ['admin'], ['creator'], ['reviewer'], etc.
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    notification_email = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)

    permissions = relationship(
        "UserPermission",
        backref="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
