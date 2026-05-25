"""Creative Library CRUD: keypoints, angles, copies, materials, combos."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_page, require_section
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint
from app.models.user import User
from app.services.country_utils import country_name, is_valid_country
from app.services.creative_service import (
    auto_classify_all_combos, classify_verdict, next_angle_id, next_combo_id,
    next_copy_id, next_material_id, propagate_derived_verdicts,
)
from app.services.parse_utils import parse_campaign_metadata

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Keypoints ─────────────────────────────────────────────


class KeypointCreate(BaseModel):
    branch_id: str
    category: str  # location | amenity | experience | value
    title: str


@router.get("/keypoints")
def list_keypoints(
    branch_id: str | None = None,
    category: str | None = None,
    target_audience: str | None = None,
    country: str | None = None,
    current_user: User = Depends(require_page("keypoints")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        q = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True))
        if branch_id:
            q = q.filter(BranchKeypoint.branch_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(BranchKeypoint.branch_id.in_(scoped_ids or ["__no_match__"]))
        if category:
            q = q.filter(BranchKeypoint.category == category)
        rows = q.order_by(BranchKeypoint.category, BranchKeypoint.title).all()

        # Aggregate combo metrics per keypoint. The target_audience / country
        # filters narrow which combos feed the metrics + verdict (combined as
        # AND) — this is how we learn which keypoints win for Solo vs Couple,
        # for JP vs PH traffic, or any slice of the two. The benchmark below
        # stays branch-wide so the WIN bar is a stable, cross-slice baseline
        # (the branch's overall ROAS).
        combo_q = db.query(AdCombo).filter(AdCombo.keypoint_ids.isnot(None))
        if target_audience:
            combo_q = combo_q.filter(AdCombo.target_audience == target_audience)
        if country:
            combo_q = combo_q.filter(AdCombo.country == country)
        all_combos = combo_q.all()
        kp_metrics: dict[str, dict] = {}
        for combo in all_combos:
            ids = combo.keypoint_ids if isinstance(combo.keypoint_ids, list) else []
            for kid in ids:
                if kid not in kp_metrics:
                    kp_metrics[kid] = {"combos": 0, "spend": 0, "revenue": 0, "impressions": 0, "clicks": 0, "conversions": 0}
                m = kp_metrics[kid]
                m["combos"] += 1
                m["spend"] += float(combo.spend or 0)
                m["revenue"] += float(combo.revenue or 0)
                m["impressions"] += int(combo.impressions or 0)
                m["clicks"] += int(combo.clicks or 0)
                m["conversions"] += int(combo.conversions or 0)

        # Compute benchmark ROAS per branch (total revenue / total spend)
        from sqlalchemy import func as sqlfunc
        bench_rows = db.query(
            AdCombo.branch_id,
            sqlfunc.sum(AdCombo.spend).label("s"),
            sqlfunc.sum(AdCombo.revenue).label("r"),
        ).group_by(AdCombo.branch_id).all()
        benchmarks: dict[str, float] = {}
        for br in bench_rows:
            s = float(br.s or 0)
            rv = float(br.r or 0)
            benchmarks[br.branch_id] = rv / s if s > 0 else 0

        result = []
        for r in rows:
            m = kp_metrics.get(r.id, {})
            spend = m.get("spend", 0)
            revenue = m.get("revenue", 0)
            impressions = m.get("impressions", 0)
            clicks = m.get("clicks", 0)
            conversions = m.get("conversions", 0)
            roas = revenue / spend if spend > 0 else 0
            bench = benchmarks.get(r.branch_id, 0)
            verdict = classify_verdict(clicks, conversions, roas, bench) if m.get("combos", 0) > 0 else "TEST"
            result.append({
                "id": r.id, "branch_id": r.branch_id, "category": r.category,
                "title": r.title,
                "combos": m.get("combos", 0),
                "spend": spend,
                "revenue": revenue,
                "roas": roas,
                "clicks": clicks,
                "conversions": conversions,
                "ctr": clicks / impressions if impressions > 0 else 0,
                "benchmark_roas": bench,
                "verdict": verdict,
            })
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/keypoints/facets")
def keypoint_facets(
    current_user: User = Depends(require_page("keypoints")),
    db: Session = Depends(get_db),
):
    """Distinct filter values for the keypoints page. Countries come from real
    combo data; target audiences come from the fixed TA_WHITELIST on the
    frontend.

    Lists every country on the branch's combos (not just keypoint-tagged ones)
    so the dropdown stays useful even when keypoint assignment is sparse. Only
    known ISO codes (+ the 'ALL' multi-country marker) are returned — this
    drops parse junk like '25' / '[E' / CJK fragments from badly-named adsets.
    Each entry carries a display name so the UI can show 'Japan' not 'JP'."""
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)
        q = db.query(AdCombo.country).filter(AdCombo.country.isnot(None))
        if scoped_ids is not None:
            q = q.filter(AdCombo.branch_id.in_(scoped_ids or ["__no_match__"]))
        codes = {c.upper() for (c,) in q.distinct().all() if is_valid_country(c)}
        countries = sorted(
            ({"code": c, "name": country_name(c)} for c in codes),
            key=lambda x: x["name"],
        )
        return _api_response(data={"countries": countries})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/keypoints")
def create_keypoint(
    body: KeypointCreate,
    current_user: User = Depends(require_page("keypoints", "edit")),
    db: Session = Depends(get_db),
):
    try:
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        kp = BranchKeypoint(branch_id=body.branch_id, category=body.category, title=body.title)
        db.add(kp)
        db.commit()
        db.refresh(kp)
        return _api_response(data={"id": kp.id, "branch_id": kp.branch_id, "category": kp.category, "title": kp.title})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.delete("/keypoints/{kp_id}")
def delete_keypoint(
    kp_id: str,
    current_user: User = Depends(require_page("keypoints", "edit")),
    db: Session = Depends(get_db),
):
    try:
        kp = db.query(BranchKeypoint).filter(BranchKeypoint.id == kp_id).first()
        if not kp:
            return _api_response(error="Keypoint not found")
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=kp.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        kp.is_active = False
        db.commit()
        return _api_response(data={"id": kp.id, "is_active": False})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── Ad Angles ─────────────────────────────────────────────


class AngleCreate(BaseModel):
    branch_id: str | None = None
    angle_type: str  # One of 13 fixed angle types
    angle_explain: str  # Strategic explanation — WHY
    hook_examples: list[str] | None = None  # Array of hook lines
    status: str = "TEST"
    notes: str | None = None
    created_by: str | None = None


class AngleUpdate(BaseModel):
    angle_type: str | None = None
    angle_explain: str | None = None
    hook_examples: list[str] | None = None
    status: str | None = None
    notes: str | None = None


@router.get("/angles")
def list_angles(
    branch_id: str | None = None,
    status: str | None = None,
    current_user: User = Depends(require_page("angles")),
    db: Session = Depends(get_db),
):
    try:
        # Angles are global (branch_id = NULL for all). Branch filter scopes
        # the combo metrics below, not the angle list itself.
        # Status filter is applied AFTER computing branch_verdict (see bottom):
        # with a branch, we filter by the computed verdict shown in the UI
        # (not the static AdAngle.status column, which stays "TEST" by default).
        rows = db.query(AdAngle).order_by(AdAngle.angle_id).all()

        # Aggregate combo metrics per angle — scoped to branch if provided
        combo_q = db.query(AdCombo).filter(AdCombo.angle_id.isnot(None))
        if branch_id:
            combo_q = combo_q.filter(AdCombo.branch_id == branch_id)
        angle_combos = combo_q.all()

        # Branch benchmark ROAS = total revenue / total spend of all combos in that branch.
        # Used to derive per-branch verdict for each angle (WIN/TEST/LOSE).
        branch_benchmark = 0.0
        if branch_id:
            branch_combos = db.query(AdCombo).filter(AdCombo.branch_id == branch_id).all()
            b_spend = sum(float(c.spend or 0) for c in branch_combos)
            b_rev = sum(float(c.revenue or 0) for c in branch_combos)
            branch_benchmark = b_rev / b_spend if b_spend > 0 else 0.0
        ang_metrics: dict[str, dict] = {}
        for combo in angle_combos:
            aid = combo.angle_id
            if aid not in ang_metrics:
                ang_metrics[aid] = {"combos": 0, "spend": 0, "revenue": 0, "impressions": 0, "clicks": 0, "conversions": 0,
                                    "hook_rates": [], "thruplay_rates": [], "eng_rates": []}
            m = ang_metrics[aid]
            m["combos"] += 1
            m["spend"] += float(combo.spend or 0)
            m["revenue"] += float(combo.revenue or 0)
            m["impressions"] += int(combo.impressions or 0)
            m["clicks"] += int(combo.clicks or 0)
            m["conversions"] += int(combo.conversions or 0)
            if combo.hook_rate: m["hook_rates"].append(float(combo.hook_rate))
            if combo.thruplay_rate: m["thruplay_rates"].append(float(combo.thruplay_rate))
            if combo.engagement_rate: m["eng_rates"].append(float(combo.engagement_rate))
            m.setdefault("linked_ads", []).append({"combo_id": combo.combo_id, "ad_name": combo.ad_name, "roas": float(combo.roas) if combo.roas else None})

        result = []
        for r in rows:
            m = ang_metrics.get(r.angle_id, {})
            spend = m.get("spend", 0)
            revenue = m.get("revenue", 0)
            impressions = m.get("impressions", 0)
            clicks = m.get("clicks", 0)
            conversions = m.get("conversions", 0)
            hook_rates = m.get("hook_rates", [])
            thruplay_rates = m.get("thruplay_rates", [])
            eng_rates = m.get("eng_rates", [])
            roas = revenue / spend if spend > 0 else 0

            # Per-branch verdict using angle rules (2x combo thresholds):
            # TEST if clicks ≤ 9,000 AND bookings < 10, else WIN/LOSE vs branch benchmark.
            branch_verdict = None
            if branch_id:
                if clicks <= 9000 and conversions < 10:
                    branch_verdict = "TEST"
                elif branch_benchmark > 0 and roas >= branch_benchmark:
                    branch_verdict = "WIN"
                else:
                    branch_verdict = "LOSE"

            # Status filter: when branch_id is set, filter on the computed
            # branch_verdict (what the UI badge shows); otherwise fall back to
            # the static AdAngle.status column.
            if status:
                effective = branch_verdict if branch_id else r.status
                if effective != status:
                    continue

            result.append({
                "id": r.id, "angle_id": r.angle_id, "branch_id": r.branch_id,
                "angle_type": r.angle_type or r.hook or "",
                "angle_explain": r.angle_explain or "",
                "hook_examples": r.hook_examples or [],
                "status": r.status, "notes": r.notes, "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "combos": m.get("combos", 0),
                "spend": spend,
                "revenue": revenue,
                "roas": roas,
                "conversions": conversions,
                "ctr": clicks / impressions if impressions > 0 else 0,
                "avg_hook_rate": sum(hook_rates) / len(hook_rates) if hook_rates else None,
                "avg_thruplay_rate": sum(thruplay_rates) / len(thruplay_rates) if thruplay_rates else None,
                "avg_engagement_rate": sum(eng_rates) / len(eng_rates) if eng_rates else None,
                "linked_ads": m.get("linked_ads", []),
                "branch_verdict": branch_verdict,
                "branch_benchmark": branch_benchmark if branch_id else None,
            })
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/angles")
def create_angle(
    body: AngleCreate,
    current_user: User = Depends(require_page("angles", "edit")),
    db: Session = Depends(get_db),
):
    try:
        aid = next_angle_id(db)
        angle = AdAngle(
            angle_id=aid, branch_id=body.branch_id, angle_type=body.angle_type,
            angle_explain=body.angle_explain, hook_examples=body.hook_examples,
            angle_text=body.angle_explain or "", target_audience="",
            status=body.status, notes=body.notes, created_by=body.created_by,
        )
        db.add(angle)
        db.commit()
        db.refresh(angle)
        return _api_response(data={"id": angle.id, "angle_id": aid, "status": angle.status})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.patch("/angles/{angle_id}")
def update_angle(
    angle_id: str,
    body: AngleUpdate,
    current_user: User = Depends(require_page("angles", "edit")),
    db: Session = Depends(get_db),
):
    try:
        angle = db.query(AdAngle).filter(AdAngle.angle_id == angle_id).first()
        if not angle:
            return _api_response(error="Angle not found")
        if body.angle_type is not None:
            angle.angle_type = body.angle_type
        if body.angle_explain is not None:
            angle.angle_explain = body.angle_explain
            angle.angle_text = body.angle_explain  # keep legacy in sync
        if body.hook_examples is not None:
            angle.hook_examples = body.hook_examples
        if body.status is not None:
            angle.status = body.status
        if body.notes is not None:
            angle.notes = body.notes
        db.commit()
        return _api_response(data={"angle_id": angle.angle_id, "status": angle.status})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── Ad Copies ─────────────────────────────────────────────


class CopyCreate(BaseModel):
    branch_id: str
    target_audience: str
    angle_id: str | None = None
    headline: str
    body_text: str
    cta: str | None = None
    language: str = "en"


@router.get("/copies")
def list_copies(
    branch_id: str | None = None, target_audience: str | None = None,
    limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        q = db.query(AdCopy)
        if branch_id:
            q = q.filter(AdCopy.branch_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdCopy.branch_id.in_(scoped_ids or ["__no_match__"]))
        if target_audience:
            q = q.filter(AdCopy.target_audience == target_audience)
        total = q.count()
        rows = q.order_by(AdCopy.copy_id).offset(offset).limit(limit).all()
        return _api_response(data={"items": [{
            "id": r.id, "copy_id": r.copy_id, "branch_id": r.branch_id,
            "target_audience": r.target_audience, "angle_id": r.angle_id,
            "headline": r.headline, "body_text": r.body_text, "cta": r.cta,
            "language": r.language, "derived_verdict": r.derived_verdict,
        } for r in rows], "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/copies")
def create_copy(
    body: CopyCreate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        cid = next_copy_id(db)
        copy = AdCopy(
            copy_id=cid, branch_id=body.branch_id, target_audience=body.target_audience,
            angle_id=body.angle_id, headline=body.headline, body_text=body.body_text,
            cta=body.cta, language=body.language,
        )
        db.add(copy)
        db.commit()
        db.refresh(copy)
        return _api_response(data={"id": copy.id, "copy_id": cid})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── Ad Materials ──────────────────────────────────────────


class MaterialCreate(BaseModel):
    branch_id: str
    material_type: str  # image | video | carousel
    file_url: str
    description: str | None = None
    target_audience: str | None = None


@router.get("/materials")
def list_materials(
    branch_id: str | None = None, material_type: str | None = None,
    limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        q = db.query(AdMaterial)
        if branch_id:
            q = q.filter(AdMaterial.branch_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdMaterial.branch_id.in_(scoped_ids or ["__no_match__"]))
        if material_type:
            q = q.filter(AdMaterial.material_type == material_type)
        total = q.count()
        rows = q.order_by(AdMaterial.material_id).offset(offset).limit(limit).all()
        return _api_response(data={"items": [{
            "id": r.id, "material_id": r.material_id, "branch_id": r.branch_id,
            "material_type": r.material_type, "file_url": r.file_url,
            "description": r.description, "target_audience": r.target_audience,
            "derived_verdict": r.derived_verdict, "url_source": r.url_source,
        } for r in rows], "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/materials")
def create_material(
    body: MaterialCreate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        mid = next_material_id(db)
        mat = AdMaterial(
            material_id=mid, branch_id=body.branch_id, material_type=body.material_type,
            file_url=body.file_url, description=body.description, target_audience=body.target_audience,
            url_source="manual",  # designer-created → protect from weekly Meta sync overwrite
        )
        db.add(mat)
        db.commit()
        db.refresh(mat)
        return _api_response(data={"id": mat.id, "material_id": mid})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


class MaterialUpdate(BaseModel):
    file_url: str | None = None
    description: str | None = None
    target_audience: str | None = None
    material_type: str | None = None


@router.patch("/materials/{material_id}")
def update_material(
    material_id: str,
    body: MaterialUpdate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Update a material. If file_url is provided, marks url_source='manual' so the
    weekly Meta sync task will not overwrite the designer's custom URL."""
    try:
        mat = db.query(AdMaterial).filter(AdMaterial.material_id == material_id).first()
        if not mat:
            return _api_response(error=f"material {material_id} not found")
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=mat.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)

        if body.file_url is not None:
            mat.file_url = body.file_url
            mat.url_source = "manual"
        if body.description is not None:
            mat.description = body.description
        if body.target_audience is not None:
            mat.target_audience = body.target_audience
        if body.material_type is not None:
            mat.material_type = body.material_type

        db.commit()
        return _api_response(data={"material_id": material_id, "url_source": mat.url_source})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── Ad Combos ─────────────────────────────────────────────


