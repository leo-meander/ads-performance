"""Budget module endpoints."""

import calendar
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.permissions import accessible_branches, is_admin
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.budget import BudgetPlan
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.user import User
from app.services.budget_service import (
    calculate_pace,
    create_allocation,
    create_budget_plan,
    get_budget_dashboard,
    get_channel_summary,
    get_plan_with_allocations,
    list_monthly_splits,
    upsert_monthly_split,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class PlanCreate(BaseModel):
    name: str
    branch: str
    channel: str
    month: str  # YYYY-MM-DD (first of month)
    total_budget: float
    currency: str = "VND"
    notes: str | None = None
    created_by: str | None = None


class AllocationCreate(BaseModel):
    plan_id: str
    campaign_id: str | None = None
    amount: float
    reason: str | None = None
    created_by: str | None = None


class MonthlySplitUpsert(BaseModel):
    branch: str
    year: int
    month: int  # 1-12
    total_vnd: float
    channel_pct: dict[str, float]  # {"meta": 70, "google": 20, "tiktok": 10}
    overflow_note: str | None = None


@router.get("/budget/dashboard")
def budget_dashboard(
    month: str = Query(None, description="YYYY-MM format"),
    branch: str = Query(None),
    channel: str = Query(None),
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """Budget overview with spend vs allocated per branch/channel."""
    try:
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            if branch and branch not in allowed:
                return _api_response(error=f"No view access to branch '{branch}'")

        if month:
            month_date = date.fromisoformat(f"{month}-01")
        else:
            today = date.today()
            month_date = date(today.year, today.month, 1)

        items = get_budget_dashboard(db, month_date, branch, channel)
        # Filter by user's accessible branches if no specific branch requested
        if not is_admin(current_user) and not branch:
            allowed = accessible_branches(db, current_user, "budget") or []
            items = [i for i in items if i.get("branch") in allowed]
        return _api_response(data={"month": month_date.isoformat(), "items": items})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/budget/plans")
def list_plans(
    month: str = Query(None),
    branch: str = Query(None),
    channel: str = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """List budget plans with optional filters."""
    try:
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            if branch and branch not in allowed:
                return _api_response(error=f"No view access to branch '{branch}'")

        q = db.query(BudgetPlan).filter(BudgetPlan.is_active.is_(True))
        if month:
            q = q.filter(BudgetPlan.month == date.fromisoformat(f"{month}-01"))
        if branch:
            q = q.filter(BudgetPlan.branch == branch)
        elif not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            q = q.filter(BudgetPlan.branch.in_(allowed or ["__no_match__"]))
        if channel:
            q = q.filter(BudgetPlan.channel == channel)

        total = q.count()
        plans = q.order_by(BudgetPlan.month.desc()).offset(offset).limit(limit).all()

        return _api_response(data={
            "total": total,
            "plans": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "branch": p.branch,
                    "channel": p.channel,
                    "month": p.month.isoformat(),
                    "total_budget": float(p.total_budget),
                    "currency": p.currency,
                    "notes": p.notes,
                    "created_by": p.created_by,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in plans
            ],
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/budget/plans")
def create_plan(
    body: PlanCreate,
    current_user: User = Depends(require_section("budget", "edit")),
    db: Session = Depends(get_db),
):
    """Create a new budget plan."""
    try:
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget", min_level="edit") or []
            if body.branch not in allowed:
                return _api_response(error=f"No edit access to branch '{body.branch}'")
        plan = create_budget_plan(db, body.model_dump())
        db.commit()
        return _api_response(data={
            "id": str(plan.id),
            "name": plan.name,
            "branch": plan.branch,
            "channel": plan.channel,
            "month": plan.month.isoformat(),
            "total_budget": float(plan.total_budget),
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/budget/plans/{plan_id}")
def get_plan(
    plan_id: str,
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """Get plan with all allocations."""
    try:
        result = get_plan_with_allocations(db, plan_id)
        if not result:
            return _api_response(error="Plan not found")
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            if result.get("plan", {}).get("branch") not in allowed:
                return _api_response(error="No view access to this plan's branch")
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/budget/allocations")
def create_budget_allocation(
    body: AllocationCreate,
    current_user: User = Depends(require_section("budget", "edit")),
    db: Session = Depends(get_db),
):
    """Create allocation — INSERT only, version auto-increments."""
    try:
        # Verify user has edit access to the plan's branch
        plan = db.query(BudgetPlan).filter(BudgetPlan.id == body.plan_id).first()
        if plan and not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget", min_level="edit") or []
            if plan.branch not in allowed:
                return _api_response(error=f"No edit access to branch '{plan.branch}'")
        allocation = create_allocation(db, body.model_dump())
        db.commit()
        return _api_response(data={
            "id": str(allocation.id),
            "plan_id": str(allocation.plan_id),
            "campaign_id": str(allocation.campaign_id) if allocation.campaign_id else None,
            "amount": float(allocation.amount),
            "version": allocation.version,
            "reason": allocation.reason,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/budget/channel-summary")
def channel_summary(
    month: str = Query(None, description="YYYY-MM format"),
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """Actual Spend vs Remaining Budget per channel, with branch breakdown."""
    try:
        if month:
            month_date = date.fromisoformat(f"{month}-01")
        else:
            today = date.today()
            month_date = date(today.year, today.month, 1)

        items = get_budget_dashboard(db, month_date)
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            items = [i for i in items if i.get("branch") in allowed]

        # Aggregate by channel
        channels: dict[str, dict] = {}
        for item in items:
            ch = item["channel"]
            if ch not in channels:
                channels[ch] = {"channel": ch, "total_budget": 0, "spent": 0, "branches": []}
            channels[ch]["total_budget"] += item["total_budget"]
            channels[ch]["spent"] += item["spent"]
            channels[ch]["branches"].append({
                "branch": item["branch"],
                "total_budget": item["total_budget"],
                "spent": item["spent"],
                "currency": item["currency"],
                "pace_status": item["pace_status"],
            })

        result = []
        for ch, data in sorted(channels.items()):
            budget = data["total_budget"]
            spent = data["spent"]
            result.append({
                "channel": ch,
                "total_budget": round(budget, 2),
                "spent": round(spent, 2),
                "remaining": round(budget - spent, 2),
                "spend_pct": round((spent / budget) * 100, 2) if budget > 0 else 0,
                "remaining_pct": round(((budget - spent) / budget) * 100, 2) if budget > 0 else 0,
                "branches": data["branches"],
            })

        return _api_response(data={"month": month_date.isoformat(), "channels": result})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/budget/pace")
def budget_pace(
    month: str = Query(None, description="YYYY-MM format"),
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """Pace status per branch/channel for the given month."""
    try:
        if month:
            month_date = date.fromisoformat(f"{month}-01")
        else:
            today = date.today()
            month_date = date(today.year, today.month, 1)

        items = get_budget_dashboard(db, month_date)
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            items = [i for i in items if i.get("branch") in allowed]
        return _api_response(data={
            "month": month_date.isoformat(),
            "pace": [
                {
                    "branch": item["branch"],
                    "channel": item["channel"],
                    "total_budget": item["total_budget"],
                    "spent": item["spent"],
                    "pace_status": item["pace_status"],
                    "days_remaining": item["days_remaining"],
                    "projected_spend": item["projected_spend"],
                }
                for item in items
            ],
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/budget/yearly")
def yearly_overview(
    year: int = Query(None),
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """Yearly budget overview: total allocate per branch + actual spend per month."""
    try:
        if not year:
            year = date.today().year

        allowed_set: set[str] | None = None
        if not is_admin(current_user):
            allowed_set = set(accessible_branches(db, current_user, "budget") or [])

        from app.services.budget_service import _get_account_ids_for_branch

        # Get all plans for this year
        plans = (
            db.query(BudgetPlan)
            .filter(
                BudgetPlan.is_active.is_(True),
                func.extract("year", BudgetPlan.month) == year,
            )
            .all()
        )

        # Aggregate allocate by branch per month
        branch_data: dict[str, dict] = {}
        for plan in plans:
            b = plan.branch
            if allowed_set is not None and b not in allowed_set:
                continue
            m = plan.month.month
            if b not in branch_data:
                branch_data[b] = {
                    "branch": b,
                    "currency": plan.currency,
                    "yearly_budget": 0,
                    "yearly_spent": 0,
                    "months": {},
                }
            if m not in branch_data[b]["months"]:
                branch_data[b]["months"][m] = {"budget": 0, "spent": 0}
            branch_data[b]["months"][m]["budget"] += float(plan.total_budget)
            branch_data[b]["yearly_budget"] += float(plan.total_budget)

        # Get actual spend per branch per month from metrics
        for b, data in branch_data.items():
            account_ids = _get_account_ids_for_branch(db, b)
            if not account_ids:
                continue

            rows = (
                db.query(
                    func.extract("month", MetricsCache.date).label("m"),
                    func.sum(MetricsCache.spend).label("spend"),
                )
                .join(Campaign, Campaign.id == MetricsCache.campaign_id)
                .filter(
                    Campaign.account_id.in_(account_ids),
                    func.extract("year", MetricsCache.date) == year,
                    MetricsCache.ad_set_id.is_(None),
                )
                .group_by(func.extract("month", MetricsCache.date))
                .all()
            )

            for row in rows:
                m = int(row.m)
                spent = float(row.spend or 0)
                data["yearly_spent"] += spent
                if m in data["months"]:
                    data["months"][m]["spent"] = spent
                else:
                    data["months"][m] = {"budget": 0, "spent": spent}

        # Build response
        MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        branches_order = ["Saigon", "Osaka", "1948", "Taipei", "Oani", "Bread"]
        result = []
        for b in branches_order:
            if b not in branch_data:
                continue
            data = branch_data[b]
            months_list = []
            for m in range(1, 13):
                md = data["months"].get(m, {"budget": 0, "spent": 0})
                months_list.append({
                    "month": m,
                    "month_name": MONTH_NAMES[m],
                    "budget": round(md["budget"], 2),
                    "spent": round(md["spent"], 2),
                })
            result.append({
                "branch": b,
                "currency": data["currency"],
                "yearly_budget": round(data["yearly_budget"], 2),
                "yearly_spent": round(data["yearly_spent"], 2),
                "months": months_list,
            })

        # All Branches total in VND
        CURRENCY_TO_VND = {"VND": 1, "TWD": 824.83, "JPY": 165.01}
        total_vnd_months: dict[int, dict] = {}
        total_vnd_yearly = {"budget": 0.0, "spent": 0.0}

        for b in result:
            rate = CURRENCY_TO_VND.get(b["currency"], 1)
            total_vnd_yearly["budget"] += b["yearly_budget"] * rate
            total_vnd_yearly["spent"] += b["yearly_spent"] * rate
            for m in b["months"]:
                mi = m["month"]
                if mi not in total_vnd_months:
                    total_vnd_months[mi] = {"budget": 0.0, "spent": 0.0}
                total_vnd_months[mi]["budget"] += m["budget"] * rate
                total_vnd_months[mi]["spent"] += m["spent"] * rate

        totals_vnd = {
            "yearly_budget": round(total_vnd_yearly["budget"]),
            "yearly_spent": round(total_vnd_yearly["spent"]),
            "months": [
                {
                    "month": m,
                    "month_name": MONTH_NAMES[m],
                    "budget": round(total_vnd_months.get(m, {}).get("budget", 0)),
                    "spent": round(total_vnd_months.get(m, {}).get("spent", 0)),
                }
                for m in range(1, 13)
            ],
        }

        return _api_response(data={"year": year, "branches": result, "totals_vnd": totals_vnd})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/budget/monthly-splits")
def get_monthly_splits(
    branch: str = Query(..., description="Branch key (e.g. Saigon, Osaka, 1948, Taipei, Oani)"),
    year: int = Query(...),
    current_user: User = Depends(require_section("budget")),
    db: Session = Depends(get_db),
):
    """Return all 12 months of monthly split data for (branch, year).

    Each month carries: total_vnd, total_native (converted via currency_rates),
    channel_pct, overflow_note, pct_sum. Missing months are returned as zeros
    so the UI can render a complete 12-row grid.
    """
    try:
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget") or []
            if branch not in allowed:
                return _api_response(error=f"No view access to branch '{branch}'")
        items = list_monthly_splits(db, branch, year)
        return _api_response(data={"branch": branch, "year": year, "months": items})
    except Exception as e:
        return _api_response(error=str(e))


@router.put("/budget/monthly-splits")
def put_monthly_split(
    body: MonthlySplitUpsert,
    current_user: User = Depends(require_section("budget", "edit")),
    db: Session = Depends(get_db),
):
    """Upsert one (branch, year, month) split. Cascades to budget_plans.

    overflow_note is required when sum(channel_pct) > 100. Existing channel
    plans for that month are deleted and replaced based on the new split.
    """
    try:
        if not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "budget", min_level="edit") or []
            if body.branch not in allowed:
                return _api_response(error=f"No edit access to branch '{body.branch}'")
        split = upsert_monthly_split(
            db,
            branch=body.branch,
            year=body.year,
            month=body.month,
            total_vnd=body.total_vnd,
            channel_pct=body.channel_pct,
            overflow_note=body.overflow_note,
            created_by=current_user.email,
        )
        db.commit()
        return _api_response(data={
            "id": str(split.id),
            "branch": split.branch,
            "year": split.year,
            "month": split.month,
            "total_vnd": float(split.total_vnd),
            "channel_pct": split.channel_pct,
            "overflow_note": split.overflow_note,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
