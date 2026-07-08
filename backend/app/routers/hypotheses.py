"""Creative Hypotheses API — Learning Engine."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ad_combo import AdCombo
from app.models.brand_identity import BrandIdentity
from app.models.creative_hypothesis import CreativeHypothesis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])

HYPOTHESIS_STATUSES = ["pending", "running", "validated", "refuted", "inconclusive"]


class HypothesisSuggestRequest(BaseModel):
    branch_name: str
    human_desire: str
    hypothesis_category: Optional[str] = None
    customer_insight: Optional[str] = None
    creative_angle: Optional[str] = None
    target_audience: Optional[str] = None
    market: Optional[str] = None
    primary_kpi: Optional[str] = None


class HypothesisCreate(BaseModel):
    branch_name: str
    combo_id: Optional[str] = None
    angle_id: Optional[str] = None
    hypothesis_category: Optional[str] = None
    customer_insight: Optional[str] = None
    human_desire: Optional[str] = None
    creative_angle: Optional[str] = None
    target_audience: Optional[str] = None
    market: Optional[str] = None
    hypothesis: str
    variable_tested: Optional[str] = None
    # Layer A verdict setup
    funnel_stage: Optional[str] = None        # Stop|Hold|Click|Downstream
    format: Optional[str] = None             # Image|Video
    primary_metric: Optional[str] = None     # pre-registered primary metric
    win_threshold: Optional[float] = None    # pre-registered threshold value
    min_sample: Optional[int] = 5            # verdict gate
    primary_kpi: Optional[str] = None
    secondary_kpi: Optional[str] = None
    expected_outcome: Optional[str] = None
    created_by: Optional[str] = None
    # 4-tier links (optional at creation)
    research_question_id: Optional[str] = None  # UUID string
    knowledge_links: Optional[list[str]] = None
    parent_hypothesis_id: Optional[str] = None  # UUID string


class BriefAnalysisRequest(BaseModel):
    brief_text: str
    script_text: str


class VisionAnalysisRequest(BaseModel):
    image_urls: Optional[list[str]] = None  # base64 data: URLs or http(s); auto-pulled from combo if omitted


class HypothesisResultUpdate(BaseModel):
    status: str
    actual_ctr: Optional[float] = None
    actual_cvr: Optional[float] = None
    actual_roas: Optional[float] = None
    actual_spend: Optional[float] = None
    confounding_factors: Optional[list[str]] = None
    confidence_level: Optional[str] = None
    confidence_score: Optional[float] = None
    learning: Optional[str] = None
    result_notes: Optional[str] = None
    # Layer B (downstream) verdict — set independently of creative verdict
    layer_b_status: Optional[str] = None   # pass|fail|insufficient
    layer_b_notes: Optional[str] = None
    # 4-tier links
    principle_id: Optional[str] = None   # UUID string
    research_question_id: Optional[str] = None
    knowledge_links: Optional[list[str]] = None


def _next_hypothesis_id(db: Session) -> str:
    last = (
        db.query(CreativeHypothesis)
        .order_by(desc(CreativeHypothesis.created_at))
        .first()
    )
    if not last or not last.hypothesis_id:
        return "HYP-001"
    try:
        num = int(last.hypothesis_id.split("-")[1]) + 1
    except (IndexError, ValueError):
        num = 1
    return f"HYP-{num:03d}"


def _serialize(h: CreativeHypothesis, combo: AdCombo | None = None, approval_status: Optional[str] = None, principle_title: Optional[str] = None) -> dict:
    clicks = int(combo.clicks or 0) if combo else None
    conversions = int(combo.conversions or 0) if combo else None
    return {
        "id": str(h.id),
        "hypothesis_id": h.hypothesis_id,
        "branch_name": h.branch_name,
        "combo_id": str(h.combo_id) if h.combo_id else None,
        "ad_name": combo.ad_name if combo else None,
        "combo_clicks": clicks,
        "combo_conversions": conversions,
        "angle_id": str(h.angle_id) if h.angle_id else None,
        "hypothesis_category": h.hypothesis_category,
        "customer_insight": h.customer_insight,
        "human_desire": h.human_desire,
        "creative_angle": h.creative_angle,
        "target_audience": h.target_audience,
        "market": h.market,
        "hypothesis": h.hypothesis,
        "variable_tested": h.variable_tested,
        "primary_kpi": h.primary_kpi,
        "secondary_kpi": h.secondary_kpi,
        "expected_outcome": h.expected_outcome,
        "status": h.status,
        "actual_ctr": float(h.actual_ctr) if h.actual_ctr else None,
        "actual_cvr": float(h.actual_cvr) if h.actual_cvr else None,
        "actual_roas": float(h.actual_roas) if h.actual_roas else None,
        "actual_spend": float(h.actual_spend) if h.actual_spend else None,
        "confounding_factors": h.confounding_factors,
        "confidence_level": h.confidence_level,
        "learning": h.learning,
        "result_notes": h.result_notes,
        "validated_at": h.validated_at.isoformat() if h.validated_at else None,
        "created_by": h.created_by,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        # Deep analysis fields
        "brief_text": h.brief_text,
        "script_text": h.script_text,
        "evidence": h.evidence,
        "creative_principle": h.creative_principle,
        "why_it_worked": h.why_it_worked,
        "human_moment": h.human_moment,
        # Approval linkage — latest approval status for this hypothesis
        "approval_status": approval_status,
        # Layer A/B verdict split
        "funnel_stage": h.funnel_stage,
        "format": h.format,
        "primary_metric": h.primary_metric,
        "win_threshold": float(h.win_threshold) if h.win_threshold is not None else None,
        "min_sample": int(h.min_sample) if h.min_sample is not None else 5,
        "layer_b_status": h.layer_b_status,
        "layer_b_notes": h.layer_b_notes,
        # 4-tier knowledge system
        "confidence_score": float(h.confidence_score) if h.confidence_score is not None else None,
        "principle_id": str(h.principle_id) if h.principle_id else None,
        "principle_title": principle_title,
        "research_question_id": str(h.research_question_id) if h.research_question_id else None,
        "knowledge_links": h.knowledge_links or [],
        "parent_hypothesis_id": str(h.parent_hypothesis_id) if h.parent_hypothesis_id else None,
    }


@router.post("/suggest")
def suggest_hypotheses(payload: HypothesisSuggestRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Use Claude to generate 3 hypothesis variants based on brand context."""
    try:
        from anthropic import Anthropic
        from app.config import settings
        from app.models.account import AdAccount
        from app.models.ad_combo import AdCombo

        brand = db.query(BrandIdentity).filter(
            BrandIdentity.branch_name == payload.branch_name
        ).first()

        # Brand context
        brand_ctx = ""
        if brand:
            brand_ctx = f"""BRAND: {brand.branch_name}
Territory: {brand.brand_territory or "—"}
Promise: {brand.brand_promise or "—"}
Feeling target: {brand.feeling_target or "—"}
Always say: {', '.join(brand.always_say or [])}
Never say: {', '.join(brand.never_say or [])}"""

        # WIN/LOSE combos for this branch — gives AI grounding in what actually worked
        account = db.query(AdAccount).filter(
            AdAccount.account_name == payload.branch_name,
            AdAccount.platform == "meta",
        ).first()
        combo_ctx = ""
        if account:
            wins = db.query(AdCombo).filter(
                AdCombo.branch_id == account.id,
                AdCombo.verdict == "WIN",
                AdCombo.spend > 0,
            ).order_by(AdCombo.roas.desc()).limit(3).all()
            loses = db.query(AdCombo).filter(
                AdCombo.branch_id == account.id,
                AdCombo.verdict == "LOSE",
                AdCombo.spend > 0,
            ).order_by(AdCombo.roas.asc()).limit(3).all()
            if wins:
                combo_ctx += "\nWINNING ADS (high ROAS):\n" + "\n".join(
                    f"- {c.ad_name or c.combo_id} | TA:{c.target_audience} | ROAS:{float(c.roas or 0):.2f}x"
                    for c in wins
                )
            if loses:
                combo_ctx += "\nLOSING ADS (low ROAS):\n" + "\n".join(
                    f"- {c.ad_name or c.combo_id} | TA:{c.target_audience} | ROAS:{float(c.roas or 0):.2f}x"
                    for c in loses
                )

        # Past learnings for this desire
        past = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == payload.branch_name,
            CreativeHypothesis.human_desire == payload.human_desire,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
            CreativeHypothesis.learning.isnot(None),
        ).order_by(desc(CreativeHypothesis.validated_at)).limit(3).all()
        past_ctx = ""
        if past:
            past_ctx = "\nPAST LEARNINGS FOR THIS DESIRE:\n" + "\n".join(
                f"- [{h.status.upper()}] {h.learning}" for h in past
            )

        # Category guidance for the booking-decision framework
        category_guidance = {
            "identity": "Focus on WHO the guest becomes by staying here. The ad must answer 'Is this hotel for someone like me?' Hypothesis should test identity signals: solo adventurer, romantic couple, design-conscious traveler, etc.",
            "decision_driver": "Focus on the rational tipping point that makes someone book NOW vs keep looking. Test price anchoring, urgency, comparison positioning, or risk-removal (free cancellation, best price guarantee).",
            "emotional_trigger": "Focus on the specific emotion that closes the booking decision. Test which feeling — romance, nostalgia, excitement, escape, pride — drives higher conversion for this TA.",
            "travel_moment": "Focus on the specific stage in the guest's travel planning journey. Test whether speaking to 'inspiration' (dreaming), 'planning' (comparing), or 'deciding' (ready to book) lifts performance.",
            "social_proof": "Focus on WHOSE voice the guest trusts most. Test peer reviews vs expert endorsements vs influencer vs staff recommendations vs user-generated content.",
            "experience": "Focus on the specific memorable moment the guest will carry away. Test which experience detail (breakfast view, pillow menu, rooftop sunset) resonates most as the reason to choose this hotel.",
            "value_perception": "Focus on whether the price feels WORTH IT. Test how the ad frames value: premium experience justification, comparison to alternatives, or tangible value-adds (included breakfast, late checkout).",
            "brand_territory": "Focus on the brand's ownable position. Test which distinct characteristic of the hotel (design philosophy, location story, founder values) guests can't get anywhere else.",
        }
        cat_ctx = ""
        if payload.hypothesis_category:
            cat_label = payload.hypothesis_category.replace("_", " ").title()
            guidance = category_guidance.get(payload.hypothesis_category, "")
            cat_ctx = f"\nHYPOTHESIS CATEGORY: {cat_label}\n{guidance}"
        insight_ctx = f"\nCUSTOMER INSIGHT (underlying belief): {payload.customer_insight}" if payload.customer_insight else ""

        prompt = f"""You are a hotel performance marketing strategist who thinks in terms of the Booking Decision framework.
Hotel guests ask 6 questions before booking: Can I trust this place? Is this for someone like me? Will I remember this? Is it worth the price? Is the location right? Will I regret not booking?
Your hypotheses must address one of these questions — NOT generic creative variations.

Generate exactly 3 creative hypothesis variants for an upcoming ad creative test.
Return a JSON array of 3 objects, each with these fields:
- hypothesis: one clear sentence stating the booking-decision belief being tested (start with "We believe..." or "If we show...")
- variable_tested: the specific creative element being changed (e.g. "Social proof type: guest review vs staff story")
- expected_outcome: measurable prediction tied to the booking question (e.g. "+15% CTR among Couple TA")
- rationale: one sentence WHY this hypothesis addresses a real booking hesitation for this brand/TA

BRAND CONTEXT:
{brand_ctx}
{combo_ctx}
{past_ctx}
{cat_ctx}
{insight_ctx}

THIS TEST:
Human Desire: {payload.human_desire}
Creative Angle: {payload.creative_angle or "—"}
Target Audience: {payload.target_audience or "—"}
Market: {payload.market or "—"}
Primary KPI: {payload.primary_kpi or "ROAS"}

Return ONLY valid JSON array. No markdown, no explanation."""

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        suggestions = json.loads(raw.strip())
        return {"success": True, "data": {"suggestions": suggestions},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("[hypothesis-suggest] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("")
def list_hypotheses(
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    human_desire: Optional[str] = None,
    hypothesis_category: Optional[str] = None,
    target_audience: Optional[str] = None,
    market: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        q = db.query(CreativeHypothesis)
        if branch_name:
            q = q.filter(CreativeHypothesis.branch_name == branch_name)
        if status:
            q = q.filter(CreativeHypothesis.status == status)
        if human_desire:
            q = q.filter(CreativeHypothesis.human_desire == human_desire)
        if hypothesis_category:
            q = q.filter(CreativeHypothesis.hypothesis_category == hypothesis_category)
        if target_audience:
            q = q.filter(CreativeHypothesis.target_audience == target_audience)
        if market:
            q = q.filter(CreativeHypothesis.market == market)
        total = q.count()
        rows = q.order_by(desc(CreativeHypothesis.created_at)).offset(offset).limit(limit).all()
        combo_ids = [r.combo_id for r in rows if r.combo_id]
        combos = {c.combo_id: c for c in db.query(AdCombo).filter(AdCombo.combo_id.in_(combo_ids)).all()}

        # Bulk-fetch latest approval status per hypothesis_id
        from app.models.approval import ComboApproval as _CA
        hyp_ids = [r.hypothesis_id for r in rows if r.hypothesis_id]
        approval_statuses: dict[str, str] = {}
        if hyp_ids:
            approvals = db.query(_CA.hypothesis_id, _CA.status, _CA.submitted_at).filter(
                _CA.hypothesis_id.in_(hyp_ids)
            ).order_by(_CA.submitted_at.desc()).all()
            for a in approvals:
                if a.hypothesis_id not in approval_statuses:
                    approval_statuses[a.hypothesis_id] = a.status

        return {"success": True, "data": {"items": [
            _serialize(r, combos.get(r.combo_id), approval_statuses.get(r.hypothesis_id))
            for r in rows
        ], "total": total}, "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("")
def create_hypothesis(payload: HypothesisCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        hyp = CreativeHypothesis(
            hypothesis_id=_next_hypothesis_id(db),
            **payload.model_dump(),
        )
        db.add(hyp)
        db.commit()
        db.refresh(hyp)
        return {"success": True, "data": _serialize(hyp), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.patch("/{hypothesis_id}/result")
def update_hypothesis_result(
    hypothesis_id: str,
    payload: HypothesisResultUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        hyp = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id == hypothesis_id
        ).first()
        if not hyp:
            raise HTTPException(status_code=404, detail=f"Hypothesis not found: {hypothesis_id}")
        if payload.status not in HYPOTHESIS_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {payload.status}")

        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(hyp, field, value)

        if payload.status in ("validated", "refuted") and not hyp.validated_at:
            hyp.validated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(hyp)
        return {"success": True, "data": _serialize(hyp), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/{hypothesis_id}/analyze-brief")
def analyze_brief(
    hypothesis_id: str,
    payload: BriefAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Paste a creative brief + script — Claude extracts deep evidence,
    creative principle, human moment, and why it worked.

    Works on any status (running, validated, refuted) — most useful after
    results are in so the analysis is grounded in actual outcome.
    """
    try:
        hyp = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id == hypothesis_id
        ).first()
        if not hyp:
            raise HTTPException(status_code=404, detail=f"Hypothesis not found: {hypothesis_id}")

        from app.services.hypothesis_analysis_service import analyze_brief as _analyze
        result = _analyze(db, hyp, payload.brief_text, payload.script_text)
        if "error" in result:
            return {"success": False, "data": None, "error": result["error"],
                    "timestamp": datetime.now(timezone.utc).isoformat()}
        return {"success": True, "data": {**result, "hypothesis": _serialize(hyp)},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/{hypothesis_id}/analyze-vision")
def analyze_vision(
    hypothesis_id: str,
    payload: VisionAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze ad images (single or carousel) with Claude Vision.

    If image_urls is omitted and the hypothesis has a combo_id, images are
    auto-pulled from ad_materials via the combo's material_id.
    """
    try:
        hyp = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id == hypothesis_id
        ).first()
        if not hyp:
            raise HTTPException(status_code=404, detail=f"Hypothesis not found: {hypothesis_id}")

        from app.services.hypothesis_analysis_service import analyze_vision as _analyze_vision
        result = _analyze_vision(db, hyp, payload.image_urls)
        if "error" in result:
            return {"success": False, "data": None, "error": result["error"],
                    "timestamp": datetime.now(timezone.utc).isoformat()}
        return {"success": True, "data": {**result, "hypothesis": _serialize(hyp)},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/by-combo/{combo_id}")
def hypotheses_for_combo(combo_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return hypotheses linked to a specific combo (for approval submit form)."""
    try:
        rows = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.combo_id == combo_id
        ).order_by(desc(CreativeHypothesis.created_at)).all()
        return {"success": True, "data": [_serialize(r) for r in rows],
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/summary/{branch_name}")
def hypothesis_summary(branch_name: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Learning Engine summary — validated learnings grouped by human_desire."""
    try:
        rows = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
        ).order_by(desc(CreativeHypothesis.validated_at)).all()

        by_desire: dict[str, list] = {}
        for h in rows:
            desire = h.human_desire or "Unknown"
            by_desire.setdefault(desire, []).append({
                "hypothesis_id": h.hypothesis_id,
                "creative_angle": h.creative_angle,
                "status": h.status,
                "primary_kpi": h.primary_kpi,
                "actual_roas": float(h.actual_roas) if h.actual_roas else None,
                "actual_ctr": float(h.actual_ctr) if h.actual_ctr else None,
                "learning": h.learning,
                "confidence_level": h.confidence_level,
            })

        return {"success": True, "data": {"branch_name": branch_name, "by_desire": by_desire,
                "total_validated": len(rows)},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/learning-dashboard/{branch_name}")
def learning_dashboard(branch_name: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Learning Dashboard — win rates by desire, category, angle, and funnel-stage failure map."""
    try:
        from collections import defaultdict

        MIN_SAMPLE = 5  # spec §5: below this, result is greyed "insufficient data"

        concluded = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
        ).all()

        all_hyps = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted", "inconclusive", "running"]),
        ).all()

        # ── Desire Win Rate ──────────────────────────────────────────────
        # spec: validated / (validated + refuted) per desire, not raw count
        desire_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if not h.human_desire:
                continue
            desire_stats[h.human_desire]["total"] += 1
            if h.status == "validated":
                desire_stats[h.human_desire]["wins"] += 1
        top_desires = sorted(
            [
                {
                    "desire": d,
                    "win_rate": round(v["wins"] / v["total"] * 100, 0),
                    "experiments": v["total"],
                    "wins": v["wins"],
                    "sufficient": v["total"] >= MIN_SAMPLE,
                }
                for d, v in desire_stats.items() if v["total"] > 0
            ],
            key=lambda x: (-x["sufficient"], -x["win_rate"]),
        )[:8]

        # ── Decision Driver Win Rate (hypothesis_category) ────────────────
        cat_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if not h.hypothesis_category:
                continue
            cat_stats[h.hypothesis_category]["total"] += 1
            if h.status == "validated":
                cat_stats[h.hypothesis_category]["wins"] += 1
        top_drivers = sorted(
            [
                {
                    "category": c.replace("_", " ").title(),
                    "raw": c,
                    "win_rate": round(v["wins"] / v["total"] * 100, 0),
                    "experiments": v["total"],
                    "sufficient": v["total"] >= MIN_SAMPLE,
                }
                for c, v in cat_stats.items() if v["total"] > 0
            ],
            key=lambda x: (-x["sufficient"], -x["win_rate"]),
        )

        # ── Angle Win Rate — ONE table, sorted by win rate ────────────────
        # spec: an angle appears only once; grey if below min sample
        angle_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if not h.creative_angle:
                continue
            angle_stats[h.creative_angle]["total"] += 1
            if h.status == "validated":
                angle_stats[h.creative_angle]["wins"] += 1
        angle_win_rates = sorted(
            [
                {
                    "angle": angle,
                    "wins": v["wins"],
                    "total": v["total"],
                    "win_rate": round(v["wins"] / v["total"] * 100, 0) if v["total"] > 0 else 0,
                    "sufficient": v["total"] >= MIN_SAMPLE,
                }
                for angle, v in angle_stats.items()
            ],
            key=lambda x: (-x["sufficient"], -x["win_rate"]),
        )

        # ── Funnel-Stage Failure Map ──────────────────────────────────────
        # spec §6 (new card): % of refutes at Stop/Hold/Click/Downstream
        stage_stats: dict[str, dict] = defaultdict(lambda: {"refutes": 0, "total": 0})
        for h in concluded:
            if not h.funnel_stage:
                continue
            stage_stats[h.funnel_stage]["total"] += 1
            if h.status == "refuted":
                stage_stats[h.funnel_stage]["refutes"] += 1
        funnel_failure_map = {
            stage: {
                "refutes": v["refutes"],
                "total": v["total"],
                "refute_rate": round(v["refutes"] / v["total"] * 100, 0) if v["total"] > 0 else 0,
            }
            for stage, v in stage_stats.items()
        }

        # ── Recent validated learnings ─────────────────────────────────────
        recent = sorted(
            [h for h in concluded if h.status == "validated" and h.learning],
            key=lambda x: x.validated_at or x.created_at,
            reverse=True,
        )[:5]
        recent_learnings = [
            {
                "hypothesis_id": h.hypothesis_id,
                "learning": h.learning,
                "human_desire": h.human_desire,
                "funnel_stage": h.funnel_stage,
                "target_audience": h.target_audience,
                "market": h.market,
                "validated_at": h.validated_at.isoformat() if h.validated_at else None,
            }
            for h in recent
        ]

        return {
            "success": True,
            "data": {
                "branch_name": branch_name,
                "total_experiments": len(concluded),
                "total_running": sum(1 for h in all_hyps if h.status == "running"),
                "total_validated": sum(1 for h in concluded if h.status == "validated"),
                "total_refuted": sum(1 for h in concluded if h.status == "refuted"),
                "min_sample": MIN_SAMPLE,
                "top_desires": top_desires,
                "top_drivers": top_drivers,
                "angle_win_rates": angle_win_rates,
                "funnel_failure_map": funnel_failure_map,
                "recent_learnings": recent_learnings,
            },
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("[learning-dashboard] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}
