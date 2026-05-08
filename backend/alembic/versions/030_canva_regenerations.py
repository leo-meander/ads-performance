"""Phase 2: Canva template metadata + material_regenerations table.

Revision ID: 030_canva_regenerations
Revises: 029_canva_material_links
Create Date: 2026-05-08

Adds:
  - ad_materials.canva_template_id      brand-template id (clonable)
  - ad_materials.canva_placeholder_schema JSONB — named slots designer wired up
  - ad_materials.is_template_ready       bool — true once a designer marked the
                                         winning material as a reusable template
  - material_regenerations               one row per regenerate request
                                         (comment, overrides, output URL, status)

Idempotent: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS on Postgres,
batch_alter_table on SQLite test path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_canva_regenerations"
down_revision: Union[str, None] = "029_canva_material_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS canva_template_id VARCHAR(50);
            """
        )
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS canva_placeholder_schema JSONB;
            """
        )
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS is_template_ready BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS material_regenerations (
                id              VARCHAR(36) PRIMARY KEY,
                source_material_id VARCHAR(10) NOT NULL REFERENCES ad_materials(material_id) ON DELETE CASCADE,
                source_combo_id VARCHAR(10) REFERENCES ad_combos(combo_id) ON DELETE SET NULL,
                comment         TEXT NOT NULL,
                overrides       JSONB,
                status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                output_canva_url   TEXT,
                output_design_id   VARCHAR(50),
                output_material_id VARCHAR(10) REFERENCES ad_materials(material_id) ON DELETE SET NULL,
                error           TEXT,
                requested_by    VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at    TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_material_regen_source_material
            ON material_regenerations (source_material_id);
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_material_regen_status
            ON material_regenerations (status);
            """
        )
    else:
        with op.batch_alter_table("ad_materials") as batch:
            batch.add_column(sa.Column("canva_template_id", sa.String(50), nullable=True))
            batch.add_column(sa.Column("canva_placeholder_schema", sa.JSON(), nullable=True))
            batch.add_column(sa.Column("is_template_ready", sa.Boolean(), nullable=False, server_default=sa.false()))

        op.create_table(
            "material_regenerations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_material_id", sa.String(10), sa.ForeignKey("ad_materials.material_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("source_combo_id", sa.String(10), sa.ForeignKey("ad_combos.combo_id", ondelete="SET NULL"), nullable=True),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column("overrides", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING", index=True),
            sa.Column("output_canva_url", sa.Text(), nullable=True),
            sa.Column("output_design_id", sa.String(50), nullable=True),
            sa.Column("output_material_id", sa.String(10), sa.ForeignKey("ad_materials.material_id", ondelete="SET NULL"), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_regenerations;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS is_template_ready;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_placeholder_schema;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_template_id;")
