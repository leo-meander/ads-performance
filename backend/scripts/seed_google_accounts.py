"""Seed Google Ads accounts from MEANDER Group.

Usage:
  cd backend && python -m scripts.seed_google_accounts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.account import AdAccount

GOOGLE_ACCOUNTS = [
    {"account_id": "754-576-7444", "account_name": "MD 1948 Google", "currency": "TWD"},
    {"account_id": "858-868-9046", "account_name": "MEANDER Saigon", "currency": "VND"},
    {"account_id": "370-779-8227", "account_name": "MEANDER Osaka", "currency": "JPY"},
    {"account_id": "850-255-1772", "account_name": "Bread Espresso &", "currency": "TWD"},
    {"account_id": "642-675-3347", "account_name": "MEANDER Taipei", "currency": "TWD"},
    {"account_id": "990-824-8556", "account_name": "Meander Oani", "currency": "TWD"},
]


def main():
    db = SessionLocal()
    created = 0
    skipped = 0

    try:
        for acct in GOOGLE_ACCOUNTS:
            existing = (
                db.query(AdAccount)
                .filter(
                    AdAccount.platform == "google",
                    AdAccount.account_id == acct["account_id"],
                )
                .first()
            )
            if existing:
                print(f"  SKIP  {acct['account_name']} ({acct['account_id']}) - already exists")
                skipped += 1
                continue

            account = AdAccount(
                platform="google",
                account_id=acct["account_id"],
                account_name=acct["account_name"],
                currency=acct["currency"],
                is_active=True,
                access_token_enc=None,  # Uses global credentials from .env
            )
            db.add(account)
            created += 1
            print(f"  ADD   {acct['account_name']} ({acct['account_id']})")

        db.commit()
        print(f"\nDone: {created} created, {skipped} skipped")
    finally:
        db.close()


if __name__ == "__main__":
    main()
