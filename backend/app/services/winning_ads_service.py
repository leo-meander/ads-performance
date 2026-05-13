"""Winning ads service.

Surfaces every combo joined with its material + copy. Default ordering is by
ROAS desc so winners bubble to the top — the UI filters/sorts further. The
"regenerate" pipeline that used to live here was Canva-specific and has been
removed; Figma-based variant generation lives under /api/figma + /api/creative/brief.

Filtering rules (server-side):
  - optional verdict, branch_id, target_audience, country filters
  - sorted by ROAS desc by default

Permissions: callers pass `scoped_account_ids` from the auth layer; this
service trusts that list and only filters by it.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial


def list_winning_ads(
    db: Session,
    *,
    scoped_account_ids: Optional[list[str]] = None,
    branch_id: Optional[str] = None,
    target_audience: Optional[str] = None,
    country: Optional[str] = None,
    verdict: Optional[str] = None,
    sort_by: str = "roas",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return combos joined with their material + copy.

    `scoped_account_ids=None` means caller has global scope (admin); empty
    list means no access — return zero rows.
    """
    if scoped_account_ids is not None and not scoped_account_ids:
        return {"items": [], "total": 0}

    q = (
        db.query(AdCombo, AdMaterial, AdCopy, AdAccount)
        .join(AdMaterial, AdMaterial.material_id == AdCombo.material_id)
        .join(AdCopy, AdCopy.copy_id == AdCombo.copy_id)
        .outerjoin(AdAccount, AdAccount.id == AdCombo.branch_id)
    )

    if scoped_account_ids is not None:
        q = q.filter(AdCombo.branch_id.in_(scoped_account_ids))
    if branch_id:
        q = q.filter(AdCombo.branch_id == branch_id)
    if target_audience:
        q = q.filter(AdCombo.target_audience == target_audience)
    if country:
        q = q.filter(AdCombo.country == country.upper())
    if verdict:
        q = q.filter(AdCombo.verdict == verdict.upper())

    total = q.count()

    sort_col = {
        "roas": AdCombo.roas,
        "spend": AdCombo.spend,
        "conversions": AdCombo.conversions,
        "ctr": AdCombo.ctr,
    }.get(sort_by, AdCombo.roas)

    q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
    rows = q.offset(offset).limit(limit).all()

    items = []
    for combo, material, copy, branch in rows:
        items.append({
            "combo_id": combo.combo_id,
            "ad_name": combo.ad_name,
            "branch_id": combo.branch_id,
            "branch_name": branch.account_name if branch else None,
            "target_audience": combo.target_audience,
            "country": combo.country,
            "verdict": combo.verdict,
            "spend": float(combo.spend) if combo.spend is not None else None,
            "roas": float(combo.roas) if combo.roas is not None else None,
            "conversions": combo.conversions,
            "cost_per_purchase": float(combo.cost_per_purchase) if combo.cost_per_purchase is not None else None,
            "ctr": float(combo.ctr) if combo.ctr is not None else None,
            "hook_rate": float(combo.hook_rate) if combo.hook_rate is not None else None,
            "thruplay_rate": float(combo.thruplay_rate) if combo.thruplay_rate is not None else None,
            # Copy snapshot (so the frontend can show what's being cloned)
            "copy_id": copy.copy_id,
            "headline": copy.headline,
            "body_text": copy.body_text,
            "cta": copy.cta,
            "language": copy.language,
            # Material
            "material_id": material.material_id,
            "material_type": material.material_type,
            "file_url": material.file_url,
        })

    return {"items": items, "total": total}


def get_winning_ad_detail(
    db: Session,
    material_id: str,
    *,
    scoped_account_ids: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """Detail view: one material + every combo using it.

    Returns None when material doesn't exist or caller has no scope on it.
    """
    material = (
        db.query(AdMaterial)
        .filter(AdMaterial.material_id == material_id)
        .first()
    )
    if not material:
        return None
    if scoped_account_ids is not None and material.branch_id not in scoped_account_ids:
        return None

    branch = db.query(AdAccount).filter(AdAccount.id == material.branch_id).first()

    combos = (
        db.query(AdCombo, AdCopy)
        .join(AdCopy, AdCopy.copy_id == AdCombo.copy_id)
        .filter(AdCombo.material_id == material_id)
        .order_by(AdCombo.roas.desc().nullslast())
        .all()
    )

    combo_list = []
    for combo, copy in combos:
        combo_list.append({
            "combo_id": combo.combo_id,
            "ad_name": combo.ad_name,
            "verdict": combo.verdict,
            "target_audience": combo.target_audience,
            "country": combo.country,
            "spend": float(combo.spend) if combo.spend is not None else None,
            "roas": float(combo.roas) if combo.roas is not None else None,
            "conversions": combo.conversions,
            "headline": copy.headline,
            "body_text": copy.body_text,
            "cta": copy.cta,
        })

    return {
        "material_id": material.material_id,
        "branch_id": material.branch_id,
        "branch_name": branch.account_name if branch else None,
        "material_type": material.material_type,
        "file_url": material.file_url,
        "description": material.description,
        "target_audience": material.target_audience,
        "derived_verdict": material.derived_verdict,
        "combos": combo_list,
    }
