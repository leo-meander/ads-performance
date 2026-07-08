"""Add evidence + creative_principle to creative_hypotheses

Revision ID: 055_hypothesis_evidence
Revises: 054_creative_hypotheses
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "055_hypothesis_evidence"
down_revision = "054_creative_hypotheses"
branch_labels = None
depends_on = None


def upgrade():
    # Use IF NOT EXISTS — columns may already exist if added manually on prod before this migration ran.
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS brief_text TEXT")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS script_text TEXT")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS evidence TEXT")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS creative_principle TEXT")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS why_it_worked TEXT")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS human_moment VARCHAR(200)")


def downgrade():
    op.drop_column("creative_hypotheses", "human_moment")
    op.drop_column("creative_hypotheses", "why_it_worked")
    op.drop_column("creative_hypotheses", "creative_principle")
    op.drop_column("creative_hypotheses", "evidence")
    op.drop_column("creative_hypotheses", "script_text")
    op.drop_column("creative_hypotheses", "brief_text")
