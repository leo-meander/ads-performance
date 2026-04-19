"""Integration tests for the Meta recommendation orchestrator.

Exercises idempotent upsert, supersede logic, and expiry — without hitting
Claude (enrichment is monkey-patched to a no-op).
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
from app.models.meta_recommendation import MetaRecommendation
from app.models.metrics import MetricsCache
from app.services.meta_recommendations import engine, ai_enricher
from app.services.meta_recommendations.ai_enricher import EnrichedFinding

TEST_DB_URL = "sqlite:///./test_meta_recs_engine.db"
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


@pytest.fixture(autouse=True)
def _stub_enricher(monkeypatch):
    def fake_batch(items, account_map, campaign_map, **_):
        return [
            EnrichedFinding(
                detector=d, target=t, finding=f,
                reasoning=f"STUB reasoning for {d.rec_type}",
                tailored_action_params={},
                confidence=0.80,
                risk_flags=[],
            )
            for d, t, f in items
        ]
    monkeypatch.setattr(ai_enricher, "enrich_batch", fake_batch)
    monkeypatch.setattr(engine, "enrich_batch", fake_batch)


def _setup_active_ad_with_high_frequency(db) -> tuple[AdAccount, Campaign, AdSet, Ad]:
    """Seed a Saigon branch ad set + ad whose 7d avg frequency > 2.5 so the
    META_FREQ_ABOVE_CEILING detector fires."""
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"meta_{uuid.uuid4().hex[:8]}",
        account_name="Meander Saigon", currency="VND", is_active=True,
    )
    db.add(acc); db.commit()
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}",
        name="[BOF] Saigon Retargeting", status="ACTIVE",
        daily_budget=Decimal("50"), funnel_stage="BOF",
        start_date=date.today() - timedelta(days=30),
    )
    db.add(camp); db.commit()
    ad_set = AdSet(
        id=str(uuid.uuid4()), account_id=acc.id, campaign_id=camp.id, platform="meta",
        platform_adset_id=f"as_{uuid.uuid4().hex[:8]}",
        name="VN_Solo_BOF", status="ACTIVE", country="VN",
    )
    db.add(ad_set); db.commit()
    ad = Ad(
        id=str(uuid.uuid4()), account_id=acc.id, campaign_id=camp.id, ad_set_id=ad_set.id,
        platform="meta", platform_ad_id=f"ad_{uuid.uuid4().hex[:8]}",
        name="Signature slide creative", status="ACTIVE",
    )
    db.add(ad); db.commit()
    # Seven days of metrics with frequency 3.0 (> 2.5 ceiling)
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
            platform="meta", date=date.today() - timedelta(days=offset),
            spend=Decimal("100"), impressions=6000, clicks=80,
            conversions=1, revenue=Decimal("300"),
            frequency=Decimal("3.00"),
        ))
    db.commit()
    return acc, camp, ad_set, ad


def test_run_daily_inserts_frequency_recommendation(db):
    _setup_active_ad_with_high_frequency(db)
    stats = engine.run_recommendations(db, cadence="daily")
    assert stats["inserted"] >= 1
    rows = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.rec_type == "META_FREQ_ABOVE_CEILING")
        .all()
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.status == "pending"
    assert r.auto_applicable is True
    assert r.suggested_action["function"] == "pause_ad"
    assert r.ai_reasoning.startswith("STUB")
    assert r.entity_level == "ad"
    assert r.funnel_stage == "BOF"
    assert r.targeted_country == "VN"


def test_run_daily_is_idempotent(db):
    _setup_active_ad_with_high_frequency(db)
    engine.run_recommendations(db, cadence="daily")
    stats2 = engine.run_recommendations(db, cadence="daily")
    # First run inserted, second run must update — no duplicate pending rows.
    assert stats2["inserted"] == 0
    assert (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.rec_type == "META_FREQ_ABOVE_CEILING")
        .count()
    ) == 1


def test_supersede_when_frequency_drops(db):
    _, _, _, ad = _setup_active_ad_with_high_frequency(db)
    engine.run_recommendations(db, cadence="daily")
    # Frequency cools back below the ceiling.
    db.query(MetricsCache).filter(MetricsCache.ad_id == ad.id).update(
        {"frequency": Decimal("1.50")},
    )
    db.commit()
    stats2 = engine.run_recommendations(db, cadence="daily")
    assert stats2["superseded"] >= 1
    row = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.rec_type == "META_FREQ_ABOVE_CEILING")
        .first()
    )
    assert row.status == "superseded"


def test_expire_stale_pending(db):
    _setup_active_ad_with_high_frequency(db)
    engine.run_recommendations(db, cadence="daily")
    row = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.rec_type == "META_FREQ_ABOVE_CEILING")
        .first()
    )
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    db.query(MetricsCache).delete(); db.commit()
    engine.run_recommendations(db, cadence="daily")
    row = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.rec_type == "META_FREQ_ABOVE_CEILING")
        .first()
    )
    assert row.status in {"superseded", "expired"}
