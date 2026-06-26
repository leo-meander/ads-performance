"""Tests for the Booking-from-Ads matcher.

Two concerns are covered:

1. Country reconciliation — the ads side stores the country parsed from the
   campaign/adset name (Meta's ISO-2 prefix, Google's ISO-2 suffix). That
   vocabulary diverges from the reservation side, which normalises Cloudbeds'
   country to ISO-2 (most notably Google's "UK" vs the reservation's "GB").
   The matcher must reconcile the two before comparing.

2. Capacity assignment — the matcher no longer reconstructs the ads revenue
   from an exact subset of reservations (the platform's conversions/revenue are
   fractionally attributed, so that was structurally lossy). Instead each ads
   row claims up to `capacity` real reservations from the same branch + kind
   within ±1 day, ranked by country, then date, then closest single-booking
   value. _assign_row is that core.
"""

from datetime import date
from types import SimpleNamespace

from app.services.booking_match_service import (
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_INFERRED,
    METHOD_CROSS,
    METHOD_EXACT,
    METHOD_MIXED,
    METHOD_NULL,
    _assign_row,
    _classify_match_method,
    _country_rank,
    _find_value_subset,
    amount_tolerance,
    country_iso_matches_reservation,
)

DAY = date(2026, 6, 10)


def _res(country_iso):
    return SimpleNamespace(country_iso=country_iso)


def _booking(grand_total, num="R1", country_iso=None):
    return SimpleNamespace(
        grand_total=grand_total,
        reservation_number=num,
        id=num,
        country_iso=country_iso,
    )


def _pool(*, same_day=None, prev_day=None, next_day=None, branch="Saigon", kind="website"):
    """Build a res_by_key dict the matcher consumes."""
    out: dict = {}
    if same_day:
        out[(DAY, branch, kind)] = list(same_day)
    if prev_day:
        out[(date(2026, 6, 9), branch, kind)] = list(prev_day)
    if next_day:
        out[(date(2026, 6, 11), branch, kind)] = list(next_day)
    return out


# Default revenue is huge so tier-1 (value confirmation) can't fire and the
# capacity/ranking tests exercise tier-2; confirmation is tested separately.
def _assign_full(res_by_key, *, country="VN", revenue=10_000_000.0, capacity=1, used=None, kinds=("website",)):
    return _assign_row(
        ads_date=DAY,
        country=country,
        branch_key="Saigon",
        kinds=list(kinds),
        revenue=revenue,
        capacity=capacity,
        res_by_key=res_by_key,
        used=used if used is not None else set(),
    )


def _assign(res_by_key, **kw):
    """Tier-2 helper: returns just the chosen reservations list."""
    return _assign_full(res_by_key, **kw)[0]


class TestCountryRank:
    def test_exact_iso_is_rank_0(self):
        assert _country_rank("VN", _res("VN")) == 0

    def test_uk_gb_reconciled_to_rank_0(self):
        assert _country_rank("UK", _res("GB")) == 0

    def test_null_country_is_rank_1(self):
        assert _country_rank("VN", _res(None)) == 1

    def test_different_nationality_is_rank_2(self):
        assert _country_rank("VN", _res("US")) == 2


class TestAssignRow:
    def test_capacity_caps_number_assigned(self):
        pool = _pool(same_day=[_booking(1000, f"R{i}") for i in range(5)])
        chosen = _assign(pool, capacity=2)
        assert len(chosen) == 2

    def test_no_candidates_returns_empty(self):
        assert _assign(_pool(), capacity=3) == []

    def test_prefers_same_country(self):
        cross = _booking(1000, "CROSS", country_iso="US")
        same = _booking(1000, "SAME", country_iso="VN")
        chosen = _assign(_pool(same_day=[cross, same]), country="VN", capacity=1)
        assert [r.reservation_number for r in chosen] == ["SAME"]

    def test_prefers_same_day_over_neighbor(self):
        # Same country tier + same value → only the date offset decides.
        same_day = _booking(1000, "SAMEDAY")
        prev = _booking(1000, "PREV")
        chosen = _assign(_pool(same_day=[same_day], prev_day=[prev]), capacity=1)
        assert [r.reservation_number for r in chosen] == ["SAMEDAY"]

    def test_cross_country_still_matches_when_no_same_country(self):
        cross = _booking(1000, "CROSS", country_iso="US")
        chosen = _assign(_pool(same_day=[cross]), country="VN", capacity=1)
        assert [r.reservation_number for r in chosen] == ["CROSS"]

    def test_value_proximity_breaks_ties(self):
        # revenue 2000 / capacity 2 → the 1000+990 pair both sums to ~2000
        # (tier-1 confirm) and is the closest to per_booking=1000.
        bookings = [_booking(1500, "HI"), _booking(1000, "ON"), _booking(990, "NEAR")]
        chosen = _assign(_pool(same_day=bookings), revenue=2000.0, capacity=2)
        assert sorted(r.reservation_number for r in chosen) == ["NEAR", "ON"]

    def test_multiple_kinds_pool_together(self):
        # A Google row is handed both pools, so it can claim an offline booking.
        web = _booking(1000, "WEB")
        off = _booking(1000, "OFF")
        pool = {(DAY, "Saigon", "website"): [web], (DAY, "Saigon", "offline"): [off]}
        chosen = _assign(pool, capacity=2, kinds=("website", "offline"))
        assert sorted(r.reservation_number for r in chosen) == ["OFF", "WEB"]

    def test_google_prefers_website_over_offline(self):
        # ~90% of bookings come from the website, so a Google row must exhaust
        # its website candidates before falling back to offline/OTA ones — even
        # when an offline booking is an equally good same-day/same-value match.
        web = _booking(1000, "WEB")
        off = _booking(1000, "OFF")
        pool = {(DAY, "Saigon", "website"): [web], (DAY, "Saigon", "offline"): [off]}
        chosen = _assign(pool, capacity=1, kinds=("website", "offline"))
        assert [r.reservation_number for r in chosen] == ["WEB"]

    def test_google_falls_back_to_offline_when_no_website(self):
        off = _booking(1000, "OFF")
        pool = {(DAY, "Saigon", "offline"): [off]}
        chosen = _assign(pool, capacity=1, kinds=("website", "offline"))
        assert [r.reservation_number for r in chosen] == ["OFF"]

    def test_single_kind_ignores_other_pool(self):
        # A Meta website row only sees website reservations.
        web = _booking(1000, "WEB")
        off = _booking(1000, "OFF")
        pool = {(DAY, "Saigon", "website"): [web], (DAY, "Saigon", "offline"): [off]}
        chosen = _assign(pool, capacity=2, kinds=("website",))
        assert [r.reservation_number for r in chosen] == ["WEB"]

    def test_used_set_prevents_double_assignment(self):
        r1 = _booking(1000, "R1")
        used = {"R1"}
        chosen = _assign(_pool(same_day=[r1]), capacity=1, used=used)
        assert chosen == []

    def test_assignment_records_into_used(self):
        r1 = _booking(1000, "R1")
        used: set = set()
        _assign(_pool(same_day=[r1]), capacity=1, used=used)
        assert "R1" in used


