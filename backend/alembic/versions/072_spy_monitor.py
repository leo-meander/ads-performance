"""Spy Ads competitor monitor: longevity ledger + creative groups

Adds the tables behind /ad-research's monitor:
  - spy_competitor_ads   one row per competitor ad, carried across crawls
  - spy_creative_groups  near-duplicate ads collapsed into one concept

Plus crawl diagnostics on spy_tracked_pages (a page that silently returns
zero ads must be distinguishable from one that stopped advertising) and a
structured result column on spy_analysis_reports for the pattern digest.

Revision ID: 072_spy_monitor
Revises: 071_ads_status_preview
Create Date: 2026-09-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Keep revision ids short: alembic_version.version_num is VARCHAR(32) and a
# longer id crash-loops the production upgrade.
revision: str = "072_spy_monitor"
down_revision: Union[str, None] = "071_ads_status_preview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spy_competitor_ads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ad_archive_id", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "tracked_page_id",
            sa.String(36),
            sa.ForeignKey("spy_tracked_pages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("page_id", sa.String(50), nullable=True),
        sa.Column("page_name", sa.String(500), nullable=True),
        sa.Column("country", sa.String(10), nullable=True),
        sa.Column("ad_creative_bodies", sa.JSON, nullable=True),
        sa.Column("ad_creative_link_titles", sa.JSON, nullable=True),
        sa.Column("ad_creative_link_captions", sa.JSON, nullable=True),
        sa.Column("cta_text", sa.String(200), nullable=True),
        sa.Column("link_url", sa.Text, nullable=True),
        sa.Column("media_type", sa.String(20), nullable=True),
        sa.Column("image_urls", sa.JSON, nullable=True),
        sa.Column("video_urls", sa.JSON, nullable=True),
        sa.Column("preview_image_url", sa.Text, nullable=True),
        sa.Column("ad_snapshot_url", sa.Text, nullable=True),
        sa.Column("publisher_platforms", sa.JSON, nullable=True),
        sa.Column("ad_delivery_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ad_delivery_stop_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("days_running", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("days_observed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_currently_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("disappeared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("creative_group_key", sa.String(64), nullable=True),
        sa.Column("ai_breakdown", sa.JSON, nullable=True),
        sa.Column("ai_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(30), nullable=True),
        sa.Column("raw_data", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_spy_comp_ads_archive", "spy_competitor_ads", ["ad_archive_id"])
    op.create_index("idx_spy_comp_ads_tracked_page", "spy_competitor_ads", ["tracked_page_id"])
    op.create_index("idx_spy_comp_ads_page", "spy_competitor_ads", ["page_id"])
    op.create_index("idx_spy_comp_ads_country", "spy_competitor_ads", ["country"])
    op.create_index("idx_spy_comp_ads_media_type", "spy_competitor_ads", ["media_type"])
    op.create_index("idx_spy_comp_ads_start", "spy_competitor_ads", ["ad_delivery_start_time"])
    op.create_index("idx_spy_comp_ads_first_seen", "spy_competitor_ads", ["first_seen_at"])
    op.create_index("idx_spy_comp_ads_last_seen", "spy_competitor_ads", ["last_seen_at"])
    op.create_index("idx_spy_comp_ads_fingerprint", "spy_competitor_ads", ["fingerprint"])
    op.create_index("idx_spy_comp_ads_group", "spy_competitor_ads", ["creative_group_key"])
    op.create_index("idx_spy_comp_ads_is_active", "spy_competitor_ads", ["is_active"])
    op.create_index(
        "idx_spy_comp_ads_currently_active", "spy_competitor_ads", ["is_currently_active"]
    )
    # The headline query is "still running, longest first" -- serve it from one
    # composite index instead of a filter plus a sort.
    op.create_index(
        "idx_spy_comp_ads_active_days",
        "spy_competitor_ads",
        ["is_currently_active", "days_running"],
    )

    op.create_table(
        "spy_creative_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("group_key", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(500), nullable=True),
        sa.Column("ad_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active_ad_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("page_ids", sa.JSON, nullable=True),
        sa.Column("page_names", sa.JSON, nullable=True),
        sa.Column("representative_ad_id", sa.String(100), nullable=True),
        sa.Column("preview_image_url", sa.Text, nullable=True),
        sa.Column("media_type", sa.String(20), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_days_running", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_still_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_spy_groups_key", "spy_creative_groups", ["group_key"])
    op.create_index("idx_spy_groups_ad_count", "spy_creative_groups", ["ad_count"])
    op.create_index("idx_spy_groups_max_days", "spy_creative_groups", ["max_days_running"])
    op.create_index("idx_spy_groups_still_active", "spy_creative_groups", ["is_still_active"])
    op.create_index("idx_spy_groups_first_seen", "spy_creative_groups", ["first_seen_at"])
    op.create_index("idx_spy_groups_last_seen", "spy_creative_groups", ["last_seen_at"])
    op.create_index("idx_spy_groups_is_active", "spy_creative_groups", ["is_active"])

    op.add_column(
        "spy_tracked_pages", sa.Column("last_crawl_ad_count", sa.Integer, nullable=True)
    )
    op.add_column("spy_tracked_pages", sa.Column("last_crawl_error", sa.Text, nullable=True))
    op.add_column(
        "spy_tracked_pages",
        sa.Column("monitor_enabled", sa.Boolean, nullable=False, server_default="true"),
    )

    op.add_column("spy_analysis_reports", sa.Column("result_json", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("spy_analysis_reports", "result_json")
    op.drop_column("spy_tracked_pages", "monitor_enabled")
    op.drop_column("spy_tracked_pages", "last_crawl_error")
    op.drop_column("spy_tracked_pages", "last_crawl_ad_count")
    op.drop_table("spy_creative_groups")
    op.drop_table("spy_competitor_ads")
