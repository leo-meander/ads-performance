"""Research Questions API — top-level creative research agenda."""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.creative_hypothesis import CreativeHypothesis
from app.models.research_question import ResearchQuestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research-questions", tags=["research-questions"])

RQ_STATUSES = ["open", "in_progress", "answered", "archived"]
RQ_PRIORITIES = ["low", "medium", "high"]


class RQCreate(BaseModel):
    branch_name: Optional[str] = None
    market: Optional[str] = None
    target_audience: Optional[str] = None
    question: str
    context: Optional[str] = None
    status: Optional[str] = "open"
    priority: Optional[str] = "medium"
    created_by: Optional[str] = None


class RQUpdate(BaseModel):
    question: Optional[str] = None
    context: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None


def _next_rq_id(db: Session) -> str:
    last = db.query(ResearchQuestion).order_by(desc(ResearchQuestion.created_at)).first()
    if not last or not last.question_id:
        return "RQ-001"
    try:
        num = int(last.question_id.split("-")[1]) + 1
    except (IndexError, ValueError):
        num = 1
    return f"RQ-{num:03d}"


def _serialize(rq: ResearchQuestion, hypothesis_count: int = 0) -> dict:
    return {
        "id": str(rq.id),
        "question_id": rq.question_id,
        "branch_name": rq.branch_name,
        "market": rq.market,
        "target_audience": rq.target_audience,
        "question": rq.question,
        "context": rq.context,
        "status": rq.status,
        "priority": rq.priority,
        "hypothesis_count": hypothesis_count,
        "created_by": rq.created_by,
        "created_at": rq.created_at.isoformat() if rq.created_at else None,
        "updated_at": rq.updated_at.isoformat() if rq.updated_at else None,
    }


@router.get("")
def list_research_questions(
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    market: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        q = db.query(ResearchQuestion)
        if branch_name:
            q = q.filter(ResearchQuestion.branch_name == branch_name)
        if status:
            q = q.filter(ResearchQuestion.status == status)
        if market:
            q = q.filter(ResearchQuestion.market == market)
        rows = q.order_by(
            desc(ResearchQuestion.status == "open"),
            desc(ResearchQuestion.priority == "high"),
            desc(ResearchQuestion.created_at),
        ).all()

        rq_ids = [str(r.id) for r in rows]
        hypo_counts: dict[str, int] = {}
        if rq_ids:
            from sqlalchemy import func
            counts = (
                db.query(CreativeHypothesis.research_question_id, func.count().label("cnt"))
                .filter(CreativeHypothesis.research_question_id.in_(rq_ids))
                .group_by(CreativeHypothesis.research_question_id)
                .all()
            )
            hypo_counts = {str(c[0]): c[1] for c in counts}

        return {
            "success": True,
            "data": [_serialize(r, hypo_counts.get(str(r.id), 0)) for r in rows],
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("")
def create_research_question(payload: RQCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        rq = ResearchQuestion(question_id=_next_rq_id(db), **payload.model_dump())
        db.add(rq)
        db.commit()
        db.refresh(rq)
        return {"success": True, "data": _serialize(rq), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.patch("/{question_id}")
def update_research_question(
    question_id: str, payload: RQUpdate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        rq = db.query(ResearchQuestion).filter(ResearchQuestion.question_id == question_id).first()
        if not rq:
            raise HTTPException(status_code=404, detail=f"Not found: {question_id}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(rq, field, value)
        db.commit()
        db.refresh(rq)
        return {"success": True, "data": _serialize(rq), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.delete("/{question_id}")
def delete_research_question(question_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        rq = db.query(ResearchQuestion).filter(ResearchQuestion.question_id == question_id).first()
        if not rq:
            raise HTTPException(status_code=404, detail=f"Not found: {question_id}")
        db.query(CreativeHypothesis).filter(
            CreativeHypothesis.research_question_id == rq.id
        ).update({"research_question_id": None})
        db.delete(rq)
        db.commit()
        return {"success": True, "data": {"deleted": question_id}, "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}
