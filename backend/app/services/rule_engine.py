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
from app.services import google_actions as google_act
from app.services.meta_actions import (
    enable_ad,
    enable_ad_set,
    enable_campaign,
    pause_ad,
    pause_ad_set,
    pause_campaign,
    update_budget,
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

    success = False
    error_message = None
    action = rule.action

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
            params = rule.action_params or {}
            multiplier = params.get("budget_multiplier", 1.0)
            current_budget = float(entity.daily_budget or 0)
            new_budget = int(current_budget * multiplier)
            if new_budget <= 0:
                raise ValueError(f"Invalid new budget: {new_budget}")
            if is_google:
                if not customer_id:
                    raise ValueError("No customer_id for Google account")
                new_budget_micros = new_budget * 1_000_000
                google_act.update_campaign_budget(customer_id, entity.platform_campaign_id, new_budget_micros)
            else:
                if not access_token:
                    raise ValueError("No access token for account")
                update_budget(access_token, entity.platform_campaign_id, new_budget)
            entity.daily_budget = new_budget
            success = True

        else:
            raise ValueError(f"Unknown action: {action}")

    except Exception as e:
        error_message = str(e)
        logger.exception("Action failed for rule '%s' on %s '%s'", rule.name, entity_level, entity.name)

    # Create immutable action log
    log = ActionLog(
        rule_id=rule.id,
        campaign_id=_resolve_campaign_id(entity, entity_level),
        ad_set_id=_resolve_adset_id(entity, entity_level),
        ad_id=_resolve_ad_id(entity, entity_level),
        platform=entity.platform,
        action=action,
        action_params=rule.action_params,
        triggered_by="rule",
        metrics_snapshot=snapshot,
        success=success,
        error_message=error_message,
        executed_at=now,
    )
    db.add(log)

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
    # Track failure reasons for summary
    fail_counts: dict[str, int] = {}  # metric -> count of entities that failed on it

    for entity in entities:
        detail = check_conditions_detailed(db, entity, rule.conditions, entity_level)
        if detail["passed"]:
            result = execute_action(db, rule, entity, entity_level)
            results.append(result)
        else:
            failed_at = detail["failed_at"] or "unknown"
            fail_counts[failed_at] = fail_counts.get(failed_at, 0) + 1

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


def evaluate_all_rules(db: Session) -> list[dict]:
    """Evaluate all active rules. Called after sync."""
    rules = db.query(AutomationRule).filter(AutomationRule.is_active.is_(True)).all()
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

    # Deduplicate by ad_id (only re-enable each ad once)
    ad_ids_to_reenable = set()
    for log in paused_logs:
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
