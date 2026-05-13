"""Set up per-branch × per-funnel Meta Ads automation tactics for MEANDER Group.

Bootstrap script. Creates a tactics suite for each of the 5 hotel branches
(skips Bread Espresso) segmented by funnel stage (TOF / MOF), with thresholds
that float dynamically with the branch's own 30-day percentile baseline.

Why dynamic thresholds:
- Hardcoded ROAS bars go stale as accounts evolve and ICPs shift season-to-season
- TOF (cold prospecting) and MOF (retargeting) have fundamentally different
  baseline ROAS profiles — one bar can't fit both
- Each branch should be evaluated relative to its own past, not a generic
  industry number

How it works at evaluation time:
- threshold_mode='dynamic' on the tactic → rule_engine resolves each condition's
  threshold from the Nth percentile of that branch's TOF/MOF entities over
  lookback_days, clamped to a safety_bound so the bar never lets ROAS=0.9 pass
  (stop loss) or ROAS=1.5 trigger scaling (surf)
- Diagnostics panel surfaces the effective threshold every run: "ROAS bar today
  = 2.83 (P25 of branch TOF ad sets over 30d = 2.83, bounded by safety=1.5)"

All tactics created as is_active=False — user toggles each on after reviewing
on /tactics.

Idempotent: skip-if-name-exists. Safe to re-run after tweaking baselines.

Usage:
    cd backend && venv/Scripts/python -m scripts.setup_branch_tactics
"""

from dataclasses import dataclass, field
from typing import Any

from app.database import SessionLocal
from app.models import AdAccount, Tactic
from app.services.tactic_service import create_tactic_from_preset

# Skip restaurants — Meta Ads tactics are only for hotel direct-booking flow.
_SKIP_ACCOUNT_NAMES = ("Bread", "Espresso")

# Branches to set up. Bread is excluded.
TARGET_BRANCHES = (
    "Meander Saigon",
    "Meander Taipei",
    "Meander 1948",
    "Meander Osaka",
    "Oani (Taipei)",
)

# Funnel stages to segment by — Campaign.funnel_stage values parsed from
# names at sync time ([TOF]/[MOF]/[BOF]).
FUNNEL_STAGES = ("TOF", "MOF")


@dataclass
class TacticSpec:
    preset_type: str
    name_suffix: str  # appended to "[Auto] <Branch> · <FUNNEL> · "
    config: dict[str, Any] = field(default_factory=dict)


# Spend safety bounds vary per currency — hardcoded as last-resort fallbacks
# when there isn't enough branch data for the percentile to mean anything.
# These are deliberately conservative: ~3 days of typical per-entity spend.
SPEND_SAFETY_BOUND_BY_CURRENCY: dict[str, dict[str, float]] = {
    # currency → {entity_level → spend floor for safety_bound}
    "VND": {"ad": 25_000, "ad_set": 75_000, "campaign": 200_000},
    "TWD": {"ad": 150, "ad_set": 400, "campaign": 1_000},
    "JPY": {"ad": 700, "ad_set": 1_500, "campaign": 4_000},
    "USD": {"ad": 5, "ad_set": 15, "campaign": 50},
    "EUR": {"ad": 5, "ad_set": 15, "campaign": 50},
}


