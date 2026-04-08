from sqlalchemy import Column, Date, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class AIConversation(TimestampMixin, Base):
    __tablename__ = "ai_conversations"

    session_id = Column(UUIDType, nullable=False, index=True)
    role = Column(String(10), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    platform_filter = Column(String(20), nullable=True)
    date_filter_from = Column(Date, nullable=True)
    date_filter_to = Column(Date, nullable=True)
