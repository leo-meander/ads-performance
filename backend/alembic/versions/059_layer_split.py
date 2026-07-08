"""Layer A / Layer B split + funnel stage + format + verdict gate fields.

Revision ID: 059_layer_split
Revises: 058_creative_knowledge_system
Create Date: 2026-07-08
"""
from alembic import op

revision = "059_layer_split"
down_revision = "058_creative_knowledge_system"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS funnel_stage VARCHAR(20)")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS format VARCHAR(10)")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS primary_metric VARCHAR(50)")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS win_threshold NUMERIC(5,2)")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS min_sample INTEGER DEFAULT 5")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS layer_b_status VARCHAR(20)")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS layer_b_notes TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ch_funnel_stage ON creative_hypotheses(funnel_stage)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ch_format ON creative_hypotheses(format)")


def downgrade():
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS funnel_stage")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS format")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS primary_metric")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS win_threshold")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS min_sample")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS layer_b_status")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS layer_b_notes")
