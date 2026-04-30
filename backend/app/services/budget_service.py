"""Budget service — plan management, allocation, pace calculation."""

import calendar
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.branches import BRANCH_ACCOUNT_MAP, BRANCH_CURRENCY
from app.models.account import AdAccount
from app.models.budget import BudgetAllocation, BudgetMonthlySplit, BudgetPlan, BudgetYearlyPlan
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
            "notes": plan.notes,
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
    # Note: per-channel "where the over-spend is offset from" notes live on
    # BudgetPlan.notes (set via PATCH /api/budget/plans/{id}). overflow_note
    # on the split is kept for backward compatibility but unused by the UI.

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

    # Cascade — replace every channel plan for this (branch, month).
    # Use bulk DELETE (not per-row db.delete) to avoid session-identity-map
    # races against rows created by the legacy "New Plan" path or earlier
    # script runs. Preserve any per-channel `notes` (the "bù từ" overspend
    # offset notes set via PATCH on the Monthly tab) across the rebuild so
    # re-saving a split doesn't wipe finance commentary.
    month_date = date(year, month, 1)
    existing_plans = (
        db.query(BudgetPlan)
        .filter(BudgetPlan.branch == branch, BudgetPlan.month == month_date)
        .all()
    )
    notes_by_channel = {p.channel: p.notes for p in existing_plans if p.notes}
    existing_plan_ids = [p.id for p in existing_plans]
    if existing_plan_ids:
        # FK is ON DELETE CASCADE on Postgres, but be explicit so SQLite (and
        # any case where the FK was added without cascade) still works.
        db.query(BudgetAllocation).filter(
            BudgetAllocation.plan_id.in_(existing_plan_ids)
        ).delete(synchronize_session=False)
        db.query(BudgetPlan).filter(
            BudgetPlan.id.in_(existing_plan_ids)
        ).delete(synchronize_session=False)
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
            notes=notes_by_channel.get(channel),
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


# ============================================================
# Yearly plan (yearly total VND + per-month %) — cascades to splits
# ============================================================


def _normalize_month_pct(month_pct: dict) -> dict[int, float]:
    """Coerce arbitrary input into {1..12: float_pct} with non-negative values.

    Accepts both string and int month keys. Months not present default to 0.
    """
    out: dict[int, float] = {m: 0.0 for m in range(1, 13)}
    for k, v in (month_pct or {}).items():
        try:
            m = int(k)
            f = float(v)
        except (TypeError, ValueError):
            continue
        if m < 1 or m > 12:
            continue
        if f < 0:
            f = 0
        out[m] = f
    return out


def get_yearly_plan(db: Session, branch: str, year: int) -> dict:
    """Return the yearly plan for (branch, year), filling defaults if absent.

    Always returns a 12-month payload so the UI can render a full grid even
    on first edit.
    """
    plan = (
        db.query(BudgetYearlyPlan)
        .filter(BudgetYearlyPlan.branch == branch, BudgetYearlyPlan.year == year)
        .first()
    )
    branch_currency = BRANCH_CURRENCY.get(branch, "VND")
    rate = _get_rate_to_vnd(db, branch_currency)

    if plan is None:
        month_pct = {m: 0.0 for m in range(1, 13)}
        yearly_total_vnd = 0.0
    else:
        month_pct = _normalize_month_pct(plan.month_pct or {})
        yearly_total_vnd = float(plan.yearly_total_vnd or 0)

    months = []
    for m in range(1, 13):
        pct = month_pct.get(m, 0.0)
        budget_vnd = round(yearly_total_vnd * pct / 100, 2)
        budget_native = round(float(Decimal(str(budget_vnd)) / rate), 2) if rate > 0 else 0
        months.append({
            "month": m,
            "month_name": _MONTH_NAMES[m][:3],
            "pct": pct,
            "budget_vnd": budget_vnd,
            "budget_native": budget_native,
        })

    pct_sum = round(sum(month_pct.values()), 2)

    return {
        "branch": branch,
        "year": year,
        "currency": branch_currency,
        "yearly_total_vnd": yearly_total_vnd,
        "yearly_total_native": round(
            float(Decimal(str(yearly_total_vnd)) / rate) if rate > 0 else 0, 2
        ),
        "month_pct": {str(m): month_pct[m] for m in range(1, 13)},
        "months": months,
        "pct_sum": pct_sum,
        "updated_at": plan.updated_at.isoformat() if plan and plan.updated_at else None,
    }


def upsert_yearly_plan(
    db: Session,
    branch: str,
    year: int,
    yearly_total_vnd: float,
    month_pct: dict,
    created_by: str | None = None,
) -> BudgetYearlyPlan:
    """Upsert (branch, year) yearly plan + cascade to BudgetMonthlySplit.

    Cascade rule: for each of 12 months, recompute total_vnd =
    yearly_total_vnd * pct/100 and upsert the matching BudgetMonthlySplit
    row, preserving its existing channel_pct / overflow_note. If a month's
    split already had channel_pct set, channel-level budget_plans for that
    month are also rebuilt so per-channel amounts stay in sync.
    """
    pct = _normalize_month_pct(month_pct)
    yearly_total_dec = Decimal(str(yearly_total_vnd or 0))

    # Upsert yearly plan row
    plan = (
        db.query(BudgetYearlyPlan)
        .filter(BudgetYearlyPlan.branch == branch, BudgetYearlyPlan.year == year)
        .first()
    )
    pct_str_keys = {str(m): pct[m] for m in range(1, 13)}
    if plan is None:
        plan = BudgetYearlyPlan(
            branch=branch,
            year=year,
            yearly_total_vnd=yearly_total_dec,
            month_pct=pct_str_keys,
            created_by=created_by,
        )
        db.add(plan)
    else:
        plan.yearly_total_vnd = yearly_total_dec
        plan.month_pct = pct_str_keys
        if created_by:
            plan.created_by = created_by
    db.flush()

    # Cascade: for each month, recompute total_vnd and call upsert_monthly_split
    # so the existing cascade-to-budget_plans logic stays the single source of
    # truth. Preserve current channel_pct / overflow_note per month.
    existing_splits = {
        s.month: s
        for s in db.query(BudgetMonthlySplit)
        .filter(BudgetMonthlySplit.branch == branch, BudgetMonthlySplit.year == year)
        .all()
    }

    for m in range(1, 13):
        month_total_vnd = float((yearly_total_dec * Decimal(str(pct[m])) / Decimal("100")).quantize(Decimal("0.01")))
        existing = existing_splits.get(m)
        channel_pct = existing.channel_pct if existing else {}
        overflow_note = existing.overflow_note if existing else None
        upsert_monthly_split(
            db,
            branch=branch,
            year=year,
            month=m,
            total_vnd=month_total_vnd,
            channel_pct=channel_pct or {},
            overflow_note=overflow_note,
            created_by=created_by,
        )

    return plan
