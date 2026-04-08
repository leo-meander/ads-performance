"""Add ad_sets and ads tables, extend metrics_cache and action_logs

Revision ID: 002_ad_sets_and_ads
Revises: 001_initial
Create Date: 2026-04-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# Use JSON for SQLite compatibility; PostgreSQL will treat it as JSONB at runtime
# because the ORM model uses JSONType (which maps to JSON on both dialects).

revision: str = "002_ad_sets_and_ads"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Create ad_sets table ---
    op.create_table(
        "ad_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("platform_adset_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("optimization_goal", sa.String(100), nullable=True),
        sa.Column("billing_event", sa.String(50), nullable=True),
        sa.Column("daily_budget", sa.Numeric(15, 2), nullable=True),
        sa.Column("lifetime_budget", sa.Numeric(15, 2), nullable=True),
        sa.Column("targeting", sa.JSON(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["ad_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("platform_adset_id"),
    )
    op.create_index("ix_ad_sets_campaign_id", "ad_sets", ["campaign_id"])
    op.create_index("ix_ad_sets_account_id", "ad_sets", ["account_id"])
    op.create_index("ix_ad_sets_platform", "ad_sets", ["platform"])
    op.create_index("ix_ad_sets_status", "ad_sets", ["status"])

    # --- 2. Create ads table ---
    op.create_table(
        "ads",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("ad_set_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("platform_ad_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("creative_id", sa.String(100), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ad_set_id"], ["ad_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["ad_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("platform_ad_id"),
    )
    op.create_index("ix_ads_ad_set_id", "ads", ["ad_set_id"])
    op.create_index("ix_ads_campaign_id", "ads", ["campaign_id"])
    op.create_index("ix_ads_account_id", "ads", ["account_id"])
    op.create_index("ix_ads_platform", "ads", ["platform"])
    op.create_index("ix_ads_status", "ads", ["status"])

    # --- 3. Add ad_set_id and ad_id to metrics_cache ---
    # SQLite does not support ADD CONSTRAINT for FK, so skip FK constraints here.
    # The ORM models define the FK relationships. On PostgreSQL, run the full migration.
    with op.batch_alter_table("metrics_cache") as batch_op:
        batch_op.add_column(sa.Column("ad_set_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("ad_id", sa.String(36), nullable=True))
        batch_op.drop_index("ix_metrics_cache_campaign_date")
        batch_op.create_index("ix_metrics_cache_ad_set_id", ["ad_set_id"])
        batch_op.create_index("ix_metrics_cache_ad_id", ["ad_id"])
        batch_op.create_index("ix_metrics_cache_entity_date", ["campaign_id", "ad_set_id", "ad_id", "date"])

    # --- 4. Add ad_set_id and ad_id to action_logs ---
    with op.batch_alter_table("action_logs") as batch_op:
        batch_op.add_column(sa.Column("ad_set_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("ad_id", sa.String(36), nullable=True))
        batch_op.create_index("ix_action_logs_ad_set_id", ["ad_set_id"])
        batch_op.create_index("ix_action_logs_ad_id", ["ad_id"])

    # --- 5. Add entity_level to automation_rules ---
    with op.batch_alter_table("automation_rules") as batch_op:
        batch_op.add_column(sa.Column("entity_level", sa.String(20), nullable=False, server_default="campaign"))
        batch_op.create_index("ix_automation_rules_entity_level", ["entity_level"])


def downgrade() -> None:
    # Remove entity_level from automation_rules
    op.drop_index("ix_automation_rules_entity_level", table_name="automation_rules")
    op.drop_column("automation_rules", "entity_level")

    # Remove ad_set_id and ad_id from action_logs
    op.drop_index("ix_action_logs_ad_id", table_name="action_logs")
    op.drop_index("ix_action_logs_ad_set_id", table_name="action_logs")
    op.drop_constraint("fk_action_logs_ad_id", "action_logs", type_="foreignkey")
    op.drop_constraint("fk_action_logs_ad_set_id", "action_logs", type_="foreignkey")
    op.drop_column("action_logs", "ad_id")
    op.drop_column("action_logs", "ad_set_id")

    # Remove ad_set_id and ad_id from metrics_cache
    op.drop_index("ix_metrics_cache_entity_date", table_name="metrics_cache")
    op.drop_index("ix_metrics_cache_ad_id", table_name="metrics_cache")
    op.drop_index("ix_metrics_cache_ad_set_id", table_name="metrics_cache")
    op.drop_constraint("fk_metrics_cache_ad_id", "metrics_cache", type_="foreignkey")
    op.drop_constraint("fk_metrics_cache_ad_set_id", "metrics_cache", type_="foreignkey")
    op.drop_column("metrics_cache", "ad_id")
    op.drop_column("metrics_cache", "ad_set_id")
    op.create_index("ix_metrics_cache_campaign_date", "metrics_cache", ["campaign_id", "date"], unique=True)

    # Drop new tables
    op.drop_table("ads")
    op.drop_table("ad_sets")
