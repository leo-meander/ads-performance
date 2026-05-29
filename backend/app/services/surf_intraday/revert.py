"""End-of-day revert: restore origin_budget when each branch hits local midnight.

Called by /internal/tasks/surf-end-of-day-revert (hourly cron). The endpoint
fires every hour; this function self-filters down to runs whose LOCAL date
has rolled past run.run_date — so a Saigon branch reverts at 17:00 UTC and
Osaka at 15:00 UTC even though the cron fires every hour for everyone.

Revert phase:
  1. Find SurfRun rows with status='active' AND
     local_now > run.run_date (i.e. it's tomorrow in that branch's tz).
  2. For each, call update_campaign_budget(force=True) to restore origin.
  3. Flip status='reverted', set reverted_at=now.
  4. Write a synthetic SurfCheckpoint marking the revert (audit).
  5. Mirror to action_logs (same shape as rule_engine reverts).

Idempotent: re-running this function with no rows due is a no-op. If the
status flip already happened (status != 'active'), the SELECT skips it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.campaign import Campaign
from app.models.surf import (
    NO_ACTION,
    SURF_RUN_STATUS_ACTIVE,
    SURF_RUN_STATUS_ERRORED,
    SURF_RUN_STATUS_REVERTED,
    SurfRun,
)
from app.services.changelog import log_change
from app.services.surf_intraday.budget_writer import write_to_meta
from app.services.surf_intraday.checkpoint import (
    append_checkpoint,
    local_date_for,
)

logger = logging.getLogger(__name__)


def revert_end_of_day_runs(
    db: Session, *, now_utc: datetime | None = None,
) -> dict[str, int]:
    """Restore origin_budget on every SurfRun whose local day has rolled past.

    Returns:
      {
        "candidates":  N,   # active runs at the start of the call
        "due":         N,   # runs whose local day has rolled past
        "reverted":    N,   # successful Meta writes
        "failed":      N,   # Meta write failed (status set to errored)
      }
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    active_runs: list[SurfRun] = (
        db.query(SurfRun)
        .filter(SurfRun.status == SURF_RUN_STATUS_ACTIVE)
        .all()
    )

    due: list[SurfRun] = []
    for run in active_runs:
        local_today = local_date_for(run.timezone, now_utc)
        if local_today > run.run_date:
            due.append(run)

    reverted = 0
    failed = 0
    for run in due:
        success = _revert_single(db, run, now_utc)
        if success:
            reverted += 1
        else:
            failed += 1

    db.commit()
    logger.info(
        "surf-revert: candidates=%d due=%d reverted=%d failed=%d",
        len(active_runs), len(due), reverted, failed,
    )
    return {
        "candidates": len(active_runs),
        "due": len(due),
        "reverted": reverted,
        "failed": failed,
    }


def _revert_single(db: Session, run: SurfRun, now_utc: datetime) -> bool:
    """Restore one campaign's daily_budget to run.origin_budget."""
    campaign = db.query(Campaign).filter(Campaign.id == run.campaign_id).first()
    if campaign is None:
        logger.warning("surf-revert: campaign %s gone, marking run errored", run.campaign_id)
        run.status = SURF_RUN_STATUS_ERRORED
        run.updated_at = now_utc
        return False

    account = db.query(AdAccount).filter(AdAccount.id == campaign.account_id).first()
    if account is None or not account.access_token_enc:
        logger.warning(
            "surf-revert: no token for campaign %s, marking errored",
            run.campaign_id,
        )
        run.status = SURF_RUN_STATUS_ERRORED
        run.updated_at = now_utc
        return False

    current = float(campaign.daily_budget or 0)
    target = float(run.origin_budget)

    if current == target:
        # Nothing to restore (no boost happened today, or already at origin).
        # Still mark as reverted so we don't re-check next cron tick.
        run.status = SURF_RUN_STATUS_REVERTED
        run.reverted_at = now_utc
        run.updated_at = now_utc
        return True

    success, error_message = write_to_meta(
        access_token=account.access_token_enc,
        platform_campaign_id=campaign.platform_campaign_id,
        current_daily_budget=current,
        new_daily_budget=target,
    )

    # Synthetic checkpoint — keeps the run timeline coherent.
    append_checkpoint(
        db,
        run=run,
        checked_at=now_utc,
        spend_at_check=0.0,  # not relevant for revert
        roas_at_check=None,
        threshold_crossed=None,
        tier_label=NO_ACTION,
        multiplier_applied=None,
        budget_before=current,
        budget_after=target if success else current,
        capped_by=None,
        meta_api_called=True,
        meta_api_success=success,
        meta_api_error=error_message,
        raw_meta_response={"action": "end_of_day_revert"},
    )

    if not success:
        run.status = SURF_RUN_STATUS_ERRORED
        run.updated_at = now_utc
        return False

    # Persist on entity + run rows.
    campaign.daily_budget = target
    run.current_budget = target
    run.status = SURF_RUN_STATUS_REVERTED
    run.reverted_at = now_utc
    run.updated_at = now_utc

    # Mirror to action_logs for the global Activity Timeline.
    action_log = ActionLog(
        id=str(uuid.uuid4()),
        rule_id=None,
        campaign_id=campaign.id,
        ad_set_id=None,
        ad_id=None,
        platform="meta",
        action="surf_revert",
        action_params={
            "tactic_id": run.tactic_id,
            "surf_run_id": run.id,
            "from_daily_budget": current,
            "new_daily_budget": target,
            "origin_budget": target,
            "currency": run.currency,
        },
        triggered_by="surf_intraday",
        metrics_snapshot=None,
        success=True,
        error_message=None,
        executed_at=now_utc,
    )
    db.add(action_log)
    db.flush()

    log_change(
        db,
        category="ad_mutation",
        title=f"SURF revert · {campaign.name}"[:200],
        source="auto",
        triggered_by="surf_intraday",
        occurred_at=now_utc,
        description=(
            f"End-of-day revert restored daily budget to origin "
            f"({run.currency} {target:.2f})"
        ),
        campaign_id=campaign.id,
        ad_set_id=None,
        ad_id=None,
        account_id=campaign.account_id,
        platform="meta",
        before_value={"daily_budget": current},
        after_value={"daily_budget": target},
        action_log_id=action_log.id,
    )

    return True
