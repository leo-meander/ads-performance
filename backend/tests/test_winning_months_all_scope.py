"""The second verdict universe: SCOPE_ALL — every ad, no exclusions.

Per Mason (2026-08-14): alongside the design KPI (KOL-named ads and Bread
excluded) he wants the same monthly WIN/LOSE view over EVERYTHING, for his own
tracking — "tab này sẽ tính tất cả các ads (tính cả Bread luôn)".

What must hold:
  1. SCOPE_ALL excludes nothing — KOL ads and Bread are candidates, and both
     feed the account's blended benchmark (so the bar genuinely differs from
     the KPI's).
  2. The two scopes are INDEPENDENT. Each freezes its own rows, reads only its
     own rows, and "an ad is judged once, ever" applies per scope — so the
     same ad legitimately holds one verdict in each, and a verdict frozen in
     one never suppresses candidacy in the other.
  3. The KPI stays exactly as it was. list_winning_months(scope='kpi'), the
     /export/winning-ads-monthly feed that drives HiD's "% Ads Win", and the
     Bread/KOL exclusions must not see a single SCOPE_ALL row.
  4. A rebuild only wipes the scope it was asked for.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.api_key import ApiKey
from app.models.user import User
from app.models.winning_ad_month import WinningAdMonth
from app.services.auth_service import create_access_token, hash_password
from app.services.export_auth import generate_api_key
from app.services.winning_months_service import (
    SCOPE_ALL,
    SCOPE_KPI,
    compute_lifetime_benchmark,
    compute_month_verdicts,
    eligible_accounts,
    freeze_winning_months,
    list_winning_months,
    normalize_scope,
    rebuild_winning_months,
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


def _account(db, name="Meander Saigon"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency="VND", access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _metric(db, acc, *, ad_name, on, spend, revenue, clicks=100, conversions=10):
    db.add(AdDailyMetric(
        id=str(uuid.uuid4()), account_id=acc.id,
        campaign_id="c1", campaign_name="Camp", adset_id="s1", adset_name="Set",
        ad_id=uuid.uuid4().hex[:8], ad_name=ad_name, date=on,
        spend=spend, revenue=revenue, impressions=1000,
        clicks=clicks, conversions=conversions,
    ))
    db.commit()


# ── scope 1: nothing is excluded ──────────────────────────


def test_normalize_scope_falls_back_to_the_kpi():
    """Anything unrecognised must land on the NARROWER scope. The other way
    round, a typo'd query param would quietly publish un-excluded numbers as
    the design KPI."""
    assert normalize_scope("all") == SCOPE_ALL
    assert normalize_scope("ALL") == SCOPE_ALL
    assert normalize_scope("kpi") == SCOPE_KPI
    assert normalize_scope(None) == SCOPE_KPI
    assert normalize_scope("") == SCOPE_KPI
    assert normalize_scope("everything") == SCOPE_KPI


def test_all_scope_counts_kol_ads_and_moves_the_benchmark():
    """The KPI's headline exclusion, inverted: under SCOPE_ALL a KOL ad is a
    candidate AND part of the bar. Same data, two honest answers."""
    db = TestSession()
    acc = _account(db)
    # Non-KOL pair blends to 600/200 = 3.0x. Adding a 100x KOL ad lifts the
    # all-scope bar to 10,600/300 ≈ 35.3x — high enough that Plain_A (5.0x),
    # a WIN under the KPI bar, must LOSE here.
    _metric(db, acc, ad_name="Plain_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="Plain_B", on=MAY, spend=100, revenue=100)
    _metric(db, acc, ad_name="KOL_runawaygirl", on=MAY, spend=100, revenue=10_000)

    kpi_bar = compute_lifetime_benchmark(db, acc.id)
    all_bar = compute_lifetime_benchmark(db, acc.id, SCOPE_ALL)
    kpi_decided = compute_month_verdicts(db, acc.id, MAY, kpi_bar)
    all_decided = compute_month_verdicts(db, acc.id, MAY, all_bar, scope=SCOPE_ALL)
    db.close()

    assert kpi_bar == 3.0
    assert round(all_bar, 2) == 35.33

    assert {d["ad_name"] for d in kpi_decided} == {"Plain_A", "Plain_B"}
    assert [d["ad_name"] for d in kpi_decided if d["verdict"] == "WIN"] == ["Plain_A"]

    # The KOL ad is judged here, and it is the only thing clearing its own bar.
    assert {d["ad_name"] for d in all_decided} == {"Plain_A", "Plain_B", "KOL_runawaygirl"}
    assert [d["ad_name"] for d in all_decided if d["verdict"] == "WIN"] == ["KOL_runawaygirl"]


def test_all_scope_covers_bread():
    """Bread is out of the KPI entirely; under SCOPE_ALL it is an ordinary
    branch — eligible for the pass, and frozen into rows of its own."""
    db = TestSession()
    hotel = _account(db, name="Meander Saigon")
    bread = _account(db, name="Bread Espresso")
    for acc in (hotel, bread):
        _metric(db, acc, ad_name=f"CRTV_win_{acc.account_name}", on=MAY, spend=100, revenue=500)
        _metric(db, acc, ad_name=f"CRTV_lose_{acc.account_name}", on=MAY, spend=100, revenue=100)
        _metric(db, acc, ad_name=f"CRTV_next_{acc.account_name}", on=JUN, spend=100, revenue=100)
    bread_id = bread.id
    db.close()

    scope_db = TestSession()
    kpi_names = {a.account_name for a in eligible_accounts(scope_db)}
    all_names = {a.account_name for a in eligible_accounts(scope_db, SCOPE_ALL)}
    freeze_winning_months(scope_db, scope=SCOPE_ALL)
    bread_all = (
        scope_db.query(WinningAdMonth)
        .filter(WinningAdMonth.account_id == bread_id, WinningAdMonth.scope == SCOPE_ALL)
        .count()
    )
    bread_kpi = (
        scope_db.query(WinningAdMonth)
        .filter(WinningAdMonth.account_id == bread_id, WinningAdMonth.scope == SCOPE_KPI)
        .count()
    )
    scope_db.close()

    assert "Bread Espresso" not in kpi_names
    assert "Bread Espresso" in all_names
    assert bread_all > 0
    assert bread_kpi == 0  # the KPI pass never ran for it, and never will


def test_endpoint_scope_all_reports_bread_and_kpi_scope_does_not():
    db = TestSession()
    hotel = _account(db, name="Meander Saigon")
    bread = _account(db, name="Bread Espresso")
    for acc in (hotel, bread):
        _metric(db, acc, ad_name=f"CRTV_win_{acc.account_name}", on=MAY, spend=100, revenue=500)
        _metric(db, acc, ad_name=f"CRTV_lose_{acc.account_name}", on=MAY, spend=100, revenue=100)
        _metric(db, acc, ad_name=f"CRTV_next_{acc.account_name}", on=JUN, spend=100, revenue=100)
    db.close()

    headers = _admin_headers()
    kpi = client.get(
        "/api/creative/winning-months", params={"year": 2026}, headers=headers
    ).json()["data"]
    all_ = client.get(
        "/api/creative/winning-months", params={"year": 2026, "scope": "all"}, headers=headers
    ).json()["data"]

    kpi_branches = {b["branch_name"] for m in kpi["months"] for b in m["by_branch"]}
    all_branches = {b["branch_name"] for m in all_["months"] for b in m["by_branch"]}

    assert kpi_branches == {"Meander Saigon"}
    assert all_branches == {"Meander Saigon", "Bread Espresso"}
    assert kpi["scope"] == SCOPE_KPI
    assert all_["scope"] == SCOPE_ALL
    assert "no exclusions" in all_["scope_note"]


# ── scope 2: the two universes are independent ────────────


def test_each_scope_judges_an_ad_on_its_own_and_neither_blocks_the_other():
    """"Judged once, ever" is per scope. The same ad gets one row in each,
    with the verdict its own scope's benchmark implies — and freezing one
    scope first must not make the ad look already-decided to the other."""
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="Plain_A", on=MAY, spend=100, revenue=500)
    _metric(db, acc, ad_name="Plain_B", on=MAY, spend=100, revenue=100)
    _metric(db, acc, ad_name="KOL_star", on=MAY, spend=100, revenue=10_000)
    # A later month closes MAY so LOSEs freeze too.
    _metric(db, acc, ad_name="Plain_A", on=JUN, spend=0, revenue=0, clicks=0, conversions=0)
    acc_id = acc.id
    db.close()

    freeze_db = TestSession()
    freeze_winning_months(freeze_db, scope=SCOPE_KPI)   # KPI first…
    freeze_winning_months(freeze_db, scope=SCOPE_ALL)   # …then the wider one
    rows = {
        (r.ad_name, r.scope): r.verdict
        for r in freeze_db.query(WinningAdMonth)
        .filter(WinningAdMonth.account_id == acc_id).all()
    }
    freeze_db.close()

    # Plain_A: WIN at the 3.0x KPI bar, LOSE at the ~35x all-ads bar.
    assert rows[("Plain_A", SCOPE_KPI)] == "WIN"
    assert rows[("Plain_A", SCOPE_ALL)] == "LOSE"
    # The KOL ad exists only in the wider scope.
    assert ("KOL_star", SCOPE_KPI) not in rows
    assert rows[("KOL_star", SCOPE_ALL)] == "WIN"


def test_read_paths_never_mix_the_two_scopes():
    db = TestSession()
    acc = _account(db)
    for scope, ad in ((SCOPE_KPI, "CRTV_kpi_only"), (SCOPE_ALL, "KOL_all_only")):
        db.add(WinningAdMonth(
            id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
            ad_name=ad, scope=scope, verdict="WIN", spend=100, revenue=500, roas=5.0,
            benchmark_roas=3.0, frozen_at=datetime.now(timezone.utc),
        ))
    db.commit()

    kpi = list_winning_months(db, year=2026)
    all_ = list_winning_months(db, year=2026, scope=SCOPE_ALL)
    db.close()

    assert [a["ad_name"] for m in kpi["months"] for a in m["ads"]] == ["CRTV_kpi_only"]
    assert [a["ad_name"] for m in all_["months"] for a in m["ads"]] == ["KOL_all_only"]
    assert kpi["total_wins"] == all_["total_wins"] == 1


def test_rebuild_only_wipes_the_scope_it_was_asked_for():
    db = TestSession()
    acc = _account(db)
    # A hand-written row in each scope, for a month with no metrics behind it:
    # a rebuild of that scope deletes it and re-freezes nothing.
    for scope in (SCOPE_KPI, SCOPE_ALL):
        db.add(WinningAdMonth(
            id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
            ad_name="CRTV_ghost", scope=scope, verdict="WIN", spend=100, revenue=500,
            roas=5.0, benchmark_roas=3.0, frozen_at=datetime.now(timezone.utc),
        ))
    db.commit()
    db.close()

    rb = TestSession()
    summary = rebuild_winning_months(rb, scope=SCOPE_ALL)
    remaining = {
        (r.ad_name, r.scope)
        for r in rb.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "CRTV_ghost").all()
    }
    rb.close()

    assert summary["deleted"] == 1
    assert summary["scope"] == SCOPE_ALL
    assert remaining == {("CRTV_ghost", SCOPE_KPI)}  # the KPI row survives untouched


# ── scope 3: the KPI feed is untouched ────────────────────


def test_hid_kpi_export_ignores_all_scope_rows():
    """/export/winning-ads-monthly drives HiD's "% Ads Win". A SCOPE_ALL row —
    here a KOL ad on Bread, doubly out of the KPI — must not reach it."""
    db = TestSession()
    plaintext, key_hash, key_prefix = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), name="HiD", key_hash=key_hash, key_prefix=key_prefix))
    hotel = _account(db, name="Meander Saigon")
    bread = _account(db, name="Bread Espresso")
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=hotel.id, month=date(2026, 5, 1),
        ad_name="CRTV_real_kpi_win", scope=SCOPE_KPI, verdict="WIN",
        spend=100, revenue=500, roas=5.0, benchmark_roas=3.0,
        frozen_at=datetime.now(timezone.utc),
    ))
    for acc, ad in ((hotel, "KOL_star"), (bread, "CRTV_bread")):
        db.add(WinningAdMonth(
            id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
            ad_name=ad, scope=SCOPE_ALL, verdict="WIN", spend=100, revenue=9000,
            roas=90.0, benchmark_roas=3.0, frozen_at=datetime.now(timezone.utc),
        ))
    db.commit()
    db.close()

    data = client.get(
        "/api/export/winning-ads-monthly",
        headers={"X-API-Key": plaintext},
        params={"year": 2026},
    ).json()["data"]

    assert [r["ad_name"] for r in data["rows"]] == ["CRTV_real_kpi_win"]
    assert data["total_wins"] == 1
