"""Creative Knowledge System — research_questions + creative_principles tables,
enhance creative_hypotheses with 4-tier architecture links.

Revision ID: 058_creative_knowledge_system
Revises: 057_hypothesis_category
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "058_creative_knowledge_system"
down_revision = "057_hypothesis_category"
branch_labels = None
depends_on = None


def upgrade():
    # ── research_questions ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS research_questions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            question_id VARCHAR(20) NOT NULL UNIQUE,
            branch_name VARCHAR(100),
            market VARCHAR(10),
            target_audience VARCHAR(100),
            question TEXT NOT NULL,
            context TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            priority VARCHAR(10) DEFAULT 'medium',
            created_by VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rq_branch ON research_questions(branch_name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rq_status ON research_questions(status)")

    # ── creative_principles ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS creative_principles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            principle_id VARCHAR(20) NOT NULL UNIQUE,
            branch_name VARCHAR(100),
            title TEXT NOT NULL,
            description TEXT,
            anti_principle TEXT,
            human_desire VARCHAR(100),
            applicable_markets JSONB,
            applicable_ta JSONB,
            confidence_score NUMERIC(5,2) DEFAULT 0,
            experiment_count INTEGER DEFAULT 0,
            validated_count INTEGER DEFAULT 0,
            refuted_count INTEGER DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cp_branch ON creative_principles(branch_name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cp_desire ON creative_principles(human_desire)")

    # ── enhance creative_hypotheses ──────────────────────────────────────────
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS principle_id UUID REFERENCES creative_principles(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS research_question_id UUID REFERENCES research_questions(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,2) DEFAULT NULL")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS knowledge_links JSONB DEFAULT '[]'")
    op.execute("ALTER TABLE creative_hypotheses ADD COLUMN IF NOT EXISTS parent_hypothesis_id UUID REFERENCES creative_hypotheses(id) ON DELETE SET NULL")

    op.execute("CREATE INDEX IF NOT EXISTS ix_ch_principle_id ON creative_hypotheses(principle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ch_rq_id ON creative_hypotheses(research_question_id)")

    # ── backfill creative_principles from existing creative_principle text ───
    # Each unique (branch_name, creative_principle) pair → one principle row
    op.execute("""
        INSERT INTO creative_principles (principle_id, branch_name, title, description, confidence_score, experiment_count, validated_count)
        SELECT
            'PRI-' || LPAD(ROW_NUMBER() OVER (ORDER BY branch_name, creative_principle)::TEXT, 3, '0'),
            branch_name,
            creative_principle,
            creative_principle,
            CASE confidence_level
                WHEN 'high' THEN 80
                WHEN 'medium' THEN 50
                WHEN 'low' THEN 25
                ELSE 40
            END,
            COUNT(*) FILTER (WHERE status IN ('validated', 'refuted', 'inconclusive')),
            COUNT(*) FILTER (WHERE status = 'validated')
        FROM creative_hypotheses
        WHERE creative_principle IS NOT NULL AND creative_principle != ''
        GROUP BY branch_name, creative_principle, confidence_level
        ON CONFLICT (principle_id) DO NOTHING
    """)

    # backfill principle_id FK on hypotheses that have creative_principle text
    op.execute("""
        UPDATE creative_hypotheses h
        SET principle_id = cp.id
        FROM creative_principles cp
        WHERE h.creative_principle IS NOT NULL
          AND h.creative_principle != ''
          AND cp.branch_name = h.branch_name
          AND cp.title = h.creative_principle
          AND h.principle_id IS NULL
    """)

    # backfill confidence_score from confidence_level
    op.execute("""
        UPDATE creative_hypotheses SET confidence_score =
            CASE confidence_level
                WHEN 'high' THEN 75
                WHEN 'medium' THEN 45
                WHEN 'low' THEN 20
                ELSE NULL
            END
        WHERE confidence_score IS NULL AND confidence_level IS NOT NULL
    """)


def downgrade():
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS parent_hypothesis_id")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS knowledge_links")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS confidence_score")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS research_question_id")
    op.execute("ALTER TABLE creative_hypotheses DROP COLUMN IF EXISTS principle_id")
    op.execute("DROP TABLE IF EXISTS creative_principles")
    op.execute("DROP TABLE IF EXISTS research_questions")
