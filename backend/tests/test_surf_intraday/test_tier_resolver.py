"""Pure-function tests for tier_resolver.

No DB / no Meta mocks needed — these are math on inputs.
"""

import pytest

from app.services.surf_intraday.tier_resolver import (
    compute_spend_thresholds,
    next_threshold_to_cross,
    resolve_tier,
)


TIERS = [
    {"roas_min": 1.74, "roas_max": 2.03, "multiplier": 1.30},
    {"roas_min": 2.03, "roas_max": 2.61, "multiplier": 1.50},
    {"roas_min": 2.61, "roas_max": None, "multiplier": 2.00},
]


def _resolve(roas, last=None, dc=True):
    return resolve_tier(
        current_roas=roas, last_roas=last, tiers=TIERS,
        double_check_enabled=dc, double_check_drop_pct=0.20,
        double_check_cut_pct=0.80,
    )


class TestTierResolver:
    def test_below_lowest_tier_is_no_action(self):
        d = _resolve(roas=1.5)
        assert d["tier_label"] == "no_action"
        assert d["multiplier"] == 1.0

    def test_tier_1_match(self):
        d = _resolve(roas=1.9)
        assert d["tier_label"] == "tier_1"
        assert d["multiplier"] == 1.30
        assert d["cut"] is False

    def test_boundary_belongs_to_upper_band(self):
        """ROAS exactly at 2.03 → tier_2 (>= min, < max semantics)."""
        d = _resolve(roas=2.03)
        assert d["tier_label"] == "tier_2"

    def test_top_tier_unbounded(self):
        d = _resolve(roas=10.0)
        assert d["tier_label"] == "tier_3"
        assert d["multiplier"] == 2.00

    def test_zero_roas_no_action(self):
        d = _resolve(roas=0)
        assert d["tier_label"] == "no_action"

    def test_none_roas_no_action(self):
        d = _resolve(roas=None)
        assert d["tier_label"] == "no_action"


class TestDoubleCheck:
    def test_drop_at_threshold_triggers_cut(self):
        """20% drop exactly meets threshold → cut."""
        d = _resolve(roas=2.40, last=3.0)  # drop = 0.20
        assert d["tier_label"] == "double_check_cut"
        assert d["cut"] is True
        assert d["multiplier"] == 0.80

    def test_drop_above_threshold_triggers_cut(self):
        d = _resolve(roas=2.0, last=3.0)  # drop = 0.333
        assert d["tier_label"] == "double_check_cut"

    def test_drop_below_threshold_does_not_trigger(self):
        d = _resolve(roas=2.5, last=2.6)  # drop = 0.0385
        assert d["tier_label"] != "double_check_cut"
        assert d["tier_label"] == "tier_2"

    def test_no_last_roas_skips_double_check(self):
        """First check of the day has no prior → skip Double Check entirely."""
        d = _resolve(roas=1.0, last=None)
        # ROAS 1.0 < lowest tier → no_action (not double_check_cut)
        assert d["tier_label"] == "no_action"

    def test_double_check_disabled(self):
        d = resolve_tier(
            current_roas=2.0, last_roas=3.0, tiers=TIERS,
            double_check_enabled=False, double_check_drop_pct=0.20,
            double_check_cut_pct=0.80,
        )
        # ROAS 2.0 → tier_1 (not cut)
        assert d["tier_label"] == "tier_1"


class TestSpendThresholds:
    def test_threshold_computation(self):
        assert compute_spend_thresholds(300, [0.30, 0.50, 0.85]) == [90.0, 150.0, 255.0]

    def test_thresholds_are_sorted(self):
        # Even if pct list is unsorted, output is sorted.
        assert compute_spend_thresholds(300, [0.85, 0.30, 0.50]) == [90.0, 150.0, 255.0]

    def test_zero_origin(self):
        assert compute_spend_thresholds(0, [0.3, 0.5]) == [0.0, 0.0]


class TestIdempotency:
    """next_threshold_to_cross is the engine's idempotency primitive."""

    THRESHOLDS = [90.0, 150.0, 210.0]

    def test_below_lowest_returns_none(self):
        assert next_threshold_to_cross(50.0, None, self.THRESHOLDS) is None

    def test_first_crossing_returns_threshold(self):
        assert next_threshold_to_cross(100.0, None, self.THRESHOLDS) == 90.0

    def test_re_query_at_same_spend_returns_none(self):
        """Once we acted on 90, querying again with spend in (90, 150) → None."""
        assert next_threshold_to_cross(120.0, 90.0, self.THRESHOLDS) is None

    def test_crosses_next_threshold(self):
        assert next_threshold_to_cross(160.0, 90.0, self.THRESHOLDS) == 150.0

    def test_skip_through_when_spend_jumps(self):
        """Spend jumped past 2 thresholds → return the highest crossed.
        Engine acts on that one and skips the middle (operator-friendly:
        avoids stale tier evaluation on old spend)."""
        assert next_threshold_to_cross(220.0, None, self.THRESHOLDS) == 210.0
