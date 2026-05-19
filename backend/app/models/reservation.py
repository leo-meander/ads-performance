from sqlalchemy import Column, Date, Integer, Numeric, String

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class Reservation(TimestampMixin, Base):
    __tablename__ = "reservations"

    reservation_number = Column(String(50), nullable=False, unique=True, index=True)
    reservation_date = Column(Date, nullable=True, index=True)
    check_in_date = Column(Date, nullable=True)
    check_out_date = Column(Date, nullable=True)
    grand_total = Column(Numeric(15, 2), nullable=True)
    country = Column(String(100), nullable=True, index=True)
    country_iso = Column(String(2), nullable=True, index=True)
    name = Column(String(300), nullable=True)
    email = Column(String(300), nullable=True)
    status = Column(String(50), nullable=True, index=True)
    source = Column(String(100), nullable=True, index=True)
    room_type = Column(String(200), nullable=True)
    rate_plan_name = Column(String(300), nullable=True)
    branch = Column(String(100), nullable=False, index=True)
    nights = Column(Integer, nullable=True)
    adults = Column(Integer, nullable=True)
    raw_data = Column(JSONType, nullable=True)
