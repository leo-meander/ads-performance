"""Creative Intelligence Phase 2 — Voyage AI embeddings.

Embeds combos, copies, and materials into 1024-dim vectors stored in the
`embedding` pgvector column. The composition functions decide what text feeds
the model — combos get the most context (copy + angle + visual tags + keypoints)
because they're the primary search target; copies and materials get lighter
text so they can still be searched alone.

The pgvector column is touched via raw SQL — see _write_embedding — so the
SQLAlchemy schema stays clean (and SQLite tests don't need pgvector).

Cost envelope (voyage-3-large, $0.06/1M tokens):
  ~150 tokens/combo × 5,000 combos = $0.045 one-time backfill.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.creative_visual_tag import CreativeVisualTag
from app.models.keypoint import BranchKeypoint

logger = logging.getLogger(__name__)


# Tables that carry an `embedding` column — kept in one place so the cron
# task and the search router stay in sync.
EMBEDDABLE_TABLES = ("ad_combos", "ad_copies", "ad_materials")


# ── Voyage client ────────────────────────────────────────────


def _voyage_client():
    """Lazy-import Voyage so the module loads even when the package isn't
    installed (e.g. in CI environments that skip embedding tests)."""
    try:
        import voyageai
    except ImportError as e:
        raise RuntimeError(
            "voyageai package not installed; run `pip install voyageai`"
        ) from e
    return voyageai.Client(api_key=settings.VOYAGE_API_KEY)


def embed_text(
    text_to_embed: str,
    *,
    input_type: str = "document",
    client=None,
) -> list[float]:
    """Embed a single string. `input_type='document'` for storage, 'query' for search."""
    if not text_to_embed.strip():
        raise ValueError("Cannot embed empty text")
    if not settings.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY not configured")

    c = client or _voyage_client()
    resp = c.embed(
        [text_to_embed[:8000]],  # 8k chars ≈ 2k tokens — way under voyage-3 32k limit
        model=settings.VOYAGE_EMBED_MODEL,
        input_type=input_type,
    )
    return resp.embeddings[0]


def embed_batch(
    texts: Sequence[str],
    *,
    input_type: str = "document",
    client=None,
) -> list[list[float]]:
    """Embed a list of strings in one Voyage call (cheaper than N single calls)."""
    if not texts:
        return []
    if not settings.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY not configured")

    c = client or _voyage_client()
    resp = c.embed(
        [t[:8000] for t in texts],
        model=settings.VOYAGE_EMBED_MODEL,
        input_type=input_type,
    )
    return resp.embeddings


# ── Text composition (what we hand to the model) ─────────────


def compose_copy_text(copy: AdCopy) -> str:
    parts = [
        f"Headline: {copy.headline}",
        f"Body: {copy.body_text}",
    ]
    if copy.cta:
        parts.append(f"CTA: {copy.cta}")
    if copy.target_audience:
        parts.append(f"Audience: {copy.target_audience}")
    if copy.language and copy.language != "en":
        parts.append(f"Language: {copy.language}")
    return " | ".join(parts)


def compose_material_text(material: AdMaterial, tags: list[CreativeVisualTag]) -> str:
    parts = [f"Type: {material.material_type}"]
    if material.description:
        parts.append(f"Description: {material.description}")
    if material.target_audience:
        parts.append(f"Audience: {material.target_audience}")
    if tags:
        # Group "category:value" so the embedding picks up the structured taxonomy
        tag_str = ", ".join(
            f"{t.tag_category}={t.tag_value}" for t in sorted(tags, key=lambda x: x.tag_category)
        )
        parts.append(f"Visual: {tag_str}")
    return " | ".join(parts)


def compose_combo_text(
    combo: AdCombo,
    copy: Optional[AdCopy],
    material: Optional[AdMaterial],
    tags: list[CreativeVisualTag],
    angle: Optional[AdAngle],
    keypoints: list[BranchKeypoint],
) -> str:
    """Combos get the richest text — they're the primary semantic search target."""
    parts = []
    if combo.ad_name:
        parts.append(f"Ad: {combo.ad_name}")
    if combo.target_audience:
        parts.append(f"Audience: {combo.target_audience}")
    if combo.country:
        parts.append(f"Country: {combo.country}")
    if combo.verdict:
        parts.append(f"Verdict: {combo.verdict}")
    if angle:
        parts.append(
            f"Angle: {angle.angle_type or angle.hook or ''} — {angle.angle_explain or ''}"
        )
    if keypoints:
        kp_str = "; ".join(f"{k.category}:{k.title}" for k in keypoints)
        parts.append(f"Keypoints: {kp_str}")
    if copy:
        parts.append(compose_copy_text(copy))
    if material:
        parts.append(compose_material_text(material, tags))
    return " || ".join(parts)


