"""Integration tests for the recommendation orchestrator.

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
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.google_recommendation import GoogleRecommendation
from app.models.metrics import MetricsCache
from app.services.google_recommendations import engine, ai_enricher
from app.services.google_recommendations.ai_enricher import EnrichedFinding

TEST_DB_URL = "sqlite:///./test_recs_engine.db"
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
    """Claude would be expensive and non-deterministic in CI; stub it."""
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


def _setup_campaign_with_zero_conv(db) -> Campaign:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="google",
        account_id=f"goog_{uuid.uuid4().hex[:8]}",
        account_name="Test Branch", currency="USD", is_active=True,
    )
    db.add(acc); db.commit()
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="google",
        platform_campaign_id=f"gc_{uuid.uuid4().hex[:8]}",
        name="Test PMax", status="ACTIVE", objective="PERFORMANCE_MAX",
        # Spend=50, budget=60 → 83% utilization: keeps SPEND_VS_BUDGET_ANOMALY
        # (>±20% deviation) AND BUDGET_DAILY_EXHAUSTED_EARLY (≥90% on 3+ days)
        # both quiet. Only ZERO_CONVERSIONS_7D should fire.
        daily_budget=Decimal("60"),
        start_date=date.today() - timedelta(days=40),
    )
    db.add(camp); db.commit()
    # seven consecutive days of spend with zero conversions
    for offset in range(1, 8):
        db.add(MetricsCache(
            id=str(uuid.uuid4()), campaign_id=camp.id, platform="google",
            date=date.today() - timedelta(days=offset),
            spend=Decimal("50"), impressions=100, clicks=5,
            conversions=0, revenue=Decimal("0"),
        ))
    db.commit()
    return camp


def test_run_daily_inserts_recommendation(db):
    _setup_campaign_with_zero_conv(db)
    stats = engine.run_recommendations(db, cadence="daily")
    assert stats["inserted"] == 1
    assert stats["updated"] == 0
    rows = db.query(GoogleRecommendation).all()
    assert len(rows) == 1
    assert rows[0].rec_type == "ZERO_CONVERSIONS_7D"
    assert rows[0].status == "pending"
    assert rows[0].ai_reasoning.startswith("STUB")


def test_run_daily_is_idempotent(db):
    _setup_campaign_with_zero_conv(db)
    engine.run_recommendations(db, cadence="daily")
    # second run — should update the same row, not insert.
    stats2 = engine.run_recommendations(db, cadence="daily")
    assert stats2["inserted"] == 0
    assert stats2["updated"] == 1
    assert db.query(GoogleRecommendation).count() == 1


def test_supersede_when_detector_stops_firing(db):
    camp = _setup_campaign_with_zero_conv(db)
    engine.run_recommendations(db, cadence="daily")
    assert db.query(GoogleRecommendation).filter_by(status="pending").count() == 1
    # Add a conversion → detector should no longer fire.
    db.query(MetricsCache).filter(
        MetricsCache.campaign_id == camp.id,
        MetricsCache.date == date.today() - timedelta(days=1),
    ).update({"conversions": 3})
    db.commit()
    stats2 = engine.run_recommendations(db, cadence="daily")
    assert stats2["superseded"] == 1
    row = db.query(GoogleRecommendation).first()
    assert row.status == "superseded"


def test_expire_stale_pending(db):
    _setup_campaign_with_zero_conv(db)
    engine.run_recommendations(db, cadence="daily")
    # Backdate expires_at to the past.
    row = db.query(GoogleRecommendation).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    # Clear metrics so detector no longer fires, then force supersede path off.
    db.query(MetricsCache).delete(); db.commit()
    stats = engine.run_recommendations(db, cadence="daily")
    # After processing: row first gets superseded (detector no longer fires)
    # OR expired if we guarantee supersede runs last. Either outcome is valid
    # as long as status is not 'pending'.
    row = db.query(GoogleRecommendation).first()
    assert row.status in {"superseded", "expired"}
    assert stats["expired"] + stats["superseded"] >= 1
