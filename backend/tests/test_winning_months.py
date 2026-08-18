"""Monthly winning-creative awards — KOL exclusion scope, the lifetime bar, and the freeze.

Things that must hold:
  1. Every ad counts EXCEPT ones whose name contains "KOL" — as candidates AND
     when computing the benchmark, so a KOL ad's outlier ROAS can't raise the
     bar and hide a real winner. Ads that lack "CRTV" now count too — that
     naming convention no longer gates anything.
  2. The bar is the account's LIFETIME-to-date blended non-KOL ROAS — "hiện
     tại" per Mason's spec means lifetime, not year-to-date and not a single
     month's isolated cohort. Only the CANDIDATE's own roas is month-scoped
     (that's what "winning BY MONTH" means); the benchmark it's measured
     against is not. The year-to-date windowing is REPORTING only — see
     test_year_filter_* below.
  3. Once awarded, a row is frozen: later data can add new winners to a month
     but must never rewrite or remove an existing award.
  4. An ad's verdict (WIN or LOSE) is decided ONCE, ever, per account — once
     it's decided in some month it is never a candidate again in a later
     month, so win_rate never double-counts a standing winner.
  5. LOSE only FREEZES for a month that's CLOSED (strictly before the
     account's most-recent synced month) — the open month can still add
     WINs, but freeze_winning_months never locks in a LOSE it might climb
     out of before it ends. list_winning_months (the read side) still
     blends a LIVE, unfrozen LOSE count into the open month's tested/
     win_rate for reporting — see test_open_month_win_rate_includes_live_lose
     — so the API doesn't read as an artificial 100% just because nothing
     froze yet.

MAY and JUN below are both in the past relative to the synced data in most
tests (JUL/AUG add a third, "still open," month where relevant), so unless a
test says otherwise, both MAY and JUN close as soon as a later month's data
exists.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.user import User
from app.models.winning_ad_month import WinningAdMonth
from app.services.auth_service import create_access_token, hash_password
from app.services.winning_months_service import (
    ManualVerdictError,
    award_manual_verdict,
    compute_lifetime_benchmark,
    compute_month_verdicts,
    describe_data_window,
    freeze_winning_months,
    is_kol,
    list_winning_months,
    month_end,
    month_start,
    months_between,
    rebuild_winning_months,
)
from tests.db import TestSession

client = TestClient(app)

MAY = date(2026, 5, 10)
JUN = date(2026, 6, 10)
JUL = date(2026, 7, 10)


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


def test_is_kol_is_case_insensitive_and_substring():
    assert is_kol("[Video] KOL_runawaygirl")
    assert is_kol("kol-osaka-solo")
    assert not is_kol("[Video] CRTV_Couple_PH")
    assert not is_kol("[Carousel] Full plan travel")
    assert not is_kol(None)


def test_month_end_handles_december_and_short_months():
    assert month_end(date(2026, 12, 3)) == date(2026, 12, 31)
    assert month_end(date(2026, 2, 3)) == date(2026, 2, 28)
    assert month_end(date(2026, 5, 31)) == date(2026, 5, 31)


def test_months_between_spans_year_boundary():
    assert months_between(date(2026, 11, 20), date(2027, 1, 5)) == [
        date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1),
    ]


# ── scope + classification ────────────────────────────────


def test_kol_ads_are_ignored_and_never_move_the_benchmark():
    db = TestSession()
    acc = _account(db)
    # Non-KOL pair: blended ROAS = 600/200 = 3.0x. A clears it, B doesn't.
    # Neither is named "CRTV" — proving the broadened scope counts them.
    _metric(db, acc, ad_name="Plain_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="Plain_B", on=MAY, spend=100, revenue=100)
    # A KOL ad at 100x. If it counted, the bar would jump to ~35x and A
    # would lose its award.
    _metric(db, acc, ad_name="KOL_runawaygirl", on=MAY, spend=100, revenue=10_000)

    benchmark = compute_lifetime_benchmark(db, acc.id)
    decided = compute_month_verdicts(db, acc.id, MAY, benchmark)
    db.close()

    assert benchmark == 3.0
    winners = [d for d in decided if d["verdict"] == "WIN"]
    losers = [d for d in decided if d["verdict"] == "LOSE"]
    assert [w["ad_name"] for w in winners] == ["Plain_A"]
    assert winners[0]["roas"] == 5.0
    assert [l["ad_name"] for l in losers] == ["Plain_B"]  # crossed the test bar, just lost it


def test_low_volume_ad_is_test_not_a_winner():
    db = TestSession()
    acc = _account(db)
    # Huge ROAS but only 2 bookings and few clicks → TEST, not decided at all.
    _metric(db, acc, ad_name="CRTV_tiny", on=MAY, spend=10, revenue=900, clicks=50, conversions=2)
    _metric(db, acc, ad_name="CRTV_big", on=MAY, spend=1000, revenue=1000, clicks=9000, conversions=40)

    benchmark = compute_lifetime_benchmark(db, acc.id)
    decided = compute_month_verdicts(db, acc.id, MAY, benchmark)
    db.close()

    assert "CRTV_tiny" not in [d["ad_name"] for d in decided]


def test_benchmark_is_lifetime_to_date_not_a_per_month_cohort():
    db = TestSession()
    acc = _account(db)
    # May alone would blend to 1.0x (400 revenue / 400 spend) — CRTV_A's 2x
    # roas would clear that isolated-month bar...
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=200)
    _metric(db, acc, ad_name="CRTV_C", on=MAY, spend=300, revenue=200)
    # ...but June brings in a much stronger cohort. "hiện tại" (current) per
    # Mason's spec means the LIFETIME blend of both months (700 spend, 4200
    # revenue = 6.0x) — not May alone (1.0x), and not June alone (12.67x)
    # either.
    _metric(db, acc, ad_name="CRTV_D", on=JUN, spend=300, revenue=3800)

    benchmark = compute_lifetime_benchmark(db, acc.id)
    may_decided = compute_month_verdicts(db, acc.id, MAY, benchmark)
    db.close()

    assert benchmark == 6.0
    may_losers = [d["ad_name"] for d in may_decided if d["verdict"] == "LOSE"]
    # CRTV_A's 2x monthly roas cleared May's isolated 1.0x bar but not the
    # account's lifetime 6.0x bar.
    assert "CRTV_A" in may_losers


def test_benchmark_spans_years_rather_than_resetting_each_january():
    """The reporting window is year-to-date, but the BAR is not — a prior
    year's data still counts toward it. Guards the split from being
    "simplified" into a YTD benchmark."""
    db = TestSession()
    acc = _account(db)
    # 2025: 100 spend / 2000 revenue. 2026: 100 spend / 200 revenue.
    # Lifetime blend = 2200 / 200 = 11.0x. A year-to-date bar would be 2.0x.
    _metric(db, acc, ad_name="CRTV_old", on=date(2025, 6, 1), spend=100, revenue=2000)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=200)

    benchmark = compute_lifetime_benchmark(db, acc.id)
    db.close()

    assert benchmark == 11.0


# ── cumulative click/booking threshold ─────────────────────


def test_click_threshold_accumulates_across_months_using_cumulative_roas():
    """Mason's spec (2026-08-10): 1,500 clicks in June + 1,500 more in July
    never cleared MIN_TEST_CLICKS (2,500) under pure per-month accounting,
    despite the ad plainly earning 3,000 clicks of evidence by end of July.
    Decide it in July, using CUMULATIVE roas — not July's own isolated roas,
    which would tell a different (wrong) story."""
    db = TestSession()
    acc = _account(db)
    # June alone: 1,500 clicks (<=2500), 0 bookings → still TEST. Own roas
    # would be 10.0x if it mattered, but it doesn't — not enough evidence yet.
    _metric(db, acc, ad_name="CRTV_slow_burn", on=JUN, spend=100, revenue=1000,
            clicks=1500, conversions=0)
    decided_june = compute_month_verdicts(db, acc.id, JUN, benchmark=3.0)
    assert decided_june == []  # cumulative clicks (1500) still <= 2500

    # July: 1,500 more clicks. Cumulative = 3,000 clicks (>2500) → exits TEST.
    _metric(db, acc, ad_name="CRTV_slow_burn", on=JUL, spend=100, revenue=100,
            clicks=1500, conversions=0)
    decided_july = compute_month_verdicts(db, acc.id, JUL, benchmark=3.0)
    db.close()

    assert len(decided_july) == 1
    d = decided_july[0]
    assert d["ad_name"] == "CRTV_slow_burn"
    assert d["clicks"] == 3000  # cumulative, not July's own 1,500
    # Cumulative roas = (1000+100) / (100+100) = 5.5x — clears the 3.0x bar.
    # July's OWN roas (100/100 = 1.0x) would have been a LOSE — proves the
    # cumulative figure, not the isolated month, decided this.
    assert d["roas"] == 5.5
    assert d["verdict"] == "WIN"


def test_dormant_ad_is_not_a_candidate_in_a_month_it_did_not_run():
    """Candidacy stays month-scoped even though the NUMBERS are cumulative:
    an ad with no rows in the month being judged isn't re-surfaced just
    because its old (still insufficient) totals sit in the account's
    history."""
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_stopped", on=MAY, spend=100, revenue=1000,
            clicks=1000, conversions=0)  # below threshold, and never runs again

    may_decided = compute_month_verdicts(db, acc.id, MAY, benchmark=3.0)
    jun_decided = compute_month_verdicts(db, acc.id, JUN, benchmark=3.0)
    db.close()

    assert may_decided == []  # correctly still TEST in May
    assert jun_decided == []  # NOT a June candidate — it didn't run in June


def test_click_threshold_never_clears_across_many_thin_months():
    """The realistic failure mode this was built to diagnose: an ad running
    every month at low volume, never individually or cumulatively reaching
    the bar within the months tested, stays TEST throughout."""
    db = TestSession()
    acc = _account(db)
    for on in (MAY, JUN, JUL):
        _metric(db, acc, ad_name="CRTV_thin", on=on, spend=100, revenue=200,
                clicks=400, conversions=0)  # 400/month; even x3 = 1200 < 2500

    decided = [
        d for m in (MAY, JUN, JUL)
        for d in compute_month_verdicts(db, acc.id, m, benchmark=1.0)
    ]
    db.close()

    assert decided == []


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

    live_bm = compute_lifetime_benchmark(db, acc.id)
    live = compute_month_verdicts(db, acc.id, MAY, live_bm)
    live_winners = [d["ad_name"] for d in live if d["verdict"] == "WIN"]
    assert "CRTV_A" not in live_winners  # dynamic view demotes it

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
    # CRTV_A is now in `decided_ad_names` from its own frozen row, so the
    # second pass excludes it as a candidate before ever re-deciding it —
    # it doesn't even reach the "already_frozen" bookkeeping, it's just
    # skipped outright. Either way nothing new lands in the table.
    second = freeze_winning_months(db)
    count = db.query(WinningAdMonth).count()
    db.close()

    assert second == {**second, "awarded": 0, "lost": 0}
    assert count == 1


def test_rerun_can_add_a_new_winner_to_an_already_frozen_month():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)
    freeze_winning_months(db)

    # CRTV_B turns around later in the month and clears the bar. May is
    # still this account's only (= most-recent = open) month, so its
    # earlier LOSE was never frozen — nothing blocks it from winning now.
    _metric(db, acc, ad_name="CRTV_B", on=date(2026, 5, 25), spend=100, revenue=2000)
    freeze_winning_months(db)

    names = {r.ad_name for r in db.query(WinningAdMonth).all()}
    db.close()
    assert names == {"CRTV_A", "CRTV_B"}


def test_lose_verdict_is_not_frozen_for_the_still_open_month():
    db = TestSession()
    acc = _account(db)
    # Only May data exists — May is this account's most-recent (open) month.
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # wins
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)  # would LOSE

    freeze_winning_months(db)
    rows = db.query(WinningAdMonth).all()
    db.close()

    # CRTV_B crossed the test threshold and would score LOSE today, but the
    # month isn't over — freezing that now would permanently bar it from
    # winning if it turns around later in May, so it's left unfrozen.
    assert {(r.ad_name, r.verdict) for r in rows} == {("CRTV_A", "WIN")}


def test_open_month_win_rate_includes_live_lose():
    """list_winning_months (the read side) is not bound by freeze's caution:
    CRTV_B already crossed the test threshold and scores below benchmark, so
    it should count as tested right now for reporting, even though nothing
    was written to WinningAdMonth for it — see the "LIVE LOSE PREVIEW" note
    on list_winning_months."""
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    # Only May data exists — May is this account's open month.
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # wins
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)  # would LOSE
    freeze_winning_months(db)
    db.close()

    resp = client.get("/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers())
    data = resp.json()["data"]
    may = next(m for m in data["months"] if m["month"] == "2026-05")

    assert may["in_progress"] is True
    assert may["count"] == 1          # frozen WIN only
    assert may["lose_count"] == 1     # live, unfrozen preview of CRTV_B
    assert may["tested"] == 2
    assert may["win_rate"] == 0.5
    assert [a["ad_name"] for a in may["ads"]] == ["CRTV_A"]  # live LOSE never joins the ads detail list

    # The live LOSE never got written — freeze's "don't lock in a LOSE it
    # might climb out of" guarantee is untouched.
    db2 = TestSession()
    rows = db2.query(WinningAdMonth).all()
    db2.close()
    assert {(r.ad_name, r.verdict) for r in rows} == {("CRTV_A", "WIN")}


def test_ad_decided_in_a_closed_month_is_never_retested():
    db = TestSession()
    acc = _account(db)
    # Same two ads, same performance, three months running. JUL's data makes
    # MAY and JUN both CLOSED months as soon as freeze runs.
    for on in (MAY, JUN, JUL):
        _metric(db, acc, ad_name="CRTV_A", on=on, spend=100, revenue=500)  # would win every month
        _metric(db, acc, ad_name="CRTV_B", on=on, spend=100, revenue=100)  # would lose every month
    freeze_winning_months(db)

    a_rows = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_A").all()
    b_rows = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_B").all()
    db.close()

    # Decided once, in May — the first month either ad crossed the test
    # threshold — never re-tested in June or July despite identical
    # performance repeating every month.
    assert [r.month for r in a_rows] == [date(2026, 5, 1)]
    assert a_rows[0].verdict == "WIN"
    assert [r.month for r in b_rows] == [date(2026, 5, 1)]
    assert b_rows[0].verdict == "LOSE"


# ── endpoint / win rate ────────────────────────────────────


def test_win_rate_is_wins_over_tested_ads_for_a_closed_month():
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    # May: 1 win, 2 losses → win_rate = 1/3. June's data is what closes May.
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # wins
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)  # loses
    _metric(db, acc, ad_name="CRTV_C", on=MAY, spend=100, revenue=50)   # loses
    _metric(db, acc, ad_name="CRTV_D", on=JUN, spend=100, revenue=100)
    db.close()

    # year=2026 pinned explicitly — the endpoint defaults to wall-clock
    # "current year," which would make this test flaky once real time moves
    # past 2026.
    resp = client.get("/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"], body["error"]
    data = body["data"]

    may = next(m for m in data["months"] if m["month"] == "2026-05")
    assert may["count"] == 1
    assert may["lose_count"] == 2
    assert may["tested"] == 3
    assert may["win_rate"] == 1 / 3
    assert may["in_progress"] is False  # May closed once June's data arrived


def test_new_ads_counts_first_seen_ad_names_per_month():
    """`new_ads` is reference-only: how many ad_names first appeared that
    month, same scope as the KPI (non-KOL). Doesn't touch win/tested."""
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # wins
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=50)   # loses
    _metric(db, acc, ad_name="KOL_someone", on=MAY, spend=100, revenue=100)  # excluded
    _metric(db, acc, ad_name="CRTV_new_jun", on=JUN, spend=100, revenue=300)  # wins
    db.close()

    resp = client.get("/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers())
    data = resp.json()["data"]

    may = next(m for m in data["months"] if m["month"] == "2026-05")
    jun = next(m for m in data["months"] if m["month"] == "2026-06")
    assert may["new_ads"] == 2  # CRTV_A + CRTV_B; KOL_someone excluded
    assert jun["new_ads"] == 1  # only CRTV_new_jun is new in June


def test_new_ad_list_itemises_the_ads_behind_the_count():
    """`new_ads` says 3; `new_ad_list` says WHICH three and where — the whole
    point being that a reader can audit the number instead of trusting it.
    Same scope as the count (KOL excluded)."""
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # wins
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=50)   # loses
    # Thin ad: nowhere near 2,500 clicks / 5 bookings, so it never leaves TEST.
    _metric(db, acc, ad_name="CRTV_thin", on=MAY, spend=10, revenue=5,
            clicks=40, conversions=0)
    _metric(db, acc, ad_name="KOL_someone", on=MAY, spend=100, revenue=100)  # excluded
    _metric(db, acc, ad_name="CRTV_jun", on=JUN, spend=100, revenue=300)
    db.close()

    data = client.get(
        "/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers()
    ).json()["data"]
    may = next(m for m in data["months"] if m["month"] == "2026-05")

    # The list is exactly as long as the count it explains.
    assert may["new_ads"] == 3
    assert len(may["new_ad_list"]) == 3
    by_name = {e["ad_name"]: e for e in may["new_ad_list"]}
    assert set(by_name) == {"CRTV_A", "CRTV_B", "CRTV_thin"}  # KOL stays out
    assert all(e["branch_name"] == "Meander Saigon" for e in may["new_ad_list"])

    # Status explains why 3 created ≠ 3 tested: the thin one never qualified.
    assert by_name["CRTV_A"]["status"] == "WIN"
    assert by_name["CRTV_B"]["status"] == "LOSE"
    assert by_name["CRTV_thin"]["status"] == "TEST"
    assert by_name["CRTV_thin"]["status_source"] == "test"
    assert by_name["CRTV_thin"]["decided_month"] is None
    # And the reader sees the same clicks number the TEST rule judged on.
    assert by_name["CRTV_thin"]["clicks"] == 40

    # Winners first, then losers, then TEST (see the sort in list_winning_months).
    assert [e["status"] for e in may["new_ad_list"]] == ["WIN", "LOSE", "TEST"]


