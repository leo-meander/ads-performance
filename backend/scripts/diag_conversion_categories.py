"""One-shot diagnostic: list ENABLED conversion actions per Google Ads account.

Usage:
    cd backend && venv/Scripts/python -m scripts.diag_conversion_categories

Why: after switching the main metrics query to filter by
`segments.conversion_action_category = PURCHASE`, any account whose Booking/
Reservation action is NOT categorized as PURCHASE will report 0 conversions.
Run this before re-syncing prod to catch misconfigured accounts.
"""
from app.services.google_client import _get_client, _search_stream
from app.models import AdAccount
from app.database import SessionLocal


def main():
    db = SessionLocal()
    try:
        accts = db.query(AdAccount).filter_by(platform="google", is_active=True).all()
        print(f"Found {len(accts)} active Google accounts\n")
        for a in accts:
            cid = a.account_id.replace("-", "")
            try:
                rows = _search_stream(_get_client(), cid, """
                    SELECT conversion_action.name, conversion_action.category, conversion_action.status
                    FROM conversion_action WHERE conversion_action.status = 'ENABLED'
                """)
                cats = [(r.conversion_action.name, r.conversion_action.category.name) for r in rows]
                has_purchase = any(cat == "PURCHASE" for _, cat in cats)
                marker = "OK " if has_purchase else "!! "
                print(f"{marker}{a.account_name} ({a.account_id}):")
                for name, cat in cats:
                    print(f"    {cat:30s} {name}")
                print()
            except Exception as e:
                print(f"!! {a.account_name} ({a.account_id}): ERROR {e}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
