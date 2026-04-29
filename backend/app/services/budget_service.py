"""Budget service — plan management, allocation, pace calculation."""

import calendar
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.branches import BRANCH_ACCOUNT_MAP, BRANCH_CURRENCY
from app.models.account import AdAccount
from app.models.budget import BudgetAllocation, BudgetMonthlySplit, BudgetPlan
from app.models.campaign import Campaign
from app.models.currency_rate import CurrencyRate
from app.models.metrics import MetricsCache

logger = logging.getLogger(__name__)


# Used to auto-name the per-channel BudgetPlan rows generated from a split.
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _get_account_ids_for_branch(db: Session, branch: str) -> list[str]:
    """Get all account IDs that belong to a branch."""
    patterns = BRANCH_ACCOUNT_MAP.get(branch, [branch])
    account_ids = []
    for pattern in patterns:
        accounts = db.query(AdAccount.id).filter(
            AdAccount.account_name.ilike(f"%{pattern}%"),
            AdAccount.is_active.is_(True),
        ).all()
        account_ids.extend([str(a.id) for a in accounts])
    return list(set(account_ids))


def get_budget_dashboard(
    db: Session,
    month: date,
    branch: str | None = None,
    channel: str | None = None,
) -> list[dict]:
    """Return budget overview with spend vs allocated per branch/channel."""
    q = db.query(BudgetPlan).filter(
        BudgetPlan.month == month,
        BudgetPlan.is_active.is_(True),
    )
    if branch:
        q = q.filter(BudgetPlan.branch == branch)
    if channel:
        q = q.filter(BudgetPlan.channel == channel)

    plans = q.order_by(BudgetPlan.branch, BudgetPlan.channel).all()
    items = []

    for plan in plans:
        allocated = _get_total_allocated(db, plan.id)
        spent = _get_actual_spend(db, plan, month)

        pace_info = calculate_pace(
            total_budget=float(plan.total_budget),
            actual_spend=float(spent),
            month=month,
        )

        items.append({
            "plan_id": str(plan.id),
            "name": plan.name,
            "branch": plan.branch,
            "channel": plan.channel,
            "total_budget": float(plan.total_budget),
            "allocated": float(allocated),
            "spent": float(spent),
            "pace_status": pace_info["status"],
            "days_remaining": pace_info["days_remaining"],
            "projected_spend": pace_info["projected_spend"],
            "currency": plan.currency,
        })

    return items


def get_channel_summary(db: Session, month: date) -> list[dict]:
    """Aggregate budget vs spend by channel for the given month."""
    plans = db.query(BudgetPlan).filter(
        BudgetPlan.month == month,
        BudgetPlan.is_active.is_(True),
    ).all()

    channel_data: dict[str, dict] = {}

    for plan in plans:
        ch = plan.channel
        if ch not in channel_data:
            channel_data[ch] = {"channel": ch, "total_budget": 0.0, "spent": 0.0}

        spent = float(_get_actual_spend(db, plan, month))
        budget = float(plan.total_budget)

        # Normalize to VND for cross-currency aggregation
        if plan.currency == "TWD":
            budget *= 824.83
            spent *= 824.83  # spend is already in native, but metrics are in native currency
        elif plan.currency == "JPY":
            budget *= 165.01

        # Actually, metrics spend is stored in platform's native currency per account
        # So we need to just sum the actual metrics spend (already in native) and budget (converted back to VND)
        channel_data[ch]["total_budget"] += float(plan.total_budget)
        channel_data[ch]["spent"] += float(_get_actual_spend(db, plan, month))

    result = []
    for ch, data in sorted(channel_data.items()):
        budget = data["total_budget"]
        spent = data["spent"]
        spend_pct = round((spent / budget) * 100, 2) if budget > 0 else 0
        remaining_pct = round(((budget - spent) / budget) * 100, 2) if budget > 0 else 0
        result.append({
            "channel": ch,
            "total_budget": budget,
            "spent": spent,
            "remaining": budget - spent,
            "spend_pct": spend_pct,
            "remaining_pct": remaining_pct,
        })

    return result


def _get_total_allocated(db: Session, plan_id: str) -> Decimal:
    """Sum allocations for a plan."""
    result = db.query(func.sum(BudgetAllocation.amount)).filter(
        BudgetAllocation.plan_id == plan_id,
    ).scalar()
    return result or Decimal("0")


