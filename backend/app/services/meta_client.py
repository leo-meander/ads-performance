"""Meta (Facebook) Ads API client.

Fetches campaigns and their insights from the Meta Marketing API.
Uses the facebook-business SDK. Each account uses its own access token.
"""

import logging
from datetime import date, datetime, timedelta

from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.api import FacebookAdsApi

logger = logging.getLogger(__name__)

# Fields to fetch for campaigns
CAMPAIGN_FIELDS = [
    Campaign.Field.id,
    Campaign.Field.name,
    Campaign.Field.status,
    Campaign.Field.objective,
    Campaign.Field.daily_budget,
    Campaign.Field.lifetime_budget,
    Campaign.Field.start_time,
    Campaign.Field.stop_time,
]

# Fields to fetch for ad sets
ADSET_FIELDS = [
    AdSet.Field.id,
    AdSet.Field.campaign_id,
    AdSet.Field.name,
    AdSet.Field.status,
    AdSet.Field.optimization_goal,
    AdSet.Field.billing_event,
    AdSet.Field.daily_budget,
    AdSet.Field.lifetime_budget,
    AdSet.Field.targeting,
    AdSet.Field.start_time,
    AdSet.Field.end_time,
]

# Fields to fetch for ads
AD_FIELDS = [
    Ad.Field.id,
    Ad.Field.adset_id,
    Ad.Field.campaign_id,
    Ad.Field.name,
    Ad.Field.status,
    Ad.Field.creative,
]

# Insight fields for metrics
INSIGHT_FIELDS = [
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "conversions",
    "purchase_roas",
    "cost_per_action_type",
    "cpc",
    "frequency",
    "actions",
    "action_values",
]


def _parse_date(value) -> date | None:
    """Parse Meta's datetime string to a date object."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def _init_api(access_token: str):
    """Initialize the Facebook Ads API with a per-account access token."""
    FacebookAdsApi.init(
        app_id="",
        app_secret="",
        access_token=access_token,
    )


def fetch_campaigns(account_id: str, access_token: str) -> list[dict]:
    """Fetch all campaigns for a given ad account.

    Args:
        account_id: Meta ad account ID (format: act_XXXXX)
        access_token: Per-account Meta access token

    Returns:
        List of campaign dicts with fields from CAMPAIGN_FIELDS.
    """
    _init_api(access_token)
    try:
        account = AdAccount(account_id)
        campaigns = account.get_campaigns(fields=CAMPAIGN_FIELDS)
        results = []
        for c in campaigns:
            results.append({
                "platform_campaign_id": c[Campaign.Field.id],
                "name": c[Campaign.Field.name],
                "status": c[Campaign.Field.status],
                "objective": c.get(Campaign.Field.objective, ""),
                "daily_budget": c.get(Campaign.Field.daily_budget),
                "lifetime_budget": c.get(Campaign.Field.lifetime_budget),
                "start_date": _parse_date(c.get(Campaign.Field.start_time)),
                "end_date": _parse_date(c.get(Campaign.Field.stop_time)),
                "raw_data": dict(c),
            })
        logger.info("Fetched %d campaigns from Meta account %s", len(results), account_id)
        return results
    except Exception:
        logger.exception("Failed to fetch campaigns from Meta account %s", account_id)
        raise


def fetch_campaign_insights(
    account_id: str,
    access_token: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily insights (metrics) for all campaigns in an account.

    Args:
        account_id: Meta ad account ID (format: act_XXXXX)
        access_token: Per-account Meta access token
        date_from: Start date for insights. Defaults to 7 days ago.
        date_to: End date for insights. Defaults to today.

    Returns:
        List of insight dicts keyed by campaign_id + date.
    """
    _init_api(access_token)

    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    try:
        account = AdAccount(account_id)
        insights = account.get_insights(
            fields=INSIGHT_FIELDS,
            params={
                "level": "campaign",
                "time_range": {
                    "since": date_from.isoformat(),
                    "until": date_to.isoformat(),
                },
                "time_increment": 1,  # daily breakdown
            },
        )

        # Action types to extract from Meta's actions array
        PURCHASE_TYPES = {"purchase", "offsite_conversion.fb_pixel_purchase"}
        ADD_TO_CART_TYPES = {"add_to_cart", "offsite_conversion.fb_pixel_add_to_cart"}
        CHECKOUT_TYPES = {"initiate_checkout", "offsite_conversion.fb_pixel_initiate_checkout"}
        SEARCH_TYPES = {"search", "offsite_conversion.fb_pixel_search"}
        LEAD_TYPES = {"lead", "offsite_conversion.fb_pixel_lead"}
        LANDING_PAGE_TYPES = {"landing_page_view"}

        results = []
        for row in insights:
            actions = row.get("actions") or []
            action_values = row.get("action_values") or []

            # Count actions by type
            conversions = 0
            add_to_cart = 0
            checkouts = 0
            searches = 0
            leads = 0
            landing_page_views = 0
            revenue = 0.0

            for action in actions:
                atype = action.get("action_type", "")
                val = int(action.get("value", 0))
                if atype in PURCHASE_TYPES:
                    conversions += val
                elif atype in ADD_TO_CART_TYPES:
                    add_to_cart += val
                elif atype in CHECKOUT_TYPES:
                    checkouts += val
                elif atype in SEARCH_TYPES:
                    searches += val
                elif atype in LEAD_TYPES:
                    leads += val
                elif atype in LANDING_PAGE_TYPES:
                    landing_page_views += val

            for av in action_values:
                if av.get("action_type") in PURCHASE_TYPES:
                    revenue += float(av.get("value", 0))

            spend = float(row.get("spend", 0))
            impressions = int(row.get("impressions", 0))
            clicks = int(row.get("clicks", 0))

            results.append({
                "campaign_id": row["campaign_id"],
                "date": row["date_start"],
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": float(row.get("ctr", 0)),
                "conversions": conversions,
                "revenue": revenue,
                "roas": revenue / spend if spend > 0 else 0,
                "cpa": spend / conversions if conversions > 0 else None,
                "cpc": float(row.get("cpc", 0)) if row.get("cpc") else None,
                "frequency": float(row.get("frequency", 0)) if row.get("frequency") else None,
                "add_to_cart": add_to_cart,
                "checkouts": checkouts,
                "searches": searches,
                "leads": leads,
                "landing_page_views": landing_page_views,
            })

        logger.info(
            "Fetched %d insight rows from Meta account %s (%s to %s)",
            len(results), account_id, date_from, date_to,
        )
        return results
    except Exception:
        logger.exception("Failed to fetch insights from Meta account %s", account_id)
        raise


