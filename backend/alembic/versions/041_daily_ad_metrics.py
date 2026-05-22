"""Daily per-ad performance metrics pulled from Meta.

Revision ID: 041_daily_ad_metrics
Revises: 040_user_page_permissions
Create Date: 2026-05-22

Backs the new "Ad Name Performance" page. Unlike ad_combos (lifetime totals,
keyed by ad_name), this table stores ONE row per (account, ad_id, day) so each
ad can be tracked day-by-day and ads sharing a name but living in different
campaigns/adsets stay distinct.

  - grain:   (account_id, ad_id, date)  — UNIQUE
  - identity: campaign_id/name, adset_id/name, ad_id/name (Meta platform ids
              stored as strings, not internal FKs)
  - metrics:  RAW counts only (spend, impressions, clicks, conversions,
              revenue, leads, engagement, video_plays, thruplay, video_p100).
              Derived rates (roas, ctr, cpp, cost_per_lead, hook_rate, ...) are
              computed at read time so window aggregation is always correct.

Only rows with spend > 0 are written by the sync (see
app/services/daily_ad_metrics_sync.py). Re-sync is delete-then-insert per
account window, so re-runs never double-count.

Idempotent: CREATE TABLE IF NOT EXISTS (Postgres) / op.create_table (SQLite).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "041_daily_ad_metrics"
down_revision: Union[str, None] = "040_user_page_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS ad_daily_metrics (
                id            VARCHAR(36) PRIMARY KEY,
                account_id    VARCHAR(36) NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
                campaign_id   VARCHAR(64),
                campaign_name VARCHAR(500),
                adset_id      VARCHAR(64),
                adset_name    VARCHAR(500),
                ad_id         VARCHAR(64) NOT NULL,
                ad_name       VARCHAR(500),
                date          DATE NOT NULL,
                spend         NUMERIC(15, 2),
                impressions   INTEGER,
                clicks        INTEGER,
                conversions   INTEGER,
                revenue       NUMERIC(15, 2),
                leads         INTEGER,
                engagement    INTEGER,
                video_plays   INTEGER,
                thruplay      INTEGER,
                video_p100    INTEGER,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ad_daily_metrics_acc_ad_date UNIQUE (account_id, ad_id, date)
            );
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ad_daily_metrics_acc_date "
            "ON ad_daily_metrics (account_id, date);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ad_daily_metrics_ad_id "
            "ON ad_daily_metrics (ad_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ad_daily_metrics_ad_name "
            "ON ad_daily_metrics (ad_name);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ad_daily_metrics_campaign_id "
            "ON ad_daily_metrics (campaign_id);"
        )
    else:
        op.create_table(
            "ad_daily_metrics",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "account_id",
                sa.String(36),
                sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("campaign_id", sa.String(64), nullable=True, index=True),
            sa.Column("campaign_name", sa.String(500), nullable=True),
            sa.Column("adset_id", sa.String(64), nullable=True),
            sa.Column("adset_name", sa.String(500), nullable=True),
            sa.Column("ad_id", sa.String(64), nullable=False, index=True),
            sa.Column("ad_name", sa.String(500), nullable=True, index=True),
            sa.Column("date", sa.Date, nullable=False),
            sa.Column("spend", sa.Numeric(15, 2), nullable=True),
            sa.Column("impressions", sa.Integer, nullable=True),
            sa.Column("clicks", sa.Integer, nullable=True),
            sa.Column("conversions", sa.Integer, nullable=True),
            sa.Column("revenue", sa.Numeric(15, 2), nullable=True),
            sa.Column("leads", sa.Integer, nullable=True),
            sa.Column("engagement", sa.Integer, nullable=True),
            sa.Column("video_plays", sa.Integer, nullable=True),
            sa.Column("thruplay", sa.Integer, nullable=True),
            sa.Column("video_p100", sa.Integer, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("account_id", "ad_id", "date", name="uq_ad_daily_metrics_acc_ad_date"),
        )
        op.create_index(
            "ix_ad_daily_metrics_acc_date", "ad_daily_metrics", ["account_id", "date"]
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ad_daily_metrics_campaign_id;")
    op.execute("DROP INDEX IF EXISTS ix_ad_daily_metrics_ad_name;")
    op.execute("DROP INDEX IF EXISTS ix_ad_daily_metrics_ad_id;")
    op.execute("DROP INDEX IF EXISTS ix_ad_daily_metrics_acc_date;")
    op.execute("DROP TABLE IF EXISTS ad_daily_metrics;")
