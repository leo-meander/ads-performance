# Data Model Specification

## Overview
The Ads Automation Platform uses PostgreSQL 16 with 17 tables organized into 5 domains:
- **Ad Hierarchy**: ad_accounts, campaigns, ad_sets, ads
- **Creative Library**: ad_angles, ad_copies, ad_materials, ad_combos, branch_keypoints
- **Metrics & Automation**: metrics_cache, automation_rules, action_logs
- **AI**: ai_conversations
- **Phase 5 additions**: budget_plans, budget_allocations, api_keys

All tables use UUID primary keys, created_at/updated_at timestamps.

---

## Ad Hierarchy Tables

### ad_accounts
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK, default gen_random_uuid() |
| platform | VARCHAR(20) | NOT NULL, indexed (meta/google/tiktok) |
| account_id | VARCHAR(100) | NOT NULL, UNIQUE |
| account_name | VARCHAR(200) | NOT NULL |
| currency | VARCHAR(3) | NOT NULL, default 'VND' |
| is_active | BOOLEAN | NOT NULL, default TRUE |
| access_token_enc | TEXT | Encrypted access token |
| created_at | TIMESTAMPTZ | NOT NULL, server default |
| updated_at | TIMESTAMPTZ | NOT NULL, server default + onupdate |

### campaigns
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| account_id | UUID | FK → ad_accounts.id ON DELETE CASCADE, indexed |
| platform | VARCHAR(20) | NOT NULL, indexed |
| platform_campaign_id | VARCHAR(100) | NOT NULL, UNIQUE |
| name | VARCHAR(500) | NOT NULL |
| status | VARCHAR(30) | NOT NULL, indexed (ACTIVE/PAUSED/ARCHIVED) |
| objective | VARCHAR(100) | |
| daily_budget | NUMERIC(15,2) | |
| lifetime_budget | NUMERIC(15,2) | |
| start_date | DATE | |
| end_date | DATE | |
| ta | VARCHAR(50) | **Phase 5** — Parsed target audience (Solo/Couple/Friend/Group/Business/Unknown) |
| funnel_stage | VARCHAR(10) | **Phase 5** — Parsed funnel stage (TOF/MOF/BOF/Unknown) |
| raw_data | JSONB | Raw API response |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Indexes**: idx_campaigns_ta, idx_campaigns_funnel_stage

### ad_sets
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| campaign_id | UUID | FK → campaigns.id ON DELETE CASCADE, indexed |
| account_id | UUID | FK → ad_accounts.id ON DELETE CASCADE, indexed |
| platform | VARCHAR(20) | NOT NULL, indexed |
| platform_adset_id | VARCHAR(100) | NOT NULL, UNIQUE |
| name | VARCHAR(500) | NOT NULL |
| status | VARCHAR(30) | NOT NULL, indexed |
| optimization_goal | VARCHAR(100) | |
| billing_event | VARCHAR(50) | |
| daily_budget | NUMERIC(15,2) | |
| lifetime_budget | NUMERIC(15,2) | |
| targeting | JSONB | |
| start_date | DATE | |
| end_date | DATE | |
| country | VARCHAR(2) | **Phase 5** — ISO 3166-1 alpha-2, parsed from name |
| raw_data | JSONB | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Indexes**: idx_ad_sets_country, idx_adsets_country_platform (composite)

### ads
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| ad_set_id | UUID | FK → ad_sets.id ON DELETE CASCADE, indexed |
| campaign_id | UUID | FK → campaigns.id ON DELETE CASCADE, indexed |
| account_id | UUID | FK → ad_accounts.id ON DELETE CASCADE, indexed |
| platform | VARCHAR(20) | NOT NULL, indexed |
| platform_ad_id | VARCHAR(100) | NOT NULL, UNIQUE |
| name | VARCHAR(500) | NOT NULL |
| status | VARCHAR(30) | NOT NULL, indexed |
| creative_id | VARCHAR(100) | |
| raw_data | JSONB | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

---

## Creative Library Tables

