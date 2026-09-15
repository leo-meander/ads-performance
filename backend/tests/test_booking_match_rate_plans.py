"""Tests for /api/booking-matches/rate-plans.

The endpoint reads reservations PMS-wide (never through BookingMatch), so the
cases that matter are: plans arriving from the explicit column AND from the
room_type fallback, cancelled rows counted but kept out of the live averages,
and the per-plan country/status/branch breakdowns shipping with the list.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models.reservation import Reservation
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password
from tests.db import TestSession

client = TestClient(app)

D = date(2026, 6, 10)
FRIEND = "MEANDER'S FRIEND"
WELCOME = "WELCOME"


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


def _res(db, num, **kw):
    defaults = dict(
        reservation_date=D,
        check_in_date=D + timedelta(days=5),
        grand_total=1_000_000,
        country="Vietnam",
        country_iso="VN",
        source="Website/Booking Engine",
        branch="Meander Saigon",
        status="Confirmed",
        room_type="Standard Twin",
        nights=2,
        adults=2,
    )
    defaults.update(kw)
    db.add(Reservation(id=str(uuid.uuid4()), reservation_number=num, **defaults))


def _seed(db):
    # Explicit rate_plan_name column.
    _res(db, "R1", rate_plan_name=FRIEND)
    _res(db, "R2", rate_plan_name=FRIEND, country="Taiwan", country_iso="TW")
    # Cancelled: counted in bookings, excluded from net revenue + averages.
    _res(db, "R3", rate_plan_name=FRIEND, status="Canceled", nights=10, adults=8)
    # Fallback path: no rate_plan_name, plan lives in the room_type parens.
    _res(db, "R4", room_type="Deluxe Double (WELCOME)")
    # Different branch, same plan — branch breakdown must split them.
    _res(db, "R5", rate_plan_name=WELCOME, branch="Meander Taipei", grand_total=8000)
    # No plan anywhere: counts as untagged, never as a plan.
    _res(db, "R6")
    # Outside the window.
    _res(db, "R7", rate_plan_name=FRIEND, reservation_date=D - timedelta(days=60))
    db.commit()


def _get(params: str = "") -> dict:
    url = f"/api/booking-matches/rate-plans?date_from={D}&date_to={D}"
    if params:
        url += f"&{params}"
    res = client.get(url, headers=_admin_headers())
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True, body["error"]
    return body["data"]


def _plan(data: dict, name: str) -> dict:
    match = [p for p in data["plans"] if p["rate_plan"] == name]
    assert match, f"{name} missing from {[p['rate_plan'] for p in data['plans']]}"
    return match[0]


def test_groups_plans_from_column_and_room_type_fallback():
    db = TestSession()
    _seed(db)
    db.close()

    data = _get()

    assert data["total_plans"] == 2
    assert {p["rate_plan"] for p in data["plans"]} == {FRIEND, WELCOME}
    # R6 has no plan on either surface; R7 is out of the window entirely.
    assert data["untagged_reservations"] == 1
    assert data["total_reservations"] == 6

    welcome = _plan(data, WELCOME)
    assert welcome["bookings"] == 2  # column row + room_type fallback row


def test_cancelled_counted_but_kept_out_of_net_and_averages():
    db = TestSession()
    _seed(db)
    db.close()

    friend = _plan(_get(), FRIEND)

    assert friend["bookings"] == 3
    assert friend["canceled"] == 1
    assert friend["live"] == 2
    assert round(friend["cancel_rate"]) == 33
    # Gross carries the cancelled row, net does not.
    assert friend["revenue"] == 3_000_000
    assert friend["revenue_net"] == 2_000_000
    # The cancelled row's 10 nights / 8 adults must not drag the averages.
    assert friend["nights"]["avg"] == 2
    assert friend["adults"]["avg"] == 2
    assert friend["nights"]["count"] == 2


def test_breakdowns_ship_with_the_list():
    db = TestSession()
    _seed(db)
    db.close()

    data = _get()
    friend = _plan(data, FRIEND)

    countries = {c["country"]: c["bookings"] for c in friend["by_country"]}
    assert countries == {"Vietnam": 2, "Taiwan": 1}
    statuses = {s["status"]: s["bookings"] for s in friend["by_status"]}
    assert statuses == {"Confirmed": 2, "Canceled": 1}
    assert friend["lead_buckets"]["4-7"] == 2  # only the live rows

    welcome = _plan(data, WELCOME)
    assert {b["branch"]: b["bookings"] for b in welcome["by_branch"]} == {
        "Saigon": 1, "Taipei": 1,
    }


def test_branch_filter_scopes_rows_and_currency():
    db = TestSession()
    _seed(db)
    db.close()

    data = _get("branches=Taipei")

    assert data["currency"] == "TWD"  # single branch -> its native currency
    welcome = _plan(data, WELCOME)
    assert welcome["bookings"] == 1
    assert welcome["revenue_net"] == 8000  # no VND conversion applied
    assert FRIEND not in {p["rate_plan"] for p in data["plans"]}
