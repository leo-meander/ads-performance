"""Rule engine: evaluates automation rules against campaign/ad-set/ad metrics and executes actions."""

import logging
import operator as op
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.rule import AutomationRule
from app.models.tactic import Tactic
from app.services import google_actions as google_act
from app.services.changelog import describe_diff, log_change
from app.services.meta_actions import (
    enable_ad,
    enable_ad_set,
    enable_campaign,
    pause_ad,
    pause_ad_set,
    pause_campaign,
    update_ad_set_budget,
    update_budget,
    update_campaign_budget,
)
from app.services.metrics_snapshot import get_metrics_snapshot

logger = logging.getLogger(__name__)

OPERATORS = {
    ">": op.gt,
    "<": op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
}

METRIC_COLUMNS = {
    "spend": MetricsCache.spend,
    "impressions": MetricsCache.impressions,
    "clicks": MetricsCache.clicks,
    "conversions": MetricsCache.conversions,
    "revenue": MetricsCache.revenue,
    "roas": MetricsCache.roas,
    "ctr": MetricsCache.ctr,
    "cpc": MetricsCache.cpc,
    "cpa": MetricsCache.cpa,
    "frequency": MetricsCache.frequency,
    "add_to_cart": MetricsCache.add_to_cart,
    "checkouts": MetricsCache.checkouts,
    "searches": MetricsCache.searches,
    "leads": MetricsCache.leads,
}


# ---------------------------------------------------------------------------
# Metric lookup helpers — dispatched by entity level
# ---------------------------------------------------------------------------

def _metric_base_filter(entity_id: str, entity_level: str):
    """Return SQLAlchemy filter clauses for the given entity level."""
    if entity_level == "ad":
        return [MetricsCache.ad_id == entity_id]
    if entity_level == "ad_set":
        return [MetricsCache.ad_set_id == entity_id, MetricsCache.ad_id.is_(None)]
    # campaign (default)
    return [MetricsCache.campaign_id == entity_id, MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None)]


def _get_metric_avg(
    db: Session, entity_id: str, entity_level: str, metric: str, days: int,
) -> float | None:
    """Get average of a metric for an entity over the last N days."""
    col = METRIC_COLUMNS.get(metric)
    if col is None:
        return None

    date_from = date.today() - timedelta(days=days)
    filters = _metric_base_filter(entity_id, entity_level) + [MetricsCache.date >= date_from]

    row = db.query(func.avg(col)).filter(*filters).scalar()
    return float(row) if row is not None else None


def _get_metric_range(
    db: Session, entity_id: str, entity_level: str, metric: str,
    days_from: int, days_to: int,
) -> float | None:
    """Get average of a metric between days_from and days_to ago."""
    col = METRIC_COLUMNS.get(metric)
    if col is None:
        return None

    d_from = date.today() - timedelta(days=days_to)
    d_to = date.today() - timedelta(days=days_from)
    filters = _metric_base_filter(entity_id, entity_level) + [
        MetricsCache.date >= d_from,
        MetricsCache.date <= d_to,
    ]

    row = db.query(func.avg(col)).filter(*filters).scalar()
    return float(row) if row is not None else None


def _get_hours_since_creation(entity) -> float | None:
    """Get hours since entity was created (start_date or created_at)."""
    start = getattr(entity, "start_date", None)
    if start:
        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - start_dt
        return delta.total_seconds() / 3600

    created = getattr(entity, "created_at", None)
    if created:
        if created.tzinfo is None:
            start_dt = created.replace(tzinfo=timezone.utc)
        else:
            start_dt = created
        delta = datetime.now(timezone.utc) - start_dt
        return delta.total_seconds() / 3600
    return None


# ---------------------------------------------------------------------------
# Condition checking
# ---------------------------------------------------------------------------

def check_conditions(
    db: Session, entity, conditions: list[dict], entity_level: str = "campaign",
) -> bool:
    """Check if ALL conditions are met for an entity (AND logic).

    Returns True only if all conditions pass.
    """
    result = check_conditions_detailed(db, entity, conditions, entity_level)
    return result["passed"]


