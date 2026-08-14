"""winning_ad_months: add scope so a second, unfiltered verdict set can coexist

Revision ID: 069_wam_scope
Revises: 068_wam_verdict_source
Create Date: 2026-08-14

Per Mason: alongside the design-team KPI (which excludes KOL-named ads and the
Bread branch) he wants a second Winning-by-Month view covering EVERY ad, with
no exclusions, purely for his own tracking -- "tab nay se tinh tat ca cac ads
(tinh ca Bread luon)".

The two cannot share rows. A verdict is frozen against the account's blended
lifetime benchmark, and that benchmark differs between the two universes (the
'all' bar includes KOL spend), so the same ad can legitimately be WIN in one
and LOSE in the other. `scope` keeps them apart, and the unique constraint
gains it so "an ad is judged once, ever" now means once per scope.

Existing rows are all KPI rows -- DEFAULT 'kpi' backfills them correctly, and
nothing about the KPI tab changes.

Ids stay short -- alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "069_wam_scope"
down_revision: Union[str, None] = "068_wam_verdict_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE winning_ad_months
            ADD COLUMN IF NOT EXISTS scope VARCHAR(10) NOT NULL DEFAULT 'kpi';
        CREATE INDEX IF NOT EXISTS ix_wam_scope ON winning_ad_months(scope);

        ALTER TABLE winning_ad_months
            DROP CONSTRAINT IF EXISTS uq_winning_ad_month;
        ALTER TABLE winning_ad_months
            ADD CONSTRAINT uq_winning_ad_month
            UNIQUE (account_id, month, ad_name, scope);
    """)


def downgrade() -> None:
    # Drop the 'all' rows first: without them the 3-column constraint below
    # would collide with the KPI rows they duplicate.
    op.execute("""
        DELETE FROM winning_ad_months WHERE scope <> 'kpi';

        ALTER TABLE winning_ad_months
            DROP CONSTRAINT IF EXISTS uq_winning_ad_month;
        ALTER TABLE winning_ad_months
            ADD CONSTRAINT uq_winning_ad_month
            UNIQUE (account_id, month, ad_name);

        DROP INDEX IF EXISTS ix_wam_scope;
        ALTER TABLE winning_ad_months DROP COLUMN IF EXISTS scope;
    """)
