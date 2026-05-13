"""Tactics API.

CRUD for Madgicx-style preset tactics. Tactics are the user-facing toggle;
under the hood they materialize into 1+ AutomationRule rows that the existing
rule engine runs.

Endpoints:
    GET    /tactics                    list with optional filters
    GET    /tactics/presets            preset catalog for UI dropdowns
    POST   /tactics                    create-from-preset
    GET    /tactics/{id}               detail (includes linked rules)
    PUT    /tactics/{id}               update config / name (rewrites rules)
    POST   /tactics/{id}/toggle        flip is_active
    DELETE /tactics/{id}               hard delete (rules cascade)
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.action_log import ActionLog
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.rule import AutomationRule
from app.models.tactic import Tactic
from app.models.user import User
from app.services import tactic_presets, tactic_service

router = APIRouter()


def _api_response(data: Any = None, error: str | None = None) -> dict:
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------- Pydantic schemas ----------

class TacticCreate(BaseModel):
    preset_type: str
    name: str | None = None
    platform: str = "meta"
    account_id: str | None = None
    # For preset_type='custom_rule' the overrides ARE the rule definition:
    # {entity_level, conditions, action, action_params}. For other presets
    # they're threshold tweaks merged over the preset's default_config.
    config_overrides: dict[str, Any] | None = None


class TacticUpdate(BaseModel):
    name: str | None = None
    config_overrides: dict[str, Any] | None = None


class TacticToggle(BaseModel):
    is_active: bool = Field(..., description="Target state.")


# ---------- Serialization ----------

def _tactic_to_dict(db: Session, t: Tactic) -> dict:
    rule_count = tactic_service.count_rules_for_tactic(db, t.id)
    return {
        "id": t.id,
        "name": t.name,
        "preset_type": t.preset_type,
        "platform": t.platform,
        "account_id": t.account_id,
        "config": t.config,
        "is_active": t.is_active,
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "rule_count": rule_count,
    }


# ---------- Preset catalog ----------

@router.get("/tactics/presets")
def list_presets_endpoint(
    current_user: User = Depends(require_section("automation")),
):
    """Return all known presets + their default configs. Drives the create dialog."""
    return _api_response(data=tactic_presets.list_presets())


# ---------- CRUD ----------

@router.get("/tactics")
def list_tactics_endpoint(
    platform: str | None = None,
    account_id: str | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(require_section("automation")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "automation")
        if not ok:
            return _api_response(error=err)

        # Apply scope filter on top of explicit account_id filter.
        q = db.query(Tactic)
        if platform:
            q = q.filter(Tactic.platform == platform)
        if account_id:
            q = q.filter(Tactic.account_id == account_id)
        if is_active is not None:
            q = q.filter(Tactic.is_active == is_active)
        if scoped_ids is not None:
            q = q.filter(
                (Tactic.account_id.is_(None))
                | (Tactic.account_id.in_(scoped_ids or ["__no_match__"]))
            )

        tactics = q.order_by(Tactic.created_at.desc()).all()
        return _api_response(data=[_tactic_to_dict(db, t) for t in tactics])
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/tactics")
def create_tactic_endpoint(
    body: TacticCreate,
    current_user: User = Depends(require_section("automation", "edit")),
    db: Session = Depends(get_db),
):
    try:
        if body.preset_type not in tactic_service.get_valid_preset_types():
            return _api_response(error=f"Unknown preset_type: {body.preset_type}")

        # Permission scope check on the target account.
        if body.account_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "automation",
                requested_account_id=body.account_id, min_level="edit",
            )
            if not ok:
                return _api_response(error=err)

        tactic = tactic_service.create_tactic_from_preset(
            db,
            preset_type=body.preset_type,
            name=body.name,
            platform=body.platform,
            account_id=body.account_id,
            config_overrides=body.config_overrides,
            created_by=getattr(current_user, "email", None) or getattr(current_user, "id", None),
        )
        return _api_response(data=_tactic_to_dict(db, tactic))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/tactics/{tactic_id}")
def get_tactic_endpoint(
    tactic_id: str,
    current_user: User = Depends(require_section("automation")),
    db: Session = Depends(get_db),
):
    try:
        tactic = tactic_service.get_tactic(db, tactic_id)
        if not tactic:
            return _api_response(error="Tactic not found")

        if tactic.account_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "automation", requested_account_id=tactic.account_id,
            )
            if not ok:
                return _api_response(error=err)

        data = _tactic_to_dict(db, tactic)
        rules = (
            db.query(AutomationRule)
            .filter(AutomationRule.tactic_id == tactic_id)
            .order_by(AutomationRule.created_at.asc())
            .all()
        )
        data["rules"] = [
            {
                "id": r.id,
                "name": r.name,
                "entity_level": r.entity_level,
                "action": r.action,
                "is_active": r.is_active,
                "conditions": r.conditions,
                "action_params": r.action_params,
                "last_evaluated_at": r.last_evaluated_at.isoformat() if r.last_evaluated_at else None,
            }
            for r in rules
        ]
        return _api_response(data=data)
    except Exception as e:
        return _api_response(error=str(e))


@router.put("/tactics/{tactic_id}")
def update_tactic_endpoint(
    tactic_id: str,
    body: TacticUpdate,
    current_user: User = Depends(require_section("automation", "edit")),
    db: Session = Depends(get_db),
):
    try:
        tactic = tactic_service.get_tactic(db, tactic_id)
        if not tactic:
            return _api_response(error="Tactic not found")

        if tactic.account_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "automation",
                requested_account_id=tactic.account_id, min_level="edit",
            )
            if not ok:
                return _api_response(error=err)

        if body.name is not None:
            tactic.name = body.name
            tactic.updated_at = datetime.now(timezone.utc)
            db.commit()

        if body.config_overrides:
            tactic = tactic_service.update_tactic_config(
                db, tactic_id, body.config_overrides,
            )
        db.refresh(tactic)
        return _api_response(data=_tactic_to_dict(db, tactic))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/tactics/{tactic_id}/toggle")
def toggle_tactic_endpoint(
    tactic_id: str,
    body: TacticToggle,
    current_user: User = Depends(require_section("automation", "edit")),
    db: Session = Depends(get_db),
):
    try:
        tactic = tactic_service.get_tactic(db, tactic_id)
        if not tactic:
            return _api_response(error="Tactic not found")
        if tactic.account_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "automation",
                requested_account_id=tactic.account_id, min_level="edit",
            )
            if not ok:
                return _api_response(error=err)
        tactic = tactic_service.toggle_tactic(db, tactic_id, body.is_active)
        return _api_response(data=_tactic_to_dict(db, tactic))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/tactics/{tactic_id}/diagnostics")
def get_tactic_diagnostics(
    tactic_id: str,
    current_user: User = Depends(require_section("automation")),
    db: Session = Depends(get_db),
):
    """Surface *why* a tactic did or didn't fire.

    For each rule under this tactic, return:
      - last_evaluation: most recent evaluation_summary action_log
        (entities_checked, actions_taken, top_fail_reason, fail_examples)
      - recent_actions: last few actual mutations + their success/error_message

    This is the "why didn't it work" panel — every value pulled from existing
    action_logs, no new write paths.
    """
    try:
        tactic = tactic_service.get_tactic(db, tactic_id)
        if not tactic:
            return _api_response(error="Tactic not found")
        if tactic.account_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "automation", requested_account_id=tactic.account_id,
            )
            if not ok:
                return _api_response(error=err)

        rules = (
            db.query(AutomationRule)
            .filter(AutomationRule.tactic_id == tactic_id)
            .all()
        )

        # Bulk fetch entity names so we can humanize "entity X" in logs.
        entity_name_cache: dict[str, str] = {}

        def _resolve_entity_name(log: ActionLog) -> str:
            eid = log.ad_id or log.ad_set_id or log.campaign_id
            if not eid:
                return "—"
            if eid in entity_name_cache:
                return entity_name_cache[eid]
            name = "—"
            if log.ad_id:
                row = db.query(Ad.name).filter(Ad.id == log.ad_id).scalar()
                if row:
                    name = row
            elif log.ad_set_id:
                row = db.query(AdSet.name).filter(AdSet.id == log.ad_set_id).scalar()
                if row:
                    name = row
            elif log.campaign_id:
                row = db.query(Campaign.name).filter(Campaign.id == log.campaign_id).scalar()
                if row:
                    name = row
            entity_name_cache[eid] = name
            return name

        rules_data = []
        for rule in rules:
            last_eval = (
                db.query(ActionLog)
                .filter(
                    ActionLog.rule_id == rule.id,
                    ActionLog.action == "evaluation_summary",
                )
                .order_by(ActionLog.executed_at.desc())
                .first()
            )
            recent_actions_q = (
                db.query(ActionLog)
                .filter(
                    ActionLog.rule_id == rule.id,
                    ActionLog.action != "evaluation_summary",
                )
                .order_by(ActionLog.executed_at.desc())
                .limit(10)
                .all()
            )
            recent_actions = [
                {
                    "executed_at": a.executed_at.isoformat() if a.executed_at else None,
                    "action": a.action,
                    "entity_name": _resolve_entity_name(a),
                    "success": a.success,
                    "error_message": a.error_message,
                }
                for a in recent_actions_q
            ]
            rules_data.append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "entity_level": rule.entity_level,
                "action": rule.action,
                "is_active": rule.is_active,
                "last_evaluated_at": rule.last_evaluated_at.isoformat() if rule.last_evaluated_at else None,
                "last_evaluation": (
                    {
                        "executed_at": last_eval.executed_at.isoformat() if last_eval.executed_at else None,
                        "entities_checked": (last_eval.metrics_snapshot or {}).get("entities_checked"),
                        "actions_taken": (last_eval.metrics_snapshot or {}).get("actions_taken"),
                        "top_fail_reason": (last_eval.metrics_snapshot or {}).get("top_fail_reason"),
                        "fail_breakdown": (last_eval.metrics_snapshot or {}).get("fail_breakdown"),
                        "fail_examples": (last_eval.metrics_snapshot or {}).get("fail_examples", []),
                        "funnel_stage": (last_eval.metrics_snapshot or {}).get("funnel_stage"),
                        "dynamic": (last_eval.metrics_snapshot or {}).get("dynamic"),
                        "error_message": last_eval.error_message,
                    }
                    if last_eval else None
                ),
                "recent_actions": recent_actions,
            })

        return _api_response(data={
            "tactic_id": tactic.id,
            "tactic_name": tactic.name,
            "is_active": tactic.is_active,
            "last_run_at": tactic.last_run_at.isoformat() if tactic.last_run_at else None,
            "rules": rules_data,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.delete("/tactics/{tactic_id}")
def delete_tactic_endpoint(
    tactic_id: str,
    current_user: User = Depends(require_section("automation", "edit")),
    db: Session = Depends(get_db),
):
    try:
        tactic = tactic_service.get_tactic(db, tactic_id)
        if not tactic:
            return _api_response(error="Tactic not found")
        if tactic.account_id:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "automation",
                requested_account_id=tactic.account_id, min_level="edit",
            )
            if not ok:
                return _api_response(error=err)
        tactic_service.delete_tactic(db, tactic_id)
        return _api_response(data={"id": tactic_id, "deleted": True})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
