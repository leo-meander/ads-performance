# Budget Module Specification

## Overview
The budget module allows the marketing manager to:
- Create monthly budget plans per branch and channel
- Allocate budget to specific campaigns
- Track spend vs allocation (pace status)
- Re-allocate mid-month with version tracking
- Export budget data via API key-authenticated endpoints

## Data Model

### budget_plans
One plan per branch/channel/month combination.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | VARCHAR(200) | e.g., "Saigon Meta April 2026" |
| branch | VARCHAR(100) | Saigon/Taipei/1948/Osaka/Oani/Bread |
| channel | VARCHAR(20) | meta/google/tiktok |
| month | DATE | First day of month |
| total_budget | NUMERIC(15,2) | Total allocated for the month |
| currency | VARCHAR(3) | Default VND |
| notes | TEXT | Optional |
| is_active | BOOLEAN | Soft delete |
| created_by | VARCHAR(100) | |

Unique constraint: (branch, channel, month)

### budget_allocations
**NEVER UPDATE existing rows** — always INSERT with incremented version.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| plan_id | UUID | FK → budget_plans |
| campaign_id | UUID | FK → campaigns, optional |
| amount | NUMERIC(15,2) | Allocated amount |
| version | INTEGER | Auto-increment per plan_id |
| reason | TEXT | Why this allocation |
| created_by | VARCHAR(100) | |

Version logic: `SELECT MAX(version) FROM budget_allocations WHERE plan_id = ? → new version = max + 1`

## API Endpoints

### GET /api/budget/dashboard
Returns budget overview with spend vs allocated per branch/channel.
Query params: `month` (YYYY-MM), `branch` (optional), `channel` (optional)

Response:
```json
{
  "success": true,
  "data": {
    "month": "2026-04",
    "items": [
      {
        "branch": "Saigon",
        "channel": "meta",
        "total_budget": 50000000,
        "allocated": 45000000,
        "spent": 32000000,
        "pace_status": "On Track",
        "days_remaining": 15,
        "projected_spend": 48000000,
        "currency": "VND"
      }
    ]
  }
}
```

### GET /api/budget/plans
List budget plans. Query: `month`, `branch`, `channel`, `limit`, `offset`

### POST /api/budget/plans
Create a new budget plan.
```json
{
  "name": "Saigon Meta April 2026",
  "branch": "Saigon",
  "channel": "meta",
  "month": "2026-04-01",
  "total_budget": 50000000,
  "currency": "VND"
}
```

### GET /api/budget/plans/{id}
Get plan with all allocations (latest version per campaign).

### POST /api/budget/allocations
Create allocation (INSERT new row, version auto-increments).
```json
{
  "plan_id": "uuid",
  "campaign_id": "uuid",
  "amount": 10000000,
  "reason": "Initial allocation for TOF campaign"
}
```

### GET /api/budget/pace
Pace status per branch/channel for current month.

## Pace Calculation

```python
days_in_month = calendar.monthrange(year, month)[1]
days_elapsed = (today - first_of_month).days + 1
expected_spend = (total_budget / days_in_month) * days_elapsed
projected_spend = (actual_spend / days_elapsed) * days_in_month

if projected_spend > total_budget * 1.1:
    pace = "Over"
elif projected_spend < total_budget * 0.9:
    pace = "Under"
else:
    pace = "On Track"
```

## Export API (API Key Authentication)

### POST /api/export/keys
Create a new API key. Returns plaintext once.

### GET /api/export/keys
List active keys (shows prefix only, never full key).

### DELETE /api/export/keys/{id}
Deactivate a key (soft delete).

### GET /api/export/budget/monthly
Requires API key in `X-API-Key` header. Rate limited (daily).
Returns monthly budget data for all branches.

### GET /api/export/spend/daily
Requires API key. Returns daily spend breakdown.
