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
    op.execute("ALTER TABLE combo_approvals ADD COLUMN IF NOT EXISTS hypothesis_id VARCHAR(20)")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_combo_approvals_hypothesis_id'
            ) THEN
                ALTER TABLE combo_approvals ADD CONSTRAINT fk_combo_approvals_hypothesis_id
                FOREIGN KEY (hypothesis_id) REFERENCES creative_hypotheses(hypothesis_id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_combo_approvals_hypothesis_id ON combo_approvals(hypothesis_id)")


def downgrade():
    op.drop_index("ix_combo_approvals_hypothesis_id", table_name="combo_approvals")
    op.drop_constraint("fk_combo_approvals_hypothesis_id", "combo_approvals", type_="foreignkey")
    op.drop_column("combo_approvals", "hypothesis_id")