def check_conditions_detailed(
    db: Session, entity, conditions: list[dict], entity_level: str = "campaign",
) -> dict:
    """Check conditions and return detailed results for logging.

    Returns:
        {"passed": bool, "failed_at": str|None, "reason": str|None, "checks": int}
    """
    checks = 0
    for cond in conditions:
        metric = cond.get("metric")
        operator_str = cond.get("operator")

        if not metric or not operator_str:
            continue

        compare_fn = OPERATORS.get(operator_str)
        if not compare_fn:
            return {"passed": False, "failed_at": metric, "reason": f"unknown operator: {operator_str}", "checks": checks}

        checks += 1

        # --- Type 4: Active ads in ad set ---
        if metric == "active_ads_in_adset":
            threshold = cond.get("threshold")
            if threshold is None:
                continue
            if entity_level == "ad_set":
                adset_id = entity.id
            elif entity_level == "ad":
                adset_id = entity.ad_set_id
            else:
                return {"passed": False, "failed_at": metric, "reason": "not applicable at campaign level", "checks": checks}
            count = db.query(Ad).filter(Ad.ad_set_id == adset_id, Ad.status == "ACTIVE").count()
            if not compare_fn(count, float(threshold)):
                return {"passed": False, "failed_at": metric, "reason": f"{count} {operator_str} {threshold} is false", "checks": checks}
            continue

        # --- Type 3: Entity age ---
        if metric == "hours_since_creation":
            threshold = cond.get("threshold")
            if threshold is None:
                continue
            hours = _get_hours_since_creation(entity)
            if hours is None:
                return {"passed": False, "failed_at": metric, "reason": "no creation date", "checks": checks}
            if not compare_fn(hours, float(threshold)):
                return {"passed": False, "failed_at": metric, "reason": f"{hours:.1f}h {operator_str} {threshold}h is false", "checks": checks}
            continue

        # --- Get left-side value (current period) ---
        days = cond.get("days", 7)
        left_val = _get_metric_avg(db, entity.id, entity_level, metric, days)
        if left_val is None:
            return {"passed": False, "failed_at": metric, "reason": "no metrics data", "checks": checks}

        # --- Type 2: Cross-period comparison ---
        compare_metric = cond.get("compare_metric")
        if compare_metric:
            period_from = cond.get("compare_period_from", 7)
            period_to = cond.get("compare_period_to", 15)
            right_val = _get_metric_range(
                db, entity.id, entity_level, compare_metric, period_from, period_to,
            )
            if right_val is None:
                return {"passed": False, "failed_at": metric, "reason": f"no comparison data for {compare_metric}", "checks": checks}
            if not compare_fn(left_val, right_val):
                return {"passed": False, "failed_at": metric, "reason": f"{left_val:.4f} {operator_str} {right_val:.4f} is false", "checks": checks}
            continue

        # --- Type 1: Static threshold ---
        threshold = cond.get("threshold")
        if threshold is None:
            continue
        if not compare_fn(left_val, float(threshold)):
            return {"passed": False, "failed_at": metric, "reason": f"{left_val:.4f} {operator_str} {threshold} is false", "checks": checks}

    return {"passed": True, "failed_at": None, "reason": None, "checks": checks}


# ---------------------------------------------------------------------------
# Entity querying
# ---------------------------------------------------------------------------

def _get_matching_campaigns(db: Session, rule: AutomationRule) -> list[Campaign]:
    q = db.query(Campaign)
    if rule.platform != "all":
        q = q.filter(Campaign.platform == rule.platform)
    if rule.account_id:
        q = q.filter(Campaign.account_id == rule.account_id)
    if rule.action != "enable_campaign":
        q = q.filter(Campaign.status == "ACTIVE")
    return q.all()


def _get_matching_adsets(db: Session, rule: AutomationRule) -> list[AdSet]:
    q = db.query(AdSet).join(Campaign, AdSet.campaign_id == Campaign.id)
    if rule.platform != "all":
        q = q.filter(AdSet.platform == rule.platform)
    if rule.account_id:
        q = q.filter(AdSet.account_id == rule.account_id)
    # Only ad sets within ACTIVE campaigns
    q = q.filter(Campaign.status == "ACTIVE")
    if rule.action not in ("enable_adset", "enable_ad_set"):
        q = q.filter(AdSet.status == "ACTIVE")
    return q.all()


