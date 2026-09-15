"""Backfill reservations.rate_plan_name from the PMS payload's own field

Revision ID: 073_res_rate_plan
Revises: 072_spy_monitor
Create Date: 2026-09-15

The PMS has always sent `rate_plan_name` as a top-level field. The sync
ignored it and instead re-derived the plan from a bracketed group at the end
of `room_type`, which resolved for 2.7%-7.9% of reservations depending on
branch -- so a rate plan like "EARLY26 2 NIGHTS" was simply absent from
Booking from Ads, and an early-bird campaign matched nothing.

The sync now reads the real field, but that only fixes rows synced from here
on. Every historical row already carries the untouched API response in
`raw_data`, so the backfill is a pure SQL update -- no PMS re-fetch, no
re-running the matcher.

Only rows where the payload actually carries a non-empty value are touched, so
a reservation whose plan legitimately came from a hand-typed room_type tag
(the KOL convention) keeps what it has.

Ids stay short -- alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "073_res_rate_plan"
down_revision: Union[str, None] = "072_spy_monitor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # sqlite test DB has no rows to backfill

    op.execute("""
        UPDATE reservations
           SET rate_plan_name = btrim(raw_data::jsonb ->> 'rate_plan_name'),
               updated_at     = now()
         WHERE raw_data IS NOT NULL
           AND btrim(coalesce(raw_data::jsonb ->> 'rate_plan_name', '')) <> ''
           AND rate_plan_name IS DISTINCT FROM btrim(raw_data::jsonb ->> 'rate_plan_name');
    """)


def downgrade() -> None:
    # The pre-backfill values were derived, not authored -- there is nothing
    # meaningful to restore, and re-deriving them would reinstate the bug.
    pass
