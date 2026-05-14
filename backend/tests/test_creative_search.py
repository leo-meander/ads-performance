"""Tests for the SQL tag+keyword search (no embeddings).

Covers /api/creative/search service-level behaviour:
  - tag match='all' requires every (category,value) pair
  - tag match='any' needs at least one
  - keyword ILIKE over ad_name / headline / body_text
  - /similar ranks by shared-tag overlap
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.creative_visual_tag import CreativeVisualTag
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password


engine = create_engine(
    "sqlite:///test_creative_search.db",
    connect_args={"check_same_thread": False},
)
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
        email=f"admin_{uuid.uuid4().hex[:6]}@meander.com",
        full_name="Admin",
        password_hash=hash_password("pw"),
        roles=["admin"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.roles or [])}"}


def _seed():
    """Two combos:
      CMB-A → material MAT-A: tags {emotional_angle:aspirational, scene_type:room}
      CMB-B → material MAT-B: tags {emotional_angle:aspirational, scene_type:exterior}
    """
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()

    for sfx, scene, headline in [
        ("A", "room", "Slow mornings in District 1"),
        ("B", "exterior", "Walk to everything in Saigon"),
    ]:
        db.add(AdCopy(
            copy_id=f"CPY-{sfx}", branch_id=account.id, target_audience="Couple",
            headline=headline, body_text=f"body {sfx}", cta="Book Now", language="en",
        ))
        db.add(AdMaterial(
            branch_id=account.id, material_id=f"MAT-{sfx}",
            material_type="image", file_url=f"https://x/{sfx}.jpg", url_source="auto",
        ))
        db.add(AdCombo(
            id=str(uuid.uuid4()), combo_id=f"CMB-{sfx}", branch_id=account.id,
            ad_name=f"Ad {sfx}", target_audience="Couple", country="VN",
            copy_id=f"CPY-{sfx}", material_id=f"MAT-{sfx}",
            verdict="WIN", roas=4.0, spend=1000000, conversions=15,
        ))
        db.add(CreativeVisualTag(
            material_id=f"MAT-{sfx}", tag_category="emotional_angle",
            tag_value="aspirational", confidence=0.9,
        ))
        db.add(CreativeVisualTag(
            material_id=f"MAT-{sfx}", tag_category="scene_type",
            tag_value=scene, confidence=0.85,
        ))
    db.commit()
    account_id = account.id
    db.close()
    return account_id


# ── /creative/search ─────────────────────────────────────────


def test_search_tag_match_all_requires_every_pair():
    _seed()
    admin = _admin()
    # Only CMB-A has BOTH aspirational + room
    resp = client.get(
        "/api/creative/search?tags=emotional_angle:aspirational&tags=scene_type:room&match=all",
        headers=_auth(admin),
    )
    body = resp.json()
    assert body["success"], body
    ids = {x["combo_id"] for x in body["data"]["items"]}
    assert ids == {"CMB-A"}


def test_search_tag_match_any_returns_union():
    _seed()
    admin = _admin()
    # Both combos share aspirational; room only on A → match=any returns both
    resp = client.get(
        "/api/creative/search?tags=scene_type:room&tags=scene_type:exterior&match=any",
        headers=_auth(admin),
    )
    body = resp.json()
    assert body["success"], body
    ids = {x["combo_id"] for x in body["data"]["items"]}
    assert ids == {"CMB-A", "CMB-B"}


def test_search_keyword_ilike():
    _seed()
    admin = _admin()
    resp = client.get("/api/creative/search?q=District 1", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    ids = {x["combo_id"] for x in body["data"]["items"]}
    assert ids == {"CMB-A"}  # headline "Slow mornings in District 1"


def test_search_no_match_returns_empty():
    _seed()
    admin = _admin()
    resp = client.get(
        "/api/creative/search?tags=scene_type:aerial&match=all",
        headers=_auth(admin),
    )
    body = resp.json()
    assert body["success"], body
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ── /creative/similar ────────────────────────────────────────


def test_similar_ranks_by_shared_tags():
    _seed()
    admin = _admin()
    # CMB-A shares 1 tag (aspirational) with CMB-B
    resp = client.get("/api/creative/similar/CMB-A", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    items = body["data"]["items"]
    assert len(items) == 1
    assert items[0]["combo_id"] == "CMB-B"
    assert items[0]["shared_tag_count"] == 1
    assert body["data"]["source_tag_count"] == 2


def test_similar_empty_when_no_tags():
    """A combo whose material has no visual tags → graceful empty + note."""
    account_id = _seed()
    db = TestSession()
    db.add(AdCopy(
        copy_id="CPY-C", branch_id=account_id, target_audience="Solo",
        headline="x", body_text="x", language="en",
    ))
    db.add(AdMaterial(
        branch_id=account_id, material_id="MAT-C",
        material_type="image", file_url="https://x/c.jpg", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-C", branch_id=account_id,
        ad_name="Ad C", copy_id="CPY-C", material_id="MAT-C", verdict="TEST",
    ))
    db.commit()
    db.close()

    admin = _admin()
    resp = client.get("/api/creative/similar/CMB-C", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    assert body["data"]["items"] == []
    assert "note" in body["data"]
