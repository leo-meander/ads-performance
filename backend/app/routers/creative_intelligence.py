"""Creative Intelligence endpoints — visual tags, semantic search, AI brief.

Phase 1: visual tags read-only API + manual retag.
Phase 2: /search + /similar (semantic).        [stubs forthcoming]
Phase 3: /brief generator + Figma variant launcher.

The cron tagger lives at /api/internal/tasks/vision-tag-materials and is
operator-triggered; this router only exposes user-facing reads + per-material
retag.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
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
