"""Campaign & metrics API endpoints for Phase 2."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.user import User
from app.routers.accounts import BRANCH_ACCOUNT_MAP, BRANCH_CURRENCY, get_account_ids_for_branches

router = APIRouter()

# Exchange rates to VND (approximate, update as needed)
FX_TO_VND = {
    "VND": 1,
    "TWD": 800,   # 1 TWD ≈ 800 VND
    "JPY": 170,   # 1 JPY ≈ 170 VND
    "USD": 25500,
}


def _get_fx_rate(currency: str) -> float:
    return FX_TO_VND.get(currency, 1)


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------- Campaigns ----------


@router.get("/campaigns")
def list_campaigns(
    platform: str | None = None,
    status: str | None = None,
    account_id: str | None = None,
    search: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """List campaigns with optional filters."""
    try:
        # Scope to the user's accessible branches for analytics
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics", requested_account_id=account_id
        )
        if not ok:
            return _api_response(error=err)

        q = db.query(Campaign).join(AdAccount, Campaign.account_id == AdAccount.id)

        if platform:
            q = q.filter(Campaign.platform == platform)
        if status:
            q = q.filter(Campaign.status == status)
        if scoped_ids is not None:
            if not scoped_ids:
                return _api_response(data={"items": [], "total": 0, "limit": limit, "offset": offset})
            q = q.filter(Campaign.account_id.in_(scoped_ids))
        if search:
            q = q.filter(Campaign.name.ilike(f"%{search}%"))

        total = q.count()
        campaigns = q.order_by(Campaign.name).offset(offset).limit(limit).all()

        # Batch-fetch account names
        account_ids = {c.account_id for c in campaigns}
        accounts_map = {}
        if account_ids:
            accs = db.query(AdAccount).filter(AdAccount.id.in_(account_ids)).all()
            accounts_map = {a.id: a for a in accs}

        items = []
        for c in campaigns:
            acc = accounts_map.get(c.account_id)
            items.append({
                "id": c.id,
                "account_id": c.account_id,
                "account_name": acc.account_name if acc else None,
                "currency": acc.currency if acc else "VND",
                "platform": c.platform,
                "platform_campaign_id": c.platform_campaign_id,
                "name": c.name,
                "status": c.status,
                "objective": c.objective,
                "daily_budget": float(c.daily_budget) if c.daily_budget else None,
                "lifetime_budget": float(c.lifetime_budget) if c.lifetime_budget else None,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })

        return _api_response(data={"items": items, "total": total, "limit": limit, "offset": offset})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: str,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Get a single campaign by ID."""
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return _api_response(error="Campaign not found")

        # Enforce scope: user must have analytics access to this campaign's account
        ok, _ids, err = scoped_account_ids(
            db, current_user, "analytics", requested_account_id=campaign.account_id
        )
        if not ok:
            return _api_response(error=err)

        acc = db.query(AdAccount).filter(AdAccount.id == campaign.account_id).first()

        return _api_response(data={
            "id": campaign.id,
            "account_id": campaign.account_id,
            "account_name": acc.account_name if acc else None,
            "currency": acc.currency if acc else "VND",
            "platform": campaign.platform,
            "platform_campaign_id": campaign.platform_campaign_id,
            "name": campaign.name,
            "status": campaign.status,
            "objective": campaign.objective,
            "daily_budget": float(campaign.daily_budget) if campaign.daily_budget else None,
            "lifetime_budget": float(campaign.lifetime_budget) if campaign.lifetime_budget else None,
            "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
            "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
            "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        })
    except Exception as e:
        return _api_response(error=str(e))


# ---------- Metrics ----------


@router.get("/campaigns/{campaign_id}/metrics")
def get_campaign_metrics(
    campaign_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Get daily metrics for a specific campaign."""
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return _api_response(error="Campaign not found")

        ok, _ids, err = scoped_account_ids(
            db, current_user, "analytics", requested_account_id=campaign.account_id
        )
        if not ok:
            return _api_response(error=err)

        q = db.query(MetricsCache).filter(MetricsCache.campaign_id == campaign_id)
        if date_from:
            q = q.filter(MetricsCache.date >= date_from)
        if date_to:
            q = q.filter(MetricsCache.date <= date_to)

        rows = q.order_by(MetricsCache.date).all()

        metrics = []
        for r in rows:
            metrics.append({
                "date": r.date.isoformat() if r.date else None,
                "spend": float(r.spend) if r.spend else 0,
                "impressions": r.impressions or 0,
                "clicks": r.clicks or 0,
                "ctr": float(r.ctr) if r.ctr else 0,
                "conversions": r.conversions or 0,
                "revenue": float(r.revenue) if r.revenue else 0,
                "roas": float(r.roas) if r.roas else 0,
                "cpa": float(r.cpa) if r.cpa else None,
                "cpc": float(r.cpc) if r.cpc else None,
                "frequency": float(r.frequency) if r.frequency else None,
            })

        return _api_response(data=metrics)
    except Exception as e:
        return _api_response(error=str(e))


def _aggregate_kpis(db: Session, d_from: date, d_to: date, platform: str | None,
                    account_id: str | None = None, account_ids: list[str] | None = None):
    """Compute aggregated KPIs for a date range.

    When no filter (all branches), converts spend/revenue to VND using FX rates.
    When account_id or account_ids set, uses raw currency values if single currency,
    otherwise converts to VND.
    """
    has_filter = account_id is not None or (account_ids is not None and len(account_ids) > 0)
    convert_to_vnd = not has_filter  # default: all branches → convert

    # Query per-account to apply FX rates
    q = db.query(
        Campaign.account_id,
        func.sum(MetricsCache.spend).label("spend"),
        func.sum(MetricsCache.impressions).label("impressions"),
        func.sum(MetricsCache.clicks).label("clicks"),
        func.sum(MetricsCache.conversions).label("conversions"),
        func.sum(MetricsCache.revenue).label("revenue"),
    ).join(Campaign, MetricsCache.campaign_id == Campaign.id)

    # Campaign-level only — exclude adset/ad rows to prevent triple counting
    q = q.filter(MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None))
    q = q.filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
    if platform:
        q = q.filter(MetricsCache.platform == platform)
    if account_id:
        q = q.filter(Campaign.account_id == account_id)
    elif account_ids:
        q = q.filter(Campaign.account_id.in_(account_ids))
        # Check if multiple currencies → need VND conversion
        currencies = db.query(AdAccount.currency).filter(
            AdAccount.id.in_(account_ids)
        ).distinct().all()
        if len(currencies) > 1:
            convert_to_vnd = True

    rows = q.group_by(Campaign.account_id).all()

    # Build account → currency map
    acc_ids = [r.account_id for r in rows]
    currency_map = {}
    if acc_ids and convert_to_vnd:
        accs = db.query(AdAccount).filter(AdAccount.id.in_(acc_ids)).all()
        currency_map = {a.id: a.currency for a in accs}

    spend = 0.0
    impressions = 0
    clicks = 0
    conversions = 0
    revenue = 0.0

    for r in rows:
        fx = _get_fx_rate(currency_map.get(r.account_id, "VND")) if convert_to_vnd else 1
        spend += float(r.spend or 0) * fx
        revenue += float(r.revenue or 0) * fx
        impressions += int(r.impressions or 0)
        clicks += int(r.clicks or 0)
        conversions += int(r.conversions or 0)

    return {
        "total_spend": spend,
        "total_revenue": revenue,
        "total_impressions": impressions,
        "total_clicks": clicks,
        "total_conversions": conversions,
        "roas": revenue / spend if spend > 0 else 0,
        "ctr": clicks / impressions if impressions > 0 else 0,
        "cpc": spend / clicks if clicks > 0 else 0,
        "cpa": spend / conversions if conversions > 0 else 0,
        "conversion_rate": conversions / clicks if clicks > 0 else 0,
    }


def _pct_change(current: float, previous: float) -> float | None:
    """Compute % change. Returns None if no previous data."""
    if previous == 0:
        return None
    return (current - previous) / previous


@router.get("/dashboard/kpis")
def get_dashboard_kpis(
    date_from: date | None = None,
    date_to: date | None = None,
    platform: str | None = None,
    account_id: str | None = None,
    branches: str | None = None,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Aggregated KPIs with period-over-period comparison."""
    try:
        # Resolve + scope requested branches/account_id to the user's permissions.
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics",
            requested_account_id=account_id,
            requested_branches=branch_list,
        )
        if not ok:
            return _api_response(error=err)
        # When admin + no filter, scoped_ids is None -> treat as "all". Otherwise use the scoped list.
        branch_account_ids = scoped_ids
        # If the explicit account_id was specified, treat it as the canonical filter
        if account_id and scoped_ids:
            account_id = scoped_ids[0]
            branch_account_ids = None

        # Default: current period = all available data (last 7 days)
        if date_to is None:
            date_to = date.today()
        if date_from is None:
            date_from = date_to - timedelta(days=6)

        # Previous period: same duration, shifted back
        period_days = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_days - 1)

        current = _aggregate_kpis(db, date_from, date_to, platform, account_id, branch_account_ids)
        previous = _aggregate_kpis(db, prev_from, prev_to, platform, account_id, branch_account_ids)

        # Add % change for each metric
        change_keys = [
            "total_spend", "total_revenue", "total_impressions", "total_clicks",
            "total_conversions", "roas", "ctr", "cpc", "cpa", "conversion_rate",
        ]
        changes = {}
        for key in change_keys:
            changes[f"{key}_change"] = _pct_change(current[key], previous[key])

        return _api_response(data={
            **current,
            **changes,
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/daily")
def get_dashboard_daily(
    date_from: date | None = None,
    date_to: date | None = None,
    platform: str | None = None,
    account_id: str | None = None,
    branches: str | None = None,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Daily aggregated metrics for dashboard charts. Converts to VND when all branches."""
    try:
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics",
            requested_account_id=account_id,
            requested_branches=branch_list,
        )
        if not ok:
            return _api_response(error=err)
        branch_account_ids = scoped_ids
        if account_id and scoped_ids:
            account_id = scoped_ids[0]
            branch_account_ids = None

        has_filter = account_id is not None or (branch_account_ids is not None and len(branch_account_ids) > 0)
        convert_to_vnd = not has_filter

        # Query per-account per-date for FX conversion
        q = db.query(
            MetricsCache.date,
            Campaign.account_id,
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        ).join(Campaign, MetricsCache.campaign_id == Campaign.id)

        # Campaign-level only — exclude adset/ad rows to prevent triple counting
        q = q.filter(MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None))
        if date_from:
            q = q.filter(MetricsCache.date >= date_from)
        if date_to:
            q = q.filter(MetricsCache.date <= date_to)
        if platform:
            q = q.filter(MetricsCache.platform == platform)
        if account_id:
            q = q.filter(Campaign.account_id == account_id)
        elif branch_account_ids:
            q = q.filter(Campaign.account_id.in_(branch_account_ids))
            # Check if multiple currencies
            currencies = db.query(AdAccount.currency).filter(
                AdAccount.id.in_(branch_account_ids)
            ).distinct().all()
            if len(currencies) > 1:
                convert_to_vnd = True

        rows = q.group_by(MetricsCache.date, Campaign.account_id).order_by(MetricsCache.date).all()

        # Build currency map
        currency_map = {}
        if convert_to_vnd:
            acc_ids = {r.account_id for r in rows}
            if acc_ids:
                accs = db.query(AdAccount).filter(AdAccount.id.in_(acc_ids)).all()
                currency_map = {a.id: a.currency for a in accs}

        # Aggregate by date with FX
        daily_map: dict[str, dict] = {}
        for r in rows:
            d = r.date.isoformat() if r.date else None
            if not d:
                continue
            fx = _get_fx_rate(currency_map.get(r.account_id, "VND")) if convert_to_vnd else 1
            if d not in daily_map:
                daily_map[d] = {"spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0}
            daily_map[d]["spend"] += float(r.spend or 0) * fx
            daily_map[d]["revenue"] += float(r.revenue or 0) * fx
            daily_map[d]["impressions"] += int(r.impressions or 0)
            daily_map[d]["clicks"] += int(r.clicks or 0)
            daily_map[d]["conversions"] += int(r.conversions or 0)

        daily = []
        for d in sorted(daily_map):
            v = daily_map[d]
            daily.append({
                "date": d,
                "spend": v["spend"],
                "impressions": v["impressions"],
                "clicks": v["clicks"],
                "conversions": v["conversions"],
                "revenue": v["revenue"],
                "roas": v["revenue"] / v["spend"] if v["spend"] > 0 else 0,
                "ctr": v["clicks"] / v["impressions"] if v["impressions"] > 0 else 0,
                "cpa": v["spend"] / v["conversions"] if v["conversions"] > 0 else 0,
            })

        return _api_response(data=daily)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/by-account")
def get_dashboard_by_account(
    date_from: date | None = None,
    date_to: date | None = None,
    platform: str | None = None,
    branches: str | None = None,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Metrics broken down by account (branch) for dashboard."""
    try:
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics", requested_branches=branch_list
        )
        if not ok:
            return _api_response(error=err)
        branch_account_ids = scoped_ids

        q = db.query(
            Campaign.account_id,
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        ).join(Campaign, MetricsCache.campaign_id == Campaign.id)

        # Campaign-level only — exclude adset/ad rows to prevent triple counting
        q = q.filter(MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None))
        if date_from:
            q = q.filter(MetricsCache.date >= date_from)
        if date_to:
            q = q.filter(MetricsCache.date <= date_to)
        if platform:
            q = q.filter(MetricsCache.platform == platform)
        if branch_account_ids:
            q = q.filter(Campaign.account_id.in_(branch_account_ids))

        rows = q.group_by(Campaign.account_id).all()

        # Fetch account names
        account_ids = [r.account_id for r in rows]
        accounts_map = {}
        if account_ids:
            accs = db.query(AdAccount).filter(AdAccount.id.in_(account_ids)).all()
            accounts_map = {a.id: a for a in accs}

        result = []
        for r in rows:
            acc = accounts_map.get(r.account_id)
            spend = float(r.spend or 0)
            conversions = int(r.conversions or 0)
            revenue = float(r.revenue or 0)
            impressions = int(r.impressions or 0)
            clicks = int(r.clicks or 0)
            result.append({
                "account_id": r.account_id,
                "account_name": acc.account_name if acc else "Unknown",
                "platform": acc.platform if acc else "unknown",
                "currency": acc.currency if acc else "VND",
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "revenue": revenue,
                "roas": revenue / spend if spend > 0 else 0,
                "ctr": clicks / impressions if impressions > 0 else 0,
                "cpa": spend / conversions if conversions > 0 else 0,
            })

        result.sort(key=lambda x: x["spend"], reverse=True)
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


def _aggregate_funnel(db: Session, d_from: date, d_to: date, platform: str | None,
                      account_id: str | None = None, account_ids: list[str] | None = None,
                      campaign_type: str | None = None):
    """Aggregate funnel metrics for a date range."""
    is_lead = campaign_type == "lead"
    q = db.query(
        func.sum(MetricsCache.impressions).label("impressions"),
        func.sum(MetricsCache.clicks).label("clicks"),
        func.sum(MetricsCache.searches).label("searches"),
        func.sum(MetricsCache.add_to_cart).label("add_to_cart"),
        func.sum(MetricsCache.checkouts).label("checkouts"),
        func.sum(MetricsCache.conversions).label("bookings"),
        func.sum(MetricsCache.landing_page_views).label("landing_page_views"),
        func.sum(MetricsCache.leads).label("leads"),
    ).join(Campaign, MetricsCache.campaign_id == Campaign.id)

    # Campaign-level only — exclude adset/ad rows to prevent triple counting
    q = q.filter(MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None))
    q = q.filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
    if platform:
        q = q.filter(MetricsCache.platform == platform)
    if account_id:
        q = q.filter(Campaign.account_id == account_id)
    elif account_ids:
        q = q.filter(Campaign.account_id.in_(account_ids))
    if campaign_type == "lead":
        q = q.filter(Campaign.name.ilike("%Lea%"))
    elif campaign_type == "sale":
        q = q.filter(~Campaign.name.ilike("%Lea%"))

    row = q.one()
    if is_lead:
        return {
            "impressions": int(row.impressions or 0),
            "clicks": int(row.clicks or 0),
            "landing_page_views": int(row.landing_page_views or 0),
            "leads": int(row.leads or 0),
            "bookings": int(row.bookings or 0),
        }
    return {
        "impressions": int(row.impressions or 0),
        "clicks": int(row.clicks or 0),
        "searches": int(row.searches or 0),
        "add_to_cart": int(row.add_to_cart or 0),
        "checkouts": int(row.checkouts or 0),
        "bookings": int(row.bookings or 0),
    }


@router.get("/dashboard/funnel")
def get_dashboard_funnel(
    date_from: date | None = None,
    date_to: date | None = None,
    platform: str | None = None,
    account_id: str | None = None,
    branches: str | None = None,
    campaign_type: str | None = None,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Funnel metrics. Sale: Impression→Click→Search→Add to cart→Checkout→Booking.
    Lead: Impression→Click→Landing Page→Form Fill→Purchase."""
    try:
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics",
            requested_account_id=account_id,
            requested_branches=branch_list,
        )
        if not ok:
            return _api_response(error=err)
        branch_account_ids = scoped_ids
        if account_id and scoped_ids:
            account_id = scoped_ids[0]
            branch_account_ids = None

        if date_to is None:
            date_to = date.today()
        if date_from is None:
            date_from = date_to - timedelta(days=6)

        period_days = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_days - 1)

        current = _aggregate_funnel(db, date_from, date_to, platform, account_id, branch_account_ids, campaign_type)
        previous = _aggregate_funnel(db, prev_from, prev_to, platform, account_id, branch_account_ids, campaign_type)

        # Build funnel steps with drop-off
        if campaign_type == "lead":
            step_keys = ["impressions", "clicks", "landing_page_views", "leads", "bookings"]
            step_labels = ["Impression", "Click", "Landing Page", "Form Fill", "Purchase"]
        else:
            step_keys = ["impressions", "clicks", "searches", "add_to_cart", "checkouts", "bookings"]
            step_labels = ["Impression", "Clicks", "Search", "Add to cart", "Checkout", "Booking"]

        steps = []
        for i, key in enumerate(step_keys):
            cur_val = current[key]
            prev_val = previous[key]
            change = _pct_change(cur_val, prev_val)

            # Drop-off: % lost from previous step
            if i == 0:
                drop_off = None
                drop_off_prev = None
                drop_off_change = None
            else:
                prev_step_cur = current[step_keys[i - 1]]
                drop_off = 1 - (cur_val / prev_step_cur) if prev_step_cur > 0 else None

                # Previous period drop-off for comparison
                prev_step_prev = previous[step_keys[i - 1]]
                drop_off_prev = 1 - (prev_val / prev_step_prev) if prev_step_prev > 0 else None

                # Drop-off change (positive = worse drop-off, negative = improved)
                if drop_off is not None and drop_off_prev is not None and drop_off_prev != 0:
                    drop_off_change = (drop_off - drop_off_prev) / abs(drop_off_prev)
                else:
                    drop_off_change = None

            steps.append({
                "key": key,
                "label": step_labels[i],
                "value": cur_val,
                "change": change,
                "drop_off": drop_off,
                "drop_off_change": drop_off_change,
            })

        return _api_response(data={
            "steps": steps,
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/dashboard/by-branch")
def get_dashboard_by_branch(
    date_from: date | None = None,
    date_to: date | None = None,
    platform: str | None = None,
    branches: str | None = None,
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Metrics broken down by branch (spend VND-normalized) for pie charts."""
    try:
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics", requested_branches=branch_list
        )
        if not ok:
            return _api_response(error=err)
        branch_account_ids = scoped_ids

        q = db.query(
            Campaign.account_id,
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        ).join(Campaign, MetricsCache.campaign_id == Campaign.id)

        # Campaign-level only — exclude adset/ad rows to prevent triple counting
        q = q.filter(MetricsCache.ad_set_id.is_(None), MetricsCache.ad_id.is_(None))
        if date_from:
            q = q.filter(MetricsCache.date >= date_from)
        if date_to:
            q = q.filter(MetricsCache.date <= date_to)
        if platform:
            q = q.filter(MetricsCache.platform == platform)
        if branch_account_ids:
            q = q.filter(Campaign.account_id.in_(branch_account_ids))

        rows = q.group_by(Campaign.account_id).all()

        account_ids = [r.account_id for r in rows]
        accounts_map = {}
        if account_ids:
            accs = db.query(AdAccount).filter(AdAccount.id.in_(account_ids)).all()
            accounts_map = {a.id: a for a in accs}

        # Map each account → branch by matching account_name substring
        def match_branch(name: str) -> str | None:
            nlow = (name or "").lower()
            for br, patterns in BRANCH_ACCOUNT_MAP.items():
                for p in patterns:
                    if p.lower() in nlow:
                        return br
            return None

        aggregates: dict[str, dict] = {}
        for r in rows:
            acc = accounts_map.get(r.account_id)
            if not acc:
                continue
            branch = match_branch(acc.account_name)
            if not branch:
                continue
            fx = _get_fx_rate(acc.currency or "VND")
            bucket = aggregates.setdefault(branch, {"spend_vnd": 0.0, "conversions": 0, "revenue_vnd": 0.0})
            bucket["spend_vnd"] += float(r.spend or 0) * fx
            bucket["conversions"] += int(r.conversions or 0)
            bucket["revenue_vnd"] += float(r.revenue or 0) * fx

        result = [
            {
                "branch": b,
                "currency": BRANCH_CURRENCY.get(b, "VND"),
                "spend_vnd": v["spend_vnd"],
                "conversions": v["conversions"],
                "revenue_vnd": v["revenue_vnd"],
            }
            for b, v in aggregates.items()
        ]
        result.sort(key=lambda x: x["spend_vnd"], reverse=True)
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))
