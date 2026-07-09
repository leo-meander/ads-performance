"""add baseline column to creative_hypotheses

Revision ID: 060_hypothesis_baseline
Revises: 059_layer_split
Create Date: 2026-07-09
"""
from alembic import op

revision = "060_hypothesis_baseline"
down_revision = "059_layer_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE creative_hypotheses
        ADD COLUMN IF NOT EXISTS baseline TEXT;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS baseline;")
