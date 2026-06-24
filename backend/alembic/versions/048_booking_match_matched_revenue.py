"""Add booking_matches.matched_revenue (real PMS grand_total of a match).

Revision ID: 048_booking_match_matched_revenue
Revises: 047_metrics_conversions_numeric
Create Date: 2026-06-23

Booking-from-Ads switched from revenue-sum reconstruction to per-reservation
capacity assignment (the ad platform's conversion count is the booking budget;
we hand it that many of the most plausible real PMS bookings, ranked by country
+ date, without demanding the revenue sum to match within a tight tolerance).

Under that model the meaningful "matched revenue" is the real PMS grand_total of
the assigned reservations, not the ad-platform-reported value (which is
fractionally attributed and drifts from PMS). We keep ads_revenue for reference
and add matched_revenue for the ground-truth money. Backfill = ads_revenue so
pre-existing rows aren't zeroed before the next match run rewrites them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "048_booking_match_matched_revenue"
down_revision: Union[str, None] = "047_metrics_conversions_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "booking_matches",
        sa.Column("matched_revenue", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )
    # Seed existing rows with their ads_revenue so the dashboard isn't blank
    # until the next match run repopulates with true PMS totals.
    op.execute("UPDATE booking_matches SET matched_revenue = ads_revenue")


def downgrade() -> None:
    op.drop_column("booking_matches", "matched_revenue")
