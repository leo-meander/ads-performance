"""Tests for creative_autoassign_service — suggest() + apply().

The Anthropic call is mocked. Coverage:
  - suggest from explicit headline/benefits + from combo copy
  - hallucinated angle_id is dropped
  - a proposed keypoint that duplicates an existing title is re-classed as matched
  - apply() creates confirmed new keypoints, dedups existing titles, stamps the combo
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.keypoint import BranchKeypoint
from app.services.creative_autoassign_service import AutoAssignError, apply, suggest


engine = create_engine(
    "sqlite:///test_autoassign.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _fake_client(payload: dict | str):
    text = payload if isinstance(payload, str) else json.dumps(payload)

    class _Block:
        type = "text"
        text = ""

    block = _Block()
    block.text = text

    class _Resp:
        content = [block]

    class _Messages:
        def create(self, **kwargs):
            return _Resp()

    return SimpleNamespace(messages=_Messages())


def _seed():
    """Branch + 2 angles + 1 existing keypoint + a combo with copy/material."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()

    db.add(AdAngle(
        angle_id="ANG-001", branch_id=None, angle_type="Offer Information Directly",
        angle_explain="State the benefit plainly", angle_text="x", target_audience="",
    ))
    db.add(AdAngle(
        angle_id="ANG-002", branch_id=None, angle_type="Stress the exclusiveness",
        angle_explain="Make it feel rare", angle_text="x", target_audience="",
    ))

    kp = BranchKeypoint(branch_id=account.id, category="amenity", title="Free breakfast")
    db.add(kp)
    db.flush()

    db.add(AdCopy(
        copy_id="CPY-1", branch_id=account.id, target_audience="Couple",
        headline="Free breakfast + walk to District 1", body_text="Stay slow.",
        cta="Book Now", language="en",
    ))
    db.add(AdMaterial(
        branch_id=account.id, material_id="MAT-1", material_type="image",
        file_url="https://x/1.jpg", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-1", branch_id=account.id,
        ad_name="Ad 1", target_audience="Couple", country="VN",
        copy_id="CPY-1", material_id="MAT-1", verdict="WIN",
    ))
    db.commit()
    branch_id = account.id
    kp_id = kp.id
    db.close()
    return branch_id, kp_id


# ── suggest ──────────────────────────────────────────────────


def test_suggest_from_explicit_text_matches_and_proposes():
    branch_id, kp_id = _seed()
    db = TestSession()
    payload = {
        "angle_id": "ANG-001",
        "angle_confidence": 0.8,
        "angle_rationale": "states the benefit directly",
        "matched_keypoint_ids": [kp_id],
        "proposed_keypoints": [
            {"title": "Walk to District 1", "category": "location", "rationale": "new — location not in list"},
        ],
    }
    result = suggest(
        db, branch_id=branch_id,
        headline="Free breakfast + walk to District 1",
        benefits=["Free breakfast", "Walk to District 1"],
        client=_fake_client(payload),
    )
    assert result["angle"]["angle_id"] == "ANG-001"
    assert result["angle"]["confidence"] == 0.8
    assert [k["id"] for k in result["keypoints"]["matched"]] == [kp_id]
    assert len(result["keypoints"]["proposed"]) == 1
    assert result["keypoints"]["proposed"][0]["title"] == "Walk to District 1"
    assert result["source"] == "explicit"
    db.close()


def test_suggest_from_combo_copy():
    branch_id, kp_id = _seed()
    db = TestSession()
    payload = {"angle_id": "ANG-002", "matched_keypoint_ids": [], "proposed_keypoints": []}
    result = suggest(db, branch_id=branch_id, combo_id="CMB-1", client=_fake_client(payload))
    assert result["source"] == "combo_copy"
    assert result["angle"]["angle_id"] == "ANG-002"
    db.close()


def test_suggest_drops_hallucinated_angle():
    branch_id, _ = _seed()
    db = TestSession()
    payload = {"angle_id": "ANG-999", "matched_keypoint_ids": [], "proposed_keypoints": []}
    result = suggest(db, branch_id=branch_id, headline="x", client=_fake_client(payload))
    assert result["angle"] is None  # ANG-999 doesn't exist → dropped
    db.close()


def test_suggest_reclasses_duplicate_proposal_as_matched():
    """If the model proposes a keypoint whose title already exists, it's moved
    to matched instead of being created as a duplicate."""
    branch_id, kp_id = _seed()
    db = TestSession()
    payload = {
        "angle_id": "ANG-001",
        "matched_keypoint_ids": [],
        # proposes "free breakfast" — already exists as "Free breakfast"
        "proposed_keypoints": [
            {"title": "free breakfast", "category": "amenity", "rationale": "x"},
        ],
    }
    result = suggest(db, branch_id=branch_id, headline="x", client=_fake_client(payload))
    assert result["keypoints"]["proposed"] == []
    assert [k["id"] for k in result["keypoints"]["matched"]] == [kp_id]
    db.close()


def test_suggest_no_source_raises():
    branch_id, _ = _seed()
    db = TestSession()
    with pytest.raises(AutoAssignError, match="No source text"):
        suggest(db, branch_id=branch_id, client=_fake_client({}))
    db.close()


# ── apply ────────────────────────────────────────────────────


def test_apply_creates_new_keypoints_and_stamps_combo():
    branch_id, kp_id = _seed()
    db = TestSession()
    result = apply(
        db,
        combo_id="CMB-1",
        angle_id="ANG-001",
        keypoint_ids=[kp_id],
        new_keypoints=[{"title": "Rooftop co-working", "category": "amenity"}],
    )
    assert result["angle_id"] == "ANG-001"
    assert len(result["created_keypoints"]) == 1
    assert kp_id in result["keypoint_ids"]
    assert len(result["keypoint_ids"]) == 2  # existing + 1 created

    db2 = TestSession()
    combo = db2.query(AdCombo).filter(AdCombo.combo_id == "CMB-1").first()
    assert combo.angle_id == "ANG-001"
    assert len(combo.keypoint_ids) == 2
    # The new keypoint is a real row on the branch
    new_kp = db2.query(BranchKeypoint).filter(
        BranchKeypoint.title == "Rooftop co-working"
    ).first()
    assert new_kp is not None and new_kp.branch_id == branch_id
    db2.close()
    db.close()


def test_apply_dedups_new_keypoint_against_existing_title():
    """A confirmed 'new' keypoint whose title already exists must reuse the
    existing row, not create a second one."""
    branch_id, kp_id = _seed()
    db = TestSession()
    result = apply(
        db,
        combo_id="CMB-1",
        keypoint_ids=[],
        new_keypoints=[{"title": "FREE BREAKFAST", "category": "amenity"}],
    )
    # No new row created — reused the existing "Free breakfast"
    assert result["created_keypoints"] == []
    assert result["keypoint_ids"] == [kp_id]

    db2 = TestSession()
    count = db2.query(BranchKeypoint).filter(
        BranchKeypoint.branch_id == branch_id
    ).count()
    assert count == 1  # still just the one
    db2.close()
    db.close()
