"""GA4 integration: ga4_property_id on ad_accounts + landing_page_ga4_snapshots

Revision ID: 018_ga4_snapshots
Revises: 017_landing_pages
Create Date: 2026-04-22

Adds Google Analytics 4 as a data source alongside Microsoft Clarity.

GA4 complements Clarity with:
  - Web Vitals (LCP / INP / CLS)        playbook §5.3 direct compliance
  - Ecommerce funnel events              playbook §7.1 drop-off map
  - Multi-touch attribution              deduplicates Meta + Google conversion claims
  - Independent session counts           cross-validation with Meta LPV / Clarity

Migration does:
  1. Add `ga4_property_id` column to ad_accounts (per-branch property id).
  2. Create landing_page_ga4_snapshots with 1 row per (page, date, source,
     medium, campaign) — mirror of the Clarity snapshot layout so dashboard
     JOINs are symmetric.

Seed step: the operator populates ga4_property_id per branch via the Settings
UI (or a manual SQL `UPDATE ad_accounts SET ga4_property_id = '...' WHERE ...`).

Idempotent per project memory.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_ga4_snapshots"
down_revision: Union[str, None] = "017_landing_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) ad_accounts.ga4_property_id
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute(
            """
            ALTER TABLE ad_accounts
            ADD COLUMN IF NOT EXISTS ga4_property_id VARCHAR(50)
            """
        )
    else:
        with op.batch_alter_table("ad_accounts") as batch:
            batch.add_column(sa.Column("ga4_property_id", sa.String(50), nullable=True))

    # 2) landing_page_ga4_snapshots
    op.create_table(
        "landing_page_ga4_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "landing_page_id",
            sa.String(36),
            sa.ForeignKey("landing_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        # Source breakdown (mirror of Clarity snapshot layout)
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("medium", sa.String(100), nullable=True),
        sa.Column("campaign", sa.String(200), nullable=True),
        # Core traffic (GA4's authoritative numbers)
        sa.Column("sessions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("engaged_sessions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("engagement_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("active_users", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_users", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("screen_page_views", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_session_duration_sec", sa.Numeric(10, 2), nullable=True),
        sa.Column("bounce_rate", sa.Numeric(6, 4), nullable=True),
        # Ecommerce funnel (ties to playbook §7.1 drop-off map)
        sa.Column("begin_checkout", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("add_payment_info", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("purchases", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("purchase_revenue", sa.Numeric(15, 2), nullable=False, server_default=sa.text("0")),
        # Web Vitals (playbook §5.3 — LCP < 1.8s, INP < 200ms, CLS < 0.1)
        # Percentile-based metrics: we pull the p75 rolling median that Google itself uses
        # to judge Core Web Vitals pass/fail on Search rankings.
        sa.Column("lcp_p75_ms", sa.Integer(), nullable=True),
        sa.Column("inp_p75_ms", sa.Integer(), nullable=True),
        sa.Column("cls_p75", sa.Numeric(6, 4), nullable=True),
        sa.Column("fcp_p75_ms", sa.Integer(), nullable=True),
        # Forward-compat
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "landing_page_id", "date", "source", "medium", "campaign",
            name="uq_lp_ga4_page_date_source",
        ),
    )
    op.create_index("idx_lp_ga4_page", "landing_page_ga4_snapshots", ["landing_page_id"])
    op.create_index("idx_lp_ga4_date", "landing_page_ga4_snapshots", ["date"])


def downgrade() -> None:
    op.drop_table("landing_page_ga4_snapshots")
    with op.batch_alter_table("ad_accounts") as batch:
        batch.drop_column("ga4_property_id")
