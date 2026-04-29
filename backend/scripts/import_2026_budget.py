"""One-shot import of the 2026 yearly budget allocation (in VND) per branch.

Source: user-provided spreadsheet screenshot (Apr 2026). Values are total
monthly ads budget in VND; the script cascades each into:
  - 1 BudgetMonthlySplit row (branch, year=2026, month) — default 100% Meta
  - 1 BudgetPlan row (branch, channel='meta', month=YYYY-MM-01) with the
    amount converted to the branch's native currency via currency_rates.

The user can re-balance the channel split per month later via the UI
(PUT /api/budget/monthly-splits) — that path also handles the overflow note.

Usage (local, with POSTGRES_CONNECTION_STRING set in env or .env):
    cd backend && python -m scripts.import_2026_budget

Usage (Zeabur shell — env already set on the service):
    python -m scripts.import_2026_budget

Re-running is safe — upsert_monthly_split UPDATEs the existing row and
deletes/re-inserts the channel plans.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.services.budget_service import upsert_monthly_split


YEAR = 2026

# Monthly totals in VND, indexed by month (1-12).
# Source: user spreadsheet "ADS BUDGET" screenshot, 2026.
BUDGETS_VND: dict[str, list[int]] = {
    "Taipei": [
        59_240_503, 42_314_645, 67_703_432, 88_860_754, 88_860_754, 76_166_361,
        59_240_503, 59_240_503, 50_777_574, 63_471_967, 88_860_754, 101_555_148,
    ],
    "Oani": [
        59_642_116, 37_276_323, 52_186_852, 78_280_278, 59_240_503, 67_097_381,
        52_186_852, 52_186_852, 44_731_587, 67_097_381, 67_097_381, 89_463_174,
    ],
    "Osaka": [
        55_805_664, 55_805_664, 74_407_552, 97_659_912, 59_240_503, 83_708_496,
        55_805_664, 65_106_608, 65_106_608, 97_659_912, 97_659_912, 111_611_328,
    ],
    "Saigon": [
        35_647_500, 25_462_500, 40_740_000, 61_110_000, 59_240_503, 38_193_750,
        30_555_000, 35_647_500, 35_647_500, 45_832_500, 45_832_500, 61_110_000,
    ],
    "1948": [
        48_566_696, 34_690_497, 55_504_796, 72_850_044, 59_240_503, 62_442_895,
        41_628_597, 48_566_696, 48_566_696, 62_442_895, 62_442_895, 83_257_193,
    ],
}

# Default channel split — placeholder. Manager refines per month via the
# /budget UI later.
DEFAULT_CHANNEL_PCT = {"meta": 100.0, "google": 0.0, "tiktok": 0.0}


def main() -> None:
    db = SessionLocal()
    inserted = 0
    try:
        for branch, monthly in BUDGETS_VND.items():
            assert len(monthly) == 12, f"{branch} must have 12 months, got {len(monthly)}"
            for m_idx, total_vnd in enumerate(monthly, start=1):
                upsert_monthly_split(
                    db,
                    branch=branch,
                    year=YEAR,
                    month=m_idx,
                    total_vnd=float(total_vnd),
                    channel_pct=DEFAULT_CHANNEL_PCT,
                    overflow_note=None,
                    created_by="import_2026_budget.py",
                )
                inserted += 1
                print(f"  {branch} {YEAR}-{m_idx:02d}: {total_vnd:>13,} VND")
        db.commit()
        print(f"\nDone. {inserted} monthly splits upserted for {YEAR}.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