class ComboCreate(BaseModel):
    branch_id: str
    ad_name: str | None = None
    target_audience: str | None = None
    keypoint_ids: list[str] | None = None
    angle_id: str | None = None
    copy_id: str
    material_id: str
    campaign_id: str | None = None
    verdict: str = "TEST"
    verdict_notes: str | None = None


class VerdictUpdate(BaseModel):
    verdict: str  # WIN | TEST | LOSE
    verdict_notes: str | None = None


@router.get("/combos")
def list_combos(
    branch_id: str | None = None, verdict: str | None = None,
    target_audience: str | None = None, country: str | None = None,
    sort_by: str | None = None, sort_dir: str = "desc",
    limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        q = db.query(AdCombo)
        if branch_id:
            q = q.filter(AdCombo.branch_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdCombo.branch_id.in_(scoped_ids or ["__no_match__"]))
        if verdict:
            q = q.filter(AdCombo.verdict == verdict)
        if target_audience:
            q = q.filter(AdCombo.target_audience == target_audience)
        if country:
            q = q.filter(AdCombo.country == country)
        total = q.count()

        # Sorting
        sort_map = {
            "roas": AdCombo.roas, "spend": AdCombo.spend, "ctr": AdCombo.ctr,
            "hook_rate": AdCombo.hook_rate, "thruplay_rate": AdCombo.thruplay_rate,
            "engagement_rate": AdCombo.engagement_rate, "cost_per_purchase": AdCombo.cost_per_purchase,
            "conversions": AdCombo.conversions, "video_complete_rate": AdCombo.video_complete_rate,
        }
        sort_col = sort_map.get(sort_by)
        if sort_col is not None:
            q = q.order_by(sort_col.desc().nullslast() if sort_dir == "desc" else sort_col.asc().nullsfirst())
        else:
            q = q.order_by(AdCombo.combo_id)

        rows = q.offset(offset).limit(limit).all()
        # Fetch keypoint titles and angle texts for display
        from app.models.keypoint import BranchKeypoint as KP
        all_kp_ids = set()
        for r in rows:
            if r.keypoint_ids:
                ids = r.keypoint_ids if isinstance(r.keypoint_ids, list) else []
                all_kp_ids.update(ids)
        kp_map = {}
        if all_kp_ids:
            kps = db.query(KP).filter(KP.id.in_(all_kp_ids)).all()
            kp_map = {k.id: k.title for k in kps}

        ang_ids = {r.angle_id for r in rows if r.angle_id}
        ang_map = {}
        if ang_ids:
            angs = db.query(AdAngle).filter(AdAngle.angle_id.in_(ang_ids)).all()
            ang_map = {a.angle_id: {"angle_type": a.angle_type or a.hook or "", "explain": a.angle_explain or "", "status": a.status, "ta": a.target_audience} for a in angs}

        # Compute benchmark ROAS per account
        from app.models.account import AdAccount as Acc
        from sqlalchemy import func as sqlfunc
        bench_rows = db.query(
            AdCombo.branch_id,
            sqlfunc.sum(AdCombo.spend).label("s"),
            sqlfunc.sum(AdCombo.revenue).label("r"),
        ).group_by(AdCombo.branch_id).all()
        benchmarks = {}
        for br in bench_rows:
            s = float(br.s or 0)
            r = float(br.r or 0)
            benchmarks[br.branch_id] = r / s if s > 0 else 0

        return _api_response(data={"items": [{
            "id": r.id, "combo_id": r.combo_id, "branch_id": r.branch_id,
            "ad_name": r.ad_name,
            "target_audience": r.target_audience, "country": r.country,
            "keypoint_ids": r.keypoint_ids or [],
            "keypoint_titles": [kp_map.get(kid, "") for kid in (r.keypoint_ids or []) if kp_map.get(kid)],
            "angle_id": r.angle_id,
            "angle_type": ang_map.get(r.angle_id, {}).get("angle_type", ""),
            "angle_explain": ang_map.get(r.angle_id, {}).get("explain", ""),
            "angle_status": ang_map.get(r.angle_id, {}).get("status", ""),
            "copy_id": r.copy_id, "material_id": r.material_id,
            "campaign_id": r.campaign_id, "verdict": r.verdict,
            "verdict_source": r.verdict_source, "verdict_notes": r.verdict_notes,
            "spend": float(r.spend) if r.spend else None,
            "impressions": r.impressions, "clicks": r.clicks,
            "conversions": r.conversions,
            "revenue": float(r.revenue) if r.revenue else None,
            "roas": float(r.roas) if r.roas else None,
            "cost_per_purchase": float(r.cost_per_purchase) if r.cost_per_purchase else None,
            "ctr": float(r.ctr) if r.ctr else None,
            "engagement": r.engagement,
            "engagement_rate": float(r.engagement_rate) if r.engagement_rate else None,
            "video_plays": r.video_plays,
            "hook_rate": float(r.hook_rate) if r.hook_rate else None,
            "thruplay_rate": float(r.thruplay_rate) if r.thruplay_rate else None,
            "video_complete_rate": float(r.video_complete_rate) if r.video_complete_rate else None,
            "benchmark_roas": benchmarks.get(r.branch_id, 0),
        } for r in rows], "total": total, "benchmarks": benchmarks})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/combos")
def create_combo(
    body: ComboCreate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)

        # A combo is uniquely identified by (copy_id, material_id). If a row
        # already exists for that pair, reuse it so the caller can continue
        # the submit-for-approval flow instead of hitting a unique-constraint
        # error.
        existing = (
            db.query(AdCombo)
            .filter(AdCombo.copy_id == body.copy_id, AdCombo.material_id == body.material_id)
            .first()
        )
        if existing:
            return _api_response(data={
                "id": existing.id,
                "combo_id": existing.combo_id,
                "verdict": existing.verdict,
                "reused": True,
                "ad_name": existing.ad_name,
            })

        cid = next_combo_id(db)
        combo = AdCombo(
            combo_id=cid, branch_id=body.branch_id,
            ad_name=body.ad_name, target_audience=body.target_audience,
            keypoint_ids=body.keypoint_ids, angle_id=body.angle_id,
            copy_id=body.copy_id, material_id=body.material_id,
            campaign_id=body.campaign_id,
            verdict=body.verdict, verdict_source="manual", verdict_notes=body.verdict_notes,
        )
        db.add(combo)
        db.commit()
        db.refresh(combo)
        propagate_derived_verdicts(db)
        return _api_response(data={"id": combo.id, "combo_id": cid, "verdict": combo.verdict, "reused": False})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


class ComboUpdate(BaseModel):
    angle_id: str | None = None
    keypoint_ids: list[str] | None = None


@router.patch("/combos/{combo_id}")
def update_combo(
    combo_id: str,
    body: ComboUpdate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Update combo's angle and/or keypoints."""
    try:
        combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
        if not combo:
            return _api_response(error="Combo not found")
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=combo.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        if body.angle_id is not None:
            combo.angle_id = body.angle_id if body.angle_id else None
        if body.keypoint_ids is not None:
            combo.keypoint_ids = body.keypoint_ids if body.keypoint_ids else None
        db.commit()
        return _api_response(data={"combo_id": combo.combo_id, "angle_id": combo.angle_id, "keypoint_ids": combo.keypoint_ids})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.patch("/combos/{combo_id}/verdict")
def update_verdict(
    combo_id: str,
    body: VerdictUpdate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
        if not combo:
            return _api_response(error="Combo not found")
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=combo.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)
        combo.verdict = body.verdict
        combo.verdict_source = "manual"
        combo.verdict_notes = body.verdict_notes
        db.commit()
        propagate_derived_verdicts(db)
        return _api_response(data={"combo_id": combo.combo_id, "verdict": combo.verdict})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


class QuickComboCreate(BaseModel):
    branch_id: str
    ad_name: str
    creative_url: str  # Figma / Drive / external link
    creative_type: str = "image"  # image | video | carousel
    headline: str
    primary_text: str
    cta: str | None = None
    language: str = "en"
    target_audience: str | None = None
    keypoint_ids: list[str] | None = None
    angle_id: str | None = None


@router.post("/combos/quick-create")
def quick_create_combo(
    body: QuickComboCreate,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Create Material + Copy + Combo in one step.

    Designed for the approval submission flow: user provides creative link,
    headline, and primary text — system creates all three records automatically.
    """
    try:
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id, min_level="edit"
        )
        if not ok:
            return _api_response(error=err)

        # 1. Create Material
        mid = next_material_id(db)
        material = AdMaterial(
            material_id=mid,
            branch_id=body.branch_id,
            material_type=body.creative_type,
            file_url=body.creative_url,
            description=body.ad_name,
            target_audience=body.target_audience,
        )
        db.add(material)
        db.flush()

        # 2. Create Copy
        cid = next_copy_id(db)
        copy = AdCopy(
            copy_id=cid,
            branch_id=body.branch_id,
            target_audience=body.target_audience or "",
            headline=body.headline,
            body_text=body.primary_text,
            cta=body.cta,
            language=body.language,
        )
        db.add(copy)
        db.flush()

        # 3. Create Combo
        combo_id = next_combo_id(db)
        combo = AdCombo(
            combo_id=combo_id,
            branch_id=body.branch_id,
            ad_name=body.ad_name,
            target_audience=body.target_audience,
            keypoint_ids=body.keypoint_ids,
            angle_id=body.angle_id,
            copy_id=cid,
            material_id=mid,
            verdict="TEST",
            verdict_source="manual",
        )
        db.add(combo)
        db.commit()
        db.refresh(combo)

        return _api_response(data={
            "id": combo.id,
            "combo_id": combo_id,
            "material_id": mid,
            "copy_id": cid,
            "ad_name": combo.ad_name,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/combos/auto-classify")
def auto_classify(
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Auto-classify all combos: TEST (clicks<=4500 or bookings<5), WIN (ROAS>=benchmark), LOSE (ROAS<benchmark)."""
    try:
        updated = auto_classify_all_combos(db)
        combos = db.query(AdCombo).all()
        from collections import Counter
        verdicts = dict(Counter(c.verdict for c in combos))
        return _api_response(data={"updated": updated, "verdicts": verdicts})
    except Exception as e:
        return _api_response(error=str(e))


# ── Analytics: Evaluate keypoints & angles by combo data ──


@router.get("/analytics/by-keypoint")
def analytics_by_keypoint(
    branch_id: str | None = None,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Aggregate combo performance grouped by keypoint."""
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        # A combo carries a JSON array of keypoint ids (a combo can target
        # multiple keypoints), so we can't GROUP BY a column — expand the
        # array in Python and accumulate per keypoint id, mirroring
        # list_keypoints above.
        combo_q = db.query(AdCombo).filter(AdCombo.keypoint_ids.isnot(None))
        if branch_id:
            combo_q = combo_q.filter(AdCombo.branch_id == branch_id)
        elif scoped_ids is not None:
            combo_q = combo_q.filter(AdCombo.branch_id.in_(scoped_ids or ["__no_match__"]))

        kp_metrics: dict[str, dict] = {}
        for combo in combo_q.all():
            ids = combo.keypoint_ids if isinstance(combo.keypoint_ids, list) else []
            for kid in ids:
                if kid not in kp_metrics:
                    kp_metrics[kid] = {"combo_count": 0, "spend": 0, "revenue": 0, "clicks": 0, "conversions": 0}
                m = kp_metrics[kid]
                m["combo_count"] += 1
                m["spend"] += float(combo.spend or 0)
                m["revenue"] += float(combo.revenue or 0)
                m["clicks"] += int(combo.clicks or 0)
                m["conversions"] += int(combo.conversions or 0)

        kp_map = {}
        if kp_metrics:
            from app.models.keypoint import BranchKeypoint as KP
            kps = db.query(KP).filter(KP.id.in_(list(kp_metrics.keys()))).all()
            kp_map = {k.id: {"title": k.title, "category": k.category} for k in kps}

        result = []
        for kid, m in kp_metrics.items():
            kp = kp_map.get(kid, {})
            spend = m["spend"]
            revenue = m["revenue"]
            result.append({
                "keypoint_id": kid,
                "keypoint_title": kp.get("title", ""),
                "category": kp.get("category", ""),
                "combo_count": m["combo_count"],
                "spend": spend,
                "revenue": revenue,
                "roas": revenue / spend if spend > 0 else 0,
                "clicks": m["clicks"],
                "conversions": m["conversions"],
            })
        result.sort(key=lambda x: x["roas"], reverse=True)
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/analytics/by-angle")
def analytics_by_angle(
    branch_id: str | None = None,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Aggregate combo performance grouped by angle."""
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        from sqlalchemy import func
        q = db.query(
            AdCombo.angle_id,
            func.count(AdCombo.id).label("combo_count"),
            func.sum(AdCombo.spend).label("spend"),
            func.sum(AdCombo.impressions).label("impressions"),
            func.sum(AdCombo.clicks).label("clicks"),
            func.sum(AdCombo.conversions).label("conversions"),
            func.sum(AdCombo.revenue).label("revenue"),
        ).filter(AdCombo.angle_id.isnot(None))

        if branch_id:
            q = q.filter(AdCombo.branch_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdCombo.branch_id.in_(scoped_ids or ["__no_match__"]))

        rows = q.group_by(AdCombo.angle_id).all()

        ang_ids = [r.angle_id for r in rows]
        ang_map = {}
        if ang_ids:
            angs = db.query(AdAngle).filter(AdAngle.angle_id.in_(ang_ids)).all()
            ang_map = {a.angle_id: {"text": a.angle_text, "ta": a.target_audience, "status": a.status} for a in angs}

        result = []
        for r in rows:
            ang = ang_map.get(r.angle_id, {})
            spend = float(r.spend or 0)
            revenue = float(r.revenue or 0)
            result.append({
                "angle_id": r.angle_id,
                "angle_text": ang.get("text", ""),
                "target_audience": ang.get("ta", ""),
                "current_status": ang.get("status", ""),
                "combo_count": r.combo_count,
                "spend": spend,
                "revenue": revenue,
                "roas": revenue / spend if spend > 0 else 0,
                "clicks": int(r.clicks or 0),
                "conversions": int(r.conversions or 0),
            })
        result.sort(key=lambda x: x["roas"], reverse=True)
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


# ── Admin / Backfill ──────────────────────────────────────


@router.post("/creative/reparse-ta")
def reparse_target_audience(
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Re-parse target_audience on existing combos, copies, and materials using
    the canonical TA_WHITELIST. One-shot cleanup after the parser fix — earlier
    sync runs stored invalid values like 'Family' or mis-categorised 'Friend'
    ads as 'Group'.

    Combos are authoritative (ad_name preserved). Copies and materials get TA
    propagated from the combo that references them; orphans fall back to
    re-parsing their own headline/description. Rows that still parse to
    'Unknown' are left untouched to avoid clobbering manual edits.
    """
    try:
        updated = {"combos": 0, "copies": 0, "materials": 0}

        combos = db.query(AdCombo).all()
        copy_ta: dict[str, str] = {}
        material_ta: dict[str, str] = {}

        for combo in combos:
            new_ta = parse_campaign_metadata(combo.ad_name or "")["ta"]
            if new_ta == "Unknown":
                continue
            if combo.target_audience != new_ta:
                combo.target_audience = new_ta
                updated["combos"] += 1
            if combo.copy_id:
                copy_ta[combo.copy_id] = new_ta
            if combo.material_id:
                material_ta[combo.material_id] = new_ta

        for m in db.query(AdMaterial).all():
            new_ta = material_ta.get(m.material_id) or parse_campaign_metadata(m.description or "")["ta"]
            if new_ta == "Unknown":
                continue
            if m.target_audience != new_ta:
                m.target_audience = new_ta
                updated["materials"] += 1

        for c in db.query(AdCopy).all():
            new_ta = copy_ta.get(c.copy_id) or parse_campaign_metadata(c.headline or "")["ta"]
            if new_ta == "Unknown":
                continue
            if c.target_audience != new_ta:
                c.target_audience = new_ta
                updated["copies"] += 1

        db.commit()
        return _api_response(data=updated)
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
