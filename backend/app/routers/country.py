"""Country dashboard endpoints with branch filter and period comparison."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.account import AdAccount
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services.country_utils import (
    calc_change,
    country_name,
    get_prev_period,
    is_valid_country,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _default_date_range():
    """Default: last 7 days."""
    today = date.today()
    return today - timedelta(days=6), today


def _apply_common_filters(q, country, platform, date_from, date_to, funnel_stage, account_id):
    """Apply common filters to a metrics query (already joined with Campaign + AdSet)."""
    if country:
        q = q.filter(AdSet.country == country.upper())
    if platform:
        q = q.filter(MetricsCache.platform == platform)
    if date_from:
        q = q.filter(MetricsCache.date >= (date.fromisoformat(date_from) if isinstance(date_from, str) else date_from))
    if date_to:
        q = q.filter(MetricsCache.date <= (date.fromisoformat(date_to) if isinstance(date_to, str) else date_to))
    if funnel_stage:
        q = q.filter(Campaign.funnel_stage == funnel_stage.upper())
    if account_id:
        q = q.filter(Campaign.account_id == account_id)
    # Only valid 2-letter country codes
    q = q.filter(AdSet.country.isnot(None), func.length(AdSet.country) == 2)
    return q


def _base_metrics_query(db: Session):
    """Base query joining metrics → campaign → adset."""
    return (
        db.query(
            AdSet.country,
            func.sum(MetricsCache.spend).label("total_spend"),
            func.sum(MetricsCache.impressions).label("total_impressions"),
            func.sum(MetricsCache.clicks).label("total_clicks"),
            func.sum(MetricsCache.conversions).label("total_conversions"),
            func.sum(MetricsCache.revenue).label("total_revenue"),
            func.count(func.distinct(Campaign.id)).label("campaign_count"),
        )
        .join(Campaign, Campaign.id == MetricsCache.campaign_id)
        .join(AdSet, AdSet.id == MetricsCache.ad_set_id)
    )


def _row_to_kpi(row) -> dict:
    spend = float(row.total_spend or 0)
    revenue = float(row.total_revenue or 0)
    impressions = int(row.total_impressions or 0)
    clicks = int(row.total_clicks or 0)
    conversions = int(row.total_conversions or 0)
    return {
        "country_code": row.country,
        "country": country_name(row.country) or row.country,
        "total_spend": spend,
        "total_revenue": revenue,
        "roas": round(revenue / spend, 2) if spend > 0 else 0,
        "ctr": round((clicks / impressions) * 100, 2) if impressions > 0 else 0,
        "cpa": round(spend / conversions, 2) if conversions > 0 else 0,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "campaign_count": getattr(row, "campaign_count", 0),
    }


@router.get("/dashboard/country")
def country_kpi_summary(
    country: str = Query(None),
    platform: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    funnel_stage: str = Query(None),
    account_id: str = Query(None, description="Branch filter — ad_accounts.id"),
    db: Session = Depends(get_db),
):
    """Country KPI summary with period-over-period comparison."""
    try:
        # Default date range
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        # Current period
        q = _base_metrics_query(db)
        q = _apply_common_filters(q, country, platform, df, dt, funnel_stage, account_id)
        rows = q.group_by(AdSet.country).all()

        # Previous period
        q_prev = _base_metrics_query(db)
        q_prev = _apply_common_filters(q_prev, country, platform, prev_from, prev_to, funnel_stage, account_id)
        prev_rows = q_prev.group_by(AdSet.country).all()
        prev_map = {r.country: r for r in prev_rows}

        items = []
        for row in rows:
            if not is_valid_country(row.country):
                continue
            kpi = _row_to_kpi(row)
            # Add change vs previous period
            prev = prev_map.get(row.country)
            if prev:
                prev_kpi = _row_to_kpi(prev)
                kpi["spend_change"] = calc_change(kpi["total_spend"], prev_kpi["total_spend"])
                kpi["revenue_change"] = calc_change(kpi["total_revenue"], prev_kpi["total_revenue"])
                kpi["roas_change"] = calc_change(kpi["roas"], prev_kpi["roas"])
                kpi["ctr_change"] = calc_change(kpi["ctr"], prev_kpi["ctr"])
                kpi["conversions_change"] = calc_change(kpi["conversions"], prev_kpi["conversions"])
            else:
                kpi["spend_change"] = None
                kpi["revenue_change"] = None
                kpi["roas_change"] = None
                kpi["ctr_change"] = None
                kpi["conversions_change"] = None
            items.append(kpi)

        return _api_response(data={
            "items": items,
            "period": {"from": date_from, "to": date_to},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/ta-breakdown")
def ta_breakdown(
    country: str = Query(...),
    platform: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    account_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """TA x Funnel Stage breakdown for a specific country, with period comparison."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query_ta(d_from, d_to):
            q = (
                db.query(
                    Campaign.ta,
                    Campaign.funnel_stage,
                    func.sum(MetricsCache.spend).label("spend"),
                    func.sum(MetricsCache.impressions).label("impressions"),
                    func.sum(MetricsCache.clicks).label("clicks"),
                    func.sum(MetricsCache.conversions).label("conversions"),
                    func.sum(MetricsCache.revenue).label("revenue"),
                )
                .join(Campaign, Campaign.id == MetricsCache.campaign_id)
                .join(AdSet, AdSet.id == MetricsCache.ad_set_id)
                .filter(AdSet.country == country.upper())
                .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
            )
            if platform:
                q = q.filter(MetricsCache.platform == platform)
            if account_id:
                q = q.filter(Campaign.account_id == account_id)
            return q.group_by(Campaign.ta, Campaign.funnel_stage).all()

        rows = _query_ta(df, dt)
        prev_rows = _query_ta(prev_from, prev_to)
        prev_map = {(r.ta, r.funnel_stage): r for r in prev_rows}

        items = []
        for row in rows:
            spend = float(row.spend or 0)
            revenue = float(row.revenue or 0)
            impressions = int(row.impressions or 0)
            clicks = int(row.clicks or 0)
            conversions = int(row.conversions or 0)
            roas = round(revenue / spend, 2) if spend > 0 else 0

            item = {
                "ta": row.ta,
                "funnel_stage": row.funnel_stage,
                "spend": spend,
                "revenue": revenue,
                "roas": roas,
                "ctr": round((clicks / impressions) * 100, 2) if impressions > 0 else 0,
                "cpa": round(spend / conversions, 2) if conversions > 0 else 0,
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "is_remarketing": row.funnel_stage == "MOF",
            }

            prev = prev_map.get((row.ta, row.funnel_stage))
            if prev:
                prev_spend = float(prev.spend or 0)
                prev_revenue = float(prev.revenue or 0)
                prev_roas = round(prev_revenue / prev_spend, 2) if prev_spend > 0 else 0
                item["spend_change"] = calc_change(spend, prev_spend)
                item["roas_change"] = calc_change(roas, prev_roas)
                item["conversions_change"] = calc_change(conversions, int(prev.conversions or 0))
            else:
                item["spend_change"] = None
                item["roas_change"] = None
                item["conversions_change"] = None

            items.append(item)

        return _api_response(data=items)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/funnel")
