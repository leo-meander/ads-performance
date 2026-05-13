"""Creative Intelligence Phase 1 — visual tagging schema.

Revision ID: 034_creative_visual_tags
Revises: 033_drop_canva
Create Date: 2026-05-13

Adds:
  - ad_materials.vision_analyzed_at  TIMESTAMPTZ — when Claude vision last
                                     scored this material. NULL = never tagged;
                                     the cron tagger picks NULL rows first.
  - ad_materials.vision_model        VARCHAR(40) — model id that produced the
                                     current tags (e.g. "claude-sonnet-4-6").
                                     Lets us rebuild tags after model upgrades.

  - creative_visual_tags             one row per (material, category, value).
                                     Categories are short strings the tagger
                                     emits — text_density, hook_type, cta_visible,
                                     color_palette, human_presence, scene_type,
                                     emotional_angle. Multiple values per category
                                     are allowed (e.g. scene_type=room +
                                     scene_type=exterior on a montage ad).

Idempotent: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS on Postgres,
batch_alter_table on SQLite test path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034_creative_visual_tags"
down_revision: Union[str, None] = "033_drop_canva"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS vision_analyzed_at TIMESTAMPTZ;
            """
        )
        op.execute(
            """
            ALTER TABLE ad_materials
            ADD COLUMN IF NOT EXISTS vision_model VARCHAR(40);
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ad_materials_vision_analyzed_at "
            "ON ad_materials (vision_analyzed_at);"
        )
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS creative_visual_tags (
                id              VARCHAR(36) PRIMARY KEY,
                material_id     VARCHAR(10) NOT NULL
                                REFERENCES ad_materials(material_id) ON DELETE CASCADE,
                tag_category    VARCHAR(40) NOT NULL,
                tag_value       VARCHAR(80) NOT NULL,
                confidence      NUMERIC(4,3),
                model_version   VARCHAR(40),
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_creative_visual_tag
                    UNIQUE (material_id, tag_category, tag_value)
            );
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_creative_visual_tags_material "
            "ON creative_visual_tags (material_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_creative_visual_tags_category_value "
            "ON creative_visual_tags (tag_category, tag_value);"
        )
    else:
        with op.batch_alter_table("ad_materials") as batch:
            batch.add_column(
                sa.Column("vision_analyzed_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(sa.Column("vision_model", sa.String(40), nullable=True))

        op.create_table(
            "creative_visual_tags",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "material_id",
                sa.String(10),
                sa.ForeignKey("ad_materials.material_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("tag_category", sa.String(40), nullable=False),
            sa.Column("tag_value", sa.String(80), nullable=False),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("model_version", sa.String(40), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "material_id",
                "tag_category",
                "tag_value",
                name="uq_creative_visual_tag",
            ),
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_creative_visual_tags_category_value;")
    op.execute("DROP INDEX IF EXISTS ix_creative_visual_tags_material;")
    op.execute("DROP TABLE IF EXISTS creative_visual_tags;")
    op.execute("DROP INDEX IF EXISTS ix_ad_materials_vision_analyzed_at;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS vision_model;")
    op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS vision_analyzed_at;")
