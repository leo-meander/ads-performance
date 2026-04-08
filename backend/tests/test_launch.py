"""Tests for launch flow — Meta Ads API is mocked, Celery email task mocked."""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password

# ── Test database setup ──────────────────────────────────────

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


@pytest.fixture(autouse=True)
def mock_email_queue():
    """Mock Celery email task to avoid Redis connection in tests."""
    with patch("app.services.approval_service._queue_emails"):
        yield


def _create_user(roles, email=None):
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=email or f"user_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Test User",
        password_hash=hash_password("pass"),
        roles=roles,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _create_combo_and_account():
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Test Account",
        currency="VND",
        access_token_enc="test_token",
    )
    db.add(account)
    db.flush()

    campaign = Campaign(
        id=str(uuid.uuid4()),
        account_id=account.id,
        platform="meta",
        platform_campaign_id="camp_123",
        name="Test Campaign",
        status="ACTIVE",
        objective="CONVERSIONS",
    )
    db.add(campaign)
    db.flush()

    combo = AdCombo(
        id=str(uuid.uuid4()),
        combo_id="CMB-LAUNCH",
        branch_id=account.id,
        ad_name="Launch Test Ad",
        copy_id="CPY-001",
        material_id="MAT-001",
    )
    db.add(combo)
    db.commit()
    db.refresh(combo)
    db.refresh(campaign)
    db.refresh(account)
    db.close()
    return combo, campaign, account


def _submit_and_approve(creator, reviewer, combo):
    """Submit a combo for approval and approve it. Returns approval_id."""
    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers={"Authorization": f"Bearer {create_access_token(creator.id, creator.roles)}"},
    )
    approval_id = resp.json()["data"]["id"]

    client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "APPROVED"},
        headers={"Authorization": f"Bearer {create_access_token(reviewer.id, reviewer.roles)}"},
    )
    return approval_id


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.roles or [])}"}


# ── Launch tests ─────────────────────────────────────────────


def test_list_launch_campaigns():
    creator = _create_user(["creator"])
    _create_combo_and_account()

    resp = client.get("/api/launch/campaigns", headers=_auth_headers(creator))
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["items"]) >= 1


@patch("app.services.launch_service._create_meta_ad")
def test_launch_to_existing_campaign(mock_create_ad):
    mock_create_ad.return_value = "ad_999"

    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo, campaign, _ = _create_combo_and_account()
    approval_id = _submit_and_approve(creator, reviewer, combo)

    resp = client.post(
        "/api/launch/existing",
        json={"approval_id": approval_id, "campaign_id": campaign.id},
        headers=_auth_headers(creator),
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["launch_status"] == "LAUNCHED"
    assert data["data"]["launch_meta_ad_id"] == "ad_999"


def test_non_creator_cannot_launch():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    other_creator = _create_user(["creator"])
    combo, campaign, _ = _create_combo_and_account()
    approval_id = _submit_and_approve(creator, reviewer, combo)

    # Other creator tries to launch — should fail
    resp = client.post(
        "/api/launch/existing",
        json={"approval_id": approval_id, "campaign_id": campaign.id},
        headers=_auth_headers(other_creator),
    )
    data = resp.json()
    assert data["success"] is False
    assert "creator" in data["error"].lower() or "admin" in data["error"].lower()


def test_cannot_launch_unapproved():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo, campaign, _ = _create_combo_and_account()

    # Submit but don't approve
    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    resp = client.post(
        "/api/launch/existing",
        json={"approval_id": approval_id, "campaign_id": campaign.id},
        headers=_auth_headers(creator),
    )
    data = resp.json()
    assert data["success"] is False
    assert "not approved" in data["error"].lower()


def test_launch_status_endpoint():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo, _, _ = _create_combo_and_account()
    approval_id = _submit_and_approve(creator, reviewer, combo)

    resp = client.get(f"/api/launch/{approval_id}/status", headers=_auth_headers(creator))
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "APPROVED"
    assert data["data"]["launch_status"] is None  # Not yet launched
