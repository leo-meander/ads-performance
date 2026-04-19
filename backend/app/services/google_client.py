"""Google Ads API client.

Fetches campaigns, ad groups, ads (RSA), asset groups (PMax),
and metrics from the Google Ads API using GAQL queries.
Uses the google-ads Python SDK.
"""

import logging
from datetime import date, timedelta
from typing import Any

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from app.config import settings

logger = logging.getLogger(__name__)

# Status normalization: Google -> internal convention
_STATUS_MAP = {
    "ENABLED": "ACTIVE",
    "PAUSED": "PAUSED",
    "REMOVED": "ARCHIVED",
}

# Asset field type -> simplified asset_type
_FIELD_TYPE_MAP = {
    "HEADLINE": "HEADLINE",
    "DESCRIPTION": "DESCRIPTION",
    "MARKETING_IMAGE": "IMAGE",
    "SQUARE_MARKETING_IMAGE": "IMAGE",
    "PORTRAIT_MARKETING_IMAGE": "IMAGE",
    "LANDSCAPE_LOGO": "LOGO",
    "SQUARE_LOGO": "LOGO",
    "LOGO": "LOGO",
    "YOUTUBE_VIDEO": "VIDEO",
    "CALL_TO_ACTION_SELECTION": "CALL_TO_ACTION",
    "BUSINESS_NAME": "BUSINESS_NAME",
    "LONG_HEADLINE": "HEADLINE",
}


