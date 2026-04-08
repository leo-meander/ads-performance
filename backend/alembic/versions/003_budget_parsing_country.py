"""Add budget tables, parsing fields, and API keys

Revision ID: 003_budget_parsing_country
Revises: 002_ad_sets_and_ads
Create Date: 2026-04-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_budget_parsing_country"
down_revision: Union[str, None] = "002_ad_sets_and_ads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Add parsing fields to existing tables ---
    op.add_column("campaigns", sa.Column("ta", sa.String(50), nullable=True))
    op.add_column("campaigns", sa.Column("funnel_stage", sa.String(10), nullable=True))
    op.add_column("ad_sets", sa.Column("country", sa.String(2), nullable=True))

    # Indexes for parsing fields
    op.create_index("idx_campaigns_ta", "campaigns", ["ta"])
    op.create_index("idx_campaigns_funnel_stage", "campaigns", ["funnel_stage"])
    op.create_index("idx_ad_sets_country", "ad_sets", ["country"])
    op.create_index("idx_adsets_country_platform", "ad_sets", ["country", "platform"])

    # --- 2. Create budget_plans table ---
    op.create_table(
        "budget_plans",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("branch", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("total_budget", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="VND"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch", "channel", "month", name="uq_budget_plan_branch_channel_month"),
    )
    op.create_index("idx_budget_plans_branch", "budget_plans", ["branch"])
    op.create_index("idx_budget_plans_month", "budget_plans", ["month"])
    op.create_index("idx_budget_plans_branch_month", "budget_plans", ["branch", "month"])

    # --- 3. Create budget_allocations table ---
    op.create_table(
        "budget_allocations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["budget_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_budget_allocations_plan_id", "budget_allocations", ["plan_id"])
    op.create_index("idx_budget_allocations_campaign_id", "budget_allocations", ["campaign_id"])

    # --- 4. Create api_keys table ---
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_request_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_count_reset_at", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("budget_allocations")
    op.drop_table("budget_plans")
    op.drop_index("idx_adsets_country_platform", table_name="ad_sets")
    op.drop_index("idx_ad_sets_country", table_name="ad_sets")
    op.drop_index("idx_campaigns_funnel_stage", table_name="campaigns")
    op.drop_index("idx_campaigns_ta", table_name="campaigns")
    op.drop_column("ad_sets", "country")
    op.drop_column("campaigns", "funnel_stage")
    op.drop_column("campaigns", "ta")
