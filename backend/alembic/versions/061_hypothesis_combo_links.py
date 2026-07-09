"""hypothesis_combo_links junction table (1 hypothesis → N combos)

Revision ID: 061_hypothesis_combo_links
Revises: 060_hypothesis_baseline
Create Date: 2026-07-09
"""
from alembic import op

revision = "061_hypothesis_combo_links"
down_revision = "060_hypothesis_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hypothesis_combo_links (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            hypothesis_id VARCHAR(20) NOT NULL REFERENCES creative_hypotheses(hypothesis_id) ON DELETE CASCADE,
            combo_id      VARCHAR(20) NOT NULL REFERENCES ad_combos(combo_id) ON DELETE CASCADE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (hypothesis_id, combo_id)
        );
        CREATE INDEX IF NOT EXISTS ix_hcl_hypothesis_id ON hypothesis_combo_links(hypothesis_id);
        CREATE INDEX IF NOT EXISTS ix_hcl_combo_id      ON hypothesis_combo_links(combo_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hypothesis_combo_links;")
