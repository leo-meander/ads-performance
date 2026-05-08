"""Regenerate a winning ad's material via Canva.

Flow (synchronous, single request):
  1. Load source material; require canva_template_id + is_template_ready.
  2. Build the autofill payload by merging:
       - the original copy headline/cta (so the new design starts identical)
       - any explicit overrides the caller passed
       - a synthetic 'idea' note carrying the user's free-text comment
         (designers can map this to a notes/text slot if they want).
  3. Call CanvaClient.clone_template — returns design_id + edit_url.
  4. Insert a material_regenerations row with status=COMPLETED (or FAILED).
  5. Return the row dict to the router.

The async/queued path is intentionally deferred: Canva's autofills endpoint
is technically async but Phase 2 ships the happy path. When we wire the
Zeabur cron poller (POST /api/internal/tasks/canva-poll), it will advance
PENDING -> RUNNING -> COMPLETED rows by polling Canva's job status.
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
from app.services.canva_client import CanvaClient, CanvaClientError

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
        status="RUNNING",
        requested_by=requested_by,
        requested_at=now,
    )
    db.add(row)
    db.flush()

    client = canva_client or CanvaClient()

    try:
        design = client.clone_template(
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

    row.status = "COMPLETED"
    row.output_canva_url = design.edit_url
    row.output_design_id = design.design_id
    row.completed_at = datetime.now(timezone.utc)
    db.commit()

    return _serialize(row, autofill_echo=design.autofill_echo)


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


# ── Helpers ───────────────────────────────────────────────────


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
        "output_canva_url": row.output_canva_url,
        "output_design_id": row.output_design_id,
        "error": row.error,
        "requested_by": row.requested_by,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "autofill_echo": autofill_echo,
    }
