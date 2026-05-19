"""Tests for app.utils.country_normalize.

Covers every variant Cloudbeds was observed to emit in production
(SELECT DISTINCT country FROM reservations, 2026-05). If a new value
appears in PMS data and `normalize_country_to_iso` returns None for a
non-junk input, add it to the fixture below first, then fix the mapping
in country_normalize.py until this test passes again.
"""

import pytest

from app.utils.country_normalize import normalize_country_to_iso


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Full English names
        ("Taiwan", "TW"),
        ("United States", "US"),
        ("United States of America", "US"),
        ("United Kingdom", "GB"),
        ("South Korea", "KR"),
        ("North Korea", "KP"),
        ("Germany", "DE"),
        ("Australia", "AU"),
        ("China", "CN"),
        ("Japan", "JP"),
        ("Canada", "CA"),
        ("Philippines", "PH"),
        ("Singapore", "SG"),
        ("Hong Kong", "HK"),
        ("Hong Kong SAR China", "HK"),
        ("Macau", "MO"),
        ("Macau SAR China", "MO"),
        ("Vietnam", "VN"),
        ("Việt Nam", "VN"),
        ("Czech Republic", "CZ"),
        ("Turkey", "TR"),  # renamed to Türkiye in ISO-3166 2022
        ("Russia", "RU"),
        ("Russian Federation", "RU"),
        ("Myanmar", "MM"),
        ("United Arab Emirates", "AE"),
        # ISO-2 passthrough
        ("TW", "TW"),
        ("US", "US"),
        ("KR", "KR"),
        ("vn", "VN"),  # lowercase ISO
        # Junk → None
        (None, None),
        ("", None),
        ("Unknown", None),
        ("unknown", None),
        ("00", None),
        ("0", None),
        ("  ", None),
        # Random invalid two-letter
        ("ZZ", None),
        # Should not over-match: North Korea must NOT map to KR
        ("North Korea", "KP"),
    ],
)
def test_normalize_country_to_iso(raw, expected):
    assert normalize_country_to_iso(raw) == expected


def test_korea_substring_does_not_overmatch():
    """Regression: the old fuzzy matcher mapped 'North Korea' to KR via the
    'korea' substring. Make sure that case is locked down."""
    assert normalize_country_to_iso("North Korea") == "KP"
    assert normalize_country_to_iso("South Korea") == "KR"


def test_macau_does_not_collide_with_china():
    """Regression: the old matcher mapped 'Macau SAR China' to CN because
    'china' appeared as a substring. Macau must resolve to MO."""
    assert normalize_country_to_iso("Macau SAR China") == "MO"
    assert normalize_country_to_iso("Macao SAR China") == "MO"
    assert normalize_country_to_iso("China") == "CN"
