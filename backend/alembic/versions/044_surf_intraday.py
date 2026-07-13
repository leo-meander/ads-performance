"""SURF Intraday: per-branch timezone + surf_runs + surf_checkpoints tables.

Revision ID: 044_surf_intraday
Revises: 043_approval_batches
Create Date: 2026-05-28

Builds on top of the per-branch budget caps shipped in migration 042
(commit d0e3580). This migration adds the state machine that makes SURF
auto-trigger:

1. ad_accounts.timezone  — IANA tz needed for end-of-day revert. Backfilled
   per branch ILIKE then enforced NOT NULL on Postgres. SQLite tests use a
   server_default of Asia/Ho_Chi_Minh.

2. surf_runs             — one row per (tactic, campaign, local_date). Holds
   the origin_budget snapshot taken at local midnight + cumulative state
   (last_threshold_hit, last_roas_at_check, total_increase_today). UNIQUE
   constraint blocks duplicate runs in the same local day.

3. surf_checkpoints      — append-only audit. Every poll tick (even no-op)
   writes one row; budget changes record before/after + which cap (if any)
   clamped the multiplier. Idempotency in the engine reads this table.

CRITICAL: on the money-write path. Engine logic enforces ALL safety caps
(per_check, per_day from ad_accounts.max_*_per_click_abs, max_multiplier,
sanity_2_5x) before invoking update_campaign_budget(force=True). DB
constraints here are a second line of defense (UNIQUE prevents duplicate
runs; FKs CASCADE so deleting a tactic cleans up its history).

Idempotent: IF NOT EXISTS guards + batch_alter_table on SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044_surf_intraday"
down_revision: Union[str, None] = "043_approval_batches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Branch name → IANA timezone backfill mapping. Order matters — most specific
# pattern first (Oani matches before Taipei). All MEANDER branches map to one
# of these three zones; future branches default to Asia/Ho_Chi_Minh.
_BRANCH_TZ_MAP: list[tuple[str, str]] = [
    ("%oani%",     "Asia/Taipei"),         # Oani — Taipei premium hotel
    ("%taipei%",   "Asia/Taipei"),         # Meander Taipei
    ("%osaka%",    "Asia/Tokyo"),          # Meander Osaka
    ("%saigon%",   "Asia/Ho_Chi_Minh"),    # Meander Saigon
    ("%1948%",     "Asia/Ho_Chi_Minh"),    # Meander 1948 (Saigon hostel)
    ("%bread%",    "Asia/Ho_Chi_Minh"),    # Bread (Saigon restaurant)
]

_DEFAULT_TZ = "Asia/Ho_Chi_Minh"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ----- 1. ad_accounts.timezone ------------------------------------------
    if is_postgres:
        op.execute("ALTER TABLE ad_accounts ADD COLUMN IF NOT EXISTS timezone VARCHAR(50);")
        for pattern, tz in _BRANCH_TZ_MAP:
            op.execute(
                f"UPDATE ad_accounts SET timezone = '{tz}' "
                f"WHERE timezone IS NULL AND account_name ILIKE '{pattern}';"
            )
        op.execute(
            f"UPDATE ad_accounts SET timezone = '{_DEFAULT_TZ}' WHERE timezone IS NULL;"
        )
        op.execute("ALTER TABLE ad_accounts ALTER COLUMN timezone SET NOT NULL;")
    else:
        with op.batch_alter_table("ad_accounts") as batch:
            batch.add_column(
                sa.Column("timezone", sa.String(50),
                          nullable=False, server_default=_DEFAULT_TZ)
            )

    # ----- 2. surf_runs -----------------------------------------------------
    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS surf_runs (
                id                     VARCHAR(36) PRIMARY KEY,
                tactic_id              VARCHAR(36) NOT NULL REFERENCES tactics(id) ON DELETE CASCADE,
                campaign_id            VARCHAR(36) NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                run_date               DATE NOT NULL,
                timezone               VARCHAR(50) NOT NULL,
                origin_budget          NUMERIC(15, 2) NOT NULL,
                current_budget         NUMERIC(15, 2) NOT NULL,
                total_increase_today   NUMERIC(15, 2) NOT NULL DEFAULT 0,
                last_threshold_hit     NUMERIC(15, 2),
                last_roas_at_check     NUMERIC(8, 4),
                status                 VARCHAR(20) NOT NULL DEFAULT 'active',
                reverted_at            TIMESTAMPTZ,
                currency               VARCHAR(3) NOT NULL,
                created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_surf_runs_tactic_campaign_date
                    UNIQUE (tactic_id, campaign_id, run_date),
                CONSTRAINT ck_surf_runs_status
                    CHECK (status IN ('active','reverted','capped','errored'))
            );
            """
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_surf_runs_tactic_id ON surf_runs(tactic_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_surf_runs_campaign_id ON surf_runs(campaign_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_surf_runs_run_date ON surf_runs(run_date);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_surf_runs_status ON surf_runs(status);")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_surf_runs_status_run_date "
            "ON surf_runs(status, run_date) WHERE status = 'active';"
        )
    else:
        op.create_table(
            "surf_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tactic_id", sa.String(36),
                      sa.ForeignKey("tactics.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("campaign_id", sa.String(36),
                      sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("run_date", sa.Date, nullable=False, index=True),
            sa.Column("timezone", sa.String(50), nullable=False),
            sa.Column("origin_budget", sa.Numeric(15, 2), nullable=False),
            sa.Column("current_budget", sa.Numeric(15, 2), nullable=False),
            sa.Column("total_increase_today", sa.Numeric(15, 2),
                      nullable=False, server_default=sa.text("0")),
            sa.Column("last_threshold_hit", sa.Numeric(15, 2), nullable=True),
            sa.Column("last_roas_at_check", sa.Numeric(8, 4), nullable=True),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default="active", index=True),
            sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tactic_id", "campaign_id", "run_date",
                                name="uq_surf_runs_tactic_campaign_date"),
            sa.CheckConstraint("status IN ('active','reverted','capped','errored')",
                               name="ck_surf_runs_status"),
        )

    # ----- 3. surf_checkpoints ----------------------------------------------
    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS surf_checkpoints (
                id                   VARCHAR(36) PRIMARY KEY,
                run_id               VARCHAR(36) NOT NULL REFERENCES surf_runs(id) ON DELETE CASCADE,
                checked_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                spend_at_check       NUMERIC(15, 2) NOT NULL,
                roas_at_check        NUMERIC(8, 4),
                threshold_crossed    NUMERIC(15, 2),
                tier_label           VARCHAR(20) NOT NULL,
                multiplier_applied   NUMERIC(5, 4),
                budget_before        NUMERIC(15, 2),
                budget_after         NUMERIC(15, 2),
                capped_by            VARCHAR(50),
                meta_api_called      BOOLEAN NOT NULL DEFAULT FALSE,
                meta_api_success     BOOLEAN,
                meta_api_error       TEXT,
                raw_meta_response    JSONB,
                created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT ck_surf_checkpoints_tier_label
                    CHECK (tier_label IN ('tier_1','tier_2','tier_3','double_check_cut','no_action','error'))
            );
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_surf_checkpoints_run_id_checked_at "
            "ON surf_checkpoints(run_id, checked_at DESC);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_surf_checkpoints_checked_at "
            "ON surf_checkpoints(checked_at DESC);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_surf_checkpoints_meta_writes "
            "ON surf_checkpoints(run_id, checked_at DESC) WHERE meta_api_called = TRUE;"
        )
    else:
        op.create_table(
            "surf_checkpoints",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36),
                      sa.ForeignKey("surf_runs.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("spend_at_check", sa.Numeric(15, 2), nullable=False),
            sa.Column("roas_at_check", sa.Numeric(8, 4), nullable=True),
            sa.Column("threshold_crossed", sa.Numeric(15, 2), nullable=True),
            sa.Column("tier_label", sa.String(20), nullable=False),
            sa.Column("multiplier_applied", sa.Numeric(5, 4), nullable=True),
            sa.Column("budget_before", sa.Numeric(15, 2), nullable=True),
            sa.Column("budget_after", sa.Numeric(15, 2), nullable=True),
            sa.Column("capped_by", sa.String(50), nullable=True),
            sa.Column("meta_api_called", sa.Boolean, nullable=False,
                      server_default=sa.text("0")),
            sa.Column("meta_api_success", sa.Boolean, nullable=True),
            sa.Column("meta_api_error", sa.Text, nullable=True),
            sa.Column("raw_meta_response", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "tier_label IN ('tier_1','tier_2','tier_3','double_check_cut','no_action','error')",
                name="ck_surf_checkpoints_tier_label",
            ),
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_surf_checkpoints_meta_writes;")
    op.execute("DROP INDEX IF EXISTS ix_surf_checkpoints_checked_at;")
    op.execute("DROP INDEX IF EXISTS ix_surf_checkpoints_run_id_checked_at;")
    op.execute("DROP TABLE IF EXISTS surf_checkpoints;")

    op.execute("DROP INDEX IF EXISTS ix_surf_runs_status_run_date;")
    op.execute("DROP INDEX IF EXISTS ix_surf_runs_status;")
    op.execute("DROP INDEX IF EXISTS ix_surf_runs_run_date;")
    op.execute("DROP INDEX IF EXISTS ix_surf_runs_campaign_id;")
    op.execute("DROP INDEX IF EXISTS ix_surf_runs_tactic_id;")
    op.execute("DROP TABLE IF EXISTS surf_runs;")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS timezone;")
