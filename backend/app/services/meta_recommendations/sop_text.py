"""Playbook excerpts used as grounding context for the Claude enricher.

Content condenses MEANDER_Meta_Ads_Playbook.docx into the minimum Claude
needs to reason about each rec_type. The full excerpt is injected as an
ephemeral cache block so the per-detector cost stays low across a batch.

Per-branch ICP blocks (H.1-H.5) are separate strings so the enricher can
inject only the block relevant to the target's account.
"""

PLAYBOOK_SUMMARY = """\
MEANDER META ADS PLAYBOOK (v1.0, Apr 2026)

Five properties, one group playbook. Every recommendation must respect:
- The hotel booking journey is longer, more emotional, and less e-commerce
  than typical Meta Ads optimization.
- Golden Rule #4: never scale a campaign by more than 25% budget in one day
  (learning phase resets).
- Golden Rule #1: never act on less than 7 days of data for warm/hot, or
  14 days for cold audiences.
- Home-country vs targeted-country matter: Saigon-home campaigns may target
  inbound SEA/AU/EU, so seasonality must respect both.
"""


PLAYBOOK_EXCERPTS: dict[str, str] = {
    # ── G.3 Diagnostic Decision Trees ─────────────────────────
    "PLAYBOOK.G.3.ROAS":
        "Tree 1 (Bad ROAS): ROAS = CVR * AOV / CPC. When ROAS drops, identify "
        "which component collapsed before acting. Check CPC (if up -> Tree 2), "
        "CR (if down -> landing page / offer / audience quality), AOV (if "
        "down -> creative promoting cheaper rooms than intended), attribution "
        "window shift (7d vs 1d), and seasonality (compare YoY not WoW). "
        "Never kill a creative on one metric.",
    "PLAYBOOK.G.3.CTR":
        "Tree 2 (Low CTR / Expensive Clicks): check frequency > 2.5 (fatigue), "
        "placement mix (restrict Audience Network), audience temperature "
        "(benchmarks: cold 0.8-1.5%, warm 1.5-3%, hot 3-8%), hook strength, "
        "and language match (localize for VN/JP markets).",
    "PLAYBOOK.G.3.CVR":
        "Tree 3 (High CTR / Low CVR): landing-page mismatch is the most common "
        "failure. Also check page load > 3s on mobile, booking friction "
        "(too many fields, no visible calendar), trust-signal absence (review "
        "score, star rating, guest count above the fold), and mobile-vs-desktop "
        "gap (mobile CR often 50% lower in hospitality).",

    # ── G.4 Seven Golden Rules ────────────────────────────────
    "PLAYBOOK.G.4.ATTRIBUTION":
        "Rule #7: do not trust Meta's in-platform ROAS alone. Reconcile against "
        "actual bookings from the PMS or OTA weekly. Attribution shifts (7d vs "
        "1d view) can make ROAS look worse without any real change.",

    # ── F.6 Creative Refresh Cadence ───────────────────────────
    "PLAYBOOK.F.6.FREQUENCY":
        "Refresh trigger: frequency above 2.5 within a 7-day window at the ad "
        "level. Above that, CTR falls and CPM rises slowly, then all at once. "
        "Pause the ad and rotate in fresh creative.",
    "PLAYBOOK.F.6.CTR_DROP":
        "Refresh trigger: CTR drops more than 25% vs the ad's first-7-day "
        "baseline. Classic fatigue. Upload 2-4 new creatives to test against "
        "the incumbent.",
    "PLAYBOOK.F.6.CPM_SPIKE":
        "Refresh trigger: CPM rises more than 30% without a clear external "
        "cause (holiday, event, competitor push). If no seasonal event is "
        "active, the audience is cooling — rotate creative.",
    "PLAYBOOK.F.6.AGE":
        "Refresh trigger: the same creative has been running for 30+ days. "
        "Rule #5 of the Seven Golden Rules: refresh regardless of current "
        "performance.",

    # ── Seasonal ───────────────────────────────────────────────
    "PLAYBOOK.SEASONAL.BUMP":
        "A seasonal event entering its lead-time window is a budget-bump "
        "trigger. Bump percentages come from the shared "
        "google_seasonality_events table (budget_bump_pct_min/max). Apply the "
        "bump for campaigns whose home country or targeted country includes "
        "the event's country_code. Cap the one-day increase at the 25% Golden "
        "Rule #4 — split larger raises across multiple days.",
    "PLAYBOOK.SEASONAL.CUT":
        "After a peak ends, cut budget back toward baseline to avoid paying "
        "shoulder-season CPM for fewer conversions. Max one-day decrease is "
        "up to 25% per the same Golden Rule #4 (decreases are less dangerous "
        "but sudden 50%+ cuts can also reset learning).",
    "PLAYBOOK.SEASONAL.LOW_SEASON":
        "Low-season window: shift spend from bottom-of-funnel conversion "
        "campaigns to top-of-funnel awareness. The 20/30/50 TOF/MOF/BOF split "
        "tilts to roughly 40/30/30 so the audience pool is primed for the "
        "next peak. Guidance only — actual shift requires new campaigns.",

    # ── E.4 Audience Exclusions ───────────────────────────────
    "PLAYBOOK.E.4.EXCL":
        "Mandatory exclusion for every campaign: Purchase event in last 30 "
        "days (recent bookers). Re-targeting just-booked guests burns money "
        "and annoys them. This is guidance-only because an auto-apply could "
        "overwrite other targeting tweaks.",
    "PLAYBOOK.E.4.TEMP":
        "Cold prospecting campaigns must exclude warm and hot audiences to "
        "avoid double-counting conversions and distorting the bid. Warm "
        "campaigns must exclude hot (they are already in the AddToCart "
        "retargeting pool).",
    "PLAYBOOK.E.4.STAFF":
        "Mandatory exclusion: upload current staff emails as a Custom "
        "Audience and exclude everywhere. Internal traffic pollutes the Pixel "
        "learning signal.",

    # ── H.x.3 Branch ICP budget mixes ─────────────────────────
    "PLAYBOOK.H.X.3.MIX":
        "Each branch has a playbook-defined monthly budget distribution across "
        "its ICPs (Section H.1.3 / H.2.3 / H.3.3 / H.4.3 / H.5.3). If actual "
        "spend drifts more than 30% from the target mix, rebalance next week's "
        "budget. Do not auto-apply — ICP mapping is interpretive.",
}


