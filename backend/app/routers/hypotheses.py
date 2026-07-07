"""Creative Hypotheses API — Learning Engine."""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.creative_hypothesis import CreativeHypothesis

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])

HYPOTHESIS_STATUSES = ["pending", "running", "validated", "refuted", "inconclusive"]


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


def _serialize(h: CreativeHypothesis) -> dict:
    return {
        "id": str(h.id),
        "hypothesis_id": h.hypothesis_id,
        "branch_name": h.branch_name,
        "combo_id": str(h.combo_id) if h.combo_id else None,
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
        return {"success": True, "data": {"items": [_serialize(r) for r in rows], "total": total},
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