### ad_angles
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| branch_id | UUID | FK → ad_accounts.id |
| angle_id | VARCHAR(20) | UNIQUE (ANG-001 format) |
| angle_type | VARCHAR(100) | NOT NULL |
| angle_explain | TEXT | |
| hook_examples | JSONB | Array of example hooks |
| status | VARCHAR(10) | WIN/TEST/LOSE |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### ad_copies
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| branch_id | UUID | FK → ad_accounts.id |
| copy_id | VARCHAR(20) | UNIQUE (CPY-001 format) |
| target_audience | VARCHAR(100) | |
| angle_id | UUID | FK → ad_angles.id |
| headline | TEXT | |
| body_text | TEXT | |
| cta | VARCHAR(100) | |
| language | VARCHAR(10) | |
| derived_verdict | VARCHAR(10) | WIN/TEST/LOSE |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### ad_materials
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| branch_id | UUID | FK → ad_accounts.id |
| material_id | VARCHAR(20) | UNIQUE (MAT-001 format) |
| material_type | VARCHAR(20) | image/video/carousel |
| file_url | TEXT | |
| description | TEXT | |
| target_audience | VARCHAR(100) | |
| derived_verdict | VARCHAR(10) | WIN/TEST/LOSE |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### ad_combos
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| branch_id | UUID | FK → ad_accounts.id |
| combo_id | VARCHAR(20) | UNIQUE (CMB-001 format) |
| ad_name | VARCHAR(500) | |
| target_audience | VARCHAR(100) | |
| country | VARCHAR(2) | |
| keypoint_ids | JSONB | Array of keypoint UUIDs |
| angle_id | UUID | FK → ad_angles.id |
| copy_id | UUID | FK → ad_copies.id |
| material_id | UUID | FK → ad_materials.id |
| campaign_id | UUID | FK → campaigns.id |
| spend | NUMERIC(15,2) | |
| impressions | INTEGER | |
| clicks | INTEGER | |
| conversions | INTEGER | |
| revenue | NUMERIC(15,2) | |
| roas | NUMERIC(10,4) | |
| cost_per_purchase | NUMERIC(15,2) | |
| ctr | NUMERIC(8,4) | |
| video_plays | INTEGER | |
| thruplay | INTEGER | |
| hook_rate | NUMERIC(8,4) | |
| thruplay_rate | NUMERIC(8,4) | |
| video_complete_rate | NUMERIC(8,4) | |
| verdict | VARCHAR(10) | WIN/TEST/LOSE |
| verdict_source | VARCHAR(10) | manual/auto |
| notes | TEXT | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### branch_keypoints
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| branch_id | UUID | FK → ad_accounts.id |
| category | VARCHAR(20) | location/amenity/experience/value |
| title | VARCHAR(200) | NOT NULL |
| description | TEXT | |
| is_active | BOOLEAN | default TRUE |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

---

## Metrics & Automation Tables

### metrics_cache
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| campaign_id | UUID | FK → campaigns.id ON DELETE CASCADE |
| ad_set_id | UUID | FK → ad_sets.id ON DELETE SET NULL, optional |
| ad_id | UUID | FK → ads.id ON DELETE SET NULL, optional |
| platform | VARCHAR(20) | NOT NULL |
| date | DATE | NOT NULL, indexed |
| spend | NUMERIC(15,2) | default 0 |
| impressions | INTEGER | default 0 |
| clicks | INTEGER | default 0 |
| conversions | INTEGER | default 0 |
| revenue | NUMERIC(15,2) | default 0 |
| roas | NUMERIC(10,4) | default 0 |
| cpa | NUMERIC(15,2) | default 0 |
| cpc | NUMERIC(15,2) | default 0 |
| ctr | NUMERIC(8,4) | default 0 |
| frequency | NUMERIC(8,4) | default 0 |
| add_to_cart | INTEGER | default 0 |
| checkouts | INTEGER | default 0 |
| searches | INTEGER | default 0 |
| leads | INTEGER | default 0 |
| landing_page_views | INTEGER | default 0 |
| computed_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Indexes**: idx_metrics_cache_date

