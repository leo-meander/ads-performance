"""Creative Principles API — the Knowledge Layer above Hypotheses."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.creative_hypothesis import CreativeHypothesis
from app.models.creative_principle import CreativePrinciple

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/principles", tags=["creative-principles"])


class PrincipleCreate(BaseModel):
    branch_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    anti_principle: Optional[str] = None
    human_desire: Optional[str] = None
    applicable_markets: Optional[list[str]] = None
    applicable_ta: Optional[list[str]] = None
    created_by: Optional[str] = None


class PrincipleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    anti_principle: Optional[str] = None
    human_desire: Optional[str] = None
    applicable_markets: Optional[list[str]] = None
    applicable_ta: Optional[list[str]] = None
    is_active: Optional[bool] = None


class AssignHypothesisRequest(BaseModel):
    hypothesis_ids: list[str]  # hypothesis_id strings (HYP-xxx)


class AIExtractRequest(BaseModel):
    branch_name: str
    hypothesis_ids: list[str]  # hypothesis_id strings to synthesize from


def _next_principle_id(db: Session) -> str:
    last = db.query(CreativePrinciple).order_by(desc(CreativePrinciple.created_at)).first()
    if not last or not last.principle_id:
        return "PRI-001"
    try:
        num = int(last.principle_id.split("-")[1]) + 1
    except (IndexError, ValueError):
        num = 1
    return f"PRI-{num:03d}"


def _recalc_stats(principle: CreativePrinciple, db: Session) -> None:
    rows = db.query(
        CreativeHypothesis.status,
        func.count().label("cnt"),
    ).filter(
        CreativeHypothesis.principle_id == principle.id,
    ).group_by(CreativeHypothesis.status).all()

    status_counts = {r.status: r.cnt for r in rows}
    total = sum(status_counts.values())
    validated = status_counts.get("validated", 0)
    refuted = status_counts.get("refuted", 0)

    principle.experiment_count = total
    principle.validated_count = validated
    principle.refuted_count = refuted
    if total > 0:
        principle.confidence_score = round((validated / total) * 100, 1)
    else:
        principle.confidence_score = 0


def _serialize(p: CreativePrinciple, linked_hypotheses: list | None = None) -> dict:
    return {
        "id": str(p.id),
        "principle_id": p.principle_id,
        "branch_name": p.branch_name,
        "title": p.title,
        "description": p.description,
        "anti_principle": p.anti_principle,
        "human_desire": p.human_desire,
        "applicable_markets": p.applicable_markets or [],
        "applicable_ta": p.applicable_ta or [],
        "confidence_score": float(p.confidence_score) if p.confidence_score is not None else 0,
        "experiment_count": p.experiment_count or 0,
        "validated_count": p.validated_count or 0,
        "refuted_count": p.refuted_count or 0,
        "is_active": p.is_active,
        "created_by": p.created_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "linked_hypotheses": linked_hypotheses,
    }


@router.get("")
def list_principles(
    branch_name: Optional[str] = None,
    human_desire: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        q = db.query(CreativePrinciple)
        if branch_name:
            q = q.filter(
                (CreativePrinciple.branch_name == branch_name) |
                (CreativePrinciple.branch_name.is_(None))
            )
        if human_desire:
            q = q.filter(CreativePrinciple.human_desire == human_desire)
        if is_active is not None:
            q = q.filter(CreativePrinciple.is_active == is_active)
        principles = q.order_by(desc(CreativePrinciple.confidence_score)).all()

        # Recalc stats from DB on list (keeps counts fresh without a separate cron)
        for p in principles:
            _recalc_stats(p, db)
        db.commit()

        return {
            "success": True,
            "data": [_serialize(p) for p in principles],
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/{principle_id}")
def get_principle(principle_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        p = db.query(CreativePrinciple).filter(CreativePrinciple.principle_id == principle_id).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Not found: {principle_id}")
        _recalc_stats(p, db)
        db.commit()

        hyps = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.principle_id == p.id
        ).order_by(desc(CreativeHypothesis.created_at)).all()

        linked = [
            {
                "hypothesis_id": h.hypothesis_id,
                "hypothesis": h.hypothesis,
                "status": h.status,
                "branch_name": h.branch_name,
                "target_audience": h.target_audience,
                "market": h.market,
                "actual_roas": float(h.actual_roas) if h.actual_roas else None,
                "confidence_score": float(h.confidence_score) if h.confidence_score else None,
            }
            for h in hyps
        ]
        return {"success": True, "data": _serialize(p, linked), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("")
def create_principle(payload: PrincipleCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        p = CreativePrinciple(principle_id=_next_principle_id(db), **payload.model_dump())
        db.add(p)
        db.commit()
        db.refresh(p)
        return {"success": True, "data": _serialize(p), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.patch("/{principle_id}")
def update_principle(
    principle_id: str, payload: PrincipleUpdate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        p = db.query(CreativePrinciple).filter(CreativePrinciple.principle_id == principle_id).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Not found: {principle_id}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(p, field, value)
        _recalc_stats(p, db)
        db.commit()
        db.refresh(p)
        return {"success": True, "data": _serialize(p), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.delete("/{principle_id}")
def delete_principle(principle_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        p = db.query(CreativePrinciple).filter(CreativePrinciple.principle_id == principle_id).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Not found: {principle_id}")
        db.query(CreativeHypothesis).filter(
            CreativeHypothesis.principle_id == p.id
        ).update({"principle_id": None})
        db.delete(p)
        db.commit()
        return {"success": True, "data": {"deleted": principle_id}, "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/{principle_id}/assign")
def assign_hypotheses(
    principle_id: str, payload: AssignHypothesisRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Link one or more hypotheses to this principle."""
    try:
        p = db.query(CreativePrinciple).filter(CreativePrinciple.principle_id == principle_id).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Not found: {principle_id}")
        updated = (
            db.query(CreativeHypothesis)
            .filter(CreativeHypothesis.hypothesis_id.in_(payload.hypothesis_ids))
            .all()
        )
        for h in updated:
            h.principle_id = p.id
        _recalc_stats(p, db)
        db.commit()
        return {"success": True, "data": {"linked": len(updated)}, "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/ai-extract")
def ai_extract_principle(payload: AIExtractRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Claude synthesizes a Creative Principle from a set of hypotheses."""
    try:
        from anthropic import Anthropic
        from app.config import settings

        hyps = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id.in_(payload.hypothesis_ids)
        ).all()
        if not hyps:
            raise HTTPException(status_code=400, detail="No hypotheses found for given IDs")

        hyp_text = "\n".join(
            f"[{h.status.upper()}] {h.hypothesis}"
            + (f"\n  Evidence: {h.evidence}" if h.evidence else "")
            + (f"\n  Why it worked: {h.why_it_worked}" if h.why_it_worked else "")
            + (f"\n  Principle (raw): {h.creative_principle}" if h.creative_principle else "")
            for h in hyps
        )

        prompt = f"""You are a creative strategist synthesizing learnings from hotel ad experiments.

Given these experiment outcomes for {payload.branch_name}:

{hyp_text}

Extract ONE clear Creative Principle — a reusable rule that can guide future creative decisions.

Return a JSON object with:
- title: short memorable principle (max 8 words, e.g. "Sell the Journey, Not the Room")
- description: 1-2 sentences explaining when and why this principle works
- anti_principle: the opposite — what NOT to do (max 8 words)
- human_desire: the core human desire this principle taps into

Return ONLY valid JSON. No markdown."""

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        return {"success": True, "data": result, "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[ai-extract-principle] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}
