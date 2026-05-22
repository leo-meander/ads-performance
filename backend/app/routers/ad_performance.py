"""Ad Name Performance — daily per-ad metrics pulled from Meta.

Backs the /ad-performance frontend page:
  - GET  /ad-performance         list ads (Campaign → Ad Set → Ad name) with
                                 totals over a date window
  - GET  /ad-performance/daily   per-day series for one or more ads (drill /
                                 compare)
  - POST /ad-performance/sync    manual "Sync from Meta" button (runs in a
                                 background thread, returns 202 immediately)

Metrics are stored as RAW counts in ad_daily_metrics; derived rates (roas,
ctr, cpp, cost_per_lead, hook_rate, ...) are computed here at read time so a
date-window sum is always correct.
"""
import logging
import threading
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sf
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import SessionLocal, get_db
from app.dependencies.auth import require_section
from app.models.ad_daily_metric import AdDailyMetric
from app.models.user import User
from app.services.daily_ad_metrics_sync import DEFAULT_SINCE, sync_all_daily_ad_metrics

logger = logging.getLogger(__name__)
router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _parse_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Default window: from DEFAULT_SINCE (2026-05-01) to today."""
    df = date.fromisoformat(date_from) if date_from else DEFAULT_SINCE
    dt = date.fromisoformat(date_to) if date_to else date.today()
    return df, dt


def _derive(s) -> dict:
    """Build the metric dict (raw + derived rates) from a row of summed counts.

    `s` is any object exposing the summed attributes by name (a query result
    row or a plain namespace)."""
    spend = float(s.spend or 0)
    impressions = int(s.impressions or 0)
    clicks = int(s.clicks or 0)
    conversions = int(s.conversions or 0)
    revenue = float(s.revenue or 0)
    leads = int(s.leads or 0)
    engagement = int(s.engagement or 0)
    video_plays = int(s.video_plays or 0)
    thruplay = int(s.thruplay or 0)
    video_p100 = int(s.video_p100 or 0)
    return {
        "spend": spend or None,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "revenue": revenue or None,
        "leads": leads,
        "roas": (revenue / spend) if spend > 0 else None,
        "cost_per_purchase": (spend / conversions) if conversions > 0 else None,
        "cost_per_lead": (spend / leads) if leads > 0 else None,
        "ctr": (clicks / impressions) if impressions > 0 else None,
        "engagement_rate": (engagement / impressions) if impressions > 0 else None,
        "hook_rate": (video_plays / impressions) if video_plays and impressions > 0 else None,
        "thruplay_rate": (thruplay / video_plays) if thruplay and video_plays > 0 else None,
        "video_complete_rate": (video_p100 / video_plays) if video_p100 and video_plays > 0 else None,
    }


_SUM_COLS = [
    sf.sum(AdDailyMetric.spend).label("spend"),
    sf.sum(AdDailyMetric.impressions).label("impressions"),
    sf.sum(AdDailyMetric.clicks).label("clicks"),
    sf.sum(AdDailyMetric.conversions).label("conversions"),
    sf.sum(AdDailyMetric.revenue).label("revenue"),
    sf.sum(AdDailyMetric.leads).label("leads"),
    sf.sum(AdDailyMetric.engagement).label("engagement"),
    sf.sum(AdDailyMetric.video_plays).label("video_plays"),
    sf.sum(AdDailyMetric.thruplay).label("thruplay"),
    sf.sum(AdDailyMetric.video_p100).label("video_p100"),
]

# Keys the list endpoint can sort by (all live in the derived dict).
_SORTABLE = {
    "spend", "roas", "conversions", "leads", "cost_per_lead", "cost_per_purchase",
    "ctr", "impressions", "clicks", "engagement_rate", "hook_rate",
    "thruplay_rate", "video_complete_rate",
}


@router.get("/ad-performance")
def list_ad_performance(
    branch_id: str | None = None,
    campaign_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "spend",
    sort_dir: str = "desc",
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Ads aggregated over a date window, one row per ad with full 3-level names."""
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        df, dt = _parse_range(date_from, date_to)

        q = db.query(
            AdDailyMetric.account_id.label("account_id"),
            AdDailyMetric.ad_id.label("ad_id"),
            sf.max(AdDailyMetric.ad_name).label("ad_name"),
            sf.max(AdDailyMetric.campaign_id).label("campaign_id"),
            sf.max(AdDailyMetric.campaign_name).label("campaign_name"),
            sf.max(AdDailyMetric.adset_name).label("adset_name"),
            *_SUM_COLS,
        ).filter(
            AdDailyMetric.date >= df,
            AdDailyMetric.date <= dt,
        )
        if branch_id:
            q = q.filter(AdDailyMetric.account_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdDailyMetric.account_id.in_(scoped_ids or ["__no_match__"]))
        if campaign_id:
            q = q.filter(AdDailyMetric.campaign_id == campaign_id)
        q = q.group_by(AdDailyMetric.account_id, AdDailyMetric.ad_id).having(
            sf.sum(AdDailyMetric.spend) > 0
        )

        items = []
        for r in q.all():
            row = {
                "account_id": r.account_id,
                "ad_id": r.ad_id,
                "ad_name": r.ad_name,
                "campaign_id": r.campaign_id,
                "campaign_name": r.campaign_name,
                "adset_name": r.adset_name,
            }
            row.update(_derive(r))
            items.append(row)

        key = sort_by if sort_by in _SORTABLE else "spend"
        items.sort(key=lambda x: x.get(key) or 0, reverse=(sort_dir != "asc"))

        return _api_response(data={
            "items": items,
            "total": len(items),
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
        })
    except Exception as e:
        logger.exception("list_ad_performance failed")
        return _api_response(error=str(e))


