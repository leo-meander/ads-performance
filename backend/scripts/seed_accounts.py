"""Seed script: register all 6 Meta Ads branch accounts into the database.

Usage:
    cd backend
    python -m scripts.seed_accounts
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.database import SessionLocal
from app.models.account import AdAccount

BRANCHES = [
    {
        "account_name": "Meander Saigon",
        "account_id": settings.META_AD_ACCOUNT_SAIGON,
        "access_token": settings.META_ACCESS_TOKEN_SAIGON,
        "currency": "VND",
    },
    {
        "account_name": "Oani (Taipei)",
        "account_id": settings.META_AD_ACCOUNT_OANI,
        "access_token": settings.META_ACCESS_TOKEN_OANI,
        "currency": "TWD",
    },
    {
        "account_name": "Meander Osaka",
        "account_id": settings.META_AD_ACCOUNT_OSAKA,
        "access_token": settings.META_ACCESS_TOKEN_OSAKA,
        "currency": "JPY",
    },
    {
        "account_name": "Meander Taipei",
        "account_id": settings.META_AD_ACCOUNT_TAIPEI,
        "access_token": settings.META_ACCESS_TOKEN_TAIPEI,
        "currency": "TWD",
    },
    {
        "account_name": "Meander 1948",
        "account_id": settings.META_AD_ACCOUNT_1948,
        "access_token": settings.META_ACCESS_TOKEN_1948,
        "currency": "TWD",
    },
    {
        "account_name": "Bread Espresso And",
        "account_id": settings.META_AD_ACCOUNT_BREAD,
        "access_token": settings.META_ACCESS_TOKEN_BREAD,
        "currency": "TWD",
    },
]


def seed():
    db = SessionLocal()
    try:
        for branch in BRANCHES:
            if not branch["account_id"]:
                print(f"  SKIP {branch['account_name']} — no account ID configured")
                continue

            existing = (
                db.query(AdAccount)
                .filter(AdAccount.account_id == branch["account_id"])
                .first()
            )

            if existing:
                # Update token if changed
                existing.access_token_enc = branch["access_token"]
                existing.account_name = branch["account_name"]
                existing.is_active = True
                print(f"  UPDATE {branch['account_name']} ({branch['account_id']})")
            else:
                account = AdAccount(
                    platform="meta",
                    account_id=branch["account_id"],
                    account_name=branch["account_name"],
                    currency=branch["currency"],
                    access_token_enc=branch["access_token"],
                )
                db.add(account)
                print(f"  CREATE {branch['account_name']} ({branch['account_id']})")

        db.commit()
        print(f"\nDone. {len(BRANCHES)} branches processed.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
