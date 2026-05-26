"""Tests for the Action Needed apply/mark-done router. Meta API is mocked."""
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.change_log_entry import ChangeLogEntry
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password

engine = create_engine("sqlite:///test_platform.db", connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _admin():
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Admin",
        password_hash=hash_password("pass"),
        roles=["admin"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.roles or [])}"}


def _meta_campaign(platform="meta", daily_budget=100.0):
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform=platform,
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Test Account",
        currency="VND",
        is_active=True,
        access_token_enc="test_token",
    )
    db.add(account)
    db.flush()
    camp = Campaign(
        id=str(uuid.uuid4()),
        account_id=account.id,
        platform=platform,
        platform_campaign_id=f"camp_{uuid.uuid4().hex[:8]}",
        name="Test Campaign",
        status="ACTIVE",
        daily_budget=daily_budget,
        funnel_stage="TOF",
    )
    db.add(camp)
    db.commit()
    cid = camp.id
    db.close()
    return cid


def test_pause_campaign_applies_and_logs():
    user = _admin()
    cid = _meta_campaign()
    with patch("app.services.meta_actions.pause_campaign") as mock_pause:
        mock_pause.return_value = True
        resp = client.post(
            "/api/action-needed/apply",
            json={"campaign_id": cid, "action": "pause_campaign", "confirm": True},
            headers=_auth(user),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True, body
    mock_pause.assert_called_once()

    db = TestSession()
    logs = db.query(ActionLog).filter(ActionLog.campaign_id == cid).all()
    changes = db.query(ChangeLogEntry).filter(ChangeLogEntry.campaign_id == cid).all()
    db.close()
    assert len(logs) == 1 and logs[0].action == "pause_campaign" and logs[0].success is True
    assert len(changes) == 1 and changes[0].category == "ad_mutation"


def test_cut_budget_halves_and_calls_update():
    user = _admin()
    cid = _meta_campaign(daily_budget=100.0)
    with patch("app.services.meta_actions.update_campaign_budget") as mock_budget:
        mock_budget.return_value = True
        resp = client.post(
            "/api/action-needed/apply",
            json={"campaign_id": cid, "action": "cut_budget", "confirm": True},
            headers=_auth(user),
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    _, kwargs = mock_budget.call_args
    assert kwargs["new_daily_budget"] == 50.0
    assert kwargs["current_daily_budget"] == 100.0


def test_apply_requires_confirm():
    user = _admin()
    cid = _meta_campaign()
    resp = client.post(
        "/api/action-needed/apply",
        json={"campaign_id": cid, "action": "pause_campaign", "confirm": False},
        headers=_auth(user),
    )
    assert resp.json()["success"] is False


def test_non_meta_campaign_rejected():
    user = _admin()
    cid = _meta_campaign(platform="google")
    resp = client.post(
        "/api/action-needed/apply",
        json={"campaign_id": cid, "action": "pause_campaign", "confirm": True},
        headers=_auth(user),
    )
    body = resp.json()
    assert body["success"] is False
    assert "Meta" in (body["error"] or "")


def test_mark_done_logs_only():
    user = _admin()
    cid = _meta_campaign()
    resp = client.post(
        "/api/action-needed/mark-done",
        json={"campaign_id": cid, "title": "Verify tracking on landing page", "note": "checked pixel"},
        headers=_auth(user),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    db = TestSession()
    changes = db.query(ChangeLogEntry).filter(ChangeLogEntry.campaign_id == cid).all()
    logs = db.query(ActionLog).filter(ActionLog.campaign_id == cid).all()
    db.close()
    assert len(changes) == 1 and changes[0].source == "manual"
    assert len(logs) == 0  # mark-done never writes an action_logs row
