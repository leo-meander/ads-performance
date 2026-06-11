"""Add video_3s (3-second video plays) to ad_daily_metrics.

Revision ID: 046_ad_daily_video_3s
Revises: 045_branch_manager_approval
Create Date: 2026-06-11

Hook rate was computed as video_plays / impressions, but video_plays
(Meta's video_play_actions) counts every autoplay start — it tracks
impressions almost 1:1, inflating hook rate to 80-90%. Ads Manager's
Hook rate is 3-second plays / impressions; the 3s count lives in the
actions[] array under action_type "video_view".

This stores that raw 3s count per (account, ad, day). NULL for existing
rows — the daily sync is delete-then-insert over its whole window, so
the next run backfills it.

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, batch_alter_table on
the SQLite test path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046_ad_daily_video_3s"
down_revision: Union[str, None] = "045_branch_manager_approval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            "ALTER TABLE ad_daily_metrics ADD COLUMN IF NOT EXISTS video_3s INTEGER"
        )
    else:
        with op.batch_alter_table("ad_daily_metrics") as batch_op:
            batch_op.add_column(sa.Column("video_3s", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("ALTER TABLE ad_daily_metrics DROP COLUMN IF EXISTS video_3s")
    else:
        with op.batch_alter_table("ad_daily_metrics") as batch_op:
            batch_op.drop_column("video_3s")
