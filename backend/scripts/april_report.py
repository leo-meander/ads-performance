"""Pull April 1-23 ads performance for monthly report.

Outputs per-branch and per-campaign breakdown:
- Total campaigns, on/off counts
- Spend / revenue / bookings / ROAS in VND
- Paused campaigns + their target markets
- Top scaling campaigns
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg2
import psycopg2.extras

# Load .env
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip())

CONN = os.environ["POSTGRES_CONNECTION_STRING"]

# FX → VND (matches backend/app/routers/campaigns.py)
FX_TO_VND = {"VND": 1, "TWD": 800, "JPY": 170, "USD": 25500}

BRANCH_PATTERNS = {
    "Saigon": ["Meander Saigon", "Saigon"],
    "Osaka": ["Meander Osaka", "Osaka"],
    "Taipei": ["Meander Taipei"],
    "1948": ["Meander 1948", "1948"],
    "Oani": ["Oani (Taipei)", "Oani"],
    "Bread": ["Bread Espresso", "Bread"],
}


def resolve_branch(account_name: str | None) -> str:
    if not account_name:
        return "Unknown"
    lower = account_name.lower()
    for branch, patterns in BRANCH_PATTERNS.items():
        for p in patterns:
            if p.lower() in lower:
                return branch
    return "Unknown"


def main():
    d_from = date(2026, 4, 1)
    d_to = date(2026, 4, 23)

    conn = psycopg2.connect(CONN)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Per-campaign aggregated metrics
    cur.execute(
        """
        SELECT
          c.id              AS campaign_id,
          c.name            AS campaign_name,
          c.platform        AS platform,
          c.status          AS status,
          c.objective       AS objective,
          c.country         AS country,
          a.account_name    AS account_name,
          a.currency        AS currency,
          COALESCE(SUM(m.spend), 0)        AS spend_native,
          COALESCE(SUM(m.impressions), 0)  AS impressions,
          COALESCE(SUM(m.clicks), 0)       AS clicks,
          COALESCE(SUM(m.link_clicks), 0)  AS link_clicks,
          COALESCE(SUM(m.conversions), 0)  AS conversions,
          COALESCE(SUM(m.revenue), 0)      AS revenue_native
        FROM campaigns c
        JOIN ad_accounts a ON c.account_id = a.id
        LEFT JOIN metrics_cache m
          ON m.campaign_id = c.id
         AND m.date >= %s AND m.date <= %s
        GROUP BY c.id, c.name, c.platform, c.status, c.objective, c.country,
                 a.account_name, a.currency
        ORDER BY a.account_name, c.name
        """,
        (d_from, d_to),
    )
    campaigns = cur.fetchall()

    # Per-branch booking match (real bookings)
    cur.execute(
        """
        SELECT
          branch,
          ads_channel,
          COUNT(*)              AS bookings,
          SUM(ads_revenue)      AS revenue
        FROM booking_matches
        WHERE match_date >= %s AND match_date <= %s
          AND match_result = 'matched'
        GROUP BY branch, ads_channel
        ORDER BY branch, ads_channel
        """,
        (d_from, d_to),
    )
    bookings = cur.fetchall()

    # Per-campaign booking matches → so we know which campaigns produced bookings
    cur.execute(
        """
        SELECT
          campaign_id,
          COUNT(*)         AS bookings,
          SUM(ads_revenue) AS revenue
        FROM booking_matches
        WHERE match_date >= %s AND match_date <= %s
          AND match_result = 'matched'
          AND campaign_id IS NOT NULL
        GROUP BY campaign_id
        """,
        (d_from, d_to),
    )
    booking_by_campaign = {row["campaign_id"]: row for row in cur.fetchall()}

    # Per-adset country (Meta) for paused campaigns — to know which markets are paused
    cur.execute(
        """
        SELECT
          s.campaign_id,
          s.country,
          s.status
        FROM ad_sets s
        WHERE s.campaign_id IS NOT NULL
        """
    )
    adsets_by_campaign: dict[str, list[dict]] = defaultdict(list)
    for r in cur.fetchall():
        adsets_by_campaign[r["campaign_id"]].append(r)

    cur.close()
    conn.close()

    # Aggregate per branch
    per_branch: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0, "on": 0, "off": 0,
            "spend_vnd": 0.0, "revenue_vnd": 0.0,
            "bookings": 0,
            "campaigns": [],
            "paused_markets": set(),
        }
    )

    for c in campaigns:
        branch = resolve_branch(c["account_name"])
        rate = FX_TO_VND.get(c["currency"], 1)
        spend_vnd = float(c["spend_native"]) * rate
        rev_native = float(c["revenue_native"])
        rev_vnd = rev_native * rate
        # Real bookings via matched booking → that's the source of truth
        bm = booking_by_campaign.get(c["campaign_id"])
        b_count = int(bm["bookings"]) if bm else 0
        b_rev_vnd = float(bm["revenue"]) if bm else 0  # ads_revenue stored in VND already

        info = {
            "id": c["campaign_id"],
            "name": c["campaign_name"],
            "platform": c["platform"],
            "status": c["status"],
            "country": c["country"],
            "spend_vnd": spend_vnd,
            "revenue_vnd": rev_vnd,
            "matched_bookings": b_count,
            "matched_revenue_vnd": b_rev_vnd,
            "roas": (rev_vnd / spend_vnd) if spend_vnd > 0 else None,
        }

        # Filter: only count campaigns that were actually running in this period
        # (had spend OR currently ACTIVE). Skip archived/paused-with-zero-spend.
        if spend_vnd <= 0 and c["status"] != "ACTIVE":
            continue

        b = per_branch[branch]
        b["total"] += 1
        if c["status"] == "ACTIVE":
            b["on"] += 1
        else:
            b["off"] += 1
            # collect target markets of paused campaigns
            if c["country"]:
                b["paused_markets"].add(c["country"])
            for s in adsets_by_campaign.get(c["campaign_id"], []):
                if s["country"]:
                    b["paused_markets"].add(s["country"])
        b["spend_vnd"] += spend_vnd
        b["revenue_vnd"] += rev_vnd
        b["bookings"] += b_count
        b["campaigns"].append(info)

    # Print summary
    print("=" * 80)
    print(f"ADS REPORT - {d_from} -> {d_to}")
    print("=" * 80)

    grand_total = sum(b["total"] for b in per_branch.values())
    grand_on = sum(b["on"] for b in per_branch.values())
    grand_off = sum(b["off"] for b in per_branch.values())
    grand_spend = sum(b["spend_vnd"] for b in per_branch.values())
    grand_rev = sum(b["revenue_vnd"] for b in per_branch.values())
    grand_book = sum(b["bookings"] for b in per_branch.values())

    print(f"\nGRAND TOTAL: {grand_total} campaigns | ON {grand_on} | OFF {grand_off}")
    print(f"  Spend: {grand_spend:,.0f} VND | Pixel revenue: {grand_rev:,.0f} VND")
    print(f"  Matched bookings (Cloudbeds): {grand_book}")
    print(f"  Blended ROAS (pixel): {grand_rev/grand_spend:.2f}" if grand_spend else "")

    for branch, b in sorted(per_branch.items()):
        print("\n" + "-" * 80)
        print(f"BRANCH: {branch}")
        print(f"  Campaigns: {b['total']}  ON: {b['on']}  OFF: {b['off']}")
        print(f"  Spend: {b['spend_vnd']:,.0f} VND")
        print(f"  Pixel revenue: {b['revenue_vnd']:,.0f} VND")
        print(f"  Matched bookings: {b['bookings']}")
        if b["spend_vnd"]:
            print(f"  ROAS (pixel): {b['revenue_vnd']/b['spend_vnd']:.2f}")
        if b["paused_markets"]:
            print(f"  Paused markets: {sorted(b['paused_markets'])}")

        # top campaigns by spend
        top = sorted(b["campaigns"], key=lambda x: x["spend_vnd"], reverse=True)[:8]
        print("  Top campaigns by spend:")
        for c in top:
            roas = f"{c['roas']:.2f}" if c["roas"] is not None else "—"
            print(
                f"    [{c['status']:7s}] {c['platform']:6s} | "
                f"spend {c['spend_vnd']:>12,.0f} | roas {roas:>5s} | "
                f"book {c['matched_bookings']:>2} | {c['name'][:60]}"
            )

    # Bookings per channel
    print("\n" + "=" * 80)
    print("BOOKINGS PER BRANCH x CHANNEL (matched, Cloudbeds-confirmed)")
    print("=" * 80)
    for row in bookings:
        rev = row["revenue"] or 0
        print(f"  {row['branch'] or '—':20s} {row['ads_channel'] or '—':10s} "
              f"bookings={row['bookings']:>3}  rev={float(rev):>14,.0f} VND")


if __name__ == "__main__":
    main()
