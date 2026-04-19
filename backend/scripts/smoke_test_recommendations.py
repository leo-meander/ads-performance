"""End-to-end dry-run of the Google recommendation engine.

Usage:
    POSTGRES_CONNECTION_STRING=sqlite:///./test_migration_011.db \
        python scripts/smoke_test_recommendations.py

Seeds a minimal dataset that triggers each of the Phase-3 smoke-test detectors,
then runs the orchestrator. No Google API or Claude API calls are made — the
Claude enricher falls back to static reasoning when ANTHROPIC_API_KEY is unset.

No writes to production Google Ads.
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.google_asset import GoogleAsset
from app.models.google_asset_group import GoogleAssetGroup
from app.models.google_recommendation import GoogleRecommendation
from app.models.google_seasonality_event import GoogleSeasonalityEvent
from app.models.metrics import MetricsCache
from app.services.google_recommendations import engine as rec_engine


def _u(): return str(uuid.uuid4())


def seed(db) -> dict:
    # ── Account (randomized so re-running the script doesn't conflict)
    rand = uuid.uuid4().hex[:8]
    acc = AdAccount(
        id=_u(), platform="google", account_id=f"acc_{rand}",
        account_name=f"Meander Saigon (smoke {rand})", currency="VND",
        is_active=True,
    )
    db.add(acc); db.commit()

    # ── PMax campaign, 40 days old, low conversions (PMAX_LEARNING_STUCK)
    pmax_stuck = Campaign(
        id=_u(), account_id=acc.id, platform="google",
        platform_campaign_id=f"pmax_1_{rand}",
        name="PMax - Meander Saigon",
        status="ACTIVE", objective="PERFORMANCE_MAX",
        daily_budget=Decimal("1000000"),
        start_date=date.today() - timedelta(days=45),
    )
    db.add(pmax_stuck)

    # ── PMax with zero conversions last 2 days (ZERO_CONVERSIONS_2D)
    pmax_tag_broken = Campaign(
        id=_u(), account_id=acc.id, platform="google",
        platform_campaign_id=f"pmax_2_{rand}",
        name="PMax - Brand Tag Broken",
        status="ACTIVE", objective="PERFORMANCE_MAX",
        daily_budget=Decimal("500000"),
        start_date=date.today() - timedelta(days=60),
    )
    db.add(pmax_tag_broken); db.commit()

    # Metrics for pmax_stuck: 5 conversions over 30 days
    for i in range(30):
        db.add(MetricsCache(
            id=_u(), campaign_id=pmax_stuck.id, platform="google",
            date=date.today() - timedelta(days=i),
            spend=Decimal("100000"), impressions=1000, clicks=50,
            conversions=(1 if i < 5 else 0),
            revenue=Decimal("0"),
        ))
    # Metrics for pmax_tag_broken: 2 days with spend but zero conversions
    for i in (1, 2):
        db.add(MetricsCache(
            id=_u(), campaign_id=pmax_tag_broken.id, platform="google",
            date=date.today() - timedelta(days=i),
            spend=Decimal("200000"), impressions=2000, clicks=100,
            conversions=0, revenue=Decimal("0"),
        ))
    db.commit()

    # ── Asset group on pmax_stuck, with no VIDEO asset (DG_MISSING_VIDEO)
    ag = GoogleAssetGroup(
        id=_u(), campaign_id=pmax_stuck.id, account_id=acc.id,
        platform_asset_group_id=f"ag_{rand}", name="Main AG", status="ACTIVE",
    )
    db.add(ag)
    db.add(GoogleAsset(
        id=_u(), asset_group_id=ag.id, account_id=acc.id,
        platform_asset_id=f"asset_img_{rand}", asset_type="IMAGE",
        image_url="https://example.com/room.jpg",
    ))
    db.commit()

    # ── Seasonality event that starts in 10 days with 14d lead
    # country_code='VN' matches the smoke account (Meander Saigon → VN home country)
    start = date.today() + timedelta(days=10)
    db.add(GoogleSeasonalityEvent(
        id=_u(), country_code="VN", event_key=f"smoke_event_{rand}",
        name="Smoke Test Peak",
        start_month=start.month, start_day=start.day,
        end_month=start.month, end_day=start.day,
        lead_time_days=14,
        budget_bump_pct_min=Decimal("20"),
        budget_bump_pct_max=Decimal("30"),
    ))
    db.commit()

    return {
        "account_id": acc.id,
        "pmax_stuck_id": pmax_stuck.id,
        "pmax_tag_broken_id": pmax_tag_broken.id,
        "asset_group_id": ag.id,
    }


def run(db_url: str) -> None:
    os.environ.pop("ANTHROPIC_API_KEY", None)  # Force Claude-free run.

    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        # Clean up prior recs so re-runs produce clean numbers.
        db.query(GoogleRecommendation).delete(); db.commit()
        ids = seed(db)
        print(f"Seeded: {ids}\n")

        for cadence in ("daily", "weekly", "seasonality", "monthly"):
            stats = rec_engine.run_recommendations(db, cadence=cadence)
            print(f"cadence={cadence:11s} → {stats}")

        print("\nAll recommendations produced:")
        recs = (
            db.query(GoogleRecommendation)
            .order_by(
                GoogleRecommendation.severity.asc(),
                GoogleRecommendation.rec_type.asc(),
            )
            .all()
        )
        for r in recs:
            print(
                f"  [{r.severity:8s}] {r.rec_type:40s} "
                f"auto={str(r.auto_applicable):5s} "
                f"title={r.title[:80]!r}"
            )
        print(f"\nTotal recommendations: {len(recs)}")


if __name__ == "__main__":
    url = os.environ.get(
        "POSTGRES_CONNECTION_STRING",
        "sqlite:///./test_migration_011.db",
    )
    print(f"Using DB: {url}\n")
    run(url)