def test_new_ad_list_reports_the_month_an_ad_was_actually_decided():
    """The reason a month can read "6 created / 3 tested": an ad is judged the
    month its CUMULATIVE evidence clears the bar, which is often later than
    the month it launched. `decided_month` makes that visible on the ad."""
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    # Launches in May with too little evidence, keeps running, and only clears
    # MIN_TEST_CLICKS once June's clicks are added to May's.
    _metric(db, acc, ad_name="CRTV_slow", on=MAY, spend=100, revenue=500,
            clicks=1400, conversions=0)
    _metric(db, acc, ad_name="CRTV_slow", on=JUN, spend=100, revenue=500,
            clicks=1400, conversions=0)
    # A second ad so June is not the open month for the LOSE-freeze rule.
    _metric(db, acc, ad_name="CRTV_jul", on=JUL, spend=100, revenue=500)
    db.close()

    data = client.get(
        "/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers()
    ).json()["data"]

    may = next(m for m in data["months"] if m["month"] == "2026-05")
    slow = next(e for e in may["new_ad_list"] if e["ad_name"] == "CRTV_slow")

    # Counted as CREATED in May...
    assert may["new_ads"] == 1
    # ...but decided in June, once 1,400 + 1,400 clicks cleared the 2,500 bar.
    assert slow["decided_month"] == "2026-06"
    assert slow["status"] == "WIN"
    assert slow["clicks"] == 2800  # cumulative, matching what the rule used
    # So May's own tested count doesn't include it — the exact gap the list explains.
    assert may["tested"] == 0


