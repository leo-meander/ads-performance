"""Create user_page_permissions table for per-page (sub-section) access control

Revision ID: 040_user_page_permissions
Revises: 039_reservation_country_iso
Create Date: 2026-05-23

Adds page-level granularity on top of user_permissions. A page is one screen
within a section (e.g. 'keypoints' under 'meta_ads'). Page access is global
per user — branch×section still governs which data is visible. No page rows
for a section => user sees all pages of that section (backward compatible).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "040_user_page_permissions"
down_revision: Union[str, None] = "039_reservation_country_iso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Disable statement timeout (Supabase pooler default is aggressive)
    op.execute("SET LOCAL statement_timeout = 0")

    op.create_table(
        "user_page_permissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.String(length=40), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
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
        sa.UniqueConstraint(
            "user_id",
            "page",
            name="uq_user_page_perm_user_page",
        ),
    )
    op.create_index(
        "ix_user_page_permissions_user_id",
        "user_page_permissions",
        ["user_id"],
    )

    # page: canonical key from app.core.permissions.PAGES (e.g. 'keypoints',
    #   'ad_research', 'approvals'). Each page maps to exactly one section.
    # level: 'view' (read-only) or 'edit' (read + write).
    # No row for a (user, section)'s pages = full section access (all pages).
    # Admin role bypasses this table entirely.


def downgrade() -> None:
    op.drop_index(
        "ix_user_page_permissions_user_id", table_name="user_page_permissions"
    )
    op.drop_table("user_page_permissions")
