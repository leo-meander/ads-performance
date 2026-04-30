"""Google Ads sync engine: orchestrates fetching and upserting Google Ads data.

Follows the same pattern as sync_meta_account in sync_engine.py.
Platform separation: this file has NO imports from meta_client.py.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

# Google rolling sync window: 21 days. Google Ads default attribution is
# 30-day click for Search/Display, and offline conversion uploads (Cloudbeds
# bookings imported via Google offline-conversion API) regularly arrive
# 7-21 days after the original click. Wider than Meta's 14-day window
# because Google's attribution + offline-upload patterns lag longer.
# Tier-2 weekly sync-backfill (60-day window) catches the long tail.
SYNC_LOOKBACK_DAYS = 21

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.google_asset_group import GoogleAssetGroup
from app.models.google_asset import GoogleAsset
from app.models.metrics import MetricsCache
from app.services.google_client import (
    fetch_ad_group_metrics,
    fetch_ad_groups,
    fetch_ad_metrics,
    fetch_ads,
    fetch_asset_group_assets,
    fetch_asset_groups,
    fetch_campaign_brand_exclusions,
    fetch_campaign_metrics,
    fetch_campaign_user_country_metrics,
    fetch_campaigns,
    fetch_conversion_action_metrics,
)
from app.config import settings
from app.services.changelog import log_change
from app.services.parse_utils import (
    parse_campaign_metadata,
    parse_google_country,
)

logger = logging.getLogger(__name__)


def _upsert_google_metrics(
    db: Session,
    campaign_id: str,
    insight: dict,
    insight_date: date,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
) -> None:
    """Upsert a single metrics row for Google Ads."""
    q = db.query(MetricsCache).filter(
        MetricsCache.campaign_id == campaign_id,
        MetricsCache.date == insight_date,
    )
    if ad_id:
        q = q.filter(MetricsCache.ad_id == ad_id)
    elif ad_set_id:
        q = q.filter(MetricsCache.ad_set_id == ad_set_id, MetricsCache.ad_id.is_(None))
    else:
        q = q.filter(MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None))

    existing = q.first()
    now = datetime.now(timezone.utc)

    # Defensive cap on CTR (edge cases where clicks > impressions).
    raw_ctr = insight.get("ctr") or 0
    safe_ctr = min(float(raw_ctr), 99.999999) if raw_ctr else 0
    metric_fields = {
        "spend": insight["spend"],
        "impressions": insight["impressions"],
        "clicks": insight["clicks"],
        # Google Ads doesn't expose a separate "link clicks" metric — every
        # click on a Google ad navigates to the destination. Mirror clicks
        # into link_clicks so the landing-page rollup reads the same column
        # regardless of source platform.
        "link_clicks": insight["clicks"],
        "ctr": safe_ctr,
        "conversions": insight["conversions"],
        "revenue": insight["revenue"],
        "roas": insight["roas"],
        "cpa": insight["cpa"],
        "cpc": insight["cpc"],
        "frequency": insight.get("frequency"),
        "add_to_cart": insight.get("add_to_cart", 0),
        "checkouts": insight.get("checkouts", 0),
        "searches": insight.get("searches", 0),
        "leads": insight.get("leads", 0),
        "landing_page_views": insight.get("landing_page_views", 0),
        "revenue_website": insight.get("revenue_website", insight.get("revenue", 0)),
        "revenue_offline": insight.get("revenue_offline", 0),
        "computed_at": now,
    }

    if existing:
        for k, v in metric_fields.items():
            setattr(existing, k, v)
        existing.updated_at = now
    else:
        metric = MetricsCache(
            campaign_id=campaign_id,
            ad_set_id=ad_set_id,
            ad_id=ad_id,
            platform="google",
            date=insight_date,
            **metric_fields,
        )
        db.add(metric)


def sync_google_metrics_window(
    db: Session,
    account: AdAccount,
    date_from: date,
    date_to: date,
) -> dict:
    """Re-pull Google campaign / ad-group / ad metrics + ad×country for a window.

    Used by both the regular sync (default 10-day rolling window) and by the
    historical backfill endpoint (chunked 30-day windows over N months).
    Assumes campaigns/ad groups/ads are already in the DB — only metrics rows
    are written.
    """
    customer_id = account.account_id.replace("-", "")
    summary = {"metrics_synced": 0, "ad_country_rows": 0, "errors": []}

    if not settings.GOOGLE_REFRESH_TOKEN or not settings.GOOGLE_DEVELOPER_TOKEN:
        summary["errors"].append("Google Ads global credentials missing")
        return summary

    # --- Campaign-level metrics ---
    try:
        raw_metrics = fetch_campaign_metrics(customer_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch campaign metrics: {e}")
        raw_metrics = []

    for insight in raw_metrics:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == insight["campaign_id"])
            .first()
        )
        if not campaign:
            continue
        insight_date = (
            date.fromisoformat(insight["date"]) if isinstance(insight["date"], str) else insight["date"]
        )
        _upsert_google_metrics(db, campaign.id, insight, insight_date)
        summary["metrics_synced"] += 1

    # --- Ad-group-level metrics ---
    try:
        ag_metrics = fetch_ad_group_metrics(customer_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad group metrics: {e}")
        ag_metrics = []

    for insight in ag_metrics:
        adset = (
            db.query(AdSet)
            .filter(AdSet.platform_adset_id == insight["entity_id"])
            .first()
        )
        if not adset:
            continue
        insight_date = (
            date.fromisoformat(insight["date"]) if isinstance(insight["date"], str) else insight["date"]
        )
        _upsert_google_metrics(db, adset.campaign_id, insight, insight_date, ad_set_id=adset.id)
        summary["metrics_synced"] += 1

    # --- Ad-level metrics ---
    try:
        ad_metrics_data = fetch_ad_metrics(customer_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad metrics: {e}")
        ad_metrics_data = []

    for insight in ad_metrics_data:
        ad_obj = (
            db.query(Ad)
            .filter(Ad.platform_ad_id == insight["entity_id"])
            .first()
        )
        if not ad_obj:
            continue
        insight_date = (
            date.fromisoformat(insight["date"]) if isinstance(insight["date"], str) else insight["date"]
        )
        _upsert_google_metrics(
            db, ad_obj.campaign_id, insight, insight_date,
            ad_set_id=ad_obj.ad_set_id, ad_id=ad_obj.id,
        )
        summary["metrics_synced"] += 1

    # --- Conversion-action metrics merged into existing campaign rows ---
    try:
        conv_action_data = fetch_conversion_action_metrics(customer_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch conversion action metrics: {e}")
        conv_action_data = []

    for row in conv_action_data:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == row["campaign_id"])
            .first()
        )
        if not campaign:
            continue
        insight_date = (
            date.fromisoformat(row["date"]) if isinstance(row["date"], str) else row["date"]
        )
        existing = (
            db.query(MetricsCache)
            .filter(
                MetricsCache.campaign_id == campaign.id,
                MetricsCache.date == insight_date,
                MetricsCache.ad_set_id.is_(None),
                MetricsCache.ad_id.is_(None),
            )
            .first()
        )
        if existing:
            current = getattr(existing, row["column"], 0) or 0
            setattr(existing, row["column"], current + row["value"])

    db.commit()

    # --- Campaign × user_country breakdown (Google has no ad-level user_location) ---
    try:
        country_rows = fetch_campaign_user_country_metrics(customer_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch user_location_view: {e}")
        country_rows = []

    now = datetime.now(timezone.utc)
    for row in country_rows:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == row["campaign_id"])
            .first()
        )
        if not campaign:
            continue
        insight_date = (
            date.fromisoformat(row["date"]) if isinstance(row["date"], str) else row["date"]
        )
        country = row.get("country")
        if not country:
            continue
        existing = (
            db.query(AdCountryMetric)
            .filter(
                AdCountryMetric.campaign_id == campaign.id,
                AdCountryMetric.ad_id.is_(None),
                AdCountryMetric.date == insight_date,
                AdCountryMetric.country == country,
            )
            .first()
        )
        values = {
            "spend": row.get("spend") or 0,
            "impressions": row.get("impressions") or 0,
            "clicks": row.get("clicks") or 0,
            "revenue_website": row.get("revenue_website") or 0,
            "revenue_offline": row.get("revenue_offline") or 0,
            "conversions_website": row.get("conversions") or 0,
            "conversions_offline": 0,
        }
        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
            existing.updated_at = now
        else:
            db.add(AdCountryMetric(
                platform="google",
                campaign_id=campaign.id,
                ad_id=None,
                date=insight_date,
                country=country,
                **values,
            ))
        summary["ad_country_rows"] += 1
    db.commit()
    return summary


def sync_google_account(
    db: Session,
    account: AdAccount,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """Sync campaigns, ad groups, ads, asset groups, assets, and metrics
    for a single Google Ads account.

    `date_from` / `date_to` override the default rolling window (last 10 days).
    Returns summary dict matching sync_meta_account format.
    """
    customer_id = account.account_id.replace("-", "")
    summary = {
        "campaigns_synced": 0,
        "adsets_synced": 0,
        "ads_synced": 0,
        "asset_groups_synced": 0,
        "assets_synced": 0,
        "metrics_synced": 0,
        "errors": [],
    }

    # Google uses global OAuth credentials from .env, not per-account tokens
    if not settings.GOOGLE_REFRESH_TOKEN or not settings.GOOGLE_DEVELOPER_TOKEN:
        summary["errors"].append(
            "Google Ads global credentials missing: set GOOGLE_REFRESH_TOKEN "
            "and GOOGLE_DEVELOPER_TOKEN in .env"
        )
        return summary

    # --- 1. Fetch and upsert campaigns ---
    try:
        raw_campaigns = fetch_campaigns(customer_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch campaigns: {e}")
        return summary

    # Brand-exclusion lookup — merged into raw_data per campaign.
    try:
        brand_excluded_ids = fetch_campaign_brand_exclusions(customer_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch brand exclusions: {e}")
        brand_excluded_ids = set()

    for raw in raw_campaigns:
        parsed = parse_campaign_metadata(raw["name"])
        country = parse_google_country(raw["name"])
        # Enrich raw_data with brand-exclusion flag before persisting.
        raw_data = dict(raw.get("raw_data") or {})
        raw_data["has_brand_exclusion"] = raw["platform_campaign_id"] in brand_excluded_ids

        existing = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == raw["platform_campaign_id"])
            .first()
        )
        if existing:
            existing.name = raw["name"]
            existing.status = raw["status"]
            existing.objective = raw["objective"]
            existing.daily_budget = raw["daily_budget"]
            existing.lifetime_budget = raw["lifetime_budget"]
            existing.ta = parsed["ta"]
            existing.funnel_stage = parsed["funnel_stage"]
            existing.country = country
            # start_date only overwritten if we got a real value from the API —
            # never null out an existing start_date.
            if raw.get("start_date"):
                existing.start_date = raw["start_date"]
            if raw.get("end_date"):
                existing.end_date = raw["end_date"]
            existing.raw_data = raw_data
            existing.updated_at = datetime.now(timezone.utc)
        else:
            new_id = str(uuid.uuid4())
            campaign = Campaign(
                id=new_id,
                account_id=account.id,
                platform="google",
                platform_campaign_id=raw["platform_campaign_id"],
                name=raw["name"],
                status=raw["status"],
                objective=raw["objective"],
                daily_budget=raw["daily_budget"],
                lifetime_budget=raw["lifetime_budget"],
                ta=parsed["ta"],
                funnel_stage=parsed["funnel_stage"],
                country=country,
                start_date=raw.get("start_date"),
                end_date=raw.get("end_date"),
                raw_data=raw_data,
            )
            db.add(campaign)
            # Google GAQL v23 doesn't expose campaign.creation_time in MCC
            # context, so fall back to start_date if present, else now.
            occurred = raw.get("start_date") or datetime.now(timezone.utc).date()
            occurred_dt = (
                datetime.combine(occurred, datetime.min.time(), tzinfo=timezone.utc)
                if isinstance(occurred, date) else datetime.now(timezone.utc)
            )
            log_change(
                db,
                category="ad_creation",
                title=f"Campaign created: {raw['name']}"[:200],
                source="auto",
                triggered_by="system",
                occurred_at=occurred_dt,
                description=f"New Google campaign synced (objective={raw.get('objective') or '?'})",
                platform="google",
                country=country,
                account_id=account.id,
                campaign_id=new_id,
                after_value={
                    "platform_campaign_id": raw["platform_campaign_id"],
                    "objective": raw.get("objective"),
                    "status": raw.get("status"),
                },
            )
        summary["campaigns_synced"] += 1

    db.flush()

    # --- 2. Fetch and upsert ad groups (Search campaigns) ---
    try:
        raw_ad_groups = fetch_ad_groups(customer_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad groups: {e}")
        raw_ad_groups = []

    for raw in raw_ad_groups:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == raw["campaign_id"])
            .first()
        )
        if not campaign:
            logger.warning(
                "Campaign %s not found for ad group %s, skipping",
                raw["campaign_id"], raw["platform_adset_id"],
            )
            continue

        # Google adgroups don't carry country — it lives in the trailing 2 chars
        # of the parent campaign name (e.g. `..._VN`, `..._TW`).
        country = parse_google_country(campaign.name)

        existing = (
            db.query(AdSet)
            .filter(AdSet.platform_adset_id == raw["platform_adset_id"])
            .first()
        )
        if existing:
            existing.name = raw["name"]
            existing.status = raw["status"]
            existing.country = country
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            adset = AdSet(
                campaign_id=campaign.id,
                account_id=account.id,
                platform="google",
                platform_adset_id=raw["platform_adset_id"],
                name=raw["name"],
                status=raw["status"],
                country=country,
                raw_data=raw["raw_data"],
            )
            db.add(adset)
        summary["adsets_synced"] += 1

    db.flush()

    # --- 3. Fetch and upsert RSA ads ---
    try:
        raw_ads = fetch_ads(customer_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ads: {e}")
        raw_ads = []

    for raw in raw_ads:
        adset = (
            db.query(AdSet)
            .filter(AdSet.platform_adset_id == raw["platform_adset_id"])
            .first()
        )
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == raw["platform_campaign_id"])
            .first()
        )
        if not adset or not campaign:
            logger.warning(
                "Ad set or campaign not found for ad %s, skipping",
                raw["platform_ad_id"],
            )
            continue

        existing = (
            db.query(Ad)
            .filter(Ad.platform_ad_id == raw["platform_ad_id"])
            .first()
        )
        if existing:
            existing.name = raw["name"]
            existing.status = raw["status"]
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            new_id = str(uuid.uuid4())
            ad = Ad(
                id=new_id,
                ad_set_id=adset.id,
                campaign_id=campaign.id,
                account_id=account.id,
                platform="google",
                platform_ad_id=raw["platform_ad_id"],
                name=raw["name"],
                status=raw["status"],
                creative_id=None,
                raw_data=raw["raw_data"],
            )
            db.add(ad)
            log_change(
                db,
                category="ad_creation",
                title=f"Ad created: {raw['name']}"[:200],
                source="auto",
                triggered_by="system",
                occurred_at=datetime.now(timezone.utc),
                description=f"New Google ad synced under campaign '{campaign.name}'",
                platform="google",
                account_id=account.id,
                campaign_id=campaign.id,
                ad_set_id=adset.id,
                ad_id=new_id,
                after_value={
                    "platform_ad_id": raw["platform_ad_id"],
                    "status": raw.get("status"),
                },
            )
        summary["ads_synced"] += 1

    db.flush()

    # --- 4. Fetch and upsert PMax asset groups ---
    try:
        raw_asset_groups = fetch_asset_groups(customer_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch asset groups: {e}")
        raw_asset_groups = []

    for raw in raw_asset_groups:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == raw["campaign_id"])
            .first()
        )
        if not campaign:
            logger.warning(
                "Campaign %s not found for asset group %s, skipping",
                raw["campaign_id"], raw["platform_asset_group_id"],
            )
            continue

        existing = (
            db.query(GoogleAssetGroup)
            .filter(GoogleAssetGroup.platform_asset_group_id == raw["platform_asset_group_id"])
            .first()
        )
        if existing:
            existing.name = raw["name"]
            existing.status = raw["status"]
            existing.final_urls = raw["final_urls"]
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            asset_group = GoogleAssetGroup(
                campaign_id=campaign.id,
                account_id=account.id,
                platform_asset_group_id=raw["platform_asset_group_id"],
                name=raw["name"],
                status=raw["status"],
                final_urls=raw["final_urls"],
                raw_data=raw["raw_data"],
            )
            db.add(asset_group)
        summary["asset_groups_synced"] += 1

    db.flush()

    # --- 5. Fetch and upsert assets ---
    try:
        raw_assets = fetch_asset_group_assets(customer_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch assets: {e}")
        raw_assets = []

    seen_assets = set()
    for raw in raw_assets:
        # Deduplicate: same asset can appear multiple times with different field_types
        dedup_key = (raw["asset_group_id"], raw["platform_asset_id"])
        if dedup_key in seen_assets:
            continue
        seen_assets.add(dedup_key)

        asset_group = (
            db.query(GoogleAssetGroup)
            .filter(GoogleAssetGroup.platform_asset_group_id == raw["asset_group_id"])
            .first()
        )
        if not asset_group:
            logger.warning(
                "Asset group %s not found for asset %s, skipping",
                raw["asset_group_id"], raw["platform_asset_id"],
            )
            continue

        existing = (
            db.query(GoogleAsset)
            .filter(
                GoogleAsset.asset_group_id == asset_group.id,
                GoogleAsset.platform_asset_id == raw["platform_asset_id"],
            )
            .first()
        )
        if existing:
            existing.asset_type = raw["asset_type"]
            existing.text_content = raw["text_content"]
            existing.image_url = raw["image_url"]
            existing.performance_label = raw["performance_label"]
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            asset = GoogleAsset(
                asset_group_id=asset_group.id,
                account_id=asset_group.account_id,
                platform_asset_id=raw["platform_asset_id"],
                asset_type=raw["asset_type"],
                text_content=raw["text_content"],
                image_url=raw["image_url"],
                performance_label=raw["performance_label"],
                raw_data=raw["raw_data"],
            )
            db.add(asset)
        summary["assets_synced"] += 1

    db.flush()

    # Default rolling window: last SYNC_LOOKBACK_DAYS including today.
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=SYNC_LOOKBACK_DAYS - 1)

    window_summary = sync_google_metrics_window(db, account, date_from, date_to)
    summary["metrics_synced"] = window_summary["metrics_synced"]
    summary["ad_country_rows"] = window_summary["ad_country_rows"]
    if window_summary["errors"]:
        summary["errors"].extend(window_summary["errors"])

    logger.info(
        "Google sync complete for account %s: %d campaigns, %d ad groups, "
        "%d ads, %d asset groups, %d assets, %d metrics rows",
        account.account_id,
        summary["campaigns_synced"],
        summary["adsets_synced"],
        summary["ads_synced"],
        summary["asset_groups_synced"],
        summary["assets_synced"],
        summary["metrics_synced"],
    )
    return summary
