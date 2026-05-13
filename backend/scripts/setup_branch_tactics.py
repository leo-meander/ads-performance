"""Set up per-branch Meta Ads automation tactics for MEANDER Group.

One-time bootstrap script: creates a calibrated suite of tactics for each of
the 5 hotel branches (excludes Bread Espresso restaurant). All tactics are
created as `is_active=False` so the user can review thresholds on /tactics
before flipping each on.

Thresholds are calibrated against the actual 30-day spend/ROAS profile of
each ad account (see comments inline) and the playbook's guidance:
  - Cold Meta ads need a fair-chance window before judging (≥3 days)
  - Direct booking saves 15-25% OTA commission → ROAS ≥ 2 is breakeven-ish,
    ROAS ≥ 4-5 is a clear winner worth scaling
  - Different ICPs / ADRs per branch → thresholds calibrated per branch

Idempotent: if a tactic with the same (account_id, preset_type, name) prefix
already exists, it's skipped. Re-runnable safely.

Usage:
    cd backend && venv/Scripts/python -m scripts.setup_branch_tactics
"""

from dataclasses import dataclass
from typing import Any

from app.database import SessionLocal
from app.models import AdAccount, Tactic
from app.services.tactic_service import create_tactic_from_preset

# Skip restaurants — Meta Ads tactics are only for hotel direct-booking flow.
_SKIP_ACCOUNT_NAMES = ("Bread", "Espresso")


@dataclass
class TacticSpec:
    preset_type: str
    name_suffix: str  # appended to "[Auto] <Branch> · "
    config: dict[str, Any]
    is_active: bool = False  # User flips on after review.


# Per-branch calibration. Spend thresholds in the account's native currency
# (VND for Saigon, TWD for the Taiwan branches, JPY for Osaka). Numbers
# anchored to ~3 days of typical per-entity spend so conditions can actually
# fire on real traffic.
BRANCH_CONFIGS: dict[str, list[TacticSpec]] = {
    # ----------------------------------------------------------------------
    # Meander Saigon (VND) — small per-ad spend, healthy ROAS (avg ~3.5)
    # 30d avg: 8,750 VND/day per ad, 26,000 VND/day per adset
    # ----------------------------------------------------------------------
    "Meander Saigon": [
        TacticSpec("stop_loss_ad", "Stop Loss Ad", {
            "roas_min": 1.5, "spend_min": 25000, "days": 3,
        }),
        TacticSpec("stop_loss_adset", "Stop Loss Ad Set", {
            "roas_min": 1.5, "spend_min": 75000, "days": 3,
        }),
        TacticSpec("surf_adset", "SURF — Scale Winners", {
            "roas_min": 5.0, "spend_min": 50000, "days": 3,
            "budget_multiplier": 1.25, "max_budget_cap_multiplier": 2.0,
        }),
        TacticSpec("revive_ad", "REVIVE Recovered Ads", {
            "roas_min": 4.0, "spend_min": 10000, "days": 3,
        }),
        TacticSpec("pause_today", "Pause Today (losing ads)", {
            "roas_min": 0.8, "spend_min": 15000,
        }),
    ],

    # ----------------------------------------------------------------------
    # Meander Taipei (TWD) — strongest performer (avg ROAS 5.23)
    # 30d avg: 31 TWD/day per ad, 107 TWD/day per adset
    # Tighten SURF threshold above the already-high baseline.
    # ----------------------------------------------------------------------
    "Meander Taipei": [
        TacticSpec("stop_loss_ad", "Stop Loss Ad", {
            "roas_min": 2.0, "spend_min": 90, "days": 3,
        }),
        TacticSpec("stop_loss_adset", "Stop Loss Ad Set", {
            "roas_min": 2.0, "spend_min": 300, "days": 3,
        }),
        TacticSpec("surf_adset", "SURF — Scale Winners", {
            "roas_min": 7.0, "spend_min": 200, "days": 3,
            "budget_multiplier": 1.25, "max_budget_cap_multiplier": 2.0,
        }),
        TacticSpec("scale_winning_adset", "Scale Winning Adset (+20%/day)", {
            "roas_min": 6.0, "spend_min": 200, "days": 3,
            "daily_step_pct": 0.20, "max_budget_cap_multiplier": 3.0,
        }),
        TacticSpec("revive_ad", "REVIVE Recovered Ads", {
            "roas_min": 5.0, "spend_min": 50, "days": 3,
        }),
        TacticSpec("pause_today", "Pause Today (losing ads)", {
            "roas_min": 1.0, "spend_min": 50,
        }),
    ],

    # ----------------------------------------------------------------------
    # Meander 1948 (TWD) — moderate (avg ROAS 2.09)
    # 30d avg: 56 TWD/day per ad, 140 TWD/day per adset
    # ----------------------------------------------------------------------
    "Meander 1948": [
        TacticSpec("stop_loss_ad", "Stop Loss Ad", {
            "roas_min": 1.5, "spend_min": 150, "days": 3,
        }),
        TacticSpec("stop_loss_adset", "Stop Loss Ad Set", {
            "roas_min": 1.5, "spend_min": 400, "days": 3,
        }),
        TacticSpec("surf_adset", "SURF — Scale Winners", {
            "roas_min": 4.0, "spend_min": 300, "days": 3,
            "budget_multiplier": 1.25, "max_budget_cap_multiplier": 2.0,
        }),
        TacticSpec("revive_ad", "REVIVE Recovered Ads", {
            "roas_min": 3.0, "spend_min": 100, "days": 3,
        }),
        TacticSpec("pause_today", "Pause Today (losing ads)", {
            "roas_min": 0.8, "spend_min": 100,
        }),
    ],

    # ----------------------------------------------------------------------
    # Meander Osaka (JPY) — weakest ROAS (avg 1.33) — aggressive stop loss
    # + sunsetting to wind down chronic underperformers
    # 30d avg: 233 JPY/day per ad, 552 JPY/day per adset
    # ----------------------------------------------------------------------
    "Meander Osaka": [
        TacticSpec("stop_loss_ad", "Stop Loss Ad (tight)", {
            "roas_min": 1.5, "spend_min": 700, "days": 3,
        }),
        TacticSpec("stop_loss_adset", "Stop Loss Ad Set (tight)", {
            "roas_min": 1.5, "spend_min": 1500, "days": 3,
        }),
        TacticSpec("surf_adset", "SURF — Scale Winners", {
            "roas_min": 3.0, "spend_min": 1500, "days": 3,
            "budget_multiplier": 1.25, "max_budget_cap_multiplier": 2.0,
        }),
        TacticSpec("revive_ad", "REVIVE Recovered Ads", {
            "roas_min": 2.5, "spend_min": 500, "days": 3,
        }),
        TacticSpec("pause_today", "Pause Today (losing ads)", {
            "roas_min": 0.7, "spend_min": 700,
        }),
        TacticSpec("sunsetting", "Sunsetting weak adsets", {
            "roas_min": 1.5, "spend_min": 1500, "days": 3,
            "step1_reduction_pct": 0.25, "step2_reduction_pct": 0.50,
        }),
    ],

    # ----------------------------------------------------------------------
    # Oani (Taipei) (TWD) — premium positioning, moderate ROAS (avg 2.07)
    # 30d avg: 223 TWD/day per ad, 817 TWD/day per adset (heaviest spender)
    # ----------------------------------------------------------------------
    "Oani (Taipei)": [
        TacticSpec("stop_loss_ad", "Stop Loss Ad", {
            "roas_min": 1.5, "spend_min": 600, "days": 3,
        }),
        TacticSpec("stop_loss_adset", "Stop Loss Ad Set", {
            "roas_min": 1.5, "spend_min": 2000, "days": 3,
        }),
        TacticSpec("surf_adset", "SURF — Scale Winners", {
            "roas_min": 3.5, "spend_min": 1500, "days": 3,
            "budget_multiplier": 1.25, "max_budget_cap_multiplier": 2.0,
        }),
        TacticSpec("revive_ad", "REVIVE Recovered Ads", {
            "roas_min": 3.0, "spend_min": 300, "days": 3,
        }),
        TacticSpec("pause_today", "Pause Today (losing ads)", {
            "roas_min": 1.0, "spend_min": 600,
        }),
    ],
}


