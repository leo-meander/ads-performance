"""Add url_source column to ad_materials to protect manually-set URLs from sync overwrite

Revision ID: 009_material_url_source
Revises: 008_booking_from_ads
Create Date: 2026-04-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_material_url_source"
down_revision: Union[str, None] = "008_booking_from_ads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Disable statement timeout for this migration (Supabase pooler default is aggressive)
    op.execute("SET LOCAL statement_timeout = 0")
    # Step 1: add nullable column (fast metadata-only change)
    op.add_column(
        "ad_materials",
        sa.Column("url_source", sa.String(10), nullable=True),
    )
    # Step 2: backfill existing rows (safe — table is small)
    op.execute("UPDATE ad_materials SET url_source = 'auto' WHERE url_source IS NULL")
    # Step 3: enforce NOT NULL + set default for future inserts
    op.alter_column("ad_materials", "url_source", nullable=False, server_default="auto")
    op.create_index("ix_ad_materials_url_source", "ad_materials", ["url_source"])
    # url_source: 'auto' = synced from Meta (overwritable by sync task)
    #             'manual' = designer-input URL (sync task MUST skip)


def downgrade() -> None:
    op.drop_index("ix_ad_materials_url_source", table_name="ad_materials")
    op.drop_column("ad_materials", "url_source")