BRANCH_ICP_BLOCKS: dict[str, str] = {
    "Saigon": (
        "Meander Saigon (D1 HCMC, 42 rooms, 125 guest capacity, 2020). "
        "Four ICPs: (1) Western Explorer US/UK/AU/CA/EU 22-38yo long booking "
        "window; (2) SEA Regional PH/ID/TH/SG/MY/HK 24-42yo 7-14d window; "
        "(3) Vietnamese Business domestic Hanoi/Danang/Cantho 26-45yo 3-10d "
        "window; (4) Couples regional+international 26-40yo Deluxe Bathtub "
        "room focus. Fun Slide + Korean/Japan town proximity are signature "
        "hooks."
    ),
    "Taipei": (
        "Meander Taipei (Ximending, 171 guest capacity, 2013, flagship). "
        "Four ICPs: (1) Western Backpacker 20-35yo 4-10 nights; (2) SEA "
        "Traveler PH/SG/MY/ID/TH/HK 22-40yo solo-female heavy; (3) Design "
        "Nomad US/UK/AU/DE 25-45yo 14+ night long-stay; (4) Taiwanese "
        "Domestic Youth non-Taipei 18-30yo weekend/event-driven. Community "
        "activities (birthday cakes, cooking nights) are the brand."
    ),
    "1948": (
        "Meander 1948 (Datong, 112 guest capacity, 2018 heritage). "
        "Three ICPs: (1) Western Design Traveler 26-45yo architecture-literate "
        "30-60d window; (2) Asian Food-Efficient SG/HK/MY/JP/KR 24-40yo "
        "Airport-MRT-driven; (3) Taiwanese Creative Professional non-Taipei "
        "22-35yo weekend heritage seekers. Airport MRT 2-min proximity is THE "
        "selling point."
    ),
    "Osaka": (
        "Meander Osaka (Namba Motomachi, 2024, most-reviewed property). "
        "Four ICPs: (1) Asian Regional SG/HK/MY/TW/TH 24-42yo Namba + food "
        "focus; (2) Japanese Domestic ex-Osaka/Kobe 20-40yo entertainment "
        "weekend; (3) Western Japan-Trip US/UK/AU/CA/EU 26-45yo multi-city "
        "60-90d window; (4) Honeymoon Couples SG/HK/MY/TW/KR 26-38yo Superior "
        "Double. Mandarin-speaking staff + dark gold facade signature hooks."
    ),
    "Oani": (
        "Oani (Ximen Exit 3, premium boutique, Dec 2025, DIFFERENT market "
        "segment from the hostels). Six ICPs: (1) Wellness Seeker solo "
        "female JP/KR/TW/VN 26-38yo scent-bar + Still Room; (2) Design "
        "Couple 28-42yo ripple visual language + Deluxe Double; (3) Premium "
        "Backpacker 22-42yo dorm at Oani pricing; (4) Wellness Taiwanese "
        "28-45yo medical-grade air purification. Higher production value "
        "vs the hostels."
    ),
    "Bread": (
        "Bread Espresso& Japanese bakery cafe (Oani ground floor, restaurant). "
        "Complementary to Oani — no separate ICP structure; campaigns drive "
        "foot traffic to the cafe."
    ),
}


def excerpt_for(sop_reference: str | None) -> str | None:
    if not sop_reference:
        return None
    return PLAYBOOK_EXCERPTS.get(sop_reference)


def full_playbook_context() -> str:
    """Concatenate every excerpt for the ephemeral cache block."""
    parts = [PLAYBOOK_SUMMARY, ""]
    for key in sorted(PLAYBOOK_EXCERPTS):
        parts.append(f"[{key}]")
        parts.append(PLAYBOOK_EXCERPTS[key])
        parts.append("")
    return "\n".join(parts)


def branch_icp_block(branch_name: str | None) -> str | None:
    """Resolve a branch canonical key from a free-text account name."""
    if not branch_name:
        return None
    lower = branch_name.lower()
    for key in BRANCH_ICP_BLOCKS:
        if key.lower() in lower:
            return BRANCH_ICP_BLOCKS[key]
    return None
