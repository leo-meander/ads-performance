"""SURF Intraday state machine models.

Two tables, both written from app.services.surf_intraday.engine:

- SurfRun        — one row per (tactic, campaign, local_date). Carries the
                   origin_budget anchor + cumulative state used to enforce
                   the per_day cap and Double Check comparison.

- SurfCheckpoint — append-only audit row written on EVERY poll tick (even
                   no-action ones). The most recent checkpoint per run
                   doubles as the source of truth for "have we already
                   processed this spend threshold today?" → idempotency.

NEVER UPDATE SurfCheckpoint rows — they're the audit trail. Mutations to
budget/threshold/roas progress live on SurfRun.

Per-branch absolute caps (max_raise_per_click_abs / max_cut_per_click_abs)
live on AdAccount and are read by the engine — they're shared with the
manual /action-needed Apply SURF button so 1 setting drives 2 surfaces.

See migration 043_surf_intraday.py for full column commentary.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


# Status vocabulary for SurfRun.status — keep aligned with the DB check
# constraint in migration 043.
SURF_RUN_STATUS_ACTIVE = "active"        # currently being polled; revert pending
SURF_RUN_STATUS_REVERTED = "reverted"    # end-of-day revert succeeded
SURF_RUN_STATUS_CAPPED = "capped"        # hit per-day cap; no more boosts today
SURF_RUN_STATUS_ERRORED = "errored"      # Meta write failed; engine paused this run

# Tier labels for SurfCheckpoint.tier_label — match the DB check constraint.
TIER_1 = "tier_1"
TIER_2 = "tier_2"
TIER_3 = "tier_3"
DOUBLE_CHECK_CUT = "double_check_cut"
NO_ACTION = "no_action"
TIER_ERROR = "error"

# Capped_by vocabulary — recorded on SurfCheckpoint when a cap binds.
CAPPED_BY_PER_CHECK = "per_check"            # ad_accounts.max_raise_per_click_abs
CAPPED_BY_PER_DAY = "per_day"                # tactic.config.surf_limit_per_day
CAPPED_BY_MAX_MULTIPLIER = "max_multiplier"  # tactic.config.max_budget_cap_multiplier
CAPPED_BY_SANITY = "sanity_abort"            # 2.5x guard, last-line defense


class SurfRun(TimestampMixin, Base):
    """One SURF day per (tactic, campaign). UNIQUE blocks duplicate runs."""

    __tablename__ = "surf_runs"
    __table_args__ = (
        UniqueConstraint(
            "tactic_id", "campaign_id", "run_date",
            name="uq_surf_runs_tactic_campaign_date",
        ),
        CheckConstraint(
            "status IN ('active','reverted','capped','errored')",
            name="ck_surf_runs_status",
        ),
    )

    tactic_id = Column(
        UUIDType,
        ForeignKey("tactics.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Local-tz date — NOT UTC. Resolved from account.timezone at run creation
    # so revert can match the same local day boundary.
    run_date = Column(Date, nullable=False, index=True)
    timezone = Column(String(50), nullable=False)

    # Anchor: budget at 00:00 local. Revert target. Cap measurements
    # (max_budget_cap_multiplier) computed against this, not current_budget.
    origin_budget = Column(Numeric(15, 2), nullable=False)
    current_budget = Column(Numeric(15, 2), nullable=False)

    # Running tally of absolute currency raise today. Compared against
    # tactic.config.surf_limit_per_day to short-circuit further boosts.
    total_increase_today = Column(
        Numeric(15, 2), nullable=False, default=0,
    )

    # Last threshold the engine acted on. Idempotency: if current spend hasn't
    # crossed the NEXT threshold above this, the tick is a no-op.
    last_threshold_hit = Column(Numeric(15, 2), nullable=True)

    # ROAS reading at the most recent check. Double Check reads this to decide
    # if ROAS dropped >= double_check_drop_pct → cut.
    last_roas_at_check = Column(Numeric(8, 4), nullable=True)

    status = Column(
        String(20), nullable=False, default=SURF_RUN_STATUS_ACTIVE, index=True,
    )
    reverted_at = Column(DateTime(timezone=True), nullable=True)

    # Snapshot from the account at run creation. Locked here so per-check /
    # per-day caps stay denominated even if the account currency mutates.
    currency = Column(String(3), nullable=False)

    checkpoints = relationship(
        "SurfCheckpoint",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="SurfCheckpoint.checked_at.desc()",
    )


class SurfCheckpoint(Base):
    """One row per poll tick. APPEND ONLY — never UPDATE.

    Idempotency contract: the engine reads the most recent checkpoint for a
    run and compares spend_at_check + last_threshold_hit against current Meta
    spend. If no new threshold has been crossed, a NO_ACTION row is appended
    and no Meta call is made.
    """

    __tablename__ = "surf_checkpoints"
    __table_args__ = (
        CheckConstraint(
            "tier_label IN ('tier_1','tier_2','tier_3','double_check_cut','no_action','error')",
            name="ck_surf_checkpoints_tier_label",
        ),
    )

    id = Column(UUIDType, primary_key=True)
    run_id = Column(
        UUIDType,
        ForeignKey("surf_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    checked_at = Column(DateTime(timezone=True), nullable=False)

    spend_at_check = Column(Numeric(15, 2), nullable=False)
    roas_at_check = Column(Numeric(8, 4), nullable=True)
    threshold_crossed = Column(Numeric(15, 2), nullable=True)

    tier_label = Column(String(20), nullable=False)
    multiplier_applied = Column(Numeric(5, 4), nullable=True)

    budget_before = Column(Numeric(15, 2), nullable=True)
    budget_after = Column(Numeric(15, 2), nullable=True)

    # NULL = no cap was binding; otherwise one of CAPPED_BY_* constants.
    capped_by = Column(String(50), nullable=True)

    # False = dry_run mode, no-action ticks, or pre-flight cap rejected
    # the write. True = we actually invoked update_campaign_budget.
    meta_api_called = Column(Boolean, nullable=False, default=False)
    meta_api_success = Column(Boolean, nullable=True)
    meta_api_error = Column(Text, nullable=True)
    raw_meta_response = Column(JSONType, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)

    run = relationship("SurfRun", back_populates="checkpoints")
