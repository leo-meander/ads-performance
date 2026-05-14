"""Tests for figma_service + figma_client (stub mode).

The Figma client runs in stub mode by default (no FIGMA_ACCESS_TOKEN), so
tests don't hit the real API. Coverage:
  - text-layer collection from a stub frame
  - template registration auto-infers placeholder_schema from text layers
  - job creation builds a deep-link
  - poll_pending_jobs flips PENDING → COMPLETED with an image URL
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table on Base.metadata before create_all
from app.config import settings
from app.models.account import AdAccount
from app.models.base import Base
from app.models.figma import FigmaJob, FigmaTemplate
from app.services.figma_client import FigmaClient, _collect_text_layers, _stub_node
from app.services.figma_service import (
    FigmaServiceError,
    create_job,
    create_template,
    poll_pending_jobs,
    refresh_template_preview,
    update_template,
)


engine = create_engine(
    "sqlite:///test_figma.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def force_stub():
    """Empty FIGMA_ACCESS_TOKEN forces FigmaClient into stub mode."""
    original = settings.FIGMA_ACCESS_TOKEN
    settings.FIGMA_ACCESS_TOKEN = ""
    yield
    settings.FIGMA_ACCESS_TOKEN = original


def _seed_branch():
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Test",
        currency="VND",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    db.close()
    return account


# ── figma_client ─────────────────────────────────────────────


def test_collect_text_layers_walks_children():
    node = _stub_node("2:1")
    out: list = []
    _collect_text_layers(node, [], out)
    names = {l.name for l in out}
    assert {"headline", "subhead", "cta"} == names


def test_get_text_layers_in_stub_mode():
    client = FigmaClient()
    assert client.is_stub
    layers = client.get_text_layers("AnyFile", "2:1")
    assert len(layers) == 3
    assert {l.characters for l in layers} == {"Stub Headline", "Stub subhead text.", "Book Now"}


def test_export_images_in_stub_mode_returns_deterministic_urls():
    client = FigmaClient()
    exports = client.export_images("FILE", ["2:1"], fmt="png")
    assert len(exports) == 1
    assert exports[0].image_url == "https://figma-stub.example/FILE/2:1.png"


# ── figma_service: templates ─────────────────────────────────


def test_create_template_auto_infers_placeholders():
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db,
        name="Meta Square Hero",
        file_key="FILE123",
        node_id="2:1",
        branch_id=branch.id,
        platform="meta",
    )
    db.close()
    assert set(tpl.placeholder_schema.keys()) == {"headline", "subhead", "cta"}
    # Slot defaults capture the current copy from the master frame
    assert tpl.placeholder_schema["headline"]["current"] == "Stub Headline"


def test_create_template_validates_required_fields():
    branch = _seed_branch()
    db = TestSession()
    with pytest.raises(FigmaServiceError, match="name"):
        create_template(db, name="  ", file_key="FILE", node_id="2:1", branch_id=branch.id)
    with pytest.raises(FigmaServiceError, match="file_key"):
        create_template(db, name="Foo", file_key="", node_id="", branch_id=branch.id)
    db.close()


def test_update_template_replaces_noisy_schema():
    """The common fix path: auto-inferred schema is noisy (layers named after
    their content), designer PATCHes in an explicit slug mapping."""
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db, name="Hero", file_key="FILE", node_id="2:1", branch_id=branch.id,
    )
    # Auto-inferred from stub = headline/subhead/cta (stub frame is clean), but
    # imagine it was noisy — replace with an explicit mapping.
    explicit = {
        "headline": {"type": "text", "figma_layer": "THE MOST FUN HOSTEL"},
        "cta": {"type": "text", "figma_layer": "BOOK NOW"},
    }
    updated = update_template(db, tpl.id, placeholder_schema=explicit, name="Hero v2")
    assert updated.name == "Hero v2"
    assert set(updated.placeholder_schema.keys()) == {"headline", "cta"}
    assert updated.placeholder_schema["cta"]["figma_layer"] == "BOOK NOW"
    db.close()


def test_update_template_soft_delete():
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db, name="Hero", file_key="FILE", node_id="2:1", branch_id=branch.id,
    )
    updated = update_template(db, tpl.id, is_active=False)
    assert updated.is_active is False
    db.close()


def test_update_template_rejects_unknown_id():
    db = TestSession()
    with pytest.raises(FigmaServiceError, match="not found"):
        update_template(db, "no-such-id", name="x")
    db.close()


def test_refresh_template_preview_writes_url():
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db, name="Hero", file_key="FILE", node_id="2:1", branch_id=branch.id,
    )
    url = refresh_template_preview(db, tpl)
    assert url == "https://figma-stub.example/FILE/2:1.png"
    db.close()


# ── figma_service: jobs ──────────────────────────────────────


def test_create_job_filters_unknown_placeholders():
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db, name="Hero", file_key="FILE", node_id="2:1", branch_id=branch.id,
    )
    job = create_job(
        db,
        template_id=tpl.id,
        request_payload={
            "headline": "Stay 3 nights, save 25%",
            "cta": "Reserve Now",
            "extra_unknown_field": "should be dropped",
        },
    )
    assert "extra_unknown_field" not in job.request_payload
    assert job.request_payload["headline"] == "Stay 3 nights, save 25%"
    assert job.status == "PENDING"
    assert "figma.com/file/FILE" in job.output_figma_url
    db.close()


def test_create_job_rejects_inactive_template():
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db, name="Hero", file_key="FILE", node_id="2:1", branch_id=branch.id,
    )
    tpl.is_active = False
    db.commit()
    with pytest.raises(FigmaServiceError, match="inactive"):
        create_job(db, template_id=tpl.id, request_payload={"headline": "x"})
    db.close()


def test_poll_pending_jobs_completes_and_attaches_image():
    branch = _seed_branch()
    db = TestSession()
    tpl = create_template(
        db, name="Hero", file_key="FILE", node_id="2:1", branch_id=branch.id,
    )
    job = create_job(db, template_id=tpl.id, request_payload={"headline": "x"})
    job_id = job.id

    counts = poll_pending_jobs(db)
    assert counts == {"polled": 1, "completed": 1, "failed": 0}

    refreshed = db.query(FigmaJob).filter(FigmaJob.id == job_id).first()
    assert refreshed.status == "COMPLETED"
    assert refreshed.output_image_url == "https://figma-stub.example/FILE/2:1.png"
    db.close()
