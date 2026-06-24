"""Add booking_matches.confidence (confirmed vs inferred match tier).

Revision ID: 049_bm_confidence
Revises: 048_bm_matched_revenue
Create Date: 2026-06-24

(Revision id kept short — alembic_version.version_num is VARCHAR(32).)

The matcher now runs two tiers per ads row:
  - "confirmed": a subset (size 1..capacity) of the candidate reservations whose
    grand_totals sum to the ads revenue within ±5% — value AND count agree, so
    we trust these are the real ad-driven bookings (and the subset size also
    corrects the platform's fractional conversion overcount).
  - "inferred": no subset reconstructs the revenue, so we fall back to capacity
    assignment (conversion count = booking budget, best country/date first).

The dashboard surfaces the split so the team can see how many matches are
value-confirmed vs count-inferred. Existing rows are seeded "inferred" (they
predate the tier and get rewritten on the next match run anyway).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_bm_confidence"
down_revision: Union[str, None] = "048_bm_matched_revenue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "booking_matches",
        sa.Column("confidence", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_booking_matches_confidence", "booking_matches", ["confidence"]
    )
    op.execute("UPDATE booking_matches SET confidence = 'inferred' WHERE confidence IS NULL")


def downgrade() -> None:
    op.drop_index("ix_booking_matches_confidence", table_name="booking_matches")
    op.drop_column("booking_matches", "confidence")
