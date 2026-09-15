"""Tests for the check-in / check-out columns on GET /api/booking-matches.

The stay window lives on the reservation, not on the match row, so the list
endpoint joins it back at read time. Two things have to hold: the dates must
line up positionally with reservation_numbers (a match can own several
reservations, and the table renders these columns side by side), and a match
whose reservations are missing or dateless must degrade to blanks rather than
dropping out of the list.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from app.main import app
from app.models.booking_match import BookingMatch
from app.models.reservation import Reservation
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password
from tests.db import TestSession

client = TestClient(app)

D = date(2026, 6, 10)


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


def _res(db, num, check_in, check_out, *, rate_plan=None, room_type=None):
    db.add(Reservation(
        id=str(uuid.uuid4()), reservation_number=num, reservation_date=D,
        check_in_date=check_in, check_out_date=check_out,
        grand_total=1000, branch="Meander Saigon", status="confirmed",
        rate_plan_name=rate_plan, room_type=room_type,
    ))


def _match(db, numbers, names, *, rate_plans=None):
    db.add(BookingMatch(
        id=str(uuid.uuid4()), match_date=D,
        ads_revenue=1000, matched_revenue=1000, ads_bookings=len(numbers.split(", ")),
        ads_channel="google", branch="Saigon", match_result="Matched",
        confidence="confirmed", reservation_numbers=numbers, guest_names=names,
        rate_plans=rate_plans, matched_at=datetime.now(timezone.utc),
    ))


def _fetch(headers):
    resp = client.get(
        f"/api/booking-matches?date_from={D}&date_to={D}", headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True, body["error"]
    return body["data"]["items"]


def test_stay_dates_align_with_reservation_numbers():
    """A match owning three reservations returns three dates, in that order."""
    db = TestSession()
    # Seeded out of order on purpose: the join must follow reservation_numbers,
    # not whatever order the database hands the reservations back in.
    _res(db, "R3", date(2026, 6, 20), date(2026, 6, 23))
    _res(db, "R1", date(2026, 6, 12), date(2026, 6, 14))
    _res(db, "R2", date(2026, 6, 15), date(2026, 6, 16))
    _match(db, "R1, R2, R3", "Ann, Bob, Cara")
    db.commit()
    db.close()

    items = _fetch(_admin_headers())
    assert len(items) == 1
    item = items[0]
    assert item["check_in_dates"] == "2026-06-12, 2026-06-15, 2026-06-20"
    assert item["check_out_dates"] == "2026-06-14, 2026-06-16, 2026-06-23"
    # Positional alignment with the columns the table renders beside them.
    assert item["reservation_numbers"].split(", ") == ["R1", "R2", "R3"]
    assert len(item["check_in_dates"].split(", ")) == len(item["guest_names"].split(", "))


def test_missing_and_dateless_reservations_render_blank():
    """Unknown number -> blank slot; known reservation with no dates -> blank."""
    db = TestSession()
    _res(db, "R1", date(2026, 6, 12), date(2026, 6, 14))
    _res(db, "R2", None, None)          # in the PMS, but no stay window on file
    _match(db, "R1, R2, GONE", "Ann, Bob, Cara")
    db.commit()
    db.close()

    items = _fetch(_admin_headers())
    assert len(items) == 1
    # Slots are held, so column N still lines up with reservation N.
    assert items[0]["check_in_dates"] == "2026-06-12, , "
    assert items[0]["check_out_dates"] == "2026-06-14, , "


def test_match_with_no_reservations_still_listed():
    """An unmatched-style row has no reservation_numbers — it must not vanish."""
    db = TestSession()
    _match(db, "", "")
    db.commit()
    db.close()

    items = _fetch(_admin_headers())
    assert len(items) == 1
    assert items[0]["check_in_dates"] == ""
    assert items[0]["check_out_dates"] == ""


# --- rate plan, re-resolved at read time ------------------------------------
# booking_matches.rate_plans was written by the matcher at match time, back
# when the plan was mis-derived from room_type. The list endpoint re-resolves
# it from the reservations so history reads correctly without a matcher re-run.

def test_rate_plans_are_refreshed_from_the_reservations():
    db = TestSession()
    _res(db, "R1", D, D, rate_plan="EARLY26 2 NIGHTS")
    _res(db, "R2", D, D, rate_plan="EARLY26 3+ NIGHTS")
    _match(db, "R1, R2", "Ann, Bob", rate_plans="FLEX, FLEX")  # what the matcher stored
    db.commit()
    db.close()

    items = _fetch(_admin_headers())
    assert items[0]["rate_plans"] == "EARLY26 2 NIGHTS, EARLY26 3+ NIGHTS"


def test_rate_plan_falls_back_to_room_type_tag():
    """No stored plan, but the room_type carries a hand-typed KOL tag."""
    db = TestSession()
    _res(db, "R1", D, D, room_type="Standard Twin (KOL_whatweieats)")
    _match(db, "R1", "Ann")
    db.commit()
    db.close()

    assert _fetch(_admin_headers())[0]["rate_plans"] == "KOL_whatweieats"


def test_unresolvable_reservations_keep_the_stored_rate_plans():
    """Nothing to re-resolve from — don't blank a column that had content."""
    db = TestSession()
    _match(db, "GONE", "Ann", rate_plans="FLEX")
    db.commit()
    db.close()

    assert _fetch(_admin_headers())[0]["rate_plans"] == "FLEX"
