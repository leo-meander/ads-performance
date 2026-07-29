"""Applier + router contract tests.

Verifies:
- 400 when confirm_warning is missing
- 409 when recommendation is guidance-only (auto_applicable=False)
- 409 when a dispatched google_actions function raises ManualActionRequired
- Successful apply writes action_logs + marks rec applied
- Dismiss sets status + reason
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.campaign import Campaign
from app.models.google_recommendation import GoogleRecommendation
from app.services import google_actions
from app.services.google_recommendations import applier
from tests.db import TestSession


@pytest.fixture
def db():
    s = TestSession()
    try:
        yield s
    finally:
        s.close()


def _seed(db, *, auto_applicable=True, function="update_campaign_budget"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="google",
        account_id="1234567890", account_name="Seed", currency="USD", is_active=True,
    )
    db.add(acc); db.commit()
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="google",
        platform_campaign_id="9999999", name="Seed PMax", status="ACTIVE",
        objective="PERFORMANCE_MAX", daily_budget=Decimal("100"),
        start_date=date.today() - timedelta(days=30),
    )
    db.add(camp); db.commit()

    rec = GoogleRecommendation(
        id=str(uuid.uuid4()),
        rec_type="SEASONALITY_LEAD_TIME_APPROACHING",
        severity="critical", status="pending",
        account_id=acc.id, campaign_id=camp.id,
        entity_level="campaign", campaign_type="PMAX",
        title="Test rec", detector_finding={}, metrics_snapshot={},
        suggested_action={"function": function, "kwargs": {
            "campaign_id": camp.id, "new_daily_budget": 150.0,
        }},
        auto_applicable=auto_applicable,
        warning_text="Test warning.",
        sop_reference="PART_6.SEASONALITY",
        dedup_key=f"X:{camp.id}",
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(rec); db.commit()
    return rec


def test_apply_requires_confirmation(db):
    rec = _seed(db)
    with pytest.raises(applier.ConfirmationRequired):
        applier.apply_recommendation(
            db, rec.id, confirm_warning=False, applied_by_user_id=None,
        )


def test_apply_rejects_guidance_only(db):
    rec = _seed(db, auto_applicable=False)
    with pytest.raises(applier.NotAutoApplicable):
        applier.apply_recommendation(
            db, rec.id, confirm_warning=True, applied_by_user_id=None,
        )


def test_apply_maps_manual_action_required(db, monkeypatch):
    rec = _seed(db, function="switch_bid_strategy")

    # switch_bid_strategy already raises ManualActionRequired in the stub.
    with pytest.raises(google_actions.ManualActionRequired):
        applier.apply_recommendation(
            db, rec.id, confirm_warning=True, applied_by_user_id=None,
        )


def test_apply_success_records_action_log(db, monkeypatch):
    rec = _seed(db)

    calls = {}
    def fake_update_budget(customer_id, platform_campaign_id, new_budget_micros):
        calls["customer_id"] = customer_id
        calls["platform_campaign_id"] = platform_campaign_id
        calls["new_budget_micros"] = new_budget_micros
        return True

    monkeypatch.setattr(
        applier.google_actions, "update_campaign_budget", fake_update_budget,
    )
    monkeypatch.setitem(
        applier.ACTION_DISPATCH, "update_campaign_budget", fake_update_budget,
    )

    updated = applier.apply_recommendation(
        db, rec.id, confirm_warning=True, applied_by_user_id="user-1",
    )
    assert updated.status == "applied"
    assert updated.applied_by == "user-1"
    assert updated.action_log_id is not None
    assert calls["customer_id"] == "1234567890"
    assert calls["platform_campaign_id"] == "9999999"
    assert calls["new_budget_micros"] == 150_000_000

    log = db.query(ActionLog).filter_by(id=updated.action_log_id).first()
    assert log is not None
    assert log.success is True
    assert log.triggered_by == "recommendation"
    assert log.action == "update_campaign_budget"


def test_dismiss_marks_dismissed_with_reason(db):
    rec = _seed(db)
    updated = applier.dismiss_recommendation(
        db, rec.id, reason="Already handled manually", dismissed_by_user_id="user-2",
    )
    assert updated.status == "dismissed"
    assert updated.dismiss_reason == "Already handled manually"
    assert updated.dismissed_by == "user-2"
