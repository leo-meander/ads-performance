"""Apply the SURF budget change with the cap stack.

The cap stack (ORDER MATTERS — money safety):

  1. per_check         — `ad_accounts.max_raise_per_click_abs` /
                          max_cut_per_click_abs. Hard ceiling per single tick.
                          Reused from the manual /action-needed feature so
                          one setting governs both surfaces.

  2. per_day           — `tactic.config.surf_limit_per_day` vs the
                          run.total_increase_today running tally. When the
                          remaining budget for today is 0, the engine flips
                          the run status to 'capped' and skips future ticks.

  3. max_multiplier    — `tactic.config.max_budget_cap_multiplier` vs the
                          run.origin_budget anchor. Caps the total daily
                          inflation — even if per_check and per_day were
                          permissive, total daily budget can't exceed
                          origin × cap_multiplier.

  4. sanity_abort      — Hard 2.5× current_budget guard. Catches logic bugs
                          (e.g. a buggy tier band sending multiplier=10).
                          If hit, ABORT without writing — the engine logs an
                          error checkpoint and the operator gets an alert.

The function below either calls Meta's budget API or, if dry_run=True,
computes everything and skips the Meta call. The returned dict tells the
engine exactly what happened so a checkpoint row can be written.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.surf import (
    CAPPED_BY_MAX_MULTIPLIER,
    CAPPED_BY_PER_CHECK,
    CAPPED_BY_PER_DAY,
    CAPPED_BY_SANITY,
)
from app.services.meta_actions import update_campaign_budget

logger = logging.getLogger(__name__)


# Sanity hard guard. Any single-tick raise above 2.5× current_budget is
# treated as a bug, not an intent. Catches: bad config (multiplier=10 typo),
# tier-resolver edge cases, accidental override. Keep this conservative.
SANITY_MAX_RATIO = 2.5


def resolve_budget_change(
    *,
    current_budget: float,
    origin_budget: float,
    desired_multiplier: float,
    is_cut: bool,
    max_per_click_abs: float | None,
    surf_limit_per_day: float | None,
    total_increase_today: float,
    max_budget_cap_multiplier: float | None,
) -> dict[str, Any]:
    """Compute (new_budget, applied_cap_reason) WITHOUT writing.

    Pure function — easy to unit test. The engine wraps this then calls Meta.

    Returns:
      {
        "new_budget":     float,          # what to send to Meta
        "delta":          float,          # absolute change (positive for raise,
                                          # positive for cut amount when is_cut)
        "capped_by":      str | None,     # one of CAPPED_BY_* constants
        "sanity_abort":   bool,           # True → caller must NOT write
        "exhausted":      bool,           # True → no remaining budget today
        "explain":        str,            # human-readable line for the audit
      }
    """
    # ---------- 1. Desired delta from the multiplier --------------------
    if is_cut:
        # `desired_multiplier` for cut is e.g. 0.80 = -20%. Delta magnitude:
        desired_delta = current_budget * (1 - desired_multiplier)
    else:
        # `desired_multiplier` for raise is e.g. 1.30 = +30%. Delta:
        desired_delta = current_budget * (desired_multiplier - 1)

    if desired_delta <= 0:
        return {
            "new_budget": current_budget,
            "delta": 0.0,
            "capped_by": None,
            "sanity_abort": False,
            "exhausted": False,
            "explain": f"multiplier {desired_multiplier} yields no change",
        }

    delta = desired_delta
    capped_by: str | None = None
    explain_parts: list[str] = [
        f"want {'cut' if is_cut else 'raise'} {desired_delta:.2f}"
    ]

    # ---------- 2. per_check cap ---------------------------------------
    if max_per_click_abs is not None and delta > float(max_per_click_abs):
        explain_parts.append(
            f"per_check cap {float(max_per_click_abs):.2f} binds"
        )
        delta = float(max_per_click_abs)
        capped_by = CAPPED_BY_PER_CHECK

    # ---------- 3. per_day cap (raise direction only) ------------------
    exhausted = False
    if not is_cut and surf_limit_per_day is not None:
        remaining = float(surf_limit_per_day) - float(total_increase_today)
        if remaining <= 0:
            exhausted = True
            explain_parts.append(
                f"per_day cap {float(surf_limit_per_day):.2f} exhausted "
                f"(used {float(total_increase_today):.2f})"
            )
            return {
                "new_budget": current_budget,
                "delta": 0.0,
                "capped_by": CAPPED_BY_PER_DAY,
                "sanity_abort": False,
                "exhausted": True,
                "explain": " · ".join(explain_parts),
            }
        if delta > remaining:
            explain_parts.append(
                f"per_day cap clamps to remaining {remaining:.2f}"
            )
            delta = remaining
            # Keep per_check tag if that already bound; otherwise per_day.
            if capped_by is None:
                capped_by = CAPPED_BY_PER_DAY

    # ---------- 4. max_multiplier vs origin (raise only) ---------------
    if not is_cut and max_budget_cap_multiplier is not None:
        ceiling = origin_budget * float(max_budget_cap_multiplier)
        projected = current_budget + delta
        if projected > ceiling:
            new_delta = max(ceiling - current_budget, 0)
            explain_parts.append(
                f"max_mult {float(max_budget_cap_multiplier):.2f}× "
                f"(ceiling {ceiling:.2f}) clamps to delta {new_delta:.2f}"
            )
            delta = new_delta
            if capped_by is None:
                capped_by = CAPPED_BY_MAX_MULTIPLIER
            if delta <= 0:
                # Already at the daily ceiling. Mark exhausted so the run
                # status flips to 'capped' and subsequent ticks skip.
                exhausted = True

    # ---------- 5. Sanity 2.5× guard (raise only) ----------------------
    if not is_cut:
        max_ratio_delta = current_budget * (SANITY_MAX_RATIO - 1)
        if delta > max_ratio_delta:
            return {
                "new_budget": current_budget,
                "delta": 0.0,
                "capped_by": CAPPED_BY_SANITY,
                "sanity_abort": True,
                "exhausted": False,
                "explain": (
                    f"SANITY ABORT — delta {delta:.2f} > current×{SANITY_MAX_RATIO} "
                    f"({max_ratio_delta:.2f}). Refusing to write to Meta."
                ),
            }

    # ---------- 6. Compute final budget --------------------------------
    if is_cut:
        new_budget = max(current_budget - delta, 1.0)
    else:
        new_budget = current_budget + delta

    explain_parts.append(
        f"{'-' if is_cut else '+'}{delta:.2f} → {new_budget:.2f}"
    )

    return {
        "new_budget": round(new_budget, 2),
        "delta": round(delta, 2),
        "capped_by": capped_by,
        "sanity_abort": False,
        "exhausted": exhausted,
        "explain": " · ".join(explain_parts),
    }


def write_to_meta(
    *,
    access_token: str,
    platform_campaign_id: str,
    current_daily_budget: float,
    new_daily_budget: float,
) -> tuple[bool, str | None]:
    """Call Meta update_campaign_budget with the tactic-managed force=True.

    Returns (success, error_message). Force=True is required because SURF
    multipliers can exceed Meta's built-in 25% guard — the cap stack above
    is our own safety mechanism.

    NEVER call this without going through resolve_budget_change first.
    """
    try:
        update_campaign_budget(
            access_token,
            platform_campaign_id,
            current_daily_budget=current_daily_budget,
            new_daily_budget=new_daily_budget,
            force=True,  # tactic-managed; our cap stack already enforced.
        )
        return True, None
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "surf budget write failed: campaign=%s %.2f→%.2f",
            platform_campaign_id, current_daily_budget, new_daily_budget,
        )
        return False, str(e)
