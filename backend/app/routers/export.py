"""Export API endpoints with API key authentication.

Key management endpoints (/export/keys) require admin JWT (httpOnly cookie).
Data export endpoints (/export/*) require X-API-Key header.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.branches import (
    canonical_branch,
    get_account_ids_for_branches,
    resolve_branch_for_account_name,
)
from app.database import get_db
from app.dependencies.auth import require_role
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_country_metric import AdCountryMetric
from app.models.ad_material import AdMaterial
from app.models.api_key import ApiKey
from app.models.booking_match import BookingMatch
from app.models.budget import BudgetPlan
from app.models.campaign import Campaign
from app.models.keypoint import BranchKeypoint
from app.models.metrics import MetricsCache
from app.models.spy_saved_ad import SpySavedAd
from app.models.user import User
from app.services.budget_service import get_yearly_plan, list_monthly_splits
from app.services.export_auth import create_api_key, validate_api_key

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────
# API KEY MANAGEMENT  (admin JWT, not X-API-Key)
# ──────────────────────────────────────────────────────────────────────


class KeyCreate(BaseModel):
    name: str
    created_by: str | None = None


@router.post("/export/keys")
def create_key(
    body: KeyCreate,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    """Create a new API key. Returns plaintext ONCE. Admin only."""
    try:
        api_key, plaintext = create_api_key(
            db, body.name, body.created_by or current_user.email
        )
        db.commit()
        return _api_response(data={
            "id": str(api_key.id),
            "name": api_key.name,
            "key": plaintext,  # Shown once, never again
            "key_prefix": api_key.key_prefix,
            "created_by": api_key.created_by,
            "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/export/keys")
def list_keys(
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    """List API keys (no plaintext shown). Admin only."""
    try:
        keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
        return _api_response(data=[
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_active,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "daily_request_count": k.daily_request_count,
                "created_by": k.created_by,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.delete("/export/keys/{key_id}")
def deactivate_key(
    key_id: str,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    """Deactivate an API key (soft delete). Admin only."""
    try:
        api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        if not api_key:
            return _api_response(error="API key not found")
        api_key.is_active = False
        db.commit()
        return _api_response(data={"id": key_id, "deactivated": True})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ──────────────────────────────────────────────────────────────────────
# DATA EXPORTS  (X-API-Key)
# ──────────────────────────────────────────────────────────────────────


@router.get("/export/accounts")
def export_accounts(
    platform: str = Query(None, description="meta | google | tiktok"),
    branch: str = Query(
        None,
        description="Filter by canonical branch (case-insensitive): saigon|taipei|1948|oani|osaka|bread",
    ),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export ad accounts (branches)."""
    try:
        q = db.query(AdAccount).filter(AdAccount.is_active.is_(True))
        if platform:
            q = q.filter(AdAccount.platform == platform)
        if branch:
            canonical = canonical_branch(branch)
            if canonical is None:
                return _api_response(error=f"Unknown branch: {branch}")
            account_ids = get_account_ids_for_branches(db, [canonical])
            if not account_ids:
                return _api_response(data=[])
            q = q.filter(AdAccount.id.in_(account_ids))
        rows = q.order_by(AdAccount.account_name).all()
        return _api_response(data=[
            {
                "id": str(r.id),
                "platform": r.platform,
                "account_id": r.account_id,
                "account_name": r.account_name,
                "currency": r.currency,
                "branch": resolve_branch_for_account_name(r.account_name),
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/angles")
def export_angles(
    status: str = Query(None, description="WIN | TEST | LOSE"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export ad angles (global, branch_id NULL)."""
    try:
        q = db.query(AdAngle)
        if status:
            q = q.filter(AdAngle.status == status)
        rows = q.order_by(AdAngle.angle_id).all()
        return _api_response(data=[
            {
                "id": str(r.id),
                "angle_id": r.angle_id,
                "branch_id": str(r.branch_id) if r.branch_id else None,
                "angle_type": r.angle_type,
                "angle_explain": r.angle_explain,
                "hook_examples": r.hook_examples,
                "target_audience": r.target_audience,
                "angle_text": r.angle_text,
                "hook": r.hook,
                "status": r.status,
                "notes": r.notes,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/keypoints")
def export_keypoints(
    branch_id: str = Query(None),
    category: str = Query(None),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export branch keypoints."""
    try:
        q = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True))
        if branch_id:
            q = q.filter(BranchKeypoint.branch_id == branch_id)
        if category:
            q = q.filter(BranchKeypoint.category == category)
        rows = q.order_by(BranchKeypoint.branch_id, BranchKeypoint.category, BranchKeypoint.title).all()
        return _api_response(data=[
            {
                "id": str(r.id),
                "branch_id": str(r.branch_id),
                "category": r.category,
                "title": r.title,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/copies")
def export_copies(
    branch_id: str = Query(None),
    target_audience: str = Query(None),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export ad copies."""
    try:
        q = db.query(AdCopy)
        if branch_id:
            q = q.filter(AdCopy.branch_id == branch_id)
        if target_audience:
            q = q.filter(AdCopy.target_audience == target_audience)
        rows = q.order_by(AdCopy.copy_id).all()
        return _api_response(data=[
            {
                "id": str(r.id),
                "copy_id": r.copy_id,
                "branch_id": str(r.branch_id),
                "target_audience": r.target_audience,
                "angle_id": r.angle_id,
                "headline": r.headline,
                "body_text": r.body_text,
                "cta": r.cta,
                "language": r.language,
                "derived_verdict": r.derived_verdict,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/materials")
def export_materials(
    branch_id: str = Query(None),
    material_type: str = Query(None, description="image | video | carousel"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export ad materials (creative assets)."""
    try:
        q = db.query(AdMaterial)
        if branch_id:
            q = q.filter(AdMaterial.branch_id == branch_id)
        if material_type:
            q = q.filter(AdMaterial.material_type == material_type)
        rows = q.order_by(AdMaterial.material_id).all()
        return _api_response(data=[
            {
                "id": str(r.id),
                "material_id": r.material_id,
                "branch_id": str(r.branch_id),
                "material_type": r.material_type,
                "file_url": r.file_url,
                "description": r.description,
                "target_audience": r.target_audience,
                "derived_verdict": r.derived_verdict,
                "url_source": r.url_source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/combos")
def export_combos(
    branch_id: str = Query(None),
    verdict: str = Query(None, description="WIN | TEST | LOSE"),
    country: str = Query(None),
    target_audience: str = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export ad combos (creative combinations) with cached metrics."""
    try:
        q = db.query(AdCombo)
        if branch_id:
            q = q.filter(AdCombo.branch_id == branch_id)
        if verdict:
            q = q.filter(AdCombo.verdict == verdict)
        if country:
            q = q.filter(AdCombo.country == country)
        if target_audience:
            q = q.filter(AdCombo.target_audience == target_audience)

        total = q.count()
        rows = q.order_by(AdCombo.combo_id).offset(offset).limit(limit).all()

        return _api_response(data={
            "items": [
                {
                    "id": str(r.id),
                    "combo_id": r.combo_id,
                    "branch_id": str(r.branch_id),
                    "ad_name": r.ad_name,
                    "target_audience": r.target_audience,
                    "country": r.country,
                    "keypoint_ids": r.keypoint_ids,
                    "angle_id": r.angle_id,
                    "copy_id": r.copy_id,
                    "material_id": r.material_id,
                    "campaign_id": str(r.campaign_id) if r.campaign_id else None,
                    "verdict": r.verdict,
                    "verdict_source": r.verdict_source,
                    "verdict_notes": r.verdict_notes,
                    "spend": float(r.spend) if r.spend is not None else None,
                    "impressions": r.impressions,
                    "clicks": r.clicks,
                    "conversions": r.conversions,
                    "revenue": float(r.revenue) if r.revenue is not None else None,
                    "roas": float(r.roas) if r.roas is not None else None,
                    "cost_per_purchase": float(r.cost_per_purchase) if r.cost_per_purchase is not None else None,
                    "ctr": float(r.ctr) if r.ctr is not None else None,
                    "engagement": r.engagement,
                    "engagement_rate": float(r.engagement_rate) if r.engagement_rate is not None else None,
                    "video_plays": r.video_plays,
                    "thruplay": r.thruplay,
                    "video_p100": r.video_p100,
                    "hook_rate": float(r.hook_rate) if r.hook_rate is not None else None,
                    "thruplay_rate": float(r.thruplay_rate) if r.thruplay_rate is not None else None,
                    "video_complete_rate": float(r.video_complete_rate) if r.video_complete_rate is not None else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/campaigns")
def export_campaigns(
    platform: str = Query(None, description="meta | google | tiktok"),
    account_id: str = Query(None),
    status: str = Query(None),
    ta: str = Query(None),
    funnel_stage: str = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export campaigns (all platforms)."""
    try:
        q = db.query(Campaign)
        if platform:
            q = q.filter(Campaign.platform == platform)
        if account_id:
            q = q.filter(Campaign.account_id == account_id)
        if status:
            q = q.filter(Campaign.status == status)
        if ta:
            q = q.filter(Campaign.ta == ta)
        if funnel_stage:
            q = q.filter(Campaign.funnel_stage == funnel_stage)

        total = q.count()
        rows = q.order_by(Campaign.name).offset(offset).limit(limit).all()

        return _api_response(data={
            "items": [
                {
                    "id": str(r.id),
                    "account_id": str(r.account_id),
                    "platform": r.platform,
                    "platform_campaign_id": r.platform_campaign_id,
                    "name": r.name,
                    "status": r.status,
                    "objective": r.objective,
                    "daily_budget": float(r.daily_budget) if r.daily_budget is not None else None,
                    "lifetime_budget": float(r.lifetime_budget) if r.lifetime_budget is not None else None,
                    "start_date": r.start_date.isoformat() if r.start_date else None,
                    "end_date": r.end_date.isoformat() if r.end_date else None,
                    "ta": r.ta,
                    "funnel_stage": r.funnel_stage,
                }
                for r in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/ads")
def export_ads(
    platform: str = Query(None),
    account_id: str = Query(None),
    campaign_id: str = Query(None),
    status: str = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export ads."""
    try:
        q = db.query(Ad)
        if platform:
            q = q.filter(Ad.platform == platform)
        if account_id:
            q = q.filter(Ad.account_id == account_id)
        if campaign_id:
            q = q.filter(Ad.campaign_id == campaign_id)
        if status:
            q = q.filter(Ad.status == status)

        total = q.count()
        rows = q.order_by(Ad.name).offset(offset).limit(limit).all()

        return _api_response(data={
            "items": [
                {
                    "id": str(r.id),
                    "account_id": str(r.account_id),
                    "campaign_id": str(r.campaign_id),
                    "ad_set_id": str(r.ad_set_id),
                    "platform": r.platform,
                    "platform_ad_id": r.platform_ad_id,
                    "name": r.name,
                    "status": r.status,
                    "creative_id": r.creative_id,
                }
                for r in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/ads/metrics")
def export_ad_metrics(
    date_from: str = Query(..., description="ISO date YYYY-MM-DD"),
    date_to: str = Query(..., description="ISO date YYYY-MM-DD"),
    platform: str = Query(None, description="meta | google | tiktok"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Per-ad_id aggregated metrics for a date window (ad-level rows only).

    Sums every metrics_cache row where ad_id IS NOT NULL across the date range.
    Video fields (views, 3s, thruplay, p25/p50/p75/p100) are 0 for non-video
    creatives and for platforms other than Meta (Google/TikTok sync doesn't
    populate them yet).
    """
    try:
        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        if df > dt:
            return _api_response(error="date_from must be <= date_to")

        q = db.query(
            MetricsCache.ad_id.label("ad_id"),
            MetricsCache.platform.label("platform"),
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
            func.sum(MetricsCache.video_views).label("video_views"),
            func.sum(MetricsCache.video_3s_views).label("video_3s_views"),
            func.sum(MetricsCache.video_thru_plays).label("video_thru_plays"),
            func.sum(MetricsCache.video_p25_views).label("video_p25_views"),
            func.sum(MetricsCache.video_p50_views).label("video_p50_views"),
            func.sum(MetricsCache.video_p75_views).label("video_p75_views"),
            func.sum(MetricsCache.video_p100_views).label("video_p100_views"),
        ).filter(
            MetricsCache.date >= df,
            MetricsCache.date <= dt,
            MetricsCache.ad_id.isnot(None),
        )
        if platform:
            q = q.filter(MetricsCache.platform == platform)

        rows = q.group_by(MetricsCache.ad_id, MetricsCache.platform).all()

        return _api_response(data=[
            {
                "ad_id": str(r.ad_id),
                "platform": r.platform,
                "spend": float(r.spend or 0),
                "impressions": int(r.impressions or 0),
                "clicks": int(r.clicks or 0),
                "conversions": int(r.conversions or 0),
                "revenue": float(r.revenue or 0),
                "video_views": int(r.video_views or 0),
                "video_3s_views": int(r.video_3s_views or 0),
                "video_thru_plays": int(r.video_thru_plays or 0),
                "video_p25_views": int(r.video_p25_views or 0),
                "video_p50_views": int(r.video_p50_views or 0),
                "video_p75_views": int(r.video_p75_views or 0),
                "video_p100_views": int(r.video_p100_views or 0),
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/countries")
def export_countries(
    date_from: str = Query(..., description="ISO date"),
    date_to: str = Query(..., description="ISO date"),
    platform: str = Query(None),
    country: str = Query(None),
    campaign_id: str = Query(None),
    ad_id: str = Query(None),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export per-country × date metrics (website vs offline revenue)."""
    try:
        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        q = db.query(AdCountryMetric).filter(
            AdCountryMetric.date >= df,
            AdCountryMetric.date <= dt,
        )
        if platform:
            q = q.filter(AdCountryMetric.platform == platform)
        if country:
            q = q.filter(AdCountryMetric.country == country)
        if campaign_id:
            q = q.filter(AdCountryMetric.campaign_id == campaign_id)
        if ad_id:
            q = q.filter(AdCountryMetric.ad_id == ad_id)

        rows = q.order_by(AdCountryMetric.date.desc()).limit(5000).all()

        return _api_response(data=[
            {
                "id": str(r.id),
                "platform": r.platform,
                "campaign_id": str(r.campaign_id),
                "ad_id": str(r.ad_id) if r.ad_id else None,
                "date": r.date.isoformat(),
                "country": r.country,
                "spend": float(r.spend or 0),
                "impressions": r.impressions,
                "clicks": r.clicks,
                "revenue_website": float(r.revenue_website or 0),
                "revenue_offline": float(r.revenue_offline or 0),
                "conversions_website": r.conversions_website,
                "conversions_offline": r.conversions_offline,
            }
            for r in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/spy-ads")
def export_spy_ads(
    country: str = Query(None),
    page_id: str = Query(None),
    media_type: str = Query(None),
    collection: str = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export spy ads (competitive research library)."""
    try:
        q = db.query(SpySavedAd).filter(SpySavedAd.is_active.is_(True))
        if country:
            q = q.filter(SpySavedAd.country == country)
        if page_id:
            q = q.filter(SpySavedAd.page_id == page_id)
        if media_type:
            q = q.filter(SpySavedAd.media_type == media_type)
        if collection:
            q = q.filter(SpySavedAd.collection == collection)

        total = q.count()
        rows = (
            q.order_by(SpySavedAd.ad_delivery_start_time.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return _api_response(data={
            "items": [
                {
                    "id": str(r.id),
                    "ad_archive_id": r.ad_archive_id,
                    "page_id": r.page_id,
                    "page_name": r.page_name,
                    "ad_creative_bodies": r.ad_creative_bodies,
                    "ad_creative_link_titles": r.ad_creative_link_titles,
                    "ad_creative_link_captions": r.ad_creative_link_captions,
                    "ad_snapshot_url": r.ad_snapshot_url,
                    "publisher_platforms": r.publisher_platforms,
                    "ad_delivery_start_time": r.ad_delivery_start_time.isoformat() if r.ad_delivery_start_time else None,
                    "ad_delivery_stop_time": r.ad_delivery_stop_time.isoformat() if r.ad_delivery_stop_time else None,
                    "country": r.country,
                    "media_type": r.media_type,
                    "tags": r.tags,
                    "notes": r.notes,
                    "collection": r.collection,
                }
                for r in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/budget/monthly")
def export_budget_monthly(
    month: str = Query(None, description="YYYY-MM format"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export monthly budget data."""
    try:
        if month:
            month_date = date.fromisoformat(f"{month}-01")
        else:
            today = date.today()
            month_date = date(today.year, today.month, 1)

        plans = (
            db.query(BudgetPlan)
            .filter(BudgetPlan.month == month_date, BudgetPlan.is_active.is_(True))
            .all()
        )

        return _api_response(data={
            "month": month_date.isoformat(),
            "plans": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "branch": p.branch,
                    "channel": p.channel,
                    "total_budget": float(p.total_budget),
                    "currency": p.currency,
                }
                for p in plans
            ],
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/budget/yearly-plan")
def export_budget_yearly_plan(
    branch: str = Query(..., description="Branch key (e.g. Saigon, Osaka, 1948, Taipei, Oani, Bread)"),
    year: int = Query(..., description="4-digit year, e.g. 2026"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export yearly budget plan for (branch, year): yearly total VND + 12 month %.

    Mirrors GET /api/budget/yearly-plan for external/automation use. Returns
    full 12-month payload (zero-filled if no plan saved yet) including budget
    and actual spend per month in both native and VND.
    """
    try:
        return _api_response(data=get_yearly_plan(db, branch, year))
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/budget/monthly-splits")
def export_budget_monthly_splits(
    branch: str = Query(..., description="Branch key (e.g. Saigon, Osaka, 1948, Taipei, Oani, Bread)"),
    year: int = Query(..., description="4-digit year, e.g. 2026"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export 12-month monthly splits for (branch, year).

    Mirrors GET /api/budget/monthly-splits. Each month carries total_vnd,
    total_native, channel_pct, overflow_note. Missing months returned as zeros.
    """
    try:
        items = list_monthly_splits(db, branch, year)
        return _api_response(data={"branch": branch, "year": year, "months": items})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/spend/daily")
def export_spend_daily(
    date_from: str = Query(...),
    date_to: str = Query(...),
    platform: str = Query(None),
    branch: str = Query(
        None,
        description="Filter by canonical branch (case-insensitive): saigon|taipei|1948|oani|osaka|bread",
    ),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export daily spend breakdown.

    Each row = (date × platform × account). The `account_id` and `branch`
    fields let consumers re-aggregate by branch without parsing account_name.
    """
    try:
        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        if df > dt:
            return _api_response(error="date_from must be <= date_to")

        q = db.query(
            MetricsCache.date.label("date"),
            MetricsCache.platform.label("platform"),
            Campaign.account_id.label("account_id"),
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        ).join(Campaign, Campaign.id == MetricsCache.campaign_id).filter(
            MetricsCache.date >= df,
            MetricsCache.date <= dt,
        )

        if platform:
            q = q.filter(MetricsCache.platform == platform)

        if branch:
            canonical = canonical_branch(branch)
            if canonical is None:
                return _api_response(error=f"Unknown branch: {branch}")
            account_ids = get_account_ids_for_branches(db, [canonical])
            if not account_ids:
                return _api_response(data=[])
            q = q.filter(Campaign.account_id.in_(account_ids))

        rows = (
            q.group_by(MetricsCache.date, MetricsCache.platform, Campaign.account_id)
            .order_by(MetricsCache.date)
            .all()
        )

        # Resolve account_id → (account_name, branch) once for the response.
        account_id_set = {r.account_id for r in rows if r.account_id}
        accounts_by_id: dict[str, AdAccount] = {}
        if account_id_set:
            for a in db.query(AdAccount).filter(AdAccount.id.in_(account_id_set)).all():
                accounts_by_id[a.id] = a

        out = []
        for row in rows:
            acc = accounts_by_id.get(row.account_id)
            account_name = acc.account_name if acc else None
            out.append({
                "date": row.date.isoformat(),
                "platform": row.platform,
                "account_id": str(row.account_id) if row.account_id else None,
                "account_name": account_name,
                "branch": resolve_branch_for_account_name(account_name),
                "spend": float(row.spend or 0),
                "impressions": int(row.impressions or 0),
                "clicks": int(row.clicks or 0),
                "conversions": int(row.conversions or 0),
                "revenue": float(row.revenue or 0),
            })
        return _api_response(data=out)
    except Exception as e:
        return _api_response(error=str(e))


def _resolve_booking_date_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    if date_to:
        dt = date.fromisoformat(date_to)
    else:
        dt = date.today()
    if date_from:
        df = date.fromisoformat(date_from)
    else:
        df = dt - timedelta(days=29)
    if df > dt:
        raise ValueError("date_from must be <= date_to")
    return df, dt


@router.get("/export/booking-matches")
def export_booking_matches(
    date_from: str = Query(None, description="ISO date YYYY-MM-DD; defaults to 30 days before date_to"),
    date_to: str = Query(None, description="ISO date YYYY-MM-DD; defaults to today"),
    branch: str = Query(None, description="Canonical branch key: Saigon|Taipei|1948|Osaka|Oani"),
    channel: str = Query(None, description="Ads channel: meta|google"),
    match_result: str = Query(None),
    purchase_kind: str = Query(None, description="website | offline"),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export Booking from Ads rows for external systems. Requires X-API-Key."""
    try:
        df, dt = _resolve_booking_date_range(date_from, date_to)

        q = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        if branch:
            q = q.filter(BookingMatch.branch == branch)
        if channel:
            q = q.filter(BookingMatch.ads_channel == channel)
        if match_result:
            q = q.filter(BookingMatch.match_result == match_result)
        if purchase_kind:
            q = q.filter(BookingMatch.purchase_kind == purchase_kind)

        total = q.count()
        rows = (
            q.order_by(BookingMatch.match_date.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        items = [
            {
                "id": str(m.id),
                "match_date": m.match_date.isoformat() if m.match_date else None,
                "ads_revenue": float(m.ads_revenue or 0),
                "ads_bookings": m.ads_bookings,
                "ads_country": m.ads_country,
                "ads_channel": m.ads_channel,
                "campaign_name": m.campaign_name,
                "campaign_id": str(m.campaign_id) if m.campaign_id else None,
                "ad_id": str(m.ad_id) if m.ad_id else None,
                "ad_name": m.ad_name,
                "purchase_kind": m.purchase_kind,
                "reservation_numbers": m.reservation_numbers,
                "guest_names": m.guest_names,
                "guest_emails": m.guest_emails,
                "reservation_statuses": m.reservation_statuses,
                "room_types": m.room_types,
                "rate_plans": m.rate_plans,
                "reservation_sources": m.reservation_sources,
                "matched_country": m.matched_country,
                "branch": m.branch,
                "match_result": m.match_result,
                "matched_at": m.matched_at.isoformat() if m.matched_at else None,
            }
            for m in rows
        ]

        return _api_response(data={
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/booking-matches/summary")
def export_booking_matches_summary(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """KPI roll-up for Booking from Ads."""
    try:
        df, dt = _resolve_booking_date_range(date_from, date_to)

        base = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        if branch:
            base = base.filter(BookingMatch.branch == branch)

        total_matches = base.count()
        total_revenue = float(base.with_entities(func.sum(BookingMatch.ads_revenue)).scalar() or 0)
        total_bookings = int(base.with_entities(func.sum(BookingMatch.ads_bookings)).scalar() or 0)

        by_channel = [
            {
                "channel": r.ads_channel or "unknown",
                "matches": int(r.matches or 0),
                "revenue": float(r.revenue or 0),
                "bookings": int(r.bookings or 0),
            }
            for r in base.with_entities(
                BookingMatch.ads_channel,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.ads_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            ).group_by(BookingMatch.ads_channel).all()
        ]

        by_branch = [
            {
                "branch": r.branch or "unknown",
                "matches": int(r.matches or 0),
                "revenue": float(r.revenue or 0),
                "bookings": int(r.bookings or 0),
            }
            for r in base.with_entities(
                BookingMatch.branch,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.ads_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            ).group_by(BookingMatch.branch).all()
        ]

        return _api_response(data={
            "total_matches": total_matches,
            "total_revenue": total_revenue,
            "total_bookings": total_bookings,
            "by_channel": by_channel,
            "by_branch": by_branch,
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))
