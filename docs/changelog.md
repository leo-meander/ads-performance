# Changelog

## Phase 6 — Combo Approval & Launch System
- **User Auth System**: JWT-based authentication with bcrypt password hashing, httpOnly cookies, role enforcement (admin/creator/reviewer)
- **Migration 005**: 5 new tables — users, combo_approvals, approval_reviewers, notifications, campaign_auto_configs
- **Approval Workflow**: Multi-reviewer approval with all-approve requirement, round versioning for re-submissions, creator-only launch control
- **Notification System**: In-system bell notifications + async email via Celery. Triggers: review request, approval/rejection, launch success/failure
- **Meta Ads Launch**: Two modes — launch into existing campaign, or auto-create new campaign from campaign_auto_configs (Country + TA + Language)
- **API Endpoints**: 20+ new endpoints across 5 routers (auth, users, approvals, launch, notifications)
- **Frontend Pages**: Login (/login), Approvals list (/approvals), Approval detail (/approvals/{id}), Launch flow (/approvals/{id}/launch), Submit for approval (/creative/{id}/submit), User management (/users)
- **Frontend Components**: AuthContext, NotificationBell, ApprovalStatusBadge, ReviewerStatusList, WorkingFileLinkCard, HeaderBar
- **Navigation**: Added Approvals (with unread badge) and Users (admin only) to sidebar
- **Tests**: test_auth.py (16), test_approvals.py (10), test_launch.py (5), test_notifications.py (6) — 37 total

## Phase 5 — Budget + Parsing Engine + Country Dashboard
- **Name Parsing Engine**: parse_utils.py extracts TA, funnel_stage from campaign names and country from adset names at sync time
- **Sync Engine Update**: Parser called on every campaign/adset upsert; POST /api/sync/reparse for manual re-parse
- **Migration 003**: Added ta + funnel_stage to campaigns, country to ad_sets; created budget_plans, budget_allocations, api_keys tables
- **Budget Module**: Full CRUD for budget plans + allocations (INSERT-only versioning), pace calculation (On Track/Over/Under)
- **Country Dashboard**: 5 new endpoints — country KPI, TA breakdown, conversion funnel, country comparison, countries list
- **Export API**: API key authentication with SHA-256 hashing, daily rate limiting, budget + spend export endpoints
- **Frontend**: New /country page (filters, KPI cards, TA table, funnel, comparison) and /budget page (plan creation, pace badges)
- **Navigation**: Removed /campaigns, added /country and /budget to sidebar
- **Documentation**: Updated CLAUDE.md to v3.1, created parsing-rules.md, platform-rules.md, full specs/ directory
- **Tests**: test_parsing.py, test_budget.py, test_country.py

## Phase 1 — Foundation & Data Pipeline
- Created project structure and documentation
- Implemented 6 SQLAlchemy models (ad_accounts, campaigns, metrics_cache, automation_rules, action_logs, ai_conversations)
- Meta Ads API client with campaign + metrics fetching
- Celery Beat sync every 15 minutes
- Sync engine: normalize Meta data, upsert to DB
- FastAPI core with health check, accounts, and sync endpoints
- Next.js 14 frontend scaffold with App Router
