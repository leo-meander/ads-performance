"""Widen metrics_cache.conversions from Integer to Numeric.

Revision ID: 047_metrics_conversions_numeric
Revises: 046_ad_daily_video_3s
Create Date: 2026-06-18

Google Ads attributes FRACTIONAL conversions (e.g. 0.33, 6.33) — a single
purchase can be split across touchpoints. The column was Integer, so every
daily sync row was rounded toward zero before storage. For low-volume accounts
this wiped out most conversions (Taipei last 7d: Google reported ~6.33, our
dashboard showed 2), which in turn corrupted the derived CR / CPA / AOV / ROAS.

Widening Integer -> Numeric(15, 2) is loss-less for existing rows (whole
numbers become x.00). Meta/TikTok continue to write whole numbers. Read paths
that int()/round the SUMMED total are unaffected — only per-row storage needed
the precision. Paired with the float fix in
google_client._fetch_purchase_metrics (which stopped truncating at the API
boundary).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047_metrics_conversions_numeric"
down_revision: Union[str, None] = "046_ad_daily_video_3s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE metrics_cache
            ALTER COLUMN conversions TYPE NUMERIC(15, 2)
            USING conversions::numeric(15, 2);
            """
        )
    else:
        # SQLite (tests) — batch rebuild. SQLite is dynamically typed so this is
        # cosmetic, but keep the schema definition in sync.
        with op.batch_alter_table("metrics_cache") as batch:
            batch.alter_column(
                "conversions",
                existing_type=sa.Integer(),
                type_=sa.Numeric(15, 2),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # Truncate fractions back to integer on the way down.
        op.execute(
            """
            ALTER TABLE metrics_cache
            ALTER COLUMN conversions TYPE INTEGER
            USING round(conversions)::integer;
            """
        )
    else:
        with op.batch_alter_table("metrics_cache") as batch:
            batch.alter_column(
                "conversions",
                existing_type=sa.Numeric(15, 2),
                type_=sa.Integer(),
                existing_nullable=False,
            )
