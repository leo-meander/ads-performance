"""Budget monthly splits — store per-(branch, year, month) totals + channel split.

Revision ID: 026_budget_monthly_splits
Revises: 025_zero_conversions_7d_rename
Create Date: 2026-04-29

Adds a new table that stores the user's monthly budgeting intent: a single
total in VND per (branch, month) plus a flexible channel split (JSONB) so
new channels (beyond meta/google/tiktok) can be added later without schema
changes. An overflow_note captures where the budget is being borrowed from
when the channel percentages sum past 100%.

The existing budget_plans table remains the channel-level source of truth
(used by /budget/dashboard, /budget/yearly, etc). Saving a monthly split
cascades: delete existing channel plans for that (branch, month), then
insert one plan per channel with amount converted from VND using
currency_rates.rate_to_vnd for the branch's native currency.

Idempotent per project memory (IF NOT EXISTS).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026_budget_monthly_splits"
down_revision: Union[str, None] = "025_zero_conversions_7d_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_monthly_splits (
                id VARCHAR(36) PRIMARY KEY,
                branch VARCHAR(100) NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                total_vnd NUMERIC(15,2) NOT NULL,
                channel_pct JSONB NOT NULL DEFAULT '{}'::jsonb,
                overflow_note TEXT,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_bms_branch_year_month "
            "ON budget_monthly_splits (branch, year, month);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_bms_branch_year "
            "ON budget_monthly_splits (branch, year);"
        )
    else:
        op.create_table(
            "budget_monthly_splits",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("branch", sa.String(length=100), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("total_vnd", sa.Numeric(15, 2), nullable=False),
            sa.Column("channel_pct", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("overflow_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        with op.batch_alter_table("budget_monthly_splits") as batch:
            batch.create_index(
                "uq_bms_branch_year_month",
                ["branch", "year", "month"],
                unique=True,
            )
            batch.create_index("ix_bms_branch_year", ["branch", "year"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_monthly_splits;")
