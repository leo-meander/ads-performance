"""Add tactics table + automation_rules.tactic_id for Madgicx-style preset tactics.

Revision ID: 032_tactics
Revises: 031_canva_job_id
Create Date: 2026-05-13

Phase 1+2 of the automation tactics layer. A "tactic" is a preset (STOP LOSS,
SURF, REVIVE, SUNSETTING, etc.) that owns 1+ AutomationRules. Bundling rules
under a tactic lets the UI toggle whole strategies on/off with one click and
lets the daily cron loop revert previous-day mutations cleanly.

Idempotent: IF NOT EXISTS / batch_alter_table on SQLite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "032_tactics"
down_revision: Union[str, None] = "031_canva_job_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS tactics (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                preset_type VARCHAR(50) NOT NULL,
                platform VARCHAR(20) NOT NULL DEFAULT 'meta',
                account_id VARCHAR(36) REFERENCES ad_accounts(id) ON DELETE SET NULL,
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_run_at TIMESTAMPTZ,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_tactics_account_id ON tactics(account_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_tactics_preset_type ON tactics(preset_type);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_tactics_is_active ON tactics(is_active);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_tactics_platform ON tactics(platform);")

        op.execute(
            """
            ALTER TABLE automation_rules
            ADD COLUMN IF NOT EXISTS tactic_id VARCHAR(36)
            REFERENCES tactics(id) ON DELETE CASCADE;
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_automation_rules_tactic_id ON automation_rules(tactic_id);"
        )
    else:
        # SQLite path used by local tests.
        op.create_table(
            "tactics",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("preset_type", sa.String(50), nullable=False, index=True),
            sa.Column("platform", sa.String(20), nullable=False, server_default="meta", index=True),
            sa.Column(
                "account_id",
                sa.String(36),
                sa.ForeignKey("ad_accounts.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("config", sa.JSON, nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1"), index=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        with op.batch_alter_table("automation_rules") as batch:
            batch.add_column(
                sa.Column(
                    "tactic_id",
                    sa.String(36),
                    sa.ForeignKey("tactics.id", ondelete="CASCADE"),
                    nullable=True,
                )
            )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_automation_rules_tactic_id;")
    op.execute("ALTER TABLE automation_rules DROP COLUMN IF EXISTS tactic_id;")
    op.execute("DROP INDEX IF EXISTS ix_tactics_platform;")
    op.execute("DROP INDEX IF EXISTS ix_tactics_is_active;")
    op.execute("DROP INDEX IF EXISTS ix_tactics_preset_type;")
    op.execute("DROP INDEX IF EXISTS ix_tactics_account_id;")
    op.execute("DROP TABLE IF EXISTS tactics;")
