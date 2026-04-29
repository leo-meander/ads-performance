// English glossary for recommendation rec_type and sop_reference codes.
// Used by InfoTag to show a hover tooltip next to every tag, so ads
// managers who are not SOP-fluent can read what each code means.
// Keep aligned with:
//   backend/app/services/google_recommendations/catalog.py
//   backend/app/services/meta_recommendations/catalog.py
//   backend/app/services/google_recommendations/sop_text.py
//   backend/app/services/meta_recommendations/sop_text.py

export const REC_TYPE_GLOSSARY: Record<string, string> = {
  // ── Google — Part 1 · Demand Gen ────────────────────────
  DG_MISSING_VIDEO:
    "Demand Gen campaign has no real video asset. Google will auto-generate a low-quality video that hurts the brand — upload a real video manually.",
  DG_BIDDING_PHASE1_TCPM:
    "Demand Gen is less than 14 days old but is not on Target CPM. Phase-1 bidding must optimize for reach before conversions.",
  DG_BIDDING_PHASE2_SWITCH:
    "Demand Gen is past the 14-day warm-up. Switch to Maximize Conversions — learning phase resets for 1–2 weeks and CPA may spike temporarily.",
  DG_ATTRIBUTION_LAST_CLICK:
    "Account attribution is still Last Click. Demand Gen touchpoints are undervalued — change to Data-Driven Attribution.",
  DG_FREQUENCY_TOO_HIGH_REMARKETING:
    "Remarketing frequency exceeds 10 per week. System will cap frequency to protect audience quality — reach will drop.",
  DG_FREQUENCY_TOO_HIGH_COLD:
    "Cold-audience frequency exceeds 5 per week. System will cap frequency to avoid audience burn.",
  DG_OPTIMIZED_TARGETING_ON_REMARKETING:
    "Optimized Targeting is ON on a Remarketing campaign — it dilutes the high-value audience pool. System will disable it.",
  DG_VTR_BELOW_BENCHMARK:
    "View-Through Rate is below 30% over the last 14 days. Replace the hook in the first 5 seconds of the video.",
  DG_CTR_BELOW_BENCHMARK:
    "Image/Carousel CTR is below 0.5% over the last 14 days. A/B test new creative.",

  // ── Google — Part 2 · Search + AI Max ───────────────────
  SEARCH_BRAND_MIXED:
    "Branded and non-branded keywords share one campaign — violates Power Pack Rule #1. Manual split required.",
  SEARCH_BRANDED_LOW_IS:
    "Branded Search impression share is below 90%. System will raise the budget 20% to defend brand queries.",
  SEARCH_BRANDED_HAS_BROAD:
    "Branded campaign contains broad match — unsafe. System will pause broad-match keywords; Exact + Phrase stay active.",
  PMAX_MISSING_BRAND_EXCLUSION:
    "PMax has no Brand Exclusion list — it will cannibalize branded traffic and inflate ROAS. Configure the brand list manually.",
  AIMAX_BRAND_NOT_PINNED:
    "Brand name is not pinned to Headline 1. System will pin it — other Headline-1 variants will stop serving.",
  AIMAX_URL_EXPANSION_EARLY:
    "AI Max is less than 14 days old but Final URL Expansion is enabled — risk of traffic going to the wrong pages. System will disable it for the first 2 weeks.",
  AIMAX_SEARCH_TERMS_UNREVIEWED:
    "No AI Max search-term review in the last 7 days. Review weekly and add negatives.",
  AIMAX_ON_BRANDED:
    "AI Max is enabled on a Branded campaign — broad match will dilute brand control. System will disable AI Max immediately.",
  RSA_AD_STRENGTH_POOR:
    "RSA Ad Strength is below Good. Replace low-performing headlines — target Good or Excellent.",
  RSA_INSUFFICIENT_ASSETS:
    "RSA has fewer than 8 headlines, fewer than 3 descriptions, or more than 3 pinned positions. Expand assets and reduce pins.",
  SEARCH_NEGATIVES_MISSING:
    "Detected search terms match SOP exclusion categories (jobs/press/academic/free/cancel) and are not yet negated. System will add them to the shared negative list.",

  // ── Google — Part 3 · Performance Max ───────────────────
  PMAX_ASSET_GROUP_INCOMPLETE:
    "PMax asset group is below the SOP minimum for images, logos, videos, headlines or descriptions. Upload missing assets manually.",
  PMAX_MISSING_AUDIENCE_SIGNAL:
    "PMax asset group has no audience signal attached. Signal accelerates AI learning — attach Customer Match, remarketing, lookalike, or custom-intent.",
  PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH:
    "Bid strategy doesn't match the SOP lifecycle (wk 1-2 Max Conversions, wk 3-6 tCPA +25%, m 2-3 tCPA actual, m 4+ tROAS). Learning phase resets for 1–2 weeks after switching.",
  PMAX_TCPA_CHANGE_TOO_LARGE:
    "tCPA was changed by more than 20% in the last 24 hours — learning phase is already reset. Cannot auto-undo; monitor for 2 weeks before the next change.",
  PMAX_LEARNING_STUCK:
    "PMax has been stuck in learning phase longer than 4 weeks. System will loosen tCPA by +25% to let the AI explore.",
  PMAX_COUNT_VS_SCALE:
    "Number of active PMax campaigns doesn't match the SOP guideline for this hotel's room count. Consolidate or split campaigns manually.",
  PMAX_BRANDED_LEAK:
    "PMax ROAS is more than 2× the account average AND branded Search impressions dropped week-over-week — classic brand-leak pattern. Add a brand exclusion list at account level.",

  // ── Google — Part 4 · Conversion Tracking ───────────────
  CONV_MULTIPLE_PRIMARY:
    "More than one conversion action is marked Primary — bidding is miscalibrated. Keep only Booking Confirmed as Primary; demote others to Secondary.",
  CONV_ENHANCED_DISABLED:
    "Enhanced Conversions is disabled. Enabling captures 10–30% more conversions via hashed first-party data.",
  CONV_ADS_VS_PMS_DELTA:
    "Ads-reported conversions differ from the PMS reservation count by more than 15% over 30 days. Audit tag firing, deduping, and attribution window.",
  CONV_VALUE_MISSING:
    "Booking Confirmed is missing conversion value for 30 days but the campaign is on tROAS. tROAS bidding will malfunction — pass dynamic booking value to the conversion tag.",

  // ── Google — Part 5 · 1st-party Data ────────────────────
  CM_LIST_STALE:
    "Customer Match list was last uploaded more than 35 days ago. Refresh from the PMS to keep signals current.",
  CM_SEGMENTATION_MISSING:
    "Customer Match has no VIP / Recent / Lapsed segments. Segmentation unlocks higher bids for high-value guests.",

  // ── Google — Part 6 · Budget & Seasonality ──────────────
  BUDGET_MIX_OFF_TARGET:
    "30-day spend split across Branded / Non-branded / PMax / Demand Gen is outside SOP bands. System will update daily budgets to the recommended mix; total spend unchanged.",
  SEASONALITY_LEAD_TIME_APPROACHING:
    "A seasonal peak is within its lead-time window and the daily budget has not been raised yet. System will raise the daily budget — AI needs 1–2 weeks to re-learn.",
  SEASONALITY_TCPA_ADJUST_DUE:
    "A seasonal event is active but tCPA is still at baseline. System will adjust tCPA per SOP — will impact learning phase temporarily.",
  LOW_SEASON_SHIFT_TO_DEMANDGEN:
    "Currently in a low-season window and Demand Gen share is below the recommended floor. Reallocate budget toward Demand Gen to warm the audience for the next peak.",
  BUDGET_DAILY_EXHAUSTED_EARLY:
    "PMax daily budget was exhausted before 2pm local on at least 3 of the last 7 days. System will raise the budget by 20%.",

  // ── Google — Part 7 · Daily checks ──────────────────────
  SPEND_VS_BUDGET_ANOMALY:
    "Yesterday's spend deviates from the daily budget by more than 20%. Check budget settings and bid strategy.",
  IMPRESSIONS_DROP_50:
    "Impressions dropped by at least 50% week-over-week. Check auction insights, ad disapprovals, and budget pacing.",
  CTR_SPIKE_100:
    "Yesterday's CTR is more than 2× the 30-day average. Inspect for invalid clicks or unusual placements.",
  ZERO_CONVERSIONS_7D:
    "Zero conversions for 7 consecutive days while spend was non-zero. Likely a broken conversion tag or a landing-page change.",
  POLICY_VIOLATION:
    "Google reports active policy disapprovals. Resolve them today — affected ads will not serve.",

  // ── Meta — Performance critical (Section G.3 / G.4) ─────
  META_BAD_ROAS_7D:
    "Campaign ROAS has trailed its tier benchmark for 7+ consecutive days. Follow Decision Tree 1 — check which component (CR / AOV / CPC) collapsed before pausing or shifting budget.",
  META_LOW_CTR_7D:
    "CTR is below the benchmark for this audience temperature. Tree 2: check frequency > 2.5, placement mix (Audience Network leak), hook strength, and language match before killing the creative.",
  META_HIGH_CTR_LOW_CVR:
    "Clicks are healthy but the 7-day booking conversion rate has dropped to less than half of the campaign's own trailing 30-day baseline. Tree 3: landing-page mismatch, slow mobile load, booking friction, or missing trust signals.",
  META_FREQ_ABOVE_CEILING:
    "Ad frequency exceeds 2.5 per week — creative fatigue threshold. System will pause the ad so the audience can cool down.",

  // ── Meta — Creative fatigue (Section F.6) ───────────────
  META_CTR_DROP_BASELINE:
    "CTR fell more than 25% vs the ad's first-7-day baseline — classic fatigue. Upload 2–4 new creatives against this ad set before scaling.",
  META_CPM_SPIKE:
    "CPM has risen more than 30% without a seasonal event — audience cooling. System will pause this ad; refresh the creative before re-enabling.",
  META_CREATIVE_AGE_30D:
    "Creative has been running 30+ days continuously. Golden Rule #5 — refresh regardless of current performance.",

  // ── Meta — Seasonal (Section H.x.4) ─────────────────────
  META_SEASONAL_BUDGET_BUMP:
    "A hotel peak event is entering its lead-time window for this branch's home country or a targeted inbound country. System will raise daily_budget (capped at the 25%/day rule).",
  META_SEASONAL_BUDGET_CUT:
    "The seasonal window has closed. System will cut daily_budget back toward baseline to avoid over-spending the shoulder period.",
  META_LOW_SEASON_SHIFT:
    "Branch is in a low-season window. Playbook recommends shifting spend from bottom-of-funnel to top-of-funnel awareness to warm up the next peak.",

  // ── Meta — Audience hygiene (Section E.4) ───────────────
  META_MISSING_RECENT_BOOKER_EXCLUSION:
    "Campaign is missing the mandatory exclusion of Purchase events in the last 30 days. Add it manually to avoid re-targeting guests who already booked.",
  META_TEMPERATURE_OVERLAP:
    "Cold prospecting campaign does not exclude warm/hot audiences — risk of double-counting conversions. Add the exclusion list manually.",

  // ── Meta — Branch-level roll-up (Section H.x.3) ─────────
  META_BRANCH_ICP_IMBALANCE:
    "Actual spend distribution across this branch's ICPs is more than 30% off the Section H.x.3 target mix. Rebalance next week's budget manually — auto-apply is not safe here.",
}


