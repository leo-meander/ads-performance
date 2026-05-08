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
        canva_url="https://www.canva.com/design/DAFwinning001/edit" if with_canva else None,
        canva_design_id="DAFwinning001" if with_canva else None,
        canva_template_id="DAFtemplate999" if template_ready else None,
        is_template_ready=template_ready,
        canva_placeholder_schema=({"headline": "main", "cta": "button"} if template_ready else None),
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

    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-901").first()
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
        copy_id="CPY-902", branch_id=account_id, target_audience="Solo",
        headline="x", body_text="x", language="en",
    ))
    db.add(AdMaterial(
        branch_id=account_id, material_id="MAT-902",
        material_type="image", file_url="https://drive/x.jpg",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-902", branch_id=account_id,
        ad_name="No-canva winner", copy_id="CPY-902", material_id="MAT-902",
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
    assert "CMB-901" in combo_ids
    assert "CMB-902" not in combo_ids


def test_winning_ad_detail_includes_template_config():
    _seed_winning_ad(with_canva=True, template_ready=True)
    admin = _admin()
    resp = client.get("/api/winning-ads/MAT-901", headers=_auth(admin))
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
            material_id="MAT-901",
            comment="couples package, sea-view bg",
        )
    db.close()


def test_regenerate_requires_comment():
    _seed_winning_ad(with_canva=True, template_ready=True)
    db = TestSession()
    with pytest.raises(RegenerateError, match="Comment"):
        regenerate_winning_ad(db, material_id="MAT-901", comment="   ")
    db.close()


def test_regenerate_stub_happy_path_seeds_from_copy():
    _seed_winning_ad(with_canva=True, template_ready=True)
    db = TestSession()
    result = regenerate_winning_ad(
        db,
        material_id="MAT-901",
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
        "/api/winning-ads/MAT-901/regenerate",
        json={"comment": "Try sea-view background"},
        headers=_auth(user),
    )
    body = resp.json()
    assert body["success"], body
    assert body["data"]["status"] == "COMPLETED"
    assert body["data"]["output_canva_url"].startswith("https://www.canva.com/design/DAFstub_")


# ── Auto-promote to AdMaterial ───────────────────────────────


def test_completed_regen_creates_new_material_row():
    """Stub-mode regenerate completes inline and should auto-create a fresh
    ad_materials row with url_source='manual' so Meta sync won't overwrite."""
    _, source, _ = _seed_winning_ad(with_canva=True, template_ready=True)
    db = TestSession()
    result = regenerate_winning_ad(
        db,
        material_id="MAT-901",
        comment="couples package, dark background",
    )
    db.close()

    assert result["status"] == "COMPLETED"
    assert result["output_material_id"] is not None
    new_id = result["output_material_id"]

    db2 = TestSession()
    promoted = db2.query(AdMaterial).filter(AdMaterial.material_id == new_id).first()
    assert promoted is not None
    assert promoted.branch_id == source.branch_id
    assert promoted.material_type == source.material_type
    assert promoted.url_source == "manual"
    assert promoted.canva_url == result["output_canva_url"]
    assert promoted.canva_design_id == result["output_design_id"]
    assert promoted.canva_source_approval_id is None  # regen, not approval
    assert "MAT-901" in (promoted.description or "")
    db2.close()


# ── Async polling (canva-poll cron) ──────────────────────────


class _FakeCanvaClient:
    """Test double for CanvaClient that mimics the async path.

    start_autofill returns in_progress; the first get_autofill_job() call
    flips to success. Mirrors what real Canva does when the queue is busy.
    """

    is_stub = False  # bypass stub branch in regenerate_service

    def __init__(self):
        self.calls = 0

    def start_autofill(self, template_id, autofill, title=None):
        from app.services.canva_client import AutofillJob
        self.calls += 1
        return AutofillJob(
            job_id=f"job_fake_{self.calls}",
            status="in_progress",
            design=None,
            autofill_echo=autofill,
        )

    def get_autofill_job(self, job_id):
        from app.services.canva_client import AutofillJob, CanvaDesign
        design = CanvaDesign(
            design_id=f"DAFasync_{job_id}",
            edit_url=f"https://www.canva.com/design/DAFasync_{job_id}/edit",
            view_url=f"https://www.canva.com/design/DAFasync_{job_id}/view",
        )
        return AutofillJob(job_id=job_id, status="success", design=design)


def test_async_path_leaves_row_pending_then_poller_completes_it():
    from app.services.regenerate_service import poll_pending_regenerations

    _seed_winning_ad(with_canva=True, template_ready=True)
    fake = _FakeCanvaClient()

    # Step 1: regenerate returns PENDING because Canva queued the job
    db = TestSession()
    result = regenerate_winning_ad(
        db,
        material_id="MAT-901",
        comment="async test",
        canva_client=fake,
    )
    db.close()

    assert result["status"] == "PENDING"
    assert result["canva_job_id"] == "job_fake_1"
    assert result["output_material_id"] is None  # no promotion until success

    # Step 2: cron poller picks it up and completes it
    db2 = TestSession()
    counts = poll_pending_regenerations(db2, canva_client=fake)
    db2.close()

    assert counts == {"polled": 1, "completed": 1, "failed": 0, "still_pending": 0}

    # Step 3: row is now COMPLETED with a new MAT-XXX promoted
    db3 = TestSession()
    from app.models.material_regeneration import MaterialRegeneration
    row = db3.query(MaterialRegeneration).filter(
        MaterialRegeneration.canva_job_id == "job_fake_1"
    ).first()
    assert row.status == "COMPLETED"
    assert row.output_design_id == "DAFasync_job_fake_1"
    assert row.output_material_id is not None
    db3.close()


def test_canva_poll_endpoint_requires_internal_secret():
    from app.config import settings
    settings.INTERNAL_TASK_SECRET = "test-secret-poll"
    try:
        # Wrong secret → 401
        resp = client.post(
            "/api/internal/tasks/canva-poll",
            headers={"X-Internal-Secret": "wrong"},
        )
        assert resp.status_code == 401

        # Correct secret + no PENDING rows → 200 with zero counts
        resp = client.post(
            "/api/internal/tasks/canva-poll",
            headers={"X-Internal-Secret": "test-secret-poll"},
        )
        body = resp.json()
        assert resp.status_code == 200
        assert body["success"]
        assert body["data"]["polled"] == 0
    finally:
        settings.INTERNAL_TASK_SECRET = ""
