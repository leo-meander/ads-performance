"""ad_daily_metrics: composite (account_id, date) index

Revision ID: 067_adm_acct_date_idx
Revises: 066_bm_perf_idx
Create Date: 2026-08-09

Every winning-months query filters the same shape: equality on `account_id`
plus a range on `date` (one calendar month at a time in compute_month_verdicts,
the whole history in compute_lifetime_benchmark). `date` had no index at all —
only `account_id` did, plus the uq_ad_daily_metrics_acc_ad_date constraint,
whose (account_id, ad_id, date) ordering puts ad_id between the two columns
actually being filtered, so a month range can't be satisfied by an index scan.

That was tolerable while the table only held May onward. The backfill to
2026-01-01 roughly doubled it, and a rebuild walks ~8 months x every account,
so each month's GROUP BY re-checked the date predicate against every row the
account had.

Leading with the equality column lets one index scan serve both predicates.

Ids stay short — alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "067_adm_acct_date_idx"
down_revision: Union[str, None] = "066_bm_perf_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_adm_account_date
            ON ad_daily_metrics(account_id, date);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_adm_account_date;")
