"""Creative Intelligence Phase 3 — Figma templates + jobs.

Revision ID: 036_figma_templates_and_jobs
Revises: 035_pgvector_embeddings
Create Date: 2026-05-13

Replaces the removed Canva regenerate flow with a Figma-based equivalent.

  - figma_templates  Designer-registered master frames. Each row points at a
                     Figma file_key + node_id and lists the named text/image
                     layers the backend can fill (placeholder_schema JSONB).
                     A template is branch-scoped + size-scoped (Meta 1080x1080,
                     PMax 1200x628, etc.) so the brief generator can recommend
                     the right one.

  - figma_jobs       One row per render request. Lifecycle:
                     PENDING → RUNNING → COMPLETED|FAILED. Output is a Figma
                     URL (deep-link to the rendered frame) + an exported PNG
                     URL when the cron poller finishes the export.

Idempotent: CREATE TABLE IF NOT EXISTS / batch_alter_table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036_figma_templates_and_jobs"
down_revision: Union[str, None] = "035_pgvector_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS figma_templates (
                id                  VARCHAR(36) PRIMARY KEY,
                name                VARCHAR(200) NOT NULL,
                file_key            VARCHAR(80) NOT NULL,
                node_id             VARCHAR(80) NOT NULL,
                branch_id           VARCHAR(36) REFERENCES ad_accounts(id) ON DELETE SET NULL,
                platform            VARCHAR(20) NOT NULL DEFAULT 'meta',
                width               INTEGER NOT NULL DEFAULT 1080,
                height              INTEGER NOT NULL DEFAULT 1080,
                placeholder_schema  JSONB NOT NULL DEFAULT '{}'::jsonb,
                preview_image_url   TEXT,
                is_active           BOOLEAN NOT NULL DEFAULT TRUE,
                created_by          VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_figma_templates_branch ON figma_templates (branch_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_figma_templates_platform ON figma_templates (platform);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_figma_templates_active ON figma_templates (is_active);")

        op.execute(
            """
            CREATE TABLE IF NOT EXISTS figma_jobs (
                id                  VARCHAR(36) PRIMARY KEY,
                template_id         VARCHAR(36) NOT NULL REFERENCES figma_templates(id) ON DELETE CASCADE,
                source_combo_id     VARCHAR(10) REFERENCES ad_combos(combo_id) ON DELETE SET NULL,
                request_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
                status              VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                output_figma_url    TEXT,
                output_image_url    TEXT,
                error               TEXT,
                requested_by        VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                requested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at        TIMESTAMPTZ,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_figma_jobs_template ON figma_jobs (template_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_figma_jobs_status ON figma_jobs (status);")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_figma_jobs_pending "
            "ON figma_jobs (status) WHERE status IN ('PENDING', 'RUNNING');"
        )
    else:
        op.create_table(
            "figma_templates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("file_key", sa.String(80), nullable=False),
            sa.Column("node_id", sa.String(80), nullable=False),
            sa.Column(
                "branch_id",
                sa.String(36),
                sa.ForeignKey("ad_accounts.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("platform", sa.String(20), nullable=False, server_default="meta", index=True),
            sa.Column("width", sa.Integer, nullable=False, server_default="1080"),
            sa.Column("height", sa.Integer, nullable=False, server_default="1080"),
            sa.Column("placeholder_schema", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("preview_image_url", sa.Text, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1"), index=True),
            sa.Column(
                "created_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_table(
            "figma_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "template_id",
                sa.String(36),
                sa.ForeignKey("figma_templates.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "source_combo_id",
                sa.String(10),
                sa.ForeignKey("ad_combos.combo_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("request_payload", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING", index=True),
            sa.Column("output_figma_url", sa.Text, nullable=True),
            sa.Column("output_image_url", sa.Text, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column(
                "requested_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_figma_jobs_pending;")
    op.execute("DROP INDEX IF EXISTS ix_figma_jobs_status;")
    op.execute("DROP INDEX IF EXISTS ix_figma_jobs_template;")
    op.execute("DROP TABLE IF EXISTS figma_jobs;")
    op.execute("DROP INDEX IF EXISTS ix_figma_templates_active;")
    op.execute("DROP INDEX IF EXISTS ix_figma_templates_platform;")
    op.execute("DROP INDEX IF EXISTS ix_figma_templates_branch;")
    op.execute("DROP TABLE IF EXISTS figma_templates;")
