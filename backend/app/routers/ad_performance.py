"""Ad Name Performance — daily per-ad metrics pulled from Meta.

Backs the /ad-performance frontend page:
  - GET  /ad-performance         list ads (Campaign → Ad Set → Ad name) with
                                 totals over a date window, either one row per
                                 ad (group_by=ad) or pivoted so every ad
                                 sharing an ad_name collapses into one row
                                 (group_by=ad_name)
  - GET  /ad-performance/daily   per-day series for one or more ads (drill /
                                 compare) — by ad_id, or by ad_name to match
                                 the pivot
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
    video_3s = int(s.video_3s or 0)
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
        "hook_rate": (video_3s / impressions) if video_3s and impressions > 0 else None,
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
    sf.sum(AdDailyMetric.video_3s).label("video_3s"),
    sf.sum(AdDailyMetric.thruplay).label("thruplay"),
    sf.sum(AdDailyMetric.video_p100).label("video_p100"),
]

# Keys the list endpoint can sort by (all live in the derived dict).
_SORTABLE = {
    "spend", "roas", "conversions", "leads", "cost_per_lead", "cost_per_purchase",
    "ctr", "impressions", "clicks", "engagement_rate", "hook_rate",
    "thruplay_rate", "video_complete_rate", "ad_count",
}

# Pivot rows are keyed by (account_id, ad_name) — NEVER by ad_name alone:
# spend/revenue are stored in each branch's native currency, so collapsing the
# same ad name across branches would sum VND onto TWD.
def _name_key(account_id, ad_name: str | None) -> str:
    return f"{account_id}::{ad_name or ''}"


@router.get("/ad-performance")
def list_ad_performance(
    branch_id: str | None = None,
    campaign_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "spend",
    sort_dir: str = "desc",
    group_by: str = "ad",
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Ads aggregated over a date window.

    group_by='ad' (default)  one row per ad, with full 3-level names.
    group_by='ad_name'       pivot — every ad sharing an ad_name inside the same
                             branch collapses into one row. Raw counts are
                             summed first, rates derived after, so the pivoted
                             ROAS/CTR/CPL are true weighted averages.
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)
        df, dt = _parse_range(date_from, date_to)
        pivot = group_by == "ad_name"

        if pivot:
            q = db.query(
                AdDailyMetric.account_id.label("account_id"),
                AdDailyMetric.ad_name.label("ad_name"),
                sf.count(sf.distinct(AdDailyMetric.ad_id)).label("ad_count"),
                sf.count(sf.distinct(AdDailyMetric.campaign_id)).label("campaign_count"),
                sf.count(sf.distinct(AdDailyMetric.adset_id)).label("adset_count"),
                sf.max(AdDailyMetric.campaign_id).label("campaign_id"),
                sf.max(AdDailyMetric.campaign_name).label("campaign_name"),
                sf.max(AdDailyMetric.adset_name).label("adset_name"),
                *_SUM_COLS,
            )
        else:
            q = db.query(
                AdDailyMetric.account_id.label("account_id"),
                AdDailyMetric.ad_id.label("ad_id"),
                sf.max(AdDailyMetric.ad_name).label("ad_name"),
                sf.max(AdDailyMetric.campaign_id).label("campaign_id"),
                sf.max(AdDailyMetric.campaign_name).label("campaign_name"),
                sf.max(AdDailyMetric.adset_name).label("adset_name"),
                *_SUM_COLS,
            )

        q = q.filter(
            AdDailyMetric.date >= df,
            AdDailyMetric.date <= dt,
        )
        if branch_id:
            q = q.filter(AdDailyMetric.account_id == branch_id)
        elif scoped_ids is not None:
            q = q.filter(AdDailyMetric.account_id.in_(scoped_ids or ["__no_match__"]))
        if campaign_id:
            q = q.filter(AdDailyMetric.campaign_id == campaign_id)

        grain = AdDailyMetric.ad_name if pivot else AdDailyMetric.ad_id
        q = q.group_by(AdDailyMetric.account_id, grain).having(
            sf.sum(AdDailyMetric.spend) > 0
        )

        items = []
        for r in q.all():
            row = {
                "account_id": r.account_id,
                "ad_name": r.ad_name,
                "campaign_id": r.campaign_id,
                "campaign_name": r.campaign_name,
                "adset_name": r.adset_name,
            }
            if pivot:
                row.update({
                    "key": _name_key(r.account_id, r.ad_name),
                    "ad_id": None,
                    "ad_count": int(r.ad_count or 0),
                    "campaign_count": int(r.campaign_count or 0),
                    "adset_count": int(r.adset_count or 0),
                })
            else:
                row.update({
                    "key": r.ad_id,
                    "ad_id": r.ad_id,
                    "ad_count": 1,
                    "campaign_count": 1,
                    "adset_count": 1,
                })
            row.update(_derive(r))
            items.append(row)

        key = sort_by if sort_by in _SORTABLE else "spend"
        items.sort(key=lambda x: x.get(key) or 0, reverse=(sort_dir != "asc"))

        return _api_response(data={
            "items": items,
            "total": len(items),
            "group_by": "ad_name" if pivot else "ad",
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
        })
    except Exception as e:
        logger.exception("list_ad_performance failed")
        return _api_response(error=str(e))


@router.get("/ad-performance/daily")
def ad_performance_daily(
    ad_ids: str | None = Query(None, description="Comma-separated Meta ad_ids"),
    ad_names: list[str] | None = Query(
        None, description="Repeatable — one series per (branch, ad_name), matching the pivot"
    ),
    date_from: str | None = None,
    date_to: str | None = None,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Per-day series for one or more ads (drill-down + multi-ad comparison).

    Pass `ad_ids` for the per-ad view, or repeated `ad_name=` params for the
    ad-name pivot — the latter sums every ad sharing that name inside a branch
    per day, then derives the rates (same maths as the pivoted list).

    ad_name is repeatable rather than comma-separated because Meta ad names
    routinely contain commas.
    """
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)
        df, dt = _parse_range(date_from, date_to)
        period = {"from": df.isoformat(), "to": dt.isoformat()}
        ids = [a.strip() for a in (ad_ids or "").split(",") if a.strip()]
        names = [n for n in (ad_names or []) if n]
        if not ids and not names:
            return _api_response(data={"items": [], "period": period})

        items = []
        if names:
            q = db.query(
                AdDailyMetric.date.label("date"),
                AdDailyMetric.account_id.label("account_id"),
                AdDailyMetric.ad_name.label("ad_name"),
                *_SUM_COLS,
            ).filter(
                AdDailyMetric.ad_name.in_(names),
                AdDailyMetric.date >= df,
                AdDailyMetric.date <= dt,
            )
            if scoped_ids is not None:
                q = q.filter(AdDailyMetric.account_id.in_(scoped_ids or ["__no_match__"]))
            q = q.group_by(
                AdDailyMetric.date, AdDailyMetric.account_id, AdDailyMetric.ad_name
            ).order_by(AdDailyMetric.ad_name, AdDailyMetric.date)

            for r in q.all():
                row = {
                    "date": r.date.isoformat(),
                    "key": _name_key(r.account_id, r.ad_name),
                    "account_id": r.account_id,
                    "ad_id": None,
                    "ad_name": r.ad_name,
                    "campaign_name": None,
                    "adset_name": None,
                }
                row.update(_derive(r))
                items.append(row)
        else:
            q = db.query(AdDailyMetric).filter(
                AdDailyMetric.ad_id.in_(ids),
                AdDailyMetric.date >= df,
                AdDailyMetric.date <= dt,
            )
            if scoped_ids is not None:
                q = q.filter(AdDailyMetric.account_id.in_(scoped_ids or ["__no_match__"]))
            q = q.order_by(AdDailyMetric.ad_id, AdDailyMetric.date)

            for r in q.all():
                row = {
                    "date": r.date.isoformat(),
                    "key": r.ad_id,
                    "account_id": r.account_id,
                    "ad_id": r.ad_id,
                    "ad_name": r.ad_name,
                    "campaign_name": r.campaign_name,
                    "adset_name": r.adset_name,
                }
                row.update(_derive(r))
                items.append(row)

        return _api_response(data={"items": items, "period": period})
    except Exception as e:
        logger.exception("ad_performance_daily failed")
        return _api_response(error=str(e))


