"""Detect & persist Canva design links onto ad_materials.

Called from approval_service whenever an approval row gets a working_file_url
(submit + resubmit + APPROVED). The url is snapshotted onto the material so
winning-ads queries can reach the design with one join.

Two URL shapes are recognized:
  - https://www.canva.com/design/{design_id}/edit  → editor URL with design id
  - https://canva.link/{short_id}                  → short share link, no
    design id embedded in URL (resolves server-side via redirect; we don't
    follow it — canva_design_id stays NULL for these and Connect API calls
    that need the id will fall back to the brand-template id instead).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.models.approval import ComboApproval

# Editor-style URL — captures the design id for Connect API use.
_CANVA_DESIGN_RE = re.compile(
    r"https?://(?:www\.)?canva\.com/design/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
# Any Canva URL, including the short canva.link/{slug} share form.
_ANY_CANVA_RE = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)?canva\.(?:com|link|site)/",
    re.IGNORECASE,
)


def extract_canva_design_id(url: Optional[str]) -> Optional[str]:
    """Return the Canva design id (DAFxxxxx) when the url is editor-style, else None.

    Short canva.link/{slug} URLs return None — the slug is not the design id
    and resolving it requires an HTTP redirect we don't perform here.
    """
    if not url:
        return None
    match = _CANVA_DESIGN_RE.search(url)
    return match.group(1) if match else None


def is_canva_url(url: Optional[str]) -> bool:
    """True for any canva.com / canva.link / *.canva.site URL."""
    if not url:
        return False
    return bool(_ANY_CANVA_RE.search(url))


def capture_canva_link_from_approval(
    db: Session, approval: ComboApproval
) -> Optional[AdMaterial]:
    """If approval has a Canva working_file_url, snapshot it onto the material.

    No-op if:
      - working_file_url is empty or not a Canva URL (any canva.* domain)
      - combo / material can't be resolved
      - material already has a canva_url (first capture wins; new approval
        rounds don't overwrite — designer can edit material directly to
        change the link)

    Returns the updated material on write, else None. Caller controls commit.
    """
    if not is_canva_url(approval.working_file_url):
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
    # design_id is only present for editor-style URLs; canva.link shares
    # leave this NULL until the designer pastes a full editor URL.
    material.canva_design_id = extract_canva_design_id(approval.working_file_url)
    material.canva_captured_at = datetime.now(timezone.utc)
    material.canva_source_approval_id = approval.id
    return material


def backfill_from_existing_approvals(db: Session) -> dict[str, int]:
    """Walk every combo_approval and capture any Canva URLs that haven't been
    snapshotted yet. Idempotent — capture skips materials that already have a
    canva_url, so re-running this is safe.

    Returns counts: {scanned, captured, skipped_no_url, skipped_already_set}.
    """
    counts = {"scanned": 0, "captured": 0, "skipped_no_url": 0, "skipped_already_set": 0}
    approvals = (
        db.query(ComboApproval)
        .filter(ComboApproval.working_file_url.isnot(None))
        .order_by(ComboApproval.submitted_at.asc().nullsfirst())
        .all()
    )
    for ap in approvals:
        counts["scanned"] += 1
        if not is_canva_url(ap.working_file_url):
            counts["skipped_no_url"] += 1
            continue
        before = capture_canva_link_from_approval(db, ap)
        if before is None:
            # Either material missing/has-url already, or url not canva
            counts["skipped_already_set"] += 1
        else:
            counts["captured"] += 1
    db.commit()
    return counts
