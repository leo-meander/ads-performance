"""Meta Ads API write operations: pause, enable, adjust budget."""

import logging

from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.api import FacebookAdsApi

logger = logging.getLogger(__name__)

# Safety cap on the apply path: reject single-step daily budget increases
# above 25% unless the caller explicitly passes force=True.
MAX_DAILY_BUDGET_INCREASE_PCT = 0.25


class BudgetGuardError(RuntimeError):
    """Raised when a budget adjust would violate the 25% daily cap."""


def _init_api(access_token: str):
    FacebookAdsApi.init(app_id="", app_secret="", access_token=access_token)


def pause_campaign(access_token: str, platform_campaign_id: str) -> bool:
    """Set a Meta campaign status to PAUSED."""
    _init_api(access_token)
    try:
        campaign = Campaign(platform_campaign_id)
        campaign[Campaign.Field.status] = Campaign.Status.paused
        campaign.remote_update()
        logger.info("Paused Meta campaign %s", platform_campaign_id)
        return True
    except Exception:
        logger.exception("Failed to pause Meta campaign %s", platform_campaign_id)
        raise


def enable_campaign(access_token: str, platform_campaign_id: str) -> bool:
    """Set a Meta campaign status to ACTIVE."""
    _init_api(access_token)
    try:
        campaign = Campaign(platform_campaign_id)
        campaign[Campaign.Field.status] = Campaign.Status.active
        campaign.remote_update()
        logger.info("Enabled Meta campaign %s", platform_campaign_id)
        return True
    except Exception:
        logger.exception("Failed to enable Meta campaign %s", platform_campaign_id)
        raise


def pause_ad_set(access_token: str, platform_adset_id: str) -> bool:
    """Set a Meta ad set status to PAUSED."""
    _init_api(access_token)
    try:
        adset = AdSet(platform_adset_id)
        adset[AdSet.Field.status] = AdSet.Status.paused
        adset.remote_update()
        logger.info("Paused Meta ad set %s", platform_adset_id)
        return True
    except Exception:
        logger.exception("Failed to pause Meta ad set %s", platform_adset_id)
        raise


def enable_ad_set(access_token: str, platform_adset_id: str) -> bool:
    """Set a Meta ad set status to ACTIVE."""
    _init_api(access_token)
    try:
        adset = AdSet(platform_adset_id)
        adset[AdSet.Field.status] = AdSet.Status.active
        adset.remote_update()
        logger.info("Enabled Meta ad set %s", platform_adset_id)
        return True
    except Exception:
        logger.exception("Failed to enable Meta ad set %s", platform_adset_id)
        raise


def pause_ad(access_token: str, platform_ad_id: str) -> bool:
    """Set a Meta ad status to PAUSED."""
    _init_api(access_token)
    try:
        ad = Ad(platform_ad_id)
        ad[Ad.Field.status] = "PAUSED"
        ad.remote_update()
        logger.info("Paused Meta ad %s", platform_ad_id)
        return True
    except Exception:
        logger.exception("Failed to pause Meta ad %s", platform_ad_id)
        raise


def enable_ad(access_token: str, platform_ad_id: str) -> bool:
    """Set a Meta ad status to ACTIVE."""
    _init_api(access_token)
    try:
        ad = Ad(platform_ad_id)
        ad[Ad.Field.status] = "ACTIVE"
        ad.remote_update()
        logger.info("Enabled Meta ad %s", platform_ad_id)
        return True
    except Exception:
        logger.exception("Failed to enable Meta ad %s", platform_ad_id)
        raise


def update_budget(access_token: str, platform_campaign_id: str, new_daily_budget: int) -> bool:
    """Update a Meta campaign's daily budget (in currency minor units).

    Legacy helper kept for backwards compatibility with older callers. New
    code should use `update_campaign_budget` which enforces the 25% cap.
    """
    _init_api(access_token)
    try:
        campaign = Campaign(platform_campaign_id)
        campaign[Campaign.Field.daily_budget] = new_daily_budget
        campaign.remote_update()
        logger.info("Updated budget for Meta campaign %s to %d", platform_campaign_id, new_daily_budget)
        return True
    except Exception:
        logger.exception("Failed to update budget for Meta campaign %s", platform_campaign_id)
        raise


