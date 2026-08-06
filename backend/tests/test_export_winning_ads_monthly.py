"""Tests for GET /api/export/winning-ads-monthly (X-API-Key).

The design-team KPI feed for the HiD Dashboard. Locks in that it reads the
FROZEN winning_ad_months rows (not the drifting Library verdict), exposes one
row per award with the ad's TOTAL spend/revenue for that month, converts money
to VND so a cross-branch dashboard can sum one column, and honours the
branch/month/year filters.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.api_key import ApiKey
from app.models.winning_ad_month import WinningAdMonth
from app.services.export_auth import generate_api_key
from tests.db import TestSession

client = TestClient(app)


def _api_key(db) -> str:
    plaintext, key_hash, key_prefix = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), name="HiD Dashboard", key_hash=key_hash, key_prefix=key_prefix))
    db.commit()
    return plaintext


def _account(db, name="Meander Osaka", currency="JPY") -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}", account_name=name,
        currency=currency, is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _award(db, account, *, month, ad_name, spend, revenue, roas, conversions=5,
           country="JP", ta="Solo", verdict="WIN"):
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=account.id, month=month, ad_name=ad_name,
        verdict=verdict, combo_id=None, target_audience=ta, country=country,
        spend=spend, revenue=revenue, impressions=1000, clicks=100,
        conversions=conversions, roas=roas, benchmark_roas=3.0,
        frozen_at=datetime.now(timezone.utc),
    ))
    db.commit()


def _get(key, **params):
    return client.get(
        "/api/export/winning-ads-monthly",
        headers={"X-API-Key": key},
        params=params,
    )


def test_requires_api_key():
    """No header at all is a FastAPI validation error (the dependency declares
    X-API-Key required); a header that doesn't match any active key is a 401."""
    db = TestSession()
    _account(db)
    db.commit()

    assert client.get("/api/export/winning-ads-monthly").status_code == 422
    assert client.get(
        "/api/export/winning-ads-monthly", headers={"X-API-Key": "not-a-real-key"}
    ).status_code == 401
    db.close()


def test_rows_carry_totals_and_vnd_conversion():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Osaka", "JPY")
    _award(db, acc, month=date(2026, 8, 1), ad_name="[Video] CRTV_Solo_JP",
           spend=2000, revenue=50000, roas=25.0)

    r = _get(key)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]

    assert data["total_wins"] == 1
    assert data["distinct_ads"] == 1
    row = data["rows"][0]
    assert row["month"] == "2026-08"
    assert row["ad_name"] == "[Video] CRTV_Solo_JP"
    assert row["spend"] == 2000
    assert row["revenue"] == 50000
    assert row["roas"] == 25.0
    assert row["benchmark_roas"] == 3.0
    # JPY branch → FX applied for the cross-branch column; ROAS untouched.
    assert row["currency"] == "JPY"
    assert row["spend_vnd"] == 2000 * 170
    assert row["revenue_vnd"] == 50000 * 170
    db.close()


def test_by_month_summary_counts_wins_per_branch():
    db = TestSession()
    key = _api_key(db)
    osaka = _account(db, "Meander Osaka", "JPY")
    saigon = _account(db, "Meander Saigon", "VND")
    _award(db, osaka, month=date(2026, 8, 1), ad_name="CRTV_a", spend=100, revenue=500, roas=5.0)
    _award(db, saigon, month=date(2026, 8, 1), ad_name="CRTV_b", spend=200, revenue=400, roas=2.0)
    _award(db, saigon, month=date(2026, 7, 1), ad_name="CRTV_c", spend=50, revenue=250, roas=5.0)

    data = _get(key).json()["data"]

    assert data["total_wins"] == 3
    # Newest month first.
    assert [m["month"] for m in data["by_month"]] == ["2026-08", "2026-07"]
    aug = data["by_month"][0]
    assert aug["wins"] == 2
    # Branch keys come from core.branches (capitalised: Saigon/Osaka/...).
    assert {b["branch"]: b["wins"] for b in aug["by_branch"]} == {"Osaka": 1, "Saigon": 1}
    db.close()


def test_month_filter_narrows_to_one_month():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Saigon", "VND")
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_aug", spend=1, revenue=5, roas=5.0)
    _award(db, acc, month=date(2026, 7, 1), ad_name="CRTV_jul", spend=1, revenue=5, roas=5.0)

    data = _get(key, month="2026-08").json()["data"]
    assert [r["ad_name"] for r in data["rows"]] == ["CRTV_aug"]
    db.close()


def test_year_filter_excludes_other_years():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Saigon", "VND")
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_2026", spend=1, revenue=5, roas=5.0)
    _award(db, acc, month=date(2025, 8, 1), ad_name="CRTV_2025", spend=1, revenue=5, roas=5.0)

    data = _get(key, year=2026).json()["data"]
    assert [r["ad_name"] for r in data["rows"]] == ["CRTV_2026"]
    db.close()


