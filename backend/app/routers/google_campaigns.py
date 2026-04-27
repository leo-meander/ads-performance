"""Google Ads API endpoints.

Provides Google-specific views for PMax asset groups, Search RSA ads,
and a manual Google-only sync trigger.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.google_asset import GoogleAsset
from app.models.google_asset_group import GoogleAssetGroup
from app.models.metrics import MetricsCache
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _ok(data):
    return {
        "success": True,
        "data": data,
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _err(msg: str, status: int = 400):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "data": None,
            "error": msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ── Google Campaigns ────────────────────────────────────────


@router.get("/google/campaigns")
def list_google_campaigns(
    campaign_type: str | None = Query(None, description="Filter: PERFORMANCE_MAX, SEARCH, DISPLAY"),
    status: str | None = Query(None),
    account_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """List all Google Ads campaigns."""
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "google_ads", requested_account_id=account_id
        )
        if not ok:
            return _err(err, 403)
        q = db.query(Campaign).filter(Campaign.platform == "google")
        if campaign_type:
            q = q.filter(Campaign.objective == campaign_type)
        if status:
            q = q.filter(Campaign.status == status)
        if account_id:
            q = q.filter(Campaign.account_id == account_id)
        elif scoped_ids is not None:
            q = q.filter(Campaign.account_id.in_(scoped_ids or ["__no_match__"]))

        total = q.count()
        campaigns = q.order_by(Campaign.name).offset(offset).limit(limit).all()

        return _ok({
            "campaigns": [
                {
                    "id": c.id,
                    "account_id": c.account_id,
                    "name": c.name,
                    "status": c.status,
                    "campaign_type": c.objective,
                    "daily_budget": float(c.daily_budget) if c.daily_budget else None,
                    "ta": c.ta,
                    "funnel_stage": c.funnel_stage,
                    "start_date": c.start_date.isoformat() if c.start_date else None,
                    "end_date": c.end_date.isoformat() if c.end_date else None,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in campaigns
            ],
            "total": total,
        })
    except Exception as e:
        return _err(str(e), 500)


@router.get("/google/campaigns/{campaign_id}")
def get_google_campaign(
    campaign_id: str,
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Get Google campaign detail."""
    try:
        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id, Campaign.platform == "google")
            .first()
        )
        if not campaign:
            return _err("Campaign not found", 404)
        ok, _ids, err = scoped_account_ids(
            db, current_user, "google_ads", requested_account_id=campaign.account_id
        )
        if not ok:
            return _err(err, 403)

        return _ok({
            "id": campaign.id,
            "account_id": campaign.account_id,
            "name": campaign.name,
            "status": campaign.status,
            "campaign_type": campaign.objective,
            "daily_budget": float(campaign.daily_budget) if campaign.daily_budget else None,
            "ta": campaign.ta,
            "funnel_stage": campaign.funnel_stage,
            "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
            "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
            "raw_data": campaign.raw_data,
        })
    except Exception as e:
        return _err(str(e), 500)


