from sqlalchemy import Column, String, Text

from app.models.base import Base, JSONType, TimestampMixin


class BrandIdentity(TimestampMixin, Base):
    __tablename__ = "brand_identities"

    branch_name = Column(String(100), nullable=False, unique=True, index=True)
    human_desires = Column(JSONType, nullable=False, default=list)
    brand_territory = Column(String(200), nullable=True)
    brand_promise = Column(Text, nullable=True)
    emotional_themes = Column(JSONType, nullable=False, default=list)
    never_say = Column(JSONType, nullable=False, default=list)
    always_say = Column(JSONType, nullable=False, default=list)
    feeling_target = Column(Text, nullable=True)
