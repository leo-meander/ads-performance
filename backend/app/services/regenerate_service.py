"""Regenerate a winning ad's material via Canva.

Flow:
  1. Load source material; require canva_template_id + is_template_ready.
  2. Build the autofill payload by merging:
       - the original copy headline/cta (so the new design starts identical)
       - any explicit overrides the caller passed
       - a synthetic 'idea' note carrying the user's free-text comment
         (designers can map this to a notes/text slot if they want).
  3. Call CanvaClient.start_autofill — returns a job that may be:
       - status=success: design ready immediately → row=COMPLETED, promoted.
       - status=in_progress: row stays PENDING with canva_job_id set;
         /api/internal/tasks/canva-poll picks it up later.
       - status=failed: row=FAILED with error message.
  4. On COMPLETED: promote_regeneration_to_material() inserts a fresh
     ad_materials row (next MAT-XXX), copying the source's branch + TA and
     attaching the new Canva URL. The regen row's output_material_id points
     to it, so the UI can deep-link to the new material.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.material_regeneration import MaterialRegeneration
from app.services.canva_client import AutofillJob, CanvaClient, CanvaClientError
from app.services.creative_service import next_material_id

logger = logging.getLogger(__name__)


class RegenerateError(ValueError):
    """Caller-facing error (returned as 4xx-style API error)."""


def regenerate_winning_ad(
    db: Session,
    *,
    material_id: str,
    comment: str,
    overrides: Optional[dict[str, Any]] = None,
    requested_by: Optional[str] = None,
    source_combo_id: Optional[str] = None,
    canva_client: Optional[CanvaClient] = None,
) -> dict[str, Any]:
    if not comment or not comment.strip():
        raise RegenerateError("Comment is required")

    material = (
        db.query(AdMaterial)
        .filter(AdMaterial.material_id == material_id)
        .first()
    )
    if not material:
        raise RegenerateError(f"Material {material_id} not found")
    if not material.is_template_ready or not material.canva_template_id:
        raise RegenerateError(
            "This material has no Canva brand template wired up yet. Mark it as "
            "template-ready and set canva_template_id before regenerating."
        )

    autofill = _build_autofill(db, material, comment, overrides, source_combo_id)

    now = datetime.now(timezone.utc)
    row = MaterialRegeneration(
        source_material_id=material.material_id,
        source_combo_id=source_combo_id,
        comment=comment.strip(),
        overrides=overrides or {},
        status="PENDING",
        requested_by=requested_by,
        requested_at=now,
    )
    db.add(row)
    db.flush()

    client = canva_client or CanvaClient()

    try:
        job = client.start_autofill(
            template_id=material.canva_template_id,
            autofill=autofill,
            title=f"Regenerated from {material.material_id}",
        )
    except CanvaClientError as e:
        row.status = "FAILED"
        row.error = str(e)
        row.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception("Canva regeneration failed for material %s", material_id)
        raise RegenerateError(f"Canva regeneration failed: {e}") from e

    _apply_job_to_row(db, row, job, source_material=material)
    db.commit()

    return _serialize(row, autofill_echo=job.autofill_echo)


def list_regenerations_for_material(
    db: Session, material_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = (
        db.query(MaterialRegeneration)
        .filter(MaterialRegeneration.source_material_id == material_id)
        .order_by(MaterialRegeneration.requested_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    return [_serialize(r) for r in rows]


# ── Async polling (called by Zeabur cron via /internal/tasks/canva-poll) ──


def poll_pending_regenerations(
    db: Session,
    *,
    canva_client: Optional[CanvaClient] = None,
    limit: int = 50,
) -> dict[str, int]:
    """Walk PENDING/RUNNING regenerations with a job_id; finish what's ready.

    Returns counts: {polled, completed, failed, still_pending}.
    """
    client = canva_client or CanvaClient()
    rows = (
        db.query(MaterialRegeneration)
        .filter(MaterialRegeneration.status.in_(["PENDING", "RUNNING"]))
        .filter(MaterialRegeneration.canva_job_id.isnot(None))
        .order_by(MaterialRegeneration.requested_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )

    counts = {"polled": 0, "completed": 0, "failed": 0, "still_pending": 0}
    for row in rows:
        counts["polled"] += 1
        try:
            job = client.get_autofill_job(row.canva_job_id)
        except CanvaClientError as e:
            logger.exception("Canva poll failed for regen %s", row.id)
            row.status = "FAILED"
            row.error = f"Poll failed: {e}"
            row.completed_at = datetime.now(timezone.utc)
            counts["failed"] += 1
            continue

        source = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == row.source_material_id)
            .first()
        )
        _apply_job_to_row(db, row, job, source_material=source)
        if row.status == "COMPLETED":
            counts["completed"] += 1
        elif row.status == "FAILED":
            counts["failed"] += 1
        else:
            counts["still_pending"] += 1

    db.commit()
    return counts


# ── Helpers ───────────────────────────────────────────────────


def _apply_job_to_row(
    db: Session,
    row: MaterialRegeneration,
    job: AutofillJob,
    source_material: Optional[AdMaterial],
) -> None:
    """Mutate row according to the job's terminal state. No commit here."""
    row.canva_job_id = job.job_id or row.canva_job_id

    if job.status == "in_progress":
        row.status = "PENDING"
        return

    if job.status == "failed":
        row.status = "FAILED"
        row.error = job.error or "Canva job failed"
        row.completed_at = datetime.now(timezone.utc)
        return

    if job.design is None:
        row.status = "FAILED"
        row.error = "Canva returned success but no design"
        row.completed_at = datetime.now(timezone.utc)
        return

    row.status = "COMPLETED"
    row.output_canva_url = job.design.edit_url
    row.output_design_id = job.design.design_id
    row.completed_at = datetime.now(timezone.utc)

    if source_material is not None and not row.output_material_id:
        try:
            promoted = promote_regeneration_to_material(db, row, source_material)
            row.output_material_id = promoted.material_id
        except Exception:
            logger.exception("Promotion to AdMaterial failed for regen %s", row.id)


