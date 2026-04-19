"""Google Ads API write operations: pause, enable, adjust budget.

Uses the Google Ads mutate API via the google-ads Python SDK.
Google uses customer_id (not access_token) — credentials from global .env.
"""

import logging

from google.ads.googleads.errors import GoogleAdsException
from google.protobuf.field_mask_pb2 import FieldMask

from app.services.google_client import _get_client

logger = logging.getLogger(__name__)


def _set_update_mask(operation, paths: list[str]) -> None:
    """Populate an Operation's update_mask without going through client.copy_from().

    google-ads Python SDK v23 removed the `FieldMask` alias from `client.get_type()`,
    AND `client.copy_from()` internally calls `get_type("FieldMask")` to coerce
    raw protobuf FieldMask sources. Both paths fail with
    "Specified type 'FieldMask' does not exist in Google Ads API v23".

    Work around by writing to the raw protobuf message directly — `operation._pb`
    exposes the underlying proto, and update_mask is a plain google.protobuf
    FieldMask field we can CopyFrom into.
    """
    operation._pb.update_mask.CopyFrom(FieldMask(paths=list(paths)))


def pause_campaign(customer_id: str, platform_campaign_id: str) -> bool:
    """Set a Google Ads campaign status to PAUSED."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        campaign_service = client.get_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = campaign_service.campaign_path(customer_id, platform_campaign_id)
        campaign.status = client.enums.CampaignStatusEnum.PAUSED
        _set_update_mask(campaign_operation, ["status"])
        campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        logger.info("Paused Google campaign %s", platform_campaign_id)
        return True
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error pausing campaign %s: %s", platform_campaign_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to pause Google campaign %s", platform_campaign_id)
        raise


def enable_campaign(customer_id: str, platform_campaign_id: str) -> bool:
    """Set a Google Ads campaign status to ENABLED."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        campaign_service = client.get_service("CampaignService")
        campaign_operation = client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = campaign_service.campaign_path(customer_id, platform_campaign_id)
        campaign.status = client.enums.CampaignStatusEnum.ENABLED
        _set_update_mask(campaign_operation, ["status"])
        campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        logger.info("Enabled Google campaign %s", platform_campaign_id)
        return True
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error enabling campaign %s: %s", platform_campaign_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to enable Google campaign %s", platform_campaign_id)
        raise


def pause_ad_group(customer_id: str, platform_ad_group_id: str) -> bool:
    """Set a Google Ads ad group status to PAUSED."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        ad_group_service = client.get_service("AdGroupService")
        operation = client.get_type("AdGroupOperation")
        ad_group = operation.update
        ad_group.resource_name = ad_group_service.ad_group_path(customer_id, platform_ad_group_id)
        ad_group.status = client.enums.AdGroupStatusEnum.PAUSED
        _set_update_mask(operation, ["status"])
        ad_group_service.mutate_ad_groups(
            customer_id=customer_id, operations=[operation]
        )
        logger.info("Paused Google ad group %s", platform_ad_group_id)
        return True
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error pausing ad group %s: %s", platform_ad_group_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to pause Google ad group %s", platform_ad_group_id)
        raise


def enable_ad_group(customer_id: str, platform_ad_group_id: str) -> bool:
    """Set a Google Ads ad group status to ENABLED."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        ad_group_service = client.get_service("AdGroupService")
        operation = client.get_type("AdGroupOperation")
        ad_group = operation.update
        ad_group.resource_name = ad_group_service.ad_group_path(customer_id, platform_ad_group_id)
        ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
        _set_update_mask(operation, ["status"])
        ad_group_service.mutate_ad_groups(
            customer_id=customer_id, operations=[operation]
        )
        logger.info("Enabled Google ad group %s", platform_ad_group_id)
        return True
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error enabling ad group %s: %s", platform_ad_group_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to enable Google ad group %s", platform_ad_group_id)
        raise


def pause_ad(customer_id: str, platform_ad_group_id: str, platform_ad_id: str) -> bool:
    """Set a Google Ads ad (ad_group_ad) status to PAUSED."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        ad_group_ad_service = client.get_service("AdGroupAdService")
        operation = client.get_type("AdGroupAdOperation")
        ad_group_ad = operation.update
        ad_group_ad.resource_name = ad_group_ad_service.ad_group_ad_path(
            customer_id, platform_ad_group_id, platform_ad_id
        )
        ad_group_ad.status = client.enums.AdGroupAdStatusEnum.PAUSED
        _set_update_mask(operation, ["status"])
        ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id, operations=[operation]
        )
        logger.info("Paused Google ad %s", platform_ad_id)
        return True
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error pausing ad %s: %s", platform_ad_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to pause Google ad %s", platform_ad_id)
        raise


def enable_ad(customer_id: str, platform_ad_group_id: str, platform_ad_id: str) -> bool:
    """Set a Google Ads ad (ad_group_ad) status to ENABLED."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        ad_group_ad_service = client.get_service("AdGroupAdService")
        operation = client.get_type("AdGroupAdOperation")
        ad_group_ad = operation.update
        ad_group_ad.resource_name = ad_group_ad_service.ad_group_ad_path(
            customer_id, platform_ad_group_id, platform_ad_id
        )
        ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
        _set_update_mask(operation, ["status"])
        ad_group_ad_service.mutate_ad_group_ads(
            customer_id=customer_id, operations=[operation]
        )
        logger.info("Enabled Google ad %s", platform_ad_id)
        return True
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error enabling ad %s: %s", platform_ad_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to enable Google ad %s", platform_ad_id)
        raise


