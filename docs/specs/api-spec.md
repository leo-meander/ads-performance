# API Specification

## Standard Response Format
All endpoints return:
```json
{
  "success": true|false,
  "data": <payload>,
  "error": null|"error message",
  "timestamp": "2026-04-03T12:00:00Z"
}
```

## Authentication
- Internal endpoints: No authentication (internal network)
- Export endpoints: API key via `X-API-Key` header

## Endpoints

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |

### Accounts
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/accounts | List active accounts |
| POST | /api/accounts | Create ad account |

### Campaigns
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/campaigns | List campaigns (with metrics) |
| GET | /api/campaigns/{id} | Campaign detail with metrics |

### Ad Sets & Ads
Accessed through campaign hierarchy.

### Creative Library
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/keypoints | List keypoints |
| POST | /api/keypoints | Create keypoint |
| PUT | /api/keypoints/{id} | Update keypoint |
| DELETE | /api/keypoints/{id} | Soft delete keypoint |
| GET | /api/angles | List angles |
| POST | /api/angles | Create angle |
| PUT | /api/angles/{id} | Update angle |
| GET | /api/copies | List copies |
| POST | /api/copies | Create copy |
| PUT | /api/copies/{id} | Update copy |
| GET | /api/materials | List materials |
| POST | /api/materials | Create material |
| PUT | /api/materials/{id} | Update material |
| GET | /api/combos | List combos with metrics |
| POST | /api/combos | Create combo |
| PUT | /api/combos/{id} | Update combo |
| POST | /api/combos/classify | Auto-classify all combos |

### Automation Rules
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/rules | List rules |
| POST | /api/rules | Create rule |
| PUT | /api/rules/{id} | Update rule |
| DELETE | /api/rules/{id} | Soft delete rule |

### AI Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/ai/chat | Stream AI response |
| GET | /api/ai/sessions | List chat sessions |
| DELETE | /api/ai/sessions/{id} | Delete session |

### Sync
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/sync/trigger | Trigger manual sync |
| POST | /api/sync/reparse | **Phase 5** — Re-parse campaign/adset names |

### Budget (Phase 5)
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/budget/dashboard | Budget overview (spend vs allocated) |
| GET | /api/budget/plans | List budget plans |
| POST | /api/budget/plans | Create budget plan |
| GET | /api/budget/plans/{id} | Plan detail with allocations |
| POST | /api/budget/allocations | Create allocation (INSERT only) |
| GET | /api/budget/pace | Pace status per branch/channel |

### Country Dashboard (Phase 5)
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/dashboard/country | Country KPI summary |
| GET | /api/dashboard/country/ta-breakdown | TA x Funnel Stage breakdown |
| GET | /api/dashboard/country/funnel | Conversion funnel data |
| GET | /api/dashboard/country/comparison | Country comparison table |
| GET | /api/dashboard/country/countries | Available countries list |

### Export API (Phase 5)
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/export/keys | Create API key |
| GET | /api/export/keys | List API keys |
| DELETE | /api/export/keys/{id} | Deactivate key |
| GET | /api/export/budget/monthly | Export budget data |
| GET | /api/export/budget/yearly-plan | Export yearly plan (mirror of /api/budget/yearly-plan) |
| GET | /api/export/budget/monthly-splits | Export 12-month splits (mirror of /api/budget/monthly-splits) |
| GET | /api/export/spend/daily | Export spend data |

## Query Parameters (common)
- `limit` — Pagination limit (default 50, max 200)
- `offset` — Pagination offset (default 0)
- `date_from` / `date_to` — Date range filter (ISO8601)
- `platform` — Platform filter (meta/google/tiktok)
- `branch` — Branch filter
- `country` — Country filter (ISO 3166-1 alpha-2)