def promote_regeneration_to_material(
    db: Session,
    regen: MaterialRegeneration,
    source: AdMaterial,
) -> AdMaterial:
    """Insert a fresh ad_materials row representing the regenerated design.

    url_source='manual' so the Meta preview-URL sync task won't overwrite the
    Canva URL with a Meta CDN URL once the new ad goes live.
    """
    if not regen.output_canva_url or not regen.output_design_id:
        raise ValueError("Regeneration has no output design to promote")

    new_id = next_material_id(db)
    description_bits = [f"Auto-generated from {source.material_id}"]
    if regen.comment:
        description_bits.append(regen.comment[:120])
    description = " — ".join(description_bits)

    new_material = AdMaterial(
        branch_id=source.branch_id,
        material_id=new_id,
        material_type=source.material_type,
        file_url=regen.output_canva_url,  # Canva edit URL doubles as preview
        description=description,
        target_audience=source.target_audience,
        url_source="manual",
        canva_url=regen.output_canva_url,
        canva_design_id=regen.output_design_id,
        canva_captured_at=datetime.now(timezone.utc),
        # canva_source_approval_id intentionally NULL — this material is
        # regen-derived, not approval-derived.
    )
    db.add(new_material)
    db.flush()
    logger.info(
        "Promoted regen %s → new material %s (template_source=%s)",
        regen.id, new_id, source.material_id,
    )
    return new_material


def _build_autofill(
    db: Session,
    material: AdMaterial,
    comment: str,
    overrides: Optional[dict[str, Any]],
    source_combo_id: Optional[str],
) -> dict[str, Any]:
    """Seed autofill from the source combo's copy, then apply overrides.

    Designer-defined placeholder schema is the contract. We only fill keys
    the schema declares — extra overrides are passed through (useful when the
    schema isn't wired yet but Canva already has the slots).
    """
    schema_keys: set[str] = set()
    if isinstance(material.canva_placeholder_schema, dict):
        schema_keys = set(material.canva_placeholder_schema.keys())
    elif isinstance(material.canva_placeholder_schema, list):
        schema_keys = set(material.canva_placeholder_schema)

    autofill: dict[str, Any] = {}

    combo = None
    if source_combo_id:
        combo = (
            db.query(AdCombo)
            .filter(AdCombo.combo_id == source_combo_id)
            .first()
        )
    if combo is None:
        combo = (
            db.query(AdCombo)
            .filter(AdCombo.material_id == material.material_id)
            .filter(AdCombo.verdict == "WIN")
            .order_by(AdCombo.roas.desc().nullslast())
            .first()
        )

    if combo and combo.copy_id:
        copy = db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first()
        if copy:
            for slot, value in (
                ("headline", copy.headline),
                ("body", copy.body_text),
                ("cta", copy.cta),
            ):
                if value and (not schema_keys or slot in schema_keys):
                    autofill[slot] = value

    if overrides:
        for k, v in overrides.items():
            if v is None:
                continue
            if not schema_keys or k in schema_keys:
                autofill[k] = v

    # Always thread the user's idea through — designers can wire it to a
    # notes layer or just inspect it on the regenerated design.
    if not schema_keys or "idea" in schema_keys:
        autofill["idea"] = comment.strip()

    return autofill


def _serialize(row: MaterialRegeneration, autofill_echo=None) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_material_id": row.source_material_id,
        "source_combo_id": row.source_combo_id,
        "comment": row.comment,
        "overrides": row.overrides,
        "status": row.status,
        "canva_job_id": row.canva_job_id,
        "output_canva_url": row.output_canva_url,
        "output_design_id": row.output_design_id,
        "output_material_id": row.output_material_id,
        "error": row.error,
        "requested_by": row.requested_by,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "autofill_echo": autofill_echo,
    }
