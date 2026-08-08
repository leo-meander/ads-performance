"""Tests for winning_months_service.diagnose_winning_by_month — explaining an
empty Winning-by-Month tab.

freeze_winning_months() has two silent skip conditions (zero ad_daily_metrics
rows for an account; rows present but every one is "KOL"-tagged, the one
excluded category) and neither logs anything. Coverage: each condition is
surfaced distinctly, a populated-and-eligible account shows up in neither
bucket, and the naming sample only appears for the "populated but all KOL"
case (not when there's simply no data at all — nothing to sample).
"""
from __future__ import annotations

import uuid
from datetime import date

from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.services.winning_months_service import diagnose_winning_by_month
from tests.db import TestSession


def _account(db, name):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency="VND", access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _metric(db, acc, ad_name, on=date(2026, 5, 10)):
    db.add(AdDailyMetric(
        id=str(uuid.uuid4()), account_id=acc.id,
        campaign_id="c1", campaign_name="Camp", adset_id="s1", adset_name="Set",
        ad_id=uuid.uuid4().hex[:8], ad_name=ad_name, date=on,
        spend=100, revenue=200, impressions=1000, clicks=50, conversions=5,
    ))
    db.commit()


def test_account_never_synced_is_flagged():
    db = TestSession()
    acc = _account(db, "Meander Never Synced")

    result = diagnose_winning_by_month(db)

    assert "Meander Never Synced" in result["accounts_never_synced_daily_metrics"]
    assert "Meander Never Synced" not in result["accounts_synced_but_all_kol"]
    entry = next(e for e in result["accounts"] if e["account_name"] == "Meander Never Synced")
    assert entry["ad_daily_metrics_rows"] == 0
    assert entry["date_range"] is None
    assert "sample_ad_names" not in entry  # nothing to sample
    db.close()


def test_account_synced_but_all_kol_is_flagged_with_sample():
    db = TestSession()
    acc = _account(db, "Meander All KOL")
    _metric(db, acc, "KOL_dnvrchoi_locationtips")
    _metric(db, acc, "[Video] KOL_someone_else")

    result = diagnose_winning_by_month(db)

    assert "Meander All KOL" in result["accounts_synced_but_all_kol"]
    assert "Meander All KOL" not in result["accounts_never_synced_daily_metrics"]
    entry = next(e for e in result["accounts"] if e["account_name"] == "Meander All KOL")
    assert entry["ad_daily_metrics_rows"] == 2
    assert entry["distinct_eligible_ad_names"] == 0
    assert set(entry["sample_ad_names"]) == {
        "KOL_dnvrchoi_locationtips", "[Video] KOL_someone_else",
    }
    db.close()


def test_account_with_non_kol_ads_is_not_flagged():
    db = TestSession()
    acc = _account(db, "Meander Healthy")
    _metric(db, acc, "[Video] AI_Text Overlay Solo F")

    result = diagnose_winning_by_month(db)

    assert "Meander Healthy" not in result["accounts_never_synced_daily_metrics"]
    assert "Meander Healthy" not in result["accounts_synced_but_all_kol"]
    entry = next(e for e in result["accounts"] if e["account_name"] == "Meander Healthy")
    assert entry["distinct_eligible_ad_names"] == 1
    assert "sample_ad_names" not in entry
    db.close()


def test_frozen_awards_count_reflects_existing_rows():
    from app.models.winning_ad_month import WinningAdMonth

    db = TestSession()
    acc = _account(db, "Meander With Award")
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
        ad_name="[Video] CRTV_Couple_PH",
    ))
    db.commit()

    result = diagnose_winning_by_month(db)

    assert result["frozen_awards_so_far"] == 1
    db.close()
