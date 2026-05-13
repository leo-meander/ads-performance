"""Drop all Canva schema (regenerations table + canva_* columns on ad_materials).

Revision ID: 033_drop_canva
Revises: 032_tactics
Create Date: 2026-05-13

The winning-ads regenerate flow is being rebuilt on Figma. All Canva-related
columns and the material_regenerations table are removed entirely. A new
figma_jobs table will replace material_regenerations in migration 036.

Idempotent: DROP IF EXISTS / batch_alter_table on SQLite.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "033_drop_canva"
down_revision: Union[str, None] = "032_tactics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # 1) Drop material_regenerations indexes + table
        op.execute("DROP INDEX IF EXISTS ix_material_regen_pending;")
        op.execute("DROP INDEX IF EXISTS ix_material_regen_job_id;")
        op.execute("DROP INDEX IF EXISTS ix_material_regen_status;")
        op.execute("DROP INDEX IF EXISTS ix_material_regen_source_material;")
        op.execute("DROP TABLE IF EXISTS material_regenerations;")

        # 2) Drop canva_* columns on ad_materials
        op.execute("DROP INDEX IF EXISTS ix_ad_materials_canva_design_id;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS is_template_ready;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_placeholder_schema;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_template_id;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_source_approval_id;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_captured_at;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_design_id;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS canva_url;")
    else:
        # SQLite path (local tests). batch_alter_table emulates DROP COLUMN.
        # Use try/except since SQLite doesn't have IF EXISTS for table-drop in
        # alembic and tests may run on a fresh schema where the table never existed.
        try:
            op.drop_table("material_regenerations")
        except Exception:
            pass

        try:
            with op.batch_alter_table("ad_materials") as batch:
                for col in (
                    "is_template_ready",
                    "canva_placeholder_schema",
                    "canva_template_id",
                    "canva_source_approval_id",
                    "canva_captured_at",
                    "canva_design_id",
                    "canva_url",
                ):
                    try:
                        batch.drop_column(col)
                    except Exception:
                        pass
        except Exception:
            pass


def downgrade() -> None:
    # Intentional one-way migration. Re-introducing Canva would mean restoring
    # 029-031; if rollback is required, downgrade to 032_tactics will run those
    # earlier migrations' upgrade() paths in reverse.
    raise NotImplementedError(
        "033_drop_canva is one-way. To restore Canva schema, restore from a "
        "pre-033 backup or re-author migrations 029-031."
    )