def _build_specs(currency: str, funnel: str) -> list[TacticSpec]:
    """Return the per-funnel tactic suite for a given branch currency.

    Every tactic uses threshold_mode='dynamic' so the actual ROAS/spend bars
    re-compute each day from the branch's own funnel-segmented baseline.

    Spend conditions still need a hard minimum so the rule doesn't fire on
    ads that haven't had a fair-chance run; we use the per-currency safety
    bound as the static minimum and let percentile lift it on heavier accounts.
    """
    sb_ad = SPEND_SAFETY_BOUND_BY_CURRENCY.get(currency, {}).get("ad", 5)
    sb_adset = SPEND_SAFETY_BOUND_BY_CURRENCY.get(currency, {}).get("ad_set", 15)

    # ROAS safety bounds are currency-agnostic (ROAS is a ratio).
    # Tuned to the playbook's direct-booking economics:
    #   - ROAS ≥ 2 ≈ break-even when accounting for OTA commission savings
    #   - ROAS ≥ 4 = clear winner worth scaling
    # MOF (retargeting) typically delivers higher ROAS than TOF (cold), so we
    # tighten the surf bar and the stop-loss bar slightly on MOF.
    if funnel == "MOF":
        stop_loss_roas_floor = 1.5      # don't pause MOF unless ROAS truly weak
        surf_roas_floor = 4.0           # MOF winners must clear a higher bar
        revive_roas_floor = 3.0
        pause_today_roas_floor = 1.0
    else:  # TOF (default)
        stop_loss_roas_floor = 1.0      # cold can run thinner before pause
        surf_roas_floor = 3.0
        revive_roas_floor = 2.5
        pause_today_roas_floor = 0.8

    return [
        # STOP LOSS Ad-level: pause ads in the bottom quartile of branch ROAS
        # — but never pause one above the safety_bound (so a healthy account
        # doesn't murder its mid-pack ads just because P25 is high).
        TacticSpec("stop_loss_ad", "Stop Loss Ad", {
            "funnel_stage": funnel,
            "threshold_mode": "dynamic",
            "lookback_days": 30,
            "days": 3,
            "roas_percentile": 25,
            "roas_safety_bound": stop_loss_roas_floor,
            "spend_min": sb_ad,
        }),
        # STOP LOSS Ad Set: same idea, tighter spend floor.
        TacticSpec("stop_loss_adset", "Stop Loss Ad Set", {
            "funnel_stage": funnel,
            "threshold_mode": "dynamic",
            "lookback_days": 30,
            "days": 3,
            "roas_percentile": 25,
            "roas_safety_bound": stop_loss_roas_floor,
            "spend_min": sb_adset,
        }),
        # SURF Ad Set: scale entities in the top quartile, never scale below
        # the safety floor even if branch as a whole is doing badly.
        TacticSpec("surf_adset", "SURF Scale Winners", {
            "funnel_stage": funnel,
            "threshold_mode": "dynamic",
            "lookback_days": 30,
            "days": 3,
            "roas_percentile": 75,
            "roas_safety_bound": surf_roas_floor,
            "spend_min": sb_adset,
            "budget_multiplier": 1.25,
            "max_budget_cap_multiplier": 2.0,
        }),
        # REVIVE Ad: re-enable paused ads whose recent ROAS is in the top half.
        TacticSpec("revive_ad", "REVIVE Recovered Ads", {
            "funnel_stage": funnel,
            "threshold_mode": "dynamic",
            "lookback_days": 30,
            "days": 3,
            "roas_percentile": 60,
            "roas_safety_bound": revive_roas_floor,
            "spend_min": sb_ad,
        }),
        # PAUSE TODAY: lighter check on 1-day data — pause if today's ROAS
        # is in the very bottom of the branch's 1-day distribution.
        TacticSpec("pause_today", "Pause Today (losing ads)", {
            "funnel_stage": funnel,
            "threshold_mode": "dynamic",
            "lookback_days": 30,
            "roas_percentile": 15,
            "roas_safety_bound": pause_today_roas_floor,
            "spend_min": sb_ad,
        }),
    ]


def _name(branch: str, funnel: str, suffix: str) -> str:
    return f"[Auto] {branch} · {funnel} · {suffix}"


def setup() -> dict:
    db = SessionLocal()
    try:
        accounts = (
            db.query(AdAccount)
            .filter(AdAccount.platform == "meta", AdAccount.is_active.is_(True))
            .all()
        )

        created = 0
        skipped_existing = 0
        per_branch: dict[str, list[str]] = {}

        for branch in TARGET_BRANCHES:
            account = next(
                (a for a in accounts if a.account_name == branch), None,
            )
            if not account:
                print(f"  [SKIP] {branch}: no active Meta ad account found")
                continue
            if any(s in account.account_name for s in _SKIP_ACCOUNT_NAMES):
                continue

            per_branch[branch] = []
            for funnel in FUNNEL_STAGES:
                for spec in _build_specs(account.currency, funnel):
                    tactic_name = _name(branch, funnel, spec.name_suffix)
                    existing = (
                        db.query(Tactic)
                        .filter(
                            Tactic.account_id == account.id,
                            Tactic.name == tactic_name,
                        )
                        .first()
                    )
                    if existing:
                        skipped_existing += 1
                        per_branch[branch].append(f"  [exists] {funnel} · {spec.name_suffix}")
                        continue

                    t = create_tactic_from_preset(
                        db,
                        preset_type=spec.preset_type,
                        name=tactic_name,
                        platform="meta",
                        account_id=account.id,
                        config_overrides=spec.config,
                        created_by="setup_branch_tactics.py",
                    )
                    # Default to inactive — user reviews on /tactics before enabling.
                    t.is_active = False
                    from app.models.rule import AutomationRule
                    db.query(AutomationRule).filter(
                        AutomationRule.tactic_id == t.id,
                    ).update({"is_active": False}, synchronize_session=False)
                    db.commit()
                    created += 1
                    per_branch[branch].append(f"  [new]    {funnel} · {spec.name_suffix}")

        return {
            "created": created,
            "skipped_existing": skipped_existing,
            "per_branch": per_branch,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print("Setting up MEANDER per-funnel dynamic tactics suite (inactive by default)...")
    summary = setup()
    print()
    print(f"Created: {summary['created']}")
    print(f"Skipped (already exists): {summary['skipped_existing']}")
    print()
    for branch, lines in summary["per_branch"].items():
        print(branch)
        for line in lines:
            print(line)
    print()
    print("All tactics created as is_active=False. Review on /tactics and toggle on per branch.")
