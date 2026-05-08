"""Add Canva URL columns to ad_materials.

Revision ID: 029_canva_material_links
Revises: 028_approval_reviewer_feedback
Create Date: 2026-05-08

Phase 1 of the winning-ads regenerate flow. When an approval is granted,
the working_file_url (typically a Canva design URL) is persisted onto the
material so it can be reused later for cloning a winning template.

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, batch_alter_table on SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_canva_material_links"
down_revision: Union[str, None] = "028_approval_reviewer_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS canva_url TEXT;
            """
        )
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS canva_design_id VARCHAR(50);
            """
        )
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS canva_captured_at TIMESTAMPTZ;
            """
        )
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS canva_source_approval_id VARCHAR(36);
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_ad_materials_canva_design_id
            ON ad_materials (canva_design_id);
            """
        )
    else:
        with op.batch_alter_table("ad_materials") as batch:
            batch.add_column(sa.Column("canva_url", sa.Text(), nullable=True))
            batch.add_column(sa.Column("canva_design_id", sa.String(50), nullable=True))
            batch.add_column(sa.Column("canva_captured_at", sa.DateTime(timezone=True), nullable=True))
            batch.add_column(sa.Column("canva_source_approval_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ad_materials_canva_design_id;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_source_approval_id;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_captured_at;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_design_id;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_url;")