@router.get("/ad-performance/daily")
def ad_performance_daily(
    ad_ids: str = Query(..., description="Comma-separated Meta ad_ids"),
    date_from: str | None = None,
    date_to: str | None = None,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Per-day series for one or more ads (drill-down + multi-ad comparison)."""
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)
        df, dt = _parse_range(date_from, date_to)
        ids = [a.strip() for a in (ad_ids or "").split(",") if a.strip()]
        if not ids:
            return _api_response(data={"items": [], "period": {"from": df.isoformat(), "to": dt.isoformat()}})

        q = db.query(AdDailyMetric).filter(
            AdDailyMetric.ad_id.in_(ids),
            AdDailyMetric.date >= df,
            AdDailyMetric.date <= dt,
        )
        if scoped_ids is not None:
            q = q.filter(AdDailyMetric.account_id.in_(scoped_ids or ["__no_match__"]))
        q = q.order_by(AdDailyMetric.ad_id, AdDailyMetric.date)

        items = []
        for r in q.all():
            row = {
                "date": r.date.isoformat(),
                "ad_id": r.ad_id,
                "ad_name": r.ad_name,
                "campaign_name": r.campaign_name,
                "adset_name": r.adset_name,
            }
            row.update(_derive(r))
            items.append(row)

        return _api_response(data={
            "items": items,
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
        })
    except Exception as e:
        logger.exception("ad_performance_daily failed")
        return _api_response(error=str(e))


@router.post("/ad-performance/sync")
def sync_ad_performance(
    since: str | None = None,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Manual 'Sync from Meta' button. Pulls daily ad metrics since `since`
    (default 2026-05-01) for every active Meta account.

    Runs in a daemon thread with its own DB session so the request returns
    immediately (Zeabur ingress is capped at ~225s); the frontend re-fetches
    the list a few seconds later.
    """
    try:
        since_date = date.fromisoformat(since) if since else DEFAULT_SINCE
    except ValueError:
        return _api_response(error="invalid 'since' date (expected YYYY-MM-DD)")

    def _wrapper():
        bg = SessionLocal()
        try:
            logger.info("[ad-daily] manual sync starting (since=%s)", since_date.isoformat())
            sync_all_daily_ad_metrics(bg, since_date=since_date)
        except Exception:
            logger.exception("[ad-daily] manual sync failed")
        finally:
            bg.close()

    threading.Thread(target=_wrapper, name="ad-daily-sync", daemon=True).start()
    return _api_response(data={"status": "started", "since": since_date.isoformat()})
