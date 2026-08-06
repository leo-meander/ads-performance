"""winning_ad_months: add verdict column (WIN/LOSE), not just winners

Revision ID: 065_wam_verdict
Revises: 064_winning_ad_months
Create Date: 2026-08-06

Two behavior changes in winning_months_service required this:

1. Win-rate % must be wins / (wins + losses) that cleared the test
   threshold that month — not wins alone. That means LOSE verdicts now
   need a frozen row too, so the table needs a column to tell them apart.
2. Once an ad has a decided verdict (WIN or LOSE) for some month, it must
   never be re-tested in a later month. Enforcing that requires knowing
   about past LOSEs, which previously left no row at all.

Existing rows predate this column and were, by construction, only ever
winners — DEFAULT 'WIN' backfills them correctly with no data loss.

Ids are VARCHAR(36) per app.models.base.UUIDType — see 064's note on why a
native UUID column here breaks the FK to ad_accounts(id).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "065_wam_verdict"
down_revision: Union[str, None] = "064_winning_ad_months"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE winning_ad_months
            ADD COLUMN IF NOT EXISTS verdict VARCHAR(10) NOT NULL DEFAULT 'WIN';
        CREATE INDEX IF NOT EXISTS ix_wam_verdict ON winning_ad_months(verdict);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_wam_verdict;
        ALTER TABLE winning_ad_months DROP COLUMN IF EXISTS verdict;
    """)
