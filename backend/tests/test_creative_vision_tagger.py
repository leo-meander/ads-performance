"""Tests for creative_vision_tagger.

Mocks the Anthropic vision call so tests stay deterministic and offline.
Covers parsing of model output, vocabulary filtering, idempotent re-tagging,
batch picker (NULL + model-mismatch), and skip rules (non-image, no URL).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.account import AdAccount
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.creative_visual_tag import CreativeVisualTag
from app.services.creative_vision_tagger import (
    VISION_MODEL,
    tag_material,
    tag_pending_materials,
)


engine = create_engine(
    "sqlite:///test_vision_tagger.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _seed_material(*, material_type: str = "image", file_url: str = "https://example/img.jpg") -> AdMaterial:
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Test",
        currency="VND",
    )
    db.add(account)
    db.flush()
    material = AdMaterial(
        branch_id=account.id,
        material_id=f"MAT-{uuid.uuid4().hex[:6].upper()}",
        material_type=material_type,
        file_url=file_url,
        url_source="auto",
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    db.close()
    return material


def _fake_client(payload: dict | str):
    """Stand-in for Anthropic client returning a single text block."""
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


# ── Parsing happy path ───────────────────────────────────────


def test_tag_material_parses_valid_json():
    material = _seed_material()
    db = TestSession()
    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == material.material_id).first()

    payload = {
        "text_density":   {"values": ["medium"], "confidence": 0.85},
        "hook_type":      {"values": ["benefit"], "confidence": 0.7},
        "cta_visible":    {"values": ["yes"], "confidence": 0.9},
        "color_palette":  {"values": ["warm"], "confidence": 0.8},
        "human_presence": {"values": ["couple"], "confidence": 0.75},
        "scene_type":     {"values": ["room", "exterior"], "confidence": 0.6},
        "emotional_angle":{"values": ["aspirational"], "confidence": 0.85},
    }
    result = tag_material(db, fresh, client=_fake_client(payload))
    db.commit()

    assert result["status"] == "ok"
    # 7 categories, scene_type has 2 values → 8 rows
    assert result["tags_written"] == 8

    rows = (
        db.query(CreativeVisualTag)
        .filter(CreativeVisualTag.material_id == fresh.material_id)
        .all()
    )
    by_cat: dict[str, set[str]] = {}
    for r in rows:
        by_cat.setdefault(r.tag_category, set()).add(r.tag_value)
    assert by_cat["scene_type"] == {"room", "exterior"}
    assert by_cat["emotional_angle"] == {"aspirational"}

    refreshed = db.query(AdMaterial).filter(AdMaterial.material_id == fresh.material_id).first()
    assert refreshed.vision_analyzed_at is not None
    assert refreshed.vision_model == VISION_MODEL
    db.close()


def test_tag_material_strips_code_fence():
    material = _seed_material()
    db = TestSession()
    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == material.material_id).first()

    fenced = "```json\n" + json.dumps({
        "text_density": {"values": ["minimal"], "confidence": 0.9},
    }) + "\n```"
    result = tag_material(db, fresh, client=_fake_client(fenced))
    db.commit()
    assert result["status"] == "ok"
    assert result["tags_written"] == 1
    db.close()


def test_tag_material_rejects_unknown_vocab():
    material = _seed_material()
    db = TestSession()
    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == material.material_id).first()

    payload = {
        # "vibrant" is not in color_palette vocab → dropped
        "color_palette": {"values": ["warm", "vibrant"], "confidence": 0.7},
    }
    result = tag_material(db, fresh, client=_fake_client(payload))
    db.commit()
    assert result["tags_written"] == 1
    rows = db.query(CreativeVisualTag).filter(
        CreativeVisualTag.material_id == fresh.material_id
    ).all()
    assert {r.tag_value for r in rows} == {"warm"}
    db.close()


def test_tag_material_invalid_json_marks_failed():
    material = _seed_material()
    db = TestSession()
    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == material.material_id).first()

    result = tag_material(db, fresh, client=_fake_client("not actually json"))
    db.commit()

    assert result["status"] == "error"
    refreshed = db.query(AdMaterial).filter(AdMaterial.material_id == fresh.material_id).first()
    assert refreshed.vision_analyzed_at is not None
    assert refreshed.vision_model.startswith("FAILED:")
    db.close()


# ── Skip rules ───────────────────────────────────────────────


def test_tag_material_skips_video():
    material = _seed_material(material_type="video")
    db = TestSession()
    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == material.material_id).first()
    result = tag_material(db, fresh, client=_fake_client({}))
    db.commit()
    assert result["status"] == "skipped"
    assert "video" in result["reason"]
    db.close()


# ── Idempotent re-tag ────────────────────────────────────────


def test_re_tag_replaces_old_tags():
    material = _seed_material()
    db = TestSession()
    fresh = db.query(AdMaterial).filter(AdMaterial.material_id == material.material_id).first()

    tag_material(db, fresh, client=_fake_client({
        "color_palette": {"values": ["warm"], "confidence": 0.8},
    }))
    db.commit()

    fresh2 = db.query(AdMaterial).filter(AdMaterial.material_id == fresh.material_id).first()
    tag_material(db, fresh2, client=_fake_client({
        "color_palette": {"values": ["cool"], "confidence": 0.9},
    }))
    db.commit()

    rows = db.query(CreativeVisualTag).filter(
        CreativeVisualTag.material_id == fresh.material_id,
        CreativeVisualTag.tag_category == "color_palette",
    ).all()
    assert {r.tag_value for r in rows} == {"cool"}  # warm dropped
    db.close()


# ── Batch picker ─────────────────────────────────────────────


def test_tag_pending_picks_null_and_model_mismatch_skips_failed():
    """tag_pending_materials should pick rows with NULL vision_analyzed_at and
    rows whose vision_model differs from VISION_MODEL — but never re-pick rows
    already marked FAILED:*.
    """
    db = TestSession()

    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Test",
        currency="VND",
    )
    db.add(account)
    db.flush()

    # NULL vision_analyzed_at — should be picked
    m1 = AdMaterial(
        branch_id=account.id, material_id="MAT-001",
        material_type="image", file_url="https://x/1.jpg", url_source="auto",
    )
    # Older model — should be re-picked
    from datetime import datetime, timezone
    m2 = AdMaterial(
        branch_id=account.id, material_id="MAT-002",
        material_type="image", file_url="https://x/2.jpg", url_source="auto",
        vision_analyzed_at=datetime.now(timezone.utc),
        vision_model="claude-sonnet-4-5",
    )
    # FAILED — should NOT be picked
    m3 = AdMaterial(
        branch_id=account.id, material_id="MAT-003",
        material_type="image", file_url="https://x/3.jpg", url_source="auto",
        vision_analyzed_at=datetime.now(timezone.utc),
        vision_model="FAILED:invalid_json",
    )
    # Already current — should NOT be picked
    m4 = AdMaterial(
        branch_id=account.id, material_id="MAT-004",
        material_type="image", file_url="https://x/4.jpg", url_source="auto",
        vision_analyzed_at=datetime.now(timezone.utc),
        vision_model=VISION_MODEL,
    )
    db.add_all([m1, m2, m3, m4])
    db.commit()

    fake_payload = {"color_palette": {"values": ["warm"], "confidence": 0.8}}
    summary = tag_pending_materials(db, limit=10, client=_fake_client(fake_payload))

    picked_ids = {r["material_id"] for r in summary["results"]}
    assert picked_ids == {"MAT-001", "MAT-002"}
    assert summary["scanned"] == 2
    assert summary["tagged"] == 2
    db.close()