def _guard_increase(current: float | None, new_value: float, *, force: bool) -> None:
    """Reject single-step daily budget increases above 25%.

    Decreases and force=True bypass the guard.
    """
    if force or current is None or current <= 0 or new_value <= current:
        return
    max_allowed = float(current) * (1 + MAX_DAILY_BUDGET_INCREASE_PCT)
    if new_value > max_allowed:
        raise BudgetGuardError(
            f"Budget increase {current:.0f} -> {new_value:.0f} exceeds the "
            f"{int(MAX_DAILY_BUDGET_INCREASE_PCT * 100)}% daily cap "
            f"(max allowed: {max_allowed:.0f}). Pass force=True to override, "
            f"or split the raise across multiple days.",
        )


def update_campaign_budget(
    access_token: str,
    platform_campaign_id: str,
    *,
    current_daily_budget: float | None = None,
    new_daily_budget: float | None = None,
    new_lifetime_budget: float | None = None,
    force: bool = False,
) -> bool:
    """Update a Meta campaign's daily or lifetime budget with Golden Rule #4 guard.

    Budgets are sent to Meta in currency minor units (e.g. VND cents) as ints.
    Callers pass either new_daily_budget or new_lifetime_budget in the account
    currency's major units and this helper converts.
    """
    if new_daily_budget is None and new_lifetime_budget is None:
        raise ValueError("Either new_daily_budget or new_lifetime_budget must be provided")
    if new_daily_budget is not None:
        _guard_increase(current_daily_budget, float(new_daily_budget), force=force)

    _init_api(access_token)
    try:
        campaign = Campaign(platform_campaign_id)
        if new_daily_budget is not None:
            campaign[Campaign.Field.daily_budget] = int(round(float(new_daily_budget) * 100))
        if new_lifetime_budget is not None:
            campaign[Campaign.Field.lifetime_budget] = int(round(float(new_lifetime_budget) * 100))
        campaign.remote_update()
        logger.info(
            "Updated budget for Meta campaign %s: daily=%s lifetime=%s force=%s",
            platform_campaign_id, new_daily_budget, new_lifetime_budget, force,
        )
        return True
    except Exception:
        logger.exception("Failed to update budget for Meta campaign %s", platform_campaign_id)
        raise


def update_ad_set_budget(
    access_token: str,
    platform_adset_id: str,
    *,
    current_daily_budget: float | None = None,
    new_daily_budget: float | None = None,
    new_lifetime_budget: float | None = None,
    force: bool = False,
) -> bool:
    """Update a Meta ad set's daily or lifetime budget with Golden Rule #4 guard."""
    if new_daily_budget is None and new_lifetime_budget is None:
        raise ValueError("Either new_daily_budget or new_lifetime_budget must be provided")
    if new_daily_budget is not None:
        _guard_increase(current_daily_budget, float(new_daily_budget), force=force)

    _init_api(access_token)
    try:
        adset = AdSet(platform_adset_id)
        if new_daily_budget is not None:
            adset[AdSet.Field.daily_budget] = int(round(float(new_daily_budget) * 100))
        if new_lifetime_budget is not None:
            adset[AdSet.Field.lifetime_budget] = int(round(float(new_lifetime_budget) * 100))
        adset.remote_update()
        logger.info(
            "Updated budget for Meta ad set %s: daily=%s lifetime=%s force=%s",
            platform_adset_id, new_daily_budget, new_lifetime_budget, force,
        )
        return True
    except Exception:
        logger.exception("Failed to update budget for Meta ad set %s", platform_adset_id)
        raise
