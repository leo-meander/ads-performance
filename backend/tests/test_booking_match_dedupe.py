"""Integration tests for run_matching: cross-row reservation de-duplication.

Meta's attribution window reports the same conversion on multiple ad-rows
(same ad on D and D+1, or different ads on the same day with the same
attributed amount). Before the fix the matcher would attribute the same
reservation to every one of those ad-rows — inflating "matched bookings"
and producing duplicates in the dashboard.

The fix: claim reservations globally per run_matching call. Pass A (same-day)
runs first so the highest-confidence pairing wins the booking; pass B
(±1 day fallback) can only consume what's left.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.ad_set import AdSet
from app.models.base import Base
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.reservation import Reservation
from app.services.booking_match_service import run_matching


engine = create_engine(
    "sqlite:///test_booking_match_dedupe.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _account(db, name="Meander Taipei") -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name=name, currency="TWD",
    )
    db.add(acc)
    db.flush()
    return acc


def _campaign(db, account_id: str, name: str) -> Campaign:
    c = Campaign(
        id=str(uuid.uuid4()), account_id=account_id, platform="meta",
        platform_campaign_id=f"camp_{uuid.uuid4().hex[:8]}",
        name=name, status="ACTIVE",
    )
    db.add(c)
    db.flush()
    return c


def _ad(db, account_id: str, campaign_id: str, name: str) -> Ad:
    adset = AdSet(
        id=str(uuid.uuid4()), campaign_id=campaign_id, account_id=account_id,
        platform="meta", platform_adset_id=f"as_{uuid.uuid4().hex[:8]}",
        name=name, status="ACTIVE",
    )
    db.add(adset)
    db.flush()
    a = Ad(
        id=str(uuid.uuid4()), ad_set_id=adset.id, campaign_id=campaign_id,
        account_id=account_id, platform="meta",
        platform_ad_id=f"ad_{uuid.uuid4().hex[:8]}",
        name=name, status="ACTIVE",
    )
    db.add(a)
    db.flush()
    return a


def _ad_row(
    db, *, campaign_id, ad_id, d: date, country: str, revenue: float,
    conversions: int = 1, kind: str = "website",
):
    """Insert one ad_country_metric row. Default = website-source revenue."""
    rev_web = Decimal(str(revenue)) if kind == "website" else Decimal("0")
    rev_off = Decimal(str(revenue)) if kind == "offline" else Decimal("0")
    db.add(AdCountryMetric(
        platform="meta", campaign_id=campaign_id, ad_id=ad_id,
        date=d, country=country, spend=Decimal("100"),
        impressions=1000, clicks=10,
        revenue_website=rev_web, revenue_offline=rev_off,
        conversions_website=conversions if kind == "website" else 0,
        conversions_offline=conversions if kind == "offline" else 0,
    ))


def _reservation(
    db, *, number: str, d: date, total: float,
    country_iso: str | None = "TW",
    source: str = "Website/Booking Engine",
    branch: str = "Meander Taipei",
):
    db.add(Reservation(
        id=str(uuid.uuid4()),
        reservation_number=number,
        reservation_date=d,
        grand_total=Decimal(str(total)),
        country=country_iso or "Taiwan",
        country_iso=country_iso,
        name=f"Guest {number}",
        source=source,
        branch=branch,
        status="confirmed",
    ))


class TestReservationClaim:
    def test_same_reservation_not_double_attributed_across_adjacent_days(self):
        """Meta reports the same conversion on D and D+1 (7d attribution
        window). Before the fix, both ad-rows matched the same reservation.
        After the fix, only the same-day row wins; the D+1 row finds nothing."""
        db = TestSession()
        try:
            acc = _account(db)
            camp = _campaign(db, acc.id, "Mason_TPE_[TOF] Landing page Solo TW")
            ad = _ad(db, acc.id, camp.id, "TW_Solo_Landing")

            # One real booking on 2026-05-26 for 1,440 TWD.
            _reservation(db, number="R-REAL", d=date(2026, 5, 26), total=1440.0)

            # Meta reports the same revenue on TWO consecutive days.
            _ad_row(db, campaign_id=camp.id, ad_id=ad.id,
                    d=date(2026, 5, 26), country="TW", revenue=1440.0)
            _ad_row(db, campaign_id=camp.id, ad_id=ad.id,
                    d=date(2026, 5, 27), country="TW", revenue=1440.0)
            db.commit()

            summary = run_matching(db, date(2026, 5, 25), date(2026, 5, 28))

            matches = db.query(BookingMatch).all()
            assert len(matches) == 1, (
                f"expected exactly one match (claim should block re-use), got "
                f"{len(matches)}: {[(m.match_date, m.reservation_numbers) for m in matches]}"
            )
            # The same-day row (5-26) wins because pass A runs first.
            assert matches[0].match_date == date(2026, 5, 26)
            assert matches[0].reservation_numbers == "R-REAL"
            assert summary["matches_created"] == 1
            assert summary["reservations_claimed"] == 1
        finally:
            db.close()

    def test_two_distinct_ads_distinct_amounts_each_get_own_match(self):
        """Sanity: when two ad-rows have distinct amounts and there's a matching
        booking for each, the claim mechanism doesn't break per-ad attribution."""
        db = TestSession()
        try:
            acc = _account(db)
            camp = _campaign(db, acc.id, "Mason_TPE_[TOF] Solo TW")
            ad_a = _ad(db, acc.id, camp.id, "TW_Solo_A")
            ad_b = _ad(db, acc.id, camp.id, "TW_Solo_B")

            _reservation(db, number="R-A", d=date(2026, 5, 26), total=1440.0)
            _reservation(db, number="R-B", d=date(2026, 5, 26), total=2200.0)

            _ad_row(db, campaign_id=camp.id, ad_id=ad_a.id,
                    d=date(2026, 5, 26), country="TW", revenue=1440.0)
            _ad_row(db, campaign_id=camp.id, ad_id=ad_b.id,
                    d=date(2026, 5, 26), country="TW", revenue=2200.0)
            db.commit()

            run_matching(db, date(2026, 5, 25), date(2026, 5, 28))

            matches = db.query(BookingMatch).all()
            attributed = sorted(m.reservation_numbers for m in matches)
            assert attributed == ["R-A", "R-B"], (
                f"each ad-row should win its own reservation, got {attributed}"
            )
        finally:
            db.close()


