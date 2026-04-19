from sqlalchemy import Column, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint

from app.models.base import Base, TimestampMixin


class GoogleSeasonalityEvent(TimestampMixin, Base):
    """Per-country hotel seasonality calendar used by SEASONALITY_* detectors.

    Seeded in migrations 011 (VN) + 012 (JP/TW + inbound source markets).
    Detectors evaluate each campaign against the union of the branch's home
    country and the campaign's currently targeted countries — a Vietnam Tet
    event must NOT fire for an Osaka PMax campaign, etc.
    """

    __tablename__ = "google_seasonality_events"
    __table_args__ = (
        UniqueConstraint("country_code", "event_key", name="uq_google_seasonality_country_event"),
    )

    country_code = Column(String(2), nullable=False, index=True)  # ISO-2: VN / JP / TW / KR / HK / SG / US / AU
    event_key = Column(String(40), nullable=False)
    name = Column(String(120), nullable=False)
    start_month = Column(SmallInteger, nullable=False)
    start_day = Column(SmallInteger, nullable=False)
    end_month = Column(SmallInteger, nullable=False)
    end_day = Column(SmallInteger, nullable=False)
    lead_time_days = Column(Integer, nullable=False)
    budget_bump_pct_min = Column(Numeric(5, 2), nullable=True)
    budget_bump_pct_max = Column(Numeric(5, 2), nullable=True)
    tcpa_adjust_pct_min = Column(Numeric(5, 2), nullable=True)
    tcpa_adjust_pct_max = Column(Numeric(5, 2), nullable=True)
    notes = Column(Text, nullable=True)