class TestConfidenceTier:
    def test_single_booking_confirms_when_value_matches(self):
        r = _booking(1000, "R1")
        chosen, conf = _assign_full(_pool(same_day=[r]), revenue=1000.0, capacity=1)
        assert [x.reservation_number for x in chosen] == ["R1"]
        assert conf == CONFIDENCE_CONFIRMED

    def test_confirmed_subset_corrects_fractional_overcount(self):
        # Capacity says 5, but two bookings sum to the revenue → confirm just 2.
        bookings = [_booking(1000, "A"), _booking(1000, "B"), _booking(9000, "C")]
        chosen, conf = _assign_full(_pool(same_day=bookings), revenue=2000.0, capacity=5)
        assert sorted(x.reservation_number for x in chosen) == ["A", "B"]
        assert conf == CONFIDENCE_CONFIRMED

    def test_inferred_when_no_subset_sums_to_revenue(self):
        bookings = [_booking(1000, "A"), _booking(1000, "B")]
        chosen, conf = _assign_full(_pool(same_day=bookings), revenue=10_000_000.0, capacity=2)
        assert len(chosen) == 2
        assert conf == CONFIDENCE_INFERRED

    def test_five_percent_tolerance(self):
        # 1040 is 4% off 1000 → within ±5%, confirmed.
        r = _booking(1040, "R1")
        _, conf = _assign_full(_pool(same_day=[r]), revenue=1000.0, capacity=1)
        assert conf == CONFIDENCE_CONFIRMED


class TestFindValueSubset:
    def test_returns_single_within_tolerance(self):
        subset = _find_value_subset([_booking(1010, "R1")], 1000.0, 3)
        assert subset is not None and [r.reservation_number for r in subset] == ["R1"]

    def test_prefers_smaller_size(self):
        # A single 1000 confirms before any pair is tried.
        cands = [_booking(1000, "SOLO"), _booking(500, "A"), _booking(500, "B")]
        subset = _find_value_subset(cands, 1000.0, 3)
        assert [r.reservation_number for r in subset] == ["SOLO"]

    def test_finds_pair_when_no_single(self):
        cands = [_booking(700, "A"), _booking(300, "B")]
        subset = _find_value_subset(cands, 1000.0, 3)
        assert subset is not None and sorted(r.reservation_number for r in subset) == ["A", "B"]

    def test_none_when_no_subset_sums(self):
        cands = [_booking(700, "A"), _booking(800, "B")]
        assert _find_value_subset(cands, 5000.0, 3) is None


class TestAmountTolerance:
    """amount_tolerance survives for the diagnose endpoint's value-delta hint."""

    def test_pct_window_with_floor(self):
        assert amount_tolerance(2700) == 54.0          # 2%
        assert amount_tolerance(10) == 0.5             # floor wins for tiny values


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
        method = _classify_match_method([_res("GB")], "UK")
        assert method == METHOD_EXACT

    def test_all_null_reservations_classified_null(self):
        method = _classify_match_method([_res(None), _res(None)], "VN")
        assert method == METHOD_NULL

    def test_mixed_exact_and_null(self):
        method = _classify_match_method([_res("VN"), _res(None)], "VN")
        assert method == METHOD_MIXED

    def test_cross_country_when_nationality_differs(self):
        method = _classify_match_method([_res("TW")], "HK")
        assert method == METHOD_CROSS

    def test_cross_country_dominates_mixed(self):
        method = _classify_match_method([_res("HK"), _res("US"), _res(None)], "HK")
        assert method == METHOD_CROSS
