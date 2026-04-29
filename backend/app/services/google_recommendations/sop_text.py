"""SOP excerpts used as grounding context for the Claude enricher.

The full SOP (Google_Ads_Power_Pack_Hotel_SOP.docx) is Vietnamese; the
excerpts below are condensed English summaries keyed by sop_reference so
Claude can cite the rationale for each recommendation.

The enricher injects the relevant excerpt into the system prompt with
cache_control: ephemeral so the SOP body is cached across a detector batch.
"""

SOP_POWER_PACK_SUMMARY = """\
GOOGLE ADS POWER PACK — HOTEL SOP (v1.0, Apr 2026)

This system of three AI-driven campaigns covers the full booking funnel:
- Demand Gen — TOF, YouTube / Discover / Gmail. Warms the audience pool.
- Search + AI Max — MOF/BOF. Captures intent.
- Performance Max — Full funnel. Convert and scale.

All three must run together. Running individually leaves traffic on the table.
"""


SOP_EXCERPTS: dict[str, str] = {
    # ── Part 1 — Demand Gen ───────────────────────────────
    "PART_1.CREATIVE":
        "Demand Gen asset hierarchy: Video (YouTube Shorts 9:16 or in-stream 16:9) is the strongest asset. "
        "Video + Image in the same asset group delivers +20% conversion vs. video alone. "
        "Never leave a campaign without a real video — Google will auto-generate a low-quality one.",
    "PART_1.BIDDING":
        "Phase 1 (weeks 1–2 while audience is cold): use tCPM to optimize reach. "
        "Phase 2 (after ≥2 weeks with enough click data): switch to Maximize Conversions.",
    "PART_1.ATTRIBUTION":
        "Attribution model must be Data-Driven, not Last Click. Last Click undervalues Demand Gen touchpoints.",
    "PART_1.FREQUENCY":
        "Remarketing frequency benchmark: 3–7 per week (action required above 10). "
        "Cold-audience frequency benchmark: 1–3 per week (action required above 5).",
    "PART_1.AUDIENCE":
        "Audience priority for Demand Gen: (1) Customer Match past guests, (2) booking-page remarketing, "
        "(3) all-site remarketing, (4) lookalikes, (5) custom intent competitors, (6) custom intent destination, "
        "(7) Optimized Targeting (cold campaigns only). "
        "NEVER enable Optimized Targeting on Remarketing — it dilutes the high-value pool.",
    "PART_1.KPI":
        "VTR >30% for in-stream (alert below 20%); image/carousel CTR >0.5% (alert below 0.2%); "
        "view-through conversions should trend up week-over-week.",

    # ── Part 2 — Search + AI Max ──────────────────────────
    "PART_2.RULE_1":
        "Rule #1: Branded and non-branded MUST run in separate campaigns. Bidding strategy, ROAS target, "
        "and negative list management differ. Mixing makes ROI measurement impossible and PMax will steal "
        "branded traffic.",
    "PART_2.BRANDED":
        "Branded Search: Target Impression Share ≥90% top-of-page. Exact + Phrase only (no broad). "
        "24/7 schedule, unlimited budget cap. Add branded keywords as negatives on non-branded and on PMax.",
    "PART_2.BRAND_EXCLUSION":
        "PMax must have a Brand Exclusion list covering the hotel name and variants — otherwise PMax will "
        "cannibalize branded traffic and report inflated ROAS.",
    "PART_2.AIMAX":
        "AI Max safe setup: (1) PIN brand name to Headline 1, (2) turn OFF Final URL Expansion for the first "
        "2 weeks, (3) enable Search Term Matching first, review weekly and add negatives, (4) only enable "
        "Text Customization after 2 weeks of clean search terms. Never enable AI Max on branded campaigns.",
    "PART_2.RSA":
        "RSA: Ad Strength target Good, aim for Excellent. Minimum 8–10 distinct headlines and 3–4 descriptions. "
        "Pin at most 2–3 positions — leave room for AI to test.",
    "PART_2.NEGATIVES":
        "Shared negative list covers: jobs/career, press/media, academic research, free/gratis, "
        "cancel/refund/complaint, competitor brand terms (unless running competitor campaign). "
        "Review weekly in the first month, every 2 weeks thereafter.",

    # ── Part 3 — Performance Max ──────────────────────────
    "PART_3.STRUCTURE":
        "PMax count by hotel scale: <50 rooms or <$30/day → 1 campaign (concentrate signal). "
        "50-200 rooms, $30-100/day → 1–2 campaigns (regular + seasonal). "
        ">200 rooms or multiple tiers → 2–3 campaigns (Regular + Premium + Seasonal).",
    "PART_3.ASSET_COMPLETENESS":
        "Per asset group: ≥1 landscape image, ≥1 square image, ≥1 logo, ≥2-3 videos (real), "
        "≥3-5 short headlines, ≥1-3 long headlines, ≥2-4 descriptions. "
        "Always upload real video — auto-generated video hurts brand.",
    "PART_3.AUDIENCE":
        "Audience signal priority: Customer Match past guests > high-value guests > booking-page remarketing > "
        "all-site remarketing > YouTube remarketing > custom intent competitors > custom intent destination > "
        "in-market segments.",
    "PART_3.BIDDING":
        "Lifecycle: Week 1-2 Max Conversions (no tCPA). Week 3-6 Max Conversions + tCPA 20-30% above actual. "
        "Month 2-3 tCPA at actual. Month 4+ tROAS (once revenue value data is clean). "
        "Never change bid strategy or tCPA more than 20% in one step — resets learning phase for 1–2 weeks.",
    "PART_3.BRAND_SAFETY":
        "Brand leak pattern: PMax ROAS abnormally high AND branded Search impressions drop week-over-week. "
        "PMax is stealing branded traffic — add the brand exclusion list at account level immediately.",

    # ── Part 4 — Conversion Tracking ──────────────────────
    "PART_4.PRIMARY":
        "Only Booking Confirmed is Primary (account-level). Checkout Initiated / Room Selection / "
        "Phone Call / Contact Form are Secondary or Micro — observe, do not optimize bidding on them.",
    "PART_4.ENHANCED":
        "Enhanced Conversions for web captures 10–30% additional conversions via hashed first-party data. "
        "Always enable.",
    "PART_4.RECONCILIATION":
        "Monthly audit: compare Ads-reported bookings vs PMS/channel-manager actuals. "
        "<15% delta is healthy; greater delta requires tag audit.",
    "PART_4.VALUE":
        "Dynamic booking value must be passed to Booking Confirmed to support Maximize Conversion Value and tROAS.",

    # ── Part 5 — 1st-party Data ───────────────────────────
    "PART_5.CUSTOMER_MATCH":
        "Refresh Customer Match monthly from PMS. Segments: VIP (>X spend or ≥3 stays, bid +30-50%), "
        "Recent (12 months, loyalty offer), Lapsed (1–3 years, win-back), One-time (>1 year, reactivation), "
        "Cancellation (exclude from all campaigns).",

    # ── Part 6 — Budget & Seasonality ─────────────────────
    "PART_6.ALLOCATION":
        "New account (0–6 months): Branded 10-15% / Non-branded 30-40% / PMax 40-50% / Demand Gen 10-15%. "
        "Stable (6+ months): Branded 5-10% / Non-branded 25-35% / PMax 40-50% / Demand Gen 15-20%.",
    "PART_6.SEASONALITY":
        "Seasonality is per-branch AND per-targeted-country. Each event carries a country_code; "
        "detectors only fire when the event country is in (branch home country ∪ campaign's targeted countries). "
        "Branch home countries: Saigon=VN, Osaka=JP, Taipei/1948/Oani/Bread=TW. "
        "VN: Tet (Jan-Feb, lead 3 weeks, +30-50% / tCPA +20-30%); 30/4-1/5 (lead 2w, +20-30%/+15-20%); "
        "Summer Jun-Aug (lead from early May, +40-60%); 2/9 (lead 2w, +20-30%); "
        "Christmas (lead from early Nov, +20-40%); Low season Mar & Sep-Oct (-10-15% tCPA, shift to Demand Gen). "
        "JP: Shogatsu (biggest peak, lead 4w, +30-50%); Golden Week (lead 4w, +40-60%); Obon (lead 3w, +30-50%); "
        "Sakura (lead 4w, inbound-driven +30-50%); Momiji (lead 4w, +20-40%); Low season: post-Shogatsu Jan-Feb and rainy June. "
        "TW: Lunar NY (lead 3w, +30-50%); Qingming, Dragon Boat, Mid-Autumn, Double Ten (each lead 2w, +15-30%); "
        "Summer peak Jun-Aug (+30-50%); Christmas/NYE (lead 4w, +20-40%); Low spring Mar, low late-autumn. "
        "Inbound source markets (KR Seollal/Chuseok, HK/SG CNY, US Thanksgiving/Xmas, AU summer/April holidays) "
        "fire only when the branch actually targets those geos. "
        "NEVER wait until peak — AI needs 1–2 weeks to re-learn.",
    "PART_6.BUDGET_PACING":
        "If PMax daily spend exhausts before 2 pm local on 3 of the last 7 days, budget is too low for the "
        "current tCPA target. Raise budget or lower tCPA target.",

    # ── Part 7 — Daily checks ─────────────────────────────
    "PART_7.DAILY":
        "Daily review (5-10 min): spend vs daily budget within ±20%; impressions drop >50% alert; "
        "CTR spike >100% inspect for invalid clicks; zero-conversion days for 7+ days → tag audit; "
        "policy violations resolved same day.",
}


def excerpt_for(sop_reference: str) -> str:
    """Return the excerpt for a sop_reference, or an empty string if unknown."""
    return SOP_EXCERPTS.get(sop_reference, "")


def full_sop_context() -> str:
    """Concatenated SOP summary + all excerpts, used as the Claude cache block."""
    parts = [SOP_POWER_PACK_SUMMARY, ""]
    for ref, body in SOP_EXCERPTS.items():
        parts.append(f"[{ref}]")
        parts.append(body)
        parts.append("")
    return "\n".join(parts)
