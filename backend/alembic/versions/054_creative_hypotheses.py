"""creative_hypotheses table for Learning Engine

Revision ID: 054_creative_hypotheses
Revises: 053_angles_new_framework
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "054_creative_hypotheses"
down_revision = "053_angles_new_framework"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "creative_hypotheses",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("hypothesis_id", sa.String(20), nullable=False, unique=True),
        sa.Column("branch_name", sa.String(100), nullable=False),
        sa.Column("combo_id", sa.String(20), nullable=True),
        sa.Column("angle_id", sa.String(20), nullable=True),
        # Strategy context
        sa.Column("human_desire", sa.String(100), nullable=True),
        sa.Column("creative_angle", sa.String(200), nullable=True),
        sa.Column("target_audience", sa.String(100), nullable=True),
        sa.Column("market", sa.String(10), nullable=True),
        # Hypothesis
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("variable_tested", sa.Text(), nullable=True),
        sa.Column("primary_kpi", sa.String(50), nullable=True),
        sa.Column("secondary_kpi", sa.String(50), nullable=True),
        sa.Column("expected_outcome", sa.Text(), nullable=True),
        # Results (filled after campaign runs)
        sa.Column("actual_ctr", sa.Numeric(8, 4), nullable=True),
        sa.Column("actual_cvr", sa.Numeric(8, 4), nullable=True),
        sa.Column("actual_roas", sa.Numeric(8, 2), nullable=True),
        sa.Column("actual_spend", sa.Numeric(15, 2), nullable=True),
        # Confounding factors for statistical integrity
        sa.Column("confounding_factors", sa.JSON(), nullable=True),
        sa.Column("confidence_level", sa.String(10), nullable=True),  # low/medium/high
        # Outcome
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # pending/running/validated/refuted/inconclusive
        sa.Column("learning", sa.Text(), nullable=True),
        sa.Column("result_notes", sa.Text(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), onupdate=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["combo_id"], ["ad_combos.combo_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["angle_id"], ["ad_angles.angle_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creative_hypotheses_branch", "creative_hypotheses", ["branch_name"])
    op.create_index("ix_creative_hypotheses_human_desire", "creative_hypotheses", ["human_desire"])
    op.create_index("ix_creative_hypotheses_status", "creative_hypotheses", ["status"])
    op.create_index("ix_creative_hypotheses_combo", "creative_hypotheses", ["combo_id"])


def downgrade():
    op.drop_index("ix_creative_hypotheses_combo", table_name="creative_hypotheses")
    op.drop_index("ix_creative_hypotheses_status", table_name="creative_hypotheses")
    op.drop_index("ix_creative_hypotheses_human_desire", table_name="creative_hypotheses")
    op.drop_index("ix_creative_hypotheses_branch", table_name="creative_hypotheses")
    op.drop_table("creative_hypotheses")
