"""Add Meta Ads playbook recommendation engine tables

Revision ID: 013_meta_recommendations
Revises: 012_seasonality_country_code
Create Date: 2026-04-19

Mirrors the Google Ads recommendation table (011) but with Meta-specific
columns: ad_set_id replaces ad_group_id/asset_group_id, funnel_stage and
targeted_country are stored so UI can filter per-branch / per-country.

Idempotent per project memory: uses IF NOT EXISTS where possible and wraps
the partial unique index in CREATE UNIQUE INDEX IF NOT EXISTS so re-running
the migration over a Supabase paste is safe. Seasonality events are shared
with Google — we do not create a separate meta_seasonality_events table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_meta_recommendations"
down_revision: Union[str, None] = "012_seasonality_country_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("SET LOCAL statement_timeout = 0")

    # Idempotent guard: the prod SQL paste at 013_meta_recommendations.sql may
    # have already created this table + indexes. Skip the Alembic create path
    # in that case so `alembic upgrade head` still moves the version marker.
    inspector = sa.inspect(bind)
    if "meta_recommendations" in inspector.get_table_names():
        return

    # ── meta_recommendations ──────────────────────────────────
    op.create_table(
        "meta_recommendations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("rec_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "account_id",
            sa.String(length=36),
            sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            sa.String(length=36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "ad_set_id",
            sa.String(length=36),
            sa.ForeignKey("ad_sets.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "ad_id",
            sa.String(length=36),
            sa.ForeignKey("ads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("entity_level", sa.String(length=20), nullable=False),
        sa.Column("funnel_stage", sa.String(length=10), nullable=True),
        sa.Column("targeted_country", sa.String(length=2), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("detector_finding", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("suggested_action", sa.JSON(), nullable=False),
        sa.Column("auto_applicable", sa.Boolean(), nullable=False),
        sa.Column("warning_text", sa.Text(), nullable=False),
        sa.Column("sop_reference", sa.String(length=40), nullable=True),
        sa.Column("dedup_key", sa.String(length=180), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.String(length=36), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", sa.String(length=36), nullable=True),
        sa.Column("dismiss_reason", sa.Text(), nullable=True),
        sa.Column(
            "action_log_id",
            sa.String(length=36),
            sa.ForeignKey("action_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_task_id", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_meta_recs_rec_type", "meta_recommendations", ["rec_type"])
    op.create_index("ix_meta_recs_severity", "meta_recommendations", ["severity"])
    op.create_index("ix_meta_recs_status", "meta_recommendations", ["status"])
    op.create_index("ix_meta_recs_account_id", "meta_recommendations", ["account_id"])
    op.create_index("ix_meta_recs_campaign_id", "meta_recommendations", ["campaign_id"])
    op.create_index("ix_meta_recs_ad_set_id", "meta_recommendations", ["ad_set_id"])
    op.create_index("ix_meta_recs_ad_id", "meta_recommendations", ["ad_id"])
    op.create_index("ix_meta_recs_funnel_stage", "meta_recommendations", ["funnel_stage"])
    op.create_index("ix_meta_recs_targeted_country", "meta_recommendations", ["targeted_country"])
    op.create_index("ix_meta_recs_dedup_key", "meta_recommendations", ["dedup_key"])
    op.create_index(
        "ix_meta_recs_account_status_severity",
        "meta_recommendations",
        ["account_id", "status", "severity"],
    )
    op.create_index(
        "ix_meta_recs_campaign_status",
        "meta_recommendations",
        ["campaign_id", "status"],
    )
    op.create_index(
        "ix_meta_recs_rec_type_status",
        "meta_recommendations",
        ["rec_type", "status"],
    )
    # Partial unique index: one pending recommendation per dedup_key at a time.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_meta_recs_dedup_pending "
        "ON meta_recommendations (dedup_key) WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_meta_recs_expires_pending "
        "ON meta_recommendations (expires_at) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_meta_recs_expires_pending")
    op.execute("DROP INDEX IF EXISTS uq_meta_recs_dedup_pending")
    op.drop_index("ix_meta_recs_rec_type_status", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_campaign_status", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_account_status_severity", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_dedup_key", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_targeted_country", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_funnel_stage", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_ad_id", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_ad_set_id", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_campaign_id", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_account_id", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_status", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_severity", table_name="meta_recommendations")
    op.drop_index("ix_meta_recs_rec_type", table_name="meta_recommendations")
    op.drop_table("meta_recommendations")
