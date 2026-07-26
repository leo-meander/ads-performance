"""Unit convention for hypothesis primary metrics.

Regression guard: combo rate columns are fractions, win_threshold is a percent.
Comparing them unscaled made every rate hypothesis lose against its own
benchmark (0.0155 vs 1.55 -> beat_pct ≈ -99%, verdict always 'refuted').
"""
from types import SimpleNamespace

import pytest

from app.services.hypothesis_sync_service import _extract_metric
from app.services.metric_units import metric_unit, norm_metric, to_display_units


class TestMetricUnits:
    def test_norm_metric_uppercases_and_normalizes_separators(self):
        assert norm_metric("hook rate") == "HOOK_RATE"
        assert norm_metric("hold-rate") == "HOLD_RATE"
        assert norm_metric(None) == ""

    def test_rates_are_percent_roas_is_multiple(self):
        assert metric_unit("CTR") == "pct"
        assert metric_unit("hook_rate") == "pct"
        assert metric_unit("hold_rate") == "pct"
        assert metric_unit("CVR") == "pct"
        assert metric_unit("roas") == "x"
        assert metric_unit("something_else") == "num"

    def test_to_display_units_scales_only_rates(self):
        assert to_display_units(0.0155, "CTR") == 1.55
        assert to_display_units(5.07, "ROAS") == 5.07
        assert to_display_units(None, "CTR") is None


def _combo(**kw):
    defaults = dict(
        ctr=None, roas=None, hook_rate=None, thruplay_rate=None,
        engagement_rate=None, conversions=None, clicks=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestExtractMetric:
    def test_ctr_fraction_becomes_percent(self):
        assert _extract_metric(_combo(ctr=0.0155), "CTR") == 1.55

    def test_hook_rate_fraction_becomes_percent(self):
        assert _extract_metric(_combo(hook_rate=0.0531), "hook_rate") == pytest.approx(5.31)

    def test_hold_rate_reads_thruplay_rate(self):
        assert _extract_metric(_combo(thruplay_rate=0.25), "hold_rate") == 25.0

    def test_thumb_stop_rate_reads_hook_rate(self):
        assert _extract_metric(_combo(hook_rate=0.02), "thumb_stop_rate") == 2.0

    def test_roas_stays_a_multiple(self):
        assert _extract_metric(_combo(roas=5.07), "ROAS") == 5.07

    def test_cvr_computed_from_conversions_over_clicks(self):
        assert _extract_metric(_combo(conversions=3, clicks=100), "CVR") == 3.0

    def test_unknown_metric_returns_none_instead_of_falling_back_to_roas(self):
        # A ROAS multiple judged against a hook-rate threshold is meaningless —
        # the caller must fall back to the combo WIN rate instead.
        assert _extract_metric(_combo(roas=5.07), "made_up_metric") is None

    def test_missing_data_returns_none(self):
        assert _extract_metric(_combo(), "CTR") is None
        assert _extract_metric(_combo(clicks=0, conversions=0), "CVR") is None
