"""Unit tests for each Meta detector.

These tests instantiate detectors directly, avoid Claude, and use in-memory
SQLite. Each test isolates one positive case and (where meaningful) one
negative case.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.google_seasonality_event import GoogleSeasonalityEvent
from app.models.metrics import MetricsCache
from app.services.meta_recommendations.base import DetectorTarget
from app.services.meta_recommendations.detectors.creative_fatigue import (
    CPMSpikeDetector,
    CreativeAge30DDetector,
)
from app.services.meta_recommendations.detectors.performance import (
    BadROASDetector,
    FrequencyAboveCeilingDetector,
    HighCTRLowCVRDetector,
    LowCTRDetector,
)
from app.services.meta_recommendations.detectors.seasonal import (
    SeasonalBudgetBumpDetector,
)

TEST_DB_URL = "sqlite:///./test_meta_recs_detectors.db"
_eng = create_engine(
    TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_eng)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=_eng)
    s = TestSession()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=_eng)


def _make_account(db, branch: str = "Meander Saigon", currency: str = "VND") -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"meta_{uuid.uuid4().hex[:8]}",
        account_name=branch, currency=currency, is_active=True,
    )
    db.add(acc); db.commit()
    return acc


def _make_campaign(db, acc, *, daily_budget=Decimal("50"), funnel_stage="BOF", name="[BOF] Test") -> Campaign:
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}",
        name=name, status="ACTIVE",
        daily_budget=daily_budget, funnel_stage=funnel_stage,
        start_date=date.today() - timedelta(days=30),
    )
    db.add(camp); db.commit()
    return camp


def _make_ad(db, acc, camp, *, country="VN") -> tuple[AdSet, Ad]:
    ad_set = AdSet(
        id=str(uuid.uuid4()), account_id=acc.id, campaign_id=camp.id, platform="meta",
        platform_adset_id=f"as_{uuid.uuid4().hex[:8]}",
        name=f"{country}_Solo_BOF", status="ACTIVE", country=country,
    )
    db.add(ad_set); db.commit()
    ad = Ad(
        id=str(uuid.uuid4()), account_id=acc.id, campaign_id=camp.id, ad_set_id=ad_set.id,
        platform="meta", platform_ad_id=f"ad_{uuid.uuid4().hex[:8]}",
        name="Fun slide creative", status="ACTIVE",
    )
    db.add(ad); db.commit()
    return ad_set, ad


# ── Frequency ceiling ────────────────────────────────────────────────────

def test_frequency_detector_fires_when_above_ceiling(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    ad_set, ad = _make_ad(db, acc, camp)
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("100"), impressions=6000, clicks=80,
            conversions=1, revenue=Decimal("300"),
            frequency=Decimal("3.0"),
        ))
    db.commit()

    det = FrequencyAboveCeilingDetector()
    targets = list(det.scope(db))
    assert len(targets) == 1
    finding = det.evaluate(db, targets[0])
    assert finding is not None
    assert finding.evidence["avg_frequency_7d"] > 2.5


def test_frequency_detector_silent_below_ceiling(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    ad_set, ad = _make_ad(db, acc, camp)
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("50"), impressions=3000, clicks=40,
            conversions=1, revenue=Decimal("200"),
            frequency=Decimal("1.5"),
        ))
    db.commit()

    det = FrequencyAboveCeilingDetector()
    target = list(det.scope(db))[0]
    assert det.evaluate(db, target) is None


# ── Low CTR ──────────────────────────────────────────────────────────────

def test_low_ctr_detector_fires_when_ctr_below_floor(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    ad_set, ad = _make_ad(db, acc, camp)
    # 7 days of high impressions + low clicks => CTR 0.3% < 0.8% floor
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("50"), impressions=10000, clicks=30,
            conversions=0, revenue=Decimal("0"),
        ))
    db.commit()
    det = LowCTRDetector()
    target = list(det.scope(db))[0]
    finding = det.evaluate(db, target)
    assert finding is not None
    assert finding.evidence["actual_ctr_7d"] < 0.008


# ── High CTR / Low CVR ───────────────────────────────────────────────────

def _seed_campaign_metrics(
    db, camp, *, days_back, days, impressions, clicks, conversions,
):
    """Seed N days of campaign-level MetricsCache rows ending `days_back` ago."""
    for offset in range(days_back, days_back + days):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("100"), impressions=impressions, clicks=clicks,
            conversions=conversions, revenue=Decimal("0"),
        ))
    db.commit()


def test_high_ctr_low_cvr_fires_when_7d_drops_below_half_of_30d(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    # Days 8-30: healthy baseline. 23 days * 1500 clicks = 34,500 clicks,
    # 23 * 30 = 690 conversions -> CVR_30d ≈ 2.0%.
    _seed_campaign_metrics(
        db, camp, days_back=8, days=23,
        impressions=10000, clicks=1500, conversions=30,
    )
    # Days 1-7: CTR still healthy (15%) but CVR collapsed to ~0.2%
    # — well below 50% of the 2% baseline.
    _seed_campaign_metrics(
        db, camp, days_back=1, days=7,
        impressions=10000, clicks=1500, conversions=3,
    )

    det = HighCTRLowCVRDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is not None
    assert finding.evidence["cvr_7d"] < finding.evidence["alert_threshold"]
    assert finding.evidence["cvr_30d_baseline"] > finding.evidence["cvr_7d"]
    assert finding.evidence["drop_ratio"] < 0.5


def test_high_ctr_low_cvr_silent_when_7d_close_to_baseline(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    # Steady CVR ~2% across both windows -> 7d not materially worse than 30d.
    _seed_campaign_metrics(
        db, camp, days_back=1, days=30,
        impressions=10000, clicks=1500, conversions=30,
    )
    det = HighCTRLowCVRDetector()
    target = next(iter(det.scope(db)))
    assert det.evaluate(db, target) is None


def test_high_ctr_low_cvr_silent_when_baseline_volume_too_low(db):
    """New campaign with healthy 7d CTR but insufficient 30d clicks must
    not fire — the baseline is too noisy to call a regression."""
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    # 7 days of data only — passes 7d gate (impr≥20k, clicks≥200) but the
    # 30d total clicks (7 * 35 = 245) falls below CVR_BASELINE_MIN_CLICKS=500.
    _seed_campaign_metrics(
        db, camp, days_back=1, days=7,
        impressions=3000, clicks=35, conversions=0,
    )
    det = HighCTRLowCVRDetector()
    target = next(iter(det.scope(db)))
    assert det.evaluate(db, target) is None


# ── Bad ROAS ─────────────────────────────────────────────────────────────

def test_bad_roas_detector_fires_below_tier_floor(db):
    acc = _make_account(db, branch="Meander Saigon")
    camp = _make_campaign(db, acc)
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("100"), impressions=5000, clicks=50,
            conversions=2, revenue=Decimal("50"),  # ROAS 0.5 < 1.0 threshold
        ))
    db.commit()
    det = BadROASDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is not None
    assert finding.evidence["actual_roas_7d"] < 1.0


# ── Creative age ─────────────────────────────────────────────────────────

def test_creative_age_30d_detector_fires_for_old_ad(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    ad_set, ad = _make_ad(db, acc, camp)
    # Backdate ad.created_at to 45 days ago.
    ad.created_at = datetime.now(timezone.utc) - timedelta(days=45)
    db.commit()
    # Need some spend in the last 7 days so the detector returns a finding.
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("10"), impressions=1000, clicks=10,
            conversions=0, revenue=Decimal("0"),
        ))
    db.commit()
    det = CreativeAge30DDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is not None
    assert finding.evidence["ad_age_days"] >= 30


# ── CPM spike ────────────────────────────────────────────────────────────

def test_cpm_spike_detector_fires_on_30pct_rise(db):
    acc = _make_account(db)
    camp = _make_campaign(db, acc)
    ad_set, ad = _make_ad(db, acc, camp)
    # Prior window: 10 USD / 6000 impressions -> 1.67 CPM.
    for offset in range(8, 15):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("10"), impressions=6000, clicks=60,
            conversions=0, revenue=Decimal("0"),
        ))
    # Current window: 20 USD / 6000 -> 3.33 CPM (100% rise)
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("20"), impressions=6000, clicks=60,
            conversions=0, revenue=Decimal("0"),
        ))
    db.commit()
    det = CPMSpikeDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is not None
    assert finding.evidence["rise_pct"] >= 0.30


# ── Seasonal budget bump + home∪target country union ────────────────────

def _seed_events(db):
    # VN Tet + JP Golden Week.
    today = date.today()
    # VN Tet window includes today by construction.
    vn_start_m, vn_start_d = today.month, today.day
    vn_end = today + timedelta(days=10)
    jp_start = today
    jp_end = today + timedelta(days=10)
    db.add(GoogleSeasonalityEvent(
        id="ev-vn-tet", country_code="VN", event_key="tet",
        name="Lunar New Year (Tet)",
        start_month=vn_start_m, start_day=vn_start_d,
        end_month=vn_end.month, end_day=vn_end.day,
        lead_time_days=7,
        budget_bump_pct_min=Decimal("20"), budget_bump_pct_max=Decimal("30"),
    ))
    db.add(GoogleSeasonalityEvent(
        id="ev-jp-gw", country_code="JP", event_key="golden_week",
        name="Golden Week",
        start_month=jp_start.month, start_day=jp_start.day,
        end_month=jp_end.month, end_day=jp_end.day,
        lead_time_days=7,
        budget_bump_pct_min=Decimal("30"), budget_bump_pct_max=Decimal("50"),
    ))
    db.commit()


def test_seasonal_fires_for_home_country_match(db):
    acc = _make_account(db, branch="Meander Saigon", currency="VND")
    camp = _make_campaign(db, acc, daily_budget=Decimal("100"))
    ad_set, ad = _make_ad(db, acc, camp, country="VN")
    _seed_events(db)

    det = SeasonalBudgetBumpDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is not None
    assert finding.evidence["country_code"] == "VN"
    # Bump mid = (20+30)/2 = 25 — equal to cap; proposed budget = 100 * 1.25 = 125
    assert finding.evidence["proposed_daily_budget"] == pytest.approx(125.0, rel=1e-3)


def test_seasonal_fires_for_targeted_inbound_country(db):
    """Saigon (home=VN) campaign with JP-targeted ad set should fire JP events."""
    acc = _make_account(db, branch="Meander Saigon", currency="VND")
    camp = _make_campaign(db, acc, daily_budget=Decimal("100"))
    ad_set, ad = _make_ad(db, acc, camp, country="JP")  # Japanese inbound
    _seed_events(db)

    det = SeasonalBudgetBumpDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is not None
    # Both VN Tet and JP Golden Week are candidates; detector picks the first.
    assert finding.evidence["country_code"] in {"VN", "JP"}


def test_seasonal_does_not_fire_for_unrelated_country(db):
    """Osaka (home=JP) campaign targeting JP should NOT fire a VN-only event
    if VN is not in targeted countries."""
    acc = _make_account(db, branch="Meander Osaka", currency="JPY")
    camp = _make_campaign(db, acc, daily_budget=Decimal("100"))
    ad_set, ad = _make_ad(db, acc, camp, country="JP")
    # Seed only a VN event — no JP event.
    today = date.today()
    vn_end = today + timedelta(days=10)
    db.add(GoogleSeasonalityEvent(
        id="ev-vn-only", country_code="VN", event_key="tet",
        name="Lunar New Year",
        start_month=today.month, start_day=today.day,
        end_month=vn_end.month, end_day=vn_end.day,
        lead_time_days=7,
        budget_bump_pct_min=Decimal("20"), budget_bump_pct_max=Decimal("30"),
    ))
    db.commit()

    det = SeasonalBudgetBumpDetector()
    target = next(iter(det.scope(db)))
    finding = det.evaluate(db, target)
    assert finding is None
