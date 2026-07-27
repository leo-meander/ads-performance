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
from app.main import app
from app.models.api_key import ApiKey
from app.models.booking_match import BookingMatch
from app.services.export_auth import generate_api_key
from tests.db import TestSession

client = TestClient(app)

D = date(2026, 6, 10)


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