def _to_json_safe(obj):
    """Recursively convert Meta SDK objects to JSON-serializable dicts."""
    import json
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        pass
    if hasattr(obj, "export_all_data"):
        return obj.export_all_data()
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    return str(obj)


def fetch_ad_sets(account_id: str, access_token: str) -> list[dict]:
    """Fetch all ad sets for a given ad account."""
    _init_api(access_token)
    try:
        account = AdAccount(account_id)
        ad_sets = account.get_ad_sets(fields=ADSET_FIELDS)
        results = []
        for s in ad_sets:
            raw_targeting = s.get(AdSet.Field.targeting)
            results.append({
                "platform_adset_id": s[AdSet.Field.id],
                "campaign_id": s[AdSet.Field.campaign_id],
                "name": s[AdSet.Field.name],
                "status": s[AdSet.Field.status],
                "optimization_goal": s.get(AdSet.Field.optimization_goal, ""),
                "billing_event": s.get(AdSet.Field.billing_event, ""),
                "daily_budget": s.get(AdSet.Field.daily_budget),
                "lifetime_budget": s.get(AdSet.Field.lifetime_budget),
                "targeting": _to_json_safe(raw_targeting) if raw_targeting else None,
                "start_date": _parse_date(s.get(AdSet.Field.start_time)),
                "end_date": _parse_date(s.get(AdSet.Field.end_time)),
                "raw_data": _to_json_safe(dict(s)),
            })
        logger.info("Fetched %d ad sets from Meta account %s", len(results), account_id)
        return results
    except Exception:
        logger.exception("Failed to fetch ad sets from Meta account %s", account_id)
        raise


def fetch_ads(account_id: str, access_token: str) -> list[dict]:
    """Fetch all ads for a given ad account."""
    _init_api(access_token)
    try:
        account = AdAccount(account_id)
        ads = account.get_ads(fields=AD_FIELDS)
        results = []
        for a in ads:
            creative = a.get(Ad.Field.creative)
            results.append({
                "platform_ad_id": a[Ad.Field.id],
                "platform_adset_id": a[Ad.Field.adset_id],
                "platform_campaign_id": a[Ad.Field.campaign_id],
                "name": a[Ad.Field.name],
                "status": a[Ad.Field.status],
                "creative_id": creative.get("id") if creative else None,
                "raw_data": _to_json_safe(dict(a)),
            })
        logger.info("Fetched %d ads from Meta account %s", len(results), account_id)
        return results
    except Exception:
        logger.exception("Failed to fetch ads from Meta account %s", account_id)
        raise


