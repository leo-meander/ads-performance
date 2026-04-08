from sqlalchemy import Boolean, Column, String, Text

from app.models.base import Base, TimestampMixin


class AdAccount(TimestampMixin, Base):
    __tablename__ = "ad_accounts"

    platform = Column(String(20), nullable=False, index=True)  # meta | google | tiktok
    account_id = Column(String(100), nullable=False, unique=True)  # platform native ID
    account_name = Column(String(200), nullable=False)
    currency = Column(String(3), nullable=False, default="VND")
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    access_token_enc = Column(Text, nullable=True)  # encrypted OAuth token
