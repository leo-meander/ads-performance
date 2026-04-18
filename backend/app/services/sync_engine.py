"""Sync engine: orchestrates fetching data from ad platforms and upserting into DB."""

import logging
from datetime import date, datetime, timedelta, timezone

# Sync window: always pull last 10 days including today. Meta conversions
# (esp. pixel/CRM-matched bookings) can arrive a few days late, so a shorter
# window drops late attribution and under-reports revenue/ROAS.
SYNC_LOOKBACK_DAYS = 10

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services.parse_utils import parse_adset_metadata, parse_campaign_metadata
from app.services.meta_client import (
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

    metric_fields = {
        "spend": insight["spend"],
        "impressions": insight["impressions"],
        "clicks": insight["clicks"],
        "ctr": insight["ctr"],
        "conversions": insight["conversions"],
        "revenue": insight["revenue"],
        "roas": insight["roas"],
        "cpa": insight["cpa"],
        "cpc": insight["cpc"],
        "frequency": insight["frequency"],
        "add_to_cart": insight.get("add_to_cart", 0),
        "checkouts": insight.get("checkouts", 0),
        "searches": insight.get("searches", 0),
        "leads": insight.get("leads", 0),
        "landing_page_views": insight.get("landing_page_views", 0),
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


def sync_meta_account(db: Session, account: AdAccount) -> dict:
    """Sync campaigns, ad sets, ads, and metrics for a single Meta ad account.

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
            campaign = Campaign(
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
            ad = Ad(
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
        summary["ads_synced"] += 1

    db.flush()  # ensure ad IDs are available

    # Always pull last 14 days including today — conversions arrive late.
    today = date.today()
    date_from = today - timedelta(days=SYNC_LOOKBACK_DAYS - 1)
    date_to = today

    # --- 4. Fetch and upsert campaign-level metrics ---
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
            date.fromisoformat(insight["date"])
            if isinstance(insight["date"], str)
            else insight["date"]
        )
        _upsert_metrics_row(db, campaign.id, insight, insight_date)
        summary["metrics_synced"] += 1

    # --- 5. Fetch and upsert ad-set-level metrics ---
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
            date.fromisoformat(insight["date"])
            if isinstance(insight["date"], str)
            else insight["date"]
        )
        _upsert_metrics_row(db, adset.campaign_id, insight, insight_date, ad_set_id=adset.id)
        summary["metrics_synced"] += 1

    # --- 6. Fetch and upsert ad-level metrics ---
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
            date.fromisoformat(insight["date"])
            if isinstance(insight["date"], str)
            else insight["date"]
        )
        _upsert_metrics_row(
            db, ad_obj.campaign_id, insight, insight_date,
            ad_set_id=ad_obj.ad_set_id, ad_id=ad_obj.id,
        )
        summary["metrics_synced"] += 1

    db.commit()

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


def sync_all_platforms(db: Session) -> list[dict]:
    """Sync all active ad accounts across all platforms.

    Currently only Meta is implemented (Phase 1).
    """
    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    results = []

    for account in accounts:
        if account.platform == "meta":
            result = sync_meta_account(db, account)
            results.append({
                "account_id": str(account.id),
                "account_name": account.account_name,
                "platform": account.platform,
                **result,
            })
        elif account.platform == "google":
            from app.services.google_sync_engine import sync_google_account
            result = sync_google_account(db, account)
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
