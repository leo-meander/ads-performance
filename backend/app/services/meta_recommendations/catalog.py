"""Meta recommendation type catalog.

Single source of truth for every rec_type produced by detectors. Drives:
- detector self-registration (catalog spec populates class attributes)
- frontend label map (rec_type -> title template)
- applier dispatch (auto_applicable gate)
- migration / seeding sanity checks

Keep this file aligned with MEANDER_Meta_Ads_Playbook.docx:
  Section G.3 — diagnostic decision trees (Bad ROAS, Low CTR, High CTR-Low CVR)
  Section G.4 — Seven Golden Rules
  Section F.6 — creative refresh triggers
  Section E.4 — exclusion discipline
  Section H.x.3 — per-branch ICP budget mix
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


_CRIT, _WARN, _INFO = "critical", "warning", "info"
_DAILY, _WEEKLY, _MONTHLY, _SEASON = "daily", "weekly", "monthly", "seasonality"


CATALOG: dict[str, RecTypeSpec] = {spec.rec_type: spec for spec in [
    # ── Performance critical (Section G.3 / G.4) ───────────────
    RecTypeSpec(
        "META_BAD_ROAS_7D", _CRIT, _DAILY, "PLAYBOOK.G.3.ROAS", False,
        "Campaign ROAS below benchmark for 7 days",
        "Campaign ROAS has trailed its tier benchmark for 7+ consecutive days. "
        "Follow decision Tree 1 — check which component (CR / AOV / CPC) collapsed "
        "before pausing or shifting budget.",
    ),
    RecTypeSpec(
        "META_LOW_CTR_7D", _WARN, _DAILY, "PLAYBOOK.G.3.CTR", False,
        "CTR below cold/warm audience benchmark",
        "CTR is below the benchmark for this audience temperature. Tree 2 says: "
        "check frequency > 2.5, placement mix (Audience Network leak), hook strength, "
        "and language match before killing the creative.",
    ),
    RecTypeSpec(
        "META_HIGH_CTR_LOW_CVR", _WARN, _WEEKLY, "PLAYBOOK.G.3.CVR", False,
        "Clicks arrive but do not convert",
        "CTR is healthy but the campaign's 7-day booking conversion rate has "
        "dropped to less than half of its own trailing 30-day baseline. Tree 3 "
        "points to landing-page mismatch, page load > 3s on mobile, booking "
        "friction, or missing trust signals. Audit the funnel as a first-time "
        "visitor.",
    ),
    RecTypeSpec(
        "META_FREQ_ABOVE_CEILING", _WARN, _DAILY, "PLAYBOOK.F.6.FREQUENCY", True,
        "Ad frequency above 2.5 in 7-day window",
        "Ad frequency exceeds 2.5/week — creative fatigue threshold in Section F.6. "
        "System will pause the ad so the audience can cool down. Rotate in fresh "
        "creative before re-enabling.",
    ),

    # ── Creative fatigue (Section F.6) ─────────────────────────
    RecTypeSpec(
        "META_CTR_DROP_BASELINE", _WARN, _WEEKLY, "PLAYBOOK.F.6.CTR_DROP", False,
        "CTR has dropped more than 25% vs first-7-day baseline",
        "CTR fell more than 25% vs the ad's first-7-day baseline — the Section F.6 "
        "refresh trigger. Upload 2-4 new creatives against this ad set before scaling.",
    ),
    RecTypeSpec(
        "META_CPM_SPIKE", _WARN, _WEEKLY, "PLAYBOOK.F.6.CPM_SPIKE", True,
        "CPM rose more than 30% without an external trigger",
        "CPM has risen more than 30% and no seasonal event is active. Classic "
        "fatigue signal. System will pause this ad — refresh the creative before "
        "re-enabling.",
    ),
    RecTypeSpec(
        "META_CREATIVE_AGE_30D", _INFO, _WEEKLY, "PLAYBOOK.F.6.AGE", False,
        "Creative has been running 30+ days continuously",
        "Rule #5 of the Seven Golden Rules: do not run the same creative longer "
        "than 30 days without a refresh — regardless of performance. Plan the next "
        "shoot or angle test.",
    ),

    # ── Seasonal (Section H.x.4) ────────────────────────────────
    RecTypeSpec(
        "META_SEASONAL_BUDGET_BUMP", _WARN, _SEASON, "PLAYBOOK.SEASONAL.BUMP", True,
        "Seasonal event approaching — raise budget",
        "A hotel peak event is entering its lead-time window for this branch's home "
        "country or a targeted inbound country. System will raise daily_budget by the "
        "playbook-recommended percent (capped at the 25% daily rule).",
    ),
    RecTypeSpec(
        "META_SEASONAL_BUDGET_CUT", _INFO, _SEASON, "PLAYBOOK.SEASONAL.CUT", True,
        "Seasonal event ended — normalize budget",
        "The seasonal window has closed. System will cut daily_budget back toward "
        "baseline to avoid over-spending the shoulder period.",
    ),
    RecTypeSpec(
        "META_LOW_SEASON_SHIFT", _INFO, _SEASON, "PLAYBOOK.SEASONAL.LOW_SEASON", False,
        "Low season — shift spend from BOF to TOF awareness",
        "Branch is in a low-season window. Playbook recommends shifting spend from "
        "bottom-of-funnel conversion campaigns to top-of-funnel awareness to warm up "
        "the audience for the next peak. Adjust the 20/30/50 mix manually in Meta.",
    ),

    # ── Audience hygiene (Section E.4) ──────────────────────────
    RecTypeSpec(
        "META_MISSING_RECENT_BOOKER_EXCLUSION", _WARN, _WEEKLY, "PLAYBOOK.E.4.EXCL", False,
        "Campaign is missing the recent-booker exclusion",
        "Section E.4 mandatory exclusion: everyone with a Purchase event in the last "
        "30 days. This campaign's targeting does not show that exclusion in "
        "raw_data. Add it manually to avoid re-targeting guests who already booked.",
    ),
    RecTypeSpec(
        "META_TEMPERATURE_OVERLAP", _WARN, _WEEKLY, "PLAYBOOK.E.4.TEMP", False,
        "Cold campaign does not exclude warm/hot audiences",
        "Cold prospecting campaigns should exclude warm and hot pools to avoid "
        "double-counting conversions. Check the adset's targeting JSON and add the "
        "exclusion list manually.",
    ),

    # ── Branch-level roll-up (Section H.x.3) ────────────────────
    RecTypeSpec(
        "META_BRANCH_ICP_IMBALANCE", _INFO, _WEEKLY, "PLAYBOOK.H.X.3.MIX", False,
        "Branch ICP spend mix drifted from playbook target",
        "Actual spend distribution across this branch's ICPs is more than 30% off "
        "the Section H.x.3 target mix. Rebalance next week's budget manually — "
        "auto-apply is not safe here because ICP mapping is interpretive.",
    ),
]}