@router.get("/google/campaigns/{campaign_id}/ad-groups")
def get_campaign_ad_groups(
    campaign_id: str,
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Get ad groups for a Google Search campaign."""
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "google_ads", requested_account_id=campaign.account_id
            )
            if not ok:
                return _err(err, 403)
        ad_groups = (
            db.query(AdSet)
            .filter(AdSet.campaign_id == campaign_id, AdSet.platform == "google")
            .order_by(AdSet.name)
            .all()
        )
        return _ok({
            "ad_groups": [
                {
                    "id": ag.id,
                    "name": ag.name,
                    "status": ag.status,
                    "country": ag.country,
                }
                for ag in ad_groups
            ],
            "total": len(ad_groups),
        })
    except Exception as e:
        return _err(str(e), 500)


@router.get("/google/campaigns/{campaign_id}/metrics")
def get_campaign_metrics(
    campaign_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Get metrics for a Google campaign."""
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign:
            ok, _ids, err = scoped_account_ids(
                db, current_user, "google_ads", requested_account_id=campaign.account_id
            )
            if not ok:
                return _err(err, 403)
        q = db.query(MetricsCache).filter(
            MetricsCache.campaign_id == campaign_id,
            MetricsCache.platform == "google",
            MetricsCache.ad_set_id.is_(None),
            MetricsCache.ad_id.is_(None),
        )
        if date_from:
            q = q.filter(MetricsCache.date >= date_from)
        if date_to:
            q = q.filter(MetricsCache.date <= date_to)

        metrics = q.order_by(MetricsCache.date).all()
        return _ok({
            "metrics": [
                {
                    "date": m.date.isoformat(),
                    "spend": float(m.spend) if m.spend else 0,
                    "impressions": m.impressions,
                    "clicks": m.clicks,
                    "ctr": float(m.ctr) if m.ctr else 0,
                    "conversions": m.conversions,
                    "revenue": float(m.revenue) if m.revenue else 0,
                    "roas": float(m.roas) if m.roas else 0,
                    "cpa": float(m.cpa) if m.cpa else None,
                    "cpc": float(m.cpc) if m.cpc else None,
                }
                for m in metrics
            ],
        })
    except Exception as e:
        return _err(str(e), 500)


# ── PMax Asset Groups ───────────────────────────────────────


@router.get("/google/asset-groups")
def list_asset_groups(
    campaign_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """List all PMax asset groups."""
    try:
        q = db.query(GoogleAssetGroup)
        if campaign_id:
            q = q.filter(GoogleAssetGroup.campaign_id == campaign_id)
        if status:
            q = q.filter(GoogleAssetGroup.status == status)

        total = q.count()
        groups = q.order_by(GoogleAssetGroup.name).offset(offset).limit(limit).all()

        # Count assets per group
        result = []
        for g in groups:
            asset_count = (
                db.query(GoogleAsset)
                .filter(GoogleAsset.asset_group_id == g.id)
                .count()
            )
            campaign = db.query(Campaign).filter(Campaign.id == g.campaign_id).first()
            result.append({
                "id": g.id,
                "campaign_id": g.campaign_id,
                "campaign_name": campaign.name if campaign else None,
                "name": g.name,
                "status": g.status,
                "final_urls": g.final_urls,
                "asset_count": asset_count,
            })

        return _ok({"asset_groups": result, "total": total})
    except Exception as e:
        return _err(str(e), 500)


@router.get("/google/asset-groups/{group_id}")
def get_asset_group(
    group_id: str,
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Get asset group detail with all assets."""
    try:
        group = db.query(GoogleAssetGroup).filter(GoogleAssetGroup.id == group_id).first()
        if not group:
            return _err("Asset group not found", 404)

        assets = (
            db.query(GoogleAsset)
            .filter(GoogleAsset.asset_group_id == group_id)
            .order_by(GoogleAsset.asset_type)
            .all()
        )
        campaign = db.query(Campaign).filter(Campaign.id == group.campaign_id).first()

        return _ok({
            "id": group.id,
            "campaign_id": group.campaign_id,
            "campaign_name": campaign.name if campaign else None,
            "name": group.name,
            "status": group.status,
            "final_urls": group.final_urls,
            "assets": [
                {
                    "id": a.id,
                    "asset_type": a.asset_type,
                    "text_content": a.text_content,
                    "image_url": a.image_url,
                    "performance_label": a.performance_label,
                }
                for a in assets
            ],
        })
    except Exception as e:
        return _err(str(e), 500)


@router.get("/google/asset-groups/{group_id}/assets")
def list_assets(
    group_id: str,
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """List assets for an asset group."""
    try:
        assets = (
            db.query(GoogleAsset)
            .filter(GoogleAsset.asset_group_id == group_id)
            .order_by(GoogleAsset.asset_type)
            .all()
        )
        return _ok({
            "assets": [
                {
                    "id": a.id,
                    "asset_type": a.asset_type,
                    "text_content": a.text_content,
                    "image_url": a.image_url,
                    "performance_label": a.performance_label,
                    "raw_data": a.raw_data,
                }
                for a in assets
            ],
            "total": len(assets),
        })
    except Exception as e:
        return _err(str(e), 500)


# ── Google Ads (RSA) ────────────────────────────────────────


@router.get("/google/ads/{ad_id}")
def get_google_ad(
    ad_id: str,
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Get a single Google ad detail (RSA with headlines/descriptions)."""
    try:
        ad = (
            db.query(Ad)
            .filter(Ad.id == ad_id, Ad.platform == "google")
            .first()
        )
        if not ad:
            return _err("Ad not found", 404)

        raw = ad.raw_data or {}
        return _ok({
            "id": ad.id,
            "name": ad.name,
            "status": ad.status,
            "ad_type": raw.get("ad_type", "UNKNOWN"),
            "headlines": raw.get("headlines", []),
            "descriptions": raw.get("descriptions", []),
            "campaign_id": ad.campaign_id,
            "ad_set_id": ad.ad_set_id,
            "raw_data": ad.raw_data,
        })
    except Exception as e:
        return _err(str(e), 500)


# ── Google Sync Trigger ─────────────────────────────────────


@router.post("/google/sync")
def trigger_google_sync(
    account_id: str | None = Query(None, description="Sync specific account only"),
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Trigger a manual Google Ads sync."""
    try:
        from app.services.google_sync_engine import sync_google_account

        q = db.query(AdAccount).filter(
            AdAccount.platform == "google",
            AdAccount.is_active.is_(True),
        )
        if account_id:
            q = q.filter(AdAccount.id == account_id)

        accounts = q.all()
        if not accounts:
            return _err("No active Google Ads accounts found", 404)

        results = []
        for account in accounts:
            result = sync_google_account(db, account)
            results.append({
                "account_id": str(account.id),
                "account_name": account.account_name,
                **result,
            })

        return _ok({"sync_results": results})
    except Exception as e:
        return _err(str(e), 500)


# ── Google Dashboard Summary ────────────────────────────────


@router.get("/google/dashboard")
def google_dashboard(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Get Google Ads dashboard KPIs."""
    try:
        from sqlalchemy import func

        q = db.query(
            func.sum(MetricsCache.spend).label("total_spend"),
            func.sum(MetricsCache.impressions).label("total_impressions"),
            func.sum(MetricsCache.clicks).label("total_clicks"),
            func.sum(MetricsCache.conversions).label("total_conversions"),
            func.sum(MetricsCache.revenue).label("total_revenue"),
        ).filter(
            MetricsCache.platform == "google",
            MetricsCache.ad_set_id.is_(None),
            MetricsCache.ad_id.is_(None),
        )
        if date_from:
            q = q.filter(MetricsCache.date >= date_from)
        if date_to:
            q = q.filter(MetricsCache.date <= date_to)

        row = q.first()

        total_spend = float(row.total_spend or 0)
        total_impressions = int(row.total_impressions or 0)
        total_clicks = int(row.total_clicks or 0)
        total_conversions = int(row.total_conversions or 0)
        total_revenue = float(row.total_revenue or 0)

        # Campaign counts by type
        pmax_count = (
            db.query(Campaign)
            .filter(Campaign.platform == "google", Campaign.objective == "PERFORMANCE_MAX")
            .count()
        )
        search_count = (
            db.query(Campaign)
            .filter(Campaign.platform == "google", Campaign.objective == "SEARCH")
            .count()
        )
        total_campaigns = (
            db.query(Campaign).filter(Campaign.platform == "google").count()
        )

        return _ok({
            "kpis": {
                "total_spend": total_spend,
                "total_impressions": total_impressions,
                "total_clicks": total_clicks,
                "total_conversions": total_conversions,
                "total_revenue": total_revenue,
                "roas": total_revenue / total_spend if total_spend > 0 else 0,
                "ctr": (total_clicks / total_impressions * 100) if total_impressions > 0 else 0,
                "cpa": total_spend / total_conversions if total_conversions > 0 else None,
            },
            "campaign_counts": {
                "total": total_campaigns,
                "performance_max": pmax_count,
                "search": search_count,
                "other": total_campaigns - pmax_count - search_count,
            },
        })
    except Exception as e:
        return _err(str(e), 500)


# ── Ad Group Ads ───────────────────────────────────────────


@router.get("/google/ad-groups/{ad_group_id}/ads")
def list_ad_group_ads(
    ad_group_id: str,
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """List RSA ads for a Google ad group."""
    try:
        ads = (
            db.query(Ad)
            .filter(Ad.ad_set_id == ad_group_id, Ad.platform == "google")
            .order_by(Ad.name)
            .all()
        )
        return _ok({
            "ads": [
                {
                    "id": a.id,
                    "name": a.name,
                    "status": a.status,
                    "ad_type": (a.raw_data or {}).get("ad_type", "UNKNOWN"),
                    "headlines": (a.raw_data or {}).get("headlines", []),
                    "descriptions": (a.raw_data or {}).get("descriptions", []),
                }
                for a in ads
            ],
            "total": len(ads),
        })
    except Exception as e:
        return _err(str(e), 500)


# ── Write Operations ───────────────────────────────────────


def _get_google_customer_id(db: Session, account_id: str) -> str:
    """Get the Google Ads customer ID for an account."""
    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if not account:
        raise ValueError("Account not found")
    return account.account_id.replace("-", "")


def _log_action(
    db: Session,
    action: str,
    campaign_id: str | None = None,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
    success: bool = True,
    error_message: str | None = None,
    action_params: dict | None = None,
) -> None:
    """Create immutable action log entry for manual Google actions."""
    log = ActionLog(
        rule_id=None,
        campaign_id=campaign_id,
        ad_set_id=ad_set_id,
        ad_id=ad_id,
        platform="google",
        action=action,
        action_params=action_params,
        triggered_by="manual",
        metrics_snapshot=None,
        success=success,
        error_message=error_message,
        executed_at=datetime.now(timezone.utc),
    )
    db.add(log)


@router.post("/google/campaigns/{campaign_id}/pause")
def pause_google_campaign(
    campaign_id: str,
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Pause a Google Ads campaign."""
    try:
        from app.services.google_actions import pause_campaign

        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id, Campaign.platform == "google")
            .first()
        )
        if not campaign:
            return _err("Campaign not found", 404)

        customer_id = _get_google_customer_id(db, campaign.account_id)
        pause_campaign(customer_id, campaign.platform_campaign_id)
        campaign.status = "PAUSED"
        campaign.updated_at = datetime.now(timezone.utc)
        _log_action(db, "pause_campaign", campaign_id=campaign.id)
        db.commit()
        return _ok({"id": campaign.id, "status": "PAUSED"})
    except Exception as e:
        _log_action(db, "pause_campaign", campaign_id=campaign_id, success=False, error_message=str(e))
        db.commit()
        return _err(str(e), 500)


@router.post("/google/campaigns/{campaign_id}/enable")
def enable_google_campaign(
    campaign_id: str,
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Enable a Google Ads campaign."""
    try:
        from app.services.google_actions import enable_campaign

        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id, Campaign.platform == "google")
            .first()
        )
        if not campaign:
            return _err("Campaign not found", 404)

        customer_id = _get_google_customer_id(db, campaign.account_id)
        enable_campaign(customer_id, campaign.platform_campaign_id)
        campaign.status = "ACTIVE"
        campaign.updated_at = datetime.now(timezone.utc)
        _log_action(db, "enable_campaign", campaign_id=campaign.id)
        db.commit()
        return _ok({"id": campaign.id, "status": "ACTIVE"})
    except Exception as e:
        _log_action(db, "enable_campaign", campaign_id=campaign_id, success=False, error_message=str(e))
        db.commit()
        return _err(str(e), 500)


@router.post("/google/campaigns/{campaign_id}/budget")
def update_google_campaign_budget(
    campaign_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Update a Google Ads campaign's daily budget."""
    try:
        from app.services.google_actions import update_campaign_budget

        daily_budget = body.get("daily_budget")
        if daily_budget is None or daily_budget <= 0:
            return _err("daily_budget must be a positive number")

        campaign = (
            db.query(Campaign)
            .filter(Campaign.id == campaign_id, Campaign.platform == "google")
            .first()
        )
        if not campaign:
            return _err("Campaign not found", 404)

        customer_id = _get_google_customer_id(db, campaign.account_id)
        new_budget_micros = int(daily_budget * 1_000_000)
        update_campaign_budget(customer_id, campaign.platform_campaign_id, new_budget_micros)

        old_budget = float(campaign.daily_budget) if campaign.daily_budget else 0
        campaign.daily_budget = daily_budget
        campaign.updated_at = datetime.now(timezone.utc)
        _log_action(
            db, "adjust_budget", campaign_id=campaign.id,
            action_params={"old_budget": old_budget, "new_budget": daily_budget},
        )
        db.commit()
        return _ok({"id": campaign.id, "daily_budget": daily_budget})
    except Exception as e:
        _log_action(
            db, "adjust_budget", campaign_id=campaign_id,
            success=False, error_message=str(e),
        )
        db.commit()
        return _err(str(e), 500)


@router.post("/google/ad-groups/{ad_group_id}/pause")
def pause_google_ad_group(
    ad_group_id: str,
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Pause a Google Ads ad group."""
    try:
        from app.services.google_actions import pause_ad_group

        adset = (
            db.query(AdSet)
            .filter(AdSet.id == ad_group_id, AdSet.platform == "google")
            .first()
        )
        if not adset:
            return _err("Ad group not found", 404)

        customer_id = _get_google_customer_id(db, adset.account_id)
        pause_ad_group(customer_id, adset.platform_adset_id)
        adset.status = "PAUSED"
        adset.updated_at = datetime.now(timezone.utc)
        _log_action(db, "pause_adset", campaign_id=adset.campaign_id, ad_set_id=adset.id)
        db.commit()
        return _ok({"id": adset.id, "status": "PAUSED"})
    except Exception as e:
        _log_action(db, "pause_adset", ad_set_id=ad_group_id, success=False, error_message=str(e))
        db.commit()
        return _err(str(e), 500)


@router.post("/google/ad-groups/{ad_group_id}/enable")
def enable_google_ad_group(
    ad_group_id: str,
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Enable a Google Ads ad group."""
    try:
        from app.services.google_actions import enable_ad_group

        adset = (
            db.query(AdSet)
            .filter(AdSet.id == ad_group_id, AdSet.platform == "google")
            .first()
        )
        if not adset:
            return _err("Ad group not found", 404)

        customer_id = _get_google_customer_id(db, adset.account_id)
        enable_ad_group(customer_id, adset.platform_adset_id)
        adset.status = "ACTIVE"
        adset.updated_at = datetime.now(timezone.utc)
        _log_action(db, "enable_adset", campaign_id=adset.campaign_id, ad_set_id=adset.id)
        db.commit()
        return _ok({"id": adset.id, "status": "ACTIVE"})
    except Exception as e:
        _log_action(db, "enable_adset", ad_set_id=ad_group_id, success=False, error_message=str(e))
        db.commit()
        return _err(str(e), 500)


@router.post("/google/ads/{ad_id}/pause")
def pause_google_ad(
    ad_id: str,
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Pause a Google Ads ad."""
    try:
        from app.services.google_actions import pause_ad

        ad = (
            db.query(Ad)
            .filter(Ad.id == ad_id, Ad.platform == "google")
            .first()
        )
        if not ad:
            return _err("Ad not found", 404)

        adset = db.query(AdSet).filter(AdSet.id == ad.ad_set_id).first()
        if not adset:
            return _err("Ad group not found for ad", 404)

        customer_id = _get_google_customer_id(db, ad.account_id)
        pause_ad(customer_id, adset.platform_adset_id, ad.platform_ad_id)
        ad.status = "PAUSED"
        ad.updated_at = datetime.now(timezone.utc)
        _log_action(db, "pause_ad", campaign_id=ad.campaign_id, ad_set_id=ad.ad_set_id, ad_id=ad.id)
        db.commit()
        return _ok({"id": ad.id, "status": "PAUSED"})
    except Exception as e:
        _log_action(db, "pause_ad", ad_id=ad_id, success=False, error_message=str(e))
        db.commit()
        return _err(str(e), 500)


@router.post("/google/ads/{ad_id}/enable")
def enable_google_ad(
    ad_id: str,
    current_user: User = Depends(require_section("google_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Enable a Google Ads ad."""
    try:
        from app.services.google_actions import enable_ad

        ad = (
            db.query(Ad)
            .filter(Ad.id == ad_id, Ad.platform == "google")
            .first()
        )
        if not ad:
            return _err("Ad not found", 404)

        adset = db.query(AdSet).filter(AdSet.id == ad.ad_set_id).first()
        if not adset:
            return _err("Ad group not found for ad", 404)

        customer_id = _get_google_customer_id(db, ad.account_id)
        enable_ad(customer_id, adset.platform_adset_id, ad.platform_ad_id)
        ad.status = "ACTIVE"
        ad.updated_at = datetime.now(timezone.utc)
        _log_action(db, "enable_ad", campaign_id=ad.campaign_id, ad_set_id=ad.ad_set_id, ad_id=ad.id)
        db.commit()
        return _ok({"id": ad.id, "status": "ACTIVE"})
    except Exception as e:
        _log_action(db, "enable_ad", ad_id=ad_id, success=False, error_message=str(e))
        db.commit()
        return _err(str(e), 500)


# ── Insights (realtime GAQL) ────────────────────────────────


def _parse_date_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Default to last 30 days if not provided."""
    today = date.today()
    df = date.fromisoformat(date_from) if date_from else today - timedelta(days=29)
    dt = date.fromisoformat(date_to) if date_to else today
    return df, dt


def _resolve_campaign_for_insights(
    db: Session, campaign_id: str, current_user: User,
) -> tuple[Campaign | None, str | None, str | None, str | None]:
    """Validate campaign exists, user has access, return (campaign, customer_id, account_currency, error_msg)."""
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_id, Campaign.platform == "google")
        .first()
    )
    if not campaign:
        return None, None, None, "Campaign not found"

    ok, _ids, err = scoped_account_ids(
        db, current_user, "google_ads", requested_account_id=campaign.account_id
    )
    if not ok:
        return None, None, None, err

    account = db.query(AdAccount).filter(AdAccount.id == campaign.account_id).first()
    if not account:
        return None, None, None, "Account not found"

    customer_id = account.account_id.replace("-", "")
    return campaign, customer_id, account.currency or "VND", None


@router.get("/google/campaigns/{campaign_id}/insights/search-terms")
def get_search_terms_insight(
    campaign_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Search-term breakdown.

    Search campaigns: real user queries via search_term_view.
    PMax: bucketed category labels via campaign_search_term_insight.
    """
    try:
        from app.services import google_insights, google_insights_client

        campaign, customer_id, currency, err = _resolve_campaign_for_insights(db, campaign_id, current_user)
        if err:
            return _err(err, 404 if err == "Campaign not found" else 403)

        df, dt = _parse_date_range(date_from, date_to)

        if campaign.objective == "PERFORMANCE_MAX":
            categories = google_insights_client.fetch_pmax_search_categories(
                customer_id, campaign.platform_campaign_id, df, dt,
            )
            return _ok({
                "mode": "pmax_categories",
                "categories": categories,
                "currency": currency,
                "date_from": df.isoformat(),
                "date_to": dt.isoformat(),
            })

        terms = google_insights_client.fetch_search_terms(
            customer_id, campaign.platform_campaign_id, df, dt,
        )
        classified = google_insights.classify_search_terms(terms)
        return _ok({
            "mode": "search_terms",
            **classified,
            "currency": currency,
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        })
    except Exception as e:
        logger.exception("search-terms insight failed for %s", campaign_id)
        return _err(str(e), 500)


@router.get("/google/campaigns/{campaign_id}/insights/devices")
def get_devices_insight(
    campaign_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    try:
        from app.services import google_insights, google_insights_client

        campaign, customer_id, currency, err = _resolve_campaign_for_insights(db, campaign_id, current_user)
        if err:
            return _err(err, 404 if err == "Campaign not found" else 403)

        df, dt = _parse_date_range(date_from, date_to)
        rows = google_insights_client.fetch_device_metrics(customer_id, campaign.platform_campaign_id, df, dt)
        diagnosis = google_insights.diagnose_devices(rows)
        return _ok({
            **diagnosis,
            "currency": currency,
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        })
    except Exception as e:
        logger.exception("devices insight failed for %s", campaign_id)
        return _err(str(e), 500)


@router.get("/google/campaigns/{campaign_id}/insights/locations")
def get_locations_insight(
    campaign_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    try:
        from app.services import google_insights, google_insights_client

        campaign, customer_id, currency, err = _resolve_campaign_for_insights(db, campaign_id, current_user)
        if err:
            return _err(err, 404 if err == "Campaign not found" else 403)

        df, dt = _parse_date_range(date_from, date_to)
        rows = google_insights_client.fetch_location_metrics(customer_id, campaign.platform_campaign_id, df, dt)
        diagnosis = google_insights.diagnose_locations(rows)
        return _ok({
            **diagnosis,
            "currency": currency,
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        })
    except Exception as e:
        logger.exception("locations insight failed for %s", campaign_id)
        return _err(str(e), 500)


@router.get("/google/campaigns/{campaign_id}/insights/time-of-day")
def get_time_of_day_insight(
    campaign_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    try:
        from app.services import google_insights, google_insights_client

        campaign, customer_id, currency, err = _resolve_campaign_for_insights(db, campaign_id, current_user)
        if err:
            return _err(err, 404 if err == "Campaign not found" else 403)

        df, dt = _parse_date_range(date_from, date_to)
        rows = google_insights_client.fetch_hourly_metrics(customer_id, campaign.platform_campaign_id, df, dt)
        diagnosis = google_insights.diagnose_time_of_day(rows)
        return _ok({
            **diagnosis,
            "currency": currency,
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        })
    except Exception as e:
        logger.exception("time-of-day insight failed for %s", campaign_id)
        return _err(str(e), 500)


@router.post("/google/campaigns/{campaign_id}/insights/narrative")
def stream_combined_narrative_endpoint(
    campaign_id: str,
    body: dict = Body(...),
    current_user: User = Depends(require_section("google_ads")),
    db: Session = Depends(get_db),
):
    """Stream Claude-generated combined narrative.

    Client sends the already-fetched per-panel data so we don't refetch.
    Body: { search_terms, devices, locations, time_of_day, totals, date_range }
    Returns text/event-stream with `data: <json-encoded chunk>\\n\\n`.
    """
    from fastapi.responses import StreamingResponse

    from app.services.google_insights_ai import stream_combined_narrative

    campaign, _customer_id, currency, err = _resolve_campaign_for_insights(db, campaign_id, current_user)
    if err:
        return _err(err, 404 if err == "Campaign not found" else 403)

    payload = {
        "campaign": {
            "name": campaign.name,
            "type": campaign.objective,
            "ta": campaign.ta,
            "funnel_stage": campaign.funnel_stage,
            "currency": currency,
        },
        "date_range": body.get("date_range"),
        "totals": body.get("totals"),
        "search_terms": body.get("search_terms"),
        "pmax_categories": body.get("pmax_categories"),
        "devices": body.get("devices"),
        "locations": body.get("locations"),
        "time_of_day": body.get("time_of_day"),
    }

    def stream_sse():
        try:
            for chunk in stream_combined_narrative(payload):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            logger.exception("narrative stream failed for %s", campaign_id)
            yield f"event: error\ndata: {json.dumps(str(e))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
