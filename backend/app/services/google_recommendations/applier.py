"""Applier: dispatches a recommendation's suggested_action to google_actions.

Always writes an immutable action_logs row recording the attempt (success or
failure). On success, the recommendation row is marked 'applied' with the
action_log_id link. On `ManualActionRequired`, the recommendation stays
pending and the caller receives a 409 with the guidance message.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.campaign import Campaign
from app.models.google_recommendation import GoogleRecommendation
from app.services import google_actions
from app.services.changelog import log_change

logger = logging.getLogger(__name__)


class ApplyError(RuntimeError):
    """Base error for applier failures."""


class ConfirmationRequired(ApplyError):
    """Caller did not pass confirm_warning=True."""


class NotAutoApplicable(ApplyError):
    """Recommendation is guidance-only (auto_applicable=False)."""


class NotApplicable(ApplyError):
    """Recommendation is no longer in a state that can be applied."""


# Dispatch table — rec suggested_action.function → google_actions function.
# Functions returning normally on success. Functions raising
# ManualActionRequired bubble up; the router maps that to 409.
ACTION_DISPATCH: dict[str, Any] = {
    "pause_campaign": google_actions.pause_campaign,
    "enable_campaign": google_actions.enable_campaign,
    "pause_ad_group": google_actions.pause_ad_group,
    "enable_ad_group": google_actions.enable_ad_group,
    "pause_ad": google_actions.pause_ad,
    "enable_ad": google_actions.enable_ad,
    "update_campaign_budget": google_actions.update_campaign_budget,
    "update_tcpa_target": google_actions.update_tcpa_target,
    "switch_bid_strategy": google_actions.switch_bid_strategy,
    "add_negative_keywords": google_actions.add_negative_keywords,
    "pin_rsa_headline": google_actions.pin_rsa_headline,
    "disable_final_url_expansion": google_actions.disable_final_url_expansion,
    "disable_aimax": google_actions.disable_aimax,
    "disable_optimized_targeting": google_actions.disable_optimized_targeting,
    "cap_campaign_frequency": google_actions.cap_campaign_frequency,
    "rebalance_budget_mix": google_actions.rebalance_budget_mix,
}


def apply_recommendation(
    db: Session,
    recommendation_id: str,
    *,
    confirm_warning: bool,
    applied_by_user_id: str | None,
    override_params: dict[str, Any] | None = None,
) -> GoogleRecommendation:
    rec = (
        db.query(GoogleRecommendation)
        .filter(GoogleRecommendation.id == recommendation_id)
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

    # Resolve Google customer_id + platform ids from the recommendation's FKs.
    account = (
        db.query(AdAccount).filter(AdAccount.id == rec.account_id).first()
    )
    if account is None:
        raise NotApplicable(f"Account {rec.account_id} not found")
    customer_id = account.account_id

    call_kwargs = _resolve_kwargs(db, rec, function_name, kwargs, customer_id)
    fn = ACTION_DISPATCH[function_name]

    success = False
    error_message: str | None = None
    try:
        fn(**call_kwargs)
        success = True
    except google_actions.ManualActionRequired as ex:
        # Bubble up — router maps this to 409 Conflict with the guidance message.
        raise
    except Exception as ex:
        error_message = str(ex)
        logger.exception(
            "apply_recommendation: %s failed (rec=%s)", function_name, rec.id,
        )

    log = ActionLog(
        id=str(uuid.uuid4()),
        campaign_id=rec.campaign_id,
        ad_set_id=rec.ad_group_id,
        ad_id=rec.ad_id,
        platform="google",
        action=function_name,
        action_params={
            "recommendation_id": rec.id,
            "rec_type": rec.rec_type,
            **kwargs,
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

    log_change(
        db,
        category="recommendation_applied",
        source="auto",
        triggered_by="recommendation",
        title=(
            f"Recommendation applied: {rec.title}"
            if success
            else f"Recommendation failed: {rec.title}"
        ),
        description=(
            f"{rec.rec_type} · {function_name}"
            + (f" · {error_message}" if error_message else "")
        ),
        platform="google",
        account_id=rec.account_id,
        campaign_id=rec.campaign_id,
        ad_set_id=rec.ad_group_id,
        ad_id=rec.ad_id,
        after_value={
            "rec_type": rec.rec_type,
            "function": function_name,
            "kwargs": kwargs,
            "success": success,
        },
        metrics_snapshot=rec.metrics_snapshot,
        author_user_id=applied_by_user_id,
        action_log_id=log.id,
    )
    db.commit()
    return rec


def _resolve_kwargs(
    db: Session,
    rec: GoogleRecommendation,
    function_name: str,
    kwargs: dict[str, Any],
    customer_id: str,
) -> dict[str, Any]:
    """Translate internal ids (campaign_id, etc.) into Google platform ids.

    The detector stores our internal UUIDs in suggested_action.kwargs so the
    applier stays decoupled from the Google API. We join to the DB here and
    build the final keyword dict that the google_actions function expects.
    """
    out: dict[str, Any] = {"customer_id": customer_id}
    campaign_id = kwargs.get("campaign_id")
    if campaign_id:
        camp = (
            db.query(Campaign).filter(Campaign.id == campaign_id).first()
        )
        if camp is None:
            raise NotApplicable(f"Campaign {campaign_id} not found")
        out["platform_campaign_id"] = camp.platform_campaign_id

    if function_name == "update_campaign_budget":
        new_daily = kwargs.get("new_daily_budget")
        if new_daily is None:
            raise NotApplicable("update_campaign_budget requires new_daily_budget")
        out["new_budget_micros"] = int(float(new_daily) * 1_000_000)
    elif function_name == "update_tcpa_target":
        micros = kwargs.get("new_tcpa_micros")
        if micros is None:
            new_tcpa = kwargs.get("new_tcpa")
            if new_tcpa is None:
                raise NotApplicable("update_tcpa_target requires new_tcpa_micros or new_tcpa")
            micros = int(float(new_tcpa) * 1_000_000)
        out["new_tcpa_micros"] = int(micros)
    elif function_name == "rebalance_budget_mix":
        # Build per-campaign plan from the stored action_kwargs.
        plan = _build_budget_rebalance_plan(db, rec, kwargs)
        out["campaign_budget_plan"] = plan
    elif function_name == "switch_bid_strategy":
        out["new_strategy"] = kwargs.get("new_strategy")
        if kwargs.get("target_cpa_micros") is not None:
            out["target_cpa_micros"] = int(kwargs["target_cpa_micros"])
        elif kwargs.get("target_cpa") is not None:
            out["target_cpa_micros"] = int(float(kwargs["target_cpa"]) * 1_000_000)
        if kwargs.get("target_roas") is not None:
            out["target_roas"] = float(kwargs["target_roas"])
    elif function_name in (
        "disable_final_url_expansion", "disable_aimax",
        "disable_optimized_targeting",
    ):
        # No extra args needed beyond platform_campaign_id.
        pass
    elif function_name == "cap_campaign_frequency":
        out["max_per_week"] = int(kwargs.get("max_per_week", 7))
    elif function_name == "pin_rsa_headline":
        out["platform_ad_id"] = kwargs.get("platform_ad_id") or ""
        out["headline_text"] = kwargs.get("headline_text") or ""
    elif function_name == "add_negative_keywords":
        out["shared_set_id"] = kwargs.get("shared_set_id") or ""
        out["keywords"] = kwargs.get("keywords") or []

    return out


def _build_budget_rebalance_plan(
    db: Session,
    rec: GoogleRecommendation,
    kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute a new daily_budget per campaign to realize the target mix.

    Keeps the total 30-day spend constant; scales each campaign's current
    daily budget by the ratio between target mid % and current actual %.
    """
    target_mid = kwargs.get("target_mid_pct") or {}
    # The detector persisted the per-bucket breakdown in detector_finding.
    finding = rec.detector_finding or {}
    campaigns_by_bucket = finding.get("campaigns_by_bucket") or {}
    current_pct = finding.get("current_mix_pct") or {}

    plan: list[dict[str, Any]] = []
    for bucket, camps in campaigns_by_bucket.items():
        target = float(target_mid.get(bucket) or 0)
        current = float(current_pct.get(bucket) or 0)
        if current <= 0:
            continue
        scale = target / current
        for c in camps:
            camp = (
                db.query(Campaign).filter(Campaign.id == c["campaign_id"]).first()
            )
            if camp is None or not camp.daily_budget:
                continue
            new_daily = float(camp.daily_budget) * scale
            plan.append({
                "platform_campaign_id": camp.platform_campaign_id,
                "new_budget_micros": int(new_daily * 1_000_000),
            })
    return plan


def dismiss_recommendation(
    db: Session, recommendation_id: str, *, reason: str, dismissed_by_user_id: str | None,
) -> GoogleRecommendation:
    rec = (
        db.query(GoogleRecommendation)
        .filter(GoogleRecommendation.id == recommendation_id)
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
