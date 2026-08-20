"""Tests for the MCP get_ad_benchmarks tool.

The bar every ad in get_winning_ads is read against: each branch's own CTR,
click-to-book, ROAS and video funnel over a window, at the same (branch,
ad_name) grain and the same scope. These tests lock in:
  * median vs blended — the median is the middle AD, the blended is pooled
    totals, and they must NOT be the same number when spend is lopsided,
  * video medians taken over VIDEO ads only, so an image ad's absent hook rate
    never enters the population as a zero,
  * scope 'kpi' dropping KOL ads + Bread, exactly like get_winning_ads,
  * lifetime_benchmark_roas staying separate from the window's own ROAS,
  * clicks_per_booking as the readable form of click_to_book_pct,
  * min_spend keeping noise ads out of the bar.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.mcp.tools import _get_ad_benchmarks
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from tests.db import TestSession

MAY = {"date_from": "2026-05-01", "date_to": "2026-05-31"}


@pytest.fixture()
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    """Saigon with three ads of deliberately unequal size, plus a KOL ad.

    "Big Ad" carries most of the impressions and performs worse than the two
    small ads, so the blended CTR sits well below the median CTR — the whole
    reason both are reported.
    """
    sgn = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_sgn",
        account_name="Meander Saigon", is_active=True,
    )
    bread = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_bread",
        account_name="Bread", is_active=True,
    )
    db.add_all([sgn, bread])
    db.flush()

    def metric(acc, ad_id, ad_name, day, spend, impressions, clicks, conversions=0,
               revenue=0, engagement=None, video_plays=None, video_3s=None,
               thruplay=None, video_p100=None):
        db.add(AdDailyMetric(
            account_id=acc.id, ad_id=ad_id, ad_name=ad_name, date=day, spend=spend,
            impressions=impressions, clicks=clicks, conversions=conversions,
            revenue=revenue, engagement=engagement, video_plays=video_plays,
            video_3s=video_3s, thruplay=thruplay, video_p100=video_p100,
        ))

    # Video ad, small and sharp: CTR 5%, hook 40%, thruplay 25%, hold 62.5%.
    metric(sgn, "ad1", "Sharp Ad", date(2026, 5, 1), 100, 1000, 50, conversions=1,
           revenue=500, engagement=300, video_plays=800, video_3s=400, thruplay=250,
           video_p100=100)
    # Video ad, middling: CTR 3%, hook 20%, thruplay 10%, hold 25%.
    metric(sgn, "ad2", "Mid Ad", date(2026, 5, 2), 100, 1000, 30, conversions=1,
           revenue=200, engagement=150, video_plays=500, video_3s=200, thruplay=50,
           video_p100=25)
    # IMAGE ad and the volume hog: 8000 impressions, CTR 1%, no video at all.
    metric(sgn, "ad3", "Big Ad", date(2026, 5, 3), 800, 8000, 80, conversions=2,
           revenue=800, engagement=400)
    # Out of KPI scope.
    metric(sgn, "ad4", "KOL Collab", date(2026, 5, 4), 50, 1000, 100, conversions=5,
           revenue=5000, engagement=500, video_plays=900, video_3s=800, thruplay=700,
           video_p100=400)
    metric(bread, "ad5", "Bread Ad", date(2026, 5, 3), 40, 1000, 40, conversions=4,
           revenue=400)
    db.commit()
    return {"sgn": sgn.id, "bread": bread.id}


def _saigon(res):
    return next(b for b in res["branches"] if b["branch"] == "Meander Saigon")


def test_median_is_the_middle_ad_not_the_pooled_total(db, seeded):
    """Median and blended must disagree when one ad owns most of the volume."""
    sgn = _saigon(_get_ad_benchmarks(MAY, db))
    assert sgn["ads"] == 3                      # KOL ad excluded under 'kpi'
    # Per-ad CTRs are 5%, 3%, 1% -> middle is 3%.
    assert sgn["median"]["ctr_pct"] == 3.0
    # Pooled: 160 clicks / 10000 impressions = 1.6%, dragged down by "Big Ad".
    assert sgn["blended"]["ctr_pct"] == 1.6


def test_video_medians_ignore_ads_without_video(db, seeded):
    """"Big Ad" is an image ad — it must not enter the hook-rate population."""
    sgn = _saigon(_get_ad_benchmarks(MAY, db))
    assert sgn["video_ads"] == 2                # Sharp + Mid, not Big
    # Hook rates are 40% and 20% -> median 30%. Counting Big Ad as 0 gives 20%.
    assert sgn["median"]["hook_rate_pct"] == 30.0
    # Hold rate = thruplay / 3s plays: 62.5% and 25% -> median 43.75%.
    assert sgn["median"]["hold_rate_pct"] == 43.75
    # Blended hook still divides by ALL impressions, video or not: 600 / 10000.
    assert sgn["blended"]["hook_rate_pct"] == 6.0


def test_click_to_book_and_clicks_per_booking(db, seeded):
    sgn = _saigon(_get_ad_benchmarks(MAY, db))
    # 4 bookings / 160 clicks = 2.5%; 4 decimals keeps sub-0.1% readable.
    assert sgn["blended"]["click_to_book_pct"] == 2.5
    assert sgn["clicks_per_booking"] == 40


def test_kpi_scope_drops_kol_and_bread(db, seeded):
    res = _get_ad_benchmarks(MAY, db)
    assert [b["branch"] for b in res["branches"]] == ["Meander Saigon"]
    assert res["scope"] == "kpi"
    # The KOL ad's 100x ROAS would visibly move a 3-ad median if it leaked in.
    assert _saigon(res)["median"]["roas"] == 2.0        # 5.0, 2.0, 1.0

    all_res = _get_ad_benchmarks({**MAY, "scope": "all"}, db)
    assert {b["branch"] for b in all_res["branches"]} == {"Meander Saigon", "Bread"}
    assert _saigon(all_res)["ads"] == 4


def test_lifetime_benchmark_is_reported_separately(db, seeded):
    """The window ROAS and the verdict bar are different numbers, both shown."""
    sgn = _saigon(_get_ad_benchmarks(MAY, db))
    assert sgn["blended"]["roas"] == 1.5                # 1500 / 1000 this window
    assert sgn["lifetime_benchmark_roas"] == 1.5        # lifetime, KOL excluded
    assert sgn["median"]["roas"] != sgn["blended"]["roas"]


def test_min_spend_keeps_noise_out_of_the_bar(db, seeded):
    sgn = _saigon(_get_ad_benchmarks({**MAY, "min_spend": 150}, db))
    assert sgn["ads"] == 1                              # only "Big Ad" spent >150
    assert sgn["median"]["ctr_pct"] == 1.0
    assert sgn["median"]["hook_rate_pct"] is None       # no video ad survives


def test_group_median_pools_rates_but_never_currency(db, seeded):
    med = _get_ad_benchmarks({**MAY, "scope": "all"}, db)["meander_median"]
    assert med["ads"] == 5
    assert med["ctr_pct"] is not None
    # ROAS / spend / revenue are deliberately absent — 3 currencies, no pooling.
    assert "roas" not in med
    assert "spend" not in med


def test_coverage_reports_partial_ingest(db, seeded):
    cov = {c["branch"]: c for c in _get_ad_benchmarks(MAY, db)["coverage"]}
    sgn = cov["Meander Saigon"]
    assert sgn["days_requested"] == 31
    assert sgn["days_with_data"] == 4
    assert sgn["coverage_pct"] == 12.9
