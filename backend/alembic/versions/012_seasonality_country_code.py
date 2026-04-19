"""Add country_code to google_seasonality_events and seed JP/TW/secondary-market calendars

Revision ID: 012_seasonality_country_code
Revises: 011_google_recommendations
Create Date: 2026-04-19

Before: a single Vietnam-only calendar fired for every Google campaign in every branch.
After: each event is scoped to a country (VN/JP/TW/KR/HK/SG/US/AU). Detectors will
union the branch's home country with the campaign's targeted countries and only
fire events whose country_code is in that set.

The unique constraint moves from event_key alone to (country_code, event_key) so
low-season prefixes (low_*) can repeat across countries.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_seasonality_country_code"
down_revision: Union[str, None] = "011_google_recommendations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("SET LOCAL statement_timeout = 0")

    # 1. Add country_code, nullable at first so we can backfill
    op.add_column(
        "google_seasonality_events",
        sa.Column("country_code", sa.String(length=2), nullable=True),
    )

    # 2. Backfill existing rows — everything currently seeded is Vietnam
    op.execute("UPDATE google_seasonality_events SET country_code = 'VN' WHERE country_code IS NULL")

    # 3. Tighten to NOT NULL + index
    with op.batch_alter_table("google_seasonality_events") as batch:
        batch.alter_column("country_code", existing_type=sa.String(length=2), nullable=False)
    op.create_index(
        "ix_google_seasonality_events_country_code",
        "google_seasonality_events",
        ["country_code"],
    )

    # 4. Replace the (event_key) unique constraint with (country_code, event_key)
    #    so the same key (e.g. "low_autumn", "christmas") can repeat per country.
    if is_postgres:
        op.execute("ALTER TABLE google_seasonality_events DROP CONSTRAINT IF EXISTS uq_google_seasonality_event_key")
    else:
        with op.batch_alter_table("google_seasonality_events") as batch:
            try:
                batch.drop_constraint("uq_google_seasonality_event_key", type_="unique")
            except Exception:  # SQLite autogen name varies
                pass
    op.create_unique_constraint(
        "uq_google_seasonality_country_event",
        "google_seasonality_events",
        ["country_code", "event_key"],
    )

    # 5. Seed JP + TW + secondary-market events.
    #    Keys follow SOP conventions: low_* prefix is load-bearing (LOW_SEASON_SHIFT_TO_DEMANDGEN
    #    detector matches on startswith("low_")).
    op.execute(
        """
        INSERT INTO google_seasonality_events (
            id, country_code, event_key, name, start_month, start_day, end_month, end_day,
            lead_time_days, budget_bump_pct_min, budget_bump_pct_max,
            tcpa_adjust_pct_min, tcpa_adjust_pct_max, notes,
            created_at, updated_at
        ) VALUES
        -- ── JAPAN (Osaka) ──────────────────────────────────────
        ('12111111-0000-0000-0000-000000000001', 'JP', 'shogatsu', 'Shogatsu (New Year)',
            12, 20, 1, 5, 30, 30, 50, 20, 30,
            'Biggest JP travel peak. Ramp budget from late November; expect high ADR.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000002', 'JP', 'sakura', 'Cherry Blossom Season',
            3, 15, 4, 10, 30, 30, 50, 15, 20,
            'Inbound-heavy peak. Budget lift driven by foreign traffic — pair with inbound geo targets.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000003', 'JP', 'golden_week', 'Golden Week',
            4, 20, 5, 6, 30, 40, 60, 20, 30,
            'Domestic peak. 4-week lead is mandatory — inventory sells out fast.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000004', 'JP', 'obon', 'Obon (Summer Holiday)',
            8, 1, 8, 20, 21, 30, 50, 15, 25,
            'Domestic family travel. Start lifting budget in late July.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000005', 'JP', 'silver_week', 'Silver Week',
            9, 10, 9, 25, 21, 20, 30, 10, 15,
            'Short autumn domestic peak around Respect-for-the-Aged Day + Autumn Equinox.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000006', 'JP', 'momiji', 'Autumn Leaves (Koyo)',
            10, 15, 11, 30, 30, 20, 40, 10, 15,
            'Inbound-driven. ADR holds through November; creative should feature foliage/ryokan stays.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000007', 'JP', 'christmas', 'Christmas Couples Window',
            12, 10, 12, 25, 21, 15, 25, 10, 15,
            'Smaller than Shogatsu but premium couples demand spikes.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000008', 'JP', 'low_winter', 'Low Season (Post-Shogatsu)',
            1, 10, 2, 28, 7, -15, -10, -15, -10,
            'Quiet cold window after New Year. Shift to Demand Gen warm-up.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12111111-0000-0000-0000-000000000009', 'JP', 'low_rainy', 'Low Season (Tsuyu Rainy Season)',
            6, 1, 6, 30, 7, -10, -5, -10, -5,
            'Rainy season dampens domestic travel. Tighten tCPA; lean on inbound traffic.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),

        -- ── TAIWAN (Taipei / 1948 / Oani / Bread) ──────────────
        ('12222222-0000-0000-0000-000000000001', 'TW', 'chinese_ny', 'Lunar New Year (TW)',
            1, 15, 2, 20, 21, 30, 50, 20, 30,
            'Biggest TW travel peak. Book-ahead starts early January.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000002', 'TW', 'qingming', 'Tomb Sweeping (Qingming)',
            3, 28, 4, 7, 14, 15, 25, 10, 15,
            'Long weekend domestic mini-peak. 2-week lead time.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000003', 'TW', 'dragon_boat', 'Dragon Boat Festival',
            5, 28, 6, 15, 14, 15, 25, 10, 15,
            'Short summer domestic peak.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000004', 'TW', 'summer_peak', 'Summer Peak (TW)',
            6, 15, 8, 31, 30, 30, 50, 10, 20,
            'Student/family travel. Lift budget early June.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000005', 'TW', 'mid_autumn', 'Mid-Autumn Festival',
            9, 10, 10, 5, 14, 20, 30, 10, 15,
            'Mooncake season, 3-day weekend.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000006', 'TW', 'double_ten', 'Double Ten (National Day TW)',
            10, 1, 10, 14, 14, 15, 25, 10, 15,
            'National day long weekend. Fireworks events drive short stays.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000007', 'TW', 'christmas_newyear', 'Christmas & NYE (TW)',
            12, 15, 1, 5, 30, 20, 40, 10, 15,
            'Couples + inbound year-end window.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000008', 'TW', 'low_spring', 'Low Season (Spring TW)',
            3, 1, 3, 27, 7, -15, -10, -15, -10,
            'Quiet between Lunar NY and Qingming.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12222222-0000-0000-0000-000000000009', 'TW', 'low_autumn', 'Low Season (Late Autumn TW)',
            10, 20, 11, 30, 7, -10, -5, -10, -5,
            'Post-Double-Ten quiet window before year-end ramp.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),

        -- ── SECONDARY MARKETS (inbound source traffic) ─────────
        ('12333333-0000-0000-0000-000000000001', 'KR', 'seollal', 'Seollal (Korean Lunar NY)',
            1, 25, 2, 15, 21, 20, 30, 10, 15,
            'KR outbound peak. Relevant when branch targets Korean travelers.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000002', 'KR', 'chuseok', 'Chuseok (Korean Mid-Autumn)',
            9, 15, 10, 5, 21, 20, 30, 10, 15,
            'KR outbound autumn peak.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000003', 'HK', 'chinese_ny', 'Chinese NY (HK)',
            1, 20, 2, 15, 21, 20, 35, 10, 15,
            'HK outbound peak to JP/TW/VN.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000004', 'HK', 'mid_autumn', 'Mid-Autumn (HK)',
            9, 15, 10, 5, 14, 15, 25, 10, 15,
            'HK outbound mid-autumn window.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000005', 'SG', 'chinese_ny', 'Chinese NY (SG)',
            1, 25, 2, 15, 21, 20, 30, 10, 15,
            'SG outbound peak.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000006', 'SG', 'national_day_sg', 'SG National Day Long Weekend',
            8, 1, 8, 12, 14, 15, 25, 10, 15,
            'SG short outbound peak.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000007', 'US', 'thanksgiving', 'Thanksgiving',
            11, 15, 12, 1, 21, 15, 25, 10, 15,
            'US outbound long weekend. Applies only when branch runs US geo_target.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000008', 'US', 'christmas', 'US Christmas & NYE',
            12, 15, 1, 3, 21, 15, 25, 10, 15,
            'US year-end outbound window.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000009', 'AU', 'xmas_summer', 'Aussie Summer Holidays',
            12, 15, 1, 25, 21, 20, 30, 10, 15,
            'AU outbound summer break. Largest AU outbound window.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('12333333-0000-0000-0000-000000000010', 'AU', 'school_hol_apr', 'AU April School Holidays',
            4, 1, 4, 25, 14, 10, 20, 5, 10,
            'AU short mid-year outbound peak.',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )


def downgrade() -> None:
    # Drop newly-seeded non-VN rows so schema revert is clean
    op.execute("DELETE FROM google_seasonality_events WHERE country_code <> 'VN'")

    op.drop_constraint(
        "uq_google_seasonality_country_event",
        "google_seasonality_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_google_seasonality_event_key",
        "google_seasonality_events",
        ["event_key"],
    )

    op.drop_index(
        "ix_google_seasonality_events_country_code",
        table_name="google_seasonality_events",
    )
    op.drop_column("google_seasonality_events", "country_code")
