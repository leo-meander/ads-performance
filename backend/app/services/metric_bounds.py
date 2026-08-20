"""Clamp derived ratio metrics to the limits of their metrics_cache columns.

Postgres raises `DataError: numeric field overflow` the moment a value exceeds
a NUMERIC(p, s) column, and that error aborts the ENTIRE transaction — not just
the offending row. During a sync that means one freak ad (a booking worth
28,000,000 VND attributed to an ad that spent 2,000 VND -> ROAS 14,040) takes
down the whole account's sync, and historically the whole account loop with it.

`ctr` already carried an inline cap for exactly this reason. These helpers
generalise it to every derived ratio we store, so a single outlier degrades to
a clamped value plus a warning instead of a silent multi-day data blackout.

Money columns (spend, revenue) are deliberately NOT clamped: they are reported
figures, and quietly capping them would corrupt the numbers the dashboard sums.
Ratios are recomputed from spend/revenue at read time anyway, so clamping them
costs nothing.
"""
import logging
import math

logger = logging.getLogger(__name__)

# metrics_cache column limits — keep in sync with app/models/metrics.py.
CTR_MAX = 99.999999          # NUMERIC(8, 6)
ROAS_MAX = 9999.9999         # NUMERIC(8, 4)
FREQUENCY_MAX = 9999.9999    # NUMERIC(8, 4)
MONEY_RATIO_MAX = 9999999999999.99  # NUMERIC(15, 2) — cpa, cpc


def clamp_metric(value, max_abs: float, *, field: str, context: str = "") -> float | None:
    """Return `value` bounded to ±max_abs, or None when it isn't a real number.

    NaN/Inf become None (the columns are nullable) — Postgres rejects both for
    NUMERIC, and they carry no information worth storing.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        logger.warning("Dropping non-finite %s%s: %r", field, f" ({context})" if context else "", value)
        return None
    if abs(v) <= max_abs:
        return v
    logger.warning(
        "Clamping %s%s: %s -> %s (column limit)",
        field, f" ({context})" if context else "", v, max_abs,
    )
    return max_abs if v > 0 else -max_abs


def clamp_ratio_fields(fields: dict, *, context: str = "") -> dict:
    """Clamp every derived-ratio key present in a metrics_cache field dict.

    Mutates and returns `fields` so callers can wrap their existing literal.
    """
    limits = {
        "ctr": CTR_MAX,
        "roas": ROAS_MAX,
        "frequency": FREQUENCY_MAX,
        "cpa": MONEY_RATIO_MAX,
        "cpc": MONEY_RATIO_MAX,
    }
    for field, max_abs in limits.items():
        if field in fields:
            fields[field] = clamp_metric(fields[field], max_abs, field=field, context=context)
    return fields
