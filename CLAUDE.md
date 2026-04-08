# Ads Automation Platform

## What This Project Is
Internal marketing ops system for MEANDER Group (6 hotel/restaurant branches).
Consolidates Meta, Google, TikTok Ads with rule automation, budget tracking,
country/TA analytics, AI creative suggestions, and Figma integration.

## Tech Stack
- Backend: Python FastAPI + Celery + Redis
- Frontend: Next.js 14 (TypeScript) + shadcn/ui + Recharts + Tailwind
- Database: PostgreSQL 16 (Zeabur managed)
- External: Claude API, Figma API, Meta/Google/TikTok Ads APIs
- Deployment: Zeabur (all services)

## Architecture Overview
- See docs/specs/api-spec.md for full API specification
- See docs/specs/data-model.md for all table schemas
- See docs/specs/budget-spec.md for Budget module
- See docs/specs/figma-spec.md for Figma integration
- See docs/specs/parsing-spec.md for name parsing rules
- See docs/architecture.md for design decisions

## Critical Rules
- All API responses: { success, data, error, timestamp }
- Never hardcode credentials — always use config.py (Pydantic BaseSettings)
- All monetary values stored in native platform currency
- TA/country/funnel_stage parsed at SYNC TIME — never computed at query time
- Platform separation: Meta logic must NOT be applied to Google/TikTok models
- budget_allocations: NEVER update rows — INSERT new version only
- Figma API calls: always async via Celery — never block request thread
- API keys: store SHA-256 hash only — show plaintext once at creation
- action_logs is IMMUTABLE — never update or delete rows
- JWT stored in httpOnly cookie — never localStorage
- Passwords: bcrypt hash only — never store or log plaintext
- Email send MUST be async via Celery task — never block API response
- Approval state transitions enforced server-side — never trust client status
- All-approve logic: ALL reviewers must approve. ANY reject = REJECTED
- Creator-only launch: verify current_user.id == combo_approval.submitted_by
- Run tests before committing: pytest tests/ -v

## Parsing Conventions (CRITICAL)
- TA: scan campaign name for ['Solo','Couple','Friend','Group','Business']
- Funnel Stage: regex [TOF|MOF|BOF] from campaign name
- Country: adset_name.split('_')[0].upper()[:2]
- Unknown parse -> save as 'Unknown', log warning, never block sync

## Navigation Pages (17 routes)
/, /country, /creative, /approvals, /angles, /keypoints, /ad-research, /rules,
/logs, /insights, /budget, /suggestions, /figma, /accounts, /users, /login

New in Phase 6: /approvals, /approvals/{id}, /approvals/{id}/launch,
/creative/{id}/submit, /users, /login

NOTE: /campaigns is REMOVED — do not recreate it

## Key Commands
- Backend: cd backend && uvicorn app.main:app --reload
- Worker: cd backend && celery -A app.tasks.celery_app worker --loglevel=info
- Frontend: cd frontend && npm run dev
- Tests: cd backend && pytest tests/ -v
- Migration: cd backend && alembic upgrade head

## Current Phase
Phase 6: Combo Approval & Launch System
Auth (JWT + bcrypt), multi-reviewer approval workflow, email + in-system
notifications, Meta Ads launch (existing or auto-create campaign).
5 new tables: users, combo_approvals, approval_reviewers, notifications,
campaign_auto_configs. Migration: 005_approval_system.

## Branches (6 total)
5 hotels + 1 restaurant — each maps to one or more ad_accounts.
- Meander Saigon
- Meander Taipei
- Meander 1948
- Meander Osaka
- Oani (Taipei premium hotel)
- Bread (restaurant)
