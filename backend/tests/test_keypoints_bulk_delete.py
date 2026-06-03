"""Tests for POST /api/keypoints/bulk-delete.

Cleans up unused selling points: soft-deletes keypoints that carry no combos.
The server re-verifies usage from ad_combos.keypoint_ids and never deletes a
keypoint that is still referenced, even if the client requests it.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.keypoint import BranchKeypoint
from app.models.user import User
from app.routers.creative import KeypointBulkDelete, bulk_delete_keypoints


engine = create_engine(
    "sqlite:///test_keypoints_bulk.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _admin() -> User:
    return User(
        id=str(uuid.uuid4()), email="a@x.com", full_name="Admin",
        password_hash="x", roles=["admin"], is_active=True,
    )


def _seed():
    """One branch, two keypoints: 'used' is referenced by a combo, 'unused' is
    referenced by none."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()
    used = BranchKeypoint(branch_id=account.id, category="amenity", title="Free breakfast")
    unused = BranchKeypoint(branch_id=account.id, category="value", title="Late checkout")
    db.add_all([used, unused])
    db.commit()
    branch_id, used_id, unused_id = account.id, used.id, unused.id

    db.add(AdCopy(
        copy_id="CPY-1", branch_id=branch_id, target_audience="Solo",
        headline="h", body_text="b", cta="Book", language="en",
    ))
    db.add(AdMaterial(
        branch_id=branch_id, material_id="MAT-1", material_type="image",
        file_url="https://x/1.jpg", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-1", branch_id=branch_id,
        ad_name="Ad 1", target_audience="Solo", country="VN",
        copy_id="CPY-1", material_id="MAT-1", keypoint_ids=[used_id],
        spend=100, revenue=500, clicks=10, impressions=1000, conversions=5,
    ))
    db.commit()
    db.close()
    return branch_id, used_id, unused_id


def test_deletes_unused_keypoint():
    branch_id, used_id, unused_id = _seed()
    db = TestSession()
    resp = bulk_delete_keypoints(KeypointBulkDelete(ids=[unused_id]), current_user=_admin(), db=db)
    assert resp["success"] is True
    assert resp["data"]["deleted"] == [unused_id]
    assert resp["data"]["skipped"] == []
    kp = db.query(BranchKeypoint).filter(BranchKeypoint.id == unused_id).first()
    assert kp.is_active is False
    db.close()


def test_skips_used_keypoint_even_when_requested():
    branch_id, used_id, unused_id = _seed()
    db = TestSession()
    resp = bulk_delete_keypoints(KeypointBulkDelete(ids=[used_id]), current_user=_admin(), db=db)
    assert resp["data"]["deleted"] == []
    assert resp["data"]["skipped"] == [{"id": used_id, "reason": "in_use"}]
    kp = db.query(BranchKeypoint).filter(BranchKeypoint.id == used_id).first()
    assert kp.is_active is True  # still in use → untouched
    db.close()


def test_mixed_batch_deletes_only_unused():
    branch_id, used_id, unused_id = _seed()
    db = TestSession()
    resp = bulk_delete_keypoints(
        KeypointBulkDelete(ids=[used_id, unused_id]), current_user=_admin(), db=db
    )
    assert resp["data"]["deleted"] == [unused_id]
    assert {"id": used_id, "reason": "in_use"} in resp["data"]["skipped"]
    db.close()


def test_unknown_id_reported_not_found():
    branch_id, used_id, unused_id = _seed()
    db = TestSession()
    ghost = str(uuid.uuid4())
    resp = bulk_delete_keypoints(KeypointBulkDelete(ids=[ghost]), current_user=_admin(), db=db)
    assert resp["data"]["deleted"] == []
    assert resp["data"]["skipped"] == [{"id": ghost, "reason": "not_found"}]
    db.close()


def test_empty_ids_is_noop():
    db = TestSession()
    resp = bulk_delete_keypoints(KeypointBulkDelete(ids=[]), current_user=_admin(), db=db)
    assert resp["success"] is True
    assert resp["data"] == {"deleted": [], "skipped": []}
    db.close()
