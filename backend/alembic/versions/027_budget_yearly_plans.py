"""Budget yearly plans — per-(branch, year) yearly total + month % allocation.

Revision ID: 027_budget_yearly_plans
Revises: 026_budget_monthly_splits
Create Date: 2026-04-30

Adds a new table that stores the user's yearly budgeting intent: one total
VND per (branch, year) plus a JSON dict of month → percentage. Saving
cascades to budget_monthly_splits (each month's total_vnd is recomputed as
yearly_total_vnd * month_pct/100), preserving each month's existing
channel_pct so Channel Splits configuration is not lost.

Idempotent per project memory (IF NOT EXISTS).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027_budget_yearly_plans"
down_revision: Union[str, None] = "026_budget_monthly_splits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_yearly_plans (
                id VARCHAR(36) PRIMARY KEY,
                branch VARCHAR(100) NOT NULL,
                year INTEGER NOT NULL,
                yearly_total_vnd NUMERIC(15,2) NOT NULL,
                month_pct JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_byp_branch_year "
            "ON budget_yearly_plans (branch, year);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_byp_branch "
            "ON budget_yearly_plans (branch);"
        )
    else:
        op.create_table(
            "budget_yearly_plans",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("branch", sa.String(length=100), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("yearly_total_vnd", sa.Numeric(15, 2), nullable=False),
            sa.Column("month_pct", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        with op.batch_alter_table("budget_yearly_plans") as batch:
            batch.create_index(
                "uq_byp_branch_year",
                ["branch", "year"],
                unique=True,
            )
            batch.create_index("ix_byp_branch", ["branch"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_yearly_plans;")
