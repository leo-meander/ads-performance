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
    _match_country_tiers,
    _try_match,
    amount_tolerance,
    country_iso_matches_reservation,
)


def _res(country_iso):
    return SimpleNamespace(country_iso=country_iso)


def _booking(grand_total, num="R1", country_iso=None):
    return SimpleNamespace(
        grand_total=grand_total, reservation_number=num, country_iso=country_iso
    )


class TestMatchCountryTiers:
    def test_prefers_same_country_when_both_match_amount(self):
        same = _booking(1000.0, "SAME", country_iso="VN")
        cross = _booking(1000.0, "CROSS", country_iso="US")
        res = _match_country_tiers([cross, same], "VN", 1, 1000.0)
        assert res is not None
        matched, _ = res
        assert [r.reservation_number for r in matched] == ["SAME"]

    def test_cross_country_fallback_when_no_same_country(self):
        # Tier-3: window has zero same-country and zero null candidates →
        # cross-country fallback fires (the only signal we have).
        cross = _booking(1000.0, "CROSS", country_iso="US")
        res = _match_country_tiers([cross], "VN", 1, 1000.0)
        assert res is not None and res[0][0].reservation_number == "CROSS"

    def test_no_tier3_when_same_country_candidate_exists_but_amount_off(self):
        # Same-country candidate exists in the window (wrong amount). A
        # cross-country candidate matches the amount exactly. Refuse the
        # cross match — better to miss than mis-attribute on coincidence.
        same_wrong_amount = _booking(500.0, "SAME", country_iso="VN")
        cross_right_amount = _booking(1000.0, "CROSS", country_iso="US")
        res = _match_country_tiers(
            [same_wrong_amount, cross_right_amount], "VN", 1, 1000.0
        )
        assert res is None

    def test_no_tier3_when_null_country_candidate_exists_but_amount_off(self):
        # Same logic for null-country: presence of a null-iso candidate gates
        # tier-3 even if its amount doesn't fit.
        null_wrong_amount = _booking(500.0, "NULL", country_iso=None)
        cross_right_amount = _booking(1000.0, "CROSS", country_iso="US")
        res = _match_country_tiers(
            [null_wrong_amount, cross_right_amount], "VN", 1, 1000.0
        )
        assert res is None

    def test_tolerance_applies_within_2pct(self):
        # 988 is 1.2% off 1000 → within ±2%.
        b = _booking(988.0, "B", country_iso="VN")
        assert _match_country_tiers([b], "VN", 1, 1000.0) is not None

    def test_empty_pool(self):
        assert _match_country_tiers([], "VN", 1, 1000.0) is None


class TestAmountTolerance:
    def test_pct_window_with_floor(self):
        assert amount_tolerance(2700) == 54.0          # 2%
        assert amount_tolerance(10) == 0.5             # floor wins for tiny values

    def test_match_within_2pct(self):
        # Google reports 2686.91 (currency-converted) for a 2,700 booking → match.
        res = _try_match([_booking(2686.91)], 1, 2700.0)
        assert res is not None and res[1] == "Matched"

    def test_no_match_beyond_2pct(self):
        # 2,500 vs 2,700 = 7.4% off → no match.
        assert _try_match([_booking(2500.0)], 1, 2700.0) is None


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
