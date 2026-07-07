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
    op.add_column("creative_hypotheses", sa.Column("brief_text", sa.Text(), nullable=True))
    op.add_column("creative_hypotheses", sa.Column("script_text", sa.Text(), nullable=True))
    op.add_column("creative_hypotheses", sa.Column("evidence", sa.Text(), nullable=True))
    op.add_column("creative_hypotheses", sa.Column("creative_principle", sa.Text(), nullable=True))
    op.add_column("creative_hypotheses", sa.Column("why_it_worked", sa.Text(), nullable=True))
    op.add_column("creative_hypotheses", sa.Column("human_moment", sa.String(200), nullable=True))


def downgrade():
    op.drop_column("creative_hypotheses", "human_moment")
    op.drop_column("creative_hypotheses", "why_it_worked")
    op.drop_column("creative_hypotheses", "creative_principle")
    op.drop_column("creative_hypotheses", "evidence")
    op.drop_column("creative_hypotheses", "script_text")
    op.drop_column("creative_hypotheses", "brief_text")
