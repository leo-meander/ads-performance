"""Action Needed — apply / acknowledge the report's recommended actions.

The /action-needed page surfaces rule-based actions. This router lets the user
EXECUTE the machine-applicable ones on Meta campaigns (pause / budget, reusing
meta_actions with the same Golden-Rule budget guard as the recommendation
applier) or MARK a manual action as done. Either path writes an Activity Log
(ChangeLogEntry) entry; real mutations also write an immutable action_logs row.

Auto-apply is Meta-only for now — Google/TikTok and human tasks (verify
tracking, refresh creative, fix landing) go through /mark-done (log only).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.campaign import Campaign
from app.models.user import User
from app.services import meta_actions
from app.services.changelog import log_change

logger = logging.getLogger(__name__)
router = APIRouter()

# Legacy default factors. Used only when the branch (AdAccount) does not
# override raise_pct/cut_pct. Match the historical hardcodes so any account
# created before migration 042 — or never updated via /budget-limits — keeps
# the exact same behavior: +25% on raise, halve on cut.
LEGACY_RAISE_PCT = 0.25
LEGACY_CUT_PCT = 0.50

AUTO_ACTIONS = {"pause_campaign", "cut_budget", "raise_budget"}


def _resolve_budget_change(
    *,
    current: float,
    action: str,
    raise_pct: float,
    cut_pct: float,
    max_raise_abs: float | None,
    max_cut_abs: float | None,
) -> tuple[float, str | None]:
    """Return (new_budget, applied_cap_reason).

    Applies the per-branch pct, then clamps by the per-branch absolute cap.
    `applied_cap_reason` is None if no cap binding, else a short string for
    audit ('per_click_abs') so the UI can surface "we wanted +NT$80 but cap
    limited it to +NT$50".

    Pre-conditions: `current` > 0 (caller checks). Negative results are
    impossible because cut_pct is bounded (0, 1).
    """
    if action == "raise_budget":
        desired_delta = current * raise_pct
        applied_cap = None
        if max_raise_abs is not None and desired_delta > max_raise_abs:
            desired_delta = max_raise_abs
            applied_cap = "per_click_abs"
        return round(current + desired_delta, 2), applied_cap

    # cut_budget
    desired_delta = current * cut_pct
    applied_cap = None
    if max_cut_abs is not None and desired_delta > max_cut_abs:
        desired_delta = max_cut_abs
        applied_cap = "per_click_abs"
    # Floor at 1 unit native currency — Meta rejects 0 daily_budget.
    return max(round(current - desired_delta, 2), 1.0), applied_cap


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ApplyBody(BaseModel):
    campaign_id: str
    action: str  # pause_campaign | cut_budget | raise_budget
    confirm: bool = False


@router.post("/action-needed/apply")
def apply_action(
    body: ApplyBody,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Execute a machine-applicable action on a Meta campaign, then log it."""
    try:
        if body.action not in AUTO_ACTIONS:
            return _api_response(error=f"Unsupported action: {body.action}")
        if not body.confirm:
            return _api_response(error="confirm must be true to apply")

        camp = db.query(Campaign).filter(Campaign.id == body.campaign_id).first()
        if camp is None:
            return _api_response(error="Campaign not found")
        if (camp.platform or "").lower() != "meta":
            return _api_response(
                error="Auto-apply is available for Meta campaigns only — use 'Mark as done' for this one.",
            )

        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads",
            requested_account_id=camp.account_id, min_level="edit",
        )
        if not ok:
            return _api_response(error=err)

        account = db.query(AdAccount).filter(AdAccount.id == camp.account_id).first()
        if account is None or not account.access_token_enc:
            return _api_response(error="Account has no access token configured")
        access_token = account.access_token_enc

        # Map the UI action onto a meta_actions call.
        action_params: dict[str, Any] = {}
        if body.action == "pause_campaign":
            fn_name = "pause_campaign"

            def _call() -> None:
                meta_actions.pause_campaign(access_token, camp.platform_campaign_id)
        else:
            current = float(camp.daily_budget) if camp.daily_budget is not None else None
            if not current or current <= 0:
                return _api_response(
                    error="No campaign-level daily budget to change (it may be set at ad-set level).",
                )
            # Per-branch overrides on AdAccount (added in migration 042). Falls
            # back to legacy hardcodes so accounts created before then keep
            # identical behavior.
            raise_pct = (
                float(account.raise_pct)
                if account.raise_pct is not None
                else LEGACY_RAISE_PCT
            )
            cut_pct = (
                float(account.cut_pct)
                if account.cut_pct is not None
                else LEGACY_CUT_PCT
            )
            max_raise_abs = (
                float(account.max_raise_per_click_abs)
                if account.max_raise_per_click_abs is not None
                else None
            )
            max_cut_abs = (
                float(account.max_cut_per_click_abs)
                if account.max_cut_per_click_abs is not None
                else None
            )
            new_budget, applied_cap = _resolve_budget_change(
                current=current, action=body.action,
                raise_pct=raise_pct, cut_pct=cut_pct,
                max_raise_abs=max_raise_abs, max_cut_abs=max_cut_abs,
            )
            # No-op guard: cap is so tight the delta rounded to current.
            # Caller should hear about it instead of paying for a Meta call.
            if new_budget == current:
                return _api_response(
                    error=(
                        f"Cap binding too tight: {body.action} would move {current:.0f} "
                        f"by 0 in {account.currency}. Loosen max_*_per_click_abs."
                    ),
                )
            action_params = {
                "from_daily_budget": current,
                "new_daily_budget": new_budget,
                "delta": round(new_budget - current, 2),
                "raise_pct": raise_pct,
                "cut_pct": cut_pct,
                "max_raise_per_click_abs": max_raise_abs,
                "max_cut_per_click_abs": max_cut_abs,
                "applied_cap": applied_cap,
                "currency": account.currency,
            }
            fn_name = "update_campaign_budget"

            def _call() -> None:
                meta_actions.update_campaign_budget(
                    access_token,
                    camp.platform_campaign_id,
                    current_daily_budget=current,
                    new_daily_budget=new_budget,
                )

        success = False
        error_message: str | None = None
        try:
            _call()
            success = True
        except meta_actions.BudgetGuardError as ex:
            error_message = str(ex)
        except Exception as ex:  # noqa: BLE001 — record any platform failure
            error_message = str(ex)
            logger.exception("action-needed apply failed: %s on campaign %s", body.action, camp.id)

        log = ActionLog(
            id=str(uuid.uuid4()),
            campaign_id=camp.id,
            platform="meta",
            action=fn_name,
            action_params={"source": "action_needed", "ui_action": body.action, **action_params},
            triggered_by="manual",
            success=success,
            error_message=error_message,
            executed_at=datetime.now(timezone.utc),
        )
        db.add(log)
        db.flush()

        log_change(
            db,
            category="ad_mutation",
            source="auto",
            triggered_by="manual",
            title=(
                f"Action Needed: {body.action} · {camp.name}"
                if success
                else f"Action Needed failed: {body.action} · {camp.name}"
            )[:200],
            description=(
                f"Applied from the Action Needed page · {fn_name}"
                + (f" · {error_message}" if error_message else "")
            ),
            platform="meta",
            account_id=camp.account_id,
            campaign_id=camp.id,
            after_value={"ui_action": body.action, "function": fn_name, **action_params, "success": success},
            author_user_id=str(current_user.id),
            action_log_id=log.id,
        )
        db.commit()

        if not success:
            return _api_response(error=error_message or "Action failed")
        return _api_response(data={"campaign_id": camp.id, "action": body.action, "params": action_params})
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.exception("apply_action crashed")
        return _api_response(error=str(e))