# ── Embedding write (raw SQL → pgvector) ─────────────────────


def _vector_literal(vec: list[float]) -> str:
    """pgvector accepts Postgres array-style strings: '[0.1, 0.2, ...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def _write_embedding(
    db: Session,
    table: str,
    pk_col: str,
    pk_value: str,
    vec: list[float],
    model: str,
) -> None:
    """UPDATE <table> SET embedding = ..., embedded_at = NOW(), embedding_model = ...

    No-ops on SQLite (no embedding column there). Postgres path uses a parameter
    bind so the long vector literal doesn't bloat slow-query logs.
    """
    if table not in EMBEDDABLE_TABLES:
        raise ValueError(f"Refusing to write embedding to unknown table {table}")

    is_postgres = db.bind.dialect.name == "postgresql"
    now = datetime.now(timezone.utc)

    if is_postgres:
        db.execute(
            text(
                f"UPDATE {table} "
                f"SET embedding = (:vec)::vector, "
                f"    embedded_at = :now, "
                f"    embedding_model = :model "
                f"WHERE {pk_col} = :pk"
            ),
            {"vec": _vector_literal(vec), "now": now, "model": model, "pk": pk_value},
        )
    else:
        # SQLite: skip the vector but still mark the row analyzed so the
        # batch picker doesn't loop forever in tests.
        db.execute(
            text(
                f"UPDATE {table} "
                f"SET embedded_at = :now, embedding_model = :model "
                f"WHERE {pk_col} = :pk"
            ),
            {"now": now, "model": model, "pk": pk_value},
        )


# ── Batch embedders (one per table) ──────────────────────────


def _pending_combos(db: Session, model: str, limit: int) -> list[AdCombo]:
    return (
        db.query(AdCombo)
        .filter(or_(AdCombo.embedded_at.is_(None), AdCombo.embedding_model != model))
        .order_by(AdCombo.created_at.asc())
        .limit(limit)
        .all()
    )


def _pending_copies(db: Session, model: str, limit: int) -> list[AdCopy]:
    return (
        db.query(AdCopy)
        .filter(or_(AdCopy.embedded_at.is_(None), AdCopy.embedding_model != model))
        .order_by(AdCopy.created_at.asc())
        .limit(limit)
        .all()
    )


def _pending_materials(db: Session, model: str, limit: int) -> list[AdMaterial]:
    return (
        db.query(AdMaterial)
        .filter(or_(AdMaterial.embedded_at.is_(None), AdMaterial.embedding_model != model))
        .order_by(AdMaterial.created_at.asc())
        .limit(limit)
        .all()
    )


def _embed_combo_batch(db: Session, combos: list[AdCombo], model: str, client) -> int:
    if not combos:
        return 0

    # Pre-fetch related rows in bulk so we don't N+1 on the loop
    copy_ids = {c.copy_id for c in combos if c.copy_id}
    material_ids = {c.material_id for c in combos if c.material_id}
    angle_ids = {c.angle_id for c in combos if c.angle_id}
    all_kp_ids: set[str] = set()
    for c in combos:
        if isinstance(c.keypoint_ids, list):
            all_kp_ids.update(c.keypoint_ids)

    copies = {
        c.copy_id: c
        for c in db.query(AdCopy).filter(AdCopy.copy_id.in_(copy_ids)).all()
    } if copy_ids else {}
    materials = {
        m.material_id: m
        for m in db.query(AdMaterial).filter(AdMaterial.material_id.in_(material_ids)).all()
    } if material_ids else {}
    angles = {
        a.angle_id: a
        for a in db.query(AdAngle).filter(AdAngle.angle_id.in_(angle_ids)).all()
    } if angle_ids else {}
    keypoints = {
        k.id: k
        for k in db.query(BranchKeypoint).filter(BranchKeypoint.id.in_(all_kp_ids)).all()
    } if all_kp_ids else {}
    tags_by_material: dict[str, list[CreativeVisualTag]] = {}
    if material_ids:
        for t in db.query(CreativeVisualTag).filter(
            CreativeVisualTag.material_id.in_(material_ids)
        ).all():
            tags_by_material.setdefault(t.material_id, []).append(t)

    texts = []
    for c in combos:
        copy = copies.get(c.copy_id) if c.copy_id else None
        material = materials.get(c.material_id) if c.material_id else None
        angle = angles.get(c.angle_id) if c.angle_id else None
        kps = [keypoints[kid] for kid in (c.keypoint_ids or []) if kid in keypoints]
        tags = tags_by_material.get(c.material_id or "", [])
        texts.append(compose_combo_text(c, copy, material, tags, angle, kps))

    vectors = embed_batch(texts, input_type="document", client=client)
    for c, vec in zip(combos, vectors):
        _write_embedding(db, "ad_combos", "combo_id", c.combo_id, vec, model)
    return len(vectors)


def _embed_copy_batch(db: Session, copies: list[AdCopy], model: str, client) -> int:
    if not copies:
        return 0
    texts = [compose_copy_text(c) for c in copies]
    vectors = embed_batch(texts, input_type="document", client=client)
    for c, vec in zip(copies, vectors):
        _write_embedding(db, "ad_copies", "copy_id", c.copy_id, vec, model)
    return len(vectors)


def _embed_material_batch(db: Session, materials: list[AdMaterial], model: str, client) -> int:
    if not materials:
        return 0
    material_ids = {m.material_id for m in materials}
    tags_by_material: dict[str, list[CreativeVisualTag]] = {}
    for t in db.query(CreativeVisualTag).filter(
        CreativeVisualTag.material_id.in_(material_ids)
    ).all():
        tags_by_material.setdefault(t.material_id, []).append(t)

    texts = [
        compose_material_text(m, tags_by_material.get(m.material_id, [])) for m in materials
    ]
    vectors = embed_batch(texts, input_type="document", client=client)
    for m, vec in zip(materials, vectors):
        _write_embedding(db, "ad_materials", "material_id", m.material_id, vec, model)
    return len(vectors)


def embed_pending(
    db: Session,
    *,
    limit_per_table: int = 32,
    client=None,
) -> dict[str, int]:
    """Walk the three tables and embed up to `limit_per_table` rows each.

    Voyage allows 128 inputs per call; staying at 32 keeps a single tick well
    under both the request limit and the cron 225s budget. Counts returned per
    table for observability.
    """
    model = settings.VOYAGE_EMBED_MODEL

    if not settings.VOYAGE_API_KEY:
        return {"error": "VOYAGE_API_KEY not configured", "ad_combos": 0, "ad_copies": 0, "ad_materials": 0}

    voyage = client or _voyage_client()

    combos = _pending_combos(db, model, limit_per_table)
    copies = _pending_copies(db, model, limit_per_table)
    materials = _pending_materials(db, model, limit_per_table)

    counts = {
        "ad_combos": _embed_combo_batch(db, combos, model, voyage),
        "ad_copies": _embed_copy_batch(db, copies, model, voyage),
        "ad_materials": _embed_material_batch(db, materials, model, voyage),
    }
    db.commit()
    return counts


# ── Search helpers (called from creative_intelligence router) ─


def cosine_search(
    db: Session,
    table: str,
    pk_col: str,
    query_vec: list[float],
    *,
    limit: int = 25,
    where_sql: str = "",
    where_params: Optional[dict] = None,
) -> list[tuple[str, float]]:
    """Return [(pk, cosine_distance)] sorted by best match.

    Postgres-only — SQLite returns []. `where_sql` is appended after the
    base WHERE; use named placeholders + `where_params`.
    """
    if table not in EMBEDDABLE_TABLES:
        raise ValueError(f"Refusing to search unknown table {table}")
    if db.bind.dialect.name != "postgresql":
        return []

    sql = (
        f"SELECT {pk_col}, embedding <=> (:vec)::vector AS distance "
        f"FROM {table} "
        f"WHERE embedding IS NOT NULL"
    )
    if where_sql:
        sql += f" AND {where_sql}"
    sql += " ORDER BY distance ASC LIMIT :limit"

    params = {"vec": _vector_literal(query_vec), "limit": limit}
    params.update(where_params or {})

    rows = db.execute(text(sql), params).fetchall()
    return [(r[0], float(r[1])) for r in rows]