export const SOP_REFERENCE_GLOSSARY: Record<string, string> = {
  // ── Google Ads Power Pack SOP sections ──────────────────
  "PART_1.CREATIVE":
    "Demand Gen asset hierarchy — always upload real video (YouTube Shorts 9:16 or in-stream 16:9). Video + Image in one group drives +20% conversion vs. video alone.",
  "PART_1.BIDDING":
    "Demand Gen bidding lifecycle — Phase 1 (weeks 1–2) tCPM for reach; Phase 2 (after 2+ weeks) switch to Maximize Conversions.",
  "PART_1.ATTRIBUTION":
    "Attribution must be Data-Driven, not Last Click. Last Click undervalues Demand Gen touchpoints.",
  "PART_1.FREQUENCY":
    "Frequency benchmarks — Remarketing 3–7/week (act above 10); Cold 1–3/week (act above 5).",
  "PART_1.AUDIENCE":
    "Demand Gen audience priority (Customer Match → booking-page remarketing → lookalikes → custom intent → Optimized Targeting for cold only). NEVER enable Optimized Targeting on Remarketing.",
  "PART_1.KPI":
    "Demand Gen KPIs — in-stream VTR >30% (alert below 20%); image/carousel CTR >0.5% (alert below 0.2%).",
  "PART_2.RULE_1":
    "Rule #1 — Branded and non-branded must run in separate campaigns. Mixing makes ROI measurement impossible and lets PMax steal branded traffic.",
  "PART_2.BRANDED":
    "Branded Search setup — Target IS ≥90% top-of-page, Exact + Phrase only, 24/7, unlimited budget cap. Add brand keywords as negatives on non-branded and PMax.",
  "PART_2.BRAND_EXCLUSION":
    "PMax Brand Exclusion list — cover hotel name and variants, otherwise PMax cannibalizes branded traffic and inflates ROAS.",
  "PART_2.AIMAX":
    "AI Max safe setup — pin brand to Headline 1, turn OFF Final URL Expansion for first 2 weeks, review search terms weekly, never enable AI Max on branded campaigns.",
  "PART_2.RSA":
    "RSA requirements — Ad Strength Good (target Excellent), 8–10 distinct headlines, 3–4 descriptions, no more than 2–3 pins.",
  "PART_2.NEGATIVES":
    "Shared negative list — jobs/career, press/media, academic, free/gratis, cancel/refund/complaint, competitor brand terms. Review weekly in month 1.",
  "PART_3.STRUCTURE":
    "PMax campaign count by hotel scale — <50 rooms: 1 campaign; 50–200 rooms: 1–2; >200 rooms: 2–3 (Regular + Premium + Seasonal).",
  "PART_3.ASSET_COMPLETENESS":
    "PMax asset group minimum per group — ≥1 landscape image, ≥1 square, ≥1 logo, ≥2–3 real videos, ≥3–5 short headlines, ≥1–3 long, ≥2–4 descriptions.",
  "PART_3.AUDIENCE":
    "PMax audience signal priority — Customer Match past guests > high-value guests > booking-page remarketing > all-site remarketing > custom intent > in-market segments.",
  "PART_3.BIDDING":
    "PMax lifecycle — wk 1–2 Max Conversions, wk 3–6 +tCPA 20–30% above actual, m 2–3 tCPA at actual, m 4+ tROAS. Never change bid strategy or tCPA more than 20% in one step.",
  "PART_3.BRAND_SAFETY":
    "Brand leak pattern — PMax ROAS abnormally high AND branded Search impressions drop WoW. Add the brand exclusion list at account level.",
  "PART_4.PRIMARY":
    "Only Booking Confirmed is Primary (account-level). Checkout Initiated / Room Selection / Phone Call / Contact Form are Secondary or Micro.",
  "PART_4.ENHANCED":
    "Enhanced Conversions for web — always enable; captures 10–30% additional conversions via hashed first-party data.",
  "PART_4.RECONCILIATION":
    "Monthly audit — compare Ads-reported bookings vs PMS/channel-manager actuals. <15% delta healthy; above requires a tag audit.",
  "PART_4.VALUE":
    "Dynamic booking value must be passed to Booking Confirmed to support Maximize Conversion Value and tROAS.",
  "PART_5.CUSTOMER_MATCH":
    "Customer Match — refresh monthly from PMS. Segments: VIP (bid +30–50%), Recent (loyalty offer), Lapsed (win-back), One-time (reactivation), Cancellation (exclude).",
  "PART_6.ALLOCATION":
    "Budget allocation — New account (0–6 mo): Branded 10–15% / Non-branded 30–40% / PMax 40–50% / Demand Gen 10–15%. Stable (6+ mo): 5–10 / 25–35 / 40–50 / 15–20.",
  "PART_6.SEASONALITY":
    "Seasonality is per-branch AND per-targeted-country. Events fire when the event country is in the branch's home country or the campaign's targeted countries. Never wait until peak — AI needs 1–2 weeks to re-learn.",
  "PART_6.BUDGET_PACING":
    "Budget pacing — if PMax daily spend exhausts before 2pm local on 3 of the last 7 days, budget is too low for the current tCPA target.",
  "PART_7.DAILY":
    "Daily review (5–10 min) — spend vs daily budget within ±20%, impressions drop >50% alert, CTR spike >100% inspect, zero-conversion 7+ days → tag audit, policy violations resolved same day.",

  // ── Meta Ads Playbook sections ──────────────────────────
  "PLAYBOOK.G.3.ROAS":
    "Decision Tree 1 (Bad ROAS) — ROAS = CVR × AOV / CPC. When it drops, identify which component collapsed before acting. Never kill a creative on one metric.",
  "PLAYBOOK.G.3.CTR":
    "Decision Tree 2 (Low CTR / Expensive Clicks) — check frequency > 2.5 (fatigue), placement mix (restrict Audience Network), audience temperature benchmarks, hook strength, language match.",
  "PLAYBOOK.G.3.CVR":
    "Decision Tree 3 (High CTR / Low CVR) — landing-page mismatch is most common. Check mobile load >3s, booking friction, missing trust signals, mobile-vs-desktop CR gap.",
  "PLAYBOOK.G.4.ATTRIBUTION":
    "Golden Rule #7 — do not trust Meta's in-platform ROAS alone. Reconcile weekly against actual PMS/OTA bookings.",
  "PLAYBOOK.F.6.FREQUENCY":
    "Creative refresh trigger — frequency above 2.5 within a 7-day window at the ad level. Pause and rotate.",
  "PLAYBOOK.F.6.CTR_DROP":
    "Creative refresh trigger — CTR drops more than 25% vs the ad's first-7-day baseline. Upload 2–4 new creatives.",
  "PLAYBOOK.F.6.CPM_SPIKE":
    "Creative refresh trigger — CPM rises more than 30% without a clear external cause. If no seasonal event is active, rotate creative.",
  "PLAYBOOK.F.6.AGE":
    "Creative refresh trigger — same creative running 30+ days. Golden Rule #5: refresh regardless of current performance.",
  "PLAYBOOK.SEASONAL.BUMP":
    "Seasonal event entering lead-time window is a budget-bump trigger. Cap the one-day increase at Golden Rule #4 (25%) — split larger raises across multiple days.",
  "PLAYBOOK.SEASONAL.CUT":
    "After a peak ends, cut budget back toward baseline. Max one-day decrease up to 25%; sudden 50%+ cuts can also reset learning.",
  "PLAYBOOK.SEASONAL.LOW_SEASON":
    "Low-season window — shift spend from bottom-of-funnel to top-of-funnel awareness. The 20/30/50 TOF/MOF/BOF split tilts to roughly 40/30/30.",
  "PLAYBOOK.E.4.EXCL":
    "Mandatory exclusion — Purchase event in last 30 days (recent bookers). Re-targeting just-booked guests burns money and annoys them.",
  "PLAYBOOK.E.4.TEMP":
    "Cold prospecting campaigns must exclude warm and hot audiences; warm campaigns must exclude hot. Avoids double-counting conversions and distorting the bid.",
  "PLAYBOOK.H.X.3.MIX":
    "Each branch has a playbook-defined monthly budget distribution across its ICPs (Section H.1.3 / H.2.3 / …). If actual spend drifts more than 30% from the target, rebalance next week.",
}


export function describeRecType(code: string): string {
  return (
    REC_TYPE_GLOSSARY[code] ??
    "No description available for this recommendation code yet."
  )
}

export function describeSopReference(code: string): string {
  return (
    SOP_REFERENCE_GLOSSARY[code] ??
    "No description available for this playbook section yet."
  )
}
