"""Add normalised ISO-2 country to reservations + match-method to booking_matches.

Revision ID: 039_reservation_country_iso
Revises: 038_approval_note
Create Date: 2026-05-19

Cloudbeds returns Reservation.country in mixed format (full English names,
ISO-2 codes, "Unknown"/None junk). The booking-match service was doing fuzzy
substring matching to bridge ISO-2 ads codes to PMS country names, which
silently miscounted: "North Korea" matched KR, "Macau SAR China" matched CN,
and ~3k junk-country rows always fell into the "match any reservation by
revenue" fallback — producing TW campaigns matched to US guests.

This migration adds:
  - reservations.country_iso (CHAR(2)) — populated at sync time via
    app.utils.country_normalize.normalize_country_to_iso. Old rows are
    backfilled in-SQL using a CASE statement covering the values that
    actually appear in production (verified against SELECT DISTINCT
    country). Anything not covered stays NULL; the next reservation sync
    will fill it in correctly via the Python normaliser.
  - booking_matches.country_match_method (VARCHAR(30)) — records whether a
    match was via exact ISO equality or the legacy "fallback when PMS
    country is missing" path, so the UI can warn on low-confidence rows.

Idempotent: ADD COLUMN IF NOT EXISTS / batch_alter_table for SQLite tests.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039_reservation_country_iso"
down_revision: Union[str, None] = "038_approval_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Backfill cases for the values actually present in production data.
# Verified via: SELECT DISTINCT country, COUNT(*) FROM reservations.
# Every full-name string here was matched to the same ISO that
# app.utils.country_normalize.normalize_country_to_iso would produce.
_BACKFILL_PAIRS: list[tuple[str, str]] = [
    ("Taiwan", "TW"), ("United States of America", "US"),
    ("United Kingdom", "GB"), ("United States", "US"),
    ("South Korea", "KR"), ("Germany", "DE"), ("Australia", "AU"),
    ("China", "CN"), ("Japan", "JP"), ("Canada", "CA"),
    ("Philippines", "PH"), ("Singapore", "SG"), ("Hong Kong", "HK"),
    ("Netherlands", "NL"), ("France", "FR"), ("Malaysia", "MY"),
    ("India", "IN"), ("Vietnam", "VN"), ("Switzerland", "CH"),
    ("Israel", "IL"), ("Thailand", "TH"), ("Indonesia", "ID"),
    ("Italy", "IT"), ("Ireland", "IE"), ("Spain", "ES"),
    ("Belgium", "BE"), ("Sweden", "SE"), ("New Zealand", "NZ"),
    ("Austria", "AT"), ("Norway", "NO"), ("Denmark", "DK"),
    ("Poland", "PL"), ("Mexico", "MX"), ("Cambodia", "KH"),
    ("Finland", "FI"), ("Brazil", "BR"), ("Russia", "RU"),
    ("Turkey", "TR"), ("Portugal", "PT"), ("Romania", "RO"),
    ("Chile", "CL"), ("United Arab Emirates", "AE"),
    ("Czech Republic", "CZ"), ("Argentina", "AR"), ("Lithuania", "LT"),
    ("Saudi Arabia", "SA"), ("Myanmar", "MM"), ("Hungary", "HU"),
    ("South Africa", "ZA"), ("Greece", "GR"), ("Slovenia", "SI"),
    ("Estonia", "EE"), ("Macau", "MO"), ("Macau SAR China", "MO"),
    ("Peru", "PE"), ("Bulgaria", "BG"), ("Kazakhstan", "KZ"),
    ("Kuwait", "KW"), ("Colombia", "CO"), ("Ukraine", "UA"),
    ("Iceland", "IS"), ("Sri Lanka", "LK"), ("Egypt", "EG"),
    ("Cyprus", "CY"), ("Luxembourg", "LU"), ("Latvia", "LV"),
    ("Slovakia", "SK"), ("Qatar", "QA"), ("Croatia", "HR"),
    ("North Korea", "KP"), ("American Samoa", "AS"), ("Brunei", "BN"),
    ("Ecuador", "EC"), ("Oman", "OM"), ("Pakistan", "PK"),
    ("Guam", "GU"), ("Mongolia", "MN"), ("Vanuatu", "VU"),
    ("Bangladesh", "BD"), ("Bahamas", "BS"), ("Faroe Islands", "FO"),
    ("Uruguay", "UY"), ("Nigeria", "NG"), ("Panama", "PA"),
    ("Morocco", "MA"), ("Laos", "LA"), ("Libya", "LY"),
    ("Lesotho", "LS"), ("Malawi", "MW"), ("Malta", "MT"),
    ("Mauritius", "MU"), ("Kenya", "KE"), ("Jamaica", "JM"),
    ("Kyrgyzstan", "KG"), ("Uzbekistan", "UZ"), ("Azerbaijan", "AZ"),
    ("Iran", "IR"), ("Madagascar", "MG"), ("Algeria", "DZ"),
    ("Cameroon", "CM"), ("Tanzania", "TZ"), ("Honduras", "HN"),
    ("Tonga", "TO"), ("Bhutan", "BT"), ("Costa Rica", "CR"),
    ("Reunion", "RE"), ("Dominican Republic", "DO"), ("Dominica", "DM"),
    ("Isle of Man", "IM"), ("Seychelles", "SC"), ("Serbia", "RS"),
    ("Armenia", "AM"),
]

# Values that should remain NULL — junk Cloudbeds emits when no country set.
_JUNK_TO_NULL = ["Unknown", "00", "0"]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(
            """
            ALTER TABLE reservations
            ADD COLUMN IF NOT EXISTS country_iso CHAR(2);
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_reservations_country_iso
            ON reservations (country_iso);
            """
        )
        op.execute(
            """
            ALTER TABLE booking_matches
            ADD COLUMN IF NOT EXISTS country_match_method VARCHAR(30);
            """
        )

        # Backfill in two passes: ISO-2 inputs (already correct, just uppercase
        # them) then full-name inputs via per-value UPDATE.
        op.execute(
            """
            UPDATE reservations
            SET country_iso = UPPER(country)
            WHERE country_iso IS NULL
              AND country IS NOT NULL
              AND LENGTH(country) = 2
              AND country ~ '^[A-Za-z]{2}$';
            """
        )
        for raw, iso in _BACKFILL_PAIRS:
            op.execute(
                sa.text(
                    "UPDATE reservations SET country_iso = :iso "
                    "WHERE country_iso IS NULL AND country = :raw"
                ).bindparams(iso=iso, raw=raw)
            )
        # Junk values stay NULL — nothing to do, country_iso defaults to NULL.

    else:
        with op.batch_alter_table("reservations") as batch:
            batch.add_column(sa.Column("country_iso", sa.String(2), nullable=True))
        with op.batch_alter_table("booking_matches") as batch:
            batch.add_column(
                sa.Column("country_match_method", sa.String(30), nullable=True)
            )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE booking_matches DROP COLUMN IF EXISTS country_match_method;"
    )
    op.execute("DROP INDEX IF EXISTS ix_reservations_country_iso;")
    op.execute("ALTER TABLE reservations DROP COLUMN IF EXISTS country_iso;")
