"""Add note column to combo_approvals for submitter context.

Revision ID: 038_approval_note
Revises: 037_figma_material_meta_creative
Create Date: 2026-05-14

The creator can now attach a free-text note when submitting a combo for
approval, giving reviewers extra context that doesn't belong on the ad copy.

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, batch_alter_table on SQLite
test path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "038_approval_note"
down_revision: Union[str, None] = "037_figma_material_meta_creative"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE combo_approvals
            ADD COLUMN IF NOT EXISTS note TEXT;
            """
        )
    else:
        with op.batch_alter_table("combo_approvals") as batch:
            batch.add_column(sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE combo_approvals DROP COLUMN IF EXISTS note;")
