"""TikTok Ads sync engine: fetch + upsert into the shared campaigns / ad_sets /
ads / metrics_cache tables.

Mirrors the structure of `google_sync_engine.py`. Platform separation: NO
imports from meta_client.py or google_client.py.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services.parse_utils import parse_adset_metadata, parse_campaign_metadata
from app.services.tiktok_client import (
    TikTokAPIError,
    fetch_ad_metrics,
    fetch_adgroup_metrics,
    fetch_adgroups,
    fetch_ads,
    fetch_advertiser_info,
    fetch_campaign_metrics,
    fetch_campaigns,
)

logger = logging.getLogger(__name__)


# Keep aligned with sync_engine.SYNC_LOOKBACK_DAYS so dashboards show consistent
# freshness across Meta / Google / TikTok.
SYNC_LOOKBACK_DAYS = 10


def _upsert_tiktok_metrics(
    db: Session,
    campaign_id: str,
    insight: dict,
    insight_date: date,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
) -> None:
    """Upsert a single metrics_cache row at any hierarchy level."""
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

    raw_ctr = insight.get("ctr") or 0
    safe_ctr = min(float(raw_ctr), 99.999999) if raw_ctr else 0
    metric_fields = {
        "spend": insight["spend"],
        "impressions": insight["impressions"],
        "clicks": insight["clicks"],
        "link_clicks": insight.get("link_clicks", insight["clicks"]),
        "ctr": safe_ctr,
        "conversions": insight["conversions"],
        "revenue": insight["revenue"],
        "revenue_website": insight.get("revenue_website", insight["revenue"]),
        "revenue_offline": insight.get("revenue_offline", 0),
        "roas": insight["roas"],
        "cpa": insight["cpa"],
        "cpc": insight["cpc"],
        "frequency": insight.get("frequency"),
        "add_to_cart": insight.get("add_to_cart", 0),
        "checkouts": insight.get("checkouts", 0),
        "searches": insight.get("searches", 0),
        "leads": insight.get("leads", 0),
        "landing_page_views": insight.get("landing_page_views", 0),
        "video_views": insight.get("video_views", 0),
        "video_3s_views": insight.get("video_3s_views", 0),
        "video_thru_plays": insight.get("video_thru_plays", 0),
        "video_p25_views": insight.get("video_p25_views", 0),
        "video_p50_views": insight.get("video_p50_views", 0),
        "video_p75_views": insight.get("video_p75_views", 0),
        "video_p100_views": insight.get("video_p100_views", 0),
        "computed_at": now,
    }

    if existing:
        for k, v in metric_fields.items():
            setattr(existing, k, v)
        existing.updated_at = now
    else:
        db.add(MetricsCache(
            campaign_id=campaign_id,
            ad_set_id=ad_set_id,
            ad_id=ad_id,
            platform="tiktok",
            date=insight_date,
            **metric_fields,
        ))


def sync_tiktok_metrics_window(
    db: Session,
    account: AdAccount,
    date_from: date,
    date_to: date,
) -> dict:
    """Re-pull campaign / adgroup / ad metrics for a date window.

    Used by the regular rolling-window sync and by the chunked historical
    backfill. Assumes campaigns / adgroups / ads are already in the DB —
    only metric rows are written.
    """
    summary = {"metrics_synced": 0, "ad_country_rows": 0, "errors": []}
    advertiser_id = account.account_id

    if not settings.TIKTOK_ACCESS_TOKEN:
        summary["errors"].append("TIKTOK_ACCESS_TOKEN not configured")
        return summary

    # --- Campaign-level ---
    try:
        campaign_metrics = fetch_campaign_metrics(advertiser_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch campaign metrics: {e}")
        campaign_metrics = []

    for insight in campaign_metrics:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == insight["campaign_id"])
            .first()
        )
        if not campaign:
            continue
        _upsert_tiktok_metrics(db, campaign.id, insight, insight["date"])
        summary["metrics_synced"] += 1

    # --- Adgroup-level ---
    try:
        adgroup_metrics = fetch_adgroup_metrics(advertiser_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch adgroup metrics: {e}")
        adgroup_metrics = []

    for insight in adgroup_metrics:
        adset = (
            db.query(AdSet)
            .filter(AdSet.platform_adset_id == insight["entity_id"])
            .first()
        )
        if not adset:
            continue
        _upsert_tiktok_metrics(
            db, adset.campaign_id, insight, insight["date"],
            ad_set_id=adset.id,
        )
        summary["metrics_synced"] += 1

    # --- Ad-level ---
    try:
        ad_metrics = fetch_ad_metrics(advertiser_id, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad metrics: {e}")
        ad_metrics = []

    for insight in ad_metrics:
        ad_obj = (
            db.query(Ad)
            .filter(Ad.platform_ad_id == insight["entity_id"])
            .first()
        )
        if not ad_obj:
            continue
        _upsert_tiktok_metrics(
            db, ad_obj.campaign_id, insight, insight["date"],
            ad_set_id=ad_obj.ad_set_id, ad_id=ad_obj.id,
        )
        summary["metrics_synced"] += 1

    db.commit()
    return summary


def sync_tiktok_account(
    db: Session,
    account: AdAccount,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """Sync campaigns, adgroups, ads, and metrics for one TikTok advertiser.

    `date_from` / `date_to` override the default rolling window (last 10 days).
    Returns a summary dict matching sync_meta_account / sync_google_account.
    """
    summary = {
        "campaigns_synced": 0,
        "adsets_synced": 0,
        "ads_synced": 0,
        "metrics_synced": 0,
        "ad_country_rows": 0,
        "errors": [],
    }

    if not settings.TIKTOK_ACCESS_TOKEN:
        summary["errors"].append("TIKTOK_ACCESS_TOKEN not configured")
        return summary

    advertiser_id = account.account_id

    # --- 1. Campaigns ---
    try:
        raw_campaigns = fetch_campaigns(advertiser_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch campaigns: {e}")
        return summary

    for raw in raw_campaigns:
        parsed = parse_campaign_metadata(raw["name"])
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
            if raw.get("start_date"):
                existing.start_date = raw["start_date"]
            if raw.get("end_date"):
                existing.end_date = raw["end_date"]
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(Campaign(
                account_id=account.id,
                platform="tiktok",
                platform_campaign_id=raw["platform_campaign_id"],
                name=raw["name"],
                status=raw["status"],
                objective=raw["objective"],
                daily_budget=raw["daily_budget"],
                lifetime_budget=raw["lifetime_budget"],
                ta=parsed["ta"],
                funnel_stage=parsed["funnel_stage"],
                start_date=raw.get("start_date"),
                end_date=raw.get("end_date"),
                raw_data=raw["raw_data"],
            ))
        summary["campaigns_synced"] += 1
    db.flush()

    # --- 2. Adgroups (= ad_sets) ---
    try:
        raw_adgroups = fetch_adgroups(advertiser_id)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch adgroups: {e}")
        raw_adgroups = []

    for raw in raw_adgroups:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == raw["campaign_id"])
            .first()
        )
        if not campaign:
            logger.warning(
                "TikTok campaign %s not found for adgroup %s, skipping",
                raw["campaign_id"], raw["platform_adset_id"],
            )
            continue

        # Country comes from the ISO prefix in the adgroup name — same
        # convention used for Meta adsets.
        parsed = parse_adset_metadata(raw["name"])

        existing = (
            db.query(AdSet)
            .filter(AdSet.platform_adset_id == raw["platform_adset_id"])
            .first()
        )
        if existing:
            existing.name = raw["name"]
            existing.status = raw["status"]
            existing.optimization_goal = raw["optimization_goal"]
            existing.billing_event = raw["billing_event"]
            existing.daily_budget = raw["daily_budget"]
            existing.lifetime_budget = raw["lifetime_budget"]
            existing.targeting = raw["targeting"]
            existing.country = parsed["country"]
            if raw.get("start_date"):
                existing.start_date = raw["start_date"]
            if raw.get("end_date"):
                existing.end_date = raw["end_date"]
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(AdSet(
                campaign_id=campaign.id,
                account_id=account.id,
                platform="tiktok",
                platform_adset_id=raw["platform_adset_id"],
                name=raw["name"],
                status=raw["status"],
                optimization_goal=raw["optimization_goal"],
                billing_event=raw["billing_event"],
                daily_budget=raw["daily_budget"],
                lifetime_budget=raw["lifetime_budget"],
                targeting=raw["targeting"],
                country=parsed["country"],
                start_date=raw.get("start_date"),
                end_date=raw.get("end_date"),
                raw_data=raw["raw_data"],
            ))
        summary["adsets_synced"] += 1
    db.flush()

    # --- 3. Ads ---
    try:
        raw_ads = fetch_ads(advertiser_id)
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
                "Adset/campaign missing for TikTok ad %s, skipping",
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
            existing.creative_id = raw["creative_id"]
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(Ad(
                ad_set_id=adset.id,
                campaign_id=campaign.id,
                account_id=account.id,
                platform="tiktok",
                platform_ad_id=raw["platform_ad_id"],
                name=raw["name"],
                status=raw["status"],
                creative_id=raw["creative_id"],
                raw_data=raw["raw_data"],
            ))
        summary["ads_synced"] += 1
    db.flush()

    # --- 4. Metrics window ---
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=SYNC_LOOKBACK_DAYS - 1)

    window = sync_tiktok_metrics_window(db, account, date_from, date_to)
    summary["metrics_synced"] = window["metrics_synced"]
    summary["ad_country_rows"] = window["ad_country_rows"]
    if window["errors"]:
        summary["errors"].extend(window["errors"])

    logger.info(
        "TikTok sync complete for advertiser %s: %d campaigns, %d adgroups, "
        "%d ads, %d metrics rows",
        advertiser_id,
        summary["campaigns_synced"],
        summary["adsets_synced"],
        summary["ads_synced"],
        summary["metrics_synced"],
    )
    return summary


# ---------------------------------------------------------- account upsert ---


def register_tiktok_advertisers(
    db: Session,
    advertiser_ids: list[str],
    branch: str | None = None,
) -> dict:
    """Pull info from TikTok and upsert ad_accounts rows.

    `branch`: optional override. If provided, the account_name is suffixed
    with the branch token so BRANCH_ACCOUNT_MAP substring matching works
    (e.g. branch="Saigon" → "Meander Saigon TikTok"). When omitted, we keep
    the raw advertiser name from TikTok — caller is responsible for ensuring
    it already contains a recognised branch substring.
    """
    from app.core.branches import BRANCH_ACCOUNT_MAP

    summary = {"created": 0, "updated": 0, "errors": [], "accounts": []}

    if not advertiser_ids:
        return summary

    try:
        info_rows = fetch_advertiser_info([str(x) for x in advertiser_ids])
    except TikTokAPIError as e:
        summary["errors"].append(str(e))
        return summary

    info_by_id = {str(row.get("id") or row.get("advertiser_id")): row for row in info_rows}

    for adv_id in advertiser_ids:
        adv_id = str(adv_id)
        info = info_by_id.get(adv_id)
        if not info:
            summary["errors"].append(f"Advertiser {adv_id} not accessible to current token")
            continue

        raw_name = info.get("name") or f"TikTok {adv_id}"
        currency = (info.get("currency") or "VND").upper()

        # Resolve branch → ensure the saved name contains a substring that
        # BRANCH_ACCOUNT_MAP can match. When branch is given but the raw name
        # doesn't already contain one of the branch's patterns, prepend
        # "Meander <branch>" so the dashboards' branch filter works.
        account_name = raw_name
        if branch:
            patterns = BRANCH_ACCOUNT_MAP.get(branch, [branch])
            already_matches = any(p.lower() in raw_name.lower() for p in patterns)
            if not already_matches:
                # Pick the canonical pattern (first entry) to prepend.
                account_name = f"{patterns[0]} TikTok — {raw_name}"

        existing = (
            db.query(AdAccount)
            .filter(AdAccount.platform == "tiktok", AdAccount.account_id == adv_id)
            .first()
        )
        if existing:
            existing.account_name = account_name
            existing.currency = currency
            existing.is_active = True
            summary["updated"] += 1
        else:
            db.add(AdAccount(
                platform="tiktok",
                account_id=adv_id,
                account_name=account_name,
                currency=currency,
                is_active=True,
            ))
            summary["created"] += 1

        summary["accounts"].append({
            "advertiser_id": adv_id,
            "account_name": account_name,
            "currency": currency,
        })

    db.commit()
    return summary
