"""Tests for the MCP get_winning_ads tool.

Lists ads at the (branch, ad_name) grain from ad_daily_metrics, each carrying
its FROZEN winning_ad_months verdict plus best-effort Creative Library context.
The handler uses portable SQL (CAST AS FLOAT, LOWER LIKE) so it runs on SQLite
here as well as Postgres in prod. These tests lock in:
  * ad_name grain — several platform ad_ids collapse into one row,
  * frozen verdict pass-through, and TEST for an ad never decided,
  * scope: 'kpi' drops KOL ads + Bread, 'all' keeps everything,
  * combo enrichment (angle / keypoints / TA / country) when the ad is mapped,
  * the coverage block, which is what exposes a half-ingested date window,
  * branch / verdict / min_spend filters and sorting.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.mcp.tools import _get_winning_ads
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_daily_metric import AdDailyMetric
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint
from app.models.winning_ad_month import WinningAdMonth
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
    """Three branches of Meta ad-level metrics.

    Saigon: "Hero Ad" runs on two ad_ids over two days (one creative),
            frozen WIN in May; "Quiet Ad" spends but was never decided (TEST);
            "KOL Collab" is out of KPI scope.
    Osaka:  "Osaka Ad" only — frozen LOSE.
    Bread:  "Bread Ad" — out of KPI scope entirely.
    """
    sgn = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_sgn",
        account_name="Meander Saigon", is_active=True,
    )
    osk = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_osk",
        account_name="Meander Osaka", is_active=True,
    )
    bread = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_bread",
        account_name="Bread", is_active=True,
    )
    db.add_all([sgn, osk, bread])
    db.flush()

    def metric(acc, ad_id, ad_name, day, spend, revenue=0, clicks=10, conversions=0):
        db.add(AdDailyMetric(
            account_id=acc.id, ad_id=ad_id, ad_name=ad_name, date=day,
            spend=spend, revenue=revenue, impressions=1000, clicks=clicks,
            conversions=conversions,
        ))

    # Saigon — "Hero Ad" is one creative running on two ad_ids across two days.
    metric(sgn, "ad1", "Hero Ad", date(2026, 5, 1), 100, revenue=600, conversions=2)
    metric(sgn, "ad2", "Hero Ad", date(2026, 5, 2), 100, revenue=600, conversions=2)
    metric(sgn, "ad3", "Quiet Ad", date(2026, 5, 1), 50, revenue=50, conversions=1)
    metric(sgn, "ad4", "KOL Collab May", date(2026, 5, 1), 80, revenue=800, conversions=3)
    metric(sgn, "ad1", "Hero Ad", date(2026, 4, 10), 999, revenue=9999)  # outside May
    # Osaka
    metric(osk, "ad5", "Osaka Ad", date(2026, 5, 3), 200, revenue=100, conversions=1)
    # Bread
    metric(bread, "ad6", "Bread Ad", date(2026, 5, 3), 40, revenue=400, conversions=4)

    # Frozen verdicts (scope 'kpi'). "Quiet Ad" deliberately has none.
    db.add_all([
        WinningAdMonth(
            account_id=sgn.id, month=date(2026, 5, 1), ad_name="Hero Ad", scope="kpi",
            verdict="WIN", verdict_source="auto", roas=6.0, benchmark_roas=3.0,
            spend=200, revenue=1200, conversions=4,
        ),
        WinningAdMonth(
            account_id=osk.id, month=date(2026, 5, 1), ad_name="Osaka Ad", scope="kpi",
            verdict="LOSE", verdict_source="auto", roas=0.5, benchmark_roas=3.0,
        ),
    ])

    # Creative Library mapping for "Hero Ad" only.
    kp = BranchKeypoint(
        id=str(uuid.uuid4()), branch_id=sgn.id, category="location",
        title="5 min to Ben Thanh", is_active=True,
    )
    angle = AdAngle(
        id=str(uuid.uuid4()), branch_id=sgn.id, angle_id="ANG-001",
        angle_type="Use an authority", angle_text="", status="WIN",
    )
    copy = AdCopy(
        id=str(uuid.uuid4()), branch_id=sgn.id, copy_id="CPY-001",
        target_audience="Couple", headline="h", body_text="b", language="en",
    )
    material = AdMaterial(
        id=str(uuid.uuid4()), branch_id=sgn.id, material_id="MAT-001",
        material_type="image", file_url="https://example.test/a.jpg",
    )
    db.add_all([kp, angle, copy, material])
    db.flush()
    db.add(AdCombo(
        id=str(uuid.uuid4()), branch_id=sgn.id, combo_id="CMB-001", ad_name="Hero Ad",
        target_audience="Couple", country="PH", keypoint_ids=[str(kp.id)],
        angle_id="ANG-001", copy_id="CPY-001", material_id="MAT-001", verdict="WIN",
    ))
    db.commit()
    return {"sgn": sgn.id, "osk": osk.id, "bread": bread.id}


def _by_name(res):
    return {a["ad_name"]: a for a in res["ads"]}


def test_lists_ads_at_ad_name_grain(db, seeded):
    """Two ad_ids sharing an ad_name are ONE creative, summed across its days."""
    ads = _by_name(_get_winning_ads({**MAY, "branch": "Saigon"}, db))
    hero = ads["Hero Ad"]
    assert hero["ad_count"] == 2          # ad1 + ad2
    assert hero["days_with_spend"] == 2
    assert hero["spend"] == 200.0         # April's 999 stays out
    assert hero["revenue"] == 1200.0
    assert hero["roas"] == 6.0
    assert hero["conversions"] == 4
    assert hero["cost_per_conversion"] == 50.0
    assert hero["ctr_pct"] == 1.0         # 20 clicks / 2000 impressions


def test_frozen_verdict_is_passed_through(db, seeded):
    ads = _by_name(_get_winning_ads({**MAY, "branch": "Saigon"}, db))
    hero = ads["Hero Ad"]
    assert hero["verdict"] == "WIN"
    assert hero["verdict_month"] == "2026-05"
    assert hero["verdict_source"] == "auto"
    assert hero["verdict_roas"] == 6.0
    assert hero["verdict_benchmark_roas"] == 3.0


def test_never_decided_ad_reads_as_test(db, seeded):
    """No winning_ad_months row = TEST, with no verdict metadata invented."""
    quiet = _by_name(_get_winning_ads({**MAY, "branch": "Saigon"}, db))["Quiet Ad"]
    assert quiet["verdict"] == "TEST"
    assert quiet["verdict_month"] is None
    assert quiet["verdict_roas"] is None
    # ...but it can still be read against the live bar.
    assert quiet["benchmark_roas_now"] is not None
    assert quiet["above_benchmark_now"] is False


def test_kpi_scope_drops_kol_and_bread(db, seeded):
    res = _get_winning_ads(MAY, db)
    names = set(_by_name(res))
    assert "KOL Collab May" not in names
    assert "Bread Ad" not in names
    assert {"Hero Ad", "Quiet Ad", "Osaka Ad"} <= names
    assert res["scope"] == "kpi"


def test_all_scope_keeps_kol_and_bread(db, seeded):
    names = set(_by_name(_get_winning_ads({**MAY, "scope": "all"}, db)))
    assert "KOL Collab May" in names
    assert "Bread Ad" in names


def test_unknown_scope_falls_back_to_kpi(db, seeded):
    res = _get_winning_ads({**MAY, "scope": "everything"}, db)
    assert res["scope"] == "kpi"
    assert "Bread Ad" not in _by_name(res)


def test_benchmark_is_lifetime_and_excludes_kol_spend(db, seeded):
    """The bar is the account's LIFETIME blended non-KOL ROAS, not the window's.

    April's row counts even though the query asks for May, and the KOL ad's
    800/80 never does: (9999+600+600+50) / (999+100+100+50) = 9.01.
    """
    ads = _by_name(_get_winning_ads({**MAY, "branch": "Saigon"}, db))
    assert ads["Hero Ad"]["benchmark_roas_now"] == 9.01
    assert ads["Hero Ad"]["above_benchmark_now"] is False   # window ROAS 6.0 < 9.01
    assert ads["Quiet Ad"]["benchmark_roas_now"] == 9.01


def test_combo_enrichment_is_best_effort(db, seeded):
    ads = _by_name(_get_winning_ads({**MAY, "branch": "Saigon"}, db))
    hero, quiet = ads["Hero Ad"], ads["Quiet Ad"]
    assert hero["combo_id"] == "CMB-001"
    assert hero["angle_id"] == "ANG-001"
    assert hero["angle_type"] == "Use an authority"
    assert hero["target_audience"] == "Couple"
    assert hero["country"] == "PH"
    assert hero["keypoints"] == ["5 min to Ben Thanh"]
    # An unmapped ad still lists — it just has no Creative Library context.
    assert quiet["combo_id"] is None
    assert quiet["angle_type"] is None
    assert quiet["keypoints"] == []


def test_verdict_filter(db, seeded):
    assert set(_by_name(_get_winning_ads({**MAY, "verdict": "WIN"}, db))) == {"Hero Ad"}
    assert set(_by_name(_get_winning_ads({**MAY, "verdict": "LOSE"}, db))) == {"Osaka Ad"}
    assert set(_by_name(_get_winning_ads({**MAY, "verdict": "TEST"}, db))) == {"Quiet Ad"}


def test_min_spend_and_sorting_and_limit(db, seeded):
    res = _get_winning_ads({**MAY, "min_spend": 60}, db)
    assert set(_by_name(res)) == {"Hero Ad", "Osaka Ad"}  # Quiet Ad (50) drops

    by_spend = _get_winning_ads({**MAY, "sort_by": "spend"}, db)["ads"]
    assert [a["spend"] for a in by_spend] == [200.0, 200.0, 50.0]
    assert by_spend[-1]["ad_name"] == "Quiet Ad"

    top = _get_winning_ads({**MAY, "sort_by": "roas", "limit": 1}, db)
    assert top["returned"] == 1
    assert top["total_matching"] == 3          # limit truncates, it doesn't filter
    assert top["ads"][0]["ad_name"] == "Hero Ad"


def test_coverage_reports_partial_ingest(db, seeded):
    """The whole point: 3 ingested days out of a 31-day window is 9.7%, not 100%."""
    cov = {c["branch"]: c for c in _get_winning_ads(MAY, db)["coverage"]}
    sgn = cov["Meander Saigon"]
    assert sgn["days_requested"] == 31
    assert sgn["days_with_data"] == 2
    assert sgn["coverage_pct"] == 6.5
    assert sgn["first_day"] == "2026-05-01"
    assert sgn["last_day"] == "2026-05-02"
    assert cov["Meander Osaka"]["days_with_data"] == 1


def test_branch_filter_isolates(db, seeded):
    res = _get_winning_ads({**MAY, "branch": "Osaka"}, db)
    assert set(_by_name(res)) == {"Osaka Ad"}
    assert [c["branch"] for c in res["coverage"]] == ["Meander Osaka"]
