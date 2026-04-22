from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Numeric, String

from app.models.base import Base


class CurrencyRate(Base):
    """Exchange rate from `currency` to VND (base currency).

    rate_to_vnd = how many VND 1 unit of `currency` is worth.
    e.g. currency=USD, rate_to_vnd=25400    → 1 USD = 25,400 VND
         currency=TWD, rate_to_vnd=780      → 1 TWD = 780 VND
         currency=VND, rate_to_vnd=1
    """

    __tablename__ = "currency_rates"

    currency = Column(String(3), primary_key=True)
    rate_to_vnd = Column(Numeric(20, 10), nullable=False)
    updated_by = Column(String(100), nullable=True)
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