def _get_actual_spend(db: Session, plan: BudgetPlan, month: date) -> Decimal:
    """Get actual spend from metrics_cache for the plan's branch + channel + month."""
    year = month.year
    month_num = month.month
    last_day = calendar.monthrange(year, month_num)[1]
    start = date(year, month_num, 1)
    end = date(year, month_num, last_day)

    # Get account IDs for this branch
    account_ids = _get_account_ids_for_branch(db, plan.branch)
    if not account_ids:
        return Decimal("0")

    # Sum spend for this branch's accounts + platform + month
    result = (
        db.query(func.sum(MetricsCache.spend))
        .join(Campaign, Campaign.id == MetricsCache.campaign_id)
        .filter(
            Campaign.account_id.in_(account_ids),
            MetricsCache.platform == plan.channel,
            MetricsCache.date >= start,
            MetricsCache.date <= end,
            MetricsCache.ad_set_id.is_(None),  # campaign-level metrics only
        )
        .scalar()
    )
    return result or Decimal("0")


def calculate_pace(total_budget: float, actual_spend: float, month: date) -> dict:
    """Calculate pace status for a budget plan."""
    year = month.year
    month_num = month.month
    days_in_month = calendar.monthrange(year, month_num)[1]

    today = date.today()
    if today.year == year and today.month == month_num:
        days_elapsed = (today - date(year, month_num, 1)).days + 1
    else:
        days_elapsed = days_in_month

    days_remaining = max(0, days_in_month - days_elapsed)

    if days_elapsed > 0 and total_budget > 0:
        projected_spend = (actual_spend / days_elapsed) * days_in_month
    else:
        projected_spend = 0.0

    if projected_spend > total_budget * 1.1:
        status = "Over"
    elif projected_spend < total_budget * 0.9:
        status = "Under"
    else:
        status = "On Track"

    return {
        "status": status,
        "days_remaining": days_remaining,
        "days_elapsed": days_elapsed,
        "projected_spend": round(projected_spend, 2),
    }


def create_budget_plan(db: Session, data: dict) -> BudgetPlan:
    """Create a new budget plan."""
    plan = BudgetPlan(
        name=data["name"],
        branch=data["branch"],
        channel=data["channel"],
        month=data["month"],
        total_budget=data["total_budget"],
        currency=data.get("currency", "VND"),
        notes=data.get("notes"),
        created_by=data.get("created_by"),
    )
    db.add(plan)
    db.flush()
    return plan


def create_allocation(db: Session, data: dict) -> BudgetAllocation:
    """Create a new allocation — NEVER update, always INSERT with incremented version."""
    max_version = db.query(func.max(BudgetAllocation.version)).filter(
        BudgetAllocation.plan_id == data["plan_id"],
    ).scalar() or 0

    allocation = BudgetAllocation(
        plan_id=data["plan_id"],
        campaign_id=data.get("campaign_id"),
        amount=data["amount"],
        version=max_version + 1,
        reason=data.get("reason"),
        created_by=data.get("created_by"),
    )
    db.add(allocation)
    db.flush()
    return allocation


