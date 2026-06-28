"""Tests for /api/booking-matches/campaign-insights.

Locks in the campaign-segmented aggregation that powers the Booking-from-Ads
intelligence panels: per-campaign bookings / cancel rate / lead time / rooms,
and the target-vs-actual country flow (exact / cross / unknown) with leakage.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register every table before create_all
from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.base import Base
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.ad_country_metric import AdCountryMetric
from app.models.reservation import Reservation
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password
from app.services.booking_match_service import run_matching

engine = create_engine(
    "sqlite:///test_campaign_insights.db",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)

D = date(2026, 6, 10)
WEBSITE = "Website/Booking Engine"


@pytest.fixture(autouse=True)
def setup_db():
    # Install our engine override per-test and restore afterwards, so this
    # module's TestClient engine isn't clobbered by another test file that also
    # overrides get_db at import time (and vice-versa).
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _admin_headers() -> dict:
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Admin",
        password_hash=hash_password("pass"),
        roles=["admin"],
    )
    db.add(user)
    db.commit()
    uid, roles = user.id, user.roles
    db.close()
    return {"Authorization": f"Bearer {create_access_token(uid, roles)}"}


def _res(db, num, gt, *, country_iso, source, status, room, lead, nights=1):
    db.add(Reservation(
        id=str(uuid.uuid4()), reservation_number=num, reservation_date=D,
        check_in_date=D + timedelta(days=lead), grand_total=gt,
        country_iso=country_iso, country=country_iso, source=source,
        branch="Meander Saigon", status=status, room_type=room, nights=nights,
    ))


def _seed(db):
    """One Google campaign targeting VN, capacity 4, 4 real bookings:
      R1 VN website confirmed (lead 5)   -> exact
      R2 VN website canceled  (lead 2)   -> exact, cancelled
      R3 US website confirmed (lead 20)  -> cross-country
      R4 unknown OTA confirmed (lead 1)  -> null country
    """
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="google",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Saigon", currency="VND",
    )
    db.add(acc)
    db.flush()
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="google",
        platform_campaign_id=str(uuid.uuid4()), name="Search_Brand_VN", status="ACTIVE",
    )
    db.add(camp)
    db.flush()
    # Revenue that no subset reconstructs -> inferred; capacity 4 claims all.
    db.add(AdCountryMetric(
        id=str(uuid.uuid4()), platform="google", campaign_id=camp.id, ad_id=None,
        date=D, country="VN", revenue_website=10_000_000.0, revenue_offline=0,
        conversions_website=4, conversions_offline=0,
    ))
    _res(db, "R1", 1000.0, country_iso="VN", source=WEBSITE, status="confirmed", room="Dorm", lead=5)
    _res(db, "R2", 1000.0, country_iso="VN", source=WEBSITE, status="canceled", room="Dorm", lead=2)
    _res(db, "R3", 3000.0, country_iso="US", source=WEBSITE, status="confirmed", room="Suite", lead=20)
    _res(db, "R4", 2000.0, country_iso=None, source="Booking.com", status="confirmed", room="Suite", lead=1)
    db.commit()


def test_campaign_insights_segments_by_campaign():
    db = TestSession()
    _seed(db)
    run_matching(db, D, D)
    db.commit()
    db.close()

    resp = client.get(
        f"/api/booking-matches/campaign-insights?date_from={D}&date_to={D}",
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"], body

    data = body["data"]
    assert len(data["campaigns"]) == 1
    c = data["campaigns"][0]
    assert c["campaign_name"] == "Search_Brand_VN"
    assert c["channel"] == "google"
    assert c["target_country"] == "VN"
    assert c["bookings"] == 4
    assert c["cancel_count"] == 1
    assert c["cancel_rate"] == pytest.approx(25.0)
    assert c["website_bookings"] == 3
    assert c["offline_bookings"] == 1
    assert c["avg_lead_time"] == pytest.approx((5 + 2 + 20 + 1) / 4)
    # Rooms ranked by revenue: Suite (5000) before Dorm (2000).
    assert [r["room_type"] for r in c["top_rooms"]] == ["Suite", "Dorm"]
    actual = {a["country"]: a["bookings"] for a in c["top_actual_countries"]}
    assert actual == {"VN": 2, "US": 1, "Unknown": 1}


def test_campaign_insights_country_flow_and_leakage():
    db = TestSession()
    _seed(db)
    run_matching(db, D, D)
    db.commit()
    db.close()

    resp = client.get(
        f"/api/booking-matches/campaign-insights?date_from={D}&date_to={D}",
        headers=_admin_headers(),
    )
    data = resp.json()["data"]

    totals = data["totals"]
    assert totals["country_exact"] == 2     # R1, R2 (VN target == VN guest)
    assert totals["country_cross"] == 1     # R3 (VN target, US guest)
    assert totals["country_unknown"] == 1   # R4 (no guest country)
    # Leakage = cross / (exact + cross) = 1 / 3.
    assert totals["leakage_rate"] == pytest.approx(100 / 3)
    assert totals["cancel_rate"] == pytest.approx(25.0)

    # Flow rows cover every (target, actual) pair, bookings preserved.
    pairs = {(f["target"], f["actual"]): f["bookings"] for f in data["country_flow"]}
    assert pairs[("VN", "VN")] == 2
    assert pairs[("VN", "US")] == 1
    assert pairs[("VN", "Unknown")] == 1


def test_campaign_insights_empty_window_is_clean():
    resp = client.get(
        "/api/booking-matches/campaign-insights?date_from=2020-01-01&date_to=2020-01-02",
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["campaigns"] == []
    assert data["country_flow"] == []
    assert data["totals"]["bookings"] == 0
    assert data["totals"]["leakage_rate"] == 0


def _raw_match(db, *, confidence, revenue, bookings):
    db.add(BookingMatch(
        id=str(uuid.uuid4()), match_date=D,
        ads_revenue=revenue, matched_revenue=revenue, ads_bookings=bookings,
        ads_channel="google", branch="Taipei", match_result="Matched",
        confidence=confidence, matched_at=datetime.now(timezone.utc),
    ))


def test_summary_confidence_filter_scopes_kpi_cards():
    # 2 confirmed bookings + 3 inferred. The summary KPI cards must reflect the
    # confidence filter (regression: /summary ignored it, so the cards stayed
    # at the unfiltered totals while the table filtered).
    db = TestSession()
    _raw_match(db, confidence="confirmed", revenue=1000.0, bookings=2)
    _raw_match(db, confidence="inferred", revenue=9000.0, bookings=3)
    db.commit()
    db.close()
    headers = _admin_headers()

    unfiltered = client.get(
        f"/api/booking-matches/summary?date_from={D}&date_to={D}", headers=headers,
    ).json()["data"]
    assert unfiltered["total_bookings"] == 5

    confirmed = client.get(
        f"/api/booking-matches/summary?date_from={D}&date_to={D}&confidence=confirmed",
        headers=headers,
    ).json()["data"]
    assert confirmed["total_matches"] == 1
    assert confirmed["total_bookings"] == 2
    conf_tiers = {c["confidence"] for c in confirmed["by_confidence"]}
    assert conf_tiers == {"confirmed"}