def _parse_insights_rows(rows, entity_id_key: str) -> list[dict]:
    """Shared parser for insight rows at any level (campaign/adset/ad)."""
    PURCHASE_TYPES = {"purchase", "offsite_conversion.fb_pixel_purchase"}
    ADD_TO_CART_TYPES = {"add_to_cart", "offsite_conversion.fb_pixel_add_to_cart"}
    CHECKOUT_TYPES = {"initiate_checkout", "offsite_conversion.fb_pixel_initiate_checkout"}
    SEARCH_TYPES = {"search", "offsite_conversion.fb_pixel_search"}
    LEAD_TYPES = {"lead", "offsite_conversion.fb_pixel_lead"}
    LANDING_PAGE_TYPES = {"landing_page_view"}

    results = []
    for row in rows:
        actions = row.get("actions") or []
        action_values = row.get("action_values") or []

        conversions = add_to_cart = checkouts = searches = leads = landing_page_views = 0
        revenue = 0.0

        for action in actions:
            atype = action.get("action_type", "")
            val = int(action.get("value", 0))
            if atype in PURCHASE_TYPES:
                conversions += val
            elif atype in ADD_TO_CART_TYPES:
                add_to_cart += val
            elif atype in CHECKOUT_TYPES:
                checkouts += val
            elif atype in SEARCH_TYPES:
                searches += val
            elif atype in LEAD_TYPES:
                leads += val
            elif atype in LANDING_PAGE_TYPES:
                landing_page_views += val

        for av in action_values:
            if av.get("action_type") in PURCHASE_TYPES:
                revenue += float(av.get("value", 0))

        spend = float(row.get("spend", 0))
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))

        result = {
            "entity_id": row.get(entity_id_key),
            "campaign_id": row.get("campaign_id"),
            "date": row["date_start"],
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": float(row.get("ctr", 0)),
            "conversions": conversions,
            "revenue": revenue,
            "roas": revenue / spend if spend > 0 else 0,
            "cpa": spend / conversions if conversions > 0 else None,
            "cpc": float(row.get("cpc", 0)) if row.get("cpc") else None,
            "frequency": float(row.get("frequency", 0)) if row.get("frequency") else None,
            "add_to_cart": add_to_cart,
            "checkouts": checkouts,
            "searches": searches,
            "leads": leads,
            "landing_page_views": landing_page_views,
        }
        # Add adset_id for ad-level insights
        if "adset_id" in row:
            result["adset_id"] = row["adset_id"]
        results.append(result)

    return results


def fetch_ad_set_insights(
    account_id: str,
    access_token: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily insights at ad-set level."""
    _init_api(access_token)
    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    try:
        account = AdAccount(account_id)
        insights = account.get_insights(
            fields=INSIGHT_FIELDS + ["adset_id", "adset_name"],
            params={
                "level": "adset",
                "time_range": {"since": date_from.isoformat(), "until": date_to.isoformat()},
                "time_increment": 1,
            },
        )
        results = _parse_insights_rows(insights, "adset_id")
        logger.info("Fetched %d ad-set insight rows from Meta account %s", len(results), account_id)
        return results
    except Exception:
        logger.exception("Failed to fetch ad-set insights from Meta account %s", account_id)
        raise


def fetch_ad_insights(
    account_id: str,
    access_token: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily insights at ad level."""
    _init_api(access_token)
    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    try:
        account = AdAccount(account_id)
        insights = account.get_insights(
            fields=INSIGHT_FIELDS + ["ad_id", "ad_name", "adset_id"],
            params={
                "level": "ad",
                "time_range": {"since": date_from.isoformat(), "until": date_to.isoformat()},
                "time_increment": 1,
            },
        )
        results = _parse_insights_rows(insights, "ad_id")
        logger.info("Fetched %d ad insight rows from Meta account %s", len(results), account_id)
        return results
    except Exception:
        logger.exception("Failed to fetch ad insights from Meta account %s", account_id)
        raise
