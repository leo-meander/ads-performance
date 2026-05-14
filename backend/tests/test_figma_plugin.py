"""Tests for the plugin-facing Figma endpoints (X-API-Key auth).

The Figma plugin can't carry the app's auth cookie, so these endpoints use the
export-API key mechanism. Coverage:
  - GET /figma/plugin/jobs returns pending jobs joined with template coords
  - missing / invalid key is rejected
  - complete + fail transition the job
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.api_key import ApiKey
from app.models.base import Base
from app.models.figma import FigmaJob, FigmaTemplate


engine = create_engine(
    "sqlite:///test_figma_plugin.db",
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

PLUGIN_KEY = "test-plugin-key-abcdef0123456789"
PLUGIN_KEY_HEADER = {"X-API-Key": PLUGIN_KEY}


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _seed():
    """API key + branch + template + one PENDING job. Returns the job id."""
    db = TestSession()
    db.add(ApiKey(
        name="Figma plugin",
        key_hash=hashlib.sha256(PLUGIN_KEY.encode()).hexdigest(),
        key_prefix=PLUGIN_KEY[:8],
        is_active=True,
    ))
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()

    tpl = FigmaTemplate(
        name="Hero Square", file_key="FILE123", node_id="4:52",
        branch_id=account.id, platform="meta", width=1080, height=1080,
        placeholder_schema={"headline": {"type": "text"}, "hero_image": {"type": "image"}},
        is_active=True,
    )
    db.add(tpl)
    db.flush()

    job = FigmaJob(
        template_id=tpl.id,
        request_payload={"headline": "Stay 2 nights, save 20%"},
        status="PENDING",
        requested_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    return job_id


# ── auth ─────────────────────────────────────────────────────


def test_plugin_jobs_requires_api_key():
    _seed()
    resp = client.get("/api/figma/plugin/jobs")
    # Missing required X-API-Key header → FastAPI 422
    assert resp.status_code == 422


def test_plugin_jobs_rejects_bad_key():
    _seed()
    resp = client.get("/api/figma/plugin/jobs", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


# ── list ─────────────────────────────────────────────────────


def test_plugin_jobs_returns_job_with_template_coords():
    job_id = _seed()
    resp = client.get("/api/figma/plugin/jobs", headers=PLUGIN_KEY_HEADER)
    body = resp.json()
    assert body["success"], body
    items = body["data"]["items"]
    assert len(items) == 1
    j = items[0]
    assert j["job_id"] == job_id
    assert j["request_payload"]["headline"] == "Stay 2 nights, save 20%"
    assert j["template"]["file_key"] == "FILE123"
    assert j["template"]["node_id"] == "4:52"
    assert "headline" in j["template"]["placeholder_schema"]


# ── complete / fail ──────────────────────────────────────────


def test_plugin_complete_job():
    job_id = _seed()
    resp = client.post(
        f"/api/figma/plugin/jobs/{job_id}/complete",
        json={"output_image_url": "https://figma-cdn/out.png"},
        headers=PLUGIN_KEY_HEADER,
    )
    body = resp.json()
    assert body["success"], body
    assert body["data"]["status"] == "COMPLETED"
    assert body["data"]["output_image_url"] == "https://figma-cdn/out.png"

    # No longer pending → not in the plugin queue
    resp2 = client.get("/api/figma/plugin/jobs", headers=PLUGIN_KEY_HEADER)
    assert resp2.json()["data"]["items"] == []


def test_plugin_fail_job():
    job_id = _seed()
    resp = client.post(
        f"/api/figma/plugin/jobs/{job_id}/fail",
        json={"error": "Master frame 4:52 not found in the open file"},
        headers=PLUGIN_KEY_HEADER,
    )
    body = resp.json()
    assert body["success"], body
    assert body["data"]["status"] == "FAILED"
    assert "not found" in body["data"]["error"]


def test_plugin_complete_unknown_job():
    _seed()
    resp = client.post(
        "/api/figma/plugin/jobs/nope/complete",
        json={},
        headers=PLUGIN_KEY_HEADER,
    )
    body = resp.json()
    assert body["success"] is False
    assert "not found" in body["error"].lower()
