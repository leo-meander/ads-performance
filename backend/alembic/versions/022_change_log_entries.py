"""Change log entries — unified auto + manual activity tracker.

Revision ID: 022_change_log_entries
Revises: 021_ad_set_country_widen
Create Date: 2026-04-23

Captures every ad operation change (auto from rule engine / launch service +
manual external factors like landing page, seasonality, competitor, algorithm,
tracking integrity) so /country can correlate changes with perf shifts.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_change_log_entries"
down_revision: Union[str, None] = "021_ad_set_country_widen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS change_log_entries (
                id VARCHAR(36) PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                occurred_at TIMESTAMPTZ NOT NULL,
                category VARCHAR(40) NOT NULL,
                source VARCHAR(20) NOT NULL,
                triggered_by VARCHAR(20) NOT NULL,
                title VARCHAR(200) NOT NULL,
                description TEXT,
                country VARCHAR(8),
                branch VARCHAR(40),
                platform VARCHAR(20),
                account_id VARCHAR(36) REFERENCES ad_accounts(id) ON DELETE SET NULL,
                campaign_id VARCHAR(36) REFERENCES campaigns(id) ON DELETE SET NULL,
                ad_set_id VARCHAR(36) REFERENCES ad_sets(id) ON DELETE SET NULL,
                ad_id VARCHAR(36) REFERENCES ads(id) ON DELETE SET NULL,
                before_value JSONB,
                after_value JSONB,
                metrics_snapshot JSONB,
                source_url TEXT,
                author_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                action_log_id VARCHAR(36) REFERENCES action_logs(id) ON DELETE SET NULL,
                rule_id VARCHAR(36) REFERENCES automation_rules(id) ON DELETE SET NULL,
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMPTZ,
                deleted_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL
            );
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_country_occurred "
            "ON change_log_entries (country, occurred_at DESC);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_branch_occurred "
            "ON change_log_entries (branch, occurred_at DESC);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_occurred_at "
            "ON change_log_entries (occurred_at DESC);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_category ON change_log_entries (category);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_source ON change_log_entries (source);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_platform ON change_log_entries (platform);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_account_id ON change_log_entries (account_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_campaign_id ON change_log_entries (campaign_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_ad_set_id ON change_log_entries (ad_set_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_ad_id ON change_log_entries (ad_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_action_log_id ON change_log_entries (action_log_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cle_is_deleted ON change_log_entries (is_deleted);"
        )
    else:
        # SQLite test path — create_table with batch_alter_table compatible DDL.
        op.create_table(
            "change_log_entries",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column("triggered_by", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("country", sa.String(length=8), nullable=True),
            sa.Column("branch", sa.String(length=40), nullable=True),
            sa.Column("platform", sa.String(length=20), nullable=True),
            sa.Column(
                "account_id",
                sa.String(length=36),
                sa.ForeignKey("ad_accounts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "campaign_id",
                sa.String(length=36),
                sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "ad_set_id",
                sa.String(length=36),
                sa.ForeignKey("ad_sets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "ad_id",
                sa.String(length=36),
                sa.ForeignKey("ads.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("before_value", sa.JSON(), nullable=True),
            sa.Column("after_value", sa.JSON(), nullable=True),
            sa.Column("metrics_snapshot", sa.JSON(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column(
                "author_user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "action_log_id",
                sa.String(length=36),
                sa.ForeignKey("action_logs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "rule_id",
                sa.String(length=36),
                sa.ForeignKey("automation_rules.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "deleted_by",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        with op.batch_alter_table("change_log_entries") as batch:
            batch.create_index("ix_cle_country_occurred", ["country", "occurred_at"])
            batch.create_index("ix_cle_branch_occurred", ["branch", "occurred_at"])
            batch.create_index("ix_cle_occurred_at", ["occurred_at"])
            batch.create_index("ix_cle_category", ["category"])
            batch.create_index("ix_cle_source", ["source"])
            batch.create_index("ix_cle_platform", ["platform"])
            batch.create_index("ix_cle_account_id", ["account_id"])
            batch.create_index("ix_cle_campaign_id", ["campaign_id"])
            batch.create_index("ix_cle_ad_set_id", ["ad_set_id"])
            batch.create_index("ix_cle_ad_id", ["ad_id"])
            batch.create_index("ix_cle_action_log_id", ["action_log_id"])
            batch.create_index("ix_cle_is_deleted", ["is_deleted"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS change_log_entries;")
