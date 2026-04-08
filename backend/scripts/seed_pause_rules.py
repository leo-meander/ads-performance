"""Seed script: create 'Pause Ad Today' automation rules for 5 hotel branches.

Replicates Madgicx-style rule logic at AD LEVEL:
  Pause an ad today if ALL conditions are true (AND):
    1. CTR today < CTR average last 30 days (underperforming)
    2. Impressions today >= 1000 (enough data to judge)
    3. Number of Active Ads in Ad Set >= 2 (don't pause the last ad)
    4. Hours since creation >= 120 (ad is at least 5 days old)
    5. Add to Cart today < 1 (zero add-to-carts)
    6. Checkouts today < 1 (zero checkouts)
    7. Purchases (conversions) today < 1 (zero purchases)

Usage:
    cd backend
    python -m scripts.seed_pause_rules
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.account import AdAccount
from app.models.rule import AutomationRule

# 5 hotel branches (excluding Bread Espresso And restaurant)
HOTEL_BRANCHES = [
    "Meander Saigon",
    "Oani (Taipei)",
    "Meander Osaka",
    "Meander Taipei",
    "Meander 1948",
]

# Rule conditions matching Madgicx "Pause Ad for Today" logic
# days=0 means "today only" (date >= today)
PAUSE_CONDITIONS = [
    # 1. CTR today < CTR avg last 30 days (incl. today)
    {
        "metric": "ctr",
        "operator": "<",
        "days": 0,
        "compare_metric": "ctr",
        "compare_period_from": 0,
        "compare_period_to": 30,
    },
    # 2. Impressions today >= 1000 (enough data to judge)
    {
        "metric": "impressions",
        "operator": ">=",
        "threshold": 1000,
        "days": 0,
    },
    # 3. Number of Active Ads in Ad Set >= 2 (don't pause the last ad)
    {
        "metric": "active_ads_in_adset",
        "operator": ">=",
        "threshold": 2,
    },
    # 4. Hours since creation >= 120 (ad at least 5 days old)
    {
        "metric": "hours_since_creation",
        "operator": ">=",
        "threshold": 120,
    },
    # 5. Add to Cart today = 0
    {
        "metric": "add_to_cart",
        "operator": "<",
        "threshold": 1,
        "days": 0,
    },
    # 6. Checkouts today = 0
    {
        "metric": "checkouts",
        "operator": "<",
        "threshold": 1,
        "days": 0,
    },
    # 7. Purchases (conversions) today = 0
    {
        "metric": "conversions",
        "operator": "<",
        "threshold": 1,
        "days": 0,
    },
]


def seed():
    db = SessionLocal()
    try:
        created = 0
        skipped = 0

        for branch_name in HOTEL_BRANCHES:
            # Look up the ad account by name
            account = (
                db.query(AdAccount)
                .filter(
                    AdAccount.account_name == branch_name,
                    AdAccount.is_active.is_(True),
                )
                .first()
            )

            if not account:
                print(f"  SKIP {branch_name} — account not found in DB")
                skipped += 1
                continue

            rule_name = f"Pause Ad Today — {branch_name}"

            # Check if rule already exists (avoid duplicates)
            existing = (
                db.query(AutomationRule)
                .filter(
                    AutomationRule.name == rule_name,
                    AutomationRule.account_id == account.id,
                )
                .first()
            )

            if existing:
                # Update existing rule conditions
                existing.conditions = PAUSE_CONDITIONS
                existing.action = "pause_ad"
                existing.entity_level = "ad"
                existing.is_active = True
                print(f"  UPDATE {rule_name} (id={existing.id})")
            else:
                rule = AutomationRule(
                    name=rule_name,
                    platform="meta",
                    account_id=account.id,
                    entity_level="ad",
                    conditions=PAUSE_CONDITIONS,
                    action="pause_ad",
                    action_params=None,
                    is_active=True,
                    created_by="seed_script",
                )
                db.add(rule)
                print(f"  CREATE {rule_name}")
                created += 1

        db.commit()
        print(f"\nDone. Created: {created}, Skipped: {skipped}, Total branches: {len(HOTEL_BRANCHES)}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
