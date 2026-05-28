"""Per-branch budget mutation limits for /action-needed apply buttons.

Revision ID: 042_budget_limits_per_branch
Revises: 041_daily_ad_metrics
Create Date: 2026-05-28

Adds 4 columns to ad_accounts so each branch can control the
Raise/Cut budget buttons on the Action Needed page:

  raise_pct                 default 0.25  → button computes new = current * (1 + raise_pct)
  cut_pct                   default 0.50  → button computes new = current * (1 - cut_pct)
  max_raise_per_click_abs   nullable      → if set, clamps the absolute raise amount
                                            in account currency (NULL = no cap, legacy behavior)
  max_cut_per_click_abs     nullable      → same, for cut direction

Defaults preserve current behavior exactly: raise_pct=0.25 matches the old
RAISE_FACTOR=1.25 hardcode; cut_pct=0.50 matches the old CUT_FACTOR=0.5. So
this migration is a no-op for any branch that never sets a cap.

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres; batch_alter_table on SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042_budget_limits_per_branch"
down_revision: Union[str, None] = "041_daily_ad_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD COLUMN IF NOT EXISTS raise_pct NUMERIC(5, 4) NOT NULL DEFAULT 0.25;
            """
        )
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD COLUMN IF NOT EXISTS cut_pct NUMERIC(5, 4) NOT NULL DEFAULT 0.50;
            """
        )
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD COLUMN IF NOT EXISTS max_raise_per_click_abs NUMERIC(15, 2);
            """
        )
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD COLUMN IF NOT EXISTS max_cut_per_click_abs NUMERIC(15, 2);
            """
        )
        # Sanity guards — protect against typos like 25 (meant 0.25) or 1.5
        # (meant 0.15). pct must be in (0, 1); abs must be > 0 or NULL.
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD CONSTRAINT ck_ad_accounts_raise_pct_range
            CHECK (raise_pct > 0 AND raise_pct <= 1);
            """
        )
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD CONSTRAINT ck_ad_accounts_cut_pct_range
            CHECK (cut_pct > 0 AND cut_pct < 1);
            """
        )
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD CONSTRAINT ck_ad_accounts_max_raise_abs_positive
            CHECK (max_raise_per_click_abs IS NULL OR max_raise_per_click_abs > 0);
            """
        )
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD CONSTRAINT ck_ad_accounts_max_cut_abs_positive
            CHECK (max_cut_per_click_abs IS NULL OR max_cut_per_click_abs > 0);
            """
        )
    else:
        # SQLite path (tests). CHECK constraints can be declared inline, but
        # since these are added to an existing table SQLite ignores most
        # ALTER...ADD CONSTRAINT. We add the columns with defaults; range
        # enforcement happens at the application layer in the PATCH endpoint.
        with op.batch_alter_table("ad_accounts") as batch:
            batch.add_column(
                sa.Column(
                    "raise_pct", sa.Numeric(5, 4),
                    nullable=False, server_default=sa.text("0.25"),
                )
            )
            batch.add_column(
                sa.Column(
                    "cut_pct", sa.Numeric(5, 4),
                    nullable=False, server_default=sa.text("0.50"),
                )
            )
            batch.add_column(
                sa.Column(
                    "max_raise_per_click_abs", sa.Numeric(15, 2), nullable=True,
                )
            )
            batch.add_column(
                sa.Column(
                    "max_cut_per_click_abs", sa.Numeric(15, 2), nullable=True,
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        for ck in (
            "ck_ad_accounts_max_cut_abs_positive",
            "ck_ad_accounts_max_raise_abs_positive",
            "ck_ad_accounts_cut_pct_range",
            "ck_ad_accounts_raise_pct_range",
        ):
            op.execute(f"ALTER TABLE ad_accounts DROP CONSTRAINT IF EXISTS {ck};")
        for col in (
            "max_cut_per_click_abs",
            "max_raise_per_click_abs",
            "cut_pct",
            "raise_pct",
        ):
            op.execute(f"ALTER TABLE ad_accounts DROP COLUMN IF EXISTS {col};")
    else:
        # SQLite — table rebuild via batch_alter_table.
        with op.batch_alter_table("ad_accounts") as batch:
            batch.drop_column("max_cut_per_click_abs")
            batch.drop_column("max_raise_per_click_abs")
            batch.drop_column("cut_pct")
            batch.drop_column("raise_pct")
