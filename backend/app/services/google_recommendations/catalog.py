"""Recommendation type catalog.

Single source of truth for every rec_type produced by detectors. Drives:
- detector self-registration (catalog spec populates class attributes)
- frontend label map (rec_type → title template)
- applier dispatch (auto_applicable gate)
- migration / seeding sanity checks

Keep this file aligned with the SOP (Google_Ads_Power_Pack_Hotel_SOP.docx)
and the plan at ~/.claude/plans/ (Section 10, Rec Type Catalog).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecTypeSpec:
    rec_type: str
    severity: str  # critical | warning | info
    cadence: str  # daily | weekly | monthly | seasonality
    sop_reference: str
    auto_applicable: bool
    default_title: str
    warning_template: str


# Short aliases for readability.
_CRIT, _WARN, _INFO = "critical", "warning", "info"
_DAILY, _WEEKLY, _MONTHLY, _SEASON = "daily", "weekly", "monthly", "seasonality"


CATALOG: dict[str, RecTypeSpec] = {spec.rec_type: spec for spec in [
    # ── Part 1 — Demand Gen ───────────────────────────────────
    RecTypeSpec(
        "DG_MISSING_VIDEO", _CRIT, _WEEKLY, "PART_1.CREATIVE", False,
        "Demand Gen campaign has no video asset",
        "Demand Gen has no video asset. Google will auto-generate low-quality video that hurts the brand. "
        "Upload a real video manually — this recommendation is guidance only.",
    ),
    RecTypeSpec(
        "DG_BIDDING_PHASE1_TCPM", _WARN, _WEEKLY, "PART_1.BIDDING", False,
        "Demand Gen should be on tCPM in phase 1",
        "Demand Gen is less than 14 days old and not on Target CPM. Phase-1 bidding must optimize for reach "
        "before conversions. Switch manually to tCPM in Google Ads.",
    ),
    RecTypeSpec(
        "DG_BIDDING_PHASE2_SWITCH", _WARN, _WEEKLY, "PART_1.BIDDING", True,
        "Move Demand Gen to Maximize Conversions",
        "System will switch bidding to Maximize Conversions now that the warm-up window has passed. "
        "Learning phase resets for 1–2 weeks — CPA may spike temporarily. Confirm?",
    ),
    RecTypeSpec(
        "DG_ATTRIBUTION_LAST_CLICK", _CRIT, _MONTHLY, "PART_1.ATTRIBUTION", False,
        "Attribution model is still Last Click",
        "Account attribution is Last Click. Demand Gen will be undervalued and budget will drain toward lower-funnel "
        "campaigns. Change to Data-Driven Attribution in Google Ads > Tools > Attribution.",
    ),
    RecTypeSpec(
        "DG_FREQUENCY_TOO_HIGH_REMARKETING", _WARN, _WEEKLY, "PART_1.FREQUENCY", True,
        "Remarketing frequency is above SOP ceiling",
        "Remarketing frequency exceeds 10 per week. System will cap frequency to protect audience quality. "
        "Reach will drop; monitor for 7 days.",
    ),
    RecTypeSpec(
        "DG_FREQUENCY_TOO_HIGH_COLD", _WARN, _WEEKLY, "PART_1.FREQUENCY", True,
        "Cold-audience frequency is above SOP ceiling",
        "Cold-audience frequency exceeds 5 per week. System will cap frequency to avoid burn. "
        "Expand audience or rotate creative after 7 days if reach stays flat.",
    ),
    RecTypeSpec(
        "DG_OPTIMIZED_TARGETING_ON_REMARKETING", _CRIT, _WEEKLY, "PART_1.AUDIENCE", True,
        "Optimized Targeting is ON for Remarketing",
        "Optimized Targeting is enabled on a Remarketing campaign — it dilutes high-value audience pools. "
        "System will disable it immediately. Audience will contract.",
    ),
    RecTypeSpec(
        "DG_VTR_BELOW_BENCHMARK", _WARN, _WEEKLY, "PART_1.KPI", False,
        "Demand Gen VTR is below benchmark",
        "View-Through Rate is below 30% over the last 14 days. Replace the hook in the first 5 seconds of video.",
    ),
    RecTypeSpec(
        "DG_CTR_BELOW_BENCHMARK", _INFO, _WEEKLY, "PART_1.KPI", False,
        "Demand Gen CTR is below benchmark",
        "Image/Carousel CTR is below 0.5% over the last 14 days. A/B test new creative.",
    ),

    # ── Part 2 — Search + AI Max ──────────────────────────────
    RecTypeSpec(
        "SEARCH_BRAND_MIXED", _CRIT, _WEEKLY, "PART_2.RULE_1", False,
        "Branded and non-branded keywords are mixed",
        "Branded and non-branded keywords share one campaign — violates Power Pack Rule #1. "
        "Manual split required; the system cannot auto-split campaigns.",
    ),
    RecTypeSpec(
        "SEARCH_BRANDED_LOW_IS", _WARN, _WEEKLY, "PART_2.BRANDED", True,
        "Branded impression share below 90%",
        "Branded Search impression share is below 90%. System will raise the budget 20% to defend brand queries. "
        "Monitor for competitor bidding.",
    ),
    RecTypeSpec(
        "SEARCH_BRANDED_HAS_BROAD", _WARN, _WEEKLY, "PART_2.BRANDED", True,
        "Branded campaign contains broad match",
        "Broad match is not safe on branded campaigns. System will pause broad-match keywords. "
        "Exact + Phrase stay active.",
    ),
    RecTypeSpec(
        "PMAX_MISSING_BRAND_EXCLUSION", _CRIT, _WEEKLY, "PART_2.BRAND_EXCLUSION", False,
        "PMax is missing a Brand Exclusion list",
        "PMax has no Brand Exclusion — it will cannibalize branded traffic and inflate ROAS. "
        "Configure the brand list manually in Google Ads > Shared Library > Brand lists.",
    ),
    RecTypeSpec(
        "AIMAX_BRAND_NOT_PINNED", _CRIT, _WEEKLY, "PART_2.AIMAX", True,
        "Brand name is not pinned to Headline 1",
        "System will pin the brand name to Headline position 1. Other Headline-1 variants will stop serving.",
    ),
    RecTypeSpec(
        "AIMAX_URL_EXPANSION_EARLY", _WARN, _WEEKLY, "PART_2.AIMAX", True,
        "Final URL Expansion is on too early",
        "AI Max is less than 14 days old and Final URL Expansion is enabled — risk of traffic going to wrong pages. "
        "System will disable URL Expansion for the first 2 weeks.",
    ),
    RecTypeSpec(
        "AIMAX_SEARCH_TERMS_UNREVIEWED", _INFO, _WEEKLY, "PART_2.AIMAX", False,
        "AI Max search-terms not reviewed this week",
        "No search-term review activity in the last 7 days. Review weekly and add negatives.",
    ),
    RecTypeSpec(
        "AIMAX_ON_BRANDED", _CRIT, _WEEKLY, "PART_2.AIMAX", True,
        "AI Max is enabled on a Branded campaign",
        "AI Max is on a branded campaign — broad match will dilute brand control and may generate off-voice headlines. "
        "System will disable AI Max immediately.",
    ),
    RecTypeSpec(
        "RSA_AD_STRENGTH_POOR", _WARN, _WEEKLY, "PART_2.RSA", False,
        "RSA Ad Strength is Poor/Average",
        "Ad Strength is below Good. Replace low-performing headlines; target Good or Excellent.",
    ),
    RecTypeSpec(
        "RSA_INSUFFICIENT_ASSETS", _WARN, _WEEKLY, "PART_2.RSA", False,
        "RSA has too few assets or too many pins",
        "RSA has fewer than 8 headlines, fewer than 3 descriptions, or more than 3 pinned positions. "
        "Expand assets and reduce pins to give the AI room to test.",
    ),
    RecTypeSpec(
        "SEARCH_NEGATIVES_MISSING", _WARN, _WEEKLY, "PART_2.NEGATIVES", True,
        "Missing negative keywords from SOP categories",
        "Detected search terms match SOP exclusion categories (jobs/press/academic/free/cancel) and are not yet negated. "
        "System will add them to the shared negative list. Review the list — you may block legitimate traffic.",
    ),

    # ── Part 3 — Performance Max ──────────────────────────────
    RecTypeSpec(
        "PMAX_ASSET_GROUP_INCOMPLETE", _CRIT, _WEEKLY, "PART_3.ASSET_COMPLETENESS", False,
        "PMax asset group is below minimum assets",
        "Asset group has fewer images, logos, videos, headlines or descriptions than the SOP minimum. "
        "Upload the missing assets manually — auto-generated media will look bad.",
    ),
    RecTypeSpec(
        "PMAX_MISSING_AUDIENCE_SIGNAL", _WARN, _WEEKLY, "PART_3.AUDIENCE", False,
        "PMax asset group has no audience signal",
        "No Customer Match, remarketing list, lookalike, or custom-intent is attached. Signal accelerates AI learning — "
        "attach at least one list.",
    ),
    RecTypeSpec(
        "PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH", _WARN, _WEEKLY, "PART_3.BIDDING", True,
        "Bid strategy does not match campaign lifecycle",
        "Campaign age and current bid strategy don't match the SOP lifecycle "
        "(wk 1-2 Max Conversions, wk 3-6 tCPA +25%, m 2-3 tCPA actual, m 4+ tROAS). "
        "System will switch strategy. Learning phase resets for 1–2 weeks.",
    ),
    RecTypeSpec(
        "PMAX_TCPA_CHANGE_TOO_LARGE", _CRIT, _DAILY, "PART_3.BIDDING", False,
        "tCPA was just changed by more than 20%",
        "tCPA was changed more than 20% in the last 24 hours — learning phase is already reset. "
        "System cannot auto-undo. Monitor performance for 2 weeks before the next change.",
    ),
    RecTypeSpec(
        "PMAX_LEARNING_STUCK", _WARN, _WEEKLY, "PART_3.BIDDING", True,
        "PMax is stuck in learning phase over 4 weeks",
        "Learning phase has lasted longer than 4 weeks. System will loosen tCPA by +25% to let the AI explore. "
        "If no improvement after 14 days, add micro-conversions.",
    ),
    RecTypeSpec(
        "PMAX_COUNT_VS_SCALE", _INFO, _MONTHLY, "PART_3.STRUCTURE", False,
        "Number of PMax campaigns does not match hotel scale",
        "The number of active PMax campaigns doesn't match the SOP guideline for this hotel's room count. "
        "Consolidate or split campaigns manually.",
    ),
    RecTypeSpec(
        "PMAX_BRANDED_LEAK", _CRIT, _WEEKLY, "PART_3.BRAND_SAFETY", False,
        "PMax is cannibalizing branded traffic",
        "PMax ROAS is more than 2× the account average AND branded Search impressions dropped week-over-week — "
        "classic brand-leak pattern. Add a brand exclusion list at the account level in Google Ads UI.",
    ),

    # ── Part 4 — Conversion Tracking ──────────────────────────
    RecTypeSpec(
        "CONV_MULTIPLE_PRIMARY", _CRIT, _MONTHLY, "PART_4.PRIMARY", False,
        "Multiple conversion actions are set as Primary",
        "More than one conversion action is marked Primary — bidding is miscalibrated. "
        "Keep only 'Booking Confirmed' as Primary; demote others to Secondary.",
    ),
    RecTypeSpec(
        "CONV_ENHANCED_DISABLED", _WARN, _MONTHLY, "PART_4.ENHANCED", False,
        "Enhanced Conversions is disabled",
        "Enhanced Conversions captures 10–30% more conversions via hashed first-party data. "
        "Enable in Google Ads > Tools > Conversions > Enhanced conversions.",
    ),
    RecTypeSpec(
        "CONV_ADS_VS_PMS_DELTA", _WARN, _MONTHLY, "PART_4.RECONCILIATION", False,
        "Ads vs PMS booking count delta is above 15%",
        "Ads-reported conversions differ from PMS reservation count by more than 15% over 30 days. "
        "Audit tag firing, deduping, and attribution window.",
    ),
    RecTypeSpec(
        "CONV_VALUE_MISSING", _CRIT, _MONTHLY, "PART_4.VALUE", False,
        "Booking Confirmed is missing conversion value",
        "Conversion value is NULL on Booking Confirmed for 30 days but the campaign is on tROAS. "
        "tROAS bidding will malfunction. Pass dynamic booking value to the conversion tag.",
    ),

    # ── Part 5 — 1st-party Data ───────────────────────────────
    RecTypeSpec(
        "CM_LIST_STALE", _WARN, _MONTHLY, "PART_5.CUSTOMER_MATCH", False,
        "Customer Match list is stale",
        "Customer Match list was last uploaded more than 35 days ago. Refresh from the PMS to keep signals current.",
    ),
    RecTypeSpec(
        "CM_SEGMENTATION_MISSING", _INFO, _MONTHLY, "PART_5.CUSTOMER_MATCH", False,
        "Customer Match has no VIP/Recent/Lapsed segments",
        "Segmentation unlocks higher bids for high-value guests. Create VIP / Recent / Lapsed segments and upload.",
    ),

    # ── Part 6 — Budget & Seasonality ─────────────────────────
    RecTypeSpec(
        "BUDGET_MIX_OFF_TARGET", _WARN, _MONTHLY, "PART_6.ALLOCATION", True,
        "Budget allocation deviates from SOP",
        "30-day spend split across Branded / Non-branded / PMax / Demand Gen is outside SOP bands. "
        "System will update daily budgets to the recommended mix. Total spend unchanged.",
    ),
    RecTypeSpec(
        "SEASONALITY_LEAD_TIME_APPROACHING", _CRIT, _SEASON, "PART_6.SEASONALITY", True,
        "Seasonal event approaching — budget not yet lifted",
        "A seasonal peak is within its lead-time window and the daily budget has not been raised yet. "
        "System will raise the daily budget. AI needs 1–2 weeks to re-learn — do not wait for peak.",
    ),
    RecTypeSpec(
        "SEASONALITY_TCPA_ADJUST_DUE", _WARN, _SEASON, "PART_6.SEASONALITY", True,
        "Seasonal event active — tCPA still at baseline",
        "A seasonal event is active but tCPA is still at baseline. System will adjust tCPA per SOP. "
        "Will impact learning phase temporarily.",
    ),
    RecTypeSpec(
        "LOW_SEASON_SHIFT_TO_DEMANDGEN", _INFO, _SEASON, "PART_6.SEASONALITY", False,
        "Low season — shift budget toward Demand Gen",
        "Currently in a low-season window. Demand Gen share is below the recommended floor. "
        "Reallocate budget toward Demand Gen to warm the audience for the next peak.",
    ),
    RecTypeSpec(
        "BUDGET_DAILY_EXHAUSTED_EARLY", _WARN, _DAILY, "PART_6.BUDGET_PACING", True,
        "PMax daily budget exhausted before 2pm",
        "Daily budget was exhausted before 2pm local on at least 3 of the last 7 days. "
        "System will raise the budget by 20%. Monitor ROAS for 7 days.",
    ),

    # ── Part 7 — Daily checks ────────────────────────────────
    RecTypeSpec(
        "SPEND_VS_BUDGET_ANOMALY", _WARN, _DAILY, "PART_7.DAILY", False,
        "Spend deviates from daily budget by more than 20%",
        "Yesterday's spend deviates from the daily budget by more than 20%. Check budget settings and bid strategy.",
    ),
    RecTypeSpec(
        "IMPRESSIONS_DROP_50", _CRIT, _DAILY, "PART_7.DAILY", False,
        "Impressions dropped 50% week-over-week",
        "Impressions dropped by at least 50% week-over-week. Check auction insights, ad disapprovals, and budget pacing.",
    ),
    RecTypeSpec(
        "CTR_SPIKE_100", _INFO, _DAILY, "PART_7.DAILY", False,
        "CTR spiked more than 100% above 30-day average",
        "Yesterday's CTR is more than 2× the 30-day average. Inspect for invalid clicks or unusual placements.",
    ),
    RecTypeSpec(
        "ZERO_CONVERSIONS_7D", _CRIT, _DAILY, "PART_7.DAILY", False,
        "Zero conversions for seven consecutive days",
        "Zero conversions for 7 consecutive days while spend > 0. Likely broken conversion tag or landing-page change.",
    ),
    RecTypeSpec(
        "POLICY_VIOLATION", _CRIT, _DAILY, "PART_7.DAILY", False,
        "Ads have policy violations",
        "Google reports active policy disapprovals. Resolve them today — affected ads will not serve.",
    ),
]}


def assert_catalog_complete() -> None:
    """Raise if the catalog is obviously inconsistent. Called by tests."""
    seen_sev = {s.severity for s in CATALOG.values()}
    assert seen_sev <= {_CRIT, _WARN, _INFO}, f"Unknown severity values: {seen_sev}"
    seen_cad = {s.cadence for s in CATALOG.values()}
    assert seen_cad <= {_DAILY, _WEEKLY, _MONTHLY, _SEASON}, f"Unknown cadence values: {seen_cad}"
