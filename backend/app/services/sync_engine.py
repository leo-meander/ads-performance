"""Sync engine: orchestrates fetching data from ad platforms and upserting into DB."""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

# Sync window: always pull last 10 days including today. Meta conversions
# (esp. pixel/CRM-matched bookings) can arrive a few days late, so a shorter
# window drops late attribution and under-reports revenue/ROAS.
SYNC_LOOKBACK_DAYS = 10

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services.changelog import log_change
from app.services.parse_utils import parse_adset_metadata, parse_campaign_metadata
from app.services.meta_client import (
    fetch_ad_country_insights,
    fetch_ad_insights,
    fetch_ad_set_insights,
    fetch_ad_sets,
    fetch_ads,
    fetch_campaign_insights,
    fetch_campaigns,
)
from app.services.rule_engine import evaluate_all_rules
from app.services.creative_service import auto_classify_all_combos
from app.services.creative_sync import sync_creative_library_for_account
from app.services.angle_assign_service import assign_angles_for_new_combos

logger = logging.getLogger(__name__)


def _upsert_metrics_row(
    db: Session,
    campaign_id: str,
    insight: dict,
    insight_date: date,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
) -> None:
    """Upsert a single metrics row at any hierarchy level."""
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

    # Defensive cap on CTR (Meta occasionally returns >100 due to tracking lag).
    # Column is NUMERIC(8,6) with max absolute value < 100.
    raw_ctr = insight.get("ctr") or 0
    safe_ctr = min(float(raw_ctr), 99.999999) if raw_ctr else 0
    metric_fields = {
        "spend": insight["spend"],
        "impressions": insight["impressions"],
        "clicks": insight["clicks"],
        "link_clicks": insight.get("link_clicks", 0),
        "ctr": safe_ctr,
        "conversions": insight["conversions"],
        "revenue": insight["revenue"],
        "revenue_website": insight.get("revenue_website", insight["revenue"]),
        "revenue_offline": insight.get("revenue_offline", 0),
        "roas": insight["roas"],
        "cpa": insight["cpa"],
        "cpc": insight["cpc"],
        "frequency": insight["frequency"],
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
        metric = MetricsCache(
            campaign_id=campaign_id,
            ad_set_id=ad_set_id,
            ad_id=ad_id,
            platform="meta",
            date=insight_date,
            **metric_fields,
        )
        db.add(metric)


def sync_meta_metrics_window(
    db: Session,
    account: AdAccount,
    date_from: date,
    date_to: date,
) -> dict:
    """Re-pull campaign / ad-set / ad insights + ad×country for a date window.

    Used by the regular sync (last-10-day rolling window) and by the historical
    backfill endpoint (chunked 30-day windows over N months). Assumes entities
    (campaigns, ad sets, ads) are already in the DB — only metrics are written.
    """
    meta_account_id = account.account_id if account.account_id.startswith("act_") else f"act_{account.account_id}"
    access_token = account.access_token_enc
    summary = {"metrics_synced": 0, "ad_country_rows": 0, "errors": []}

    if not access_token:
        summary["errors"].append("No access token configured for this account")
        return summary

    # --- Campaign-level insights ---
    try:
        raw_insights = fetch_campaign_insights(meta_account_id, access_token, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch campaign insights: {e}")
        raw_insights = []

    for insight in raw_insights:
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
        _upsert_metrics_row(db, campaign.id, insight, insight_date)
        summary["metrics_synced"] += 1

    # --- Ad-set-level insights ---
    try:
        adset_insights = fetch_ad_set_insights(meta_account_id, access_token, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad-set insights: {e}")
        adset_insights = []

    for insight in adset_insights:
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
        _upsert_metrics_row(db, adset.campaign_id, insight, insight_date, ad_set_id=adset.id)
        summary["metrics_synced"] += 1

    # --- Ad-level insights ---
    try:
        ad_insights = fetch_ad_insights(meta_account_id, access_token, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad insights: {e}")
        ad_insights = []

    for insight in ad_insights:
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
        _upsert_metrics_row(
            db, ad_obj.campaign_id, insight, insight_date,
            ad_set_id=ad_obj.ad_set_id, ad_id=ad_obj.id,
        )
        summary["metrics_synced"] += 1

    db.commit()

    # --- Ad × country breakdown for Booking-from-Ads matching ---
    try:
        country_insights = fetch_ad_country_insights(meta_account_id, access_token, date_from, date_to)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad×country insights: {e}")
        country_insights = []

    now = datetime.now(timezone.utc)
    for insight in country_insights:
        platform_ad_id = insight.get("entity_id")
        country = insight.get("country")
        if not platform_ad_id or not country:
            continue
        ad_obj = (
            db.query(Ad)
            .filter(Ad.platform_ad_id == platform_ad_id)
            .first()
        )
        if not ad_obj:
            continue
        insight_date = (
            date.fromisoformat(insight["date"]) if isinstance(insight["date"], str) else insight["date"]
        )
        existing = (
            db.query(AdCountryMetric)
            .filter(
                AdCountryMetric.ad_id == ad_obj.id,
                AdCountryMetric.date == insight_date,
                AdCountryMetric.country == country,
            )
            .first()
        )
        values = {
            "spend": insight.get("spend") or 0,
            "impressions": insight.get("impressions") or 0,
            "clicks": insight.get("clicks") or 0,
            "revenue_website": insight.get("revenue_website") or 0,
            "revenue_offline": insight.get("revenue_offline") or 0,
            "conversions_website": insight.get("conversions") or 0,
            "conversions_offline": insight.get("conversions_offline") or 0,
        }
        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
            existing.updated_at = now
        else:
            db.add(AdCountryMetric(
                platform="meta",
                campaign_id=ad_obj.campaign_id,
                ad_id=ad_obj.id,
                date=insight_date,
                country=country,
                **values,
            ))
        summary["ad_country_rows"] += 1

    db.commit()
    return summary


def sync_meta_account(
    db: Session,
    account: AdAccount,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """Sync campaigns, ad sets, ads, and metrics for a single Meta ad account.

    `date_from` / `date_to` override the default rolling window (last 10 days).
    Returns summary dict with counts.
    """
    meta_account_id = account.account_id if account.account_id.startswith("act_") else f"act_{account.account_id}"
    access_token = account.access_token_enc
    summary = {
        "campaigns_synced": 0,
        "adsets_synced": 0,
        "ads_synced": 0,
        "metrics_synced": 0,
        "materials_created": 0,
        "copies_created": 0,
        "combos_created": 0,
        "errors": [],
    }

    if not access_token:
        summary["errors"].append("No access token configured for this account")
        return summary

    # --- 1. Fetch and upsert campaigns ---
    try:
        raw_campaigns = fetch_campaigns(meta_account_id, access_token)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch campaigns: {e}")
        return summary

    for raw in raw_campaigns:
        # Parse TA and funnel stage from campaign name
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
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            new_id = str(uuid.uuid4())
            campaign = Campaign(
                id=new_id,
                account_id=account.id,
                platform="meta",
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
            )
            db.add(campaign)
            log_change(
                db,
                category="ad_creation",
                title=f"Campaign created: {raw['name']}"[:200],
                source="auto",
                triggered_by="system",
                occurred_at=raw.get("platform_created_at") or datetime.now(timezone.utc),
                description=f"New Meta campaign synced (objective={raw.get('objective') or '?'})",
                platform="meta",
                account_id=account.id,
                campaign_id=new_id,
                after_value={
                    "platform_campaign_id": raw["platform_campaign_id"],
                    "objective": raw.get("objective"),
                    "status": raw.get("status"),
                },
            )
        summary["campaigns_synced"] += 1

    db.flush()  # ensure campaign IDs are available

    # --- 2. Fetch and upsert ad sets ---
    try:
        raw_adsets = fetch_ad_sets(meta_account_id, access_token)
    except Exception as e:
        summary["errors"].append(f"Failed to fetch ad sets: {e}")
        raw_adsets = []

    for raw in raw_adsets:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.platform_campaign_id == raw["campaign_id"])
            .first()
        )
        if not campaign:
            logger.warning("Campaign %s not found for ad set %s, skipping", raw["campaign_id"], raw["platform_adset_id"])
            continue

        # Parse country from adset name
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
            existing.raw_data = raw["raw_data"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            adset = AdSet(
                campaign_id=campaign.id,
                account_id=account.id,
                platform="meta",
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
            )
            db.add(adset)
        summary["adsets_synced"] += 1

    db.flush()  # ensure ad set IDs are available

    # --- 3. Fetch and upsert ads ---
    try:
        raw_ads = fetch_ads(meta_account_id, access_token)
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
            logger.warning("Ad set or campaign not found for ad %s, skipping", raw["platform_ad_id"])
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
            new_id = str(uuid.uuid4())
            ad = Ad(
                id=new_id,
                ad_set_id=adset.id,
                campaign_id=campaign.id,
                account_id=account.id,
                platform="meta",
                platform_ad_id=raw["platform_ad_id"],
                name=raw["name"],
                status=raw["status"],
                creative_id=raw["creative_id"],
                raw_data=raw["raw_data"],
            )
            db.add(ad)
            log_change(
                db,
                category="ad_creation",
                title=f"Ad created: {raw['name']}"[:200],
                source="auto",
                triggered_by="system",
                occurred_at=raw.get("platform_created_at") or datetime.now(timezone.utc),
                description=f"New Meta ad synced under campaign '{campaign.name}'",
                platform="meta",
                account_id=account.id,
                campaign_id=campaign.id,
                ad_set_id=adset.id,
                ad_id=new_id,
                after_value={
                    "platform_ad_id": raw["platform_ad_id"],
                    "creative_id": raw.get("creative_id"),
                    "status": raw.get("status"),
                },
            )
        summary["ads_synced"] += 1

    db.flush()  # ensure ad IDs are available

    # Default rolling window: last SYNC_LOOKBACK_DAYS including today —
    # conversions (esp. pixel/CRM-matched bookings) arrive a few days late.
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=SYNC_LOOKBACK_DAYS - 1)

    # --- 4-6b. Metrics + ad×country for the window ---
    window_summary = sync_meta_metrics_window(db, account, date_from, date_to)
    summary["metrics_synced"] = window_summary["metrics_synced"]
    summary["ad_country_rows"] = window_summary["ad_country_rows"]
    if window_summary["errors"]:
        summary["errors"].extend(window_summary["errors"])

    # --- 7. Upsert creative library (materials, copies, combos) from Meta ad creatives ---
    try:
        creative_summary = sync_creative_library_for_account(db, account)
        summary["materials_created"] = creative_summary.get("materials_created", 0)
        summary["copies_created"] = creative_summary.get("copies_created", 0)
        summary["combos_created"] = creative_summary.get("combos_created", 0)
        if creative_summary.get("errors"):
            summary["errors"].extend(creative_summary["errors"])
    except Exception as e:
        logger.exception("Creative library sync failed for account %s", account.account_id)
        summary["errors"].append(f"Creative library sync failed: {e}")

    logger.info(
        "Meta sync complete for account %s: %d campaigns, %d ad sets, %d ads, %d metrics, "
        "%d materials, %d copies, %d combos",
        account.account_id,
        summary["campaigns_synced"],
        summary["adsets_synced"],
        summary["ads_synced"],
        summary["metrics_synced"],
        summary["materials_created"],
        summary["copies_created"],
        summary["combos_created"],
    )
    return summary


def sync_all_platforms(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Sync all active ad accounts across all platforms.

    `date_from` / `date_to` override the per-account default rolling window.
    """
    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    results = []

    for account in accounts:
        if account.platform == "meta":
            result = sync_meta_account(db, account, date_from=date_from, date_to=date_to)
            results.append({
                "account_id": str(account.id),
                "account_name": account.account_name,
                "platform": account.platform,
                **result,
            })
        elif account.platform == "google":
            from app.services.google_sync_engine import sync_google_account
            result = sync_google_account(db, account, date_from=date_from, date_to=date_to)
            results.append({
                "account_id": str(account.id),
                "account_name": account.account_name,
                "platform": account.platform,
                **result,
            })
        # Phase 8: TikTok sync will be added here

    # After sync: auto-classify creative verdicts
    try:
        auto_classify_all_combos(db)
    except Exception:
        logger.exception("Auto-classify combos failed after sync")

    # After sync: auto-assign angle + keypoints to new combos (incremental)
    try:
        summary = assign_angles_for_new_combos(db)
        if summary.get("updated", 0) > 0:
            logger.info("Angle assignment: %s", summary)
    except Exception:
        logger.exception("Angle/keypoint auto-assign failed after sync")

    # After sync: evaluate automation rules
    try:
        rule_results = evaluate_all_rules(db)
        total_actions = sum(r.get("actions_taken", 0) for r in rule_results)
        if total_actions > 0:
            logger.info("Rule evaluation complete: %d actions taken", total_actions)
    except Exception:
        logger.exception("Rule evaluation failed after sync")

    return results
