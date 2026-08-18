"""ads: effective_status + preview_url; drop the meta_ad_states side table

Revision ID: 071_ads_status_preview
Revises: 070_meta_ad_states
Create Date: 2026-08-18

070 created meta_ad_states to hold each Meta ad's delivery status + shareable
preview link. That was a table too many: `ads` already holds one row per
platform_ad_id, is already written by sync_engine.sync_meta_account, and
meta_client.fetch_ads already pages through exactly those ads -- so the two
fields ride along on a request that was happening anyway, refreshed by the
twice-daily platform cron instead of a second nightly job and a second Meta
call per account.

070 is NOT edited or deleted: it already ran in production, so its revision id
is sitting in alembic_version. Rewriting history there is what turns a deploy
into a crash-loop ("Can't locate revision"). This migration supersedes it
forward instead, and drops the now-unused table at the end.

The columns are nullable because `ads` is shared with Google/TikTok, which
have neither field. Existing Meta rows stay NULL until the next platform sync;
ad_state.summarize_states falls back to `status` meanwhile, so the UI column is
never blank.

The index serves the read path both surfaces use: every ad in one branch
carrying one ad_name (a creative shipped into several campaigns is several
ads). `name` had no index at all.

Ids stay short -- alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "071_ads_status_preview"
down_revision: Union[str, None] = "070_meta_ad_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ads ADD COLUMN IF NOT EXISTS effective_status VARCHAR(40);
        ALTER TABLE ads ADD COLUMN IF NOT EXISTS preview_url      VARCHAR(1000);
        CREATE INDEX IF NOT EXISTS ix_ads_effective_status ON ads(effective_status);
        CREATE INDEX IF NOT EXISTS ix_ads_account_name     ON ads(account_id, name);
    """)
    # Nothing reads meta_ad_states any more. It only ever held a snapshot that
    # the next platform sync reproduces, so there is nothing to migrate across.
    op.execute("DROP TABLE IF EXISTS meta_ad_states;")


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_ads_account_name;
        DROP INDEX IF EXISTS ix_ads_effective_status;
        ALTER TABLE ads DROP COLUMN IF EXISTS preview_url;
        ALTER TABLE ads DROP COLUMN IF EXISTS effective_status;
    """)
    # meta_ad_states is left dropped: 070's upgrade() recreates it if the chain
    # is walked back that far, and it is CREATE TABLE IF NOT EXISTS.
