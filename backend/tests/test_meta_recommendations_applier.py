"""Applier tests — verify:
- pause_ad auto-apply writes an immutable ActionLog + flips rec status
- guidance-only rec raises NotAutoApplicable
- budget guard rejects > 25% raise without force=True
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.meta_recommendation import MetaRecommendation
from app.services import meta_actions
from app.services.meta_recommendations import applier

TEST_DB_URL = "sqlite:///./test_meta_recs_applier.db"
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


@pytest.fixture
def entities(db):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Saigon", currency="VND", is_active=True,
        access_token_enc="fake_token",
    )
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}",
        name="[BOF] Test", status="ACTIVE",
        daily_budget=Decimal("100"),
    )
    ad_set = AdSet(
        id=str(uuid.uuid4()), account_id=acc.id, campaign_id=camp.id, platform="meta",
        platform_adset_id=f"as_{uuid.uuid4().hex[:8]}",
        name="VN_Solo_BOF", status="ACTIVE", country="VN",
        daily_budget=Decimal("50"),
    )
    ad = Ad(
        id=str(uuid.uuid4()), account_id=acc.id, campaign_id=camp.id, ad_set_id=ad_set.id,
        platform="meta", platform_ad_id=f"ad_{uuid.uuid4().hex[:8]}",
        name="Fatigued creative", status="ACTIVE",
    )
    db.add_all([acc, camp, ad_set, ad])
    db.commit()
    return acc, camp, ad_set, ad


def _make_rec(
    db, *,
    rec_type: str,
    auto_applicable: bool,
    account_id: str,
    campaign_id: str | None = None,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
    entity_level: str = "ad",
    function: str | None = None,
    kwargs: dict | None = None,
) -> MetaRecommendation:
    rec = MetaRecommendation(
        id=str(uuid.uuid4()),
        rec_type=rec_type,
        severity="warning",
        status="pending",
        account_id=account_id,
        campaign_id=campaign_id,
        ad_set_id=ad_set_id,
        ad_id=ad_id,
        entity_level=entity_level,
        title="test",
        detector_finding={"k": "v"},
        metrics_snapshot={"spend_7d": 42},
        suggested_action={"function": function, "kwargs": kwargs or {}},
        auto_applicable=auto_applicable,
        warning_text="warning",
        dedup_key=f"{rec_type}:{entity_level}:{ad_id or ad_set_id or campaign_id}",
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(rec); db.commit()
    return rec


def test_apply_pause_ad_writes_action_log_and_flips_status(db, entities, monkeypatch):
    acc, camp, ad_set, ad = entities
    called: dict = {}

    def fake_pause_ad(access_token, platform_ad_id):
        called["access_token"] = access_token
        called["platform_ad_id"] = platform_ad_id
        return True

    monkeypatch.setattr(meta_actions, "pause_ad", fake_pause_ad)
    monkeypatch.setitem(applier.ACTION_DISPATCH, "pause_ad", fake_pause_ad)

    rec = _make_rec(
        db, rec_type="META_FREQ_ABOVE_CEILING", auto_applicable=True,
        account_id=acc.id, campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
        function="pause_ad", kwargs={},
    )
    updated = applier.apply_recommendation(
        db, rec.id, confirm_warning=True, applied_by_user_id="user-1",
    )
    assert updated.status == "applied"
    assert called["platform_ad_id"] == ad.platform_ad_id

    logs = db.query(ActionLog).all()
    assert len(logs) == 1
    assert logs[0].platform == "meta"
    assert logs[0].action == "pause_ad"
    assert logs[0].success is True
    assert logs[0].triggered_by == "recommendation"


def test_apply_guidance_rec_raises_not_auto_applicable(db, entities):
    acc, camp, ad_set, ad = entities
    rec = _make_rec(
        db, rec_type="META_MISSING_RECENT_BOOKER_EXCLUSION", auto_applicable=False,
        account_id=acc.id, campaign_id=camp.id, ad_set_id=ad_set.id,
        entity_level="ad_set",
    )
    with pytest.raises(applier.NotAutoApplicable):
        applier.apply_recommendation(
            db, rec.id, confirm_warning=True, applied_by_user_id="user-1",
        )


def test_apply_requires_confirm_warning(db, entities):
    acc, camp, ad_set, ad = entities
    rec = _make_rec(
        db, rec_type="META_FREQ_ABOVE_CEILING", auto_applicable=True,
        account_id=acc.id, campaign_id=camp.id, ad_set_id=ad_set.id, ad_id=ad.id,
        function="pause_ad", kwargs={},
    )
    with pytest.raises(applier.ConfirmationRequired):
        applier.apply_recommendation(
            db, rec.id, confirm_warning=False, applied_by_user_id="user-1",
        )


def test_budget_guard_rejects_over_25pct_raise():
    with pytest.raises(meta_actions.BudgetGuardError):
        meta_actions._guard_increase(100.0, 150.0, force=False)


def test_budget_guard_allows_force():
    # Should not raise.
    meta_actions._guard_increase(100.0, 200.0, force=True)


def test_budget_guard_allows_decrease():
    meta_actions._guard_increase(100.0, 80.0, force=False)


def test_budget_guard_allows_within_cap():
    # 100 -> 120 == +20% (within 25% cap)
    meta_actions._guard_increase(100.0, 120.0, force=False)
