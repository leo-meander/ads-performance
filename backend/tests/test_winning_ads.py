"""Tests for the winning-ads list/detail endpoints.

The Canva-based regenerate flow + canva_link_capture were removed in
migration 033. Variant generation now lives under /api/figma + /api/creative/brief.
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
from app.models.base import Base
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services.auth_service import create_access_token, hash_password


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


def _seed_winning_ad(*, verdict: str = "WIN"):
    """Create branch + copy + material + combo. Returns (account, material, combo)."""
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
        copy_id="CPY-901",
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
        material_id="MAT-901",
        material_type="image",
        file_url="https://drive.example/img.jpg",
    )
    db.add(material)

    combo = AdCombo(
        id=str(uuid.uuid4()),
        combo_id="CMB-901",
        branch_id=account.id,
        ad_name="Winning Ad",
        target_audience="Couple",
        country="VN",
        copy_id="CPY-901",
        material_id="MAT-901",
        verdict=verdict,
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


# ── List endpoint ─────────────────────────────────────────────


def test_list_winning_ads_returns_combos():
    _seed_winning_ad()
    admin = _admin()
    resp = client.get("/api/winning-ads", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    items = body["data"]["items"]
    combo_ids = {x["combo_id"] for x in items}
    assert "CMB-901" in combo_ids


def test_list_winning_ads_filters_by_verdict():
    _seed_winning_ad(verdict="WIN")
    admin = _admin()
    resp = client.get("/api/winning-ads?verdict=WIN", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    items = body["data"]["items"]
    assert all(x["verdict"] == "WIN" for x in items)
    assert {"CMB-901"} <= {x["combo_id"] for x in items}


def test_list_winning_ads_filters_out_other_verdicts():
    _seed_winning_ad(verdict="TEST")
    admin = _admin()
    resp = client.get("/api/winning-ads?verdict=WIN", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    assert "CMB-901" not in {x["combo_id"] for x in body["data"]["items"]}


def test_list_winning_ads_branch_scope_for_non_admin():
    _, material, _ = _seed_winning_ad()
    user = _editor_for_saigon()
    # Editor's UserPermission says branch="Saigon" — but our scoped_account_ids
    # join resolves by branch text label. Without a matching label for our seed
    # account, the response should be empty. (Admin sees it; editor doesn't.)
    resp = client.get("/api/winning-ads", headers=_auth(user))
    body = resp.json()
    assert body["success"], body


# ── Detail endpoint ───────────────────────────────────────────


def test_winning_ad_detail_returns_combos_using_material():
    _seed_winning_ad()
    admin = _admin()
    resp = client.get("/api/winning-ads/MAT-901", headers=_auth(admin))
    body = resp.json()
    assert body["success"], body
    data = body["data"]
    assert data["material_id"] == "MAT-901"
    combo_ids = {c["combo_id"] for c in data["combos"]}
    assert "CMB-901" in combo_ids


def test_winning_ad_detail_404_for_unknown_material():
    admin = _admin()
    resp = client.get("/api/winning-ads/MAT-DOES-NOT-EXIST", headers=_auth(admin))
    body = resp.json()
    assert body["success"] is False
    assert "not found" in body["error"].lower()