def test_winning_months_endpoint_groups_by_month():
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    # Different ad names per month: under the "decided once" rule, the same
    # ad_name winning in May would be excluded from candidacy in June, so
    # distinct names are needed to see both months populate independently.
    for on, win_name, lose_name in ((MAY, "CRTV_A", "CRTV_B"), (JUN, "CRTV_C", "CRTV_D")):
        _metric(db, acc, ad_name=win_name, on=on, spend=100, revenue=500)
        _metric(db, acc, ad_name=lose_name, on=on, spend=100, revenue=100)
    _metric(db, acc, ad_name="KOL_star", on=MAY, spend=100, revenue=99_999)
    db.close()

    resp = client.get("/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"], body["error"]
    data = body["data"]

    assert [m["month"] for m in data["months"]] == ["2026-06", "2026-05"]
    assert all(m["count"] == 1 for m in data["months"])
    assert data["total_wins"] == 2
    assert data["distinct_ads"] == 2  # two distinct winning creatives now, one each
    ads = data["months"][0]["ads"]
    assert [a["ad_name"] for a in ads] == ["CRTV_C"]
    assert ads[0]["branch_name"] == "Meander Saigon"
    assert data["months"][0]["by_branch"] == [{"branch_name": "Meander Saigon", "count": 1}]

    # June is this account's most-recent synced month — still open, so
    # CRTV_D's LOSE hasn't frozen (WinningAdMonth stays WIN-only for June),
    # but list_winning_months still folds it in live for tested/win_rate.
    june = data["months"][0]
    assert june["in_progress"] is True
    assert june["lose_count"] == 1  # live preview of CRTV_D, not frozen
    assert june["tested"] == 2
    assert june["win_rate"] == 0.5

    # May is closed (June's data exists): both ads got decided.
    may = data["months"][1]
    assert may["in_progress"] is False
    assert may["lose_count"] == 1
    assert may["tested"] == 2
    assert may["win_rate"] == 0.5


