"""Add hypothesis_category and customer_insight to creative_hypotheses

Revision ID: 057_hypothesis_category
Revises: 056_approval_hypothesis_link
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "057_hypothesis_category"
down_revision = "056_approval_hypothesis_link"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS hypothesis_category VARCHAR(50)")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS customer_insight TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_creative_hypotheses_category ON creative_hypotheses(hypothesis_category)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_creative_hypotheses_category")
    op.drop_column("creative_hypotheses", "customer_insight")
    op.drop_column("creative_hypotheses", "hypothesis_category")
