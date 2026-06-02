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


def _create_combos(n):
    """Create n combos under one shared account; returns list of combos."""
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
    combos = []
    for i in range(n):
        combo = AdCombo(
            id=str(uuid.uuid4()),
            combo_id=f"CMB-{uuid.uuid4().hex[:6]}",
            branch_id=account.id,
            ad_name=f"Test Ad Combo {i}",
            copy_id=f"CPY-{i:03d}",
            material_id=f"MAT-{i:03d}",
        )
        db.add(combo)
        combos.append(combo)
    db.commit()
    for c in combos:
        db.refresh(c)
    db.close()
    return combos


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


# ── Needs-revision tests ─────────────────────────────────────


def test_needs_revision_decision():
    creator = _create_user(["creator"])
    r1 = _create_user(["reviewer"])
    r2 = _create_user(["reviewer"])
    combo = _create_combo()

    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [r1.id, r2.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    # First reviewer asks for revision — approval transitions immediately
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "NEEDS_REVISION"},
        headers=_auth_headers(r1),
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "NEEDS_REVISION"

    # Second reviewer is locked out — already resolved
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(r2),
    )
    assert resp.json()["success"] is False


def test_needs_revision_notifies_creator():
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
        json={"decision": "NEEDS_REVISION"},
        headers=_auth_headers(reviewer),
    )

    db = TestSession()
    notifs = db.query(Notification).filter(
        Notification.user_id == creator.id,
        Notification.type == "COMBO_NEEDS_REVISION",
    ).all()
    assert len(notifs) == 1
    db.close()


def test_resubmit_after_needs_revision():
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
        json={"decision": "NEEDS_REVISION"},
        headers=_auth_headers(reviewer),
    )

    # Omit reviewer_ids — service should reuse the previous round's reviewers
    resp = client.post(
        f"/api/approvals/{approval_id}/resubmit",
        json={"working_file_url": "https://canva.com/design/v2"},
        headers=_auth_headers(creator),
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["round"] == 2
    assert data["data"]["status"] == "PENDING_APPROVAL"
    assert len(data["data"]["reviewers"]) == 1
    assert data["data"]["reviewers"][0]["reviewer_id"] == reviewer.id


def test_invalid_decision_rejected():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combo = _create_combo()

    resp = client.post(
        "/api/approvals",
        json={"combo_id": combo.id, "reviewer_ids": [reviewer.id]},
        headers=_auth_headers(creator),
    )
    approval_id = resp.json()["data"]["id"]

    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "MAYBE"},
        headers=_auth_headers(reviewer),
    )
    assert resp.json()["success"] is False


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


# ── Approval batch (multi-version) tests ─────────────────────


def _submit_batch(creator, reviewers, combos):
    return client.post(
        "/api/approval-batches",
        json={
            "versions": [{"combo_id": c.id} for c in combos],
            "reviewer_ids": [r.id for r in reviewers],
        },
        headers=_auth_headers(creator),
    )


def test_submit_batch_creates_versions():
    creator = _create_user(["creator"])
    r1 = _create_user(["reviewer"], email="br1@meander.com")
    r2 = _create_user(["reviewer"], email="br2@meander.com")
    combos = _create_combos(3)

    resp = _submit_batch(creator, [r1, r2], combos)
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "PENDING_APPROVAL"
    assert len(data["data"]["versions"]) == 3
    assert len(data["data"]["reviewers"]) == 2


def test_batch_reviewer_gets_one_notification():
    """A 3-version batch must produce ONE review request per reviewer, not 3."""
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"], email="bnotif@meander.com")
    combos = _create_combos(3)

    _submit_batch(creator, [reviewer], combos)

    resp = client.get("/api/notifications", headers=_auth_headers(reviewer))
    items = resp.json()["data"]["items"]
    review_reqs = [n for n in items if n["type"] == "REVIEW_REQUESTED"]
    assert len(review_reqs) == 1


