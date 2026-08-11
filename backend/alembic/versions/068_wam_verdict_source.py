"""winning_ad_months: add verdict_source + verdict_notes for manual overrides

Revision ID: 068_wam_verdict_source
Revises: 067_adm_acct_date_idx
Create Date: 2026-08-11

Per Mason: old ads stuck in TEST forever (never accumulate enough clicks/
bookings to clear MIN_TEST_CLICKS, and never will if spend stays low) need a
way to get a human-decided WIN/LOSE instead of sitting un-judged permanently
-- "giải quyết triệt để vấn đề thiếu dữ liệu kết luận ad tested."

Mirrors ad_combos.verdict_source / verdict_notes exactly (see
creative_service.auto_classify_all_combos and the PATCH /combos/{id}/verdict
endpoint) so the same "manual overrides never get silently re-decided"
convention applies here. Existing rows predate this column and were all
computed by freeze_winning_months -- DEFAULT 'auto' backfills them correctly.

Ids stay short -- alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "068_wam_verdict_source"
down_revision: Union[str, None] = "067_adm_acct_date_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE winning_ad_months
            ADD COLUMN IF NOT EXISTS verdict_source VARCHAR(10) NOT NULL DEFAULT 'auto',
            ADD COLUMN IF NOT EXISTS verdict_notes TEXT;
        CREATE INDEX IF NOT EXISTS ix_wam_verdict_source ON winning_ad_months(verdict_source);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_wam_verdict_source;
        ALTER TABLE winning_ad_months
            DROP COLUMN IF EXISTS verdict_notes,
            DROP COLUMN IF EXISTS verdict_source;
    """)