def get_plan_with_allocations(db: Session, plan_id: str) -> dict | None:
    """Get a plan with all its allocations."""
    plan = db.query(BudgetPlan).filter(BudgetPlan.id == plan_id).first()
    if not plan:
        return None

    allocations = (
        db.query(BudgetAllocation)
        .filter(BudgetAllocation.plan_id == plan_id)
        .order_by(BudgetAllocation.version.desc())
        .all()
    )

    return {
        "id": str(plan.id),
        "name": plan.name,
        "branch": plan.branch,
        "channel": plan.channel,
        "month": plan.month.isoformat(),
        "total_budget": float(plan.total_budget),
        "currency": plan.currency,
        "notes": plan.notes,
        "is_active": plan.is_active,
        "created_by": plan.created_by,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "allocations": [
            {
                "id": str(a.id),
                "campaign_id": str(a.campaign_id) if a.campaign_id else None,
                "amount": float(a.amount),
                "version": a.version,
                "reason": a.reason,
                "created_by": a.created_by,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in allocations
        ],
    }


# ============================================================
# Monthly split (total VND + channel %) — cascades to budget_plans
# ============================================================


def _get_rate_to_vnd(db: Session, currency: str) -> Decimal:
    """Look up rate_to_vnd for `currency` from the currency_rates table.

    Falls back to 1 if the row is missing so the import never crashes —
    the user can fix the rate in Settings and re-save the split.
    """
    if currency == "VND":
        return Decimal("1")
    row = db.query(CurrencyRate).filter(CurrencyRate.currency == currency).first()
    if not row or not row.rate_to_vnd:
        logger.warning("No currency_rates row for %s — defaulting to 1", currency)
        return Decimal("1")
    return Decimal(str(row.rate_to_vnd))


def _normalize_pct(channel_pct: dict) -> dict[str, float]:
    """Coerce arbitrary input into {channel: float_pct} with non-negative values."""
    out: dict[str, float] = {}
    for ch, v in (channel_pct or {}).items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f < 0:
            f = 0
        out[str(ch).lower()] = f
    return out


def upsert_monthly_split(
    db: Session,
    branch: str,
    year: int,
    month: int,
    total_vnd: float,
    channel_pct: dict,
    overflow_note: str | None = None,
    created_by: str | None = None,
) -> BudgetMonthlySplit:
    """Upsert (branch, year, month) split + cascade to budget_plans.

    Cascade rule: delete every existing budget_plan for that (branch, month)
    across ALL channels, then insert one new plan per channel where pct > 0.
    The plan amount is in the branch's native currency, converted from
    total_vnd via currency_rates.rate_to_vnd.
    """
    if month < 1 or month > 12:
        raise ValueError("month must be 1-12")

    pct = _normalize_pct(channel_pct)
    pct_sum = sum(pct.values())

    if pct_sum > 100 and not (overflow_note or "").strip():
        raise ValueError(
            f"Channel % sum is {pct_sum:.1f}% (>100%) — overflow_note is required"
        )

    branch_currency = BRANCH_CURRENCY.get(branch, "VND")
    rate_to_vnd = _get_rate_to_vnd(db, branch_currency)
    total_vnd_dec = Decimal(str(total_vnd))
    total_native = total_vnd_dec / rate_to_vnd if rate_to_vnd > 0 else Decimal("0")

    # Upsert split row
    split = (
        db.query(BudgetMonthlySplit)
        .filter(
            BudgetMonthlySplit.branch == branch,
            BudgetMonthlySplit.year == year,
            BudgetMonthlySplit.month == month,
        )
        .first()
    )
    if split is None:
        split = BudgetMonthlySplit(
            branch=branch,
            year=year,
            month=month,
            total_vnd=total_vnd_dec,
            channel_pct=pct,
            overflow_note=(overflow_note or None),
            created_by=created_by,
        )
        db.add(split)
    else:
        split.total_vnd = total_vnd_dec
        split.channel_pct = pct
        split.overflow_note = (overflow_note or None)
        if created_by:
            split.created_by = created_by

    # Cascade — replace every channel plan for this (branch, month)
    month_date = date(year, month, 1)
    existing_plans = (
        db.query(BudgetPlan)
        .filter(
            BudgetPlan.branch == branch,
            BudgetPlan.month == month_date,
        )
        .all()
    )
    for p in existing_plans:
        # Detach allocations first (FK CASCADE handles this, but be explicit
        # so SQLite without cascade also works).
        db.query(BudgetAllocation).filter(BudgetAllocation.plan_id == p.id).delete()
        db.delete(p)
    db.flush()

    month_label = _MONTH_NAMES[month]
    for channel, p in pct.items():
        if p <= 0:
            continue
        amount = (total_native * Decimal(str(p)) / Decimal("100")).quantize(Decimal("0.01"))
        plan = BudgetPlan(
            name=f"{branch} {channel.title()} {month_label} {year}",
            branch=branch,
            channel=channel,
            month=month_date,
            total_budget=amount,
            currency=branch_currency,
            notes=(overflow_note or None),
            created_by=created_by,
        )
        db.add(plan)

    db.flush()
    return split


def list_monthly_splits(db: Session, branch: str, year: int) -> list[dict]:
    """Return all 12 months for (branch, year). Missing months return zeros."""
    rows = (
        db.query(BudgetMonthlySplit)
        .filter(
            BudgetMonthlySplit.branch == branch,
            BudgetMonthlySplit.year == year,
        )
        .all()
    )
    by_month = {r.month: r for r in rows}
    branch_currency = BRANCH_CURRENCY.get(branch, "VND")
    rate = _get_rate_to_vnd(db, branch_currency)

    out = []
    for m in range(1, 13):
        r = by_month.get(m)
        if r is None:
            out.append({
                "branch": branch,
                "year": year,
                "month": m,
                "total_vnd": 0,
                "total_native": 0,
                "currency": branch_currency,
                "channel_pct": {},
                "overflow_note": None,
                "pct_sum": 0,
            })
            continue
        pct = r.channel_pct or {}
        total_vnd = float(r.total_vnd or 0)
        total_native = float(Decimal(str(total_vnd)) / rate) if rate > 0 else 0
        out.append({
            "branch": branch,
            "year": year,
            "month": m,
            "total_vnd": total_vnd,
            "total_native": round(total_native, 2),
            "currency": branch_currency,
            "channel_pct": pct,
            "overflow_note": r.overflow_note,
            "pct_sum": round(sum(float(v) for v in pct.values()), 2),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out
