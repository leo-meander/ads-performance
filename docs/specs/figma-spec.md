# Figma Integration Specification

## Overview
Figma replaces the old Canva regenerate flow. Designers register **master
template frames**; the backend can list templates, infer their named text
layers, queue **variant jobs**, and export PNG previews via Figma's REST API.

The Figma REST surface is **read-mostly** — it can fetch file structure and
render frames, but cannot overwrite text content from outside the editor.
A variant job's primary artefacts are therefore:

- A **deep-link** the designer opens to apply the request payload manually
- A **rendered PNG preview** of the master template (refreshed by cron)
- (Future) **Figma plugin** auto-fill once we ship the headless plugin

## Tables (migration 036)
- `figma_templates` — Designer-registered master frames
  - `file_key`, `node_id` — Figma identifiers
  - `branch_id` (nullable — shared templates are NULL)
  - `platform`, `width`, `height` — used by the brief generator to match size
  - `placeholder_schema` (JSONB) — named slots, e.g.
    `{"headline": {"type": "text", "max_chars": 60}, "hero_image": {"type": "image"}}`
  - `preview_image_url` — last cron-rendered PNG
- `figma_jobs` — One row per variant request
  - `template_id`, `source_combo_id`
  - `request_payload` (JSONB) — `{slot_name: value}` overrides
  - `status` PENDING → RUNNING → COMPLETED|FAILED
  - `output_figma_url` (deep-link, set at create time)
  - `output_image_url` (PNG, set when cron poller finishes)

## Endpoints
- `GET  /api/figma/templates`              — list (filter by branch/platform)
- `POST /api/figma/templates`              — register a master frame
- `POST /api/figma/templates/{id}/refresh-preview`  — re-export PNG
- `POST /api/figma/jobs`                   — queue a variant request
- `GET  /api/figma/jobs`                   — list (filter by template/status)
- `GET  /api/figma/jobs/{id}`              — detail

## Cron
- `POST /api/internal/tasks/figma-job-poll` — every ~2 min; completes PENDING
  jobs by exporting the master frame as PNG. Bounded — `limit` capped at 50.

## Platform-Specific Sizes (recommended defaults)
- Meta: 1080x1080
- Google PMax: Multi-size (1200x628, 1200x1200, 960x1200)
- TikTok: 1080x1920

## Stub mode
When `FIGMA_ACCESS_TOKEN` is empty the client returns deterministic stub
responses. Tests run end-to-end without OAuth.

## Auth
Set `FIGMA_ACCESS_TOKEN` (Personal Access Token from Figma Account Settings).
For shared org templates, prefer a service-user PAT — Figma's OAuth flow is
not required for read+export usage.