class MarkDoneBody(BaseModel):
    title: str
    campaign_id: str | None = None
    platform: str | None = None
    note: str = ""


@router.post("/action-needed/mark-done")
def mark_done(
    body: MarkDoneBody,
    current_user: User = Depends(require_section("analytics", "edit")),
    db: Session = Depends(get_db),
):
    """Record that the user handled a manual / non-auto action. Logs to the
    Activity Log only — no platform mutation, no action_logs row."""
    try:
        if not body.title or not body.title.strip():
            return _api_response(error="title is required")

        camp = None
        account_id = None
        if body.campaign_id:
            camp = db.query(Campaign).filter(Campaign.id == body.campaign_id).first()
            if camp is not None:
                account_id = camp.account_id

        log_change(
            db,
            category="other",
            source="manual",
            triggered_by="manual",
            title=f"Action Needed — marked done: {body.title}"[:200],
            description=(body.note.strip() or None) if body.note else None,
            platform=body.platform or (camp.platform if camp else None),
            account_id=account_id,
            campaign_id=body.campaign_id,
            after_value={"manual": True, "marked_done": True},
            author_user_id=str(current_user.id),
        )
        db.commit()
        return _api_response(data={"marked_done": True, "campaign_id": body.campaign_id})
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return _api_response(error=str(e))