### automation_rules
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| name | VARCHAR(200) | NOT NULL |
| platform | VARCHAR(20) | NOT NULL |
| account_id | UUID | FK → ad_accounts.id |
| entity_level | VARCHAR(20) | campaign/ad_set/ad |
| conditions | JSONB | [{metric, operator, threshold}] |
| action | VARCHAR(50) | pause_campaign/enable_campaign/etc |
| action_params | JSONB | |
| is_active | BOOLEAN | default TRUE |
| last_evaluated_at | TIMESTAMPTZ | |
| created_by | VARCHAR(100) | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### action_logs (IMMUTABLE)
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| rule_id | UUID | FK → automation_rules.id ON DELETE SET NULL |
| campaign_id | UUID | FK → campaigns.id ON DELETE SET NULL |
| ad_set_id | UUID | FK → ad_sets.id ON DELETE SET NULL |
| ad_id | UUID | FK → ads.id ON DELETE SET NULL |
| platform | VARCHAR(20) | |
| action | VARCHAR(50) | NOT NULL |
| action_params | JSONB | |
| triggered_by | VARCHAR(20) | rule/manual/api |
| metrics_snapshot | JSONB | |
| success | BOOLEAN | NOT NULL |
| error_message | TEXT | |
| executed_at | TIMESTAMPTZ | NOT NULL |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

---

## AI Table

### ai_conversations
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| session_id | VARCHAR(100) | NOT NULL, indexed |
| role | VARCHAR(20) | user/assistant |
| content | TEXT | NOT NULL |
| platform_filter | VARCHAR(20) | |
| date_filter_from | DATE | |
| date_filter_to | DATE | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

---

## Phase 5 Tables

### budget_plans
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| name | VARCHAR(200) | NOT NULL |
| branch | VARCHAR(100) | NOT NULL (Saigon/Taipei/1948/Osaka/Oani/Bread) |
| channel | VARCHAR(20) | NOT NULL (meta/google/tiktok) |
| month | DATE | NOT NULL (first day of month) |
| total_budget | NUMERIC(15,2) | NOT NULL |
| currency | VARCHAR(3) | NOT NULL, default 'VND' |
| notes | TEXT | |
| is_active | BOOLEAN | default TRUE |
| created_by | VARCHAR(100) | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Unique**: (branch, channel, month) — one plan per branch/channel/month

### budget_allocations
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| plan_id | UUID | FK → budget_plans.id ON DELETE CASCADE |
| campaign_id | UUID | FK → campaigns.id ON DELETE SET NULL, optional |
| amount | NUMERIC(15,2) | NOT NULL |
| version | INTEGER | NOT NULL, default 1 |
| reason | TEXT | Why this allocation/reallocation |
| created_by | VARCHAR(100) | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Rule**: NEVER UPDATE — always INSERT new row with incremented version.

### api_keys
| Column | Type | Constraints |
|--------|------|------------|
| id | UUID | PK |
| name | VARCHAR(200) | NOT NULL |
| key_hash | VARCHAR(64) | NOT NULL, UNIQUE (SHA-256 hex) |
| key_prefix | VARCHAR(8) | NOT NULL (first 8 chars for identification) |
| is_active | BOOLEAN | default TRUE |
| last_used_at | TIMESTAMPTZ | |
| daily_request_count | INTEGER | default 0 |
| daily_count_reset_at | DATE | |
| created_by | VARCHAR(100) | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

---

## Indexes (Phase 5 additions)

```sql
CREATE INDEX idx_campaigns_ta ON campaigns(ta);
CREATE INDEX idx_campaigns_funnel_stage ON campaigns(funnel_stage);
CREATE INDEX idx_ad_sets_country ON ad_sets(country);
CREATE INDEX idx_metrics_cache_date ON metrics_cache(date);
CREATE INDEX idx_adsets_country_platform ON ad_sets(country, platform);
CREATE INDEX idx_budget_plans_branch_month ON budget_plans(branch, month);
CREATE INDEX idx_budget_allocations_plan_id ON budget_allocations(plan_id);
```
