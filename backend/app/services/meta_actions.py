"""Meta Ads API write operations: pause, enable, adjust budget."""

import logging

from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.api import FacebookAdsApi

logger = logging.getLogger(__name__)


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
    """Update a Meta campaign's daily budget (in currency minor units)."""
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
