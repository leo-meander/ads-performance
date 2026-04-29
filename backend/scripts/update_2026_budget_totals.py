"""Update only the monthly Allocate (total_vnd) for 2026 — keep channel split.

Why this exists: the manager corrected the source spreadsheet after the
first import. Re-running `import_2026_budget.py` would also reset every
month back to the default 100% Meta split, undoing the per-month channel
percentages they've been entering via /budget Channel Splits.

This script reads the existing BudgetMonthlySplit row for each
(branch, 2026, month), keeps its current channel_pct, and only updates
total_vnd to the new value. The cascade in upsert_monthly_split then
re-derives the per-channel BudgetPlan amounts (notes are preserved by
budget_service:387).

Usage:
    cd backend && python -m scripts.update_2026_budget_totals
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.budget import BudgetMonthlySplit
from app.services.budget_service import upsert_monthly_split


YEAR = 2026

# CORRECTED monthly totals in VND, indexed by month (1-12).
# Source: user spreadsheet "ADS BUDGET" screenshot (revised), 2026.
BUDGETS_VND: dict[str, list[int]] = {
    "Taipei": [
        33_450_742, 23_893_387, 38_229_419, 50_176_113, 50_176_113, 43_008_097,
        33_450_742, 33_450_742, 28_672_064, 35_840_080, 50_176_113, 57_344_129,
    ],
    "Oani": [
        59_606_225, 37_253_890, 52_155_446, 78_233_170, 33_450_742, 67_057_003,
        52_155_446, 52_155_446, 44_704_668, 67_057_003, 67_057_003, 89_409_337,
    ],
    "Osaka": [
        31_513_625, 31_513_625, 42_018_167, 55_148_845, 33_450_742, 47_270_438,
        31_513_625, 36_765_896, 36_765_896, 55_148_845, 55_148_845, 63_027_251,
    ],
    "Saigon": [
        20_140_838, 14_386_313, 23_018_100, 34_527_150, 33_450_742, 21_579_469,
        17_263_575, 20_140_838, 20_140_838, 25_895_363, 25_895_363, 34_527_150,
    ],
    "1948": [
        27_423_670, 19_588_336, 31_341_337, 41_135_505, 33_450_742, 35_259_005,
        23_506_003, 27_423_670, 27_423_670, 35_259_005, 35_259_005, 47_012_006,
    ],
}

# Fallback when no existing split row is found — defaults to 100% Meta so
# channels still get a plan, matching the initial import behaviour.
FALLBACK_CHANNEL_PCT = {"meta": 100.0, "google": 0.0, "tiktok": 0.0}


def main() -> None:
    db = SessionLocal()
    updated = 0
    new_rows = 0
    try:
        for branch, monthly in BUDGETS_VND.items():
            assert len(monthly) == 12, f"{branch} must have 12 months"
            for m_idx, total_vnd in enumerate(monthly, start=1):
                existing = (
                    db.query(BudgetMonthlySplit)
                    .filter(
                        BudgetMonthlySplit.branch == branch,
                        BudgetMonthlySplit.year == YEAR,
                        BudgetMonthlySplit.month == m_idx,
                    )
                    .first()
                )
                if existing:
                    channel_pct = dict(existing.channel_pct or {})
                    tag = "UPDATE"
                    updated += 1
                else:
                    channel_pct = dict(FALLBACK_CHANNEL_PCT)
                    tag = " NEW  "
                    new_rows += 1

                upsert_monthly_split(
                    db,
                    branch=branch,
                    year=YEAR,
                    month=m_idx,
                    total_vnd=float(total_vnd),
                    channel_pct=channel_pct,
                    overflow_note=None,  # not used anymore
                    created_by="update_2026_budget_totals.py",
                )
                pct_str = ", ".join(f"{k}={v:g}%" for k, v in channel_pct.items())
                print(f"  [{tag}] {branch:7} {YEAR}-{m_idx:02d}: {total_vnd:>13,} VND  ({pct_str})")
        db.commit()
        print(f"\nDone. {updated} updated (kept channel_pct), {new_rows} created (default 100% Meta).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
