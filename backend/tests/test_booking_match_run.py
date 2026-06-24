"""End-to-end tests for run_matching — the capacity-assignment matcher.

The key behaviour these lock in (and the bug they guard against): a campaign
that reports N conversions whose ad-platform revenue does NOT reconstruct the
sum of the real PMS grand_totals should still match up to N real bookings. The
old subset-sum matcher returned ZERO for such a campaign, which is how 45
attributed conversions collapsed to 7 matches.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_country_metric import AdCountryMetric
from app.models.base import Base
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.reservation import Reservation
from app.services.booking_match_service import run_matching

engine = create_engine(
    "sqlite:///test_booking_match_run.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

D = date(2026, 6, 10)
WEBSITE = "Website/Booking Engine"


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    s = TestSession()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _account(db) -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="google",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Saigon", currency="VND",
    )
    db.add(acc)
    db.flush()
    return acc


def _campaign(db, acc, name="Search_Brand_VN") -> Campaign:
    c = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="google",
        platform_campaign_id=str(uuid.uuid4()), name=name, status="ACTIVE",
    )
    db.add(c)
    db.flush()
    return c


def _ad_row(db, campaign, *, country, rev=0.0, conv=0, kind="website"):
    db.add(AdCountryMetric(
        id=str(uuid.uuid4()), platform="google", campaign_id=campaign.id,
        ad_id=None, date=D, country=country,
        revenue_website=rev if kind == "website" else 0,
        revenue_offline=rev if kind == "offline" else 0,
        conversions_website=conv if kind == "website" else 0,
        conversions_offline=conv if kind == "offline" else 0,
    ))


def _res(db, num, gt, *, country_iso=None, source=WEBSITE, d=D):
    db.add(Reservation(
        id=str(uuid.uuid4()), reservation_number=num, reservation_date=d,
        grand_total=gt, country_iso=country_iso, country=country_iso,
        source=source, branch="Meander Saigon", status="confirmed",
    ))


def test_matches_n_bookings_even_when_revenue_does_not_sum(db):
    """3 conversions, ad revenue 10,000 (≠ any subset of the 1,000 bookings).
    Old matcher: 0. New matcher: 3 real bookings, real PMS revenue 3,000."""
    acc = _account(db)
    camp = _campaign(db, acc)
    _ad_row(db, camp, country="VN", rev=10000.0, conv=3)
    # 3 VN + 2 US bookings, all 1,000 — no subset sums to 10,000.
    for i in range(3):
        _res(db, f"VN{i}", 1000.0, country_iso="VN")
    for i in range(2):
        _res(db, f"US{i}", 1000.0, country_iso="US")
    db.commit()

    summary = run_matching(db, D, D)

    matches = db.query(BookingMatch).all()
    assert len(matches) == 1
    m = matches[0]
    assert m.ads_bookings == 3                      # capacity = round(conv)
    assert float(m.matched_revenue) == 3000.0        # real PMS money, not 10,000
    assert float(m.ads_revenue) == 10000.0           # platform figure kept for ref
    assert m.match_result == "Matched (combo)"
    assert m.confidence == "inferred"                # revenue didn't sum → count-based
    # Country preference: the 3 VN bookings were claimed before any US one.
    assert set(m.reservation_numbers.split(", ")) == {"VN0", "VN1", "VN2"}
    assert summary["matches_created"] == 1
    assert summary["matches_confirmed"] == 0
    assert summary["matches_inferred"] == 1


def test_capacity_floor_of_one_when_conversions_round_to_zero(db):
    """Fractional Google conversion rounding to 0 still gets 1 booking if the
    row reported revenue."""
    acc = _account(db)
    camp = _campaign(db, acc)
    _ad_row(db, camp, country="VN", rev=2000.0, conv=0)
    _res(db, "R1", 2000.0, country_iso="VN")
    db.commit()

    run_matching(db, D, D)

    m = db.query(BookingMatch).one()
    assert m.ads_bookings == 1
    assert float(m.matched_revenue) == 2000.0
    assert m.confidence == "confirmed"   # single booking value matches ads revenue


def test_no_reservation_attributed_twice_across_campaigns(db):
    """Two campaigns with capacity 2 each but only 3 bookings → 3 matched
    bookings total, none double-counted."""
    acc = _account(db)
    c1 = _campaign(db, acc, name="Search_A_VN")
    c2 = _campaign(db, acc, name="Search_B_VN")
    _ad_row(db, c1, country="VN", rev=9000.0, conv=2)   # higher rev → processed first
    _ad_row(db, c2, country="VN", rev=1000.0, conv=2)
    for i in range(3):
        _res(db, f"R{i}", 1000.0, country_iso="VN")
    db.commit()

    run_matching(db, D, D)

    matches = db.query(BookingMatch).all()
    total_bookings = sum(m.ads_bookings for m in matches)
    all_nums = [n for m in matches for n in m.reservation_numbers.split(", ")]
    assert total_bookings == 3
    assert sorted(all_nums) == ["R0", "R1", "R2"]       # each booking used once


def test_google_purchase_matches_offline_booking_too(db):
    """Google reports one combined PURCHASE total we don't split, so a Google
    row may match an OTA/offline booking (not just Website/Booking-Engine)."""
    acc = _account(db)
    camp = _campaign(db, acc)
    _ad_row(db, camp, country="VN", rev=1000.0, conv=1, kind="website")
    _res(db, "OTA1", 1000.0, country_iso="VN", source="Booking.com")
    db.commit()

    run_matching(db, D, D)

    m = db.query(BookingMatch).one()
    assert m.reservation_numbers == "OTA1"
    assert float(m.matched_revenue) == 1000.0
    assert m.confidence == "confirmed"


def test_meta_website_row_does_not_claim_offline_booking(db):
    """Meta keeps website vs offline split, so a Meta website row never matches
    an OTA/offline booking."""
    acc = _account(db)
    acc.platform = "meta"
    camp = _campaign(db, acc)
    camp.platform = "meta"
    # Meta row carries platform="meta" on the AdCountryMetric.
    db.add(AdCountryMetric(
        id=str(uuid.uuid4()), platform="meta", campaign_id=camp.id,
        ad_id=None, date=D, country="VN",
        revenue_website=1000.0, revenue_offline=0,
        conversions_website=1, conversions_offline=0,
    ))
    _res(db, "OTA1", 1000.0, country_iso="VN", source="Booking.com")
    db.commit()

    run_matching(db, D, D)

    assert db.query(BookingMatch).count() == 0