def test_backfill_alone_leaves_the_earlier_month_wrong():
    """Documents WHY rebuild_winning_months exists. The "decided once, ever"
    rule keys off existing rows, not calendar order — so an ad already decided
    in May keeps that row and never gets one in the January that a later
    backfill revealed."""
    db = TestSession()
    acc = _account(db)
    # First pass: only May/Jun data exists (the pre-backfill world).
    _metric(db, acc, ad_name="CRTV_long_runner", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_other", on=JUN, spend=100, revenue=100)
    freeze_winning_months(db)
    assert [r.month for r in db.query(WinningAdMonth)
            .filter(WinningAdMonth.ad_name == "CRTV_long_runner").all()] == [date(2026, 5, 1)]

    # Backfill: the same ad turns out to have been running since January.
    _metric(db, acc, ad_name="CRTV_long_runner", on=date(2026, 1, 15), spend=100, revenue=500)
    freeze_winning_months(db)

    rows = db.query(WinningAdMonth).filter(
        WinningAdMonth.ad_name == "CRTV_long_runner"
    ).all()
    db.close()

    # Still only the May row — January got nothing, which is the bug the
    # rebuild fixes.
    assert [r.month for r in rows] == [date(2026, 5, 1)]


def test_rebuild_moves_the_verdict_to_the_true_first_month():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_long_runner", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_other", on=JUN, spend=100, revenue=100)
    freeze_winning_months(db)
    _metric(db, acc, ad_name="CRTV_long_runner", on=date(2026, 1, 15), spend=100, revenue=500)

    summary = rebuild_winning_months(db)

    rows = db.query(WinningAdMonth).filter(
        WinningAdMonth.ad_name == "CRTV_long_runner"
    ).all()
    db.close()

    assert summary["deleted"] > 0
    # Now decided in January — the month it actually first cleared the bar.
    assert [r.month for r in rows] == [date(2026, 1, 1)]
    assert rows[0].verdict == "WIN"


