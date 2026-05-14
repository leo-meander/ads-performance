"""Creative Intelligence endpoints — visual tags, tag search, AI brief.

Phase 1: visual tags read-only API + manual retag.
Phase 2: /search (tag + keyword filter) + /similar/{combo_id} (shared-tag cluster).
Phase 3: /brief generator + Figma variant launcher.

Search is pure SQL — no embedding provider. Combos are matched on their
material's creative_visual_tags (Claude-vision-derived) plus an optional
ILIKE keyword over ad_name / headline / body_text. The cron tagger at
/api/internal/tasks/vision-tag-materials keeps the tags fresh.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
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


# ── Tag + keyword search (Phase 2) ───────────────────────────


def _serialize_combo_row(combo, copy, material, branch, *, extra: dict | None = None) -> dict:
    row = {
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
    }
    if extra:
        row.update(extra)
    return row


def _parse_tag_pairs(tags: list[str]) -> list[tuple[str, str]]:
    """Parse ['emotional_angle:aspirational', 'scene_type:room'] → [(cat, val), ...]."""
    out: list[tuple[str, str]] = []
    for raw in tags or []:
        if ":" not in raw:
            continue
        cat, val = raw.split(":", 1)
        cat, val = cat.strip(), val.strip()
        if cat and val:
            out.append((cat, val))
    return out


def _material_ids_matching_tags(
    db: Session, tag_pairs: list[tuple[str, str]], match: str
) -> set[str] | None:
    """Return the set of material_ids whose visual tags satisfy `tag_pairs`.

    match='all' → material must carry every (category,value) pair.
    match='any' → material carries at least one.
    Returns None when no tag filter was requested (caller skips the filter).
    """
    if not tag_pairs:
        return None

    or_clauses = [
        (CreativeVisualTag.tag_category == cat) & (CreativeVisualTag.tag_value == val)
        for cat, val in tag_pairs
    ]
    base = (
        db.query(CreativeVisualTag.material_id)
        .filter(or_(*or_clauses))
    )
    if match == "all":
        # Count distinct matched pairs per material; require == len(tag_pairs).
        base = (
            base.group_by(CreativeVisualTag.material_id)
            .having(
                func.count(
                    func.distinct(
                        CreativeVisualTag.tag_category + ":" + CreativeVisualTag.tag_value
                    )
                )
                == len(tag_pairs)
            )
        )
    rows = base.all()
    return {r[0] for r in rows}


@router.get("/creative/search")
def tag_search(
    q: str | None = Query(None, description="Keyword — ILIKE over ad_name / headline / body_text"),
    tags: list[str] = Query(default=[], description="Repeated category:value, e.g. tags=scene_type:room"),
    match: str = Query("all", description="'all' = combo must carry every tag; 'any' = at least one"),
    branch_id: str | None = None,
    target_audience: str | None = None,
    country: str | None = None,
    verdict: str | None = None,
    figma_only: bool = Query(False, description="Only combos whose material has a Figma source"),
    sort_by: str = Query("roas", description="roas | spend | conversions"),
    limit: int = Query(25, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Search combos by visual tags + optional keyword. Pure SQL — no embeddings.

    Tag matching runs against the combo's material's creative_visual_tags
    (Claude-vision-derived). The keyword does a case-insensitive ILIKE over
    ad_name, headline and body_text. Branch / TA / country / verdict scope as
    plain filters. `figma_only` restricts to materials with a Figma source
    (file_url is a figma.com link or figma_file_key is wired). Results are
    sorted by the chosen performance column.
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        tag_pairs = _parse_tag_pairs(tags)
        match = "any" if match == "any" else "all"
        matched_material_ids = _material_ids_matching_tags(db, tag_pairs, match)
        if matched_material_ids is not None and not matched_material_ids:
            # Tag filter requested but nothing matched — short-circuit.
            return _api_response(data={"items": [], "total": 0, "tags": tags, "query": q})

        base = (
            db.query(AdCombo, AdCopy, AdMaterial, AdAccount)
            .outerjoin(AdCopy, AdCopy.copy_id == AdCombo.copy_id)
            .outerjoin(AdMaterial, AdMaterial.material_id == AdCombo.material_id)
            .outerjoin(AdAccount, AdAccount.id == AdCombo.branch_id)
        )

        if branch_id:
            base = base.filter(AdCombo.branch_id == branch_id)
        elif scoped_ids is not None:
            base = base.filter(AdCombo.branch_id.in_(scoped_ids or ["__no_match__"]))
        if target_audience:
            base = base.filter(AdCombo.target_audience == target_audience)
        if country:
            base = base.filter(AdCombo.country == country.upper())
        if verdict:
            base = base.filter(AdCombo.verdict == verdict.upper())
        if matched_material_ids is not None:
            base = base.filter(AdCombo.material_id.in_(matched_material_ids))
        if figma_only:
            base = base.filter(
                or_(
                    AdMaterial.file_url.ilike("%figma.com%"),
                    AdMaterial.figma_file_key.isnot(None),
                )
            )
        if q:
            like = f"%{q}%"
            base = base.filter(
                or_(
                    AdCombo.ad_name.ilike(like),
                    AdCopy.headline.ilike(like),
                    AdCopy.body_text.ilike(like),
                )
            )

        total = base.count()

        sort_col = {
            "roas": AdCombo.roas,
            "spend": AdCombo.spend,
            "conversions": AdCombo.conversions,
        }.get(sort_by, AdCombo.roas)
        rows = (
            base.order_by(sort_col.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = [
            _serialize_combo_row(combo, copy, material, branch)
            for combo, copy, material, branch in rows
        ]
        return _api_response(data={
            "items": items,
            "total": total,
            "tags": tags,
            "query": q,
            "match": match,
        })
    except Exception as e:
        return _api_response(error=str(e))


class BriefRequest(BaseModel):
    branch_id: str
    target_audience: str | None = None
    country: str | None = None
    vibe: str | None = None
    n_variants: int = 3
    performance_goal: str = "roas"


@router.post("/creative/brief")
def generate_brief_endpoint(
    body: BriefRequest,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Produce N AI-generated brief variants grounded in the branch's winners.

    Returns the briefs + the pattern summary that fed the model + a short list
    of recommended Figma templates ready to clone.
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id
        )
        if not ok:
            return _api_response(error=err)

        from app.services.creative_brief_service import generate_brief

        result = generate_brief(
            db,
            branch_id=body.branch_id,
            target_audience=body.target_audience,
            country=body.country,
            vibe=body.vibe,
            n_variants=body.n_variants,
            performance_goal=body.performance_goal,
        )
        return _api_response(data=result)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        return _api_response(error=str(e))


# ── Auto-assign angle + keypoints (suggest → confirm) ────────


class AutoAssignSuggestRequest(BaseModel):
    branch_id: str
    combo_id: str | None = None
    headline: str | None = None
    benefits: list[str] | None = None
    body_text: str | None = None
    script_text: str | None = None
    use_figma: bool = False


@router.post("/creative/autoassign/suggest")
def autoassign_suggest(
    body: AutoAssignSuggestRequest,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Suggest an angle + keypoint split for a combo / raw text / video script.

    Pure — no DB writes. Returns matched existing keypoints + PROPOSED new ones
    for the user to confirm. Source priority: script_text > use_figma > explicit
    headline/benefits > combo copy.
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)

        from app.services.creative_autoassign_service import AutoAssignError, suggest

        try:
            result = suggest(
                db,
                branch_id=body.branch_id,
                combo_id=body.combo_id,
                headline=body.headline,
                benefits=body.benefits,
                body_text=body.body_text,
                script_text=body.script_text,
                use_figma=body.use_figma,
            )
        except AutoAssignError as e:
            return _api_response(error=str(e))
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


class NewKeypoint(BaseModel):
    title: str
    category: str  # location | amenity | experience | value


class AutoAssignApplyRequest(BaseModel):
    combo_id: str
    angle_id: str | None = None
    keypoint_ids: list[str] | None = None  # existing keypoints the user kept
    new_keypoints: list[NewKeypoint] | None = None  # proposed ones the user confirmed


@router.post("/creative/autoassign/apply")
def autoassign_apply(
    body: AutoAssignApplyRequest,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Persist a confirmed auto-assignment: creates the confirmed new keypoints
    and stamps angle_id + keypoint_ids onto the combo."""
    try:
        from app.models.ad_combo import AdCombo as _AdCombo
        combo = db.query(_AdCombo).filter(_AdCombo.combo_id == body.combo_id).first()
        if not combo:
            return _api_response(error=f"Combo {body.combo_id} not found")

        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        if scoped_ids is not None and combo.branch_id not in scoped_ids:
            return _api_response(error="No access to this combo")

        from app.services.creative_autoassign_service import AutoAssignError, apply

        try:
            result = apply(
                db,
                combo_id=body.combo_id,
                angle_id=body.angle_id,
                keypoint_ids=body.keypoint_ids,
                new_keypoints=[nk.model_dump() for nk in (body.new_keypoints or [])],
            )
        except AutoAssignError as e:
            return _api_response(error=str(e))
        return _api_response(data=result)
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/creative/similar/{combo_id}")
def find_similar_combos(
    combo_id: str,
    limit: int = Query(10, le=50),
    same_branch: bool = Query(False, description="Restrict to combos in the same branch"),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Combos whose material shares the most visual tags with this one.

    "Show me other ads like this winner" — ranks by the count of overlapping
    (category, value) visual tags, tie-broken by ROAS. Skips the source combo.
    Works on any DB (pure SQL over creative_visual_tags).
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

        # Source material's tag set.
        source_tags = {
            (t.tag_category, t.tag_value)
            for t in db.query(CreativeVisualTag).filter(
                CreativeVisualTag.material_id == combo.material_id
            ).all()
        }
        if not source_tags:
            return _api_response(data={
                "items": [], "source_combo_id": combo_id,
                "note": "Source material has no visual tags yet — wait for the vision tagger.",
            })

        # Count overlapping tags per OTHER material.
        or_clauses = [
            (CreativeVisualTag.tag_category == cat) & (CreativeVisualTag.tag_value == val)
            for cat, val in source_tags
        ]
        overlap_rows = (
            db.query(
                CreativeVisualTag.material_id,
                func.count(
                    func.distinct(
                        CreativeVisualTag.tag_category + ":" + CreativeVisualTag.tag_value
                    )
                ).label("shared"),
            )
            .filter(or_(*or_clauses))
            .filter(CreativeVisualTag.material_id != combo.material_id)
            .group_by(CreativeVisualTag.material_id)
            .all()
        )
        shared_by_material = {r[0]: r[1] for r in overlap_rows}
        if not shared_by_material:
            return _api_response(data={
                "items": [], "source_combo_id": combo_id,
                "note": "No combos share visual tags with this one.",
            })

        # Pull candidate combos (exclude self), apply scope.
        cand = (
            db.query(AdCombo, AdCopy, AdMaterial, AdAccount)
            .outerjoin(AdCopy, AdCopy.copy_id == AdCombo.copy_id)
            .outerjoin(AdMaterial, AdMaterial.material_id == AdCombo.material_id)
            .outerjoin(AdAccount, AdAccount.id == AdCombo.branch_id)
            .filter(AdCombo.material_id.in_(shared_by_material.keys()))
            .filter(AdCombo.combo_id != combo_id)
        )
        if same_branch:
            cand = cand.filter(AdCombo.branch_id == combo.branch_id)
        elif scoped_ids is not None:
            cand = cand.filter(AdCombo.branch_id.in_(scoped_ids or ["__no_match__"]))

        rows = cand.all()
        # Rank: shared-tag count desc, then ROAS desc.
        rows.sort(
            key=lambda r: (
                shared_by_material.get(r[0].material_id, 0),
                float(r[0].roas) if r[0].roas is not None else -1.0,
            ),
            reverse=True,
        )

        items = [
            _serialize_combo_row(
                combo_, copy, material, branch,
                extra={
                    "shared_tag_count": shared_by_material.get(combo_.material_id, 0),
                    "source_tag_count": len(source_tags),
                },
            )
            for combo_, copy, material, branch in rows[:limit]
        ]
        return _api_response(data={
            "items": items,
            "source_combo_id": combo_id,
            "source_tag_count": len(source_tags),
        })
    except Exception as e:
        return _api_response(error=str(e))
