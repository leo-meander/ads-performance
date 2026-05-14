"""Figma template + variant-job endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.figma import FigmaJob, FigmaTemplate
from app.models.user import User
from app.services.figma_service import (
    FigmaServiceError,
    create_job,
    create_template,
    list_templates,
    refresh_template_preview,
    serialize_job,
    update_template,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Templates ────────────────────────────────────────────────


@router.get("/figma/templates")
def list_templates_endpoint(
    branch_id: str | None = None,
    platform: str | None = None,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        # Templates can be branch-scoped OR shared (branch_id=NULL); the list
        # endpoint always shows shared ones in addition to scoped ones.
        items = list_templates(db, branch_id=branch_id, platform=platform)
        return _api_response(data={"items": items, "total": len(items)})
    except Exception as e:
        return _api_response(error=str(e))


class TemplateCreate(BaseModel):
    name: str
    file_key: str
    node_id: str
    branch_id: str | None = None
    platform: str = "meta"
    width: int = 1080
    height: int = 1080
    placeholder_schema: dict[str, Any] | None = None


@router.post("/figma/templates")
def create_template_endpoint(
    body: TemplateCreate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        if body.branch_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "meta_ads",
                requested_account_id=body.branch_id, min_level="edit",
            )
            if not ok:
                return _api_response(error=err)

        tpl = create_template(
            db,
            name=body.name,
            file_key=body.file_key,
            node_id=body.node_id,
            branch_id=body.branch_id,
            platform=body.platform,
            width=body.width,
            height=body.height,
            placeholder_schema=body.placeholder_schema,
            created_by=current_user.id,
        )
        return _api_response(data={
            "id": tpl.id,
            "name": tpl.name,
            "placeholder_schema": tpl.placeholder_schema,
        })
    except FigmaServiceError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


class TemplateUpdate(BaseModel):
    name: str | None = None
    placeholder_schema: dict[str, Any] | None = None
    is_active: bool | None = None


@router.patch("/figma/templates/{template_id}")
def update_template_endpoint(
    template_id: str,
    body: TemplateUpdate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Patch a template — typically to replace the noisy auto-inferred
    placeholder_schema with an explicit {slug: {...}} mapping so the designer
    doesn't have to rename layers in Figma.

    Example placeholder_schema body:
      {"headline": {"type": "text", "figma_layer": "THE MOST FUN HOSTEL"},
       "cta": {"type": "text", "figma_layer": "BOOK NOW"}}
    """
    try:
        tpl = update_template(
            db,
            template_id,
            name=body.name,
            placeholder_schema=body.placeholder_schema,
            is_active=body.is_active,
        )
        return _api_response(data={
            "id": tpl.id,
            "name": tpl.name,
            "placeholder_schema": tpl.placeholder_schema,
            "is_active": tpl.is_active,
        })
    except FigmaServiceError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.delete("/figma/templates/{template_id}")
def delete_template_endpoint(
    template_id: str,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Soft-delete a template (is_active = False) — per the project's
    DELETE-is-always-soft-delete rule."""
    try:
        tpl = update_template(db, template_id, is_active=False)
        return _api_response(data={"id": tpl.id, "is_active": tpl.is_active})
    except FigmaServiceError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/figma/templates/{template_id}/refresh-preview")
def refresh_template_preview_endpoint(
    template_id: str,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        tpl = db.query(FigmaTemplate).filter(FigmaTemplate.id == template_id).first()
        if not tpl:
            return _api_response(error="Template not found")
        url = refresh_template_preview(db, tpl)
        return _api_response(data={"id": template_id, "preview_image_url": url})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── Jobs (variant requests) ──────────────────────────────────


class JobCreate(BaseModel):
    template_id: str
    request_payload: dict[str, Any] = {}
    source_combo_id: str | None = None


@router.post("/figma/jobs")
def create_job_endpoint(
    body: JobCreate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Queue a variant request. Returns a job row + a Figma deep-link the
    designer can open immediately. Image preview lands later via cron poll."""
    try:
        job = create_job(
            db,
            template_id=body.template_id,
            request_payload=body.request_payload,
            requested_by=current_user.id,
            source_combo_id=body.source_combo_id,
        )
        return _api_response(data=serialize_job(job))
    except FigmaServiceError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/figma/jobs")
def list_jobs_endpoint(
    template_id: str | None = None,
    status: str | None = Query(None, description="PENDING | RUNNING | COMPLETED | FAILED"),
    limit: int = Query(50, le=200),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(FigmaJob)
        if template_id:
            q = q.filter(FigmaJob.template_id == template_id)
        if status:
            q = q.filter(FigmaJob.status == status.upper())
        rows = q.order_by(FigmaJob.requested_at.desc().nullslast()).limit(limit).all()
        return _api_response(data={"items": [serialize_job(j) for j in rows]})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/figma/jobs/{job_id}")
def get_job_endpoint(
    job_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        job = db.query(FigmaJob).filter(FigmaJob.id == job_id).first()
        if not job:
            return _api_response(error="Job not found")
        return _api_response(data=serialize_job(job))
    except Exception as e:
        return _api_response(error=str(e))
