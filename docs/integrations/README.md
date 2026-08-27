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

---

## Campaign Report sheet ↔ Ads Platform

`[MEANDER GROUP] CAMPAIGN REPORT`: the three monthly blocks (META / GOOGLE /
TIKTOK) fill themselves from the Ads Platform instead of being typed by hand
each month. One script, two tabs (`CONFIG.TARGETS`), one set of API calls
shared between them:

| Tab                     | Branches        | Currency        |
|-------------------------|-----------------|-----------------|
| `Total Budget_Paid Ads` | all except Bread | VND             |
| `BE& Only_Paid Ads`     | Bread only       | native (NT$)    |

- **Apps Script:** [`campaign-report-sheet.gs`](campaign-report-sheet.gs) —
  paste into the sheet's Apps Script project, set `ADS_BASE_URL` +
  `ADS_API_KEY`, then menu **Ads Sync → Xem thử (dry run)** before the first
  real run. `installDailyTrigger` schedules a daily pull (~08:00).

### What it writes

| Row            | Source                                   |
|----------------|------------------------------------------|
| Spent (-VAT)   | `spend_vnd` / `spend_native` (÷ `1 + VAT_RATE`, default 0) |
| Booking / Purchase | `conversions`                        |
| Revenue        | `revenue_vnd` / `revenue_native`         |
| ROAS           | live formula `=Revenue/Spent`            |
| Leads          | `leads` — written only when the API reports > 0 |
| Cost per lead  | live formula `=Spent/Leads`              |

`leads` is Meta's lead actions plus Google `SUBMIT_LEAD_FORM`, summed over the
same campaign-level rows as spend. Writing it only when it is > 0 keeps a
hand-entered figure from being zeroed by a platform that runs no lead ads; a
hand-typed Cost per lead is likewise never replaced by the formula.

The **TOTAL CHANNEL** block gets no numbers written into it — it runs on the
sheet's own formulas. But a newly inserted month column starts empty, which
looks like the roll-up lost the month. Two fallbacks, in order:

1. copy the previous month column's formulas across (`copyTo` shifts the
   relative refs), then
2. for cells still empty — which happens when the previous month was *typed in*
   rather than computed — build the formula from the block rows the script
   already located: `=P4+P15+P24` (Meta + Google + TikTok), plus
   `=Revenue/Spent` for ROAS and `=Spent/Leads` for cost per lead.

Neither step ever overwrites a cell that already holds something. Same idea for
the **Total** column: an existing `=SUM(C4:O4)` gets its range widened to cover
the new column. Anything that is not a single-range same-row `SUM` (the weighted
ROAS total, for instance) is left alone.

### Endpoint contract

`GET /api/export/kpi/paid-ads-monthly?year=YYYY&platform=meta|google|tiktok`
(auth: `X-API-Key`). Returns branch × month `spend_native/vnd`,
`revenue_native/vnd`, `conversions`, `roas` — the exact mirror of the
`/dashboard/country` aggregate (campaign-level metrics only, valid country
only). The script sums the branches itself, so it can drop some.

The current partial month's header label (`August - 2026 (1st-25th)`) is
derived from `GET /api/export/spend/daily` — the last day that actually has
spend. Once a month is fully synced the suffix is dropped.

### Branch scope — BE& is its own target

`Bread` (BE&) is reported on its own tab, so the group tab must not include it.
Both tabs are declared in `CONFIG.TARGETS`:

```js
{ sheetName: 'Total Budget_Paid Ads', onlyBranches: [],        excludeBranches: ['Bread'], currency: 'VND' }
{ sheetName: 'BE& Only_Paid Ads',     onlyBranches: ['Bread'], excludeBranches: [],        currency: 'NATIVE' }
```

`currency: 'NATIVE'` makes the BE& tab use `spend_native` / `revenue_native`
(NT$), while the group tab uses the VND columns. The BE& tab labels its
conversions row **Purchase** rather than **Booking** — both are recognised.
Menu items **Chỉ tab tổng** / **Chỉ tab BE&** run a single target; a failure in
one tab never stops the other.

### Month columns

Month → column is read from each block's header row, so nothing is hard-coded.
A block missing the label for a month (e.g. Google had no `August - 2026` yet)
gets it written in, copying that block's own label style (`June - 2026` →
`July - 2026`, but `Jul (1st-27th)` → `Aug`). If **no** block has the month,
`AUTO_ADD_COLUMN` inserts a new column after the last month column.

Columns are only ever appended to the **right**, for a month newer than every
column already present. A missing *older* month is reported and skipped: the
two tabs cover different periods (BE& opened in May 2026), and inserting `Jan`
after `Jul` scrambles the sheet. Each target can also declare
`startYear` / `startMonth`, which is what keeps a whole-year run from asking
the BE& tab for January–April at all.

`EXTEND_TOTAL_SUM` handles the Total column after an insert; `COPY_FORMULA_COLUMN`
handles the TOTAL CHANNEL block. Set either to `false` to go back to doing it
by hand.

### Troubleshooting

Menu **Ads Sync → Debug: vì sao tháng này không ra số?** dumps everything the
script sees: the blocks it detected, every header label (and whether it parsed
to a month), the month→column map, and the raw per-branch API numbers for the
current month — including which branches were excluded. If the API totals come
back 0 the problem is upstream (metrics not synced for that month), not the
sheet.

Two failure modes already fixed, worth knowing about:

- **Header scan out of bounds** — reading up to `MAX_SCAN_COL` (40) on a sheet
  with fewer columns makes Apps Script throw, and the whole run dies before
  writing anything. The scan is now clamped to `sheet.getMaxColumns()`.
- **Hidden prior-year columns** — the collapsed columns left of `Jan - 2026`
  hold last year's months. If their labels carry no year (`Jul`, `Aug`), a
  naive scan maps month 7/8 to those hidden columns and writes there, which
  looks exactly like "the script did nothing". The month map now takes
  year-qualified labels first and never accepts a year-less label to the left
  of the target year's range.

### Safety defaults

- `OVERWRITE: 'recent'` — only the current month + the previous one are
  rewritten, so hand-entered history stays put. `'all'` rewrites the year.
- `SKIP_EMPTY_MONTH: true` — a month the API reports as 0/0 is skipped rather
  than zeroing a cell that already holds a real number (guards against a dead
  sync token silently blanking the sheet).
- `VAT_RATE: 0` — platform spend is treated as already ex-VAT. Set `0.05` to
  make the script divide it out.
