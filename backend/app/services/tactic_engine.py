"""Tactic-specific execution helpers and the daily revert phase.

Lives alongside `rule_engine.py`. The split: `rule_engine` evaluates conditions
and dispatches actions; this module knows about preset semantics
(SURF caps, SUNSETTING steps, Scale Winning ratchets, REVERT_NEXT_DAY undo).

Daily cron orchestration:
    1. revert_tactic_actions(db)   — undo yesterday's REVERT_NEXT_DAY mutations
    2. sync_all_platforms(db)      — pulls fresh metrics (existing fn)
       └─ also fires evaluate_all_rules at the tail
    3. (rules with sunsetting/scale_winning flags branch via the helpers here)
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.rule import AutomationRule
from app.models.tactic import Tactic
from app.services.changelog import log_change
from app.services.meta_actions import (
    enable_ad,
    enable_ad_set,
    update_ad_set_budget,
    update_campaign_budget,
)
from app.services.tactic_presets import REVERT_NEXT_DAY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity loading
# ---------------------------------------------------------------------------

_ENTITY_MODELS = {
    "campaign": Campaign,
    "ad_set": AdSet,
    "ad": Ad,
}


def _load_entity(db: Session, entity_level: str, entity_id: str):
    model = _ENTITY_MODELS.get(entity_level)
    if not model:
        return None
    return db.query(model).filter(model.id == entity_id).first()


def _resolve_entity_level(log: ActionLog) -> str:
    if log.ad_id:
        return "ad"
    if log.ad_set_id:
        return "ad_set"
    return "campaign"


def _resolve_entity_id(log: ActionLog) -> str | None:
    return log.ad_id or log.ad_set_id or log.campaign_id


def _action_params_get(log: ActionLog, key: str, default=None):
    """JSON column may be a string on SQLite older versions — handle gracefully."""
    ap = log.action_params
    if not isinstance(ap, dict):
        return default
    return ap.get(key, default)


# ---------------------------------------------------------------------------
# Sunsetting step machine
# ---------------------------------------------------------------------------

def get_sunsetting_step(
    db: Session, tactic_id: str, entity_level: str, entity_id: str,
) -> int:
    """Count how many sunsetting actions this tactic has already taken on this entity.

    Returns 0 if this is the first firing. Step 1 reduces 25%, step 2 reduces 50%
    (cumulative from original), step 3 pauses.
    """
    filters = [
        ActionLog.success.is_(True),
        ActionLog.triggered_by == "rule",
    ]
    if entity_level == "ad_set":
        filters.append(ActionLog.ad_set_id == entity_id)
    elif entity_level == "campaign":
        filters.append(ActionLog.campaign_id == entity_id)
    else:
        filters.append(ActionLog.ad_id == entity_id)

    # Filter on the JSON marker. ActionLog.action_params is a JSON column;
    # SQLite + PostgreSQL both support comparing extracted keys via cast,
    # but for simplicity we just count rows referencing this tactic and
    # use Python-side filter on the marker.
    logs = (
        db.query(ActionLog)
        .filter(*filters)
        .filter(or_(
            ActionLog.action == "adjust_budget",
            ActionLog.action == "pause_adset",
            ActionLog.action == "pause_campaign",
            ActionLog.action == "pause_ad",
        ))
        .order_by(ActionLog.executed_at.desc())
        .all()
    )
    step = 0
    for log in logs:
        if _action_params_get(log, "tactic_id") != tactic_id:
            continue
        if not _action_params_get(log, "sunsetting"):
            continue
        step += 1
    return step


def get_scale_winning_origin(
    db: Session, tactic_id: str, entity_level: str, entity_id: str,
) -> float | None:
    """Return the budget value before this tactic's first ever scale_winning hit.

    None on first firing (caller treats current budget as origin).
    """
    filters = [
        ActionLog.success.is_(True),
        ActionLog.triggered_by == "rule",
        ActionLog.action == "adjust_budget",
    ]
    if entity_level == "ad_set":
        filters.append(ActionLog.ad_set_id == entity_id)
    else:
        filters.append(ActionLog.campaign_id == entity_id)

    logs = (
        db.query(ActionLog)
        .filter(*filters)
        .order_by(ActionLog.executed_at.asc())
        .all()
    )
    for log in logs:
        if _action_params_get(log, "tactic_id") != tactic_id:
            continue
        if not _action_params_get(log, "scale_winning"):
            continue
        original_state = _action_params_get(log, "original_state") or {}
        budget = original_state.get("daily_budget")
        if budget is not None:
            try:
                return float(budget)
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# Budget computation for tactic-driven adjust_budget actions
# ---------------------------------------------------------------------------

def compute_tactic_budget(
    db: Session,
    rule: AutomationRule,
    entity,
    entity_level: str,
) -> dict[str, Any]:
    """Resolve target daily budget for a tactic-driven adjust_budget mutation.

    Returns:
        {
            "new_budget": int | None,        # None = caller should pause instead
            "should_pause": bool,            # True for sunsetting step 3
            "origin_budget": float,          # what cap is measured against
            "sunsetting_step": int | None,
            "scale_winning": bool,
            "cap_applied": bool,             # True if hit max_budget_cap_multiplier
        }
    """
    params = rule.action_params or {}
    current_budget = float(getattr(entity, "daily_budget", 0) or 0)

    # SUNSETTING branch ---------------------------------------------------
    if params.get("sunsetting") and rule.tactic_id:
        prior_step = get_sunsetting_step(
            db, rule.tactic_id, entity_level, entity.id,
        )
        next_step = prior_step + 1

        # Look up first-ever sunsetting log for original_budget origin.
        origin = _first_sunsetting_origin(db, rule.tactic_id, entity_level, entity.id)
        if origin is None:
            origin = current_budget

        if next_step == 1:
            new = origin * (1 - float(params.get("step1_reduction_pct", 0.25)))
            return {
                "new_budget": max(int(round(new)), 1),
                "should_pause": False,
                "origin_budget": origin,
                "sunsetting_step": next_step,
                "scale_winning": False,
                "cap_applied": False,
            }
        if next_step == 2:
            new = origin * (1 - float(params.get("step2_reduction_pct", 0.50)))
            return {
                "new_budget": max(int(round(new)), 1),
                "should_pause": False,
                "origin_budget": origin,
                "sunsetting_step": next_step,
                "scale_winning": False,
                "cap_applied": False,
            }
        # Step 3+: pause.
        return {
            "new_budget": None,
            "should_pause": True,
            "origin_budget": origin,
            "sunsetting_step": next_step,
            "scale_winning": False,
            "cap_applied": False,
        }

    # SCALE WINNING branch ------------------------------------------------
    if params.get("scale_winning") and rule.tactic_id:
        step_pct = float(params.get("daily_step_pct", 0.20))
        cap_mult = float(params.get("max_budget_cap_multiplier", 3.0))
        origin = get_scale_winning_origin(db, rule.tactic_id, entity_level, entity.id)
        if origin is None:
            origin = current_budget
        target = current_budget * (1 + step_pct)
        ceiling = origin * cap_mult
        cap_applied = target >= ceiling
        new_budget = min(target, ceiling)
        return {
            "new_budget": max(int(round(new_budget)), 1),
            "should_pause": False,
            "origin_budget": origin,
            "sunsetting_step": None,
            "scale_winning": True,
            "cap_applied": cap_applied,
        }

    # Plain multiplier (SURF or legacy adjust_budget) ---------------------
    multiplier = float(params.get("budget_multiplier", 1.0))
    cap_mult = params.get("max_budget_cap_multiplier")
    target = current_budget * multiplier
    cap_applied = False
    if cap_mult is not None:
        ceiling = current_budget * float(cap_mult)
        if target > ceiling:
            target = ceiling
            cap_applied = True
    return {
        "new_budget": max(int(round(target)), 1),
        "should_pause": False,
        "origin_budget": current_budget,
        "sunsetting_step": None,
        "scale_winning": False,
        "cap_applied": cap_applied,
    }


def _first_sunsetting_origin(
    db: Session, tactic_id: str, entity_level: str, entity_id: str,
) -> float | None:
    """Find the original_state.daily_budget from the EARLIEST sunsetting hit
    on this entity by this tactic — the anchor for percentage reductions."""
    filters = [
        ActionLog.success.is_(True),
        ActionLog.triggered_by == "rule",
        ActionLog.action == "adjust_budget",
    ]
    if entity_level == "ad_set":
        filters.append(ActionLog.ad_set_id == entity_id)
    else:
        filters.append(ActionLog.campaign_id == entity_id)

    logs = (
        db.query(ActionLog)
        .filter(*filters)
        .order_by(ActionLog.executed_at.asc())
        .all()
    )
    for log in logs:
        if _action_params_get(log, "tactic_id") != tactic_id:
            continue
        if not _action_params_get(log, "sunsetting"):
            continue
        original = _action_params_get(log, "original_state") or {}
        budget = original.get("daily_budget")
        if budget is not None:
            try:
                return float(budget)
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# Daily revert phase
# ---------------------------------------------------------------------------

def revert_tactic_actions(db: Session, *, lookback_days: int = 2) -> dict[str, Any]:
    """Undo previous-day mutations from REVERT_NEXT_DAY tactics.

    Scope:
      - action_logs where action_params.revert_policy == 'next_day'
      - executed_at within [today - lookback_days, today_start)
      - one revert per (entity, original log) — skip if already reverted

    For each, restore original_state via the Meta API and write:
      - a new ActionLog with action='tactic_revert'
      - a change_log_entries diff entry (so the activity timeline matches)
    """
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    window_start = today_start - timedelta(days=lookback_days)

    # Pull candidate originals — Python-side filter for action_params.revert_policy
    # because JSON path operators differ across sqlite/postgres and the volume
    # is small (one cron run/day).
    candidates: list[ActionLog] = (
        db.query(ActionLog)
        .filter(
            ActionLog.success.is_(True),
            ActionLog.triggered_by == "rule",
            ActionLog.executed_at >= window_start,
            ActionLog.executed_at < today_start,
        )
        .all()
    )

    pending: list[ActionLog] = []
    for log in candidates:
        if _action_params_get(log, "revert_policy") != REVERT_NEXT_DAY:
            continue
        pending.append(log)

    # Dedupe: at most one revert per (entity_level, entity_id, action). Keep the
    # latest mutation — that's the one whose original_state reflects the state
    # before the day's first SURF firing.
    latest_by_entity: dict[tuple[str, str, str], ActionLog] = {}
    for log in pending:
        entity_id = _resolve_entity_id(log)
        if not entity_id:
            continue
        key = (_resolve_entity_level(log), entity_id, log.action)
        prev = latest_by_entity.get(key)
        if prev is None or log.executed_at > prev.executed_at:
            latest_by_entity[key] = log

    # Skip entities that already have a revert log against this original.
    already_reverted_ids = _ids_with_existing_revert(
        db, [log.id for log in latest_by_entity.values()],
    )

    results = []
    for (level, entity_id, action), original_log in latest_by_entity.items():
        if original_log.id in already_reverted_ids:
            continue
        result = _revert_single(db, original_log, level, entity_id)
        results.append(result)

    db.commit()

    summary = {
        "candidates": len(latest_by_entity),
        "reverted": sum(1 for r in results if r.get("success")),
        "failed": sum(1 for r in results if r.get("success") is False),
        "skipped_already_reverted": len(already_reverted_ids),
    }
    logger.info(
        "tactic_revert: candidates=%d reverted=%d failed=%d skipped=%d",
        summary["candidates"], summary["reverted"], summary["failed"], summary["skipped_already_reverted"],
    )
    return summary


def _ids_with_existing_revert(db: Session, original_log_ids: list[str]) -> set[str]:
    """Return the subset of `original_log_ids` that already have a revert recorded.

    Reverts log themselves with action_params.reverted_action_log_id pointing
    back at the original.
    """
    if not original_log_ids:
        return set()
    candidates = (
        db.query(ActionLog)
        .filter(
            ActionLog.action.in_(("tactic_revert",)),
            ActionLog.triggered_by == "tactic_revert",
        )
        .all()
    )
    found: set[str] = set()
    target_set = set(original_log_ids)
    for log in candidates:
        original_id = _action_params_get(log, "reverted_action_log_id")
        if original_id in target_set:
            found.add(original_id)
    return found


def _revert_single(
    db: Session,
    original_log: ActionLog,
    entity_level: str,
    entity_id: str,
) -> dict[str, Any]:
    """Restore one entity to its pre-mutation state and log the revert."""
    entity = _load_entity(db, entity_level, entity_id)
    if not entity:
        return {"success": False, "error": "entity not found", "entity_id": entity_id}

    account = (
        db.query(AdAccount).filter(AdAccount.id == entity.account_id).first()
        if hasattr(entity, "account_id") else None
    )
    if not account or not account.access_token_enc:
        return {"success": False, "error": "no access token", "entity_id": entity_id}

    original_state = _action_params_get(original_log, "original_state") or {}
    new_state_after_revert: dict[str, Any] = {}
    pre_status = getattr(entity, "status", None)
    pre_budget = float(entity.daily_budget) if getattr(entity, "daily_budget", None) else None

    action = original_log.action
    revert_action = None
    success = False
    error_message = None

    try:
        if action == "adjust_budget":
            original_budget = original_state.get("daily_budget")
            if original_budget is None:
                raise ValueError("no original_state.daily_budget to revert to")
            if entity_level == "ad_set":
                update_ad_set_budget(
                    account.access_token_enc, entity.platform_adset_id,
                    current_daily_budget=float(entity.daily_budget or 0),
                    new_daily_budget=float(original_budget),
                    force=True,  # revert never trips the 25% guard
                )
            else:
                update_campaign_budget(
                    account.access_token_enc, entity.platform_campaign_id,
                    current_daily_budget=float(entity.daily_budget or 0),
                    new_daily_budget=float(original_budget),
                    force=True,
                )
            entity.daily_budget = original_budget
            revert_action = "restore_budget"
            new_state_after_revert = {"daily_budget": float(original_budget)}
            success = True

        elif action in ("pause_ad",):
            enable_ad(account.access_token_enc, entity.platform_ad_id)
            entity.status = "ACTIVE"
            revert_action = "enable_ad"
            new_state_after_revert = {"status": "ACTIVE"}
            success = True

        elif action == "pause_adset":
            enable_ad_set(account.access_token_enc, entity.platform_adset_id)
            entity.status = "ACTIVE"
            revert_action = "enable_adset"
            new_state_after_revert = {"status": "ACTIVE"}
            success = True

        else:
            raise ValueError(f"unsupported revert for action={action}")
    except Exception as e:
        error_message = str(e)
        logger.exception("revert failed for action_log %s entity=%s", original_log.id, entity_id)

    now = datetime.now(timezone.utc)
    revert_log = ActionLog(
        rule_id=original_log.rule_id,
        campaign_id=original_log.campaign_id,
        ad_set_id=original_log.ad_set_id,
        ad_id=original_log.ad_id,
        platform=original_log.platform,
        action="tactic_revert",
        action_params={
            "reverted_action_log_id": original_log.id,
            "original_action": action,
            "revert_action": revert_action,
            "tactic_id": _action_params_get(original_log, "tactic_id"),
            "preset_type": _action_params_get(original_log, "preset_type"),
            "original_state": original_state,
            "new_state": new_state_after_revert,
        },
        triggered_by="tactic_revert",
        metrics_snapshot=None,
        success=success,
        error_message=error_message,
        executed_at=now,
    )
    db.add(revert_log)
    db.flush()

    if success:
        before_val: dict[str, Any] = {}
        after_val: dict[str, Any] = {}
        if action == "adjust_budget":
            before_val = {"daily_budget": pre_budget}
            after_val = new_state_after_revert
        else:
            before_val = {"status": pre_status or "PAUSED"}
            after_val = new_state_after_revert
        log_change(
            db,
            category="ad_mutation",
            title=f"Tactic revert: {revert_action} on {entity_level} '{getattr(entity, 'name', entity_id)}'"[:200],
            source="auto",
            triggered_by="tactic_revert",
            occurred_at=now,
            description=(
                f"Auto-revert of previous day's {action} (action_log {original_log.id}). "
                f"Restored to pre-tactic state."
            ),
            campaign_id=original_log.campaign_id,
            ad_set_id=original_log.ad_set_id,
            ad_id=original_log.ad_id,
            account_id=getattr(entity, "account_id", None),
            platform=original_log.platform,
            before_value=before_val,
            after_value=after_val,
            rule_id=original_log.rule_id,
            action_log_id=revert_log.id,
        )

    return {
        "entity_id": entity_id,
        "entity_level": entity_level,
        "original_action": action,
        "revert_action": revert_action,
        "success": success,
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# Per-tactic last_run_at bookkeeping
# ---------------------------------------------------------------------------

def stamp_last_run(db: Session) -> int:
    """After a daily cron pass, mark every active tactic with last_run_at=now.

    Cheap — one UPDATE — and gives the UI a "Last run" column without us
    threading the tactic_id through evaluate_all_rules. Returns row count.
    """
    now = datetime.now(timezone.utc)
    count = (
        db.query(Tactic)
        .filter(Tactic.is_active.is_(True))
        .update({"last_run_at": now, "updated_at": now}, synchronize_session=False)
    )
    db.commit()
    return count
