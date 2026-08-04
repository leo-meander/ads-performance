from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint

from app.models.base import Base, TimestampMixin, UUIDType


class WinningAdMonth(TimestampMixin, Base):
    """A creative that WON in a given calendar month — frozen at award time.

    The Creative Library verdict is DYNAMIC: it re-compares each combo's
    lifetime ROAS against the account's current blended ROAS, so an ad that
    won in May can silently flip to LOSE in August when the benchmark moves.
    That makes "how many winners did we ship in May?" unanswerable.

    This table is the answer. One row per (account, month, ad_name), written
    ONCE when the ad first clears that month's bar and never recomputed —
    roas / benchmark_roas / conversions are the numbers AS OF the award, kept
    verbatim for the record. Rows are INSERT-only: a later benchmark shift
    can add new winners to a month, never demote existing ones.

    Scope: only ads whose name contains "CRTV" (the creative-team naming
    convention) are considered — both as candidates AND when computing the
    month's benchmark, so KOL/other traffic never skews the bar.
    """

    __tablename__ = "winning_ad_months"
    __table_args__ = (
        UniqueConstraint("account_id", "month", "ad_name", name="uq_winning_ad_month"),
    )

    account_id = Column(
        UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    month = Column(Date, nullable=False, index=True)  # first day of the month
    ad_name = Column(String(500), nullable=False, index=True)

    # Best-effort link back to the Creative Library. NULL when the ad has no
    # combo row yet (combos are created manually / by the creative sync).
    combo_id = Column(
        String(10), ForeignKey("ad_combos.combo_id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Parsed dimensions, copied off the combo at award time so the monthly
    # view keeps working even if the combo is re-parsed later.
    target_audience = Column(String(30), nullable=True)
    country = Column(String(10), nullable=True)

    # Frozen performance — that month only, not lifetime.
    spend = Column(Numeric(15, 2), nullable=True)
    revenue = Column(Numeric(15, 2), nullable=True)
    impressions = Column(Integer, nullable=True)
    clicks = Column(Integer, nullable=True)
    conversions = Column(Integer, nullable=True)
    roas = Column(Numeric(8, 4), nullable=True)
    # The bar the ad cleared: the account's blended CRTV ROAS for that month.
    benchmark_roas = Column(Numeric(8, 4), nullable=True)

    frozen_at = Column(DateTime(timezone=True), nullable=True)
