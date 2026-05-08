"""Add canva_job_id to material_regenerations for async polling.

Revision ID: 031_canva_job_id
Revises: 030_canva_regenerations
Create Date: 2026-05-08

When Canva's autofill API returns status=in_progress we now persist the
job_id so /api/internal/tasks/canva-poll (Zeabur cron) can finish the row
later instead of failing the request.

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, batch_alter_table on SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031_canva_job_id"
down_revision: Union[str, None] = "030_canva_regenerations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE material_regenerations
            ADD COLUMN IF NOT EXISTS canva_job_id VARCHAR(80);
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_material_regen_job_id
            ON material_regenerations (canva_job_id);
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_material_regen_pending
            ON material_regenerations (status) WHERE status IN ('PENDING', 'RUNNING');
            """
        )
    else:
        with op.batch_alter_table("material_regenerations") as batch:
            batch.add_column(sa.Column("canva_job_id", sa.String(80), nullable=True))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_regen_pending;")
    op.execute("DROP INDEX IF EXISTS ix_material_regen_job_id;")
    op.execute("ALTER TABLE material_regenerations DROP COLUMN IF EXISTS canva_job_id;")
