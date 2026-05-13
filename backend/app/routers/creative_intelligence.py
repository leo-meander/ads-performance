"""Creative Intelligence endpoints — visual tags, semantic search, AI brief.

Phase 1: visual tags read-only API + manual retag.
Phase 2: /search (semantic by free-text query) + /similar/{combo_id}.
Phase 3: /brief generator + Figma variant launcher.

The cron tagger lives at /api/internal/tasks/vision-tag-materials and the
cron embedder at /api/internal/tasks/embed-creatives — both operator-triggered.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.creative_visual_tag import CreativeVisualTag
from app.models.user import User

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _serialize_tag(tag: CreativeVisualTag) -> dict:
    return {
        "category": tag.tag_category,
        "value": tag.tag_value,
        "confidence": float(tag.confidence) if tag.confidence is not None else None,
        "model_version": tag.model_version,
    }


# ── Per-material tag listing ─────────────────────────────────


@router.get("/creative/materials/{material_id}/tags")
def get_material_tags(
    material_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """All visual tags for a single material, plus the analysis timestamp.

    Empty `tags` + null `analyzed_at` means the cron tagger hasn't reached this
    material yet. Empty `tags` + non-null `analyzed_at` means the model
    returned no usable values (rare — usually means a broken thumbnail URL).
    """
    try:
        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == material_id)
            .first()
        )
        if not material:
            return _api_response(error=f"Material {material_id} not found")

        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)
        if scoped_ids is not None and material.branch_id not in scoped_ids:
            return _api_response(error="No access to this material")

        tags = (
            db.query(CreativeVisualTag)
            .filter(CreativeVisualTag.material_id == material_id)
            .order_by(CreativeVisualTag.tag_category, CreativeVisualTag.tag_value)
            .all()
        )

        # Group by category for the UI's badge layout
        grouped: dict[str, list[dict]] = {}
        for t in tags:
            grouped.setdefault(t.tag_category, []).append(_serialize_tag(t))

        return _api_response(data={
            "material_id": material_id,
            "analyzed_at": (
                material.vision_analyzed_at.isoformat()
                if material.vision_analyzed_at else None
            ),
            "model_version": material.vision_model,
            "tag_count": len(tags),
            "tags": grouped,
        })
    except Exception as e:
        return _api_response(error=str(e))


# ── Cross-material tag search ────────────────────────────────


@router.get("/creative/visual-tags")
def list_materials_by_tag(
    category: str = Query(..., description="e.g. emotional_angle, scene_type"),
    value: str = Query(..., description="e.g. aspirational, room"),
    branch_id: str | None = None,
    target_audience: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """List materials carrying a given (category, value) tag.

    Joins through ad_materials so callers can apply the standard branch/TA
    filters. Useful pattern: "show me all 'aspirational' creatives in Saigon
    with TA=Couple" → drives the next brief.
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        q = (
            db.query(AdMaterial, CreativeVisualTag)
            .join(
                CreativeVisualTag,
                CreativeVisualTag.material_id == AdMaterial.material_id,
            )
            .filter(CreativeVisualTag.tag_category == category)
            .filter(CreativeVisualTag.tag_value == value)
        )

        if branch_id:
            q = q.filter(AdMaterial.branch_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdMaterial.branch_id.in_(scoped_ids or ["__no_match__"]))

        if target_audience:
            q = q.filter(AdMaterial.target_audience == target_audience)

        total = q.count()
        rows = q.order_by(CreativeVisualTag.confidence.desc().nullslast()).offset(offset).limit(limit).all()

        items = [
            {
                "material_id": material.material_id,
                "branch_id": material.branch_id,
                "material_type": material.material_type,
                "file_url": material.file_url,
                "description": material.description,
                "target_audience": material.target_audience,
                "derived_verdict": material.derived_verdict,
                "matched_tag": _serialize_tag(tag),
            }
            for material, tag in rows
        ]
        return _api_response(data={"items": items, "total": total})
    except Exception as e:
        return _api_response(error=str(e))


# ── Manual retag trigger (single material) ───────────────────


