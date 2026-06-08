# Integrations

## Growth Team Expenses sheet ↔ Ads Platform + HiD

One Apps Script auto-fills the expenses Google Sheet (`Month | Year | Branch |
Chanel | Allocate | Actual Spend | % Spend`) from **two** sources:

| Channels            | Source        | Endpoint                                  | From    |
|---------------------|---------------|-------------------------------------------|---------|
| Meta / Google / TikTok | Ads Platform  | `GET /api/export/budget/channel-monthly`  | 03/2026 |
| KOL / CRM           | HiD Dashboard | `GET /api/marketing-budget/yearly`        | 04/2026 |

Designer + everything else stays manual.

- **Apps Script:** [`expenses-sheet.gs`](expenses-sheet.gs) — paste into the
  sheet's Apps Script project, fill `ADS_BASE_URL` + `ADS_API_KEY` +
  `HID_BASE_URL`, run `syncExpenses` (menu **Expenses Sync → Kéo tất cả**;
  optionally `installDailyTrigger` for a daily pull).

### Block model (so it can sort)

Everything from `FILL_START_ROW` (**A109**) downward is script-managed. Each
run wipes A–G from that row down, fetches both sources, merges, **sorts by
year → month → branch → channel**, and rewrites. Idempotent (no dupes), Actual
self-updates daily. **Manual rows must live ABOVE row 109.**

### Ads Platform endpoint contract

### Endpoint contract

Auth: `X-API-Key` header (create one via `POST /api/export/keys`, admin only).

Query params:

| param  | required | notes                                            |
|--------|----------|--------------------------------------------------|
| `year` | yes      | 4-digit, e.g. `2026`                             |
| `branch` | no     | canonical branch (case-insensitive). All if omitted |
| `month`  | no     | `1`–`12`. Whole year if omitted                 |

Returns one row per (month × branch × channel) for `meta` / `google` /
`tiktok` only, with **both** allocate and spend already converted to **VND**
server-side (via `currency_rates`). Spend mirrors the Budget module
(campaign-level metrics only, no ad-set/ad double counting). Rows where both
allocate and spend are zero are omitted.

```jsonc
{
  "success": true,
  "data": {
    "year": 2026,
    "month": null,
    "rows": [
      {
        "year": 2026, "month": 3, "branch": "Osaka", "channel": "Meta",
        "channel_key": "meta", "currency": "JPY", "rate_to_vnd": 165.01,
        "allocate_native": 331797.6, "spend_native": 414850.0,
        "allocate_vnd": 54750805, "spend_vnd": 68454550, "spend_pct": 125.03
      }
      // ...
    ]
  },
  "error": null,
  "timestamp": "..."
}
```

> Allocate is read from `budget_plans` — so a branch/channel only shows an
> Allocate value once it has been entered in the Budget module. Spend shows up
> regardless, as long as ad metrics are synced.