def test_batch_all_approve():
    creator = _create_user(["creator"])
    r1 = _create_user(["reviewer"])
    r2 = _create_user(["reviewer"])
    combos = _create_combos(2)

    batch_id = _submit_batch(creator, [r1, r2], combos).json()["data"]["id"]

    # First reviewer approves → still pending
    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(r1),
    )
    assert resp.json()["data"]["status"] == "PENDING_APPROVAL"

    # Second reviewer approves → batch + all versions APPROVED
    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(r2),
    )
    data = resp.json()["data"]
    assert data["status"] == "APPROVED"
    assert all(v["status"] == "APPROVED" for v in data["versions"])


def test_batch_any_reject():
    creator = _create_user(["creator"])
    r1 = _create_user(["reviewer"])
    r2 = _create_user(["reviewer"])
    combos = _create_combos(2)

    batch_id = _submit_batch(creator, [r1, r2], combos).json()["data"]["id"]

    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "REJECTED"},
        headers=_auth_headers(r1),
    )
    data = resp.json()["data"]
    assert data["status"] == "REJECTED"
    assert all(v["status"] == "REJECTED" for v in data["versions"])


def test_batch_cannot_decide_twice():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)

    batch_id = _submit_batch(creator, [reviewer], combos).json()["data"]["id"]

    client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer),
    )
    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "REJECTED"},
        headers=_auth_headers(reviewer),
    )
    assert resp.json()["success"] is False
    assert "already" in resp.json()["error"].lower()


def test_batch_creator_notified_on_approval():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)

    batch_id = _submit_batch(creator, [reviewer], combos).json()["data"]["id"]
    client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer),
    )

    resp = client.get("/api/notifications", headers=_auth_headers(creator))
    items = resp.json()["data"]["items"]
    approved = [n for n in items if n["type"] == "COMBO_APPROVED"]
    assert len(approved) == 1  # one consolidated, not one per version


def test_batch_list_includes_batch_id():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)

    batch_id = _submit_batch(creator, [reviewer], combos).json()["data"]["id"]

    resp = client.get("/api/approvals", headers=_auth_headers(creator))
    items = resp.json()["data"]["items"]
    assert all(item["batch_id"] == batch_id for item in items)


def test_batch_access_denied_for_outsider():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)
    batch_id = _submit_batch(creator, [reviewer], combos).json()["data"]["id"]

    other = _create_user(["creator"])
    resp = client.get(f"/api/approval-batches/{batch_id}", headers=_auth_headers(other))
    assert resp.json()["success"] is False
    assert "denied" in resp.json()["error"].lower()


def test_batch_revise_bumps_round_and_resets_reviewers():
    creator = _create_user(["creator"])
    r1 = _create_user(["reviewer"])
    r2 = _create_user(["reviewer"])
    combos = _create_combos(2)

    batch = _submit_batch(creator, [r1, r2], combos).json()["data"]
    batch_id = batch["id"]
    v0_id = batch["versions"][0]["id"]

    # One reviewer decides before the creator revises.
    client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(r1),
    )

    resp = client.post(
        f"/api/approval-batches/{batch_id}/revise",
        json={
            "reviewer_ids": [r1.id, r2.id],
            "versions": [{"approval_id": v0_id, "working_file_url": "https://example.com/new"}],
        },
        headers=_auth_headers(creator),
    )
    data = resp.json()["data"]
    assert resp.json()["success"] is True
    assert data["status"] == "PENDING_APPROVAL"
    assert data["round"] == 2  # batch round bumped
    assert all(v["round"] == 2 for v in data["versions"])  # each version bumped
    assert all(rv["status"] == "PENDING" for rv in data["reviewers"])  # decisions reset
    v0 = next(v for v in data["versions"] if v["id"] == v0_id)
    assert v0["working_file_url"] == "https://example.com/new"

    # The reviewer who already decided can decide again on the re-opened batch.
    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(r1),
    )
    assert resp.json()["success"] is True