def test_describe_data_window_is_the_rebuild_preflight():
    """Answers "how far back does the data actually go" without running a
    rebuild — the check that catches a still-running backfill. Excluded
    branches are left out, same scope as the rebuild itself."""
    db = TestSession()
    saigon = _account(db, name="Meander Saigon")
    bread = _account(db, name="Bread Espresso")
    _metric(db, saigon, ad_name="CRTV_A", on=date(2026, 1, 10), spend=100, revenue=500)
    _metric(db, saigon, ad_name="CRTV_A", on=date(2026, 1, 11), spend=100, revenue=500)
    _metric(db, saigon, ad_name="CRTV_B", on=date(2026, 3, 4), spend=100, revenue=100)
    _metric(db, bread, ad_name="CRTV_bread", on=MAY, spend=100, revenue=100)

    window = describe_data_window(db)
    db.close()

    assert [e["account_name"] for e in window] == ["Meander Saigon"]  # Bread excluded
    saigon_window = window[0]
    assert saigon_window["from"] == "2026-01-10"
    assert saigon_window["to"] == "2026-03-04"
    # Two distinct months, not three day-rows — Jan counted once.
    assert saigon_window["months"] == 2


def test_describe_data_window_handles_an_account_with_no_metrics():
    db = TestSession()
    _account(db, name="Meander Saigon")
    db.commit()

    window = describe_data_window(db)
    db.close()

    assert window == [{
        "account_name": "Meander Saigon", "from": None, "to": None, "months": 0,
    }]


def test_rebuild_reports_the_data_window_it_saw():
    """A rebuild run while a backfill is still writing silently re-creates the
    skew it exists to fix. `data_seen` surfaces the window in the response so
    a short range is caught immediately instead of weeks later on the chart."""
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    _metric(db, acc, ad_name="CRTV_A", on=date(2026, 1, 10), spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=MAY, spend=100, revenue=100)

    summary = rebuild_winning_months(db)
    db.close()

    seen = {e["account_name"]: e for e in summary["data_seen"]}
    assert seen["Meander Saigon"]["from"] == "2026-01-10"
    assert seen["Meander Saigon"]["to"] == "2026-05-10"
    assert seen["Meander Saigon"]["months"] == 2  # Jan and May only


def test_rebuild_is_idempotent():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="CRTV_B", on=JUN, spend=100, revenue=100)

    rebuild_winning_months(db)
    first = {(r.account_id, r.month, r.ad_name, r.verdict)
             for r in db.query(WinningAdMonth).all()}
    rebuild_winning_months(db)
    second = {(r.account_id, r.month, r.ad_name, r.verdict)
              for r in db.query(WinningAdMonth).all()}
    db.close()

    assert first == second


def test_rebuild_purges_excluded_branch_rows():
    """A rebuild also cleans out awards frozen for Bread before it was
    excluded — they can't come back, since freeze skips the branch."""
    db = TestSession()
    hotel = _account(db, name="Meander Saigon")
    bread = _account(db, name="Bread Espresso")
    _metric(db, hotel, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)
    _metric(db, hotel, ad_name="CRTV_B", on=JUN, spend=100, revenue=100)
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=bread.id, month=date(2026, 5, 1),
        ad_name="CRTV_legacy_bread", verdict="WIN", spend=100, revenue=500, roas=5.0,
    ))
    db.commit()
    bread_id = bread.id

    rebuild_winning_months(db)

    remaining = db.query(WinningAdMonth).filter(
        WinningAdMonth.account_id == bread_id
    ).count()
    db.close()
    assert remaining == 0


