"""Tests for approval workflow: submit, decide, resubmit, notifications."""
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.base import Base
from app.models.notification import Notification
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


def _create_combo():
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Test Account",
        currency="VND",
    )
    db.add(account)
    db.flush()
    combo = AdCombo(
        id=str(uuid.uuid4()),
        combo_id="CMB-TEST",
        branch_id=account.id,
        ad_name="Test Ad Combo",
        copy_id="CPY-001",
        material_id="MAT-001",
    )
    db.add(combo)
    db.commit()
    db.refresh(combo)
    db.close()
    return combo


def _auth_headers(user):
    token = create_access_token(user.id, user.roles or [])
    return {"Authorization": f"Bearer {token}"}


# ── Submit for approval tests ────────────────────────────────


def test_submit_for_approval():
    creator = _create_user(["creator"])
    reviewer1 = _create_user(["reviewer"], email="rev1@meander.com")
    reviewer2 = _create_user(["reviewer"], email="rev2@meander.com")
    combo = _create_combo()

    response = client.post(
        "/api/approvals",
        json={
            "combo_id": combo.id,
            "reviewer_ids": [reviewer1.id, reviewer2.id],
            "working_file_url": "https://canva.com/design/test",
            "working_file_label": "Canva Design",
        },
        headers=_auth_headers(creator),
    )
    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] == "PENDING_APPROVAL"
    assert len(data["data"]["reviewers"]) == 2
    assert data["data"]["working_file_url"] == "https://canva.com/design/test"


def test_reviewer_cannot_submit():
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    response = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(reviewer),
    )
    assert response.status_code == 403


def test_submit_creates_notifications():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"], email="notif@meander.com")
    combo = _create_combo()

    client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )

    # Check notifications for reviewer
    response = client.get("/api/notifications", headers=_auth_headers(reviewer))
    data = response.json()
    assert data["success"] is True
    assert data["data"]["unread_count"] >= 1
    assert any(n["type"] == "REVIEW_REQUESTED" for n in data["data"]["items"])


# ── Decision tests ───────────────────────────────────────────


def test_all_approve():
    creator = _create_user(["creator"])
    reviewer1 = _create_user(["reviewer"])
    reviewer2 = _create_user(["reviewer"])
    combo = _create_combo()

    # Submit
    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer1.id, reviewer2.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    # Reviewer 1 approves
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer1),
    )
    assert resp.json()["data"]["status"] == "PENDING_APPROVAL"

    # Reviewer 2 approves → should be APPROVED
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer2),
    )
    assert resp.json()["data"]["status"] == "APPROVED"


def test_any_reject():
    creator = _create_user(["creator"])
    reviewer1 = _create_user(["reviewer"])
    reviewer2 = _create_user(["reviewer"])
    combo = _create_combo()

    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer1.id, reviewer2.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    # Reviewer 1 rejects → immediately REJECTED
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "REJECTED"},
        headers=_auth_headers(reviewer1),
    )
    assert resp.json()["data"]["status"] == "REJECTED"


def test_creator_notified_on_approval():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    # Approve
    client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer),
    )

    # Check creator notifications
    resp = client.get("/api/notifications", headers=_auth_headers(creator))
    data = resp.json()["data"]
    assert any(n["type"] == "COMBO_APPROVED" for n in data["items"])


def test_cannot_decide_twice():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer),
    )

    # Try to decide again
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "REJECTED"},
        headers=_auth_headers(reviewer),
    )
    assert resp.json()["success"] is False
    assert "already" in resp.json()["error"].lower()


# ── Resubmit tests ──────────────────────────────────────────


def test_resubmit_after_rejection():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    # Submit + reject
    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "REJECTED"},
        headers=_auth_headers(reviewer),
    )

    # Resubmit
    resp = client.post(
        f"/api/approvals/{approval_id}/resubmit",
        json={"reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["round"] == 2
    assert data["data"]["status"] == "PENDING_APPROVAL"


# ── Access control tests ─────────────────────────────────────


def test_get_approval_detail():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    # Creator can access
    resp = client.get(f"/api/approvals/{approval_id}", headers=_auth_headers(creator))
    assert resp.json()["success"] is True

    # Reviewer can access
    resp = client.get(f"/api/approvals/{approval_id}", headers=_auth_headers(reviewer))
    assert resp.json()["success"] is True

    # Another user cannot access
    other = _create_user(["creator"])
    resp = client.get(f"/api/approvals/{approval_id}", headers=_auth_headers(other))
    assert resp.json()["success"] is False
    assert "denied" in resp.json()["error"].lower()


def test_pending_reviews_endpoint():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )

    resp = client.get("/api/approvals/pending", headers=_auth_headers(reviewer))
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["items"]) == 1
