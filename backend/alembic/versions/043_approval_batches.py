"""Approval batches: group multiple combo versions under one review.

Revision ID: 043_approval_batches
Revises: 042_budget_limits_per_branch
Create Date: 2026-05-29

A creator can now submit N ad versions of the same target as a single batch.
Reviewers decide the whole batch at once (all-or-nothing) — the decision is
applied to every child combo_approval.

  approval_batches          new table holding the shared submission metadata
                            (submitter, round, deadline, note, timestamps)
  combo_approvals.batch_id  nullable FK → approval_batches. NULL = standalone
                            single-version approval (all legacy rows stay NULL,
                            so this migration needs no data backfill and the
                            existing single-submit / launch flows are untouched)

Idempotent: CREATE TABLE / ADD COLUMN IF NOT EXISTS on Postgres;
batch_alter_table on the SQLite test path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043_approval_batches"
down_revision: Union[str, None] = "042_budget_limits_per_branch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # NOTE: all ids in this app are app-generated VARCHAR(36)
        # (UUIDType = String(36)), NOT native Postgres UUID. submitted_by must
        # match users.id's type (VARCHAR), otherwise the FK can't be created.
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_batches (
                id VARCHAR(36) PRIMARY KEY,
                submitted_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                round INTEGER NOT NULL DEFAULT 1,
                submitted_at TIMESTAMPTZ NOT NULL,
                deadline TIMESTAMPTZ,
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_approval_batches_submitted_by "
            "ON approval_batches (submitted_by);"
        )
        op.execute(
            """
            ALTER TABLE combo_approvals
            ADD COLUMN IF NOT EXISTS batch_id VARCHAR(36)
            REFERENCES approval_batches(id) ON DELETE CASCADE;
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_combo_approvals_batch_id "
            "ON combo_approvals (batch_id);"
        )
    else:
        op.create_table(
            "approval_batches",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("submitted_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        with op.batch_alter_table("combo_approvals") as batch:
            batch.add_column(sa.Column("batch_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("ALTER TABLE combo_approvals DROP COLUMN IF EXISTS batch_id;")
        op.execute("DROP TABLE IF EXISTS approval_batches;")
    else:
        with op.batch_alter_table("combo_approvals") as batch:
            batch.drop_column("batch_id")
        op.drop_table("approval_batches")
