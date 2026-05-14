"""Figma template + job lifecycle.

Templates are designer-registered master frames; jobs are render/variant
requests. The Figma REST API can EXPORT a frame to PNG and READ its text
layers but cannot WRITE text content from outside the editor — so a job's
primary output is:

  - an output_figma_url deep-link the designer opens to apply the
    request_payload manually (or via a future Figma plugin), and
  - an output_image_url for the rendered preview.

Polling is cron-driven — see /internal/tasks/figma-job-poll.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.figma import FigmaJob, FigmaTemplate
from app.services.figma_client import FigmaClient, FigmaClientError

logger = logging.getLogger(__name__)


class FigmaServiceError(ValueError):
    """Caller-facing error (4xx-style)."""


# ── Template management ──────────────────────────────────────


def list_templates(
    db: Session,
    *,
    branch_id: Optional[str] = None,
    platform: Optional[str] = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    q = db.query(FigmaTemplate)
    if branch_id:
        q = q.filter(FigmaTemplate.branch_id == branch_id)
    if platform:
        q = q.filter(FigmaTemplate.platform == platform)
    if active_only:
        q = q.filter(FigmaTemplate.is_active.is_(True))
    rows = q.order_by(FigmaTemplate.created_at.desc()).all()
    return [_serialize_template(t) for t in rows]


def create_template(
    db: Session,
    *,
    name: str,
    file_key: str,
    node_id: str,
    branch_id: Optional[str] = None,
    platform: str = "meta",
    width: int = 1080,
    height: int = 1080,
    placeholder_schema: Optional[dict] = None,
    created_by: Optional[str] = None,
    client: Optional[FigmaClient] = None,
) -> FigmaTemplate:
    """Register a master template. If placeholder_schema is omitted we infer it
    from the file's TEXT layers — anything named like a slug becomes a slot.
    """
    if not name.strip():
        raise FigmaServiceError("Template name is required")
    if not file_key.strip() or not node_id.strip():
        raise FigmaServiceError("file_key + node_id are required")

    schema = placeholder_schema or {}
    if not schema:
        c = client or FigmaClient()
        try:
            placeholders = c.get_placeholders(file_key, node_id)
        except FigmaClientError as e:
            logger.warning("Failed to auto-infer placeholders: %s", e)
            placeholders = []
        schema = _build_schema_from_placeholders(placeholders)

    template = FigmaTemplate(
        name=name.strip(),
        file_key=file_key.strip(),
        node_id=node_id.strip(),
        branch_id=branch_id,
        platform=platform,
        width=width,
        height=height,
        placeholder_schema=schema,
        is_active=True,
        created_by=created_by,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _build_schema_from_placeholders(placeholders: list) -> dict[str, Any]:
    """Turn FigmaPlaceholder rows into the stored placeholder_schema dict.

    Text slots keep their `current` content (handy default in the UI); image
    slots only record the source layer. The `$` prefix is already stripped by
    the client's collector, so keys are clean slugs (`headline`, `hero_image`).
    """
    schema: dict[str, Any] = {}
    for p in placeholders:
        if not p.name:
            continue
        if p.slot_type == "text":
            schema[p.name] = {
                "type": "text",
                "figma_layer": p.raw_name,
                "current": (p.characters or "")[:200],
            }
        else:
            schema[p.name] = {"type": "image", "figma_layer": p.raw_name}
    return schema


def refresh_template_schema(
    db: Session,
    template_id: str,
    *,
    client: Optional[FigmaClient] = None,
) -> FigmaTemplate:
    """Re-scan the template's Figma frame and rebuild placeholder_schema.

    The path designers use after renaming layers in Figma — no need to delete
    and re-register the template. Overwrites placeholder_schema wholesale with
    whatever `$`-prefixed slots currently exist in the frame.
    """
    template = db.query(FigmaTemplate).filter(FigmaTemplate.id == template_id).first()
    if not template:
        raise FigmaServiceError(f"Template {template_id} not found")

    c = client or FigmaClient()
    try:
        placeholders = c.get_placeholders(template.file_key, template.node_id)
    except FigmaClientError as e:
        raise FigmaServiceError(f"Figma re-scan failed: {e}") from e

    template.placeholder_schema = _build_schema_from_placeholders(placeholders)
    db.commit()
    db.refresh(template)
    return template


def update_template(
    db: Session,
    template_id: str,
    *,
    name: Optional[str] = None,
    placeholder_schema: Optional[dict] = None,
    is_active: Optional[bool] = None,
) -> FigmaTemplate:
    """Patch an existing template.

    The common case: the auto-inferred placeholder_schema was noisy (Figma
    auto-names text layers after their content), so the designer supplies an
    explicit {slug: {...}} mapping here instead of renaming layers in Figma.

    Pass-through semantics — None leaves a field unchanged.
    """
    template = db.query(FigmaTemplate).filter(FigmaTemplate.id == template_id).first()
    if not template:
        raise FigmaServiceError(f"Template {template_id} not found")

    if name is not None:
        if not name.strip():
            raise FigmaServiceError("Template name cannot be blank")
        template.name = name.strip()
    if placeholder_schema is not None:
        template.placeholder_schema = placeholder_schema
    if is_active is not None:
        template.is_active = is_active

    db.commit()
    db.refresh(template)
    return template


def refresh_template_preview(
    db: Session,
    template: FigmaTemplate,
    *,
    client: Optional[FigmaClient] = None,
) -> Optional[str]:
    """Re-export the template frame as a PNG and update preview_image_url.

    Used by the cron poller and on-demand from the templates UI. Returns the
    new URL (or None on failure).
    """
    c = client or FigmaClient()
    try:
        exports = c.export_images(template.file_key, [template.node_id], fmt="png")
    except FigmaClientError as e:
        logger.warning("Preview refresh failed for template %s: %s", template.id, e)
        return None
    if not exports:
        return None
    template.preview_image_url = exports[0].image_url
    db.commit()
    return exports[0].image_url


# ── Job lifecycle ────────────────────────────────────────────


def create_job(
    db: Session,
    *,
    template_id: str,
    request_payload: dict,
    requested_by: Optional[str] = None,
    source_combo_id: Optional[str] = None,
) -> FigmaJob:
    """Queue a variant request. The cron poller exports the frame; designers
    apply the request_payload's text/image overrides manually until plugin
    support lands.
    """
    template = db.query(FigmaTemplate).filter(FigmaTemplate.id == template_id).first()
    if not template:
        raise FigmaServiceError(f"Template {template_id} not found")
    if not template.is_active:
        raise FigmaServiceError(f"Template {template_id} is inactive")

    # Validate the request_payload only fills declared slots — anything else
    # is dropped to keep the schema honest.
    schema_keys = set((template.placeholder_schema or {}).keys())
    cleaned = {k: v for k, v in (request_payload or {}).items() if not schema_keys or k in schema_keys}

    now = datetime.now(timezone.utc)
    job = FigmaJob(
        template_id=template.id,
        source_combo_id=source_combo_id,
        request_payload=cleaned,
        status="PENDING",
        requested_by=requested_by,
        requested_at=now,
        # Deep-link gives the designer one-click access to the master frame.
        output_figma_url=_deep_link(template.file_key, template.node_id),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def poll_pending_jobs(
    db: Session,
    *,
    limit: int = 25,
    client: Optional[FigmaClient] = None,
) -> dict[str, int]:
    """Walk PENDING jobs, export the underlying template frame, mark COMPLETED.

    The export is the only async piece — the deep-link is set at create time.
    Future: when plugin support lands this is where we kick off the headless
    text-fill step before exporting.
    """
    c = client or FigmaClient()

    rows = (
        db.query(FigmaJob)
        .filter(FigmaJob.status.in_(["PENDING", "RUNNING"]))
        .order_by(FigmaJob.requested_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )

    counts = {"polled": 0, "completed": 0, "failed": 0}
    if not rows:
        return counts

    template_ids = {r.template_id for r in rows}
    templates = {
        t.id: t
        for t in db.query(FigmaTemplate).filter(FigmaTemplate.id.in_(template_ids)).all()
    }

    for job in rows:
        counts["polled"] += 1
        template = templates.get(job.template_id)
        if not template:
            job.status = "FAILED"
            job.error = "Template no longer exists"
            job.completed_at = datetime.now(timezone.utc)
            counts["failed"] += 1
            continue

        try:
            exports = c.export_images(template.file_key, [template.node_id], fmt="png")
        except FigmaClientError as e:
            job.status = "FAILED"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            counts["failed"] += 1
            continue

        job.output_image_url = exports[0].image_url if exports else None
        if not job.output_figma_url:
            job.output_figma_url = _deep_link(template.file_key, template.node_id)
        job.status = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        counts["completed"] += 1

    db.commit()
    return counts


# ── Plugin-facing helpers ────────────────────────────────────


def list_pending_jobs_for_plugin(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    """Pending/running jobs joined with their template's Figma coordinates.

    The Figma plugin needs everything in one payload: which file + node is the
    master frame, its placeholder schema (so it knows which layers are slots),
    and the job's request_payload (the values to fill).
    """
    rows = (
        db.query(FigmaJob, FigmaTemplate)
        .join(FigmaTemplate, FigmaTemplate.id == FigmaJob.template_id)
        .filter(FigmaJob.status.in_(["PENDING", "RUNNING"]))
        .order_by(FigmaJob.requested_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )
    out = []
    for job, tpl in rows:
        out.append({
            "job_id": job.id,
            "status": job.status,
            "source_combo_id": job.source_combo_id,
            "request_payload": job.request_payload or {},
            "requested_at": job.requested_at.isoformat() if job.requested_at else None,
            "template": {
                "id": tpl.id,
                "name": tpl.name,
                "file_key": tpl.file_key,
                "node_id": tpl.node_id,
                "width": tpl.width,
                "height": tpl.height,
                "placeholder_schema": tpl.placeholder_schema or {},
            },
        })
    return out


def complete_job(
    db: Session,
    job_id: str,
    *,
    output_figma_url: Optional[str] = None,
    output_image_url: Optional[str] = None,
) -> FigmaJob:
    """Mark a job COMPLETED — called by the plugin after it generates the frame."""
    job = db.query(FigmaJob).filter(FigmaJob.id == job_id).first()
    if not job:
        raise FigmaServiceError(f"Job {job_id} not found")
    job.status = "COMPLETED"
    job.completed_at = datetime.now(timezone.utc)
    if output_figma_url:
        job.output_figma_url = output_figma_url
    if output_image_url:
        job.output_image_url = output_image_url
    job.error = None
    db.commit()
    db.refresh(job)
    return job


def fail_job(db: Session, job_id: str, *, error: str) -> FigmaJob:
    """Mark a job FAILED with an error message."""
    job = db.query(FigmaJob).filter(FigmaJob.id == job_id).first()
    if not job:
        raise FigmaServiceError(f"Job {job_id} not found")
    job.status = "FAILED"
    job.error = (error or "Plugin reported a failure")[:2000]
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


# ── Serialization helpers ────────────────────────────────────


def _serialize_template(t: FigmaTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "file_key": t.file_key,
        "node_id": t.node_id,
        "branch_id": t.branch_id,
        "platform": t.platform,
        "width": t.width,
        "height": t.height,
        "placeholder_schema": t.placeholder_schema,
        "preview_image_url": t.preview_image_url,
        "is_active": t.is_active,
        "deep_link": _deep_link(t.file_key, t.node_id),
    }


def serialize_job(j: FigmaJob) -> dict[str, Any]:
    return {
        "id": j.id,
        "template_id": j.template_id,
        "source_combo_id": j.source_combo_id,
        "request_payload": j.request_payload,
        "status": j.status,
        "output_figma_url": j.output_figma_url,
        "output_image_url": j.output_image_url,
        "error": j.error,
        "requested_by": j.requested_by,
        "requested_at": j.requested_at.isoformat() if j.requested_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


def _deep_link(file_key: str, node_id: str) -> str:
    """Open-in-Figma URL targeting a specific node."""
    # Figma deep-link format: https://www.figma.com/file/{key}?node-id={id}
    safe_node = node_id.replace(":", "%3A")
    return f"https://www.figma.com/file/{file_key}?node-id={safe_node}"
