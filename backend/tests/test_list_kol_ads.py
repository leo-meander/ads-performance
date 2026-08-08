"""Tests for winning_months_service.list_kol_ads — finding every
currently-spending ad that Winning by Month is blind to because its name
contains "KOL" (the one excluded category).

Coverage:
  - a KOL ad is listed with its aggregated spend/revenue/roas
  - a non-KOL ad is excluded entirely (it already counts toward the KPI)
  - multiple day-rows for the same ad_name are summed, not duplicated
  - results are ranked by spend descending
  - account_name_filter scopes to one branch (substring, case-insensitive)
  - an ad with zero spend still appears with roas=None, not a crash
"""
from __future__ import annotations

import uuid
from datetime import date

from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.services.winning_months_service import list_kol_ads
from tests.db import TestSession


def _account(db, name="Meander 1948"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency="VND", access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _metric(db, acc, *, ad_name, on, spend, revenue, conversions=5, ad_id=None):
    db.add(AdDailyMetric(
        id=str(uuid.uuid4()), account_id=acc.id,
        campaign_id="c1", campaign_name="Camp", adset_id="s1", adset_name="Set",
        ad_id=ad_id or uuid.uuid4().hex[:8], ad_name=ad_name, date=on,
        spend=spend, revenue=revenue, impressions=1000, clicks=50, conversions=conversions,
    ))
    db.commit()


def test_kol_ad_is_listed_with_totals():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="[Video] KOL_runawaygirl", on=date(2026, 8, 1), spend=100, revenue=300)

    result = list_kol_ads(db)

    assert result["count"] == 1
    ad = result["ads"][0]
    assert ad["ad_name"] == "[Video] KOL_runawaygirl"
    assert ad["account_name"] == "Meander 1948"
    assert ad["spend"] == 100
    assert ad["revenue"] == 300
    assert ad["roas"] == 3.0
    db.close()


def test_non_kol_ad_is_excluded():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="[Carousel] Full plan travel", on=date(2026, 8, 1), spend=100, revenue=300)

    result = list_kol_ads(db)

    assert result["count"] == 0
    assert result["ads"] == []
    db.close()


def test_kol_match_is_case_insensitive():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="kol_lowercase_variant", on=date(2026, 8, 1), spend=100, revenue=300)

    result = list_kol_ads(db)
    assert result["count"] == 1
    db.close()


def test_multiple_days_are_summed_not_duplicated():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="KOL_full_plan_travel", on=date(2026, 8, 1), spend=100, revenue=300, ad_id="fixed")
    _metric(db, acc, ad_name="KOL_full_plan_travel", on=date(2026, 8, 2), spend=50, revenue=150, ad_id="fixed")

    result = list_kol_ads(db)

    assert result["count"] == 1
    ad = result["ads"][0]
    assert ad["spend"] == 150
    assert ad["revenue"] == 450
    assert ad["roas"] == 3.0
    db.close()


def test_ranked_by_spend_descending():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="KOL_small_spender", on=date(2026, 8, 1), spend=10, revenue=20)
    _metric(db, acc, ad_name="KOL_big_spender", on=date(2026, 8, 1), spend=1000, revenue=2000)
    _metric(db, acc, ad_name="KOL_mid_spender", on=date(2026, 8, 1), spend=100, revenue=200)

    result = list_kol_ads(db)

    assert [a["ad_name"] for a in result["ads"]] == ["KOL_big_spender", "KOL_mid_spender", "KOL_small_spender"]
    db.close()


def test_account_name_filter_scopes_to_one_branch():
    db = TestSession()
    oani = _account(db, "Oani (Taipei)")
    saigon = _account(db, "Meander Saigon")
    _metric(db, oani, ad_name="KOL_oani_travel_ad", on=date(2026, 8, 1), spend=100, revenue=200)
    _metric(db, saigon, ad_name="KOL_saigon_travel_ad", on=date(2026, 8, 1), spend=100, revenue=200)

    result = list_kol_ads(db, account_name_filter="oani")

    assert result["count"] == 1
    assert result["ads"][0]["account_name"] == "Oani (Taipei)"
    db.close()


def test_zero_spend_ad_has_none_roas_not_a_crash():
    db = TestSession()
    acc = _account(db)
    _metric(db, acc, ad_name="KOL_no_spend_yet", on=date(2026, 8, 1), spend=0, revenue=0)

    result = list_kol_ads(db)

    assert result["count"] == 1
    assert result["ads"][0]["roas"] is None
    db.close()


def test_no_ads_at_all_returns_empty_not_error():
    db = TestSession()
    _account(db)
    db.commit()

    result = list_kol_ads(db)
    assert result == {
        "count": 0, "ads": [],
        "note": result["note"],  # just confirm the key exists; content checked elsewhere
    }
    db.close()
