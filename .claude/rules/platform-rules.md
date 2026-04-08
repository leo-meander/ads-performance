---
globs: ["backend/app/services/meta_*.py", "backend/app/services/google_*.py", "backend/app/services/tiktok_*.py"]
---
# Platform Separation Rules

- Each platform has its own client file: meta_client.py, google_client.py, tiktok_client.py
- NEVER import meta_client logic into google_client or tiktok_client
- ad_combos table is for Meta and TikTok only — Google PMax uses asset_groups (Phase 3)
- Figma export sizes differ by platform: Meta=1080x1080, PMax=multi-size, TikTok=1080x1920
- AI suggestion output schema must include platform field — suggestions are platform-specific
- Dashboard metrics are normalized (spend, ROAS, CTR, CPA) — platform-specific metrics go in raw_data
- /campaigns route is REMOVED — do not reference it in any new code