def test_unknown_branch_is_an_error_not_silent_empty():
    db = TestSession()
    key = _api_key(db)
    _account(db)
    db.commit()

    body = _get(key, branch="atlantis").json()
    assert body["success"] is False
    assert "atlantis" in body["error"]
    db.close()


def test_invalid_month_is_rejected():
    db = TestSession()
    key = _api_key(db)
    _account(db)
    db.commit()

    body = _get(key, month="August").json()
    assert body["success"] is False
    assert "YYYY-MM" in body["error"]
    db.close()


def test_win_rate_counts_losses_in_the_denominator_only():
    """The "% Ads win" KPI the HiD Dashboard pulls: LOSE verdicts move
    `tested` / `win_rate` but never leak into `rows` or the money totals."""
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Saigon", "VND")
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_win", spend=100, revenue=500, roas=5.0)
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_lose1", spend=900, revenue=90,
           roas=0.1, verdict="LOSE")
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_lose2", spend=800, revenue=80,
           roas=0.1, verdict="LOSE")

    data = _get(key).json()["data"]

    assert [r["ad_name"] for r in data["rows"]] == ["CRTV_win"]
    aug = data["by_month"][0]
    assert (aug["wins"], aug["losses"], aug["tested"]) == (1, 2, 3)
    assert aug["win_rate"] == 1 / 3
    # Losers' spend/revenue stay out of the winners-only money columns.
    assert aug["spend_vnd"] == 100
    assert aug["revenue_vnd"] == 500

    assert data["total_wins"] == 1
    assert data["total_losses"] == 2
    assert data["total_tested"] == 3
    assert data["overall_win_rate"] == 1 / 3
    assert data["distinct_ads"] == 1
    db.close()


def test_by_branch_carries_its_own_denominator():
    """Per-branch win rate without one HTTP call per branch."""
    db = TestSession()
    key = _api_key(db)
    osaka = _account(db, "Meander Osaka", "JPY")
    saigon = _account(db, "Meander Saigon", "VND")
    _award(db, osaka, month=date(2026, 8, 1), ad_name="CRTV_o1", spend=100, revenue=500, roas=5.0)
    _award(db, osaka, month=date(2026, 8, 1), ad_name="CRTV_o2", spend=100, revenue=10,
           roas=0.1, verdict="LOSE")
    _award(db, saigon, month=date(2026, 8, 1), ad_name="CRTV_s1", spend=100, revenue=500, roas=5.0)

    aug = _get(key).json()["data"]["by_month"][0]
    by_branch = {b["branch"]: b for b in aug["by_branch"]}

    assert by_branch["Osaka"]["wins"] == 1
    assert by_branch["Osaka"]["tested"] == 2
    assert by_branch["Osaka"]["win_rate"] == 0.5
    assert by_branch["Saigon"]["win_rate"] == 1.0
    db.close()


def test_month_with_only_losses_reports_zero_win_rate():
    """A month where nothing won must still appear — otherwise the KPI reads
    as "no data" instead of the 0% it actually was."""
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Saigon", "VND")
    _award(db, acc, month=date(2026, 7, 1), ad_name="CRTV_flop", spend=500, revenue=50,
           roas=0.1, verdict="LOSE")

    data = _get(key).json()["data"]

    assert [m["month"] for m in data["by_month"]] == ["2026-07"]
    jul = data["by_month"][0]
    assert (jul["wins"], jul["tested"], jul["win_rate"]) == (0, 1, 0.0)
    assert data["rows"] == []
    db.close()


def test_in_progress_flags_the_month_a_branch_is_still_syncing():
    """LOSE only freezes for a CLOSED month, so the newest synced month's
    win_rate is provisional — the flag says so instead of the consumer
    guessing from wall-clock today."""
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Saigon", "VND")
    _award(db, acc, month=date(2026, 7, 1), ad_name="CRTV_jul", spend=100, revenue=500, roas=5.0)
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_aug", spend=100, revenue=500, roas=5.0)
    db.add(AdDailyMetric(
        id=str(uuid.uuid4()), account_id=acc.id, ad_id="123", ad_name="CRTV_aug",
        date=date(2026, 8, 14), spend=100, revenue=500,
    ))
    db.commit()

    by_month = {m["month"]: m for m in _get(key).json()["data"]["by_month"]}
    assert by_month["2026-08"]["in_progress"] is True
    assert by_month["2026-07"]["in_progress"] is False
    db.close()


def test_same_ad_winning_two_months_counts_once_as_distinct():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Saigon", "VND")
    _award(db, acc, month=date(2026, 8, 1), ad_name="CRTV_repeat", spend=1, revenue=5, roas=5.0)
    _award(db, acc, month=date(2026, 7, 1), ad_name="CRTV_repeat", spend=1, revenue=5, roas=5.0)

    data = _get(key).json()["data"]
    assert data["total_wins"] == 2
    assert data["distinct_ads"] == 1
    db.close()
