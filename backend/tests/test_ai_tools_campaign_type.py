"""get_ad_performance's campaign_type filter (Sale / Lead / Engagement), plus
two related bugs surfaced while wiring it up (BUG-010):

- Branches with 2+ AdAccount rows (one per platform) only ever queried the
  first fuzzy-matched account, silently dropping every other platform.
- metrics_cache holds campaign/ad_set/ad-level rows for the same date; the
  query summed all of them instead of just the campaign-level rows.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services.ai_tools import _tool_get_ad_performance
from tests.db import TestSession


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def account(db):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Osaka", currency="JPY", is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _campaign_with_metrics(db, account, name, objective, funnel_stage, spend, revenue, conversions,
                            ad_set_id=None, ad_id=None, platform="meta"):
    c = Campaign(
        id=str(uuid.uuid4()), account_id=account.id, platform=platform,
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}", name=name,
        status="ACTIVE", objective=objective, funnel_stage=funnel_stage,
    )
    db.add(c)
    db.flush()
    db.add(MetricsCache(
        id=str(uuid.uuid4()), campaign_id=c.id, platform=platform,
        date=date(2026, 8, 1), spend=spend, revenue=revenue, conversions=conversions,
        ad_set_id=ad_set_id, ad_id=ad_id,
    ))
    db.flush()
    return c


@pytest.fixture
def seeded(db, account):
    _campaign_with_metrics(
        db, account, "Mason_OSK_[MOF] Sale Remarketing_202608 JP", "OUTCOME_SALES",
        "MOF", spend=1000, revenue=5000, conversions=10,
    )
    _campaign_with_metrics(
        db, account, "Mason_OSK_[MOF] Lead Gen_202608 JP", "OUTCOME_LEADS",
        "MOF", spend=1000, revenue=1000, conversions=20,
    )
    return account


def test_campaign_type_filter_splits_sale_and_lead(db, seeded):
    sale = _tool_get_ad_performance(db, {
        "branch": "Meander Osaka", "funnel": "MOF", "campaign_type": "sale",
        "date_from": "2026-08-01", "date_to": "2026-08-01",
    })
    lead = _tool_get_ad_performance(db, {
        "branch": "Meander Osaka", "funnel": "MOF", "campaign_type": "lead",
        "date_from": "2026-08-01", "date_to": "2026-08-01",
    })

    assert sale["spend"] == 1000.0
    assert sale["revenue"] == 5000.0
    assert sale["roas"] == 5.0
    assert sale["conversions"] == 10

    assert lead["spend"] == 1000.0
    assert lead["revenue"] == 1000.0
    assert lead["roas"] == 1.0
    assert lead["conversions"] == 20

    assert sale["filters"]["campaign_type"] == "sale"
    assert lead["filters"]["campaign_type"] == "lead"


def test_no_campaign_type_returns_everything_combined(db, seeded):
    combined = _tool_get_ad_performance(db, {
        "branch": "Meander Osaka", "funnel": "MOF",
        "date_from": "2026-08-01", "date_to": "2026-08-01",
    })
    assert combined["spend"] == 2000.0
    assert combined["revenue"] == 6000.0
    assert combined["conversions"] == 30
    assert combined["filters"]["campaign_type"] is None


def test_ad_and_adset_level_rows_are_not_double_counted(db, account):
    """metrics_cache carries campaign/ad_set/ad-level rows for the same date.
    Only the campaign-level row (ad_set_id and ad_id both NULL) may be summed —
    else spend/revenue inflate 2-3x."""
    campaign = _campaign_with_metrics(
        db, account, "Mason_OSK_[MOF] Sale_202608 JP", "OUTCOME_SALES", "MOF",
        spend=1000, revenue=5000, conversions=10,
    )
    # Same campaign, finer-grained rows for the same date — must be ignored.
    db.add(MetricsCache(
        id=str(uuid.uuid4()), campaign_id=campaign.id, platform="meta",
        date=date(2026, 8, 1), spend=1000, revenue=5000, conversions=10,
        ad_set_id=str(uuid.uuid4()),
    ))
    db.add(MetricsCache(
        id=str(uuid.uuid4()), campaign_id=campaign.id, platform="meta",
        date=date(2026, 8, 1), spend=1000, revenue=5000, conversions=10,
        ad_set_id=str(uuid.uuid4()), ad_id=str(uuid.uuid4()),
    ))
    db.flush()

    result = _tool_get_ad_performance(db, {
        "branch": "Meander Osaka", "date_from": "2026-08-01", "date_to": "2026-08-01",
    })
    assert result["spend"] == 1000.0
    assert result["revenue"] == 5000.0
    assert result["conversions"] == 10


def test_branch_with_meta_and_google_accounts_combines_both(db):
    """A branch commonly has one AdAccount row per platform. Resolving only
    the first fuzzy match silently dropped the other platform's data —
    reproduces the real 'Meander Taipei' (Meta) / 'MEANDER Taipei' (Google)
    casing split found in prod."""
    meta_acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Taipei", currency="TWD", is_active=True,
    )
    google_acc = AdAccount(
        id=str(uuid.uuid4()), platform="google", account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="MEANDER Taipei", currency="TWD", is_active=True,
    )
    db.add_all([meta_acc, google_acc])
    db.flush()
    _campaign_with_metrics(
        db, meta_acc, "Mason_TPE_[MOF] Lead Gen_202608 TW", "OUTCOME_LEADS", "MOF",
        spend=500, revenue=1000, conversions=4, platform="meta",
    )
    _campaign_with_metrics(
        db, google_acc, "Mason_TPE_[MOF] Sale_202608 TW", "OUTCOME_SALES", "MOF",
        spend=300, revenue=2000, conversions=2, platform="google",
    )

    result = _tool_get_ad_performance(db, {
        "branch": "Meander Taipei", "funnel": "MOF",
        "date_from": "2026-08-01", "date_to": "2026-08-01",
    })
    assert result["spend"] == 800.0
    assert result["revenue"] == 3000.0
    assert result["conversions"] == 6
