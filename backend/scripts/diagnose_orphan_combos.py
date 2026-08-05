"""CLI wrapper for creative_sync.diagnose_orphan_combos — see that function's
docstring for what it does and why the naive "no matching `ads` row" SQL test
over-selects.

Read-only: opens a session, writes nothing. For environments without local DB
access, hit POST /api/internal/tasks/diagnose-orphan-combos on the deployed
backend instead (same logic, JSON response).

Usage:
    cd backend && python -m scripts.diagnose_orphan_combos
    cd backend && python -m scripts.diagnose_orphan_combos --account "Meander 1948"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.services.creative_sync import diagnose_orphan_combos


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", help="only this account_name (substring match)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = diagnose_orphan_combos(db, account_name_filter=args.account)
        for entry in result["accounts"]:
            print(f"\n=== {entry['account_name']} ({entry['account_id']})")
            print(f"  {entry['status']}")
            for c in entry.get("combos", []):
                twins = f"  twins={c['twins']}" if c["twins"] else ""
                print(
                    f"  [{c['verdict']:17}] {c['combo_id']} {c['combo_verdict']:5} "
                    f"spend={c['spend']} roas={c['roas']} "
                    f"updated={c['updated_at']} {c['ad_name']!r}{twins}"
                )

        t = result["totals"]
        print(
            f"\nTOTAL: {t['RENAMED_OR_DELETED']} renamed/deleted, "
            f"{t['MISSING_FROM_ADS']} missing-from-ads (not renames), "
            f"{t['NO_SPEND']} never delivered"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
