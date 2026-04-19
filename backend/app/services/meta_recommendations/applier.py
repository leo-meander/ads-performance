"""Applier: dispatches a recommendation's suggested_action to meta_actions.

Always writes an immutable action_logs row recording the attempt (success or
failure). On success, the recommendation row is marked 'applied' with the
action_log_id link. Budget updates run behind the Golden Rule #4 25% cap
enforced in meta_actions.update_campaign_budget / update_ad_set_budget.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.meta_recommendation import MetaRecommendation
from app.services import meta_actions

logger = logging.getLogger(__name__)


class ApplyError(RuntimeError):
    """Base error for applier failures."""


class ConfirmationRequired(ApplyError):
    """Caller did not pass confirm_warning=True."""


class NotAutoApplicable(ApplyError):
    """Recommendation is guidance-only (auto_applicable=False)."""


class NotApplicable(ApplyError):
    """Recommendation is no longer in a state that can be applied."""


# Dispatch table — rec.suggested_action.function -> meta_actions function.
ACTION_DISPATCH: dict[str, Any] = {
    "pause_campaign": meta_actions.pause_campaign,
    "enable_campaign": meta_actions.enable_campaign,
    "pause_ad_set": meta_actions.pause_ad_set,
    "enable_ad_set": meta_actions.enable_ad_set,
    "pause_ad": meta_actions.pause_ad,
    "enable_ad": meta_actions.enable_ad,
    "update_campaign_budget": meta_actions.update_campaign_budget,
    "update_ad_set_budget": meta_actions.update_ad_set_budget,
}


def apply_recommendation(
    db: Session,
    recommendation_id: str,
    *,
    confirm_warning: bool,
    applied_by_user_id: str | None,
    override_params: dict[str, Any] | None = None,
) -> MetaRecommendation:
    rec = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.id == recommendation_id)
        .first()
    )
    if rec is None:
        raise NotApplicable(f"Recommendation {recommendation_id} not found")
    if rec.status != "pending":
        raise NotApplicable(f"Recommendation status={rec.status}, cannot apply")
    if not confirm_warning:
        raise ConfirmationRequired("confirm_warning must be true to apply")
    if not rec.auto_applicable:
        raise NotAutoApplicable(
            f"rec_type={rec.rec_type} is guidance-only; follow the warning text manually",
        )

    function_name = (rec.suggested_action or {}).get("function")
    kwargs = dict((rec.suggested_action or {}).get("kwargs") or {})
    if override_params:
        kwargs.update(override_params)
    if function_name not in ACTION_DISPATCH:
        raise NotApplicable(
            f"Unknown or unsupported action function: {function_name!r}",
        )

    account = db.query(AdAccount).filter(AdAccount.id == rec.account_id).first()
    if account is None:
        raise NotApplicable(f"Account {rec.account_id} not found")
    access_token = account.access_token_enc
    if not access_token:
        raise NotApplicable(
            f"Account {account.account_name} has no access token configured",
        )

    call_kwargs = _resolve_kwargs(db, rec, function_name, kwargs, access_token)
    fn = ACTION_DISPATCH[function_name]

    success = False
    error_message: str | None = None
    try:
        fn(**call_kwargs)
        success = True
    except meta_actions.BudgetGuardError as ex:
        error_message = str(ex)
        logger.warning(
            "apply_meta_recommendation: budget guard rejected %s (rec=%s): %s",
            function_name, rec.id, ex,
        )
    except Exception as ex:
        error_message = str(ex)
        logger.exception(
            "apply_meta_recommendation: %s failed (rec=%s)", function_name, rec.id,
        )

    log = ActionLog(
        id=str(uuid.uuid4()),
        campaign_id=rec.campaign_id,
        ad_set_id=rec.ad_set_id,
        ad_id=rec.ad_id,
        platform="meta",
        action=function_name,
        action_params={
            "recommendation_id": rec.id,
            "rec_type": rec.rec_type,
            **{k: v for k, v in kwargs.items() if k != "access_token"},
        },
        triggered_by="recommendation",
        metrics_snapshot=rec.metrics_snapshot,
        success=success,
        error_message=error_message,
        executed_at=datetime.now(timezone.utc),
    )
    db.add(log)
    db.flush()

    if success:
        rec.status = "applied"
        rec.applied_at = datetime.now(timezone.utc)
        rec.applied_by = applied_by_user_id
        rec.action_log_id = log.id
    else:
        rec.status = "failed"
        rec.action_log_id = log.id
    db.commit()
    return rec


def _resolve_kwargs(
    db: Session,
    rec: MetaRecommendation,
    function_name: str,
    kwargs: dict[str, Any],
    access_token: str,
) -> dict[str, Any]:
    """Translate internal UUIDs into Meta platform IDs for the action call."""
    out: dict[str, Any] = {"access_token": access_token}

    if function_name in ("pause_campaign", "enable_campaign"):
        out["platform_campaign_id"] = _campaign_platform_id(db, rec.campaign_id)
    elif function_name in ("pause_ad_set", "enable_ad_set"):
        out["platform_adset_id"] = _ad_set_platform_id(db, rec.ad_set_id)
    elif function_name in ("pause_ad", "enable_ad"):
        out["platform_ad_id"] = _ad_platform_id(db, rec.ad_id)
    elif function_name == "update_campaign_budget":
        camp = _campaign(db, rec.campaign_id)
        out["platform_campaign_id"] = camp.platform_campaign_id
        out["current_daily_budget"] = (
            float(camp.daily_budget) if camp.daily_budget is not None else None
        )
        if "new_daily_budget" in kwargs:
            out["new_daily_budget"] = float(kwargs["new_daily_budget"])
        if "new_lifetime_budget" in kwargs:
            out["new_lifetime_budget"] = float(kwargs["new_lifetime_budget"])
        out["force"] = bool(kwargs.get("force", False))
    elif function_name == "update_ad_set_budget":
        ad_set = _ad_set(db, rec.ad_set_id)
        out["platform_adset_id"] = ad_set.platform_adset_id
        out["current_daily_budget"] = (
            float(ad_set.daily_budget) if ad_set.daily_budget is not None else None
        )
        if "new_daily_budget" in kwargs:
            out["new_daily_budget"] = float(kwargs["new_daily_budget"])
        if "new_lifetime_budget" in kwargs:
            out["new_lifetime_budget"] = float(kwargs["new_lifetime_budget"])
        out["force"] = bool(kwargs.get("force", False))
    return out


def _campaign(db: Session, campaign_id: str | None) -> Campaign:
    if not campaign_id:
        raise NotApplicable("Recommendation is missing campaign_id")
    camp = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if camp is None:
        raise NotApplicable(f"Campaign {campaign_id} not found")
    return camp


def _ad_set(db: Session, ad_set_id: str | None) -> AdSet:
    if not ad_set_id:
        raise NotApplicable("Recommendation is missing ad_set_id")
    row = db.query(AdSet).filter(AdSet.id == ad_set_id).first()
    if row is None:
        raise NotApplicable(f"AdSet {ad_set_id} not found")
    return row


def _campaign_platform_id(db: Session, campaign_id: str | None) -> str:
    return _campaign(db, campaign_id).platform_campaign_id


def _ad_set_platform_id(db: Session, ad_set_id: str | None) -> str:
    return _ad_set(db, ad_set_id).platform_adset_id


def _ad_platform_id(db: Session, ad_id: str | None) -> str:
    if not ad_id:
        raise NotApplicable("Recommendation is missing ad_id")
    row = db.query(Ad).filter(Ad.id == ad_id).first()
    if row is None:
        raise NotApplicable(f"Ad {ad_id} not found")
    return row.platform_ad_id


def dismiss_recommendation(
    db: Session,
    recommendation_id: str,
    *,
    reason: str,
    dismissed_by_user_id: str | None,
) -> MetaRecommendation:
    rec = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.id == recommendation_id)
        .first()
    )
    if rec is None:
        raise NotApplicable(f"Recommendation {recommendation_id} not found")
    if rec.status != "pending":
        raise NotApplicable(f"Recommendation status={rec.status}, cannot dismiss")
    rec.status = "dismissed"
    rec.dismissed_at = datetime.now(timezone.utc)
    rec.dismissed_by = dismissed_by_user_id
    rec.dismiss_reason = (reason or "").strip() or None
    db.commit()
    return rec
