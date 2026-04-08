"""Add approval system: users, combo_approvals, approval_reviewers, notifications, campaign_auto_configs

Revision ID: 005_approval_system
Revises: 004_spy_ads_tables
Create Date: 2026-04-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_approval_system"
down_revision: Union[str, None] = "004_spy_ads_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_email", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_is_active", "users", ["is_active"])

    # ── combo_approvals ──────────────────────────────────────
    op.create_table(
        "combo_approvals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("combo_id", sa.String(36), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING_APPROVAL'")),
        sa.Column("submitted_by", sa.String(36), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("working_file_url", sa.Text(), nullable=True),
        sa.Column("working_file_label", sa.String(100), nullable=True),
        sa.Column("launch_campaign_id", sa.String(36), nullable=True),
        sa.Column("launch_meta_ad_id", sa.String(100), nullable=True),
        sa.Column("launch_status", sa.String(20), nullable=True),
        sa.Column("launch_error", sa.Text(), nullable=True),
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["combo_id"], ["ad_combos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["launch_campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_combo_approvals_combo_id", "combo_approvals", ["combo_id"])
    op.create_index("idx_combo_approvals_submitted_by", "combo_approvals", ["submitted_by"])
    op.create_index("idx_combo_approvals_status", "combo_approvals", ["status"])

    # ── approval_reviewers ───────────────────────────────────
    op.create_table(
        "approval_reviewers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("approval_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_email_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_system_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["approval_id"], ["combo_approvals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_approval_reviewers_approval_id", "approval_reviewers", ["approval_id"])
    op.create_index("idx_approval_reviewers_reviewer_id", "approval_reviewers", ["reviewer_id"])

    # ── notifications ────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("reference_id", sa.String(36), nullable=True),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_notifications_user_id", "notifications", ["user_id"])
    op.create_index("idx_notifications_is_read", "notifications", ["is_read"])
    op.create_index("idx_notifications_reference_id", "notifications", ["reference_id"])

    # ── campaign_auto_configs ────────────────────────────────
    op.create_table(
        "campaign_auto_configs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("ta", sa.String(20), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("campaign_name_template", sa.String(500), nullable=False),
        sa.Column("default_objective", sa.String(100), nullable=False, server_default=sa.text("'CONVERSIONS'")),
        sa.Column("default_daily_budget", sa.Numeric(15, 2), nullable=False),
        sa.Column("default_funnel_stage", sa.String(10), nullable=False, server_default=sa.text("'TOF'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["ad_accounts.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_campaign_auto_configs_account_id", "campaign_auto_configs", ["account_id"])
    op.create_index("idx_campaign_auto_configs_country", "campaign_auto_configs", ["country"])
    op.create_index("idx_campaign_auto_configs_ta", "campaign_auto_configs", ["ta"])


def downgrade() -> None:
    op.drop_table("campaign_auto_configs")
    op.drop_table("notifications")
    op.drop_table("approval_reviewers")
    op.drop_table("combo_approvals")
    op.drop_table("users")
