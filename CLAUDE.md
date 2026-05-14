# Ads Automation Platform

## What This Project Is
Internal marketing ops system for MEANDER Group (6 hotel/restaurant branches).
Consolidates Meta, Google, TikTok Ads with rule automation, budget tracking,
country/TA analytics, AI creative suggestions, and Figma integration.

## Tech Stack
- Backend: Python FastAPI + Celery + Redis (Zeabur cron is preferred for new
  schedulers — see /api/internal/tasks/* + INTERNAL_TASK_SECRET)
- Frontend: Next.js 14 (TypeScript) + shadcn/ui + Recharts + Tailwind
- Database: PostgreSQL 16 (Supabase managed)
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
/logs, /insights, /budget, /accounts, /users, /login,
/google, /google/pmax, /google/pmax/{id}, /google/search, /google/search/{id}

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
Phase 8: Creative Intelligence (migrations 033-036)
- Canva integration removed; Figma is the variant-generation surface.
- Visual tagging: Claude Sonnet vision scores ad_materials across 7
  dimensions; tags stored on creative_visual_tags.
- Tag search: /api/creative/search filters combos by their material's
  visual tags + optional ILIKE keyword (pure SQL, no embedding provider).
  /api/creative/similar/{combo_id} ranks by shared-tag overlap.
- AI brief generator: /api/creative/brief — given a branch/TA/vibe, emits
  N grounded brief variants + recommended Figma templates.
- Figma surface: /api/figma/templates + /api/figma/jobs. Cron pollers:
  /api/internal/tasks/{vision-tag-materials,figma-job-poll}.
- NOTE: migration 035 added dormant pgvector columns (embedding, embedded_at,
  embedding_model). The Voyage embedding pipeline was dropped — these columns
  are unused; do not wire new code to them.

## Branches (6 total)
5 hotels + 1 restaurant — each maps to one or more ad_accounts.
- Meander Saigon
- Meander Taipei
- Meander 1948
- Meander Osaka
- Oani (Taipei premium hotel)
- Bread (restaurant)
