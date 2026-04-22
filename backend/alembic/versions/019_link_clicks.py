"""Add link_clicks column to metrics_cache

Revision ID: 019_link_clicks
Revises: 018_ga4_snapshots
Create Date: 2026-04-22

Meta's Insights API has two separate click metrics:
  - `clicks`              All clicks on the ad (post reactions, video plays,
                          profile taps, link clicks — everything). Inflated.
  - `inline_link_clicks`  Clicks that specifically went to the destination
                          link. This is the correct denominator when measuring
                          landing page traffic.

The landing-page analytics dashboard was using `clicks` which over-stated
the pre-page traffic by 2–3×. We add a dedicated `link_clicks` column so
reconciliation reads the apples-to-apples number. `clicks` is kept for
backward compatibility and other views.

Google Ads doesn't distinguish (every Google ad click is a link click) so
`link_clicks` there can be filled with the same value as `clicks`. For
older synced rows the column is NULL until a resync refreshes them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_link_clicks"
down_revision: Union[str, None] = "018_ga4_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute(
            """
            ALTER TABLE metrics_cache
            ADD COLUMN IF NOT EXISTS link_clicks INTEGER NOT NULL DEFAULT 0
            """
        )
    else:
        with op.batch_alter_table("metrics_cache") as batch:
            batch.add_column(sa.Column("link_clicks", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("metrics_cache") as batch:
        batch.drop_column("link_clicks")
