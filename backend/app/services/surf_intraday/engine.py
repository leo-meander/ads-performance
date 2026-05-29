"""SURF Intraday orchestrator — called by the 15-min cron.

  poll_active_surfs(db) is the single entry point. It iterates every active
  SURF Intraday tactic, and for each (tactic, campaign in scope) runs one
  poll cycle:

    1. Get-or-create today's SurfRun (snapshots origin_budget on creation).
    2. Skip if status != 'active' (capped / reverted / errored).
    3. Fetch today's spend + revenue from Meta Insights API.
    4. Compute the spend thresholds from origin_budget × thresholds_pct.
    5. Find the largest threshold the run hasn't acted on yet.
       - None → append a NO_ACTION checkpoint, return.
    6. Resolve tier from current ROAS (with Double Check against last_roas).
       - NO_ACTION → append checkpoint, return.
       - DOUBLE_CHECK_CUT → flow into budget_writer with is_cut=True.
    7. Run the cap stack via resolve_budget_change().
    8. If dry_run or sanity_abort → write a checkpoint with meta_api_called=False.
    9. Else call Meta. Update SurfRun on success; mark errored on failure.
   10. Always append exactly one SurfCheckpoint per tick.

Idempotency:
  Re-firing the same tick on the same spend should write a NO_ACTION row
  (because last_threshold_hit already covers current spend's threshold). The
  engine never reads "wall clock since last tick" — only Meta spend.

Concurrency:
  No Redis lock in v1. The DB UNIQUE on surf_runs(tactic, campaign, run_date)
  prevents duplicate runs. Within a run, racing ticks could both call Meta
  briefly — acceptable risk; cap stack caps the damage to per_check at worst.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.surf import (
    NO_ACTION,
    SURF_RUN_STATUS_ACTIVE,
    SurfRun,
)
from app.models.tactic import Tactic
from app.services.surf_intraday.budget_writer import (
    resolve_budget_change,
    write_to_meta,
)
from app.services.surf_intraday.checkpoint import (
    append_checkpoint,
    get_or_create_run,
    latest_checkpoint,
    mark_run_errored,
    update_run_after_action,
    was_noop_at_threshold,
)
from app.services.surf_intraday.meta_intraday import fetch_today_metrics
from app.services.surf_intraday.tier_resolver import (
    compute_spend_thresholds,
    next_threshold_to_cross,
    resolve_tier,
)

logger = logging.getLogger(__name__)


# Defaults if the tactic config omits a key — match the Madgicx-style
# presentation in the original screenshot.
_DEFAULT_THRESHOLDS_PCT = [0.30, 0.40, 0.50, 0.60, 0.70, 0.85]
_DEFAULT_TIERS = [
    {"roas_min": 1.74, "roas_max": 2.03, "multiplier": 1.30},
    {"roas_min": 2.03, "roas_max": 2.61, "multiplier": 1.50},
    {"roas_min": 2.61, "roas_max": None, "multiplier": 2.00},
]
_DEFAULT_DOUBLE_CHECK_DROP_PCT = 0.20
_DEFAULT_DOUBLE_CHECK_CUT_PCT = 0.80  # cut to 80% of current = -20%

# Tactic preset_type for surf intraday. Kept in sync with
# app/models/tactic.py + app/services/tactic_presets.py.
PRESET_SURF_INTRADAY_CAMPAIGN = "surf_intraday_campaign"


def poll_active_surfs(
    db: Session, *, now_utc: datetime | None = None,
) -> dict:
    """Cron entry. Iterates every active SURF intraday tactic + campaign.

    Returns a summary dict for the cron response body so the operator can
    see "12 campaigns polled, 3 boosted, 1 errored" without reading logs.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    tactics: list[Tactic] = (
        db.query(Tactic)
        .filter(
            Tactic.is_active.is_(True),
            Tactic.preset_type == PRESET_SURF_INTRADAY_CAMPAIGN,
        )
        .all()
    )

    total_polled = 0
    total_actions = 0
    total_errors = 0

    for tactic in tactics:
        cfg = tactic.config or {}
        if cfg.get("kill_switch"):
            logger.info("surf-engine: kill_switch on for tactic %s, skipping", tactic.id)
            continue

        # Tactic must be bound to an account to know access tokens.
        if not tactic.account_id:
            logger.warning("surf-engine: tactic %s has no account_id", tactic.id)
            continue

        account: AdAccount | None = (
            db.query(AdAccount).filter(AdAccount.id == tactic.account_id).first()
        )
        if account is None or not account.access_token_enc:
            logger.warning(
                "surf-engine: tactic %s account missing or no token", tactic.id,
            )
            continue

        # Which campaigns does this tactic apply to? V1: explicit allowlist
        # in tactic.config.campaign_ids (per-campaign opt-in). If empty/None,
        # the tactic is a no-op until the operator binds at least one campaign.
        campaign_ids = cfg.get("campaign_ids") or []
        if not campaign_ids:
            continue

        campaigns: list[Campaign] = (
            db.query(Campaign)
            .filter(
                Campaign.id.in_(campaign_ids),
                Campaign.platform == "meta",
                Campaign.status == "ACTIVE",
            )
            .all()
        )

        for campaign in campaigns:
            total_polled += 1
            try:
                result = _process_campaign(
                    db, tactic=tactic, campaign=campaign,
                    account=account, now_utc=now_utc,
                )
                if result.get("action_taken"):
                    total_actions += 1
                if result.get("error"):
                    total_errors += 1
            except Exception:
                logger.exception(
                    "surf-engine: unhandled error on tactic=%s campaign=%s",
                    tactic.id, campaign.id,
                )
                total_errors += 1

        db.commit()

    summary = {
        "tactics": len(tactics),
        "polled": total_polled,
        "actions": total_actions,
        "errors": total_errors,
    }
    logger.info("surf-engine: %s", summary)
    return summary


