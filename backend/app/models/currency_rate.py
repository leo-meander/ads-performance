from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Numeric, String

from app.models.base import Base


class CurrencyRate(Base):
    """Exchange rate from `currency` to USD.

    rate_to_usd = how many USD 1 unit of `currency` is worth.
    e.g. currency=VND, rate_to_usd=0.000039  → 1 VND = 0.000039 USD
         currency=USD, rate_to_usd=1
    """

    __tablename__ = "currency_rates"

    currency = Column(String(3), primary_key=True)
    rate_to_usd = Column(Numeric(20, 10), nullable=False)
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