def country_funnel(
    country: str = Query(...),
    ta: str = Query(None),
    funnel_stage: str = Query(None),
    platform: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    account_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Conversion funnel filterable by country, TA, funnel stage, branch."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query_funnel(d_from, d_to):
            q = (
                db.query(
                    func.sum(MetricsCache.impressions).label("impressions"),
                    func.sum(MetricsCache.clicks).label("clicks"),
                    func.sum(MetricsCache.searches).label("searches"),
                    func.sum(MetricsCache.add_to_cart).label("add_to_cart"),
                    func.sum(MetricsCache.checkouts).label("checkouts"),
                    func.sum(MetricsCache.conversions).label("bookings"),
                )
                .join(Campaign, Campaign.id == MetricsCache.campaign_id)
                .join(AdSet, AdSet.id == MetricsCache.ad_set_id)
                .filter(AdSet.country == country.upper())
                .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
            )
            if ta:
                q = q.filter(Campaign.ta == ta)
            if funnel_stage:
                q = q.filter(Campaign.funnel_stage == funnel_stage.upper())
            if platform:
                q = q.filter(MetricsCache.platform == platform)
            if account_id:
                q = q.filter(Campaign.account_id == account_id)
            return q.first()

        row = _query_funnel(df, dt)
        prev_row = _query_funnel(prev_from, prev_to)

        if not row or not row.impressions:
            return _api_response(data={"stages": [], "country": country, "country_name": country_name(country) or country})

        fields = ["impressions", "clicks", "searches", "add_to_cart", "checkouts", "bookings"]
        labels = ["Impression", "Click", "Search", "Add to Cart", "Checkout", "Booking"]

        stages = []
        for i, (field, label) in enumerate(zip(fields, labels)):
            val = int(getattr(row, field) or 0)
            prev_val = int(getattr(prev_row, field) or 0) if prev_row else 0

            stage = {"name": label, "value": val, "change": calc_change(val, prev_val)}
            if i > 0:
                prev = stages[i - 1]["value"]
                stage["drop_off_rate"] = round((val / prev) * 100, 1) if prev > 0 else 0
            stages.append(stage)

        return _api_response(data={
            "country": country,
            "country_name": country_name(country) or country,
            "stages": stages,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/comparison")
def country_comparison(
    platform: str = Query(None),
    ta: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    account_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Side-by-side comparison across all countries with period change."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query_countries(d_from, d_to):
            q = _base_metrics_query(db).filter(
                AdSet.country.isnot(None),
                func.length(AdSet.country) == 2,
                MetricsCache.date >= d_from,
                MetricsCache.date <= d_to,
            )
            if platform:
                q = q.filter(MetricsCache.platform == platform)
            if ta:
                q = q.filter(Campaign.ta == ta)
            if account_id:
                q = q.filter(Campaign.account_id == account_id)
            return q.group_by(AdSet.country).order_by(func.sum(MetricsCache.spend).desc()).all()

        rows = _query_countries(df, dt)
        prev_rows = _query_countries(prev_from, prev_to)
        prev_map = {r.country: r for r in prev_rows}

        items = []
        for row in rows:
            if not is_valid_country(row.country):
                continue
            kpi = _row_to_kpi(row)
            prev = prev_map.get(row.country)
            if prev:
                prev_kpi = _row_to_kpi(prev)
                kpi["spend_change"] = calc_change(kpi["total_spend"], prev_kpi["total_spend"])
                kpi["roas_change"] = calc_change(kpi["roas"], prev_kpi["roas"])
                kpi["conversions_change"] = calc_change(kpi["conversions"], prev_kpi["conversions"])
            else:
                kpi["spend_change"] = None
                kpi["roas_change"] = None
                kpi["conversions_change"] = None
            items.append(kpi)

        return _api_response(data=items)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/countries")
def list_countries(
    account_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """List available countries with display names."""
    try:
        q = (
            db.query(AdSet.country, func.count(AdSet.id).label("adset_count"))
            .filter(
                AdSet.country.isnot(None),
                AdSet.country != "Unknown",
                func.length(AdSet.country) == 2,
            )
        )
        if account_id:
            q = q.filter(AdSet.account_id == account_id)

        rows = q.group_by(AdSet.country).order_by(AdSet.country).all()

        data = []
        for row in rows:
            if is_valid_country(row.country):
                name = country_name(row.country)
                if name:
                    data.append({
                        "code": row.country,
                        "name": name,
                        "adset_count": row.adset_count,
                    })

        # Sort by display name
        data.sort(key=lambda x: x["name"])
        return _api_response(data=data)
    except Exception as e:
        return _api_response(error=str(e))
