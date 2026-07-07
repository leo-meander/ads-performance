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
    creative_angle: Optional[str] = None
    target_audience: Optional[str] = None
    market: Optional[str] = None
    primary_kpi: Optional[str] = None


class HypothesisCreate(BaseModel):
    branch_name: str
    combo_id: Optional[str] = None
    angle_id: Optional[str] = None
    human_desire: Optional[str] = None
    creative_angle: Optional[str] = None
    target_audience: Optional[str] = None
    market: Optional[str] = None
    hypothesis: str
    variable_tested: Optional[str] = None
    primary_kpi: Optional[str] = None
    secondary_kpi: Optional[str] = None
    expected_outcome: Optional[str] = None
    created_by: Optional[str] = None


class HypothesisResultUpdate(BaseModel):
    status: str
    actual_ctr: Optional[float] = None
    actual_cvr: Optional[float] = None
    actual_roas: Optional[float] = None
    actual_spend: Optional[float] = None
    confounding_factors: Optional[list[str]] = None
    confidence_level: Optional[str] = None
    learning: Optional[str] = None
    result_notes: Optional[str] = None


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


def _serialize(h: CreativeHypothesis, combo: AdCombo | None = None) -> dict:
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

        prompt = f"""You are a performance marketing strategist for a boutique hotel brand.
Generate exactly 3 creative hypothesis variants for an upcoming ad creative test.
Return a JSON array of 3 objects, each with these fields:
- hypothesis: one clear sentence stating the belief being tested (start with "We believe..." or "If we...")
- variable_tested: the specific creative element being changed (e.g. "Social scene vs Room scene")
- expected_outcome: measurable prediction (e.g. "+15% CTR vs control")
- rationale: one sentence WHY this hypothesis aligns with the brand and what the winning/losing ads suggest

CONTEXT:
{brand_ctx}
{combo_ctx}
{past_ctx}

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
        total = q.count()
        rows = q.order_by(desc(CreativeHypothesis.created_at)).offset(offset).limit(limit).all()
        combo_ids = [r.combo_id for r in rows if r.combo_id]
        combos = {c.combo_id: c for c in db.query(AdCombo).filter(AdCombo.combo_id.in_(combo_ids)).all()}
        return {"success": True, "data": {"items": [_serialize(r, combos.get(r.combo_id)) for r in rows], "total": total},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
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
