"""Add spy ads tables: tracked pages, saved ads, analysis reports

Revision ID: 004_spy_ads_tables
Revises: 003_budget_parsing_country
Create Date: 2026-04-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_spy_ads_tables"
down_revision: Union[str, None] = "003_budget_parsing_country"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- spy_tracked_pages ---
    op.create_table(
        "spy_tracked_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("page_id", sa.String(50), nullable=False, unique=True),
        sa.Column("page_name", sa.String(500), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("country", sa.String(10), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_spy_tracked_pages_page_id", "spy_tracked_pages", ["page_id"])
    op.create_index("idx_spy_tracked_pages_category", "spy_tracked_pages", ["category"])
    op.create_index("idx_spy_tracked_pages_is_active", "spy_tracked_pages", ["is_active"])

    # --- spy_saved_ads ---
    op.create_table(
        "spy_saved_ads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ad_archive_id", sa.String(100), nullable=False, unique=True),
        sa.Column("page_id", sa.String(50), nullable=True),
        sa.Column("page_name", sa.String(500), nullable=True),
        sa.Column("ad_creative_bodies", sa.JSON, nullable=True),
        sa.Column("ad_creative_link_titles", sa.JSON, nullable=True),
        sa.Column("ad_creative_link_captions", sa.JSON, nullable=True),
        sa.Column("ad_snapshot_url", sa.String(2000), nullable=True),
        sa.Column("publisher_platforms", sa.JSON, nullable=True),
        sa.Column("ad_delivery_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ad_delivery_stop_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("country", sa.String(10), nullable=True),
        sa.Column("media_type", sa.String(20), nullable=True),
        sa.Column("tags", sa.JSON, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("collection", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("raw_data", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_spy_saved_ads_archive_id", "spy_saved_ads", ["ad_archive_id"])
    op.create_index("idx_spy_saved_ads_page_id", "spy_saved_ads", ["page_id"])
    op.create_index("idx_spy_saved_ads_start_time", "spy_saved_ads", ["ad_delivery_start_time"])
    op.create_index("idx_spy_saved_ads_country", "spy_saved_ads", ["country"])
    op.create_index("idx_spy_saved_ads_collection", "spy_saved_ads", ["collection"])
    op.create_index("idx_spy_saved_ads_is_active", "spy_saved_ads", ["is_active"])

    # --- spy_analysis_reports ---
    op.create_table(
        "spy_analysis_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("input_ad_ids", sa.JSON, nullable=True),
        sa.Column("input_params", sa.JSON, nullable=True),
        sa.Column("result_markdown", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_spy_reports_type", "spy_analysis_reports", ["analysis_type"])
    op.create_index("idx_spy_reports_is_active", "spy_analysis_reports", ["is_active"])


def downgrade() -> None:
    op.drop_table("spy_analysis_reports")
    op.drop_table("spy_saved_ads")
    op.drop_table("spy_tracked_pages")
