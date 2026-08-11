from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint

from app.models.base import Base, TimestampMixin, UUIDType


class WinningAdMonth(TimestampMixin, Base):
    """A creative that got a frozen WIN or LOSE verdict in a calendar month.

    The Creative Library verdict is DYNAMIC: it re-compares each combo's
    lifetime ROAS against the account's current blended ROAS, so an ad that
    won in May can silently flip to LOSE in August when the benchmark moves.
    That makes "how many winners did we ship in May, and what was the win
    rate?" unanswerable.

    This table is the answer. One row per (account, month, ad_name), written
    ONCE — either automatically, when the ad's CUMULATIVE clicks/bookings
    first cross MIN_TEST_CLICKS (verdict_source='auto', see
    winning_months_service.compute_month_verdicts), or by a human deciding an
    ad that's stuck in TEST and never accumulating enough evidence on its own
    (verdict_source='manual', see winning_months_service.award_manual_verdict)
    — and never recomputed after that. roas / benchmark_roas / conversions /
    verdict are the numbers AS OF that award, kept verbatim for the record.
    Rows are INSERT-only.

    An ad_name only ever gets ONE row across all of history for a given
    account, regardless of verdict_source: once it has a decided verdict
    (WIN or LOSE) in some month, it is excluded from candidacy in every later
    month — see winning_months_service.freeze_winning_months. This is what
    makes win_rate = WIN count / (WIN + LOSE count) for a month meaningful
    instead of double-counting an ad that keeps clearing the bar every month.

    Scope: every ad EXCEPT ones whose name contains "KOL" — both as
    candidates AND when computing the month's benchmark, so KOL traffic
    never skews the bar. Applies to manual awards too.
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

    # WIN or LOSE — the decision this ad received once it crossed the test
    # threshold that month. Every decided ad gets a row now (not just
    # winners), because win-rate % and the "never re-test a decided ad"
    # rule both need to know about LOSEs, not just WINs.
    verdict = Column(String(10), nullable=False, default="WIN", server_default="WIN", index=True)

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

    # 'auto' (freeze_winning_months decided it, the default / historical
    # behavior) or 'manual' (a human overrode a stuck-in-TEST ad — see
    # winning_months_service.award_manual_verdict). Mirrors
    # ad_combos.verdict_source / verdict_notes exactly.
    verdict_source = Column(String(10), nullable=False, default="auto", server_default="auto")
    verdict_notes = Column(Text, nullable=True)

    frozen_at = Column(DateTime(timezone=True), nullable=True)
