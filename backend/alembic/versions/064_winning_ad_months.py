"""winning_ad_months: frozen monthly winning-creative awards

Revision ID: 064_winning_ad_months
Revises: 063_landing_page_ver
Create Date: 2026-08-03

The Creative Library verdict is dynamic — an ad's WIN/LOSE is recomputed
against the account's CURRENT blended ROAS, so the answer to "how many
winners did we ship in May?" changes every time the benchmark moves.

This table freezes the award: one row per (account, month, ad_name), written
once when the ad first clears that month's bar, with the roas / benchmark /
bookings AS OF that moment. Rows are INSERT-only — like budget_allocations,
never updated in place. A later benchmark shift can add winners to a month;
it can never demote one.

Only ads whose name contains "CRTV" are in scope (candidates AND benchmark).

Backfill runs from the app: POST /api/creative/winning-months/recompute, or
the cron endpoint /api/internal/tasks/freeze-winning-ads. Source data is
ad_daily_metrics, which starts 2026-05-01.

Id columns are VARCHAR(36), NOT the native UUID type: app.models.base defines
UUIDType = String(36) and every existing table follows that (ad_accounts.id is
varchar). A native `UUID` column here makes the FK to ad_accounts(id)
un-creatable — "Key columns are of incompatible types" — which is exactly how
the first cut of this migration crash-looped the backend on deploy. Ids are
generated in Python by TimestampMixin, so there is no DB-side default.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "064_winning_ad_months"
down_revision: Union[str, None] = "063_landing_page_ver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS winning_ad_months (
            id              VARCHAR(36) PRIMARY KEY,
            account_id      VARCHAR(36) NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
            month           DATE NOT NULL,
            ad_name         VARCHAR(500) NOT NULL,
            combo_id        VARCHAR(10) REFERENCES ad_combos(combo_id) ON DELETE SET NULL,
            target_audience VARCHAR(30),
            country         VARCHAR(10),
            spend           NUMERIC(15, 2),
            revenue         NUMERIC(15, 2),
            impressions     INTEGER,
            clicks          INTEGER,
            conversions     INTEGER,
            roas            NUMERIC(8, 4),
            benchmark_roas  NUMERIC(8, 4),
            frozen_at       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_winning_ad_month UNIQUE (account_id, month, ad_name)
        );
        CREATE INDEX IF NOT EXISTS ix_wam_account_id ON winning_ad_months(account_id);
        CREATE INDEX IF NOT EXISTS ix_wam_month      ON winning_ad_months(month);
        CREATE INDEX IF NOT EXISTS ix_wam_ad_name    ON winning_ad_months(ad_name);
        CREATE INDEX IF NOT EXISTS ix_wam_combo_id   ON winning_ad_months(combo_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS winning_ad_months;")