def _get_matching_ads(db: Session, rule: AutomationRule) -> list[Ad]:
    q = db.query(Ad).join(Campaign, Ad.campaign_id == Campaign.id)
    if rule.platform != "all":
        q = q.filter(Ad.platform == rule.platform)
    if rule.account_id:
        q = q.filter(Ad.account_id == rule.account_id)
    # Only ads within ACTIVE campaigns
    q = q.filter(Campaign.status == "ACTIVE")
    if rule.action not in ("enable_ad",):
        q = q.filter(Ad.status == "ACTIVE")
    return q.all()


# ---------------------------------------------------------------------------
# Entity ID resolution helpers
# ---------------------------------------------------------------------------

def _resolve_campaign_id(entity, entity_level: str) -> str | None:
    if entity_level == "campaign":
        return entity.id
    return getattr(entity, "campaign_id", None)


def _resolve_adset_id(entity, entity_level: str) -> str | None:
    if entity_level == "ad_set":
        return entity.id
    if entity_level == "ad":
        return getattr(entity, "ad_set_id", None)
    return None


def _resolve_ad_id(entity, entity_level: str) -> str | None:
    if entity_level == "ad":
        return entity.id
    return None


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def execute_action(
    db: Session, rule: AutomationRule, entity, entity_level: str = "campaign",
) -> dict:
    """Execute the rule's action on an entity and log the result."""
    now = datetime.now(timezone.utc)
    account = db.query(AdAccount).filter(AdAccount.id == entity.account_id if hasattr(entity, "account_id") else None).first()
    access_token = account.access_token_enc if account else None

    # Determine the correct account_id for campaign-level entities
    if not account and entity_level == "campaign":
        account = db.query(AdAccount).filter(AdAccount.id == entity.account_id).first()
        access_token = account.access_token_enc if account else None

    # Get metrics snapshot for audit
    max_days = max((c.get("days", 7) for c in rule.conditions), default=7)
    snapshot = get_metrics_snapshot(db, entity.id, entity_level, days=max_days)

    # Capture pre-mutation state — used both for change_log diffs and for the
    # tactic revert phase tomorrow.
    pre_status = getattr(entity, "status", None)
    pre_budget = (
        float(entity.daily_budget or 0) if hasattr(entity, "daily_budget") else None
    )
    original_state: dict = {"status": pre_status}
    if pre_budget is not None:
        original_state["daily_budget"] = pre_budget

    # If this rule belongs to a tactic, load it so we can stamp revert_policy +
    # branch to tactic-specific budget logic (SURF cap, SUNSETTING, Scale Winning).
    tactic: Tactic | None = None
    if rule.tactic_id:
        tactic = db.query(Tactic).filter(Tactic.id == rule.tactic_id).first()

    success = False
    error_message = None
    action = rule.action

    # Tactic-specific extras stamped onto the action log for the revert phase.
    tactic_log_extras: dict = {}
    if tactic:
        tactic_log_extras = {
            "tactic_id": tactic.id,
            "preset_type": (tactic.config or {}).get("_preset_type") or tactic.preset_type,
            "revert_policy": (tactic.config or {}).get("_revert_policy", "none"),
        }

    is_google = getattr(entity, "platform", None) == "google"
    customer_id = account.account_id.replace("-", "") if account and is_google else None

    try:
        if action == "send_alert":
            success = True
            logger.info("Alert: Rule '%s' triggered for %s '%s'", rule.name, entity_level, entity.name)

        elif action == "pause_campaign":
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                google_act.pause_campaign(customer_id, entity.platform_campaign_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                pause_campaign(access_token, entity.platform_campaign_id)
            entity.status = "PAUSED"
            success = True

        elif action == "enable_campaign":
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                google_act.enable_campaign(customer_id, entity.platform_campaign_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                enable_campaign(access_token, entity.platform_campaign_id)
            entity.status = "ACTIVE"
            success = True

        elif action == "pause_adset":
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                google_act.pause_ad_group(customer_id, entity.platform_adset_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                pause_ad_set(access_token, entity.platform_adset_id)
            entity.status = "PAUSED"
            success = True

        elif action == "enable_adset":
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                google_act.enable_ad_group(customer_id, entity.platform_adset_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                enable_ad_set(access_token, entity.platform_adset_id)
            entity.status = "ACTIVE"
            success = True

        elif action == "pause_ad":
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                adset = db.query(AdSet).filter(AdSet.id == entity.ad_set_id).first()
                if not adset:
                    raise ValueError("Ad group not found for Google ad")
                google_act.pause_ad(customer_id, adset.platform_adset_id, entity.platform_ad_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                pause_ad(access_token, entity.platform_ad_id)
            entity.status = "PAUSED"
            success = True

        elif action == "enable_ad":
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                adset = db.query(AdSet).filter(AdSet.id == entity.ad_set_id).first()
                if not adset:
                    raise ValueError("Ad group not found for Google ad")
                google_act.enable_ad(customer_id, adset.platform_adset_id, entity.platform_ad_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                enable_ad(access_token, entity.platform_ad_id)
            entity.status = "ACTIVE"
            success = True

        elif action == "adjust_budget":
            # Tactic-aware budget resolution handles SURF cap, SUNSETTING steps,
            # and Scale Winning ratchets. Standalone rules fall through to plain
            # multiplier behavior for backward compat with the /rules UI.
            params = rule.action_params or {}
            current_budget = float(entity.daily_budget or 0)

            new_budget: int | None = None
            should_pause = False
            tactic_compute_extras: dict = {}

            if rule.tactic_id:
                # Lazy import to avoid circular deps (tactic_engine imports rule_engine indirectly).
                from app.services import tactic_engine as te
                compute = te.compute_tactic_budget(db, rule, entity, entity_level)
                new_budget = compute["new_budget"]
                should_pause = compute["should_pause"]
                tactic_compute_extras = {
                    "sunsetting": params.get("sunsetting", False),
                    "scale_winning": params.get("scale_winning", False),
                    "sunsetting_step": compute["sunsetting_step"],
                    "origin_budget": compute["origin_budget"],
                    "cap_applied": compute["cap_applied"],
                }
            else:
                multiplier = float(params.get("budget_multiplier", 1.0))
                new_budget = int(current_budget * multiplier)

            if should_pause:
                # SUNSETTING step 3 — swap into pause path.
                if entity_level != "ad_set":
                    raise ValueError("Sunsetting pause only supported on ad_set level")
                if is_google:
                    if not customer_id:
                        raise ValueError("No customer_id for Google account")
                    google_act.pause_ad_group(customer_id, entity.platform_adset_id)
                else:
                    if not access_token:
                        raise ValueError("No access token for account")
                    pause_ad_set(access_token, entity.platform_adset_id)
                entity.status = "PAUSED"
                # Record the effective action for the log: caller wrote 'adjust_budget'
                # but we executed a pause. Surface that.
                action = "pause_adset"
                success = True
            else:
                if new_budget is None or new_budget <= 0:
                    raise ValueError(f"Invalid new budget: {new_budget}")
                if entity_level == "ad_set":
                    if is_google:
                        # Google ad-group budget edits go through update_campaign_budget
                        # on the parent campaign — not supported in this tactic path.
                        raise ValueError("Google ad_set budget adjust not supported via tactics yet")
                    if not access_token:
                        raise ValueError("No access token for account")
                    update_ad_set_budget(
                        access_token, entity.platform_adset_id,
                        current_daily_budget=current_budget,
                        new_daily_budget=float(new_budget),
                        # Tactic-driven moves enforce their own cap via
                        # compute_tactic_budget; the 25% guard is for ad-hoc rules.
                        force=bool(rule.tactic_id),
                    )
                else:
                    if is_google:
                        if not customer_id:
                            raise ValueError("No customer_id for Google account")
                        new_budget_micros = new_budget * 1_000_000
                        google_act.update_campaign_budget(customer_id, entity.platform_campaign_id, new_budget_micros)
                    else:
                        if not access_token:
                            raise ValueError("No access token for account")
                        if rule.tactic_id:
                            update_campaign_budget(
                                access_token, entity.platform_campaign_id,
                                current_daily_budget=current_budget,
                                new_daily_budget=float(new_budget),
                                force=True,  # tactic-managed cap
                            )
                        else:
                            update_budget(access_token, entity.platform_campaign_id, new_budget)
                entity.daily_budget = new_budget
                success = True

            # Stamp compute context onto extras so revert + observability work.
            if tactic_compute_extras:
                tactic_log_extras.update(tactic_compute_extras)

        else:
            raise ValueError(f"Unknown action: {action}")

    except Exception as e:
        error_message = str(e)
        logger.exception("Action failed for rule '%s' on %s '%s'", rule.name, entity_level, entity.name)

    # Capture post-mutation state for the revert phase.
    post_status = getattr(entity, "status", None)
    post_budget = (
        float(entity.daily_budget or 0) if hasattr(entity, "daily_budget") else None
    )
    new_state: dict = {"status": post_status}
    if post_budget is not None:
        new_state["daily_budget"] = post_budget

    # Build enriched action_params: keep the rule's raw config under rule_params
    # so the engine can still read it, and add execution context for revert/UI.
    log_action_params: dict = {
        "rule_params": rule.action_params,
        "original_state": original_state,
        "new_state": new_state,
    }
    if tactic_log_extras:
        log_action_params.update(tactic_log_extras)

    # Create immutable action log
    log = ActionLog(
        rule_id=rule.id,
        campaign_id=_resolve_campaign_id(entity, entity_level),
        ad_set_id=_resolve_adset_id(entity, entity_level),
        ad_id=_resolve_ad_id(entity, entity_level),
        platform=entity.platform,
        action=action,
        action_params=log_action_params,
        triggered_by="rule",
        metrics_snapshot=snapshot,
        success=success,
        error_message=error_message,
        executed_at=now,
    )
    db.add(log)
    db.flush()  # Populate log.id for change_log_entries.action_log_id link.

    # Emit a user-facing change log entry for successful state-changing actions.
    # Failures aren't real changes — they go to action_logs only for debugging.
    if success:
        before_val: dict | None = None
        after_val: dict | None = None
        if action in ("pause_campaign", "pause_adset", "pause_ad"):
            before_val = {"status": pre_status or "ACTIVE"}
            after_val = {"status": "PAUSED"}
        elif action in ("enable_campaign", "enable_adset", "enable_ad"):
            before_val = {"status": pre_status or "PAUSED"}
            after_val = {"status": "ACTIVE"}
        elif action == "adjust_budget":
            before_val = {"daily_budget": pre_budget}
            after_val = {"daily_budget": float(entity.daily_budget or 0)}

        change_category = (
            "automation_rule_applied" if action == "send_alert" else "ad_mutation"
        )
        title_diff = describe_diff(before_val, after_val)
        title_body = title_diff or action.replace("_", " ").title()
        title = f"[{rule.name}] {title_body}"[:200]

        log_change(
            db,
            category=change_category,
            title=title,
            source="auto",
            triggered_by="rule",
            occurred_at=now,
            description=(
                f"Rule '{rule.name}' → {action} on {entity_level} '{entity.name}'"
            ),
            campaign_id=_resolve_campaign_id(entity, entity_level),
            ad_set_id=_resolve_adset_id(entity, entity_level),
            ad_id=_resolve_ad_id(entity, entity_level),
            account_id=getattr(entity, "account_id", None),
            platform=entity.platform,
            before_value=before_val,
            after_value=after_val,
            metrics_snapshot=snapshot,
            rule_id=rule.id,
            action_log_id=log.id,
        )

    return {
        "entity_level": entity_level,
        "entity_id": entity.id,
        "entity_name": entity.name,
        "campaign_id": _resolve_campaign_id(entity, entity_level),
        "action": action,
        "success": success,
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def evaluate_rule(db: Session, rule: AutomationRule) -> list[dict]:
    """Evaluate a rule against all matching entities.

    Returns list of action results for entities that matched conditions.
    Always logs a summary entry to action_logs for visibility.
    """
    now = datetime.now(timezone.utc)
    entity_level = getattr(rule, "entity_level", "campaign") or "campaign"

    if entity_level == "ad":
        entities = _get_matching_ads(db, rule)
    elif entity_level == "ad_set":
        entities = _get_matching_adsets(db, rule)
    else:
        entities = _get_matching_campaigns(db, rule)

    results = []
    fail_counts: dict[str, int] = {}  # metric -> count of entities that failed on it
    # Track up to N concrete fail examples so the UI can show *why*, not just
    # "X entities failed". Each entry: {entity_name, failed_at, reason}.
    _MAX_FAIL_EXAMPLES = 5
    fail_examples: list[dict] = []

    for entity in entities:
        detail = check_conditions_detailed(db, entity, rule.conditions, entity_level)
        if detail["passed"]:
            result = execute_action(db, rule, entity, entity_level)
            results.append(result)
        else:
            failed_at = detail["failed_at"] or "unknown"
            fail_counts[failed_at] = fail_counts.get(failed_at, 0) + 1
            if len(fail_examples) < _MAX_FAIL_EXAMPLES:
                fail_examples.append({
                    "entity_id": getattr(entity, "id", None),
                    "entity_name": getattr(entity, "name", None),
                    "failed_at": failed_at,
                    "reason": detail.get("reason"),
                })

    # Always log an evaluation summary
    summary_snapshot = {
        "entities_checked": len(entities),
        "actions_taken": len(results),
        "entity_level": entity_level,
    }
    if fail_counts:
        # Sort by count descending, show top reasons
        sorted_fails = sorted(fail_counts.items(), key=lambda x: -x[1])
        summary_snapshot["fail_breakdown"] = {k: v for k, v in sorted_fails}
        summary_snapshot["top_fail_reason"] = sorted_fails[0][0]
        summary_snapshot["fail_examples"] = fail_examples

    log = ActionLog(
        rule_id=rule.id,
        campaign_id=None,
        ad_set_id=None,
        ad_id=None,
        platform=rule.platform,
        action="evaluation_summary",
        action_params=None,
        triggered_by="rule",
        metrics_snapshot=summary_snapshot,
        success=True,
        error_message=None if results or not entities else f"0/{len(entities)} entities matched all conditions",
        executed_at=now,
    )
    db.add(log)

    # Update last evaluated timestamp
    rule.last_evaluated_at = now
    db.commit()

    logger.info(
        "Rule '%s' evaluated (%s level): %d entities checked, %d actions taken",
        rule.name, entity_level, len(entities), len(results),
    )
    return results


def evaluate_all_rules(
    db: Session,
    *,
    tactics_filter: str = "all",
) -> list[dict]:
    """Evaluate all active rules. Called after sync.

    tactics_filter:
      - 'all' (default, /api/rules/evaluate-all): every active rule
      - 'no_tactics': only rules where tactic_id IS NULL — used by sync_all_platforms
        so tactic rules don't fire on every intraday sync (would compound budget
        multipliers across runs).
      - 'tactic_only': only rules where tactic_id IS NOT NULL — used by the
        once-per-day run-daily-tactics cron.
    """
    q = db.query(AutomationRule).filter(AutomationRule.is_active.is_(True))
    if tactics_filter == "no_tactics":
        q = q.filter(AutomationRule.tactic_id.is_(None))
    elif tactics_filter == "tactic_only":
        q = q.filter(AutomationRule.tactic_id.isnot(None))
    elif tactics_filter != "all":
        raise ValueError(f"unknown tactics_filter: {tactics_filter}")
    rules = q.all()
    all_results = []

    for rule in rules:
        try:
            results = evaluate_rule(db, rule)
            all_results.append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "entity_level": getattr(rule, "entity_level", "campaign"),
                "actions_taken": len(results),
                "results": results,
            })
        except Exception as e:
            logger.exception("Failed to evaluate rule '%s'", rule.name)
            all_results.append({
                "rule_id": rule.id,
                "rule_name": rule.name,
                "error": str(e),
            })

    return all_results


# ---------------------------------------------------------------------------
# Daily re-enable: undo "Pause Ad Today" from previous days
# ---------------------------------------------------------------------------

def reenable_paused_ads(db: Session) -> list[dict]:
    """Re-enable ads that were paused by 'pause_ad' rules on previous days.

    Finds action_logs where:
    - action = 'pause_ad'
    - triggered_by = 'rule'
    - success = True
    - executed_at < today (paused before today)
    - ad is still PAUSED

    Re-enables them via Meta API and logs the action.
    """
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)

    # Find ads paused by rules before today
    paused_logs = (
        db.query(ActionLog)
        .filter(
            ActionLog.action == "pause_ad",
            ActionLog.triggered_by == "rule",
            ActionLog.success.is_(True),
            ActionLog.ad_id.isnot(None),
            ActionLog.executed_at < today_start,
        )
        .all()
    )

    # Skip tactic-driven pauses — those are owned by tactic_engine.revert_tactic_actions
    # which honors the tactic's revert_policy (REVERT_NEXT_DAY vs REVERT_NONE).
    # Without this filter we'd resurrect ads that a PAUSE_PERMANENT tactic just killed.
    ad_ids_to_reenable: set = set()
    for log in paused_logs:
        ap = log.action_params if isinstance(log.action_params, dict) else None
        if ap and ap.get("tactic_id"):
            continue
        ad_ids_to_reenable.add(log.ad_id)

    if not ad_ids_to_reenable:
        logger.info("No ads to re-enable today")
        return []

    results = []
    for ad_id in ad_ids_to_reenable:
        ad_obj = db.query(Ad).filter(Ad.id == ad_id, Ad.status == "PAUSED").first()
        if not ad_obj:
            continue  # already re-enabled or deleted

        account = db.query(AdAccount).filter(AdAccount.id == ad_obj.account_id).first()
        access_token = account.access_token_enc if account else None

        success = False
        error_message = None

        try:
            if ad_obj.platform == "google":
                customer_id = account.account_id.replace("-", "") if account else None
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                adset = db.query(AdSet).filter(AdSet.id == ad_obj.ad_set_id).first()
                if not adset:
                    raise ValueError("Ad group not found for Google ad")
                google_act.enable_ad(customer_id, adset.platform_adset_id, ad_obj.platform_ad_id)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                enable_ad(access_token, ad_obj.platform_ad_id)
            ad_obj.status = "ACTIVE"
            success = True
            logger.info("Re-enabled ad %s (%s)", ad_obj.name, ad_obj.platform_ad_id)
        except Exception as e:
            error_message = str(e)
            logger.exception("Failed to re-enable ad %s", ad_obj.platform_ad_id)

        # Log the re-enable action
        log = ActionLog(
            rule_id=None,
            campaign_id=ad_obj.campaign_id,
            ad_set_id=ad_obj.ad_set_id,
            ad_id=ad_obj.id,
            platform=ad_obj.platform,
            action="reenable_ad",
            action_params={"reason": "daily_reenable_after_pause_ad_today"},
            triggered_by="rule",
            metrics_snapshot=None,
            success=success,
            error_message=error_message,
            executed_at=now,
        )
        db.add(log)
        db.flush()

        if success:
            log_change(
                db,
                category="ad_mutation",
                title=f"Ad re-enabled (daily cycle): {ad_obj.name}"[:200],
                source="auto",
                triggered_by="rule",
                occurred_at=now,
                description="Automatic re-enable of ads paused by 'pause_ad' rules on previous days.",
                campaign_id=ad_obj.campaign_id,
                ad_set_id=ad_obj.ad_set_id,
                ad_id=ad_obj.id,
                account_id=ad_obj.account_id,
                platform=ad_obj.platform,
                before_value={"status": "PAUSED"},
                after_value={"status": "ACTIVE"},
                action_log_id=log.id,
            )

        results.append({
            "ad_id": ad_obj.id,
            "ad_name": ad_obj.name,
            "success": success,
            "error": error_message,
        })

    db.commit()
    logger.info("Daily re-enable complete: %d ads processed, %d succeeded",
                len(results), sum(1 for r in results if r["success"]))
    return results