def update_campaign_budget(
    customer_id: str, platform_campaign_id: str, new_budget_micros: int
) -> bool:
    """Update a Google Ads campaign's daily budget (in micros: 1,000,000 = 1 unit)."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        # First, get the campaign's budget resource name
        ga_service = client.get_service("GoogleAdsService")
        query = f"""
            SELECT campaign.campaign_budget
            FROM campaign
            WHERE campaign.id = {platform_campaign_id}
        """
        stream = ga_service.search_stream(customer_id=customer_id, query=query)
        budget_resource = None
        for batch in stream:
            for row in batch.results:
                budget_resource = row.campaign.campaign_budget
                break
            break

        if not budget_resource:
            raise ValueError(f"Budget not found for campaign {platform_campaign_id}")

        # Mutate the budget
        budget_service = client.get_service("CampaignBudgetService")
        operation = client.get_type("CampaignBudgetOperation")
        budget = operation.update
        budget.resource_name = budget_resource
        budget.amount_micros = new_budget_micros
        _set_update_mask(operation, ["amount_micros"])
        budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[operation]
        )
        logger.info(
            "Updated budget for Google campaign %s to %d micros",
            platform_campaign_id, new_budget_micros,
        )
        return True
    except GoogleAdsException as ex:
        logger.exception(
            "Google Ads API error updating budget for campaign %s: %s",
            platform_campaign_id, ex.failure,
        )
        raise
    except Exception:
        logger.exception("Failed to update budget for Google campaign %s", platform_campaign_id)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Power Pack recommendation actions
# These back `/google/recommendations/{id}/apply`. Any function added here
# must be listed in applier.ACTION_DISPATCH.
# ─────────────────────────────────────────────────────────────────────────────


def update_tcpa_target(
    customer_id: str, platform_campaign_id: str, new_tcpa_micros: int,
) -> bool:
    """Update Target CPA on a campaign's bidding strategy (micros).

    Used by PMAX_LEARNING_STUCK and SEASONALITY_TCPA_ADJUST_DUE. The campaign
    must already be on a TargetCpa or MaximizeConversions-with-tCPA strategy.
    """
    customer_id = customer_id.replace("-", "")
    client = _get_client()
    try:
        campaign_service = client.get_service("CampaignService")
        operation = client.get_type("CampaignOperation")
        campaign = operation.update
        campaign.resource_name = campaign_service.campaign_path(
            customer_id, platform_campaign_id,
        )
        campaign.maximize_conversions.target_cpa_micros = int(new_tcpa_micros)
        _set_update_mask(operation, ["maximize_conversions.target_cpa_micros"])
        campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[operation],
        )
        logger.info(
            "Updated tCPA for Google campaign %s to %d micros",
            platform_campaign_id, new_tcpa_micros,
        )
        return True
    except GoogleAdsException as ex:
        logger.exception(
            "Google Ads API error updating tCPA for campaign %s: %s",
            platform_campaign_id, ex.failure,
        )
        raise


# ── Stubs for actions not yet fully implemented in the Google Ads SDK layer ──
# Each raises NotImplementedError with a message that the recommendation
# applier surfaces as a 409 Conflict with actionable guidance for manual work.

class ManualActionRequired(RuntimeError):
    """Raised by stubs to signal that the operation must be done in Google Ads UI."""


def _manual_only(name: str, guidance: str) -> None:
    raise ManualActionRequired(
        f"{name} must be applied manually in Google Ads UI. {guidance}",
    )


def switch_bid_strategy(customer_id: str, platform_campaign_id: str, **kwargs) -> bool:
    _manual_only(
        "switch_bid_strategy",
        "Open the campaign → Settings → Bidding, and switch to the recommended strategy.",
    )
    return False  # unreachable


def add_negative_keywords(customer_id: str, shared_set_id: str, keywords: list[str]) -> bool:
    _manual_only(
        "add_negative_keywords",
        "Open Shared Library → Negative keyword lists, and add the listed keywords.",
    )
    return False


def pin_rsa_headline(customer_id: str, platform_ad_id: str, headline_text: str) -> bool:
    _manual_only(
        "pin_rsa_headline",
        "Open the RSA → Edit → Pin the brand headline to position 1.",
    )
    return False


def disable_final_url_expansion(customer_id: str, platform_campaign_id: str) -> bool:
    _manual_only(
        "disable_final_url_expansion",
        "Open the campaign → Settings → AI Max, and turn off Final URL Expansion.",
    )
    return False


def disable_aimax(customer_id: str, platform_campaign_id: str) -> bool:
    _manual_only(
        "disable_aimax",
        "Open the campaign → Settings → AI Max, and disable the feature entirely.",
    )
    return False


def disable_optimized_targeting(customer_id: str, platform_campaign_id: str) -> bool:
    _manual_only(
        "disable_optimized_targeting",
        "Open the campaign → Audiences, and turn off Optimized Targeting.",
    )
    return False


def cap_campaign_frequency(
    customer_id: str, platform_campaign_id: str, max_per_week: int,
) -> bool:
    _manual_only(
        "cap_campaign_frequency",
        "Open the campaign → Settings → Frequency, and set the weekly cap.",
    )
    return False


def rebalance_budget_mix(
    customer_id: str, campaign_budget_plan: list[dict],
) -> bool:
    """Apply a computed budget plan across campaigns in one account.

    Plan format: [{"platform_campaign_id": str, "new_budget_micros": int}, ...].
    Calls update_campaign_budget per entry; any failure aborts the rest.
    """
    for entry in campaign_budget_plan:
        update_campaign_budget(
            customer_id,
            entry["platform_campaign_id"],
            int(entry["new_budget_micros"]),
        )
    return True