def test_batch_revise_only_creator():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)
    batch_id = _submit_batch(creator, [reviewer], combos).json()["data"]["id"]

    other = _create_user(["creator"])
    resp = client.post(
        f"/api/approval-batches/{batch_id}/revise",
        json={"reviewer_ids": [reviewer.id], "versions": []},
        headers=_auth_headers(other),
    )
    assert resp.json()["success"] is False
    assert "creator" in resp.json()["error"].lower()


def test_batch_revise_replaces_reviewer_set():
    creator = _create_user(["creator"])
    r1 = _create_user(["reviewer"])
    r2 = _create_user(["reviewer"])
    combos = _create_combos(2)
    batch_id = _submit_batch(creator, [r1, r2], combos).json()["data"]["id"]

    # Drop r2 — only r1 remains a reviewer across all versions.
    resp = client.post(
        f"/api/approval-batches/{batch_id}/revise",
        json={"reviewer_ids": [r1.id], "versions": []},
        headers=_auth_headers(creator),
    )
    data = resp.json()["data"]
    assert resp.json()["success"] is True
    assert {rv["reviewer_id"] for rv in data["reviewers"]} == {r1.id}

    # r2 is no longer assigned and cannot decide.
    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(r2),
    )
    assert resp.json()["success"] is False


def test_batch_revise_rejected_after_resolved():
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)
    batch_id = _submit_batch(creator, [reviewer], combos).json()["data"]["id"]

    client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer),
    )

    resp = client.post(
        f"/api/approval-batches/{batch_id}/revise",
        json={"reviewer_ids": [reviewer.id], "versions": []},
        headers=_auth_headers(creator),
    )
    assert resp.json()["success"] is False
    assert "pending" in resp.json()["error"].lower()


def test_batch_revise_resubmits_after_needs_revision():
    """A needs-revision batch can be revised in place — it re-opens as the
    resubmit path: round bumps, version + reviewer statuses reset to pending."""
    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"])
    combos = _create_combos(2)
    batch = _submit_batch(creator, [reviewer], combos).json()["data"]
    batch_id = batch["id"]
    v0_id = batch["versions"][0]["id"]

    # Reviewer asks for changes → whole batch flips to NEEDS_REVISION.
    client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "NEEDS_REVISION", "feedback": "tighten the hook"},
        headers=_auth_headers(reviewer),
    )

    resp = client.post(
        f"/api/approval-batches/{batch_id}/revise",
        json={
            "reviewer_ids": [reviewer.id],
            "versions": [{"approval_id": v0_id, "working_file_url": "https://example.com/v2"}],
        },
        headers=_auth_headers(creator),
    )
    data = resp.json()["data"]
    assert resp.json()["success"] is True
    assert data["status"] == "PENDING_APPROVAL"  # batch re-opened
    assert data["round"] == 2
    assert all(v["status"] == "PENDING_APPROVAL" for v in data["versions"])  # verdicts cleared
    assert all(rv["status"] == "PENDING" for rv in data["reviewers"])
    v0 = next(v for v in data["versions"] if v["id"] == v0_id)
    assert v0["working_file_url"] == "https://example.com/v2"

    # Reviewer can now decide afresh on the resubmitted batch.
    resp = client.post(
        f"/api/approval-batches/{batch_id}/decide",
        json={"decision": "APPROVED"},
        headers=_auth_headers(reviewer),
    )
    assert resp.json()["success"] is True


# ── Auto-queue Figma render on full approval ─────────────────


