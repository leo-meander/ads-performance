"""approval comments table + status migration

Revision ID: 051_approval_comments
Revises: 049_booking_match_confidence
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "051_approval_comments"
down_revision = "049_booking_match_confidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "approval_comments",
        sa.Column("id", sa.String(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["combo_approvals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["approval_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["approval_comments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approval_comments_approval_id", "approval_comments", ["approval_id"])
    op.create_index("ix_approval_comments_batch_id", "approval_comments", ["batch_id"])
    op.create_index("ix_approval_comments_user_id", "approval_comments", ["user_id"])

    # Migrate old statuses to new simplified ones
    op.execute("""
        UPDATE combo_approvals
        SET status = 'ONGOING'
        WHERE status IN ('PENDING_APPROVAL', 'REJECTED', 'NEEDS_REVISION')
    """)
    op.execute("""
        UPDATE approval_reviewers
        SET status = 'ONGOING'
        WHERE status IN ('PENDING', 'REJECTED', 'NEEDS_REVISION')
    """)


def downgrade():
    op.drop_index("ix_approval_comments_user_id", table_name="approval_comments")
    op.drop_index("ix_approval_comments_batch_id", table_name="approval_comments")
    op.drop_index("ix_approval_comments_approval_id", table_name="approval_comments")
    op.drop_table("approval_comments")
