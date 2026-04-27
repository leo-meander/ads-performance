"""Meta Ads playbook recommendation endpoints."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.campaign import Campaign
from app.models.meta_recommendation import MetaRecommendation
from app.models.user import User
from app.services.meta_recommendations import applier, engine
from app.services.recommendation_context import build_context_map

router = APIRouter()


def _exclude_paused_campaign_pendings(q, db: Session):
    """Hide pending recs whose underlying campaign is no longer ACTIVE.

    Operators pause campaigns mid-cycle; until the next scheduler run flips
    those recs to 'superseded', they would otherwise still surface in the UI.
    """
    paused = db.query(Campaign.id).filter(Campaign.status != "ACTIVE").subquery()
    return q.filter(
        ~(
            (MetaRecommendation.status == "pending")
            & MetaRecommendation.campaign_id.isnot(None)
            & MetaRecommendation.campaign_id.in_(paused)
        ),
    )


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _rec_to_dict(
    r: MetaRecommendation,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": r.id,
        "rec_type": r.rec_type,
        "severity": r.severity,
        "status": r.status,
        "account_id": r.account_id,
        "campaign_id": r.campaign_id,
        "ad_set_id": r.ad_set_id,
        "ad_id": r.ad_id,
        "entity_level": r.entity_level,
        "funnel_stage": r.funnel_stage,
        "targeted_country": r.targeted_country,
        "title": r.title,
        "detector_finding": r.detector_finding,
        "metrics_snapshot": r.metrics_snapshot,
        "ai_reasoning": r.ai_reasoning,
        "ai_confidence": float(r.ai_confidence) if r.ai_confidence is not None else None,
        "suggested_action": r.suggested_action,
        "auto_applicable": r.auto_applicable,
        "warning_text": r.warning_text,
        "sop_reference": r.sop_reference,
        "dedup_key": r.dedup_key,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "applied_at": r.applied_at.isoformat() if r.applied_at else None,
        "applied_by": r.applied_by,
        "dismissed_at": r.dismissed_at.isoformat() if r.dismissed_at else None,
        "dismissed_by": r.dismissed_by,
        "dismiss_reason": r.dismiss_reason,
        "action_log_id": r.action_log_id,
        "context": context or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ── List / detail ────────────────────────────────────────────────────────────

@router.get("/meta/recommendations")
def list_recommendations(
    status: str | None = None,
    severity: str | None = None,
    rec_type: str | None = None,
    entity_level: str | None = None,
    funnel_stage: str | None = None,
    targeted_country: str | None = None,
    account_id: str | None = None,
    campaign_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)

        q = db.query(MetaRecommendation)
        if status:
            q = q.filter(MetaRecommendation.status == status)
        if severity:
            q = q.filter(MetaRecommendation.severity == severity)
        if rec_type:
            q = q.filter(MetaRecommendation.rec_type == rec_type)
        if entity_level:
            q = q.filter(MetaRecommendation.entity_level == entity_level)
        if funnel_stage:
            q = q.filter(MetaRecommendation.funnel_stage == funnel_stage)
        if targeted_country:
            q = q.filter(MetaRecommendation.targeted_country == targeted_country.upper())
        if account_id:
            q = q.filter(MetaRecommendation.account_id == account_id)
        if campaign_id:
            q = q.filter(MetaRecommendation.campaign_id == campaign_id)
        if scoped_ids is not None:
            q = q.filter(
                MetaRecommendation.account_id.in_(scoped_ids or ["__no_match__"]),
            )
        q = _exclude_paused_campaign_pendings(q, db)

        total = q.count()
        severity_order = case(
            (MetaRecommendation.severity == "critical", 0),
            (MetaRecommendation.severity == "warning", 1),
            (MetaRecommendation.severity == "info", 2),
            else_=3,
        )
        q = q.order_by(severity_order, MetaRecommendation.created_at.desc())
        rows = q.offset(offset).limit(limit).all()
        ctx_map = build_context_map(db, rows)
        return _api_response(data={
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_rec_to_dict(r, ctx_map.get(r.id)) for r in rows],
        })
    except Exception as exc:
        return _api_response(error=str(exc))


@router.get("/meta/recommendations/{rec_id}")
def get_recommendation(
    rec_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        rec = db.query(MetaRecommendation).filter(
            MetaRecommendation.id == rec_id,
        ).first()
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)
        if scoped_ids is not None and rec.account_id not in scoped_ids:
            raise HTTPException(status_code=403, detail="No access to this branch")
        ctx_map = build_context_map(db, [rec])
        return _api_response(data=_rec_to_dict(rec, ctx_map.get(rec.id)))
    except HTTPException:
        raise
    except Exception as exc:
        return _api_response(error=str(exc))


# ── Apply / dismiss / regenerate ─────────────────────────────────────────────

class ApplyBody(BaseModel):
    confirm_warning: bool = False
    override_params: dict[str, Any] | None = None


@router.post("/meta/recommendations/{rec_id}/apply")
def apply_recommendation(
    rec_id: str,
    body: ApplyBody,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        rec = db.query(MetaRecommendation).filter(
            MetaRecommendation.id == rec_id,
        ).first()
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads",
            requested_account_id=rec.account_id, min_level="edit",
        )
        if not ok:
            return _api_response(error=err)

        updated = applier.apply_recommendation(
            db, rec_id,
            confirm_warning=body.confirm_warning,
            applied_by_user_id=current_user.id,
            override_params=body.override_params,
        )
        ctx_map = build_context_map(db, [updated])
        return _api_response(data=_rec_to_dict(updated, ctx_map.get(updated.id)))
    except applier.ConfirmationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except applier.NotAutoApplicable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except applier.NotApplicable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        return _api_response(error=str(exc))


class DismissBody(BaseModel):
    reason: str = ""


@router.post("/meta/recommendations/{rec_id}/dismiss")
def dismiss_recommendation(
    rec_id: str,
    body: DismissBody,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        rec = db.query(MetaRecommendation).filter(
            MetaRecommendation.id == rec_id,
        ).first()
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads",
            requested_account_id=rec.account_id, min_level="edit",
        )
        if not ok:
            return _api_response(error=err)
        updated = applier.dismiss_recommendation(
            db, rec_id, reason=body.reason, dismissed_by_user_id=current_user.id,
        )
        ctx_map = build_context_map(db, [updated])
        return _api_response(data=_rec_to_dict(updated, ctx_map.get(updated.id)))
    except applier.NotApplicable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        return _api_response(error=str(exc))


@router.post("/meta/recommendations/{rec_id}/regenerate")
def regenerate_recommendation(
    rec_id: str,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        rec = db.query(MetaRecommendation).filter(
            MetaRecommendation.id == rec_id,
        ).first()
        if rec is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads",
            requested_account_id=rec.account_id, min_level="edit",
        )
        if not ok:
            return _api_response(error=err)
        refreshed = engine.regenerate_recommendation(db, rec_id)
        if refreshed is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        ctx_map = build_context_map(db, [refreshed])
        return _api_response(data=_rec_to_dict(refreshed, ctx_map.get(refreshed.id)))
    except HTTPException:
        raise
    except Exception as exc:
        return _api_response(error=str(exc))


# ── Counters and admin runs ──────────────────────────────────────────────────

@router.get("/meta/recommendations-counts/campaign/{campaign_id}")
def count_for_campaign(
    campaign_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    try:
        camp = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if camp is not None and camp.status != "ACTIVE":
            return _api_response(data={"critical": 0, "warning": 0, "info": 0})
        rows = (
            db.query(MetaRecommendation.severity, func.count(MetaRecommendation.id))
            .filter(MetaRecommendation.campaign_id == campaign_id)
            .filter(MetaRecommendation.status == "pending")
            .group_by(MetaRecommendation.severity)
            .all()
        )
        counts = {"critical": 0, "warning": 0, "info": 0}
        for sev, count in rows:
            counts[sev] = int(count)
        return _api_response(data=counts)
    except Exception as exc:
        return _api_response(error=str(exc))


@router.get("/meta/recommendations-counts/branch/{account_id}")
def count_for_branch(
    account_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Branch roll-up: pending recommendation severity counts for an account."""
    try:
        paused = db.query(Campaign.id).filter(Campaign.status != "ACTIVE").subquery()
        rows = (
            db.query(MetaRecommendation.severity, func.count(MetaRecommendation.id))
            .filter(MetaRecommendation.account_id == account_id)
            .filter(MetaRecommendation.status == "pending")
            .filter(
                ~(
                    MetaRecommendation.campaign_id.isnot(None)
                    & MetaRecommendation.campaign_id.in_(paused)
                ),
            )
            .group_by(MetaRecommendation.severity)
            .all()
        )
        counts = {"critical": 0, "warning": 0, "info": 0}
        for sev, count in rows:
            counts[sev] = int(count)
        return _api_response(data=counts)
    except Exception as exc:
        return _api_response(error=str(exc))


class RunBody(BaseModel):
    cadence: str = "daily"  # daily | weekly | monthly | seasonality
    account_ids: list[str] | None = None


@router.post("/meta/recommendations/run")
def run_on_demand(
    body: RunBody,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    try:
        if "admin" not in (current_user.roles or []):
            raise HTTPException(status_code=403, detail="Admin only")
        stats = engine.run_recommendations(
            db, cadence=body.cadence, account_ids=body.account_ids,
            source_task_id=f"manual:{current_user.id}",
        )
        return _api_response(data=stats)
    except HTTPException:
        raise
    except Exception as exc:
        return _api_response(error=str(exc))
