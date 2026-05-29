"""SurfRun + SurfCheckpoint persistence helpers.

`engine.py` calls these to:
  - get_or_create the SurfRun for (tactic, campaign, local_date)
  - read the latest checkpoint (for Double Check comparison + idempotency)
  - append a new checkpoint (with the cap reason if any binding occurred)

Append-only contract for SurfCheckpoint is enforced by convention (this
module never UPDATEs checkpoints — only INSERTs). SurfRun is the only
mutable row in the SURF surface.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.surf import (
    SURF_RUN_STATUS_ACTIVE,
    NO_ACTION,
    SurfCheckpoint,
    SurfRun,
)


def local_date_for(tz_name: str, when_utc: datetime | None = None) -> date:
    """Resolve the local-tz date for a UTC moment.

    Example: when_utc=2026-05-28 16:30 UTC, tz_name='Asia/Ho_Chi_Minh' (UTC+7)
             → 2026-05-28 23:30 local → returns 2026-05-28
             when_utc=2026-05-28 17:30 UTC, same tz → 2026-05-29 00:30 local
             → returns 2026-05-29 (a new SurfRun starts now)
    """
    if when_utc is None:
        when_utc = datetime.now(timezone.utc)
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=timezone.utc)
    try:
        local = when_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        # Bad tz name → fall back to UTC. Migration 043 backfills valid
        # IANA names so this should not happen in practice.
        local = when_utc
    return local.date()


def get_or_create_run(
    db: Session,
    *,
    tactic_id: str,
    campaign: Campaign,
    account_tz: str,
    account_currency: str,
    origin_budget: float,
    now_utc: datetime | None = None,
) -> tuple[SurfRun, bool]:
    """Find today's SurfRun for (tactic, campaign) or create it.

    On creation: snapshots origin_budget from the campaign's current
    daily_budget. This is the anchor for end-of-day revert + the
    max_budget_cap_multiplier ceiling.

    Returns (run, created) where `created` is True on first call of the
    local day. Caller uses that flag to skip Double Check on the first tick.

    UNIQUE(tactic_id, campaign_id, run_date) is the safety net against
    duplicate runs from racing ticks.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    today_local = local_date_for(account_tz, now_utc)

    run = (
        db.query(SurfRun)
        .filter(
            SurfRun.tactic_id == tactic_id,
            SurfRun.campaign_id == campaign.id,
            SurfRun.run_date == today_local,
        )
        .first()
    )
    if run is not None:
        return run, False

    run = SurfRun(
        id=str(uuid.uuid4()),
        tactic_id=tactic_id,
        campaign_id=campaign.id,
        run_date=today_local,
        timezone=account_tz,
        origin_budget=origin_budget,
        current_budget=origin_budget,
        total_increase_today=0,
        last_threshold_hit=None,
        last_roas_at_check=None,
        status=SURF_RUN_STATUS_ACTIVE,
        currency=account_currency,
        created_at=now_utc,
        updated_at=now_utc,
    )
    db.add(run)
    db.flush()
    return run, True


def latest_checkpoint(db: Session, run_id: str) -> SurfCheckpoint | None:
    """Most recent checkpoint for this run. Used to populate `last_roas` for
    Double Check and to read the previous threshold hit for idempotency."""
    return (
        db.query(SurfCheckpoint)
        .filter(SurfCheckpoint.run_id == run_id)
        .order_by(SurfCheckpoint.checked_at.desc())
        .first()
    )


def append_checkpoint(
    db: Session,
    *,
    run: SurfRun,
    checked_at: datetime,
    spend_at_check: float,
    roas_at_check: float | None,
    threshold_crossed: float | None,
    tier_label: str,
    multiplier_applied: float | None,
    budget_before: float | None,
    budget_after: float | None,
    capped_by: str | None,
    meta_api_called: bool,
    meta_api_success: bool | None,
    meta_api_error: str | None,
    raw_meta_response: dict | None,
) -> SurfCheckpoint:
    """INSERT a checkpoint row. Never UPDATE — append only.

    Even no_action ticks call this so the audit trail is dense enough to
    rebuild a timeline. Drives the "Runs Today" UI on /tactics/[id]/surf-intraday.
    """
    cp = SurfCheckpoint(
        id=str(uuid.uuid4()),
        run_id=run.id,
        checked_at=checked_at,
        spend_at_check=spend_at_check,
        roas_at_check=roas_at_check,
        threshold_crossed=threshold_crossed,
        tier_label=tier_label,
        multiplier_applied=multiplier_applied,
        budget_before=budget_before,
        budget_after=budget_after,
        capped_by=capped_by,
        meta_api_called=meta_api_called,
        meta_api_success=meta_api_success,
        meta_api_error=meta_api_error,
        raw_meta_response=raw_meta_response,
        created_at=checked_at,
    )
    db.add(cp)
    db.flush()
    return cp


def update_run_after_action(
    db: Session,
    *,
    run: SurfRun,
    new_current_budget: float,
    increase_amount: float,
    threshold_crossed: float | None,
    roas_at_check: float | None,
    capped_today: bool,
) -> None:
    """Update the run's running state. Called only when a Meta write
    succeeded — failed writes do NOT advance state (so retry on the next
    tick is correct).

    `capped_today` flips the status to 'capped' when surf_limit_per_day has
    been exhausted; the engine then skips subsequent ticks for this run.
    """
    run.current_budget = new_current_budget
    run.total_increase_today = (
        float(run.total_increase_today or 0) + max(increase_amount, 0)
    )
    if threshold_crossed is not None:
        run.last_threshold_hit = threshold_crossed
    if roas_at_check is not None:
        run.last_roas_at_check = roas_at_check
    if capped_today:
        from app.models.surf import SURF_RUN_STATUS_CAPPED
        run.status = SURF_RUN_STATUS_CAPPED
    run.updated_at = datetime.now(timezone.utc)


def mark_run_errored(db: Session, run: SurfRun, error_message: str) -> None:
    """Flip the run to 'errored' so the engine skips it on future ticks
    until an operator inspects. Used for Meta token expired / persistent
    API failures."""
    from app.models.surf import SURF_RUN_STATUS_ERRORED
    run.status = SURF_RUN_STATUS_ERRORED
    run.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def was_noop_at_threshold(latest: SurfCheckpoint | None, threshold: float) -> bool:
    """Idempotency probe: have we already processed THIS threshold?

    Returns True iff the latest checkpoint already acted on this threshold
    (so this tick should write a NO_ACTION marker and return).
    """
    if latest is None:
        return False
    if latest.threshold_crossed is None:
        return False
    return float(latest.threshold_crossed) >= float(threshold)