def test_bread_branch_is_excluded_from_the_kpi():
    """Bread (the restaurant) is out of this KPI: no rows are frozen for it,
    and any frozen before the exclusion stay hidden from the read path."""
    db = TestSession()
    hotel = _account(db, name="Meander Saigon")
    bread = _account(db, name="Bread Espresso")
    for acc in (hotel, bread):
        _metric(db, acc, ad_name=f"CRTV_win_{acc.account_name}", on=MAY, spend=100, revenue=500)
        _metric(db, acc, ad_name=f"CRTV_lose_{acc.account_name}", on=MAY, spend=100, revenue=100)
        _metric(db, acc, ad_name=f"CRTV_next_{acc.account_name}", on=JUN, spend=100, revenue=100)
    bread_id = bread.id
    db.close()

    freeze_db = TestSession()
    freeze_winning_months(freeze_db)
    bread_rows = (
        freeze_db.query(WinningAdMonth)
        .filter(WinningAdMonth.account_id == bread_id).count()
    )
    freeze_db.close()
    assert bread_rows == 0  # never frozen in the first place

    data = client.get(
        "/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers()
    ).json()["data"]

    branches = {b["branch_name"] for m in data["months"] for b in m["by_branch"]}
    assert branches == {"Meander Saigon"}
    assert "Bread" in data["scope_note"]


def test_frozen_bread_rows_are_hidden_from_the_read_path():
    """The table is append-only, so an award frozen before Bread was excluded
    still exists on disk — it must not reach the totals."""
    db = TestSession()
    bread = _account(db, name="Bread Espresso")
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=bread.id, month=date(2026, 5, 1),
        ad_name="CRTV_legacy_bread", verdict="WIN", spend=100, revenue=500, roas=5.0,
    ))
    db.commit()
    db.close()

    data = client.get(
        "/api/creative/winning-months",
        params={"year": 2026, "refresh": "false"},
        headers=_admin_headers(),
    ).json()["data"]

    assert data["total_wins"] == 0
    assert data["months"] == []


def test_year_filter_scopes_the_totals_without_changing_verdicts():
    """The YTD window is REPORTING only. A 2025 award stays frozen with the
    same verdict and benchmark; asking for 2026 just leaves it out of the
    buckets and the headline totals."""
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    # Both clear the lifetime bar and both sit in CLOSED months (JUN's data
    # is what closes MAY, and 2026 data closes 2025), so both freeze as WIN.
    _metric(db, acc, ad_name="CRTV_2025", on=date(2025, 6, 10), spend=100, revenue=5000)
    _metric(db, acc, ad_name="CRTV_2026", on=MAY, spend=100, revenue=5000)
    _metric(db, acc, ad_name="CRTV_later", on=JUN, spend=100, revenue=100)
    acc_id = acc.id  # `acc` detaches once the session closes
    db.close()

    headers = _admin_headers()
    ytd = client.get("/api/creative/winning-months", params={"year": 2026}, headers=headers).json()["data"]
    all_time = client.get("/api/creative/winning-months", params={"year": 0}, headers=headers).json()["data"]

    # 2026-06 shows up too: CRTV_later already crossed the test threshold and
    # scores below benchmark, so it's a live (unfrozen) LOSE preview for the
    # still-open June bucket — see test_open_month_win_rate_includes_live_lose.
    ytd_months = [m["month"] for m in ytd["months"]]
    assert ytd_months == ["2026-06", "2026-05"]  # 2025 is windowed out
    assert ytd["year"] == 2026

    # year=0 opts out of the window entirely and 2025 reappears, unchanged.
    assert [m["month"] for m in all_time["months"]] == ["2026-06", "2026-05", "2025-06"]
    assert all_time["year"] is None
    assert all_time["total_wins"] == ytd["total_wins"] + 1

    # The 2025 row itself was never re-judged by either request — same
    # verdict, and its frozen bar is the lifetime one, not a 2025-only blend.
    db = TestSession()
    row = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_2025").one()
    assert row.verdict == "WIN"
    # ~33.67 (the lifetime blend), not 50.0 (what a 2025-only bar would be).
    # approx because the column rounds to 4 decimal places.
    assert float(row.benchmark_roas) == pytest.approx(
        compute_lifetime_benchmark(db, acc_id), rel=1e-4
    )
    db.close()


# ── manual verdict override ─────────────────────────────────


def test_manual_verdict_awards_a_stuck_test_ad():
    """The actual point of this feature: an ad that will NEVER accumulate
    enough clicks/bookings on its own gets a human-decided verdict instead of
    sitting in TEST forever."""
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_thin", on=MAY, spend=100, revenue=300,
            clicks=400, conversions=0)  # nowhere near 2500 clicks / 5 bookings
    acc_id = acc.id
    db.close()

    db = TestSession()
    row = award_manual_verdict(db, acc_id, "CRTV_thin", "win", notes="creative team call")
    db.commit()
    assert row.verdict == "WIN"  # lowercase input normalized, checked before the session closes
    db.close()

    db = TestSession()
    saved = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_thin").one()
    db.close()

    assert saved.verdict == "WIN"
    assert saved.verdict_source == "manual"
    assert saved.verdict_notes == "creative team call"
    assert saved.month == month_start(MAY)  # defaulted to the account's only synced month
    assert float(saved.spend) == 100
    assert float(saved.roas) == 3.0


