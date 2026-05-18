"""Re-sync Google Ads metrics for the PURCHASE-only conversion fix.

After landing the change that filters main metrics by
`segments.conversion_action_category = PURCHASE`, MetricsCache rows for
historical dates still hold the old (inflated) conversions/revenue. This
script re-pulls a date window per Google account so the cache reflects the
new definition.

Usage:
    cd backend
    venv/Scripts/python -m scripts.resync_google_purchases [--bread-only] \
        [--date-from 2026-04-01] [--date-to 2026-05-18]
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.database import SessionLocal
from app.models.account import AdAccount
from app.services.google_sync_engine import sync_google_metrics_window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bread-only", action="store_true")
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--chunk-days", type=int, default=15)
    args = parser.parse_args()

    end = date.fromisoformat(args.date_to) if args.date_to else date.today()
    start = date.fromisoformat(args.date_from) if args.date_from else end - timedelta(days=45)

    db = SessionLocal()
    try:
        q = db.query(AdAccount).filter_by(platform="google", is_active=True)
        if args.bread_only:
            q = q.filter(AdAccount.account_name.ilike("%Bread%"))
        accounts = q.all()

        print(f"Re-syncing {len(accounts)} Google account(s) from {start} to {end}")
        print(f"  chunk size = {args.chunk_days} days\n")

        chunk_end = end
        chunk_count = 0
        totals = {"metrics_synced": 0, "ad_country_rows": 0, "errors": 0}

        while chunk_end >= start:
            chunk_start = max(chunk_end - timedelta(days=args.chunk_days - 1), start)
            chunk_count += 1
            print(f"-- chunk #{chunk_count}: {chunk_start} .. {chunk_end} --")
            for account in accounts:
                try:
                    res = sync_google_metrics_window(db, account, chunk_start, chunk_end)
                    totals["metrics_synced"] += res["metrics_synced"]
                    totals["ad_country_rows"] += res["ad_country_rows"]
                    totals["errors"] += len(res["errors"])
                    err_tag = f" errs={len(res['errors'])}" if res["errors"] else ""
                    print(f"  {account.account_name}: metrics={res['metrics_synced']} country={res['ad_country_rows']}{err_tag}")
                except Exception as e:
                    print(f"  {account.account_name}: EXCEPTION {e}")
                    totals["errors"] += 1
            chunk_end = chunk_start - timedelta(days=1)

        print(f"\nDone. {chunk_count} chunks. totals={totals}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
