"""Detect & persist Canva design links onto ad_materials.

Called from approval_service when a combo_approval transitions to APPROVED.
The approval's working_file_url is the canonical source — designers paste
the Canva working file there at submit time. We snapshot that URL onto the
material so it survives even if the approval row is later mutated, and so
winning-ads queries can reach the design with one join.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.models.approval import ComboApproval

# Canva design URL patterns we care about:
#   https://www.canva.com/design/DAFxxxxx/edit
#   https://www.canva.com/design/DAFxxxxx/view
#   https://canva.com/design/DAFxxxxx/...
_CANVA_DESIGN_RE = re.compile(
    r"https?://(?:www\.)?canva\.com/design/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def extract_canva_design_id(url: Optional[str]) -> Optional[str]:
    """Return the Canva design id (DAFxxxxx) embedded in url, else None."""
    if not url:
        return None
    match = _CANVA_DESIGN_RE.search(url)
    return match.group(1) if match else None


def capture_canva_link_from_approval(
    db: Session, approval: ComboApproval
) -> Optional[AdMaterial]:
    """If approval has a Canva working_file_url, snapshot it onto the material.

    No-op if:
      - working_file_url is empty or not a Canva URL
      - combo / material can't be resolved
      - material already has a canva_url (don't overwrite — first APPROVED wins)

    Returns the updated material on write, else None. Caller controls commit.
    """
    design_id = extract_canva_design_id(approval.working_file_url)
    if not design_id:
        return None

    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    if not combo or not combo.material_id:
        return None

    material = (
        db.query(AdMaterial)
        .filter(AdMaterial.material_id == combo.material_id)
        .first()
    )
    if not material:
        return None

    if material.canva_url:
        return None

    material.canva_url = approval.working_file_url
    material.canva_design_id = design_id
    material.canva_captured_at = datetime.now(timezone.utc)
    material.canva_source_approval_id = approval.id
    return material
