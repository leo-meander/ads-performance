---
globs: ["backend/app/services/parse_utils.py", "backend/app/services/sync_engine.py"]
---
# Name Parsing Rules

- TA_WHITELIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business'] — exact list, no additions without approval
- Funnel stage regex: \[(TOF|MOF|BOF)\] — case-insensitive, bracket required
- Country: always adset_name.split('_')[0].upper()[:2] — first segment only
- Unknown parse results: save value as 'Unknown', log to sync_warnings, never raise exception
- Parsing runs at upsert time in sync_engine — NEVER at query time
- Re-parse endpoint must update existing rows, not create duplicates
- MOF funnel_stage = remarketing audience — this affects AI suggestion context
- BOF is valid future value — parser already handles it, do not add special cases
