"""Tests for the combo detail drawer endpoint + list enrichment + why.

Covers:
  - /api/combos list now carries material_type + material_url
  - /api/creative/combos/{id}/detail bundles copy + material + tags + insight
  - the heuristic insight emits a positive ROAS reason when ROAS beats the
    branch benchmark
  - /api/creative/combos/{id}/why delegates to the AI service (mocked)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
from app.models.approval import ComboApproval
from app.models.base import Base
from app.models.creative_visual_tag import CreativeVisualTag
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password


engine = create_engine(
    "sqlite:///test_creative_detail.db",
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
    """One branch, two video combos:
      CMB-WIN → ROAS 5.0 (beats benchmark), MAT-WIN tagged
      CMB-LOSE → ROAS 0.5 (drags benchmark down)
    Benchmark = Σrevenue/Σspend = (5,000,000 + 500,000) / (1,000,000 + 1,000,000) = 2.75
    """
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()

    db.add(AdCopy(
        copy_id="CPY-WIN", branch_id=account.id, target_audience="Couple",
        headline="Slow mornings in District 1", body_text="Stay where it all happens.",
        cta="Book Now", language="en",
    ))
    db.add(AdMaterial(
        branch_id=account.id, material_id="MAT-WIN",
        material_type="video", file_url="https://x/win.mp4", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-WIN", branch_id=account.id,
        ad_name="Winner Ad", target_audience="Couple", country="VN",
        copy_id="CPY-WIN", material_id="MAT-WIN", verdict="WIN",
        roas=5.0, spend=1000000, revenue=5000000, conversions=15,
        ctr=0.03, hook_rate=0.5, thruplay_rate=0.3,
    ))
    db.add(CreativeVisualTag(
        material_id="MAT-WIN", tag_category="emotional_angle",
        tag_value="aspirational", confidence=0.9,
    ))

    db.add(AdMaterial(
        branch_id=account.id, material_id="MAT-LOSE",
        material_type="image", file_url="https://x/lose.jpg", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-LOSE", branch_id=account.id,
        ad_name="Loser Ad", target_audience="Couple", country="VN",
        copy_id="CPY-WIN", material_id="MAT-LOSE", verdict="LOSE",
        roas=0.5, spend=1000000, revenue=500000, conversions=1, ctr=0.005,
    ))
    db.commit()
    db.close()


def test_combos_list_carries_material_format():
    _seed()
    admin = _admin()
    resp = client.get("/api/combos?limit=50", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    by_id = {x["combo_id"]: x for x in body["data"]["items"]}
    assert by_id["CMB-WIN"]["material_type"] == "video"
    assert by_id["CMB-WIN"]["material_url"] == "https://x/win.mp4"
    assert by_id["CMB-LOSE"]["material_type"] == "image"


def test_detail_bundles_copy_material_tags_insight():
    _seed()
    admin = _admin()
    resp = client.get("/api/creative/combos/CMB-WIN/detail", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    d = body["data"]
    assert d["copy"]["headline"] == "Slow mornings in District 1"
    assert d["material"]["material_type"] == "video"
    assert "emotional_angle" in d["material"]["tags"]
    # benchmark = 2.75; CMB-WIN ROAS 5.0 beats it → positive ROAS reason present
    roas_reasons = [r for r in d["insight"]["reasons"] if r["key"] == "roas"]
    assert roas_reasons and roas_reasons[0]["sentiment"] == "positive"
    assert d["insight"]["positive"] >= 1


def test_detail_loser_flags_negative_roas():
    _seed()
    admin = _admin()
    resp = client.get("/api/creative/combos/CMB-LOSE/detail", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    roas_reasons = [r for r in body["data"]["insight"]["reasons"] if r["key"] == "roas"]
    assert roas_reasons and roas_reasons[0]["sentiment"] == "negative"


def test_detail_working_file_null_without_approval():
    _seed()
    admin = _admin()
    resp = client.get("/api/creative/combos/CMB-WIN/detail", headers=_auth(admin))
    assert resp.json()["data"]["working_file"] is None


def test_detail_surfaces_latest_working_file_from_approval():
    _seed()
    admin = _admin()
    db = TestSession()
    combo = db.query(AdCombo).filter(AdCombo.combo_id == "CMB-WIN").first()
    # Two approval rounds — the most recent working file should win.
    db.add(ComboApproval(
        id=str(uuid.uuid4()), combo_id=combo.id, round=1,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        working_file_url="https://drive.google.com/old", working_file_label="v1",
    ))
    db.add(ComboApproval(
        id=str(uuid.uuid4()), combo_id=combo.id, round=2,
        submitted_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        working_file_url="https://drive.google.com/new", working_file_label="v2",
    ))
    db.commit()
    db.close()

    resp = client.get("/api/creative/combos/CMB-WIN/detail", headers=_auth(admin))
    wf = resp.json()["data"]["working_file"]
    assert wf == {"url": "https://drive.google.com/new", "label": "v2"}


def test_detail_unknown_combo_errors():
    _seed()
    admin = _admin()
    resp = client.get("/api/creative/combos/CMB-NOPE/detail", headers=_auth(admin))
    body = resp.json()
    assert not body["success"]
    assert "not found" in (body["error"] or "").lower()


def test_why_delegates_to_service():
    _seed()
    admin = _admin()
    with patch(
        "app.services.creative_why_service.analyze_why",
        return_value={"combo_id": "CMB-WIN", "analysis": "It won on hook.", "model": "x"},
    ):
        resp = client.post("/api/creative/combos/CMB-WIN/why", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    assert body["data"]["analysis"] == "It won on hook."
