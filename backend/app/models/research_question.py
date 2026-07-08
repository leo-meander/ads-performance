from sqlalchemy import Boolean, Column, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class ResearchQuestion(TimestampMixin, Base):
    __tablename__ = "research_questions"

    question_id = Column(String(20), nullable=False, unique=True, index=True)
    branch_name = Column(String(100), nullable=True, index=True)
    market = Column(String(10), nullable=True)
    target_audience = Column(String(100), nullable=True)
    question = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    # open | in_progress | answered | archived
    priority = Column(String(10), nullable=True, default="medium")
    # low | medium | high
    created_by = Column(String(200), nullable=True)