@router.post("/ad-performance/sync")
def sync_ad_performance(
    since: str | None = None,
    until: str | None = None,
    branch_id: str | None = None,
    current_user: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Manual 'Sync from Meta' button. Pulls daily ad metrics over
    [since, until] (since default 2026-05-01, until default today).

    When `branch_id` is given only that branch is synced; otherwise every Meta
    account the user can edit. The window matches the page's active filters so a
    'Last 7 days' / 'Last month' sync only re-fetches those days.

    Runs in a daemon thread with its own DB session so the request returns
    immediately (Zeabur ingress is capped at ~225s); the frontend re-fetches
    the list a few seconds later.
    """
    try:
        since_date = date.fromisoformat(since) if since else DEFAULT_SINCE
        until_date = date.fromisoformat(until) if until else None
    except ValueError:
        return _api_response(error="invalid date (expected YYYY-MM-DD)")

    if until_date and until_date < since_date:
        return _api_response(error="'until' must not be before 'since'")

    # Restrict the sync to the accounts this user is allowed to edit (and to the
    # requested branch, when one is selected).
    ok, scoped_ids, err = scoped_account_ids(
        db, current_user, "meta_ads", requested_account_id=branch_id, min_level="edit"
    )
    if not ok:
        return _api_response(error=err)

    def _wrapper():
        bg = SessionLocal()
        try:
            logger.info(
                "[ad-daily] manual sync starting (since=%s until=%s accounts=%s)",
                since_date.isoformat(),
                (until_date or date.today()).isoformat(),
                scoped_ids if scoped_ids is not None else "all",
            )
            sync_all_daily_ad_metrics(
                bg, since_date=since_date, until_date=until_date, account_ids=scoped_ids
            )
        except Exception:
            logger.exception("[ad-daily] manual sync failed")
        finally:
            bg.close()

    threading.Thread(target=_wrapper, name="ad-daily-sync", daemon=True).start()
    return _api_response(data={
        "status": "started",
        "since": since_date.isoformat(),
        "until": (until_date or date.today()).isoformat(),
        "branch_id": branch_id,
    })
