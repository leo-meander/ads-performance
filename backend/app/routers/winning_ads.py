"""Winning ads endpoints — surface WIN combos that have a Canva link captured.

Phase 1: list + detail (read-only).
Phase 2: regenerate endpoint lives in this router too (POST .../regenerate).
"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.ad_material import AdMaterial
from app.models.user import User
from app.services.regenerate_service import (
    RegenerateError,
    list_regenerations_for_material,
    regenerate_winning_ad,
)
from app.services.winning_ads_service import (
    get_winning_ad_detail,
    list_winning_ads,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/winning-ads")
def list_winning_ads_endpoint(
    branch_id: str | None = None,
    target_audience: str | None = None,
    country: str | None = None,
    verdict: str | None = None,
    sort_by: str = Query("roas"),
    sort_dir: str = Query("desc"),
    limit: int = Query(100, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        result = list_winning_ads(
            db,
            scoped_account_ids=scoped_ids,
            branch_id=branch_id,
            target_audience=target_audience,
            country=country,
            verdict=verdict,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
        )
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/winning-ads/backfill-canva")
def backfill_canva_endpoint(
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """One-shot: scan all combo_approvals for canva.* URLs and snapshot them
    onto materials. Idempotent — skips materials that already have a canva_url.
    Use this once after enabling the feature to backfill historical approvals.
    """
    try:
        from app.services.canva_link_capture import backfill_from_existing_approvals
        counts = backfill_from_existing_approvals(db)
        return _api_response(data=counts)
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/winning-ads/{material_id}")
def get_winning_ad_endpoint(
    material_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)

        detail = get_winning_ad_detail(db, material_id, scoped_account_ids=scoped_ids)
        if detail is None:
            return _api_response(error="Material not found or not accessible")

        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == material_id)
            .first()
        )
        if material is not None:
            detail["canva_template_id"] = material.canva_template_id
            detail["is_template_ready"] = material.is_template_ready
            detail["canva_placeholder_schema"] = material.canva_placeholder_schema

        detail["regenerations"] = list_regenerations_for_material(db, material_id)
        return _api_response(data=detail)
    except Exception as e:
        return _api_response(error=str(e))


# ── Phase 2: template config + regenerate ────────────────────


class TemplateConfigRequest(BaseModel):
    canva_template_id: str | None = None
    canva_placeholder_schema: dict[str, Any] | None = None
    is_template_ready: bool | None = None


@router.put("/winning-ads/{material_id}/template-config")
def configure_template(
    material_id: str,
    body: TemplateConfigRequest,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Designer wires up the brand template id + placeholder schema."""
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads", min_level="edit")
        if not ok:
            return _api_response(error=err)

        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == material_id)
            .first()
        )
        if not material:
            return _api_response(error="Material not found")
        if scoped_ids is not None and material.branch_id not in scoped_ids:
            return _api_response(error="No access to this material")

        if body.canva_template_id is not None:
            material.canva_template_id = body.canva_template_id or None
        if body.canva_placeholder_schema is not None:
            material.canva_placeholder_schema = body.canva_placeholder_schema
        if body.is_template_ready is not None:
            material.is_template_ready = body.is_template_ready
        db.commit()

        return _api_response(data={
            "material_id": material.material_id,
            "canva_template_id": material.canva_template_id,
            "canva_placeholder_schema": material.canva_placeholder_schema,
            "is_template_ready": material.is_template_ready,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


class RegenerateRequest(BaseModel):
    comment: str
    overrides: dict[str, Any] | None = None
    source_combo_id: str | None = None


@router.post("/winning-ads/{material_id}/regenerate")
def regenerate(
    material_id: str,
    body: RegenerateRequest,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Clone the winning material's Canva template, applying user comment + overrides."""
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads", min_level="edit")
        if not ok:
            return _api_response(error=err)

        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == material_id)
            .first()
        )
        if not material:
            return _api_response(error="Material not found")
        if scoped_ids is not None and material.branch_id not in scoped_ids:
            return _api_response(error="No access to this material")

        result = regenerate_winning_ad(
            db,
            material_id=material_id,
            comment=body.comment,
            overrides=body.overrides,
            requested_by=current_user.id,
            source_combo_id=body.source_combo_id,
        )
        return _api_response(data=result)
    except RegenerateError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
