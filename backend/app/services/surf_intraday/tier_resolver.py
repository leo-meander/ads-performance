"""ROAS → tier multiplier resolver (pure functions, no DB).

Two paths, evaluated in this order:

  1. Double Check  — if the previous checkpoint had a ROAS reading and
                     today's ROAS dropped by >= `double_check_drop_pct`,
                     return the CUT multiplier instead of a boost.

  2. Tier bands    — sorted list of {roas_min, roas_max, multiplier}. The
                     first band whose [min, max) contains current ROAS wins.
                     roas_max=None means "no upper bound" (top tier).

If neither path matches → NO_ACTION (1.0 multiplier, no Meta call).

The whole module is intentionally testable as pure functions. The engine
hands in current values; resolver returns a decision dict. No SQLAlchemy.
"""

from __future__ import annotations

from typing import Any

from app.models.surf import DOUBLE_CHECK_CUT, NO_ACTION, TIER_1, TIER_2, TIER_3


# Decision returned to the engine. `multiplier`: the factor to apply to
# current_budget. `cut`: True → engine subtracts the delta instead of adding.
# `reason`: short human-readable string for the checkpoint audit row.
Decision = dict[str, Any]


def _no_action(reason: str = "ROAS outside any tier band") -> Decision:
    return {
        "tier_label": NO_ACTION,
        "multiplier": 1.0,
        "cut": False,
        "reason": reason,
    }


def _double_check_cut(
    current_roas: float, last_roas: float, drop_pct: float, cut_pct: float,
) -> Decision:
    return {
        "tier_label": DOUBLE_CHECK_CUT,
        "multiplier": cut_pct,
        "cut": True,
        "reason": (
            f"ROAS {current_roas:.4f} dropped {((last_roas - current_roas) / last_roas * 100):.1f}% "
            f"vs last check {last_roas:.4f} (threshold {drop_pct*100:.0f}%)"
        ),
    }


def _tier_label_for_index(idx: int) -> str:
    """Map a tier band's position in the tactic config to the DB enum.

    The DB CHECK constraint allows tier_1, tier_2, tier_3. Tactics with more
    than 3 bands collapse extras into tier_3 — the engine only needs the
    audit label, not the count.
    """
    return [TIER_1, TIER_2, TIER_3][min(idx, 2)]


def resolve_tier(
    *,
    current_roas: float,
    last_roas: float | None,
    tiers: list[dict],
    double_check_enabled: bool,
    double_check_drop_pct: float,
    double_check_cut_pct: float,
) -> Decision:
    """Pick the SURF action for this tick.

    Args:
        current_roas: ROAS computed from today's Meta intraday spend + revenue.
                      None or 0 -> no_action.
        last_roas: ROAS reading at the previous checkpoint. None on the
                   first check of the day (Double Check skipped then).
        tiers: list of {"roas_min": float, "roas_max": float|None,
                        "multiplier": float}. Order matters — first match wins.
        double_check_enabled: tactic.config.double_check_enabled
        double_check_drop_pct: e.g. 0.20 means cut if ROAS fell ≥ 20% since
                               last check.
        double_check_cut_pct: how much to cut the budget by, as a multiplier
                              (0.80 = -20%).

    Returns: Decision dict — see Decision type above.
    """
    if current_roas is None or current_roas <= 0:
        return _no_action(reason="ROAS unavailable or zero")

    # 1. Double Check — guard against momentum reversal. Only fires if we
    #    have a previous reading to compare against (skipped on the first
    #    check of each day).
    if double_check_enabled and last_roas is not None and last_roas > 0:
        # Fractional drop. Positive number = ROAS got worse.
        drop = (last_roas - current_roas) / last_roas
        if drop >= double_check_drop_pct:
            return _double_check_cut(
                current_roas=current_roas,
                last_roas=last_roas,
                drop_pct=double_check_drop_pct,
                cut_pct=double_check_cut_pct,
            )

    # 2. Tier bands — find first band containing current_roas.
    for idx, tier in enumerate(tiers):
        roas_min = float(tier["roas_min"])
        roas_max = tier.get("roas_max")  # may be None = unbounded
        if current_roas < roas_min:
            continue
        if roas_max is not None and current_roas >= float(roas_max):
            continue
        # Match.
        multiplier = float(tier["multiplier"])
        roas_max_str = f"{float(roas_max):.2f}x" if roas_max is not None else "∞"
        return {
            "tier_label": _tier_label_for_index(idx),
            "multiplier": multiplier,
            "cut": False,
            "reason": (
                f"ROAS {current_roas:.4f} in band [{roas_min:.2f}x, {roas_max_str}) "
                f"→ ×{multiplier:.2f}"
            ),
        }

    return _no_action(
        reason=f"ROAS {current_roas:.4f} below lowest tier "
               f"({float(tiers[0]['roas_min']):.2f}x)" if tiers else "no tiers configured",
    )


def compute_spend_thresholds(
    origin_budget: float, thresholds_pct: list[float],
) -> list[float]:
    """Derive absolute spend thresholds from the origin budget.

    e.g. origin=300, pcts=[0.30, 0.50, 0.85] → [90, 150, 255]

    The engine then asks "which is the largest threshold ≤ current_spend that
    we haven't acted on yet?" to decide whether the tick is actionable.
    """
    return sorted(round(origin_budget * float(p), 2) for p in thresholds_pct)


def next_threshold_to_cross(
    current_spend: float,
    last_threshold_hit: float | None,
    thresholds: list[float],
) -> float | None:
    """Find the largest threshold that current_spend has reached but the run
    has NOT yet acted on. Returns None if nothing new to act on.

    Idempotency guarantee: if last_threshold_hit was 90 and current_spend is
    still in (90, 150), we return None → no action. Only when spend crosses
    150 do we return 150.
    """
    eligible = [t for t in thresholds if t <= current_spend]
    if not eligible:
        return None
    highest_eligible = max(eligible)
    if last_threshold_hit is not None and highest_eligible <= last_threshold_hit:
        return None
    return highest_eligible
