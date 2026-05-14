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
from app.models.ad_set import AdSet
from app.models.approval import ComboApproval
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.user import User
from app.models.user_permission import UserPermission
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
    db.flush()
    if "admin" not in (roles or []):
        db.add(UserPermission(
            user_id=user.id, branch="Saigon", section="meta_ads", level="edit",
        ))
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _create_combo_and_account(with_adset: bool = True):
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

    if with_adset:
        adset = AdSet(
            id=str(uuid.uuid4()),
            campaign_id=campaign.id,
            account_id=account.id,
            platform="meta",
            platform_adset_id="adset_456",
            name="Test AdSet",
            status="ACTIVE",
        )
        db.add(adset)
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


def test_list_launch_campaigns_excludes_non_meta():
    """Regression: Google PMax / TikTok campaigns must not leak into the
    Launch to Meta Ads campaign picker — they have no Meta ad sets."""
    creator = _create_user(["creator"])
    _combo, _campaign, account = _create_combo_and_account()

    db = TestSession()
    google_campaign = Campaign(
        id=str(uuid.uuid4()),
        account_id=account.id,
        platform="google",
        platform_campaign_id=f"g_{uuid.uuid4().hex[:8]}",
        name="Mason_TPE_[TOF] PMax DE",
        status="ACTIVE",
    )
    db.add(google_campaign)
    db.commit()
    db.close()

    resp = client.get("/api/launch/campaigns", headers=_auth_headers(creator))
    data = resp.json()
    assert data["success"] is True
    names = [c["name"] for c in data["data"]["items"]]
    assert "Mason_TPE_[TOF] PMax DE" not in names


@patch("app.services.launch_service._create_meta_ad_from_ids")
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

    # Regression: must call Meta with adset platform ID, never campaign ID.
    args, _kwargs = mock_create_ad.call_args
    _account, adset_platform_id, _combo = args
    assert adset_platform_id == "adset_456"
    assert adset_platform_id != campaign.platform_campaign_id


@patch("app.services.launch_service._create_meta_ad_from_ids")
def test_launch_with_explicit_adset(mock_create_ad):
    mock_create_ad.return_value = "ad_explicit"

    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo, campaign, account = _create_combo_and_account(with_adset=True)

    db = TestSession()
    other = AdSet(
        id=str(uuid.uuid4()),
        campaign_id=campaign.id,
        account_id=account.id,
        platform="meta",
        platform_adset_id="adset_other",
        name="Other AdSet",
        status="ACTIVE",
    )
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()

    approval_id = _submit_and_approve(creator, reviewer, combo)

    resp = client.post(
        "/api/launch/existing",
        json={"approval_id": approval_id, "campaign_id": campaign.id, "adset_id": other_id},
        headers=_auth_headers(creator),
    )
    assert resp.json()["success"] is True
    args, _kwargs = mock_create_ad.call_args
    assert args[1] == "adset_other"


def test_launch_fails_when_no_adset_under_campaign():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo, campaign, _ = _create_combo_and_account(with_adset=False)
    approval_id = _submit_and_approve(creator, reviewer, combo)

    resp = client.post(
        "/api/launch/existing",
        json={"approval_id": approval_id, "campaign_id": campaign.id},
        headers=_auth_headers(creator),
    )
    data = resp.json()
    assert data["success"] is False
    assert "ad set" in data["error"].lower() or "adset" in data["error"].lower()


@patch("app.services.launch_service._create_meta_ad_from_ids")
def test_launch_marks_failed_on_meta_api_error(mock_create_ad):
    mock_create_ad.side_effect = RuntimeError("Meta API rate limited")

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
    assert data["success"] is False
    assert "rate limited" in data["error"].lower()

    db = TestSession()
    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    assert approval.launch_status == "LAUNCH_FAILED"
    assert "rate limited" in (approval.launch_error or "").lower()
    db.close()


def test_list_adsets_under_campaign():
    creator = _create_user(["creator"])
    _, campaign, _ = _create_combo_and_account()

    resp = client.get(
        f"/api/launch/adsets?campaign_id={campaign.id}",
        headers=_auth_headers(creator),
    )
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["items"]) == 1
    assert data["data"]["items"][0]["platform_adset_id"] == "adset_456"


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
