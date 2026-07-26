"""Unit convention for creative-hypothesis primary metrics.

Storage is FRACTIONS: ad_combos.ctr / hook_rate / thruplay_rate and
creative_hypotheses.actual_ctr / actual_cvr are all clicks/impressions style
ratios (0.0155 = 1.55%).

Everything a human types or reads is PERCENT: the Win Threshold input in the
Hypotheses form, the 60-day benchmark autofill, and every value the API sends
to the Learning Dashboard (1.55 = 1.55%).

ROAS is neither — it stays a raw multiple (5.07 = 5.07x).

Convert with to_display_units() at the boundary so a threshold comparison never
puts a fraction next to a percent.
"""

RATE_METRICS = {
    "CTR",
    "CVR",
    "HOOK_RATE",
    "HOLD_RATE",
    "THUMB_STOP_RATE",
    "BOOKING_RATE",
    "ENGAGEMENT_RATE",
}


def norm_metric(metric: str | None) -> str:
    """'hook rate' / 'hook-rate' / 'Hook_Rate' -> 'HOOK_RATE'."""
    return (metric or "").upper().replace(" ", "_").replace("-", "_")


def metric_unit(metric: str | None) -> str:
    """Display unit for a metric: 'pct' | 'x' | 'num'."""
    m = norm_metric(metric)
    if m == "ROAS":
        return "x"
    if m in RATE_METRICS:
        return "pct"
    return "num"


def to_display_units(value: float | None, metric: str | None) -> float | None:
    """Stored fraction -> display units. Rates x100, ROAS untouched."""
    if value is None:
        return None
    return value * 100 if metric_unit(metric) == "pct" else value