@router.post("/creative/materials/{material_id}/retag")
def retag_material(
    material_id: str,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Force a re-tag of a single material.

    Clears vision_analyzed_at + vision_model so the next cron tick re-scores
    it. Synchronous tagging is intentionally NOT exposed here — vision calls
    are 5-15s and would block the API thread; cron handles the delay.
    """
    try:
        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == material_id)
            .first()
        )
        if not material:
            return _api_response(error=f"Material {material_id} not found")

        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        if scoped_ids is not None and material.branch_id not in scoped_ids:
            return _api_response(error="No access to this material")

        material.vision_analyzed_at = None
        material.vision_model = None
        db.commit()
        return _api_response(data={
            "material_id": material_id,
            "queued_for_retag": True,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── Semantic search (Phase 2) ────────────────────────────────


def _hydrate_combos(
    db: Session, combo_ids: list[str], distances: dict[str, float]
) -> list[dict]:
    """Look up combos + joined copy/material/branch for the search response."""
    if not combo_ids:
        return []
    rows = (
        db.query(AdCombo, AdCopy, AdMaterial, AdAccount)
        .outerjoin(AdCopy, AdCopy.copy_id == AdCombo.copy_id)
        .outerjoin(AdMaterial, AdMaterial.material_id == AdCombo.material_id)
        .outerjoin(AdAccount, AdAccount.id == AdCombo.branch_id)
        .filter(AdCombo.combo_id.in_(combo_ids))
        .all()
    )
    by_id = {r[0].combo_id: r for r in rows}
    out = []
    # Preserve cosine-distance order (best first)
    for cid in combo_ids:
        row = by_id.get(cid)
        if not row:
            continue
        combo, copy, material, branch = row
        out.append({
            "combo_id": combo.combo_id,
            "ad_name": combo.ad_name,
            "branch_id": combo.branch_id,
            "branch_name": branch.account_name if branch else None,
            "verdict": combo.verdict,
            "target_audience": combo.target_audience,
            "country": combo.country,
            "roas": float(combo.roas) if combo.roas is not None else None,
            "spend": float(combo.spend) if combo.spend is not None else None,
            "conversions": combo.conversions,
            "headline": copy.headline if copy else None,
            "cta": copy.cta if copy else None,
            "material_id": material.material_id if material else None,
            "file_url": material.file_url if material else None,
            "distance": distances.get(cid),
        })
    return out


@router.get("/creative/search")
def semantic_search(
    q: str = Query(..., min_length=2, description="Natural-language query, e.g. 'calm couple aspirational room'"),
    branch_id: str | None = None,
    target_audience: str | None = None,
    country: str | None = None,
    verdict: str | None = None,
    limit: int = Query(25, le=100),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Cosine-similarity search over ad_combos using Voyage embeddings.

    Query is embedded with input_type='query' (asymmetric to the document-side
    embeddings on storage, which improves retrieval quality). Filters are
    applied as plain WHERE clauses on top of the vector match — branch /
    audience / country / verdict scoping comes for free.

    Returns combos sorted by ascending cosine distance. Postgres-only;
    returns an empty list when run on SQLite (test path).
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        from app.services.embedding_service import cosine_search, embed_text

        try:
            qvec = embed_text(q, input_type="query")
        except RuntimeError as e:
            return _api_response(error=str(e))

        # Build the WHERE for the search SQL — must match the literal column
        # names in ad_combos. We use named placeholders so cosine_search can
        # bind them safely.
        where_clauses = []
        where_params: dict = {}
        if branch_id:
            where_clauses.append("branch_id = :branch_id")
            where_params["branch_id"] = branch_id
        elif scoped_ids is not None:
            where_clauses.append("branch_id = ANY(:scoped_ids)")
            where_params["scoped_ids"] = scoped_ids or ["__no_match__"]
        if target_audience:
            where_clauses.append("target_audience = :ta")
            where_params["ta"] = target_audience
        if country:
            where_clauses.append("country = :country")
            where_params["country"] = country.upper()
        if verdict:
            where_clauses.append("verdict = :verdict")
            where_params["verdict"] = verdict.upper()

        hits = cosine_search(
            db,
            "ad_combos",
            "combo_id",
            qvec,
            limit=limit,
            where_sql=" AND ".join(where_clauses),
            where_params=where_params,
        )

        if not hits:
            return _api_response(data={"items": [], "query": q, "engine": "voyage"})

        combo_ids = [pk for pk, _ in hits]
        distances = {pk: dist for pk, dist in hits}
        items = _hydrate_combos(db, combo_ids, distances)

        return _api_response(data={
            "items": items,
            "query": q,
            "engine": "voyage",
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/creative/similar/{combo_id}")
def find_similar_combos(
    combo_id: str,
    limit: int = Query(10, le=50),
    same_branch: bool = Query(False, description="Restrict to combos in the same branch"),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Nearest neighbours to a given combo by cosine distance on its stored embedding.

    Useful for "show me other ads like this winner". Skips the source combo itself.
    Postgres-only; empty result on SQLite.
    """
    try:
        combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
        if not combo:
            return _api_response(error=f"Combo {combo_id} not found")

        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)
        if scoped_ids is not None and combo.branch_id not in scoped_ids:
            return _api_response(error="No access to this combo")

        if db.bind.dialect.name != "postgresql":
            return _api_response(data={"items": [], "source_combo_id": combo_id, "engine": "voyage"})

        from sqlalchemy import text

        # Skip self + apply optional branch / scope filters via WHERE.
        where_clauses = ["combo_id != :self_id", "embedding IS NOT NULL"]
        where_params: dict = {"self_id": combo_id}
        if same_branch:
            where_clauses.append("branch_id = :branch_id")
            where_params["branch_id"] = combo.branch_id
        elif scoped_ids is not None:
            where_clauses.append("branch_id = ANY(:scoped_ids)")
            where_params["scoped_ids"] = scoped_ids or ["__no_match__"]

        sql = (
            "SELECT combo_id, "
            "       embedding <=> (SELECT embedding FROM ad_combos WHERE combo_id = :self_id) AS distance "
            "FROM ad_combos "
            "WHERE " + " AND ".join(where_clauses) + " "
            "ORDER BY distance ASC LIMIT :limit"
        )
        where_params["limit"] = limit
        hits = db.execute(text(sql), where_params).fetchall()
        if not hits:
            return _api_response(data={
                "items": [], "source_combo_id": combo_id, "engine": "voyage",
                "note": "No similar combos found — make sure the source combo has been embedded.",
            })

        combo_ids = [r[0] for r in hits]
        distances = {r[0]: float(r[1]) for r in hits}
        items = _hydrate_combos(db, combo_ids, distances)
        return _api_response(data={
            "items": items,
            "source_combo_id": combo_id,
            "engine": "voyage",
        })
    except Exception as e:
        return _api_response(error=str(e))