def test_manual_verdict_rejects_an_already_decided_ad():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # auto-decides via bookings
    acc_id = acc.id
    db.close()

    freeze_db = TestSession()
    freeze_winning_months(freeze_db)
    freeze_db.close()

    db = TestSession()
    with pytest.raises(ManualVerdictError, match="already has a WIN verdict"):
        award_manual_verdict(db, acc_id, "CRTV_A", "LOSE")
    db.close()


def test_manual_verdict_rejects_kol_ads():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="KOL_someone", on=MAY, spend=100, revenue=100, clicks=100)
    acc_id = acc.id
    db.close()

    db = TestSession()
    with pytest.raises(ManualVerdictError, match="KOL"):
        award_manual_verdict(db, acc_id, "KOL_someone", "WIN")
    db.close()


def test_manual_verdict_rejects_excluded_branches():
    db = TestSession()
    bread = _account(db, name="Bread Espresso")
    _metric(db, bread, ad_name="CRTV_bread", on=MAY, spend=100, revenue=100, clicks=100)
    bread_id = bread.id
    db.close()

    db = TestSession()
    with pytest.raises(ManualVerdictError, match="EXCLUDED_BRANCHES"):
        award_manual_verdict(db, bread_id, "CRTV_bread", "WIN")
    db.close()


def test_manual_verdict_rejects_invalid_verdict_value():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=100, clicks=100)
    acc_id = acc.id
    db.close()

    db = TestSession()
    with pytest.raises(ManualVerdictError, match="WIN or LOSE"):
        award_manual_verdict(db, acc_id, "CRTV_A", "TEST")
    db.close()


def test_manual_verdict_rejects_an_ad_with_no_data():
    """The account has OTHER data (so month-resolution succeeds) but this
    specific ad_name never ran — almost certainly a typo, not a real award."""
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_other", on=MAY, spend=100, revenue=100, clicks=100)
    acc_id = acc.id
    db.close()

    db = TestSession()
    with pytest.raises(ManualVerdictError, match="nothing to award"):
        award_manual_verdict(db, acc_id, "CRTV_never_ran", "WIN")
    db.close()


def test_manual_verdict_rejects_when_account_has_no_data_at_all():
    db = TestSession()
    acc = _account(db)
    acc_id = acc.id
    db.close()

    db = TestSession()
    with pytest.raises(ManualVerdictError, match="pass `month` explicitly"):
        award_manual_verdict(db, acc_id, "CRTV_never_ran", "WIN")
    db.close()


def test_manual_verdict_uses_cumulative_totals_through_the_given_month():
    """Same convention as an automatic award: spend/revenue/clicks are
    cumulative through month-end, not just that one month's isolated total —
    and data AFTER the given month must not leak in."""
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_thin", on=MAY, spend=100, revenue=200, clicks=400)
    _metric(db, acc, ad_name="CRTV_thin", on=JUN, spend=100, revenue=200, clicks=400)
    _metric(db, acc, ad_name="CRTV_thin", on=JUL, spend=999, revenue=999, clicks=999)  # after the award month
    acc_id = acc.id
    db.close()

    db = TestSession()
    row = award_manual_verdict(db, acc_id, "CRTV_thin", "WIN", month=JUN)
    db.commit()
    assert row.month == month_start(JUN)
    assert float(row.spend) == 200  # May + June only, July excluded
    assert float(row.revenue) == 400
    assert row.clicks == 800
    db.close()


def test_manual_verdict_then_freeze_never_re_decides_it():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_thin", on=MAY, spend=100, revenue=300, clicks=400)
    acc_id = acc.id
    db.close()

    db = TestSession()
    award_manual_verdict(db, acc_id, "CRTV_thin", "WIN")
    db.commit()
    db.close()

    freeze_db = TestSession()
    summary = freeze_winning_months(freeze_db)
    freeze_db.close()

    db = TestSession()
    rows = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_thin").all()
    db.close()

    assert summary["awarded"] == 0  # freeze didn't touch it — already decided
    assert len(rows) == 1
    assert rows[0].verdict_source == "manual"


