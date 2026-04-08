# Phase 5: Budget + Parsing Engine + Country Dashboard

## Goal
After completion, the marketing manager can:
1. Open /budget → see current month spend vs allocated per branch/channel
2. Create monthly budget plan, allocate to campaigns, re-allocate mid-month
3. See pace status: On Track / Over / Under with days remaining
4. Open /country → see Country x TA x Funnel Stage breakdown
5. Filter the conversion funnel by country + TA + funnel stage
6. Pull budget + spend data via Export API with API key
7. Trigger /api/sync/reparse to re-parse all campaign/adset names

## Tasks

### Migration & Models
- [ ] Add ta, funnel_stage columns to campaigns model
- [ ] Add country column to ad_sets model
- [ ] Create BudgetPlan, BudgetAllocation models
- [ ] Create ApiKey model
- [ ] Write Migration 003 (3 new tables + 3 fields + indexes)

### Services
- [ ] Create parse_utils.py (TA, funnel stage, country parsing)
- [ ] Update sync_engine.py (call parser on every upsert)
- [ ] Create budget_service.py (pace calc, allocation, dashboard)
- [ ] Create export_auth.py (API key validation, rate limiting)

### Routers
- [ ] Create budget.py router (6 endpoints)
- [ ] Create country.py router (5 endpoints)
- [ ] Create export.py router (5 endpoints)
- [ ] Add POST /api/sync/reparse to sync.py
- [ ] Register new routers in main.py

### Frontend
- [ ] Update Sidebar.tsx (remove /campaigns, add /country + /budget)
- [ ] Create /country page (filters, KPI, TA breakdown, funnel, comparison)
- [ ] Create /budget page (overview, plan creation, pace badges)

### Tests
- [ ] test_parsing.py — edge cases for TA, funnel, country parsing
- [ ] test_budget.py — CRUD, versioning, pace calculation
- [ ] test_country.py — endpoint responses

### Documentation
- [x] Update CLAUDE.md to v3.1
- [x] Create .claude/rules/parsing-rules.md
- [x] Create .claude/rules/platform-rules.md
- [x] Create docs/specs/ files (data-model, parsing, budget, api, figma)
- [x] Create docs/architecture.md
- [ ] Update docs/changelog.md
- [ ] Prep docs/current-phase.md for Phase 6

## Verification Checklist
- [ ] alembic upgrade head succeeds — all new tables + columns created
- [ ] Sync a test campaign — verify ta, funnel_stage populated correctly
- [ ] Sync a test adset — verify country = first 2 chars of name
- [ ] Campaign with no [TOF/MOF] → funnel_stage = 'Unknown' (not error)
- [ ] POST /api/sync/reparse returns { reparsed, unknown_ta, unknown_country }
- [ ] GET /api/budget/dashboard returns branch/channel spend vs allocated
- [ ] POST /api/budget/allocations: second call increments version (not overwrite)
- [ ] GET /api/budget/pace returns On Track / Over / Under with correct logic
- [ ] POST /api/export/keys returns plaintext key once
- [ ] GET /api/export/budget/monthly returns 401 without key
- [ ] GET /api/dashboard/country returns country KPI breakdown
- [ ] GET /api/dashboard/country/ta-breakdown returns TA x funnel_stage table
- [ ] GET /api/dashboard/country/funnel returns filterable funnel data
- [ ] Frontend /country page loads — filters work
- [ ] Frontend /budget page loads — pace badges show correct status
- [ ] Sidebar: /campaigns is gone, /country and /budget are present
- [ ] pytest tests/ -v — all pass
