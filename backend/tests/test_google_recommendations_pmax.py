"""Tests for the 4 Phase-7 PMax full-coverage detectors."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.google_asset_group import GoogleAssetGroup
from app.models.metrics import MetricsCache
from app.services.google_recommendations.registry import get_detector
from tests.db import TestSession, engine


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _account(db, account_name: str = "Meander Saigon"):
    a = AdAccount(
        id=str(uuid.uuid4()),
        platform="google",
        account_id=f"goog_{uuid.uuid4().hex[:8]}",
        account_name=account_name,
        currency="USD",
        is_active=True,
    )
    db.add(a); db.commit()
    return a


def _pmax_campaign(db, account, *, start_days_ago=40, raw_data=None, name="Test PMax"):
    c = Campaign(
        id=str(uuid.uuid4()),
        account_id=account.id,
        platform="google",
        platform_campaign_id=f"gc_{uuid.uuid4().hex[:8]}",
        name=name,
        status="ACTIVE",
        objective="PERFORMANCE_MAX",
        daily_budget=Decimal("100.00"),
        start_date=date.today() - timedelta(days=start_days_ago),
        raw_data=raw_data or {},
    )
    db.add(c); db.commit()
    return c


def _asset_group(db, campaign, account, *, raw_data=None):
    ag = GoogleAssetGroup(
        id=str(uuid.uuid4()),
        campaign_id=campaign.id,
        account_id=account.id,
        platform_asset_group_id=f"ag_{uuid.uuid4().hex[:6]}",
        name="Main AG",
        status="ACTIVE",
        raw_data=raw_data or {},
    )
    db.add(ag); db.commit()
    return ag


def _metrics(db, campaign, d: date, *, spend: float, conversions: float = 0, revenue: float = 0):
    m = MetricsCache(
        id=str(uuid.uuid4()),
        campaign_id=campaign.id,
        platform="google",
        date=d,
        spend=Decimal(str(spend)),
        impressions=int(spend * 10),
        clicks=int(spend),
        conversions=int(conversions),
        revenue=Decimal(str(revenue)),
    )
    db.add(m); db.commit()
    return m


# ── PMAX_MISSING_AUDIENCE_SIGNAL ─────────────────────────────
def test_missing_audience_signal_fires_when_empty(db):
    acc = _account(db)
    camp = _pmax_campaign(db, acc)
    _asset_group(db, camp, acc, raw_data={"audience_signals": [], "signal_count": 0})
    det = get_detector("PMAX_MISSING_AUDIENCE_SIGNAL")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["signal_count"] == 0


def test_missing_audience_signal_skips_when_signal_attached(db):
    acc = _account(db)
    camp = _pmax_campaign(db, acc)
    _asset_group(db, camp, acc, raw_data={
        "audience_signals": [{"signal_type": "AUDIENCE", "resource_name": "x"}],
        "signal_count": 1,
    })
    det = get_detector("PMAX_MISSING_AUDIENCE_SIGNAL")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_missing_audience_signal_skips_when_unknown(db):
    """When sync engine hasn't populated signals, detector must not false-fire."""
    acc = _account(db)
    camp = _pmax_campaign(db, acc)
    _asset_group(db, camp, acc, raw_data={})
    det = get_detector("PMAX_MISSING_AUDIENCE_SIGNAL")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


# ── PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH ─────────────────────
def test_lifecycle_fires_when_old_on_wrong_strategy(db):
    acc = _account(db)
    camp = _pmax_campaign(
        db, acc, start_days_ago=100,  # month_4_plus
        raw_data={"bidding_strategy_type": "MAXIMIZE_CONVERSIONS"},
    )
    for i in range(30):
        _metrics(db, camp, date.today() - timedelta(days=i), spend=50, conversions=1, revenue=200)
    det = get_detector("PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    ev = hits[0].evidence
    assert ev["lifecycle_bucket"] == "month_4_plus"
    assert ev["recommended_strategy"] == "MAXIMIZE_CONVERSION_VALUE_WITH_TROAS"
    assert hits[0].action_kwargs["new_strategy"] == "MAXIMIZE_CONVERSION_VALUE_WITH_TROAS"
    assert hits[0].action_kwargs["target_roas"] is not None


def test_lifecycle_skips_week_1_2_on_max_conv(db):
    acc = _account(db)
    camp = _pmax_campaign(
        db, acc, start_days_ago=7,
        raw_data={"bidding_strategy_type": "MAXIMIZE_CONVERSIONS"},
    )
    det = get_detector("PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_lifecycle_skips_when_sync_missing(db):
    """No bidding_strategy_type in raw_data → no false positive."""
    acc = _account(db)
    _pmax_campaign(db, acc, start_days_ago=100, raw_data={})
    det = get_detector("PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_lifecycle_build_action_shape(db):
    acc = _account(db)
    camp = _pmax_campaign(
        db, acc, start_days_ago=30,
        raw_data={"bidding_strategy_type": "MAXIMIZE_CONVERSIONS"},
    )
    for i in range(30):
        _metrics(db, camp, date.today() - timedelta(days=i), spend=50, conversions=1, revenue=200)
    det = get_detector("PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH")
    targets = list(det.scope(db))
    finding = det.evaluate(db, targets[0])
    action = det.build_action(targets[0], finding)
    assert action["function"] == "switch_bid_strategy"
    assert action["kwargs"]["new_strategy"] == "MAXIMIZE_CONVERSIONS_WITH_TCPA"
    assert action["kwargs"]["target_cpa_micros"] > 0


# ── PMAX_COUNT_VS_SCALE ──────────────────────────────────────
def test_count_vs_scale_fires_too_many(db):
    acc = _account(db, "Meander Saigon")  # 42 rooms → expect 2-3 PMax
    for i in range(5):
        _pmax_campaign(db, acc, name=f"PMax {i}")
    det = get_detector("PMAX_COUNT_VS_SCALE")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    ev = hits[0].evidence
    assert ev["direction"] == "too_many"
    assert ev["active_pmax_count"] == 5


def test_count_vs_scale_fires_too_few_for_small_hotel(db):
    # Oani is 18 rooms → expected (1, 1). Zero PMax → too_few.
    acc = _account(db, "Oani Taipei")
    det = get_detector("PMAX_COUNT_VS_SCALE")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["direction"] == "too_few"
    assert hits[0].evidence["active_pmax_count"] == 0


def test_count_vs_scale_skips_when_in_band(db):
    acc = _account(db, "Meander Saigon")  # expect 2-3
    _pmax_campaign(db, acc, name="PMax A")
    _pmax_campaign(db, acc, name="PMax B")
    det = get_detector("PMAX_COUNT_VS_SCALE")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_count_vs_scale_skips_unknown_branch(db):
    acc = _account(db, "Random Hotel XYZ")
    det = get_detector("PMAX_COUNT_VS_SCALE")
    targets = list(det.scope(db))
    assert targets == []


# ── PMAX_MISSING_BRAND_EXCLUSION ─────────────────────────────
def test_brand_exclusion_fires_when_false(db):
    acc = _account(db)
    _pmax_campaign(db, acc, raw_data={"has_brand_exclusion": False})
    det = get_detector("PMAX_MISSING_BRAND_EXCLUSION")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["has_brand_exclusion"] is False


def test_brand_exclusion_skips_when_true(db):
    acc = _account(db)
    _pmax_campaign(db, acc, raw_data={"has_brand_exclusion": True})
    det = get_detector("PMAX_MISSING_BRAND_EXCLUSION")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_brand_exclusion_skips_when_unknown(db):
    """Missing key → unknown → must not fire."""
    acc = _account(db)
    _pmax_campaign(db, acc, raw_data={})
    det = get_detector("PMAX_MISSING_BRAND_EXCLUSION")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


# ── Registry sanity ──────────────────────────────────────────
def test_all_four_phase7_detectors_registered():
    from app.services.google_recommendations.registry import all_detectors
    rec_types = {d.rec_type for d in all_detectors()}
    assert {
        "PMAX_MISSING_AUDIENCE_SIGNAL",
        "PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH",
        "PMAX_COUNT_VS_SCALE",
        "PMAX_MISSING_BRAND_EXCLUSION",
    }.issubset(rec_types)