def test_manual_verdict_endpoint_creates_a_manual_row():
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    _metric(db, acc, ad_name="CRTV_thin", on=MAY, spend=100, revenue=300, clicks=400)
    acc_id = acc.id
    db.close()

    resp = client.post(
        "/api/creative/winning-months/manual-verdict",
        json={"account_id": acc_id, "ad_name": "CRTV_thin", "verdict": "WIN", "notes": "call it"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"], body["error"]
    assert body["data"]["verdict"] == "WIN"
    assert body["data"]["verdict_source"] == "manual"
    assert body["data"]["month"] == "2026-05"

    # And it shows up through the normal read path, tagged as manual.
    listed = client.get(
        "/api/creative/winning-months", params={"year": 2026}, headers=_admin_headers()
    ).json()["data"]
    may = next(m for m in listed["months"] if m["month"] == "2026-05")
    ad = next(a for a in may["ads"] if a["ad_name"] == "CRTV_thin")
    assert ad["verdict_source"] == "manual"
    assert ad["verdict_notes"] == "call it"


def test_manual_verdict_endpoint_rejects_duplicate_with_400_shaped_error():
    db = TestSession()
    acc = _account(db, name="Meander Saigon")
    _metric(db, acc, ad_name="CRTV_A", on=MAY, spend=100, revenue=500)  # auto-decides
    acc_id = acc.id
    db.close()

    freeze_db = TestSession()
    freeze_winning_months(freeze_db)
    freeze_db.close()

    resp = client.post(
        "/api/creative/winning-months/manual-verdict",
        json={"account_id": acc_id, "ad_name": "CRTV_A", "verdict": "LOSE"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200  # _api_response always 200; success=False carries the error
    body = resp.json()
    assert body["success"] is False
    assert "already has a WIN verdict" in body["error"]


# ── live ad state on the rows (preview link + is-it-still-running) ─────────


def _live_ad(db, acc, ad_id, ad_name, effective_status, preview=None):
    """A row in `ads` — what the platform sync writes. The winning-months rows
    match it by (branch, ad_name)."""
    from app.models.ad import Ad
    from app.models.ad_set import AdSet
    from app.models.campaign import Campaign

    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="meta",
        platform_campaign_id=f"c_{ad_id}", name="Camp", objective="OUTCOME_SALES",
        status="ACTIVE",
    )
    db.add(camp)
    aset = AdSet(
        id=str(uuid.uuid4()), campaign_id=camp.id, account_id=acc.id, platform="meta",
        platform_adset_id=f"s_{ad_id}", name="Set", status="ACTIVE",
    )
    db.add(aset)
    db.flush()
    db.add(Ad(
        id=str(uuid.uuid4()), ad_set_id=aset.id, campaign_id=camp.id, account_id=acc.id,
        platform="meta", platform_ad_id=ad_id, name=ad_name,
        status=effective_status, effective_status=effective_status, preview_url=preview,
    ))
    db.commit()


def _winner_rows(db, acc, month):
    """The awarded-winners list for one month."""
    data = list_winning_months(db, account_ids=[acc.id], month=month)
    bucket = next(m for m in data["months"] if m["month"] == month)
    return bucket["ads"]


def test_winner_rows_carry_the_meta_preview_link():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_Winner", on=date(2026, 3, 5),
            spend=1_000_000, revenue=6_000_000, clicks=3000, conversions=20)
    _metric(db, acc, ad_name="CRTV_Filler", on=date(2026, 3, 5),
            spend=1_000_000, revenue=1_000_000, clicks=3000, conversions=5)
    freeze_winning_months(db, account_ids=[acc.id])
    # Same creative shipped into two campaigns: one paused, one still live.
    _live_ad(db, acc, "a1", "CRTV_Winner", "PAUSED", "https://fb.com/p/a1")
    _live_ad(db, acc, "a2", "CRTV_Winner", "ACTIVE", "https://fb.com/p/a2")

    ads = _winner_rows(db, acc, "2026-03")
    win = next(a for a in ads if a["ad_name"] == "CRTV_Winner")
    assert win["preview_url"] == "https://fb.com/p/a2"  # links the live one
    assert win["live_status"] == "ACTIVE"
    assert win["live_active_count"] == 1
    assert win["live_ad_count"] == 2
    # The verdict fields are untouched — live state must not be read as one.
    assert win["roas"] is not None
    db.close()


def test_winner_row_without_a_live_ad_still_renders():
    # Nothing synced yet, or the ad was archived on Meta after it won. The
    # award must survive; only the link goes missing.
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="CRTV_Winner", on=date(2026, 3, 5),
            spend=1_000_000, revenue=6_000_000, clicks=3000, conversions=20)
    _metric(db, acc, ad_name="CRTV_Filler", on=date(2026, 3, 5),
            spend=1_000_000, revenue=1_000_000, clicks=3000, conversions=5)
    freeze_winning_months(db, account_ids=[acc.id])

    win = next(a for a in _winner_rows(db, acc, "2026-03") if a["ad_name"] == "CRTV_Winner")
    assert win["preview_url"] is None
    assert win["live_status"] is None
    assert win["live_ad_count"] == 0
    db.close()


def test_live_state_never_crosses_branches():
    # Two branches running an identically-named creative: each row must read
    # its own branch's ad, not the other's.
    db = TestSession()
    sgn = _account(db, "Saigon")
    tpe = _account(db, "Taipei")
    for acc in (sgn, tpe):
        _metric(db, acc, ad_name="CRTV_Same", on=date(2026, 3, 5),
                spend=1_000_000, revenue=6_000_000, clicks=3000, conversions=20)
        _metric(db, acc, ad_name="CRTV_Filler", on=date(2026, 3, 5),
                spend=1_000_000, revenue=1_000_000, clicks=3000, conversions=5)
    freeze_winning_months(db, account_ids=[sgn.id, tpe.id])
    _live_ad(db, sgn, "s1", "CRTV_Same", "ACTIVE", "https://fb.com/p/sgn")
    _live_ad(db, tpe, "t1", "CRTV_Same", "PAUSED", "https://fb.com/p/tpe")

    sgn_win = next(a for a in _winner_rows(db, sgn, "2026-03") if a["ad_name"] == "CRTV_Same")
    tpe_win = next(a for a in _winner_rows(db, tpe, "2026-03") if a["ad_name"] == "CRTV_Same")
    assert sgn_win["preview_url"] == "https://fb.com/p/sgn"
    assert sgn_win["live_status"] == "ACTIVE"
    assert tpe_win["preview_url"] == "https://fb.com/p/tpe"
    assert tpe_win["live_status"] == "PAUSED"
    db.close()