def _seed_pending_approval(*, creator, reviewer, combo, working_file_url):
    """Create an AdCopy for the combo + a PENDING approval (one reviewer)
    carrying working_file_url. Returns approval_id."""
    from datetime import datetime, timezone

    from app.models.ad_copy import AdCopy
    from app.models.approval import ApprovalReviewer, ComboApproval

    db = TestSession()
    db.add(AdCopy(
        id=str(uuid.uuid4()),
        branch_id=combo.branch_id,
        copy_id=combo.copy_id,
        target_audience="Solo",
        headline="Stay solo, never alone",
        body_text="Shared lounge + indoor slide",
        cta="Book now",
    ))
    approval = ComboApproval(
        id=str(uuid.uuid4()),
        combo_id=combo.id,
        round=1,
        status="PENDING_APPROVAL",
        submitted_by=creator.id,
        submitted_at=datetime.now(timezone.utc),
        working_file_url=working_file_url,
    )
    db.add(approval)
    db.flush()
    db.add(ApprovalReviewer(
        id=str(uuid.uuid4()),
        approval_id=approval.id,
        reviewer_id=reviewer.id,
        status="PENDING",
    ))
    db.commit()
    approval_id = approval.id
    db.close()
    return approval_id


def test_approval_auto_queues_figma_render_when_working_file_is_figma():
    """Full approval + a Figma working file → a PENDING render job is queued
    into the frame's template, tagged with source_combo_id and filled from the
    combo's copy (cleaned to the template's declared slots)."""
    from app.models.figma import FigmaJob, FigmaTemplate
    from app.services.approval_service import record_decision

    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"], email="rev_figma@meander.com")
    combo = _create_combo()

    db = TestSession()
    tpl = FigmaTemplate(
        id=str(uuid.uuid4()),
        name="Hero Square",
        file_key="ABC123",
        node_id="143:22",
        branch_id=combo.branch_id,
        platform="meta",
        placeholder_schema={"headline": {"type": "text"}, "cta": {"type": "text"}},
        is_active=True,
    )
    db.add(tpl)
    db.commit()
    tpl_id = tpl.id
    db.close()

    approval_id = _seed_pending_approval(
        creator=creator, reviewer=reviewer, combo=combo,
        # node-id uses a dash in the URL; parse_figma_url converts it to a colon
        working_file_url="https://www.figma.com/design/ABC123/Hero?node-id=143-22",
    )

    db = TestSession()
    record_decision(db, approval_id, reviewer.id, "APPROVED")
    db.close()

    db = TestSession()
    jobs = db.query(FigmaJob).filter(FigmaJob.source_combo_id == combo.combo_id).all()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.template_id == tpl_id
    assert job.status == "PENDING"
    assert job.request_payload.get("headline") == "Stay solo, never alone"
    assert job.request_payload.get("cta") == "Book now"
    # subhead/body/hook are not declared slots on this template → dropped
    assert "subhead" not in job.request_payload
    db.close()


def test_approval_no_render_when_working_file_not_figma():
    """A non-Figma working file (e.g. Canva) must not queue any render job."""
    from app.models.figma import FigmaJob
    from app.services.approval_service import record_decision

    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"], email="rev_canva@meander.com")
    combo = _create_combo()

    approval_id = _seed_pending_approval(
        creator=creator, reviewer=reviewer, combo=combo,
        working_file_url="https://canva.com/design/test",
    )

    db = TestSession()
    record_decision(db, approval_id, reviewer.id, "APPROVED")
    db.close()

    db = TestSession()
    assert db.query(FigmaJob).count() == 0
    db.close()


def test_approval_no_render_when_figma_url_has_no_registered_template():
    """A Figma working file with no matching active template → skip silently
    (strict: no branch-template fallback)."""
    from app.models.figma import FigmaJob
    from app.services.approval_service import record_decision

    creator = _create_user(["creator"])
    reviewer = _create_user(["reviewer"], email="rev_notpl@meander.com")
    combo = _create_combo()

    approval_id = _seed_pending_approval(
        creator=creator, reviewer=reviewer, combo=combo,
        working_file_url="https://www.figma.com/design/NOPE999/X?node-id=1-1",
    )

    db = TestSession()
    record_decision(db, approval_id, reviewer.id, "APPROVED")
    db.close()

    db = TestSession()
    assert db.query(FigmaJob).count() == 0
    db.close()
