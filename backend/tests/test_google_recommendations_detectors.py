"""Smoke tests for the first 5 Google recommendation detectors."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.account import AdAccount
from app.models.ad_set import AdSet
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.google_asset import GoogleAsset
from app.models.google_asset_group import GoogleAssetGroup
from app.models.google_seasonality_event import GoogleSeasonalityEvent
from app.models.metrics import MetricsCache
from app.services.google_recommendations.registry import get_detector, all_detectors

TEST_DB_URL = "sqlite:///./test_recs.db"
engine = create_engine(
    TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _account(db, account_name: str = "Meander Saigon"):
    """Default to Saigon (VN) so country-scoped detectors resolve a home country."""
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


def _adset(db, campaign, account, country: str):
    """Create an ad_set with a parsed country code — feeds the targeted-country scope helper."""
    s = AdSet(
        id=str(uuid.uuid4()),
        campaign_id=campaign.id,
        account_id=account.id,
        platform="google",
        platform_adset_id=f"as_{uuid.uuid4().hex[:8]}",
        name=f"{country}_TestAdGroup",
        status="ACTIVE",
        country=country,
    )
    db.add(s); db.commit()
    return s


def _campaign(db, account, **kwargs):
    defaults = dict(
        id=str(uuid.uuid4()),
        platform="google",
        platform_campaign_id=f"gc_{uuid.uuid4().hex[:8]}",
        name="Test PMax",
        status="ACTIVE",
        objective="PERFORMANCE_MAX",
        daily_budget=Decimal("100.00"),
        start_date=date.today() - timedelta(days=40),
    )
    defaults.update(kwargs)
    c = Campaign(account_id=account.id, **defaults)
    db.add(c); db.commit()
    return c


def _metrics(db, campaign, d: date, spend: float, conversions: float = 0, revenue: float = 0):
    m = MetricsCache(
        id=str(uuid.uuid4()),
        campaign_id=campaign.id,
        platform="google",
        date=d,
        spend=Decimal(str(spend)),
        impressions=int(spend * 10),
        clicks=int(spend * 1),
        conversions=int(conversions),
        revenue=Decimal(str(revenue)),
    )
    db.add(m); db.commit()
    return m


# ── ZERO_CONVERSIONS_2D ──────────────────────────────────────
def test_zero_conversions_detector_fires_on_2d_zero(db):
    acc = _account(db)
    camp = _campaign(db, acc)
    yesterday = date.today() - timedelta(days=1)
    day_before = date.today() - timedelta(days=2)
    _metrics(db, camp, yesterday, spend=50, conversions=0)
    _metrics(db, camp, day_before, spend=50, conversions=0)

    det = get_detector("ZERO_CONVERSIONS_2D")
    targets = list(det.scope(db))
    findings = [det.evaluate(db, t) for t in targets]
    hits = [f for f in findings if f is not None]
    assert len(hits) == 1
    assert hits[0].evidence["yesterday_spend"] == 50


def test_zero_conversions_detector_skips_when_any_conversion(db):
    acc = _account(db)
    camp = _campaign(db, acc)
    yesterday = date.today() - timedelta(days=1)
    day_before = date.today() - timedelta(days=2)
    _metrics(db, camp, yesterday, spend=50, conversions=1)
    _metrics(db, camp, day_before, spend=50, conversions=0)

    det = get_detector("ZERO_CONVERSIONS_2D")
    hits = [det.evaluate(db, t) for t in det.scope(db)]
    assert all(h is None for h in hits)


# ── DG_MISSING_VIDEO ────────────────────────────────────────
def test_dg_missing_video_fires_when_no_video(db):
    acc = _account(db)
    camp = _campaign(db, acc)  # PERFORMANCE_MAX
    ag = GoogleAssetGroup(
        id=str(uuid.uuid4()),
        campaign_id=camp.id,
        account_id=acc.id,
        platform_asset_group_id=f"ag_{uuid.uuid4().hex[:6]}",
        name="Main AG",
        status="ACTIVE",
    )
    db.add(ag); db.commit()
    # Only an image asset — no video.
    db.add(GoogleAsset(
        id=str(uuid.uuid4()),
        asset_group_id=ag.id,
        account_id=acc.id,
        platform_asset_id=f"a_{uuid.uuid4().hex[:6]}",
        asset_type="IMAGE",
    ))
    db.commit()

    det = get_detector("DG_MISSING_VIDEO")
    hits = [det.evaluate(db, t) for t in det.scope(db)]
    hits = [h for h in hits if h]
    assert len(hits) == 1
    assert hits[0].evidence["video_count"] == 0


def test_dg_missing_video_skips_when_video_exists(db):
    acc = _account(db)
    camp = _campaign(db, acc)
    ag = GoogleAssetGroup(
        id=str(uuid.uuid4()),
        campaign_id=camp.id,
        account_id=acc.id,
        platform_asset_group_id=f"ag_{uuid.uuid4().hex[:6]}",
        name="Main AG",
        status="ACTIVE",
    )
    db.add(ag); db.commit()
    db.add(GoogleAsset(
        id=str(uuid.uuid4()),
        asset_group_id=ag.id,
        account_id=acc.id,
        platform_asset_id=f"a_{uuid.uuid4().hex[:6]}",
        asset_type="VIDEO",
    ))
    db.commit()

    det = get_detector("DG_MISSING_VIDEO")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


# ── PMAX_LEARNING_STUCK ─────────────────────────────────────
def test_pmax_learning_stuck_fires_when_old_and_low_conv(db):
    acc = _account(db)
    camp = _campaign(
        db, acc,
        start_date=date.today() - timedelta(days=45),
    )
    # Only 5 conversions in the last 30 days.
    for i in range(5):
        _metrics(db, camp, date.today() - timedelta(days=i), spend=100, conversions=1)

    det = get_detector("PMAX_LEARNING_STUCK")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["campaign_age_days"] >= 28


def test_pmax_learning_stuck_skips_young_campaign(db):
    acc = _account(db)
    camp = _campaign(
        db, acc, start_date=date.today() - timedelta(days=10),
    )
    det = get_detector("PMAX_LEARNING_STUCK")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


# ── BUDGET_MIX_OFF_TARGET ───────────────────────────────────
def test_budget_mix_off_target_fires_when_only_pmax(db):
    acc = _account(db)
    pmax = _campaign(db, acc, name="PMax Main", objective="PERFORMANCE_MAX")
    # 30 days of PMax spend only — mix will be 100% PMax, way off SOP.
    for i in range(30):
        _metrics(db, pmax, date.today() - timedelta(days=i), spend=50, conversions=1, revenue=500)

    det = get_detector("BUDGET_MIX_OFF_TARGET")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    dev = hits[0].evidence["deviations"]
    assert "PMAX" in dev or "DEMAND_GEN" in dev or "SEARCH" in dev


# ── SEASONALITY_LEAD_TIME_APPROACHING ───────────────────────
def _seed_event(db, *, country_code: str, event_key: str, start: date, lead: int = 14):
    db.add(GoogleSeasonalityEvent(
        id=str(uuid.uuid4()),
        country_code=country_code,
        event_key=event_key,
        name=f"{country_code} {event_key}",
        start_month=start.month,
        start_day=start.day,
        end_month=start.month,
        end_day=start.day,
        lead_time_days=lead,
        budget_bump_pct_min=Decimal("20"),
        budget_bump_pct_max=Decimal("30"),
    ))
    db.commit()


def test_seasonality_lead_time_fires_when_event_near(db):
    acc = _account(db, "Meander Saigon")  # VN branch
    camp = _campaign(db, acc)
    _seed_event(
        db, country_code="VN", event_key="test_event",
        start=date.today() + timedelta(days=10), lead=14,
    )

    det = get_detector("SEASONALITY_LEAD_TIME_APPROACHING")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["event_key"] == "test_event"
    assert hits[0].evidence["country_code"] == "VN"


def test_seasonality_skips_event_for_wrong_home_country(db):
    """Osaka (JP branch) must NOT fire on a Vietnam event."""
    acc = _account(db, "Meander Osaka")  # JP branch
    _campaign(db, acc)
    _seed_event(
        db, country_code="VN", event_key="tet",
        start=date.today() + timedelta(days=10),
    )

    det = get_detector("SEASONALITY_LEAD_TIME_APPROACHING")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_seasonality_fires_when_home_country_matches(db):
    """Osaka fires on a JP event."""
    acc = _account(db, "Meander Osaka")
    _campaign(db, acc)
    _seed_event(
        db, country_code="JP", event_key="golden_week",
        start=date.today() + timedelta(days=10),
    )

    det = get_detector("SEASONALITY_LEAD_TIME_APPROACHING")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["country_code"] == "JP"


def test_seasonality_fires_when_targeted_country_matches(db):
    """Saigon campaign targeting KR adgroup fires on a KR event, even though home is VN."""
    acc = _account(db, "Meander Saigon")
    camp = _campaign(db, acc)
    _adset(db, camp, acc, country="KR")
    _seed_event(
        db, country_code="KR", event_key="chuseok",
        start=date.today() + timedelta(days=10),
    )

    det = get_detector("SEASONALITY_LEAD_TIME_APPROACHING")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert len(hits) == 1
    assert hits[0].evidence["country_code"] == "KR"


def test_seasonality_skips_when_branch_unknown(db):
    """Random account_name that doesn't map to a branch → no home country → detector skips."""
    acc = _account(db, "Random Unknown Account")
    _campaign(db, acc)
    _seed_event(
        db, country_code="VN", event_key="tet",
        start=date.today() + timedelta(days=10),
    )

    det = get_detector("SEASONALITY_LEAD_TIME_APPROACHING")
    hits = [h for h in (det.evaluate(db, t) for t in det.scope(db)) if h]
    assert hits == []


def test_all_detectors_registered():
    """Sanity: every registered detector is in the catalog, and the Phase-3
    core set is present."""
    detectors = all_detectors()
    rec_types = {d.rec_type for d in detectors}
    # Phase 3 core detectors MUST be present.
    assert {
        "DG_MISSING_VIDEO",
        "ZERO_CONVERSIONS_2D",
        "PMAX_LEARNING_STUCK",
        "BUDGET_MIX_OFF_TARGET",
        "SEASONALITY_LEAD_TIME_APPROACHING",
    }.issubset(rec_types)
    # Every registered rec_type has a catalog entry (prevents rogue registers).
    from app.services.google_recommendations.catalog import CATALOG
    assert rec_types.issubset(set(CATALOG.keys()))