class TestCountryTier3Gating:
    def test_refuses_cross_country_match_when_same_country_candidate_exists(self):
        """Same-day Taipei booking from a TW guest with the WRONG amount, plus
        a US guest with the right amount. Old behaviour: matched US (tier-3
        fallback). New behaviour: refuses — same-country signal gates tier-3."""
        db = TestSession()
        try:
            acc = _account(db)
            camp = _campaign(db, acc.id, "Mason_TPE_[TOF] Solo TW")
            ad = _ad(db, acc.id, camp.id, "TW_Solo")

            # Wrong-amount TW booking (gates tier-3) + right-amount US booking.
            _reservation(db, number="R-TW-WRONG", d=date(2026, 5, 26),
                         total=500.0, country_iso="TW")
            _reservation(db, number="R-US-RIGHT", d=date(2026, 5, 26),
                         total=1440.0, country_iso="US")

            _ad_row(db, campaign_id=camp.id, ad_id=ad.id,
                    d=date(2026, 5, 26), country="TW", revenue=1440.0)
            db.commit()

            run_matching(db, date(2026, 5, 25), date(2026, 5, 28))

            assert db.query(BookingMatch).count() == 0, (
                "tier-3 should not fire when a same-country candidate exists "
                "in the window — better to miss than mis-attribute"
            )
        finally:
            db.close()

    def test_falls_back_to_cross_country_when_no_same_country_candidate(self):
        """No TW guest at all → tier-3 fallback is allowed."""
        db = TestSession()
        try:
            acc = _account(db)
            camp = _campaign(db, acc.id, "Mason_TPE_[TOF] Solo TW")
            ad = _ad(db, acc.id, camp.id, "TW_Solo")

            _reservation(db, number="R-US", d=date(2026, 5, 26),
                         total=1440.0, country_iso="US")

            _ad_row(db, campaign_id=camp.id, ad_id=ad.id,
                    d=date(2026, 5, 26), country="TW", revenue=1440.0)
            db.commit()

            run_matching(db, date(2026, 5, 25), date(2026, 5, 28))

            matches = db.query(BookingMatch).all()
            assert len(matches) == 1
            assert matches[0].reservation_numbers == "R-US"
            assert matches[0].country_match_method == "cross_country"
        finally:
            db.close()
