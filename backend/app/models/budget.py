from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class BudgetPlan(TimestampMixin, Base):
    __tablename__ = "budget_plans"
    __table_args__ = (
        UniqueConstraint("branch", "channel", "month", name="uq_budget_plan_branch_channel_month"),
    )

    name = Column(String(200), nullable=False)
    branch = Column(String(100), nullable=False, index=True)  # Saigon/Taipei/1948/Osaka/Oani/Bread
    channel = Column(String(20), nullable=False)  # meta/google/tiktok
    month = Column(Date, nullable=False, index=True)  # First day of month
    total_budget = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="VND")
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(100), nullable=True)


class BudgetAllocation(TimestampMixin, Base):
    """Budget allocation — NEVER UPDATE existing rows, always INSERT with incremented version."""

    __tablename__ = "budget_allocations"

    plan_id = Column(
        UUIDType,
        ForeignKey("budget_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount = Column(Numeric(15, 2), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    reason = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)


class BudgetYearlyPlan(TimestampMixin, Base):
    """Per-(branch, year) yearly budget total + per-month % allocation.

    The user enters one yearly total in VND and 12 month percentages; saving
    cascades to BudgetMonthlySplit (monthly total_vnd = yearly * pct/100)
    while preserving each month's existing channel_pct + overflow_note.

    This is the upstream input — Channel Splits then divide each derived
    monthly total across meta/google/tiktok.
    """

    __tablename__ = "budget_yearly_plans"
    __table_args__ = (
        UniqueConstraint("branch", "year", name="uq_byp_branch_year"),
    )

    branch = Column(String(100), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    yearly_total_vnd = Column(Numeric(15, 2), nullable=False)
    # {"1": 8.33, "2": 8.33, ...} — percentages per month (1-12)
    month_pct = Column(JSONType, nullable=False, default=dict)
    created_by = Column(String(100), nullable=True)


class BudgetMonthlySplit(TimestampMixin, Base):
    """Per-(branch, year, month) total budget in VND with channel % split.

    Source of truth for the user's monthly intent. Saving cascades to
    budget_plans (one row per channel with pct > 0, amount in branch's
    native currency).

    overflow_note is required only when channel_pct values sum > 100 —
    it captures where the over-budget is offset from (e.g. KOL budget).
    """

    __tablename__ = "budget_monthly_splits"
    __table_args__ = (
        UniqueConstraint("branch", "year", "month", name="uq_bms_branch_year_month"),
    )

    branch = Column(String(100), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)  # 1-12
    total_vnd = Column(Numeric(15, 2), nullable=False)
    channel_pct = Column(JSONType, nullable=False, default=dict)  # {"meta": 70, "google": 20, "tiktok": 10}
    overflow_note = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)
