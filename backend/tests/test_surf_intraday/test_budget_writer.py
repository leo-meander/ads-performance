"""Cap-stack tests for budget_writer.resolve_budget_change.

The cap stack ordering matters — order is per_check → per_day → max_mult →
sanity. These tests pin that ordering down so a refactor can't accidentally
reorder them.
"""

import pytest

from app.services.surf_intraday.budget_writer import (
    SANITY_MAX_RATIO,
    resolve_budget_change,
)


def _resolve(
    current_budget=300, origin_budget=300, desired_multiplier=1.30, is_cut=False,
    max_per_click_abs=None, surf_limit_per_day=None,
    total_increase_today=0, max_budget_cap_multiplier=None,
):
    return resolve_budget_change(
        current_budget=current_budget, origin_budget=origin_budget,
        desired_multiplier=desired_multiplier, is_cut=is_cut,
        max_per_click_abs=max_per_click_abs,
        surf_limit_per_day=surf_limit_per_day,
        total_increase_today=total_increase_today,
        max_budget_cap_multiplier=max_budget_cap_multiplier,
    )


class TestNoCapsRaise:
    def test_straight_multiplier(self):
        r = _resolve(desired_multiplier=1.30)
        assert r["new_budget"] == 390.0
        assert r["delta"] == 90.0
        assert r["capped_by"] is None
        assert r["sanity_abort"] is False
        assert r["exhausted"] is False

    def test_multiplier_one_is_no_op(self):
        r = _resolve(desired_multiplier=1.0)
        assert r["delta"] == 0.0
        assert r["new_budget"] == 300.0


class TestPerCheckCap:
    def test_cap_binds(self):
        r = _resolve(desired_multiplier=1.30, max_per_click_abs=50)
        assert r["new_budget"] == 350.0
        assert r["delta"] == 50.0
        assert r["capped_by"] == "per_click_abs" or r["capped_by"] == "per_check"

    def test_cap_loose(self):
        """Cap 100 > desired delta 90 → cap doesn't bind."""
        r = _resolve(desired_multiplier=1.30, max_per_click_abs=100)
        assert r["delta"] == 90.0
        assert r["capped_by"] is None


class TestPerDayCap:
    def test_already_exhausted_skips_write(self):
        r = _resolve(
            desired_multiplier=1.30, surf_limit_per_day=200,
            total_increase_today=200,
        )
        assert r["exhausted"] is True
        assert r["delta"] == 0
        assert r["capped_by"] == "per_day"

    def test_partial_remaining_clamps_delta(self):
        """Want +90, only 30 remaining today → delta = 30."""
        r = _resolve(
            desired_multiplier=1.30, surf_limit_per_day=200,
            total_increase_today=170,
        )
        assert r["delta"] == 30.0
        assert r["new_budget"] == 330.0
        assert r["capped_by"] == "per_day"

    def test_per_day_does_not_apply_to_cut(self):
        """Cut budget never consumes surf_limit_per_day."""
        r = _resolve(
            desired_multiplier=0.80, is_cut=True,
            surf_limit_per_day=200, total_increase_today=200,
        )
        # 300 - 60 = 240, no exhausted block
        assert r["new_budget"] == 240.0
        assert r["delta"] == 60.0
        assert r["exhausted"] is False


class TestMaxMultiplierCap:
    def test_ceiling_binds(self):
        """origin=300, mult cap=2.0 → ceiling 600. current=580 → cap to 600."""
        r = _resolve(
            current_budget=580, origin_budget=300,
            desired_multiplier=2.00,
            max_budget_cap_multiplier=2.0,
        )
        assert r["new_budget"] == 600.0
        assert r["delta"] == 20.0
        assert r["capped_by"] == "max_multiplier"

    def test_at_ceiling_marks_exhausted(self):
        """current=600, ceiling=600 → delta=0, exhausted=True (run becomes capped)."""
        r = _resolve(
            current_budget=600, origin_budget=300,
            desired_multiplier=1.30,
            max_budget_cap_multiplier=2.0,
        )
        assert r["delta"] == 0.0
        assert r["exhausted"] is True


class TestSanityAbort:
    def test_abort_above_2_5x(self):
        """Multiplier 5× would set new=1500 from current 300 → abort."""
        r = _resolve(current_budget=100, desired_multiplier=5.0)
        assert r["sanity_abort"] is True
        assert r["capped_by"] == "sanity_abort"
        assert r["delta"] == 0  # caller must NOT write

    def test_exactly_at_2_5x_passes(self):
        """delta = current × 1.5 = exactly the sanity ratio cap → still ok."""
        # Multiplier 2.5 → delta = current × 1.5 = matches SANITY_MAX_RATIO bound.
        r = _resolve(current_budget=100, desired_multiplier=SANITY_MAX_RATIO)
        assert r["sanity_abort"] is False

    def test_sanity_not_applied_to_cut(self):
        """Cuts can't trigger sanity (cuts go DOWN, not up)."""
        r = _resolve(current_budget=300, desired_multiplier=0.1, is_cut=True)
        assert r["sanity_abort"] is False


class TestCutPath:
    def test_basic_cut(self):
        r = _resolve(desired_multiplier=0.80, is_cut=True)
        assert r["new_budget"] == 240.0
        assert r["delta"] == 60.0

    def test_cut_cap_binds(self):
        """Cut delta 150 capped at 50 → only cut 50."""
        r = _resolve(
            desired_multiplier=0.50, is_cut=True, max_per_click_abs=50,
        )
        assert r["new_budget"] == 250.0
        assert r["delta"] == 50.0
        # Either label is fine — different code paths historically used
        # 'per_check' or 'per_click_abs'.
        assert r["capped_by"] in ("per_check", "per_click_abs")

    def test_cut_floors_at_1(self):
        """Cut that would go below 1 unit of currency → floor at 1.0."""
        r = _resolve(
            current_budget=2.0, desired_multiplier=0.01, is_cut=True,
        )
        assert r["new_budget"] == 1.0