def _get_client() -> GoogleAdsClient:
    """Create GoogleAdsClient from config settings."""
    credentials = {
        "developer_token": settings.GOOGLE_DEVELOPER_TOKEN,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": settings.GOOGLE_REFRESH_TOKEN,
        "login_customer_id": settings.GOOGLE_LOGIN_CUSTOMER_ID.replace("-", ""),
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(credentials)


def _enum_name(enum_val: Any) -> str:
    """Get the string name from a Google Ads proto-plus enum value."""
    if hasattr(enum_val, 'name'):
        return enum_val.name
    name = str(enum_val).split(".")[-1]
    return name


def _normalize_status(status_enum: Any) -> str:
    """Convert Google Ads status enum to internal convention."""
    name = _enum_name(status_enum)
    return _STATUS_MAP.get(name, name)


def _micros_to_currency(micros: int | None) -> float | None:
    """Convert Google Ads micros (1,000,000 = 1 unit) to currency float."""
    if micros is None:
        return None
    return micros / 1_000_000


def _search_stream(client: GoogleAdsClient, customer_id: str, query: str) -> list[Any]:
    """Execute a GAQL query via SearchStream and collect all rows."""
    ga_service = client.get_service("GoogleAdsService")
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    rows = []
    for batch in stream:
        for row in batch.results:
            rows.append(row)
    return rows


def _parse_date_str(s: str | None):
    """Parse a Google Ads date string (YYYY-MM-DD). Returns date or None."""
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def fetch_campaigns(customer_id: str) -> list[dict]:
    """Fetch all active/paused campaigns for a Google Ads account.

    Pulls PMax-relevant fields (bidding strategy type, tCPA/tROAS targets,
    start_date) for the recommendation engine. Portfolio bid-strategy fields
    and url_expansion are intentionally omitted — v23 GAQL rejects
    campaign.url_expansion_opt_out and the portfolio bid fields for our
    MCC query context.
    Returns list of dicts compatible with the campaigns table schema.
    """
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign.start_date,
            campaign.end_date,
            campaign.bidding_strategy_type,
            campaign.maximize_conversions.target_cpa_micros,
            campaign.maximize_conversion_value.target_roas,
            campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status != 'REMOVED'
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = []
        for row in rows:
            c = row.campaign
            campaign_type = _enum_name(c.advertising_channel_type)
            bidding_strategy_type = _enum_name(c.bidding_strategy_type) if c.bidding_strategy_type else None

            tcpa_micros = c.maximize_conversions.target_cpa_micros or None
            troas = c.maximize_conversion_value.target_roas or None
            results.append({
                "platform_campaign_id": str(c.id),
                "name": c.name,
                "status": _normalize_status(c.status),
                "objective": campaign_type,  # PERFORMANCE_MAX, SEARCH, DISPLAY, etc.
                "daily_budget": _micros_to_currency(
                    row.campaign_budget.amount_micros if row.campaign_budget else None
                ),
                "lifetime_budget": None,  # Google uses daily budgets
                "start_date": _parse_date_str(c.start_date),
                "end_date": _parse_date_str(c.end_date),
                "raw_data": {
                    "campaign_id": str(c.id),
                    "campaign_type": campaign_type,
                    "budget_micros": row.campaign_budget.amount_micros if row.campaign_budget else None,
                    "bidding_strategy_type": bidding_strategy_type,
                    "target_cpa_micros": int(tcpa_micros) if tcpa_micros else None,
                    "target_roas": float(troas) if troas else None,
                },
            })
        logger.info("Fetched %d campaigns from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching campaigns for %s: %s", customer_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch campaigns from Google account %s", customer_id)
        raise


def fetch_ad_groups(customer_id: str) -> list[dict]:
    """Fetch ad groups (Search campaigns). Maps to ad_sets table."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = """
        SELECT
            ad_group.id,
            ad_group.name,
            ad_group.status,
            ad_group.campaign,
            campaign.id
        FROM ad_group
        WHERE ad_group.status != 'REMOVED'
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = []
        for row in rows:
            ag = row.ad_group
            results.append({
                "platform_adset_id": str(ag.id),
                "campaign_id": str(row.campaign.id),
                "name": ag.name,
                "status": _normalize_status(ag.status),
                "optimization_goal": None,
                "billing_event": None,
                "daily_budget": None,
                "lifetime_budget": None,
                "targeting": None,
                "raw_data": {"ad_group_id": str(ag.id)},
            })
        logger.info("Fetched %d ad groups from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching ad groups for %s: %s", customer_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch ad groups from Google account %s", customer_id)
        raise


def fetch_ads(customer_id: str) -> list[dict]:
    """Fetch RSA ads (responsive search ads). Maps to ads table."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = """
        SELECT
            ad_group_ad.ad.id,
            ad_group_ad.ad.name,
            ad_group_ad.ad.type,
            ad_group_ad.status,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group.id,
            campaign.id
        FROM ad_group_ad
        WHERE ad_group_ad.status != 'REMOVED'
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = []
        for row in rows:
            ad = row.ad_group_ad.ad
            rsa = ad.responsive_search_ad

            headlines = [h.text for h in rsa.headlines] if rsa and rsa.headlines else []
            descriptions = [d.text for d in rsa.descriptions] if rsa and rsa.descriptions else []

            ad_type = _enum_name(ad.type_) if ad.type_ else "UNKNOWN"

            results.append({
                "platform_ad_id": str(ad.id),
                "platform_adset_id": str(row.ad_group.id),
                "platform_campaign_id": str(row.campaign.id),
                "name": ad.name or f"Ad {ad.id}",
                "status": _normalize_status(row.ad_group_ad.status),
                "creative_id": None,
                "raw_data": {
                    "ad_id": str(ad.id),
                    "ad_type": ad_type,
                    "headlines": headlines,
                    "descriptions": descriptions,
                },
            })
        logger.info("Fetched %d ads from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching ads for %s: %s", customer_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch ads from Google account %s", customer_id)
        raise


def _fetch_asset_group_signals(client: GoogleAdsClient, customer_id: str) -> dict[str, list[dict]]:
    """Return {asset_group_id: [{signal_type, resource_name}, ...]}.

    asset_group_signal links an asset group to a Customer Match, remarketing
    list, custom-intent, or lookalike audience. PMax asset groups without any
    signal learn slower — that's what PMAX_MISSING_AUDIENCE_SIGNAL checks.
    """
    query = """
        SELECT
            asset_group_signal.asset_group,
            asset_group_signal.audience,
            asset_group_signal.search_theme.text
        FROM asset_group_signal
    """
    out: dict[str, list[dict]] = {}
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("Failed to fetch asset_group_signal for %s", customer_id)
        return out
    except Exception:
        logger.exception("asset_group_signal query crashed for %s", customer_id)
        return out

    for row in rows:
        ags = row.asset_group_signal
        asset_group_resource = ags.asset_group
        # resource name format: customers/{cid}/assetGroups/{id}
        asset_group_id = asset_group_resource.split("/")[-1]
        audience_rn = ags.audience
        search_theme = ags.search_theme.text if ags.search_theme else None
        if audience_rn:
            out.setdefault(asset_group_id, []).append({
                "signal_type": "AUDIENCE",
                "resource_name": audience_rn,
            })
        elif search_theme:
            out.setdefault(asset_group_id, []).append({
                "signal_type": "SEARCH_THEME",
                "text": search_theme,
            })
    return out


def fetch_asset_groups(customer_id: str) -> list[dict]:
    """Fetch PMax asset groups and their audience/search-theme signals."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = """
        SELECT
            asset_group.id,
            asset_group.name,
            asset_group.status,
            asset_group.campaign,
            campaign.id
        FROM asset_group
        WHERE asset_group.status != 'REMOVED'
    """

    try:
        signals_by_ag = _fetch_asset_group_signals(client, customer_id)
        rows = _search_stream(client, customer_id, query)
        results = []
        for row in rows:
            ag = row.asset_group
            ag_id = str(ag.id)
            signals = signals_by_ag.get(ag_id, [])
            results.append({
                "platform_asset_group_id": ag_id,
                "campaign_id": str(row.campaign.id),
                "name": ag.name,
                "status": _normalize_status(ag.status),
                "final_urls": [],
                "raw_data": {
                    "asset_group_id": ag_id,
                    "audience_signals": signals,
                    "signal_count": len(signals),
                },
            })
        logger.info("Fetched %d asset groups from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching asset groups for %s: %s", customer_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch asset groups from Google account %s", customer_id)
        raise


def fetch_campaign_brand_exclusions(customer_id: str) -> set[str]:
    """Return set of platform_campaign_ids that have a BRAND_LIST asset set attached.

    For PMax, a Brand Exclusion list is attached via campaign_asset_set where
    asset_set.type = BRAND_LIST. Campaigns not in the returned set have no
    brand exclusion — what PMAX_MISSING_BRAND_EXCLUSION flags.
    """
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = """
        SELECT
            campaign_asset_set.campaign,
            campaign_asset_set.asset_set,
            asset_set.type
        FROM campaign_asset_set
        WHERE campaign_asset_set.status = 'ENABLED'
    """
    try:
        rows = _search_stream(client, customer_id, query)
    except GoogleAdsException:
        logger.exception("Failed to fetch campaign_asset_set for %s", customer_id)
        return set()
    except Exception:
        logger.exception("campaign_asset_set query crashed for %s", customer_id)
        return set()

    out: set[str] = set()
    for row in rows:
        set_type = _enum_name(row.asset_set.type_) if row.asset_set.type_ else ""
        if set_type != "BRAND_LIST":
            continue
        campaign_resource = row.campaign_asset_set.campaign
        # resource name format: customers/{cid}/campaigns/{id}
        out.add(campaign_resource.split("/")[-1])
    logger.info(
        "Found %d campaigns with BRAND_LIST exclusions in Google account %s",
        len(out), customer_id,
    )
    return out


def fetch_asset_group_assets(customer_id: str) -> list[dict]:
    """Fetch assets linked to PMax asset groups."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    query = """
        SELECT
            asset_group_asset.asset,
            asset_group_asset.asset_group,
            asset_group_asset.field_type,
            asset.id,
            asset.name,
            asset.text_asset.text,
            asset.image_asset.full_size.url,
            asset.youtube_video_asset.youtube_video_id,
            asset_group.id
        FROM asset_group_asset
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = []
        for row in rows:
            asset = row.asset
            aga = row.asset_group_asset

            field_type = _enum_name(aga.field_type)
            asset_type = _FIELD_TYPE_MAP.get(field_type, field_type)

            perf_label = None

            # Determine content based on type
            text_content = None
            image_url = None
            if asset.text_asset and asset.text_asset.text:
                text_content = asset.text_asset.text
            if asset.image_asset and asset.image_asset.full_size and asset.image_asset.full_size.url:
                image_url = asset.image_asset.full_size.url
            if asset.youtube_video_asset and asset.youtube_video_asset.youtube_video_id:
                image_url = f"https://www.youtube.com/watch?v={asset.youtube_video_asset.youtube_video_id}"

            results.append({
                "platform_asset_id": str(asset.id),
                "asset_group_id": str(row.asset_group.id),
                "asset_type": asset_type,
                "text_content": text_content,
                "image_url": image_url,
                "performance_label": perf_label,
                "raw_data": {
                    "asset_id": str(asset.id),
                    "field_type": field_type,
                    "asset_name": asset.name,
                },
            })
        logger.info("Fetched %d asset group assets from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching assets for %s: %s", customer_id, ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch assets from Google account %s", customer_id)
        raise


def _parse_metrics_rows(rows: list[Any], entity_id_field: str) -> list[dict]:
    """Parse metrics rows from GAQL response into normalized dicts."""
    results = []
    for row in rows:
        m = row.metrics
        seg = row.segments

        spend = _micros_to_currency(m.cost_micros) or 0
        impressions = m.impressions or 0
        clicks = m.clicks or 0
        conversions = m.conversions or 0
        revenue = m.conversions_value or 0

        # Get entity ID dynamically
        if entity_id_field == "campaign":
            entity_id = str(row.campaign.id)
        elif entity_id_field == "ad_group":
            entity_id = str(row.ad_group.id)
        elif entity_id_field == "ad_group_ad":
            entity_id = str(row.ad_group_ad.ad.id)
        else:
            entity_id = None

        result = {
            "entity_id": entity_id,
            "campaign_id": str(row.campaign.id),
            "date": seg.date,
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": (clicks / impressions * 100) if impressions > 0 else 0,
            "conversions": int(conversions),
            "revenue": float(revenue),
            "roas": float(revenue) / spend if spend > 0 else 0,
            "cpa": spend / conversions if conversions > 0 else None,
            "cpc": spend / clicks if clicks > 0 else None,
            "frequency": None,  # Google doesn't have frequency like Meta
            "add_to_cart": 0,
            "checkouts": 0,
            "searches": 0,
            "leads": 0,
            "landing_page_views": 0,
        }

        # Add adset_id for ad-group and ad level
        if entity_id_field in ("ad_group", "ad_group_ad"):
            result["adset_id"] = str(row.ad_group.id)

        results.append(result)

    return results


def fetch_campaign_metrics(
    customer_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily campaign-level metrics."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    query = f"""
        SELECT
            campaign.id,
            segments.date,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
            AND campaign.status != 'REMOVED'
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = _parse_metrics_rows(rows, "campaign")
        logger.info(
            "Fetched %d campaign metric rows from Google account %s (%s to %s)",
            len(results), customer_id, date_from, date_to,
        )
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching campaign metrics: %s", ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch campaign metrics from Google account %s", customer_id)
        raise


def fetch_ad_group_metrics(
    customer_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily ad-group-level metrics."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    query = f"""
        SELECT
            ad_group.id,
            campaign.id,
            segments.date,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM ad_group
        WHERE segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
            AND ad_group.status != 'REMOVED'
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = _parse_metrics_rows(rows, "ad_group")
        logger.info("Fetched %d ad-group metric rows from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching ad group metrics: %s", ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch ad group metrics from Google account %s", customer_id)
        raise


def fetch_ad_metrics(
    customer_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily ad-level metrics."""
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    query = f"""
        SELECT
            ad_group_ad.ad.id,
            ad_group.id,
            campaign.id,
            segments.date,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions,
            metrics.conversions_value
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
            AND ad_group_ad.status != 'REMOVED'
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = _parse_metrics_rows(rows, "ad_group_ad")
        logger.info("Fetched %d ad metric rows from Google account %s", len(results), customer_id)
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching ad metrics: %s", ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch ad metrics from Google account %s", customer_id)
        raise


# Conversion action name patterns → metrics_cache column
_CONVERSION_ACTION_MAP = {
    "add_to_cart": "add_to_cart",
    "begin_checkout": "checkouts",
    "checkout": "checkouts",
    "purchase": "conversions",  # fallback — already counted in main metrics
    "lead": "leads",
    "website visits": "landing_page_views",
    "website_visit": "landing_page_views",
}


def _match_conversion_column(action_name: str) -> str | None:
    """Map a GA4 conversion action name to the metrics_cache column."""
    name_lower = action_name.lower()
    for pattern, column in _CONVERSION_ACTION_MAP.items():
        if pattern in name_lower:
            return column
    return None


def fetch_conversion_action_metrics(
    customer_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Fetch daily campaign-level conversion metrics segmented by conversion action.

    Returns list of dicts with campaign_id, date, conversion_action_name,
    conversions count, and the mapped column name.
    """
    customer_id = customer_id.replace("-", "")
    client = _get_client()

    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    query = f"""
        SELECT
            campaign.id,
            segments.date,
            segments.conversion_action_name,
            metrics.all_conversions
        FROM campaign
        WHERE segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
            AND campaign.status != 'REMOVED'
            AND metrics.all_conversions > 0
    """

    try:
        rows = _search_stream(client, customer_id, query)
        results = []
        for row in rows:
            action_name = row.segments.conversion_action_name
            column = _match_conversion_column(action_name)
            if column and column != "conversions":  # skip purchase — already in main metrics
                results.append({
                    "campaign_id": str(row.campaign.id),
                    "date": row.segments.date,
                    "conversion_action_name": action_name,
                    "column": column,
                    "value": int(row.metrics.all_conversions or 0),
                })
        logger.info(
            "Fetched %d conversion action metric rows from Google account %s",
            len(results), customer_id,
        )
        return results
    except GoogleAdsException as ex:
        logger.exception("Google Ads API error fetching conversion actions: %s", ex.failure)
        raise
    except Exception:
        logger.exception("Failed to fetch conversion action metrics from Google account %s", customer_id)
        raise
