from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from app.models.base import Base, TimestampMixin, UUIDType


class BookingMatch(TimestampMixin, Base):
    __tablename__ = "booking_matches"

    match_date = Column(Date, nullable=False, index=True)
    # ads_revenue: revenue the ad platform reported for the campaign row (kept
    # for reference / diagnostics). matched_revenue: the real PMS grand_total of
    # the reservations we assigned to this row — the ground-truth money booked,
    # and what the dashboard reports as "Matched Revenue".
    ads_revenue = Column(Numeric(15, 2), nullable=False)
    matched_revenue = Column(Numeric(15, 2), nullable=False, default=0)
    ads_bookings = Column(Integer, nullable=False, default=1)
    ads_country = Column(String(100), nullable=True)
    ads_channel = Column(String(20), nullable=True)
    campaign_name = Column(String(500), nullable=True)
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ad_id = Column(UUIDType, nullable=True, index=True)
    ad_name = Column(String(500), nullable=True)
    purchase_kind = Column(String(20), nullable=True)  # 'website' or 'offline'
    reservation_ids = Column(String(1000), nullable=True)
    reservation_numbers = Column(String(1000), nullable=True)
    guest_names = Column(String(1000), nullable=True)
    guest_emails = Column(String(1000), nullable=True)
    reservation_statuses = Column(String(500), nullable=True)
    room_types = Column(String(1000), nullable=True)
    rate_plans = Column(String(1000), nullable=True)
    reservation_sources = Column(String(500), nullable=True)
    matched_country = Column(String(200), nullable=True)
    country_match_method = Column(String(30), nullable=True)
    branch = Column(String(100), nullable=True, index=True)
    match_result = Column(String(50), nullable=False, index=True)
    # confidence: "confirmed" = the matched reservations' grand_totals sum to the
    # ads revenue within tolerance (value AND count agree). "inferred" = matched
    # by capacity/count only (the platform's conversion count is the booking
    # budget; revenue did not line up — common because attribution is fractional).
    confidence = Column(String(20), nullable=True, index=True)
    matched_at = Column(DateTime(timezone=True), nullable=False)
