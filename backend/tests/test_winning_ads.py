"""Tests for the winning-ads regenerate flow.

Covers:
  - canva_link_capture URL detection + persistence on APPROVED
  - winning_ads_service list/detail filtering on verdict=WIN + canva_url
  - regenerate_service happy path in Canva stub mode
  - regenerate_service rejects materials without is_template_ready
"""
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
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.approval import ComboApproval
from app.models.base import Base
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services.auth_service import create_access_token, hash_password
from app.services.canva_link_capture import (
    capture_canva_link_from_approval,
    extract_canva_design_id,
)
from app.services.regenerate_service import RegenerateError, regenerate_winning_ad


engine = create_engine("sqlite:///test_winning_ads.db", connect_args={"check_same_thread": False})
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
    with patch("app.services.approval_service._queue_emails"):
        yield


# ── Fixtures ──────────────────────────────────────────────────


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


def _editor_for_saigon():
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=f"u_{uuid.uuid4().hex[:6]}@meander.com",
        full_name="Editor",
        password_hash=hash_password("pw"),
        roles=["creator"],
    )
    db.add(user)
    db.flush()
    db.add(UserPermission(
        user_id=user.id, branch="Saigon", section="meta_ads", level="edit",
    ))
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _seed_winning_ad(*, with_canva: bool = True, template_ready: bool = False):
    """Create branch + copy + material + WIN combo. Returns (account, material, combo)."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Saigon",
        currency="VND",
    )
    db.add(account)
    db.flush()

    copy = AdCopy(
        copy_id="CPY-W01",
        branch_id=account.id,
        target_audience="Couple",
        headline="Stay 2 nights, save 20%",
        body_text="Romantic getaway awaits.",
        cta="Book Now",
        language="en",
    )
    db.add(copy)

    material = AdMaterial(
        branch_id=account.id,
        material_id="MAT-W01",
        material_type="image",
        file_url="https://drive.example/img.jpg",
        canva_url="https://www.canva.com/design/DAFwinning001/edit" if with_canva else None,
        canva_design_id="DAFwinning001" if with_canva else None,
        canva_template_id="DAFtemplate999" if template_ready else None,
        is_template_ready=template_ready,
        canva_placeholder_schema=({"headline": "main", "cta": "button"} if template_ready else None),
    )
    db.add(material)

    combo = AdCombo(
        id=str(uuid.uuid4()),
        combo_id="CMB-W01",
        branch_id=account.id,
        ad_name="Winning Ad",
        target_audience="Couple",
        country="VN",
        copy_id="CPY-W01",
        material_id="MAT-W01",
        verdict="WIN",
        roas=4.5,
        spend=1000000,
        conversions=20,
    )
    db.add(combo)
    db.commit()
    db.refresh(account)
    db.refresh(material)
    db.refresh(combo)
    db.close()
    return account, material, combo


def _auth(user):
    token = create_access_token(user.id, user.roles or [])
    return {"Authorization": f"Bearer {token}"}


# ── canva_link_capture ────────────────────────────────────────


def test_extract_canva_design_id_variants():
    assert extract_canva_design_id("https://www.canva.com/design/DAFabc123/edit") == "DAFabc123"
    assert extract_canva_design_id("https://canva.com/design/DAFxyz/view") == "DAFxyz"
    assert extract_canva_design_id("https://drive.google.com/file/abc") is None
    assert extract_canva_design_id("") is None
    assert extract_canva_design_id(None) is None


def test_capture_skips_when_material_already_has_canva():
    """First APPROVED wins — re-approving a different combo shouldn't overwrite."""
    _, material, combo = _seed_winning_ad(with_canva=True)
    db = TestSession()
    approval = ComboApproval(
        combo_id=combo.id,
        round=1,
        status="APPROVED",
        submitted_by=None,
        submitted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        working_file_url="https://www.canva.com/design/DAFnewer/edit",
    )
    db.add(approval)
    db.commit()

    result = capture_canva_link_from_approval(db, approval)
    assert result is None  # not overwritten

    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-W01").first()
    assert fresh.canva_design_id == "DAFwinning001"  # original preserved
    db.close()


