"""ads: effective_status + preview_url (Meta)

Revision ID: 070_ads_status_preview
Revises: 069_wam_scope
Create Date: 2026-08-17

The Ad Name Performance table and the Creative Library drawer could show what
an ad spent but not whether it is still running, and gave no way to open the
ad itself. Both facts live on the Meta Ad object.

They belong on `ads`, not on ad_daily_metrics (whose grain is a day -- a pause
today would have to be written back across every past day) and not on a new
side table: `ads` already holds one row per platform_ad_id, is already written
by sync_engine.sync_meta_account, and fetch_ads already pages through exactly
these ads, so the two fields ride along on a request that was happening
anyway. Nothing new to schedule.

Nullable because `ads` is shared with Google/TikTok, which have neither field.

The index serves the read path both surfaces use: every ad in one branch
carrying one ad_name (a creative shipped into several campaigns is several
ads). `name` had no index at all.

Ids stay short -- alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "070_ads_status_preview"
down_revision: Union[str, None] = "069_wam_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ads ADD COLUMN IF NOT EXISTS effective_status VARCHAR(40);
        ALTER TABLE ads ADD COLUMN IF NOT EXISTS preview_url      VARCHAR(1000);
        CREATE INDEX IF NOT EXISTS ix_ads_effective_status ON ads(effective_status);
        CREATE INDEX IF NOT EXISTS ix_ads_account_name     ON ads(account_id, name);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_ads_account_name;
        DROP INDEX IF EXISTS ix_ads_effective_status;
        ALTER TABLE ads DROP COLUMN IF EXISTS preview_url;
        ALTER TABLE ads DROP COLUMN IF EXISTS effective_status;
    """)