def _name(branch: str, suffix: str) -> str:
    return f"[Auto] {branch} · {suffix}"


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
        skipped_no_account = 0
        per_branch: dict[str, list[str]] = {}

        for branch, specs in BRANCH_CONFIGS.items():
            account = next(
                (a for a in accounts if a.account_name == branch), None,
            )
            if not account:
                print(f"  [SKIP] {branch}: no active Meta ad account found")
                skipped_no_account += len(specs)
                continue
            if any(s in account.account_name for s in _SKIP_ACCOUNT_NAMES):
                continue

            per_branch[branch] = []
            for spec in specs:
                tactic_name = _name(branch, spec.name_suffix)
                # Idempotency: skip if a tactic with this name already exists.
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
                    per_branch[branch].append(f"  [exists] {spec.name_suffix}")
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
                if not spec.is_active:
                    t.is_active = False
                    # Cascade to rules too (toggle_tactic also flips linked rules
                    # but we want to set without going through that path so the
                    # transaction stays in our control).
                    from app.models.rule import AutomationRule
                    db.query(AutomationRule).filter(
                        AutomationRule.tactic_id == t.id,
                    ).update({"is_active": False}, synchronize_session=False)
                    db.commit()

                created += 1
                per_branch[branch].append(f"  [new]    {spec.name_suffix}")

        summary = {
            "created": created,
            "skipped_existing": skipped_existing,
            "skipped_no_account": skipped_no_account,
            "per_branch": per_branch,
        }
        return summary
    finally:
        db.close()


if __name__ == "__main__":
    print("Setting up MEANDER Meta Ads tactics suite (inactive by default)…")
    summary = setup()
    print()
    print(f"Created: {summary['created']}")
    print(f"Skipped (already exists): {summary['skipped_existing']}")
    print(f"Skipped (no account): {summary['skipped_no_account']}")
    print()
    for branch, lines in summary["per_branch"].items():
        print(branch)
        for line in lines:
            print(line)
    print()
    print("All tactics created as is_active=False. Review on /tactics and toggle on per branch.")