def test_capture_writes_when_material_empty():
    _, material, combo = _seed_winning_ad(with_canva=False)
    db = TestSession()
    approval = ComboApproval(
        combo_id=combo.id,
        round=1,
        status="APPROVED",
        submitted_by=None,
        submitted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        working_file_url="https://www.canva.com/design/DAFfresh/edit",
    )
    db.add(approval)
    db.commit()

    updated = capture_canva_link_from_approval(db, approval)
    assert updated is not None
    assert updated.canva_design_id == "DAFfresh"
    assert updated.canva_url == "https://www.canva.com/design/DAFfresh/edit"
    assert updated.canva_source_approval_id == approval.id
    db.commit()
    db.close()


def test_capture_ignores_non_canva_url():
    _, material, combo = _seed_winning_ad(with_canva=False)
    db = TestSession()
    approval = ComboApproval(
        combo_id=combo.id,
        round=1,
        status="APPROVED",
        submitted_by=None,
        submitted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        working_file_url="https://drive.google.com/some/file",
    )
    db.add(approval)
    db.commit()
    assert capture_canva_link_from_approval(db, approval) is None
    db.close()


# ── winning_ads_service / endpoint ────────────────────────────


def test_list_winning_ads_excludes_materials_without_canva():
    _, material_with, _ = _seed_winning_ad(with_canva=True)
    # add a second material without canva — should NOT appear in list
    db = TestSession()
    account_id = material_with.branch_id
    db.add(AdCopy(
        copy_id="CPY-W02", branch_id=account_id, target_audience="Solo",
        headline="x", body_text="x", language="en",
    ))
    db.add(AdMaterial(
        branch_id=account_id, material_id="MAT-W02",
        material_type="image", file_url="https://drive/x.jpg",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-W02", branch_id=account_id,
        ad_name="No-canva winner", copy_id="CPY-W02", material_id="MAT-W02",
        verdict="WIN", roas=3.0, spend=500000, conversions=10,
    ))
    db.commit()
    db.close()

    admin = _admin()
    resp = client.get("/api/winning-ads", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    items = body["data"]["items"]
    combo_ids = {x["combo_id"] for x in items}
    assert "CMB-W01" in combo_ids
    assert "CMB-W02" not in combo_ids


def test_winning_ad_detail_includes_template_config():
    _seed_winning_ad(with_canva=True, template_ready=True)
    admin = _admin()
    resp = client.get("/api/winning-ads/MAT-W01", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    assert body["data"]["is_template_ready"] is True
    assert body["data"]["canva_template_id"] == "DAFtemplate999"
    assert body["data"]["regenerations"] == []


# ── regenerate_service ────────────────────────────────────────


def test_regenerate_requires_template_ready():
    _seed_winning_ad(with_canva=True, template_ready=False)
    db = TestSession()
    with pytest.raises(RegenerateError, match="brand template"):
        regenerate_winning_ad(
            db,
            material_id="MAT-W01",
            comment="couples package, sea-view bg",
        )
    db.close()


def test_regenerate_requires_comment():
    _seed_winning_ad(with_canva=True, template_ready=True)
    db = TestSession()
    with pytest.raises(RegenerateError, match="Comment"):
        regenerate_winning_ad(db, material_id="MAT-W01", comment="   ")
    db.close()


def test_regenerate_stub_happy_path_seeds_from_copy():
    _seed_winning_ad(with_canva=True, template_ready=True)
    db = TestSession()
    result = regenerate_winning_ad(
        db,
        material_id="MAT-W01",
        comment="couples package",
        overrides={"cta": "Reserve Now"},
    )
    assert result["status"] == "COMPLETED"
    assert result["output_canva_url"].startswith("https://www.canva.com/design/DAFstub_")
    assert result["output_design_id"].startswith("DAFstub_")
    # Stub echoes autofill back so we can verify schema-aware merging
    echo = result["autofill_echo"]
    assert echo["headline"] == "Stay 2 nights, save 20%"  # seeded from copy
    assert echo["cta"] == "Reserve Now"  # override wins
    assert "idea" not in echo  # schema only declares headline/cta — 'idea' filtered out
    db.close()


def test_regenerate_endpoint_returns_design_url():
    _seed_winning_ad(with_canva=True, template_ready=True)
    user = _editor_for_saigon()
    resp = client.post(
        "/api/winning-ads/MAT-W01/regenerate",
        json={"comment": "Try sea-view background"},
        headers=_auth(user),
    )
    body = resp.json()
    assert body["success"], body
    assert body["data"]["status"] == "COMPLETED"
    assert body["data"]["output_canva_url"].startswith("https://www.canva.com/design/DAFstub_")
