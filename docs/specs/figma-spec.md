# Figma Integration Specification (Phase 6)

## Overview
Figma integration enables automated creative generation using Figma templates.
This is planned for Phase 6 — this spec is a placeholder.

## Planned Tables
- `figma_templates` — Template metadata + Figma file IDs
- `figma_jobs` — Generation job queue with status tracking

## Planned Endpoints
- `GET /api/figma/templates` — List available templates
- `POST /api/figma/generate` — Queue creative generation job (async via Celery)
- `GET /api/figma/jobs/{id}` — Check job status

## Platform-Specific Sizes
- Meta: 1080x1080
- Google PMax: Multi-size (1200x628, 1200x1200, 960x1200)
- TikTok: 1080x1920

## Rules
- All Figma API calls must be async via Celery — never block request thread
- Template variables are stored as JSONB for flexibility
