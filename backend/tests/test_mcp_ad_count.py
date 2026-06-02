"""Tests for the MCP get_ad_count tool.

Counts distinct ads (ad/creative level) that spent in a window, per branch,
from ad_daily_metrics. The handler uses portable SQL (CAST AS FLOAT, LOWER LIKE)
so it runs on SQLite here as well as Postgres in prod. These tests lock in:
  * distinct-ad counting at the (branch, ad_id) grain (a multi-day ad = 1 ad),
  * exclusion of ads whose window-total spend is 0 / NULL,
  * the branch substring filter,
  * the min_spend window-total threshold,
  * date-range bounding.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.mcp.tools import _get_ad_count
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.base import Base

engine = create_engine(
    "sqlite:///test_mcp_ad_count.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded(db):
    """Two branches with ad-level daily metrics.

    Saigon: adA spends across 2 days (total 150), adB spends 0 both days,
            adC spends 30 on one day.   -> 2 ads with spend (A, C)
    Osaka:  adD spends 200, adE spends 5. -> 2 ads with spend (D, E)
    One out-of-range row for adA (April) must not be counted in May.
    """
    sgn = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_sgn",
        account_name="Meander Saigon", is_active=True,
    )
    osk = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_osk",
        account_name="Meander Osaka", is_active=True,
    )
    db.add_all([sgn, osk])
    db.flush()

    def metric(acc, ad_id, day, spend):
        db.add(AdDailyMetric(
            account_id=acc.id, ad_id=ad_id, ad_name=ad_id,
            date=day, spend=spend, impressions=100, clicks=10,
        ))

    # Saigon
    metric(sgn, "adA", date(2026, 5, 1), 100)
    metric(sgn, "adA", date(2026, 5, 2), 50)    # same ad, 2nd day -> still ONE ad
    metric(sgn, "adB", date(2026, 5, 1), 0)
    metric(sgn, "adB", date(2026, 5, 2), 0)     # zero spend both days -> excluded
    metric(sgn, "adC", date(2026, 5, 3), 30)
    metric(sgn, "adA", date(2026, 4, 15), 999)  # out of May window
    # Osaka
    metric(osk, "adD", date(2026, 5, 1), 200)
    metric(osk, "adE", date(2026, 5, 2), 5)
    db.commit()
    return {"sgn": sgn.id, "osk": osk.id}


MAY = {"date_from": "2026-05-01", "date_to": "2026-05-31"}


def _by_branch(res):
    return {r["branch"]: r for r in res["by_branch"]}


def test_counts_distinct_ads_with_spend(db, seeded):
    res = _get_ad_count(MAY, db)
    rows = _by_branch(res)
    assert rows["Meander Saigon"]["ads_with_spend"] == 2   # adA, adC (adB excluded)
    assert rows["Meander Saigon"]["spend"] == 180.0        # 100 + 50 + 30
    assert rows["Meander Osaka"]["ads_with_spend"] == 2    # adD, adE
    assert res["total_ads_with_spend"] == 4


def test_multiday_ad_counts_once(db, seeded):
    """adA has two daily rows in May but must count as a single ad."""
    res = _get_ad_count({**MAY, "branch": "Saigon"}, db)
    rows = _by_branch(res)
    assert set(rows) == {"Meander Saigon"}
    assert rows["Meander Saigon"]["ads_with_spend"] == 2


def test_min_spend_threshold(db, seeded):
    # min_spend 10: Saigon adA(150) & adC(30) pass; Osaka adD(200) passes, adE(5) drops.
    res = _get_ad_count({**MAY, "min_spend": 10}, db)
    rows = _by_branch(res)
    assert rows["Meander Saigon"]["ads_with_spend"] == 2
    assert rows["Meander Osaka"]["ads_with_spend"] == 1

    # min_spend 40: only adA(150) and adD(200) survive.
    res2 = _by_branch(_get_ad_count({**MAY, "min_spend": 40}, db))
    assert res2["Meander Saigon"]["ads_with_spend"] == 1
    assert res2["Meander Osaka"]["ads_with_spend"] == 1


def test_date_window_excludes_outside_rows(db, seeded):
    """adA's April 999-spend row must not leak into the May count or spend."""
    res = _by_branch(_get_ad_count(MAY, db))
    assert res["Meander Saigon"]["spend"] == 180.0  # 999 not included


def test_branch_filter_isolates(db, seeded):
    res = _get_ad_count({**MAY, "branch": "Osaka"}, db)
    rows = _by_branch(res)
    assert set(rows) == {"Meander Osaka"}
    assert res["total_ads_with_spend"] == 2
