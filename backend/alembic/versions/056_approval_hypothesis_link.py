"""Link combo_approvals to creative_hypotheses

Revision ID: 056_approval_hypothesis_link
Revises: 055_hypothesis_evidence
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "056_approval_hypothesis_link"
down_revision = "055_hypothesis_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "combo_approvals",
        sa.Column("hypothesis_id", sa.String(20), nullable=True),
    )
    op.create_foreign_key(
        "fk_combo_approvals_hypothesis_id",
        "combo_approvals",
        "creative_hypotheses",
        ["hypothesis_id"],
        ["hypothesis_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_combo_approvals_hypothesis_id",
        "combo_approvals",
        ["hypothesis_id"],
    )


def downgrade():
    op.drop_index("ix_combo_approvals_hypothesis_id", table_name="combo_approvals")
    op.drop_constraint("fk_combo_approvals_hypothesis_id", "combo_approvals", type_="foreignkey")
    op.drop_column("combo_approvals", "hypothesis_id")