def _process_campaign(
    db: Session,
    *,
    tactic: Tactic,
    campaign: Campaign,
    account: AdAccount,
    now_utc: datetime,
) -> dict:
    """Run one poll cycle for (tactic, campaign). Always writes exactly one
    SurfCheckpoint row (even no_action / cap-exhausted) for the audit trail.

    Returns: {action_taken: bool, error: str | None, tier_label: str}.
    """
    cfg = tactic.config or {}

    # 1. Resolve current budget — bail if ABO (no campaign-level budget).
    current_budget = float(campaign.daily_budget or 0)
    if current_budget <= 0:
        logger.info(
            "surf-engine: campaign %s has no daily_budget (likely ABO), skipping",
            campaign.id,
        )
        return {"action_taken": False, "error": None, "tier_label": NO_ACTION}

    # 2. Get-or-create SurfRun. On the first tick of the local day this
    #    snapshots origin_budget = current_budget.
    run, just_created = get_or_create_run(
        db,
        tactic_id=tactic.id,
        campaign=campaign,
        account_tz=account.timezone or "Asia/Ho_Chi_Minh",
        account_currency=account.currency,
        origin_budget=current_budget,
        now_utc=now_utc,
    )
    if run.status != SURF_RUN_STATUS_ACTIVE:
        return {
            "action_taken": False, "error": None,
            "tier_label": "skipped_non_active",
        }

    # 3. Fetch intraday metrics from Meta.
    try:
        metrics = fetch_today_metrics(
            access_token=account.access_token_enc,
            platform_account_id=account.account_id,
            platform_campaign_id=campaign.platform_campaign_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("surf-engine: Meta insights fetch failed campaign=%s", campaign.id)
        append_checkpoint(
            db, run=run, checked_at=now_utc,
            spend_at_check=0.0, roas_at_check=None, threshold_crossed=None,
            tier_label="error", multiplier_applied=None,
            budget_before=current_budget, budget_after=current_budget,
            capped_by=None, meta_api_called=False, meta_api_success=None,
            meta_api_error=f"insights_fetch_failed: {e}", raw_meta_response=None,
        )
        # Don't flip errored on first fetch failure — could be transient.
        return {"action_taken": False, "error": str(e), "tier_label": "error"}

    spend = float(metrics["spend"])
    roas = metrics.get("roas")

    # 4. Compute thresholds from origin_budget × pcts.
    thresholds_pct = cfg.get("spend_thresholds_pct") or _DEFAULT_THRESHOLDS_PCT
    thresholds = compute_spend_thresholds(float(run.origin_budget), thresholds_pct)

    # 5. Find next threshold to act on.
    threshold = next_threshold_to_cross(
        current_spend=spend,
        last_threshold_hit=float(run.last_threshold_hit) if run.last_threshold_hit else None,
        thresholds=thresholds,
    )
    if threshold is None:
        append_checkpoint(
            db, run=run, checked_at=now_utc,
            spend_at_check=spend, roas_at_check=roas,
            threshold_crossed=None,
            tier_label=NO_ACTION, multiplier_applied=None,
            budget_before=current_budget, budget_after=current_budget,
            capped_by=None, meta_api_called=False, meta_api_success=None,
            meta_api_error=None, raw_meta_response=None,
        )
        return {"action_taken": False, "error": None, "tier_label": NO_ACTION}

    # 6. Resolve tier from ROAS (with Double Check).
    last_cp = latest_checkpoint(db, run.id)
    last_roas_val = (
        float(last_cp.roas_at_check)
        if last_cp is not None and last_cp.roas_at_check is not None
        else None
    )
    decision = resolve_tier(
        current_roas=roas if roas is not None else 0.0,
        last_roas=last_roas_val,
        tiers=cfg.get("tiers") or _DEFAULT_TIERS,
        double_check_enabled=bool(cfg.get("double_check_enabled", True)),
        double_check_drop_pct=float(cfg.get("double_check_drop_pct", _DEFAULT_DOUBLE_CHECK_DROP_PCT)),
        double_check_cut_pct=float(cfg.get("double_check_cut_pct", _DEFAULT_DOUBLE_CHECK_CUT_PCT)),
    )

    if decision["tier_label"] == NO_ACTION:
        # Mark threshold acknowledged even though we don't write — so next
        # tick at the same spend doesn't re-evaluate (idempotency).
        append_checkpoint(
            db, run=run, checked_at=now_utc,
            spend_at_check=spend, roas_at_check=roas,
            threshold_crossed=threshold,
            tier_label=NO_ACTION, multiplier_applied=None,
            budget_before=current_budget, budget_after=current_budget,
            capped_by=None, meta_api_called=False, meta_api_success=None,
            meta_api_error=None, raw_meta_response={"reason": decision["reason"]},
        )
        run.last_threshold_hit = threshold
        run.last_roas_at_check = roas
        run.updated_at = now_utc
        return {"action_taken": False, "error": None, "tier_label": NO_ACTION}

    # 7. Cap stack — what budget would we actually send?
    is_cut = bool(decision["cut"])
    max_per_click_abs = (
        float(account.max_cut_per_click_abs)
        if is_cut and account.max_cut_per_click_abs is not None
        else float(account.max_raise_per_click_abs)
        if not is_cut and account.max_raise_per_click_abs is not None
        else None
    )

    cap_result = resolve_budget_change(
        current_budget=current_budget,
        origin_budget=float(run.origin_budget),
        desired_multiplier=float(decision["multiplier"]),
        is_cut=is_cut,
        max_per_click_abs=max_per_click_abs,
        surf_limit_per_day=(
            float(cfg["surf_limit_per_day"]) if cfg.get("surf_limit_per_day") is not None else None
        ),
        total_increase_today=float(run.total_increase_today or 0),
        max_budget_cap_multiplier=(
            float(cfg["max_budget_cap_multiplier"])
            if cfg.get("max_budget_cap_multiplier") is not None else None
        ),
    )

    # 8. Dry run / sanity abort — checkpoint only, no Meta call.
    dry_run = bool(cfg.get("dry_run", True))
    if cap_result["sanity_abort"] or dry_run or cap_result["delta"] == 0:
        append_checkpoint(
            db, run=run, checked_at=now_utc,
            spend_at_check=spend, roas_at_check=roas,
            threshold_crossed=threshold,
            tier_label=decision["tier_label"],
            multiplier_applied=float(decision["multiplier"]),
            budget_before=current_budget,
            budget_after=cap_result["new_budget"],
            capped_by=cap_result["capped_by"],
            meta_api_called=False,
            meta_api_success=None,
            meta_api_error=(
                "sanity_abort" if cap_result["sanity_abort"]
                else ("dry_run" if dry_run else None)
            ),
            raw_meta_response={
                "decision": decision,
                "cap_explain": cap_result["explain"],
            },
        )
        # In dry-run mode, advance the threshold pointer so we don't pile up
        # multiple checkpoints on the same threshold. Sanity abort: same.
        run.last_threshold_hit = threshold
        run.last_roas_at_check = roas
        run.updated_at = now_utc
        return {
            "action_taken": False,  # no Meta write
            "error": None,
            "tier_label": decision["tier_label"],
        }

    # 9. Real write to Meta.
    success, error_message = write_to_meta(
        access_token=account.access_token_enc,
        platform_campaign_id=campaign.platform_campaign_id,
        current_daily_budget=current_budget,
        new_daily_budget=float(cap_result["new_budget"]),
    )
    append_checkpoint(
        db, run=run, checked_at=now_utc,
        spend_at_check=spend, roas_at_check=roas,
        threshold_crossed=threshold,
        tier_label=decision["tier_label"],
        multiplier_applied=float(decision["multiplier"]),
        budget_before=current_budget,
        budget_after=cap_result["new_budget"] if success else current_budget,
        capped_by=cap_result["capped_by"],
        meta_api_called=True,
        meta_api_success=success,
        meta_api_error=error_message,
        raw_meta_response={
            "decision": decision,
            "cap_explain": cap_result["explain"],
        },
    )

    if not success:
        # First failure → just log. Persistent failure handling could mark
        # the run errored, but for now we retry next tick.
        return {
            "action_taken": False, "error": error_message,
            "tier_label": decision["tier_label"],
        }

    # 10. Persist post-action state.
    campaign.daily_budget = float(cap_result["new_budget"])
    update_run_after_action(
        db, run=run,
        new_current_budget=float(cap_result["new_budget"]),
        increase_amount=float(cap_result["delta"]) if not is_cut else 0.0,
        threshold_crossed=threshold,
        roas_at_check=roas,
        capped_today=bool(cap_result["exhausted"]),
    )
    return {
        "action_taken": True, "error": None,
        "tier_label": decision["tier_label"],
    }
