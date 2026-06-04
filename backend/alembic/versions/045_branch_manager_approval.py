"""Branch-manager sign-off with screenshot proof on combo_approvals.

Revision ID: 045_branch_manager_approval
Revises: 044_surf_intraday
Create Date: 2026-06-04

Branch managers approve creatives offline (over chat — Lark / messenger). This
records that sign-off directly: the marketer pastes the approval screenshot and
the combo is marked APPROVED immediately, bypassing the in-app reviewer round.

  combo_approvals.bm_approved_at   when the branch-manager sign-off was recorded
  combo_approvals.bm_approved_by   user who recorded it (FK users, SET NULL)
  combo_approvals.bm_proof_image   the screenshot as a base64 data URL (TEXT) —
                                   the app has no blob storage, so the proof
                                   lives inline on the row

All nullable + no backfill: existing approvals stay untouched (NULL = no
branch-manager proof, status still driven by the reviewer flow).

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, batch_alter_table on SQLite
test path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "045_branch_manager_approval"
down_revision: Union[str, None] = "044_surf_intraday"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE combo_approvals
            ADD COLUMN IF NOT EXISTS bm_approved_at TIMESTAMPTZ;
            """
        )
        # bm_approved_by must match users.id's type (VARCHAR(36) app-generated
        # ids, not native Postgres UUID), otherwise the FK can't be created.
        op.execute(
            """
            ALTER TABLE combo_approvals
            ADD COLUMN IF NOT EXISTS bm_approved_by VARCHAR(36)
            REFERENCES users(id) ON DELETE SET NULL;
            """
        )
        op.execute(
            """
            ALTER TABLE combo_approvals
            ADD COLUMN IF NOT EXISTS bm_proof_image TEXT;
            """
        )
    else:
        with op.batch_alter_table("combo_approvals") as batch:
            batch.add_column(sa.Column("bm_approved_at", sa.DateTime(timezone=True), nullable=True))
            batch.add_column(sa.Column("bm_approved_by", sa.String(length=36), nullable=True))
            batch.add_column(sa.Column("bm_proof_image", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("ALTER TABLE combo_approvals DROP COLUMN IF EXISTS bm_proof_image;")
        op.execute("ALTER TABLE combo_approvals DROP COLUMN IF EXISTS bm_approved_by;")
        op.execute("ALTER TABLE combo_approvals DROP COLUMN IF EXISTS bm_approved_at;")
    else:
        with op.batch_alter_table("combo_approvals") as batch:
            batch.drop_column("bm_proof_image")
            batch.drop_column("bm_approved_by")
            batch.drop_column("bm_approved_at")
