# Name Parsing Specification

## Overview
The parsing engine extracts structured metadata from campaign and adset names at sync time.
Parsed values are stored directly on the database row — never computed at query time.

## Parsing Rules

### Campaign Name → TA + Funnel Stage

**Examples:**
```
Mason_TPE_[TOF] Landing page Solo UK       → TA: Solo,    Funnel: TOF
Mason_OSK_[TOF] Sales_Landing Page Couple   → TA: Couple,  Funnel: TOF
Mason_SGN_[MOF] Retargeting Friend VN       → TA: Friend,  Funnel: MOF
```

**TA** — whitelist keyword scan (case-insensitive, first match wins):
```python
TA_WHITELIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']
ta = next((t for t in TA_WHITELIST if t.lower() in name.lower()), 'Unknown')
```

**Funnel Stage** — bracket pattern match:
```python
import re
match = re.search(r'\[(TOF|MOF|BOF)\]', name, re.IGNORECASE)
funnel_stage = match.group(1).upper() if match else 'Unknown'
```

| Value | Meaning |
|-------|---------|
| TOF | Top of Funnel (cold audience) |
| MOF | Middle of Funnel (remarketing) |
| BOF | Bottom of Funnel (future — parse ready) |
| Unknown | No bracket tag found — flag in dashboard |

### Adset Name → Country

**Examples:**
```
TW_25_M&F_ZH_Broad     → Country: TW
AU_25-44_M&F_New LP     → Country: AU
JP_25-44_M&F_ENG        → Country: JP
SG_25-34_M&F_ENG        → Country: SG
US_25-44_M&F_Lookalike  → Country: US
```

**Country** — always first segment before underscore:
```python
country = adset_name.split('_')[0].upper()[:2]  # Always 2 chars
```

Country stored as ISO 3166-1 alpha-2. No lookup table needed.

## Where Parsing Runs

Parsing runs inside sync_engine.py at upsert time:
1. `sync_engine.py` calls `parse_campaign_metadata(campaign_name)` before upsert
2. `sync_engine.py` calls `parse_adset_metadata(adset_name)` before upsert
3. Parsed values stored on `campaigns.ta`, `campaigns.funnel_stage`, `ad_sets.country`
4. If parsing fails (Unknown) → row saved with Unknown + logged for review

## Failure Handling

- Unknown TA → save as `'Unknown'`, log warning, never raise exception
- Unknown funnel stage → save as `'Unknown'`, log warning
- Empty/null name → save as `'Unknown'` for all fields
- Re-parse via `POST /api/sync/reparse` if naming convention changes

## Re-parse Endpoint

```
POST /api/sync/reparse
Body: { "scope": "all" | "campaigns" | "adsets", "account_id": optional }
→ Reads all existing names, re-runs parser, updates ta/funnel_stage/country
→ Returns: { "reparsed": 234, "unknown_ta": 12, "unknown_country": 3 }
```
