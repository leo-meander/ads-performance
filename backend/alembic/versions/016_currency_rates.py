"""Currency rates table for editable FX conversions to VND

Revision ID: 016_currency_rates
Revises: 015_ad_country_matching
Create Date: 2026-04-22

Adds a small admin-editable settings table storing one row per ISO-4217
currency code used by the platform. `rate_to_vnd` is how many VND a single
unit of that currency is worth — reporting code multiplies native amounts
by this factor to normalise spend/revenue across the 6 branches to VND.

VND is the base currency because Meander Saigon (the largest branch by
spend volume) reports natively in VND and finance books totals in VND.

Seeds the 5 currencies currently in use (VND, USD, TWD, JPY, THB) with
approximate mid-market rates so reports work out-of-the-box; the Settings
UI lets admins update them whenever rates drift.

Idempotent per project memory (IF NOT EXISTS / ON CONFLICT). No manual
`UPDATE alembic_version` — alembic handles that itself.

Notes on rerun safety: an earlier version of this migration created the
table with column `rate_to_usd`. If that column exists on the target DB
(fresh merge), we drop the table so the new schema + seeds land cleanly —
the only contents are seed rows, so this is safe.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_currency_rates"
down_revision: Union[str, None] = "015_ad_country_matching"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# rate_to_vnd = how many VND 1 unit of `currency` is worth (mid-market approx)
SEED_RATES = [
    ("VND", "1"),
    ("USD", "25400"),
    ("TWD", "780"),
    ("JPY", "160"),
    ("THB", "725"),
]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # If a pre-release version of 016 created the table with rate_to_usd,
        # drop it so the new schema applies cleanly (seed-only data).
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'currency_rates'
                      AND column_name = 'rate_to_usd'
                ) THEN
                    DROP TABLE currency_rates;
                END IF;
            END $$;
            """
        )
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS currency_rates (
                currency VARCHAR(3) PRIMARY KEY,
                rate_to_vnd NUMERIC(20,10) NOT NULL,
                updated_by VARCHAR(100),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for code, rate in SEED_RATES:
            op.execute(
                sa.text(
                    "INSERT INTO currency_rates (currency, rate_to_vnd) "
                    "VALUES (:c, :r) ON CONFLICT (currency) DO NOTHING"
                ).bindparams(c=code, r=rate)
            )
    else:
        op.create_table(
            "currency_rates",
            sa.Column("currency", sa.String(3), primary_key=True),
            sa.Column("rate_to_vnd", sa.Numeric(20, 10), nullable=False),
            sa.Column("updated_by", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        from datetime import datetime, timezone as tz

        now = datetime.now(tz.utc)
        for code, rate in SEED_RATES:
            op.execute(
                sa.text(
                    "INSERT INTO currency_rates (currency, rate_to_vnd, created_at, updated_at) "
                    "VALUES (:c, :r, :t, :t)"
                ).bindparams(c=code, r=rate, t=now)
            )


def downgrade() -> None:
    op.drop_table("currency_rates")
