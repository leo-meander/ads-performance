"""Country dashboard endpoints with branch filter and period comparison."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session, aliased

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.user import User
from app.services.country_utils import (
    calc_change,
    country_name,
    get_prev_period,
    is_valid_country,
)

router = APIRouter()


# Exchange rates to VND (kept in sync with campaigns.py).
FX_TO_VND = {
    "VND": 1,
    "TWD": 800,
    "JPY": 170,
    "USD": 25500,
}


def _fx(currency: str) -> float:
    return FX_TO_VND.get(currency or "VND", 1)


def _resolve_currency(db: Session, account_id, scoped_ids):
    """Return (display_currency, convert_to_vnd).

    - Single account filter: that account's currency, no FX conversion.
    - Scoped list with exactly one currency: use it, no FX conversion.
    - Otherwise (admin all-branches, or mixed currencies): VND, convert.
    """
    if account_id:
        acc = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        return (acc.currency if acc and acc.currency else "VND"), False
    if scoped_ids:
        rows = db.query(AdAccount.currency).filter(
            AdAccount.id.in_(scoped_ids or ["__no_match__"])
        ).distinct().all()
        currencies = {r[0] for r in rows if r[0]}
        if len(currencies) == 1:
            return currencies.pop(), False
    return "VND", True


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


def _country_col():
    """Effective country dimension across platforms.

    - Meta: AdSet.country (parsed from adset-name prefix at sync time).
    - Google Search: AdSet.country (set from parent campaign trailing 2 chars).
    - Google PMax: no AdSet rows exist → falls back to Campaign.country.

    COALESCE works because Meta never sets Campaign.country, and Google sets
    both AdSet.country and Campaign.country to the same value.
    """
    return func.coalesce(AdSet.country, Campaign.country)


def _no_double_count_filter():
    """Avoid double-counting Search-style platforms that sync both campaign-
    level and ad-group-level metrics rows for the same date.

    Rule:
      - Keep ad-set-level rows (ad_set_id IS NOT NULL).
      - Keep campaign-level rows (ad_set_id IS NULL) only if the campaign has
        no AdSets at all — i.e. PMax campaigns.
    """
    _AS = aliased(AdSet)
    has_adset = exists().where(_AS.campaign_id == MetricsCache.campaign_id)
    return or_(MetricsCache.ad_set_id.isnot(None), ~has_adset)


def _apply_common_filters(q, country, platform, date_from, date_to, funnel_stage, account_id, account_ids=None):
    """Apply common filters to a metrics query (already joined with Campaign + AdSet)."""
    # Exclude ad-level rows; for campaign-level rows, only keep when the
    # campaign has no AdSets (PMax). Avoids double-counting Search.
    q = q.filter(MetricsCache.ad_id.is_(None), _no_double_count_filter())
    cc = _country_col()
    if country:
        q = q.filter(cc == country.upper())
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
    elif account_ids is not None:
        # empty list => return no rows
        q = q.filter(Campaign.account_id.in_(account_ids or ["__no_match__"]))
    # Valid country codes: 2-letter ISO, or the "ALL" multi-country marker.
    # Excludes NULL and the "Unknown" sentinel from failed parses.
    q = q.filter(
        cc.isnot(None),
        cc != "Unknown",
        (func.length(cc) == 2) | (cc == "ALL"),
    )
    return q


def _resolve_scope(db, user, account_id, branches=None):
    """Resolve analytics scoping — returns (scoped_account_id, scoped_account_ids, error).

    Accepts either:
      - account_id: single ad_accounts.id filter
      - branches: comma-separated list of branch names (e.g. "Saigon,Taipei")
    """
    branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
    ok, scoped_ids, err = scoped_account_ids(
        db, user, "analytics",
        requested_account_id=account_id,
        requested_branches=branch_list,
    )
    if not ok:
        return None, None, err
    if account_id:
        # single-account filter honored
        return account_id, None, None
    return None, scoped_ids, None


def _base_metrics_query(db: Session):
    """Base query joining metrics → campaign → adset (LEFT) → account, grouped per (country, account).

    LEFT JOIN on AdSet so Google PMax (which has no AdSet rows) still surfaces
    via Campaign.country fallback in `_country_col()`.
    """
    cc = _country_col().label("country")
    return (
        db.query(
            cc,
            Campaign.account_id.label("account_id"),
            AdAccount.currency.label("currency"),
            func.sum(MetricsCache.spend).label("total_spend"),
            func.sum(MetricsCache.impressions).label("total_impressions"),
            func.sum(MetricsCache.clicks).label("total_clicks"),
            func.sum(MetricsCache.conversions).label("total_conversions"),
            func.sum(MetricsCache.revenue).label("total_revenue"),
            func.count(func.distinct(Campaign.id)).label("campaign_count"),
        )
        .join(Campaign, Campaign.id == MetricsCache.campaign_id)
        .join(AdAccount, AdAccount.id == Campaign.account_id)
        .outerjoin(AdSet, AdSet.id == MetricsCache.ad_set_id)
    )


def _aggregate_country_rows(rows, convert_to_vnd: bool) -> dict:
    """Merge per-(country, account) rows into per-country dicts, applying FX if needed."""
    agg: dict[str, dict] = {}
    for row in rows:
        code = row.country
        cur = agg.setdefault(code, {
            "country_code": code,
            "country": country_name(code) or code,
            "total_spend": 0.0,
            "total_revenue": 0.0,
            "impressions": 0,
            "clicks": 0,
            "conversions": 0,
            "campaign_count": 0,
        })
        fx = _fx(row.currency) if convert_to_vnd else 1
        cur["total_spend"] += float(row.total_spend or 0) * fx
        cur["total_revenue"] += float(row.total_revenue or 0) * fx
        cur["impressions"] += int(row.total_impressions or 0)
        cur["clicks"] += int(row.total_clicks or 0)
        cur["conversions"] += int(row.total_conversions or 0)
        cur["campaign_count"] += int(getattr(row, "campaign_count", 0) or 0)

    for cur in agg.values():
        spend = cur["total_spend"]
        revenue = cur["total_revenue"]
        imp = cur["impressions"]
        clicks = cur["clicks"]
        conv = cur["conversions"]
        cur["roas"] = round(revenue / spend, 2) if spend > 0 else 0
        cur["ctr"] = round((clicks / imp) * 100, 2) if imp > 0 else 0
        cur["cpa"] = round(spend / conv, 2) if conv > 0 else 0
        # ROAS = CR x AOV / CPC. Carrying these on the KPI row lets the
        # frontend show period-over-period deltas alongside Spend / ROAS.
        cur["cr"] = round((conv / clicks) * 100, 2) if clicks > 0 else 0
        cur["aov"] = round(revenue / conv, 2) if conv > 0 else 0
        cur["cpc"] = round(spend / clicks, 2) if clicks > 0 else 0
    return agg


@router.get("/dashboard/country")
def country_kpi_summary(
    country: str = Query(None),
    platform: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    funnel_stage: str = Query(None),
    account_id: str = Query(None, description="Branch filter — ad_accounts.id"),
    branches: str = Query(None, description="Comma-separated branch names"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Country KPI summary with period-over-period comparison."""
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        display_currency, convert_to_vnd = _resolve_currency(db, account_id, scoped_ids)

        # Default date range
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        cc = _country_col()

        # Current period
        q = _base_metrics_query(db)
        q = _apply_common_filters(q, country, platform, df, dt, funnel_stage, account_id, scoped_ids)
        rows = q.group_by(cc, Campaign.account_id, AdAccount.currency).all()

        # Previous period
        q_prev = _base_metrics_query(db)
        q_prev = _apply_common_filters(q_prev, country, platform, prev_from, prev_to, funnel_stage, account_id, scoped_ids)
        prev_rows = q_prev.group_by(cc, Campaign.account_id, AdAccount.currency).all()

        curr_by_country = _aggregate_country_rows(rows, convert_to_vnd)
        prev_by_country = _aggregate_country_rows(prev_rows, convert_to_vnd)

        items = []
        for code, kpi in curr_by_country.items():
            if not is_valid_country(code):
                continue
            prev_kpi = prev_by_country.get(code)
            if prev_kpi:
                kpi["spend_change"] = calc_change(kpi["total_spend"], prev_kpi["total_spend"])
                kpi["revenue_change"] = calc_change(kpi["total_revenue"], prev_kpi["total_revenue"])
                kpi["roas_change"] = calc_change(kpi["roas"], prev_kpi["roas"])
                kpi["ctr_change"] = calc_change(kpi["ctr"], prev_kpi["ctr"])
                kpi["cpa_change"] = calc_change(kpi["cpa"], prev_kpi["cpa"])
                kpi["cr_change"] = calc_change(kpi["cr"], prev_kpi["cr"])
                kpi["aov_change"] = calc_change(kpi["aov"], prev_kpi["aov"])
                kpi["cpc_change"] = calc_change(kpi["cpc"], prev_kpi["cpc"])
                kpi["conversions_change"] = calc_change(kpi["conversions"], prev_kpi["conversions"])
            else:
                kpi["spend_change"] = None
                kpi["revenue_change"] = None
                kpi["roas_change"] = None
                kpi["ctr_change"] = None
                kpi["cpa_change"] = None
                kpi["cr_change"] = None
                kpi["aov_change"] = None
                kpi["cpc_change"] = None
                kpi["conversions_change"] = None
            items.append(kpi)

        return _api_response(data={
            "items": items,
            "currency": display_currency,
            "period": {"from": date_from, "to": date_to},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/daily-spend")
def daily_spend_series(
    country: str = Query(None),
    platform: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    funnel_stage: str = Query(None),
    account_id: str = Query(None),
    branches: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Daily spend + revenue + ROAS series for the performance sparkline that
    the Activity Log overlays change-markers onto. Honors the same scoping +
    filters as the main KPI endpoint."""
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        display_currency, convert_to_vnd = _resolve_currency(db, account_id, scoped_ids)

        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        q = (
            db.query(
                MetricsCache.date.label("date"),
                AdAccount.currency.label("currency"),
                func.sum(MetricsCache.spend).label("spend"),
                func.sum(MetricsCache.revenue).label("revenue"),
            )
            .join(Campaign, Campaign.id == MetricsCache.campaign_id)
            .join(AdAccount, AdAccount.id == Campaign.account_id)
            .outerjoin(AdSet, AdSet.id == MetricsCache.ad_set_id)
        )
        q = _apply_common_filters(q, country, platform, df, dt, funnel_stage, account_id, scoped_ids)
        rows = q.group_by(MetricsCache.date, AdAccount.currency).all()

        agg: dict[str, dict] = {}
        for row in rows:
            d = row.date.isoformat() if row.date else None
            if not d:
                continue
            entry = agg.setdefault(d, {"date": d, "spend": 0.0, "revenue": 0.0})
            fx = _fx(row.currency) if convert_to_vnd else 1
            entry["spend"] += float(row.spend or 0) * fx
            entry["revenue"] += float(row.revenue or 0) * fx

        series = []
        cursor = df
        while cursor <= dt:
            key = cursor.isoformat()
            entry = agg.get(key, {"date": key, "spend": 0.0, "revenue": 0.0})
            spend = entry["spend"]
            revenue = entry["revenue"]
            series.append({
                "date": key,
                "spend": round(spend, 2),
                "revenue": round(revenue, 2),
                "roas": round(revenue / spend, 4) if spend > 0 else 0,
            })
            cursor = cursor + timedelta(days=1)

        return _api_response(data={
            "series": series,
            "currency": display_currency,
            "period": {"from": date_from, "to": date_to},
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
    branches: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """TA x Funnel Stage breakdown for a specific country, with period comparison."""
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        _, convert_to_vnd = _resolve_currency(db, account_id, scoped_ids)

        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query_ta(d_from, d_to):
            cc = _country_col()
            q = (
                db.query(
                    Campaign.ta,
                    Campaign.funnel_stage,
                    AdAccount.currency.label("currency"),
                    func.sum(MetricsCache.spend).label("spend"),
                    func.sum(MetricsCache.impressions).label("impressions"),
                    func.sum(MetricsCache.clicks).label("clicks"),
                    func.sum(MetricsCache.conversions).label("conversions"),
                    func.sum(MetricsCache.revenue).label("revenue"),
                )
                .join(Campaign, Campaign.id == MetricsCache.campaign_id)
                .join(AdAccount, AdAccount.id == Campaign.account_id)
                .outerjoin(AdSet, AdSet.id == MetricsCache.ad_set_id)
                .filter(MetricsCache.ad_id.is_(None), _no_double_count_filter())
                .filter(cc == country.upper())
                .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
            )
            if platform:
                q = q.filter(MetricsCache.platform == platform)
            if account_id:
                q = q.filter(Campaign.account_id == account_id)
            elif scoped_ids is not None:
                q = q.filter(Campaign.account_id.in_(scoped_ids or ["__no_match__"]))
            return q.group_by(Campaign.ta, Campaign.funnel_stage, AdAccount.currency).all()

        def _aggregate(rows):
            agg: dict[tuple[str, str], dict] = {}
            for r in rows:
                key = (r.ta, r.funnel_stage)
                cur = agg.setdefault(key, {
                    "ta": r.ta, "funnel_stage": r.funnel_stage,
                    "spend": 0.0, "revenue": 0.0,
                    "impressions": 0, "clicks": 0, "conversions": 0,
                })
                fx = _fx(r.currency) if convert_to_vnd else 1
                cur["spend"] += float(r.spend or 0) * fx
                cur["revenue"] += float(r.revenue or 0) * fx
                cur["impressions"] += int(r.impressions or 0)
                cur["clicks"] += int(r.clicks or 0)
                cur["conversions"] += int(r.conversions or 0)
            return agg

        curr = _aggregate(_query_ta(df, dt))
        prev = _aggregate(_query_ta(prev_from, prev_to))

        items = []
        for key, cur in curr.items():
            spend = cur["spend"]
            revenue = cur["revenue"]
            impressions = cur["impressions"]
            clicks = cur["clicks"]
            conversions = cur["conversions"]
            roas = round(revenue / spend, 2) if spend > 0 else 0

            item = {
                "ta": cur["ta"],
                "funnel_stage": cur["funnel_stage"],
                "spend": spend,
                "revenue": revenue,
                "roas": roas,
                "ctr": round((clicks / impressions) * 100, 2) if impressions > 0 else 0,
                "cpa": round(spend / conversions, 2) if conversions > 0 else 0,
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "is_remarketing": cur["funnel_stage"] == "MOF",
            }

            p = prev.get(key)
            if p:
                prev_roas = round(p["revenue"] / p["spend"], 2) if p["spend"] > 0 else 0
                item["spend_change"] = calc_change(spend, p["spend"])
                item["roas_change"] = calc_change(roas, prev_roas)
                item["conversions_change"] = calc_change(conversions, p["conversions"])
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
    branches: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Conversion funnel filterable by country, TA, funnel stage, branch."""
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query_funnel(d_from, d_to):
            cc = _country_col()
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
                .outerjoin(AdSet, AdSet.id == MetricsCache.ad_set_id)
                .filter(MetricsCache.ad_id.is_(None), _no_double_count_filter())
                .filter(cc == country.upper())
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
            elif scoped_ids is not None:
                q = q.filter(Campaign.account_id.in_(scoped_ids or ["__no_match__"]))
            return q.first()

        row = _query_funnel(df, dt)
        prev_row = _query_funnel(prev_from, prev_to)

        if not row or not row.impressions:
            return _api_response(data={"stages": [], "country": country, "country_name": country_name(country) or country})

        fields = ["impressions", "clicks", "searches", "add_to_cart", "checkouts", "bookings"]
        labels = ["Impression", "Click", "Search", "Add to Cart", "Checkout", "Booking"]

        stages = []
        for i, field in enumerate(fields):
            cur_val = int(getattr(row, field) or 0)
            prev_val = int(getattr(prev_row, field) or 0) if prev_row else 0

            # Period-over-period change for the stage count
            change = calc_change(cur_val, prev_val)

            # Drop-off: fraction lost from the previous stage (1 - conv_rate)
            if i == 0:
                drop_off = None
                drop_off_change = None
            else:
                prev_step_cur = int(getattr(row, fields[i - 1]) or 0)
                prev_step_prev = int(getattr(prev_row, fields[i - 1]) or 0) if prev_row else 0

                drop_off = 1 - (cur_val / prev_step_cur) if prev_step_cur > 0 else None
                drop_off_prev = 1 - (prev_val / prev_step_prev) if prev_step_prev > 0 else None

                if drop_off is not None and drop_off_prev is not None and drop_off_prev != 0:
                    drop_off_change = (drop_off - drop_off_prev) / abs(drop_off_prev)
                else:
                    drop_off_change = None

            stages.append({
                "name": labels[i],
                "value": cur_val,
                "change": change,
                "drop_off": drop_off,
                "drop_off_change": drop_off_change,
            })

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
    branches: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Side-by-side comparison across all countries with period change."""
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        display_currency, convert_to_vnd = _resolve_currency(db, account_id, scoped_ids)

        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query_countries(d_from, d_to):
            cc = _country_col()
            q = _base_metrics_query(db).filter(
                cc.isnot(None),
                func.length(cc) == 2,
                MetricsCache.date >= d_from,
                MetricsCache.date <= d_to,
                MetricsCache.ad_id.is_(None),
                _no_double_count_filter(),
            )
            if platform:
                q = q.filter(MetricsCache.platform == platform)
            if ta:
                q = q.filter(Campaign.ta == ta)
            if account_id:
                q = q.filter(Campaign.account_id == account_id)
            elif scoped_ids is not None:
                q = q.filter(Campaign.account_id.in_(scoped_ids or ["__no_match__"]))
            return q.group_by(cc, Campaign.account_id, AdAccount.currency).all()

        rows = _query_countries(df, dt)
        prev_rows = _query_countries(prev_from, prev_to)

        curr_by_country = _aggregate_country_rows(rows, convert_to_vnd)
        prev_by_country = _aggregate_country_rows(prev_rows, convert_to_vnd)

        ordered = sorted(
            curr_by_country.values(),
            key=lambda k: k["total_spend"],
            reverse=True,
        )

        items = []
        for kpi in ordered:
            if not is_valid_country(kpi["country_code"]):
                continue
            prev_kpi = prev_by_country.get(kpi["country_code"])
            if prev_kpi:
                kpi["spend_change"] = calc_change(kpi["total_spend"], prev_kpi["total_spend"])
                kpi["roas_change"] = calc_change(kpi["roas"], prev_kpi["roas"])
                kpi["conversions_change"] = calc_change(kpi["conversions"], prev_kpi["conversions"])
            else:
                kpi["spend_change"] = None
                kpi["roas_change"] = None
                kpi["conversions_change"] = None
            items.append(kpi)

        # Kept as a plain array for frontend compatibility; display_currency is
        # exposed via /dashboard/country instead.
        _ = display_currency
        return _api_response(data=items)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/campaigns")
def country_campaign_breakdown(
    country: str = Query(None, description="ISO-2 country code; optional"),
    platform: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    funnel_stage: str = Query(None),
    account_id: str = Query(None),
    branches: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Per-campaign metrics for the active filters.

    Surfaces CR (conversion rate), AOV, CPC alongside ROAS so the user can
    pinpoint which factor is dragging a campaign's ROAS — wired from the
    "Open in Country Dashboard" deep-link on Meta recommendation cards.
    Country is optional: when omitted, all countries under the branch scope
    are aggregated per campaign.
    """
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        display_currency, convert_to_vnd = _resolve_currency(db, account_id, scoped_ids)

        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        prev_from, prev_to = get_prev_period(df, dt)

        def _query(d_from, d_to):
            cc = _country_col()
            q = (
                db.query(
                    Campaign.id.label("campaign_id"),
                    Campaign.name.label("campaign_name"),
                    Campaign.status.label("campaign_status"),
                    Campaign.funnel_stage.label("funnel_stage"),
                    Campaign.ta.label("ta"),
                    Campaign.platform.label("platform"),
                    AdAccount.account_name.label("account_name"),
                    AdAccount.currency.label("currency"),
                    func.sum(MetricsCache.spend).label("spend"),
                    func.sum(MetricsCache.impressions).label("impressions"),
                    func.sum(MetricsCache.clicks).label("clicks"),
                    func.sum(MetricsCache.conversions).label("conversions"),
                    func.sum(MetricsCache.revenue).label("revenue"),
                )
                .join(Campaign, Campaign.id == MetricsCache.campaign_id)
                .join(AdAccount, AdAccount.id == Campaign.account_id)
                .outerjoin(AdSet, AdSet.id == MetricsCache.ad_set_id)
                .filter(MetricsCache.ad_id.is_(None), _no_double_count_filter())
                .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
            )
            if country:
                q = q.filter(cc == country.upper())
            else:
                q = q.filter(
                    cc.isnot(None),
                    cc != "Unknown",
                    (func.length(cc) == 2) | (cc == "ALL"),
                )
            if platform:
                q = q.filter(MetricsCache.platform == platform)
            if funnel_stage:
                q = q.filter(Campaign.funnel_stage == funnel_stage.upper())
            if account_id:
                q = q.filter(Campaign.account_id == account_id)
            elif scoped_ids is not None:
                q = q.filter(Campaign.account_id.in_(scoped_ids or ["__no_match__"]))
            return q.group_by(
                Campaign.id, Campaign.name, Campaign.status, Campaign.funnel_stage,
                Campaign.ta, Campaign.platform,
                AdAccount.account_name, AdAccount.currency,
            ).all()

        def _fold(rows):
            agg: dict[str, dict] = {}
            for r in rows:
                cid = r.campaign_id
                cur = agg.setdefault(cid, {
                    "campaign_id": cid,
                    "campaign_name": r.campaign_name,
                    "campaign_status": r.campaign_status,
                    "funnel_stage": r.funnel_stage,
                    "ta": r.ta,
                    "platform": r.platform,
                    "account_name": r.account_name,
                    "spend": 0.0,
                    "revenue": 0.0,
                    "impressions": 0,
                    "clicks": 0,
                    "conversions": 0,
                })
                fx = _fx(r.currency) if convert_to_vnd else 1
                cur["spend"] += float(r.spend or 0) * fx
                cur["revenue"] += float(r.revenue or 0) * fx
                cur["impressions"] += int(r.impressions or 0)
                cur["clicks"] += int(r.clicks or 0)
                cur["conversions"] += int(r.conversions or 0)
            return agg

        curr = _fold(_query(df, dt))
        prev = _fold(_query(prev_from, prev_to))

        def _derive(spend, revenue, impressions, clicks, conversions):
            return {
                "roas": round(revenue / spend, 4) if spend > 0 else 0,
                "ctr": round((clicks / impressions) * 100, 4) if impressions > 0 else 0,
                "cpc": round(spend / clicks, 2) if clicks > 0 else 0,
                "cpa": round(spend / conversions, 2) if conversions > 0 else 0,
                # CR (conversion rate) = conversions / clicks. Stored as percent.
                "cr": round((conversions / clicks) * 100, 4) if clicks > 0 else 0,
                # AOV = revenue / conversions. Drives the ROAS = CR × AOV / CPC chain.
                "aov": round(revenue / conversions, 2) if conversions > 0 else 0,
            }

        items = []
        for cid, cur in curr.items():
            d = _derive(
                cur["spend"], cur["revenue"], cur["impressions"],
                cur["clicks"], cur["conversions"],
            )
            row = {**cur, **d}
            p = prev.get(cid)
            if p:
                p_d = _derive(
                    p["spend"], p["revenue"], p["impressions"],
                    p["clicks"], p["conversions"],
                )
                row["spend_change"] = calc_change(cur["spend"], p["spend"])
                row["roas_change"] = calc_change(d["roas"], p_d["roas"])
                row["cr_change"] = calc_change(d["cr"], p_d["cr"])
                row["aov_change"] = calc_change(d["aov"], p_d["aov"])
                row["cpc_change"] = calc_change(d["cpc"], p_d["cpc"])
                row["conversions_change"] = calc_change(cur["conversions"], p["conversions"])
            else:
                row["spend_change"] = None
                row["roas_change"] = None
                row["cr_change"] = None
                row["aov_change"] = None
                row["cpc_change"] = None
                row["conversions_change"] = None
            items.append(row)

        items.sort(key=lambda r: r["spend"], reverse=True)

        return _api_response(data={
            "items": items,
            "currency": display_currency,
            "period": {"from": date_from, "to": date_to},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/country/countries")
def list_countries(
    account_id: str = Query(None),
    branches: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """List available countries with display names."""
    try:
        account_id, scoped_ids, err = _resolve_scope(db, current_user, account_id, branches)
        if err:
            return _api_response(error=err)

        # Source 1: countries on AdSets (Meta + Google Search).
        adset_q = (
            db.query(AdSet.country.label("country"), func.count(AdSet.id).label("entity_count"))
            .filter(
                AdSet.country.isnot(None),
                AdSet.country != "Unknown",
                func.length(AdSet.country) == 2,
            )
        )
        if account_id:
            adset_q = adset_q.filter(AdSet.account_id == account_id)
        elif scoped_ids is not None:
            adset_q = adset_q.filter(AdSet.account_id.in_(scoped_ids or ["__no_match__"]))
        adset_rows = adset_q.group_by(AdSet.country).all()

        # Source 2: Google PMax countries (no AdSet) — read from Campaign.country.
        pmax_q = (
            db.query(Campaign.country.label("country"), func.count(Campaign.id).label("entity_count"))
            .filter(
                Campaign.platform == "google",
                Campaign.country.isnot(None),
                Campaign.country != "Unknown",
                func.length(Campaign.country) == 2,
                ~exists().where(AdSet.campaign_id == Campaign.id),
            )
        )
        if account_id:
            pmax_q = pmax_q.filter(Campaign.account_id == account_id)
        elif scoped_ids is not None:
            pmax_q = pmax_q.filter(Campaign.account_id.in_(scoped_ids or ["__no_match__"]))
        pmax_rows = pmax_q.group_by(Campaign.country).all()

        counts: dict[str, int] = {}
        for row in adset_rows:
            counts[row.country] = counts.get(row.country, 0) + int(row.entity_count or 0)
        for row in pmax_rows:
            counts[row.country] = counts.get(row.country, 0) + int(row.entity_count or 0)

        data = []
        for code, count in counts.items():
            if is_valid_country(code):
                name = country_name(code)
                if name:
                    data.append({"code": code, "name": name, "adset_count": count})

        data.sort(key=lambda x: x["name"])
        return _api_response(data=data)
    except Exception as e:
        return _api_response(error=str(e))
