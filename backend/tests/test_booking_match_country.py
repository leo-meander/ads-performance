"""Tests for ads/reservation country reconciliation in booking matching.

The ads side stores the country as parsed from the campaign/adset name (Meta's
ISO-2 prefix, Google's ISO-2 suffix). That vocabulary diverges from the
reservation side, which normalises Cloudbeds' country to ISO-2 via
normalize_country_to_iso — most notably Google's "UK" vs the reservation's
"GB". The matching layer must reconcile the two before comparing, otherwise
UK-targeted bookings never match.
"""

from types import SimpleNamespace

from app.services.booking_match_service import (
    METHOD_CROSS,
    METHOD_EXACT,
    METHOD_MIXED,
    METHOD_NULL,
    _classify_match_method,
    country_iso_matches_reservation,
)


def _res(country_iso):
    return SimpleNamespace(country_iso=country_iso)


class TestCountryIsoMatchesReservation:
    def test_google_uk_matches_reservation_gb(self):
        # Regression: Google campaigns store "UK"; reservations store "GB".
        assert country_iso_matches_reservation("UK", _res("GB")) is True

    def test_iso2_passthrough_matches(self):
        assert country_iso_matches_reservation("VN", _res("VN")) is True
        assert country_iso_matches_reservation("TW", _res("TW")) is True
        assert country_iso_matches_reservation("JP", _res("JP")) is True

    def test_lowercase_ads_iso_matches(self):
        assert country_iso_matches_reservation("vn", _res("VN")) is True

    def test_different_country_does_not_match(self):
        assert country_iso_matches_reservation("VN", _res("TW")) is False

    def test_null_reservation_iso_never_matches_here(self):
        assert country_iso_matches_reservation("VN", _res(None)) is False

    def test_null_ads_iso_never_matches(self):
        assert country_iso_matches_reservation(None, _res("VN")) is False

    def test_unmappable_ads_country_does_not_match(self):
        # Multi-country marker / junk normalises to None → no match.
        assert country_iso_matches_reservation("ALL", _res("VN")) is False


class TestClassifyMatchMethod:
    def test_uk_gb_classified_exact_not_null(self):
        # The reconciled match must be tagged "exact", not downgraded to
        # null_country just because the raw codes ("UK" vs "GB") differ.
        method = _classify_match_method([_res("GB")], "UK")
        assert method == METHOD_EXACT

    def test_all_null_reservations_classified_null(self):
        method = _classify_match_method([_res(None), _res(None)], "VN")
        assert method == METHOD_NULL

    def test_mixed_exact_and_null(self):
        method = _classify_match_method([_res("VN"), _res(None)], "VN")
        assert method == METHOD_MIXED

    def test_cross_country_when_nationality_differs(self):
        # An "HK" campaign matched (by date+revenue) to a TW guest is a valid
        # tier-3 fallback match — tagged cross_country, not excluded.
        method = _classify_match_method([_res("TW")], "HK")
        assert method == METHOD_CROSS

    def test_cross_country_dominates_mixed(self):
        # Any cross-country reservation in a combo flags the whole match cross.
        method = _classify_match_method([_res("HK"), _res("US"), _res(None)], "HK")
        assert method == METHOD_CROSS
