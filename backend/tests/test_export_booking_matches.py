"""Tests for the X-API-Key booking-match export endpoints.

Locks in the rule that the export (which the KOL Engine pulls to exclude
paid-ads revenue from organic KOL revenue) returns only value-confirmed
matches by default — inferred matches are capacity guesses and must not be
used to subtract real revenue.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register every table before create_all
from app.database import get_db
from app.main import app
from app.models.api_key import ApiKey
from app.models.base import Base
from app.models.booking_match import BookingMatch
from app.services.export_auth import generate_api_key

engine = create_engine(
    "sqlite:///test_export_booking_matches.db",
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


def _api_key(db) -> str:
    plaintext, key_hash, key_prefix = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), name="KOL-Paid Ads", key_hash=key_hash, key_prefix=key_prefix))
    db.commit()
    return plaintext


def _match(db, *, confidence, revenue):
    db.add(BookingMatch(
        id=str(uuid.uuid4()), match_date=D,
        ads_revenue=revenue, matched_revenue=revenue, ads_bookings=1,
        ads_channel="google", branch="Taipei", match_result="Matched",
        confidence=confidence, matched_at=datetime.now(timezone.utc),
    ))


def _seed():
    db = TestSession()
    key = _api_key(db)
    _match(db, confidence="confirmed", revenue=1000.0)
    _match(db, confidence="confirmed", revenue=2000.0)
    _match(db, confidence="inferred", revenue=9000.0)
    db.commit()
    db.close()
    return key


def test_export_defaults_to_confirmed_only():
    key = _seed()
    resp = client.get(
        f"/api/export/booking-matches?date_from={D}&date_to={D}",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["confidence"] == "confirmed"
    assert data["total"] == 2
    assert all(it["confidence"] == "confirmed" for it in data["items"])


def test_export_all_includes_inferred():
    key = _seed()
    resp = client.get(
        f"/api/export/booking-matches?date_from={D}&date_to={D}&confidence=all",
        headers={"X-API-Key": key},
    )
    data = resp.json()["data"]
    assert data["total"] == 3
    assert {it["confidence"] for it in data["items"]} == {"confirmed", "inferred"}


def test_export_summary_defaults_to_confirmed_only():
    key = _seed()
    resp = client.get(
        f"/api/export/booking-matches/summary?date_from={D}&date_to={D}",
        headers={"X-API-Key": key},
    )
    data = resp.json()["data"]
    assert data["confidence"] == "confirmed"
    # Only the two confirmed matches (1000 + 2000 TWD) count, not the 9000 inferred.
    assert data["total_matches"] == 2
    assert data["total_bookings"] == 2


def test_export_summary_all_includes_inferred():
    key = _seed()
    resp = client.get(
        f"/api/export/booking-matches/summary?date_from={D}&date_to={D}&confidence=all",
        headers={"X-API-Key": key},
    )
    data = resp.json()["data"]
    assert data["total_matches"] == 3
    assert data["total_bookings"] == 3
