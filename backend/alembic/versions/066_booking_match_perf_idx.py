"""booking_matches: composite (branch, match_date) index for the dashboard

Revision ID: 066_bm_perf_idx
Revises: 065_wam_verdict
Create Date: 2026-08-06

Every /booking-matches endpoint filters the same way: equality on `branch`
(usually an IN over the user's selected branches) plus a range on `match_date`.
The table only had two single-column indexes, so Postgres could use exactly one
of them and then re-check the other predicate on every heap row — the whole
window's rows for a wide date range.

A composite with the equality column first lets one index scan satisfy both
predicates. The existing single-column ix on match_date stays: it still serves
the all-branches case, where there is no branch predicate to lead with.

Ids stay short — alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "066_bm_perf_idx"
down_revision: Union[str, None] = "065_wam_verdict"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bm_branch_date
            ON booking_matches(branch, match_date);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_bm_branch_date;")
