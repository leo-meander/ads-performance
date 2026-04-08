"""Rules CRUD and Action Logs API endpoints for Phase 3."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action_log import ActionLog
from app.models.campaign import Campaign
from app.models.rule import AutomationRule
from app.services.rule_engine import evaluate_all_rules, evaluate_rule

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------- Pydantic schemas ----------

class ConditionItem(BaseModel):
    metric: str
    operator: str  # > < >= <= ==
    threshold: float | None = None  # static value (optional if cross-period)
    days: int = 7
    # Cross-period comparison (optional)
    compare_metric: str | None = None
    compare_period_from: int | None = None  # e.g., 7 = 7 days ago
    compare_period_to: int | None = None  # e.g., 15 = 15 days ago


class RuleCreate(BaseModel):
    name: str
    platform: str = "meta"  # meta | google | tiktok | all
    account_id: str | None = None
    entity_level: str = "campaign"  # campaign | ad_set | ad
    conditions: list[ConditionItem]
    action: str  # pause_campaign | enable_campaign | pause_adset | enable_adset | pause_ad | enable_ad | adjust_budget | send_alert
    action_params: dict | None = None
    created_by: str | None = None


class RuleUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    account_id: str | None = None
    entity_level: str | None = None
    conditions: list[ConditionItem] | None = None
    action: str | None = None
    action_params: dict | None = None
    is_active: bool | None = None


# ---------- Rules CRUD ----------

def _rule_to_dict(r: AutomationRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "platform": r.platform,
        "account_id": r.account_id,
        "entity_level": r.entity_level,
        "conditions": r.conditions,
        "action": r.action,
        "action_params": r.action_params,
        "is_active": r.is_active,
        "last_evaluated_at": r.last_evaluated_at.isoformat() if r.last_evaluated_at else None,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/rules")
def list_rules(
    platform: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(AutomationRule)
        if platform:
            q = q.filter(AutomationRule.platform == platform)
        if is_active is not None:
            q = q.filter(AutomationRule.is_active == is_active)

        rules = q.order_by(AutomationRule.created_at.desc()).all()
        return _api_response(data=[_rule_to_dict(r) for r in rules])
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/rules")
def create_rule(body: RuleCreate, db: Session = Depends(get_db)):
    try:
        rule = AutomationRule(
            name=body.name,
            platform=body.platform,
            account_id=body.account_id,
            entity_level=body.entity_level,
            conditions=[c.model_dump() for c in body.conditions],
            action=body.action,
            action_params=body.action_params,
            created_by=body.created_by,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return _api_response(data=_rule_to_dict(rule))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/rules/{rule_id}")
def get_rule(rule_id: str, db: Session = Depends(get_db)):
    try:
        rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
        if not rule:
            return _api_response(error="Rule not found")
        return _api_response(data=_rule_to_dict(rule))
    except Exception as e:
        return _api_response(error=str(e))


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdate, db: Session = Depends(get_db)):
    try:
        rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
        if not rule:
            return _api_response(error="Rule not found")

        if body.name is not None:
            rule.name = body.name
        if body.platform is not None:
            rule.platform = body.platform
        if body.account_id is not None:
            rule.account_id = body.account_id
        if body.entity_level is not None:
            rule.entity_level = body.entity_level
        if body.conditions is not None:
            rule.conditions = [c.model_dump() for c in body.conditions]
        if body.action is not None:
            rule.action = body.action
        if body.action_params is not None:
            rule.action_params = body.action_params
        if body.is_active is not None:
            rule.is_active = body.is_active

        rule.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(rule)
        return _api_response(data=_rule_to_dict(rule))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    """Soft delete: set is_active = False."""
    try:
        rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
        if not rule:
            return _api_response(error="Rule not found")
        rule.is_active = False
        rule.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _api_response(data={"id": rule.id, "is_active": False})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ---------- Rule Evaluation ----------

@router.post("/rules/{rule_id}/evaluate")
def evaluate_single_rule(rule_id: str, db: Session = Depends(get_db)):
    """Manually trigger evaluation for one rule."""
    try:
        rule = db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()
        if not rule:
            return _api_response(error="Rule not found")
        results = evaluate_rule(db, rule)
        return _api_response(data={
            "rule_id": rule.id,
            "rule_name": rule.name,
            "actions_taken": len(results),
            "results": results,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/rules/evaluate-all")
def evaluate_all(db: Session = Depends(get_db)):
    """Manually trigger evaluation for all active rules."""
    try:
        results = evaluate_all_rules(db)
        return _api_response(data=results)
    except Exception as e:
        return _api_response(error=str(e))


# ---------- Action Logs ----------

@router.get("/logs")
def list_logs(
    rule_id: str | None = None,
    campaign_id: str | None = None,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
    platform: str | None = None,
    success: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(ActionLog)
        if rule_id:
            q = q.filter(ActionLog.rule_id == rule_id)
        if campaign_id:
            q = q.filter(ActionLog.campaign_id == campaign_id)
        if ad_set_id:
            q = q.filter(ActionLog.ad_set_id == ad_set_id)
        if ad_id:
            q = q.filter(ActionLog.ad_id == ad_id)
        if platform:
            q = q.filter(ActionLog.platform == platform)
        if success is not None:
            q = q.filter(ActionLog.success == success)
        if date_from:
            q = q.filter(ActionLog.executed_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            q = q.filter(ActionLog.executed_at <= datetime.combine(date_to, datetime.max.time()))

        total = q.count()
        logs = q.order_by(ActionLog.executed_at.desc()).offset(offset).limit(limit).all()

        # Batch-fetch rule names and campaign names
        rule_ids = {log.rule_id for log in logs if log.rule_id}
        campaign_ids = {log.campaign_id for log in logs if log.campaign_id}

        rules_map = {}
        if rule_ids:
            rules = db.query(AutomationRule).filter(AutomationRule.id.in_(rule_ids)).all()
            rules_map = {r.id: r.name for r in rules}

        campaigns_map = {}
        if campaign_ids:
            camps = db.query(Campaign).filter(Campaign.id.in_(campaign_ids)).all()
            campaigns_map = {c.id: c.name for c in camps}

        items = []
        for log in logs:
            items.append({
                "id": log.id,
                "rule_id": log.rule_id,
                "rule_name": rules_map.get(log.rule_id, "—"),
                "campaign_id": log.campaign_id,
                "campaign_name": campaigns_map.get(log.campaign_id, "—"),
                "ad_set_id": log.ad_set_id,
                "ad_id": log.ad_id,
                "platform": log.platform,
                "action": log.action,
                "action_params": log.action_params,
                "triggered_by": log.triggered_by,
                "metrics_snapshot": log.metrics_snapshot,
                "success": log.success,
                "error_message": log.error_message,
                "executed_at": log.executed_at.isoformat() if log.executed_at else None,
            })

        return _api_response(data={"items": items, "total": total, "limit": limit, "offset": offset})
    except Exception as e:
        return _api_response(error=str(e))
