"""Tests for embedding_service.

The Voyage call is mocked so tests stay offline. Coverage focuses on:
  - text composition (combo / copy / material)
  - SQLite no-op write path (vector skipped, bookkeeping updated)
  - batch picker semantics (NULL + model-mismatch only)
  - vector_literal formatting matches pgvector's '[a,b,...]' shape
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.creative_visual_tag import CreativeVisualTag
from app.services.embedding_service import (
    _vector_literal,
    compose_combo_text,
    compose_copy_text,
    compose_material_text,
    embed_pending,
)


engine = create_engine(
    "sqlite:///test_embedding.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def voyage_key():
    """Force a non-empty key so the embed_pending() guard doesn't short-circuit
    before reaching the mocked client."""
    original = settings.VOYAGE_API_KEY
    settings.VOYAGE_API_KEY = "test-key"
    yield
    settings.VOYAGE_API_KEY = original


def _fake_voyage(dim: int = 1024):
    """A stand-in for voyageai.Client whose .embed returns deterministic vectors."""
    class _Resp:
        embeddings: list[list[float]] = []

    class _Client:
        def __init__(self):
            self.calls = []

        def embed(self, texts, model, input_type):
            self.calls.append({"texts": list(texts), "model": model, "input_type": input_type})
            r = _Resp()
            r.embeddings = [[0.001 * i + 0.0001] * dim for i, _ in enumerate(texts, start=1)]
            return r

    return _Client()


def _seed():
    """One branch + one each of copy/material/combo. Returns the combo."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon",
        currency="VND",
    )
    db.add(account)
    db.flush()

    copy = AdCopy(
        copy_id="CPY-100",
        branch_id=account.id,
        target_audience="Couple",
        headline="Sea-view stay 30% off",
        body_text="Three nights, breakfast, sunset deck.",
        cta="Book Direct",
        language="en",
    )
    material = AdMaterial(
        branch_id=account.id,
        material_id="MAT-100",
        material_type="image",
        file_url="https://x/100.jpg",
        description="Couple sunset deck",
        target_audience="Couple",
        url_source="auto",
    )
    db.add_all([copy, material])
    db.flush()

    db.add(CreativeVisualTag(
        material_id="MAT-100",
        tag_category="emotional_angle",
        tag_value="aspirational",
        confidence=0.9,
    ))
    db.add(CreativeVisualTag(
        material_id="MAT-100",
        tag_category="scene_type",
        tag_value="exterior",
        confidence=0.85,
    ))

    combo = AdCombo(
        id=str(uuid.uuid4()),
        combo_id="CMB-100",
        branch_id=account.id,
        ad_name="Couple Sunset",
        target_audience="Couple",
        country="VN",
        copy_id="CPY-100",
        material_id="MAT-100",
        verdict="WIN",
    )
    db.add(combo)
    db.commit()
    db.close()
    return combo


# ── Vector literal formatting ────────────────────────────────


def test_vector_literal_matches_pgvector_format():
    assert _vector_literal([0.1, 0.2, 0.3]) == "[0.100000,0.200000,0.300000]"
    assert _vector_literal([1.0]) == "[1.000000]"


# ── Text composition ─────────────────────────────────────────


def test_compose_copy_text_includes_required_fields():
    db = TestSession()
    _seed()
    copy = db.query(AdCopy).filter(AdCopy.copy_id == "CPY-100").first()
    text = compose_copy_text(copy)
    assert "Headline:" in text
    assert "Sea-view stay 30% off" in text
    assert "CTA: Book Direct" in text
    assert "Audience: Couple" in text
    db.close()


def test_compose_material_text_lists_visual_tags():
    db = TestSession()
    _seed()
    material = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-100").first()
    tags = db.query(CreativeVisualTag).filter(
        CreativeVisualTag.material_id == "MAT-100"
    ).all()
    text = compose_material_text(material, tags)
    assert "Type: image" in text
    assert "emotional_angle=aspirational" in text
    assert "scene_type=exterior" in text
    db.close()


def test_compose_combo_text_combines_everything():
    db = TestSession()
    _seed()
    combo = db.query(AdCombo).filter(AdCombo.combo_id == "CMB-100").first()
    copy = db.query(AdCopy).filter(AdCopy.copy_id == "CPY-100").first()
    material = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-100").first()
    tags = db.query(CreativeVisualTag).filter(
        CreativeVisualTag.material_id == "MAT-100"
    ).all()
    text = compose_combo_text(combo, copy, material, tags, angle=None, keypoints=[])
    assert "Ad: Couple Sunset" in text
    assert "Verdict: WIN" in text
    assert "Sea-view stay 30% off" in text
    assert "scene_type=exterior" in text
    db.close()


# ── Batch picker on SQLite (no vector column, but bookkeeping flips) ──


def test_embed_pending_marks_rows_on_sqlite():
    """SQLite can't store the vector but should still flip embedded_at +
    embedding_model so the next tick doesn't re-embed the same rows."""
    _seed()
    db = TestSession()
    fake = _fake_voyage()
    counts = embed_pending(db, limit_per_table=10, client=fake)

    assert counts["ad_combos"] == 1
    assert counts["ad_copies"] == 1
    assert counts["ad_materials"] == 1

    db2 = TestSession()
    combo = db2.query(AdCombo).filter(AdCombo.combo_id == "CMB-100").first()
    copy = db2.query(AdCopy).filter(AdCopy.copy_id == "CPY-100").first()
    material = db2.query(AdMaterial).filter(AdMaterial.material_id == "MAT-100").first()

    assert combo.embedded_at is not None
    assert copy.embedded_at is not None
    assert material.embedded_at is not None
    assert combo.embedding_model == settings.VOYAGE_EMBED_MODEL

    # Second tick should be a no-op (every row already has the current model)
    counts2 = embed_pending(db2, limit_per_table=10, client=fake)
    assert counts2 == {"ad_combos": 0, "ad_copies": 0, "ad_materials": 0}
    db2.close()
    db.close()


def test_embed_pending_re_embeds_on_model_change():
    _seed()
    db = TestSession()
    fake = _fake_voyage()
    embed_pending(db, limit_per_table=10, client=fake)

    # Pretend the deployed model upgraded — rows still pinned to old model
    # should be re-embedded.
    db2 = TestSession()
    db2.execute(
        AdCombo.__table__.update().values(embedding_model="voyage-3"),
    )
    db2.commit()
    counts = embed_pending(db2, limit_per_table=10, client=fake)
    assert counts["ad_combos"] == 1
    db2.close()
    db.close()


def test_embed_pending_returns_error_when_no_key():
    _seed()
    settings.VOYAGE_API_KEY = ""
    db = TestSession()
    counts = embed_pending(db, limit_per_table=10)
    assert counts["error"].startswith("VOYAGE_API_KEY")
    db.close()
