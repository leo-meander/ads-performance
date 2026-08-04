"""Monthly winning-creative awards — CRTV scope, the monthly bar, and the freeze.

Three things must hold:
  1. Only ads whose name contains "CRTV" are in play — as candidates AND when
     computing the month's benchmark, so a KOL ad's outlier ROAS can't raise
     the bar and hide a real winner.
  2. The bar is that MONTH's blended CRTV ROAS, not lifetime.
  3. Once awarded, a row is frozen: later data can add new winners to a month
     but must never rewrite or remove an existing award.
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.user import User
from app.models.winning_ad_month import WinningAdMonth
from app.services.auth_service import create_access_token, hash_password
from app.services.winning_months_service import (
    compute_month_winners,
    freeze_winning_months,
    is_crtv,
    month_end,
    months_between,
)
from tests.db import TestSession

client = TestClient(app)

MAY = date(2026, 5, 10)
JUN = date(2026, 6, 10)


def _admin_headers():
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


def _account(db, name="Saigon"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency="VND", access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _metric(db, acc, *, ad_name, on, spend, revenue, clicks=100, conversions=10,
            impressions=1000, ad_id=None):
    db.add(AdDailyMetric(
        id=str(uuid.uuid4()), account_id=acc.id,
        campaign_id="c1", campaign_name="Camp", adset_id="s1", adset_name="Set",
        ad_id=ad_id or uuid.uuid4().hex[:8], ad_name=ad_name, date=on,
        spend=spend, revenue=revenue, impressions=impressions,
        clicks=clicks, conversions=conversions,
    ))
    db.commit()


# ── helpers ───────────────────────────────────────────────


def test_is_crtv_is_case_insensitive_and_substring():
    assert is_crtv("[Video] CRTV_Couple_PH")
    assert is_crtv("crtv-osaka-solo")
    assert not is_crtv("[Video] KOL_runawaygirl")
    assert not is_crtv(None)


def test_month_end_handles_december_and_short_months():
    assert month_end(date(2026, 12, 3)) == date(2026, 12, 31)
    assert month_end(date(2026, 2, 3)) == date(2026, 2, 28)
    assert month_end(date(2026, 5, 31)) == date(2026, 5, 31)


def test_months_between_spans_year_boundary():
    assert months_between(date(2026, 11, 20), date(2027, 1, 5)) == [
        date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1),
    ]


# ── scope + classification ────────────────────────────────


def test_non_crtv_ads_are_ignored_and_never_move_the_benchmark():
    db = TestSession()
    acc = _account(db)
    # CRTV pair: blended ROAS = 600/200 = 3.0x. A clears it, B doesn't.
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)
    # A KOL ad at 100x. If it counted, the bar would jump to ~35x and A
    # would lose its award.
    _metric(db, acc, ad_name="KOL_runawaygirl", on=MAY, spend=100, revenue=10_000)

    winners, benchmark = compute_month_winners(db, acc.id, MAY)
    db.close()

    assert benchmark == 3.0
    assert [w["ad_name"] for w in winners] == ["CRTV_A"]
    assert winners[0]["roas"] == 5.0


def test_low_volume_ad_is_test_not_a_winner():
    db = TestSession()
    acc = _account(db)
    # Huge ROAS but only 2 bookings and few clicks → TEST, not WIN.
    _metric(db, acc, ad_name="CRTV_tiny", on=MAY, spend=10, revenue=900, clicks=50, conversions=2)
    _metric(db, acc, ad_name="CRTV_big", on=MAY, spend=1000, revenue=1000, clicks=9000, conversions=40)

    winners, _ = compute_month_winners(db, acc.id, MAY)
    db.close()

    assert "CRTV_tiny" not in [w["ad_name"] for w in winners]


def test_benchmark_is_per_month_not_lifetime():
    db = TestSession()
    acc = _account(db)
    # May: the account is weak (1.0x blended) — a 2x ad wins.
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=200)
    _metric(db, acc, ad_name="CRTV_C", on=MAY, spend=300, revenue=200)
    # June: the account is strong (10x blended) — the same 2x ad would lose.
    _metric(db, acc, ad_name="CRTV_A", on=JUN, spend=100, revenue=200)
    _metric(db, acc, ad_name="CRTV_D", on=JUN, spend=300, revenue=3800)

    may_winners, may_bm = compute_month_winners(db, acc.id, MAY)
    jun_winners, jun_bm = compute_month_winners(db, acc.id, JUN)
    db.close()

    assert may_bm == 1.0 and "CRTV_A" in [w["ad_name"] for w in may_winners]
    assert jun_bm == 10.0 and "CRTV_A" not in [w["ad_name"] for w in jun_winners]


# ── freeze semantics ──────────────────────────────────────


def test_award_is_frozen_even_after_the_benchmark_moves():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)

    first = freeze_winning_months(db)
    assert first["awarded"] == 1
    row = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_A").one()
    frozen_roas = float(row.roas)
    frozen_bm = float(row.benchmark_roas)
    assert frozen_roas == 5.0 and frozen_bm == 3.0

    # A late-May flood of cheap spend drags CRTV_A under the new bar. The
    # award must survive untouched — that's the whole point of the table.
    _metric(db, acc, ad_name="CRTV_A", on=date(2026, 5, 28), spend=900, revenue=0)
    _metric(db, acc, ad_name="CRTV_B", on=date(2026, 5, 28), spend=100, revenue=5000)

    live, _ = compute_month_winners(db, acc.id, MAY)
    assert "CRTV_A" not in [w["ad_name"] for w in live]  # dynamic view demotes it

    freeze_winning_months(db)
    rows = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_A").all()
    db.close()

    assert len(rows) == 1
    assert float(rows[0].roas) == frozen_roas
    assert float(rows[0].benchmark_roas) == frozen_bm


def test_rerun_on_unchanged_data_awards_nothing_new():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)

    assert freeze_winning_months(db)["awarded"] == 1
    second = freeze_winning_months(db)
    count = db.query(WinningAdMonth).count()
    db.close()

    assert second == {**second, "awarded": 0, "already_frozen": 1}
    assert count == 1


def test_rerun_can_add_a_new_winner_to_an_already_frozen_month():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)
    freeze_winning_months(db)

    # CRTV_B turns around later in the month and clears the bar.
    _metric(db, acc, ad_name="CRTV_B", on=date(2026, 5, 25), spend=100, revenue=2000)
    freeze_winning_months(db)

    names = {r.ad_name for r in db.query(WinningAdMonth).all()}
    db.close()
    assert names == {"CRTV_A", "CRTV_B"}


def test_same_ad_wins_in_two_months_as_two_rows():
    db = TestSession()
    acc = _account(db)
    for on in (MAY, JUN):
        _metric(db, acc, ad_name="CRTV_A", on=on, spend=100, revenue=500)
        _metric(db, acc, ad_name="CRTV_B", on=on, spend=100, revenue=100)
    freeze_winning_months(db)

    rows = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_A").all()
    db.close()
    assert sorted(r.month for r in rows) == [date(2026, 5, 1), date(2026, 6, 1)]


# ── endpoint ──────────────────────────────────────────────


def test_winning_months_endpoint_groups_by_month():
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    for on in (MAY, JUN):
        _metric(db, acc, ad_name="CRTV_A", on=on, spend=100, revenue=500)
        _metric(db, acc, ad_name="CRTV_B", on=on, spend=100, revenue=100)
    _metric(db, acc, ad_name="KOL_star", on=MAY, spend=100, revenue=99_999)
    db.close()

    resp = client.get("/api/creative/winning-months", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"], body["error"]
    data = body["data"]

    assert [m["month"] for m in data["months"]] == ["2026-06", "2026-05"]
    assert all(m["count"] == 1 for m in data["months"])
    assert data["total_wins"] == 2
    assert data["distinct_ads"] == 1  # one creative, two monthly awards
    ads = data["months"][0]["ads"]
    assert [a["ad_name"] for a in ads] == ["CRTV_A"]
    assert ads[0]["branch_name"] == "Meander Saigon"
    assert data["months"][0]["by_branch"] == [{"branch_name": "Meander Saigon", "count": 1}]
