"""Creative Hypotheses API — Learning Engine."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ad_combo import AdCombo
from app.models.brand_identity import BrandIdentity
from app.models.creative_hypothesis import CreativeHypothesis
from app.models.hypothesis_combo_link import HypothesisComboLink

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])

HYPOTHESIS_STATUSES = ["pending", "running", "validated", "refuted", "inconclusive"]


class HypothesisSuggestRequest(BaseModel):
    branch_name: str
    human_desire: str
    hypothesis_category: Optional[str] = None
    customer_insight: Optional[str] = None
    creative_angle: Optional[str] = None
    target_audience: Optional[str] = None
    market: Optional[str] = None
    primary_kpi: Optional[str] = None
    # Layer A spec fields — if present, AI writes to these instead of primary_kpi
    funnel_stage: Optional[str] = None    # Stop|Hold|Click|Downstream
    format: Optional[str] = None          # Image|Video
    primary_metric: Optional[str] = None  # auto-derived from stage+format
    win_threshold: Optional[float] = None # benchmark value for context


class HypothesisCreate(BaseModel):
    branch_name: str
    combo_id: Optional[str] = None          # legacy single-link (kept for compat)
    combo_ids: Optional[list[str]] = None   # multi-link (preferred)
    angle_id: Optional[str] = None
    hypothesis_category: Optional[str] = None
    customer_insight: Optional[str] = None
    human_desire: Optional[str] = None
    creative_angle: Optional[str] = None
    target_audience: Optional[str] = None
    market: Optional[str] = None
    hypothesis: str
    variable_tested: Optional[str] = None   # A/B: "X vs Y"; omit for benchmark test
    baseline: Optional[str] = None          # benchmark: human-readable description of the baseline
    # Layer A verdict setup
    funnel_stage: Optional[str] = None        # Stop|Hold|Click|Downstream
    format: Optional[str] = None             # Image|Video
    primary_metric: Optional[str] = None     # pre-registered primary metric
    win_threshold: Optional[float] = None    # pre-registered threshold value
    min_sample: Optional[int] = 5            # verdict gate
    primary_kpi: Optional[str] = None
    secondary_kpi: Optional[str] = None
    expected_outcome: Optional[str] = None
    created_by: Optional[str] = None
    # 4-tier links (optional at creation)
    research_question_id: Optional[str] = None  # UUID string
    knowledge_links: Optional[list[str]] = None
    parent_hypothesis_id: Optional[str] = None  # UUID string


class BriefAnalysisRequest(BaseModel):
    brief_text: str
    script_text: str


class VisionAnalysisRequest(BaseModel):
    image_urls: Optional[list[str]] = None  # base64 data: URLs or http(s); auto-pulled from combo if omitted


class HypothesisResultUpdate(BaseModel):
    status: str
    actual_ctr: Optional[float] = None
    actual_cvr: Optional[float] = None
    actual_roas: Optional[float] = None
    actual_spend: Optional[float] = None
    confounding_factors: Optional[list[str]] = None
    confidence_level: Optional[str] = None
    confidence_score: Optional[float] = None
    learning: Optional[str] = None
    result_notes: Optional[str] = None
    # Layer B (downstream) verdict — set independently of creative verdict
    layer_b_status: Optional[str] = None   # pass|fail|insufficient
    layer_b_notes: Optional[str] = None
    # 4-tier links
    principle_id: Optional[str] = None   # UUID string
    research_question_id: Optional[str] = None
    knowledge_links: Optional[list[str]] = None


def _next_hypothesis_id(db: Session) -> str:
    last = (
        db.query(CreativeHypothesis)
        .order_by(desc(CreativeHypothesis.created_at))
        .first()
    )
    if not last or not last.hypothesis_id:
        return "HYP-001"
    try:
        num = int(last.hypothesis_id.split("-")[1]) + 1
    except (IndexError, ValueError):
        num = 1
    return f"HYP-{num:03d}"


def _serialize(h: CreativeHypothesis, combo: AdCombo | None = None, approval_status: Optional[str] = None, principle_title: Optional[str] = None, linked_combos: list[AdCombo] | None = None) -> dict:
    clicks = int(combo.clicks or 0) if combo else None
    conversions = int(combo.conversions or 0) if combo else None
    return {
        "id": str(h.id),
        "hypothesis_id": h.hypothesis_id,
        "branch_name": h.branch_name,
        "combo_id": str(h.combo_id) if h.combo_id else None,
        "ad_name": combo.ad_name if combo else None,
        "combo_clicks": clicks,
        "combo_conversions": conversions,
        "linked_combos": [
            {"combo_id": c.combo_id, "ad_name": c.ad_name, "verdict": c.verdict,
             "roas": float(c.roas) if c.roas else None, "hook_rate": float(c.hook_rate) if c.hook_rate else None,
             "ctr": float(c.ctr) if c.ctr else None}
            for c in (linked_combos or [])
        ],
        "angle_id": str(h.angle_id) if h.angle_id else None,
        "hypothesis_category": h.hypothesis_category,
        "customer_insight": h.customer_insight,
        "human_desire": h.human_desire,
        "creative_angle": h.creative_angle,
        "target_audience": h.target_audience,
        "market": h.market,
        "hypothesis": h.hypothesis,
        "variable_tested": h.variable_tested,
        "baseline": h.baseline,
        "primary_kpi": h.primary_kpi,
        "secondary_kpi": h.secondary_kpi,
        "expected_outcome": h.expected_outcome,
        "status": h.status,
        "actual_ctr": float(h.actual_ctr) if h.actual_ctr else None,
        "actual_cvr": float(h.actual_cvr) if h.actual_cvr else None,
        "actual_roas": float(h.actual_roas) if h.actual_roas else None,
        "actual_spend": float(h.actual_spend) if h.actual_spend else None,
        "confounding_factors": h.confounding_factors,
        "confidence_level": h.confidence_level,
        "learning": h.learning,
        "result_notes": h.result_notes,
        "validated_at": h.validated_at.isoformat() if h.validated_at else None,
        "created_by": h.created_by,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        # Deep analysis fields
        "brief_text": h.brief_text,
        "script_text": h.script_text,
        "evidence": h.evidence,
        "creative_principle": h.creative_principle,
        "why_it_worked": h.why_it_worked,
        "human_moment": h.human_moment,
        # Approval linkage — latest approval status for this hypothesis
        "approval_status": approval_status,
        # Layer A/B verdict split
        "funnel_stage": h.funnel_stage,
        "format": h.format,
        "primary_metric": h.primary_metric,
        "win_threshold": float(h.win_threshold) if h.win_threshold is not None else None,
        "min_sample": int(h.min_sample) if h.min_sample is not None else 5,
        "layer_b_status": h.layer_b_status,
        "layer_b_notes": h.layer_b_notes,
        # 4-tier knowledge system
        "confidence_score": float(h.confidence_score) if h.confidence_score is not None else None,
        "principle_id": str(h.principle_id) if h.principle_id else None,
        "principle_title": principle_title,
        "research_question_id": str(h.research_question_id) if h.research_question_id else None,
        "knowledge_links": h.knowledge_links or [],
        "parent_hypothesis_id": str(h.parent_hypothesis_id) if h.parent_hypothesis_id else None,
    }


@router.post("/suggest")
def suggest_hypotheses(payload: HypothesisSuggestRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Generate 3 hypothesis variants. When funnel_stage + format are set, all output is
    written exclusively to that stage's primary metric — never falls back to CTR."""
    try:
        from collections import defaultdict
        from anthropic import Anthropic
        from app.config import settings

        # ── 1. Determine the binding metric ──────────────────────────────
        FUNNEL_METRICS = {
            "Stop":       {"Video": "hook_rate",    "Image": "thumb_stop_rate"},
            "Hold":       {"Video": "hold_rate",    "Image": "hold_rate"},
            "Click":      {"Video": "CTR",          "Image": "CTR"},
            "Downstream": {"Video": "booking_rate", "Image": "booking_rate"},
        }
        STAGE_SURFACE = {
            "Stop":       "the first 3 seconds / opening frame of the ad",
            "Hold":       "the body, pacing, or length of the video",
            "Click":      "the call-to-action, end-card, or offer framing",
            "Downstream": "the proof, price, or offer (Layer B — booking intent)",
        }

        active_metric: str
        if payload.funnel_stage and payload.format:
            active_metric = FUNNEL_METRICS.get(payload.funnel_stage, {}).get(payload.format, "")
        else:
            active_metric = payload.primary_metric or payload.primary_kpi or "CTR"

        stage = payload.funnel_stage or "—"
        fmt = payload.format or "—"
        surface = STAGE_SURFACE.get(payload.funnel_stage or "", "")

        # ── 2. Brand context (never say = hard constraint) ────────────────
        brand = db.query(BrandIdentity).filter(
            BrandIdentity.branch_name == payload.branch_name
        ).first()
        never_say = brand.never_say if brand else []
        brand_ctx = ""
        if brand:
            brand_ctx = (
                f"Branch: {brand.branch_name}\n"
                f"Territory: {brand.brand_territory or '—'}\n"
                f"Promise: {brand.brand_promise or '—'}\n"
                f"Feeling target: {brand.feeling_target or '—'}\n"
                f"Always say: {', '.join(brand.always_say or [])}\n"
                f"NEVER SAY (hard exclusion — drop any suggestion that uses these): "
                f"{', '.join(never_say) if never_say else 'none'}"
            )

        # ── 3. Dashboard learnings — angle win rates + top desires ────────
        MIN_SAMPLE = 5
        concluded = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == payload.branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
        ).all()

        angle_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if h.creative_angle:
                angle_stats[h.creative_angle]["total"] += 1
                if h.status == "validated":
                    angle_stats[h.creative_angle]["wins"] += 1
        proven_angles = sorted(
            [(a, v) for a, v in angle_stats.items() if v["total"] >= MIN_SAMPLE],
            key=lambda x: x[1]["wins"] / x[1]["total"],
            reverse=True,
        )[:5]
        exploratory = len(concluded) < MIN_SAMPLE

        learning_ctx = ""
        if proven_angles:
            lines = [f"  - \"{a}\" — {v['wins']}/{v['total']} win rate ({round(v['wins']/v['total']*100)}%)"
                     for a, v in proven_angles]
            learning_ctx += "PROVEN ANGLES (prefer building on these, cite win rate):\n" + "\n".join(lines) + "\n"
        if exploratory:
            learning_ctx += f"NOTE: fewer than {MIN_SAMPLE} concluded tests — mark suggestions as EXPLORATORY.\n"

        # Past learnings for this desire
        past = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == payload.branch_name,
            CreativeHypothesis.human_desire == payload.human_desire,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
            CreativeHypothesis.learning.isnot(None),
        ).order_by(desc(CreativeHypothesis.validated_at)).limit(4).all()
        if past:
            learning_ctx += "PAST LEARNINGS FOR THIS DESIRE:\n" + "\n".join(
                f"  - [{h.status.upper()}] {h.learning}" for h in past
            ) + "\n"

        # ── 4. Benchmark band for the active metric ───────────────────────
        benchmark_ctx = ""
        if payload.win_threshold:
            benchmark_ctx = (
                f"60-day benchmark for {active_metric} on {payload.branch_name}: "
                f"{payload.win_threshold}% average. "
                f"Set Expected Outcome threshold near this band — do not invent fantasy deltas."
            )

        # ── 5. Category guidance ──────────────────────────────────────────
        category_guidance = {
            "identity":        "Test identity signals — WHO does the guest become? Solo adventurer, romantic couple, design-conscious traveler.",
            "decision_driver": "Test the rational tipping point — price anchoring, urgency, risk-removal.",
            "emotional_trigger": "Test which emotion closes the booking — romance, nostalgia, excitement, escape, pride.",
            "travel_moment":   "Test which planning stage the ad speaks to — dreaming, comparing, or ready-to-book.",
            "social_proof":    "Test whose voice the guest trusts — peer review, expert endorsement, UGC, staff.",
            "experience":      "Test which memorable moment detail resonates — breakfast view, rooftop sunset, unique ritual.",
            "value_perception":"Test how value is framed — premium justification, comparison, or tangible add-ons.",
            "brand_territory": "Test which ownable brand characteristic only this hotel has.",
        }
        cat_ctx = ""
        if payload.hypothesis_category:
            cat_ctx = (
                f"Booking Decision Category: {payload.hypothesis_category.replace('_',' ').title()}\n"
                f"{category_guidance.get(payload.hypothesis_category, '')}"
            )
        insight_ctx = f"Customer Insight (underlying belief): {payload.customer_insight}" if payload.customer_insight else ""

        # ── 6. Build the prompt ───────────────────────────────────────────
        prompt = f"""You are a hotel performance marketing strategist. Generate exactly 3 creative hypothesis variants.

═══ BINDING CONSTRAINT — READ THIS FIRST ═══
Funnel Stage: {stage}
Format: {fmt}
PRIMARY METRIC: {active_metric}

Every hypothesis, variable, and expected outcome MUST be written in terms of {active_metric} ONLY.
Do NOT mention CTR, ROAS, CVR, or any other metric.
The variable may ONLY touch: {surface or 'the surface appropriate for this stage'}.
If stage is Stop → the variable must be about the OPENING FRAME, not the CTA or offer.
If stage is Click → the variable must be about the CTA or offer, not the opening.
Expected Outcome must name {active_metric} and nothing else.
════════════════════════════════════════════

BRAND CONTEXT:
{brand_ctx}

{learning_ctx}
{benchmark_ctx}

THIS TEST:
Human Desire: {payload.human_desire}
Creative Angle: {payload.creative_angle or '—'}
Target Audience: {payload.target_audience or '—'}
Market: {payload.market or '—'}
{cat_ctx}
{insight_ctx}

OUTPUT FORMAT — JSON array of exactly 3 objects:
{{
  "hypothesis": "We believe... [references {active_metric}, no other metric]",
  "variable_tested": "[exactly one X vs Y pair about {surface or 'the right surface'}]",
  "expected_outcome": "[{active_metric} ≥ X% or +X pp vs baseline — no other metric]",
  "customer_insight": "[the belief underneath — one sentence]",
  "rationale": "[why this addresses a real booking hesitation for {payload.branch_name} {payload.target_audience or ''}]"
}}

Self-check before responding:
1. Does expected_outcome name ONLY {active_metric}? If not → rewrite.
2. Is variable_tested exactly one vs pair about {surface or 'the correct surface'}? If not → rewrite.
3. Does any suggestion use a NEVER SAY word ({', '.join(never_say) if never_say else 'none'})? If yes → drop and replace.
{('4. Mark all suggestions as EXPLORATORY if history is thin.' if exploratory else '')}

Return ONLY valid JSON array. No markdown, no explanation."""

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        suggestions = json.loads(raw.strip())

        # ── 7. Server-side self-check: drop suggestions that mention wrong metrics ──
        wrong_metrics = {"CTR", "ROAS", "CVR", "LPV", "CPA"}
        if active_metric in wrong_metrics:
            wrong_metrics.discard(active_metric)
        cleaned = []
        for s in suggestions:
            outcome = s.get("expected_outcome", "")
            bad = [m for m in wrong_metrics if m.lower() in outcome.lower()]
            if not bad:
                cleaned.append(s)
            else:
                logger.warning("[suggest] dropped suggestion mentioning %s in outcome: %s", bad, outcome)
        # Fall back to full list if all were dropped (shouldn't happen)
        suggestions = cleaned or suggestions

        return {"success": True, "data": {"suggestions": suggestions, "active_metric": active_metric},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("[hypothesis-suggest] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


class BulkGenerateRequest(BaseModel):
    branch_name: str


@router.post("/bulk-generate")
def bulk_generate_hypotheses(payload: BulkGenerateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Group combos by (TA + country + dominant_metric), generate one hypothesis per cohort via Claude."""
    try:
        from anthropic import Anthropic
        from app.config import settings
        from app.core.branches import get_account_ids_for_branches, canonical_branch

        # Resolve branch name → account IDs (handles "Meander Taipei" → "Taipei" → account UUIDs)
        canonical = canonical_branch(payload.branch_name) or payload.branch_name
        account_ids = get_account_ids_for_branches(db, [canonical])
        if not account_ids:
            # Fallback: try the full string as a pattern
            account_ids = get_account_ids_for_branches(db, [payload.branch_name])

        combos = (
            db.query(AdCombo)
            .filter(AdCombo.branch_id.in_(account_ids))
            .all()
        ) if account_ids else []
        if not combos:
            return {"success": True, "data": {"proposals": []}, "error": None,
                    "timestamp": datetime.now(timezone.utc).isoformat()}

        # Exclude combos already linked to a hypothesis
        linked_ids = {
            lk.combo_id for lk in db.query(HypothesisComboLink.combo_id).all()
        }
        # Also exclude combos referenced via legacy combo_id column
        legacy_ids = {
            r.combo_id for r in db.query(CreativeHypothesis.combo_id)
            .filter(CreativeHypothesis.combo_id.isnot(None)).all()
        }
        already_linked = linked_ids | legacy_ids
        combos = [c for c in combos if c.combo_id not in already_linked]

        if not combos:
            return {"success": True, "data": {"proposals": [], "total_combos": 0,
                    "skipped": len(already_linked), "total_cohorts": 0}, "error": None,
                    "timestamp": datetime.now(timezone.utc).isoformat()}

        # Group by (TA, country, dominant_metric)
        def dominant_metric(c: AdCombo) -> str:
            if c.hook_rate and float(c.hook_rate) > 0:
                return "hook_rate"
            if c.ctr and float(c.ctr) > 0:
                return "CTR"
            if c.roas and float(c.roas) > 0:
                return "roas"
            return "CTR"

        from collections import defaultdict
        groups: dict[tuple, list[AdCombo]] = defaultdict(list)
        for c in combos:
            key = (c.target_audience or "Unknown", c.country or "Unknown", dominant_metric(c))
            groups[key].append(c)

        # Only cohorts with ≥2 combos are interesting
        groups = {k: v for k, v in groups.items() if len(v) >= 2}

        # Brand context
        brand = db.query(BrandIdentity).filter(BrandIdentity.branch_name == payload.branch_name).first()
        never_say = (brand.never_say if isinstance(brand.never_say, list) else []) if brand else []
        brand_promise = brand.brand_promise or "" if brand else ""

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        proposals = []

        for (ta, country, metric), members in list(groups.items())[:20]:  # cap at 20 cohorts
            # Sort: WIN first, then by metric desc
            def sort_key(c: AdCombo):
                val = float(getattr(c, "hook_rate" if metric == "hook_rate" else "ctr" if metric == "CTR" else "roas") or 0)
                verdict_score = 2 if c.verdict == "WIN" else 1 if c.verdict == "TEST" else 0
                return (verdict_score, val)
            sorted_m = sorted(members, key=sort_key, reverse=True)
            top = sorted_m[:3]
            bottom = sorted_m[-2:]

            def fmt(c: AdCombo) -> str:
                val = float(getattr(c, "hook_rate" if metric == "hook_rate" else "ctr" if metric == "CTR" else "roas") or 0)
                fmt_val = f"{val:.2%}" if metric != "roas" else f"{val:.2f}x"
                return f"- [{c.verdict}] {c.ad_name or c.combo_id}: {metric}={fmt_val}"

            top_lines = "\n".join(fmt(c) for c in top)
            bottom_lines = "\n".join(fmt(c) for c in bottom)

            top_metric_val = float(getattr(top[0], "hook_rate" if metric == "hook_rate" else "ctr" if metric == "CTR" else "roas") or 0) if top else 0
            cohort_avg = sum(float(getattr(c, "hook_rate" if metric == "hook_rate" else "ctr" if metric == "CTR" else "roas") or 0) for c in members) / len(members)
            avg_fmt = f"{cohort_avg:.2%}" if metric != "roas" else f"{cohort_avg:.2f}x"

            prompt = f"""You are a creative strategist for {payload.branch_name}, a hotel/restaurant brand.

Cohort: TA={ta}, Market={country}, Primary Metric={metric}
Brand promise: {brand_promise}
Never say: {', '.join(never_say) or 'none'}
Cohort average {metric}: {avg_fmt}

Top performers:
{top_lines}

Bottom performers:
{bottom_lines}

Study the gap between winners and losers. Write a 4-part hypothesis using this exact structure:

1. BELIEF — the enduring behavioral insight. What do these guests fundamentally care about? One sentence. Starts with the guest. Lives for 5 years.
   ✓ "Solo travelers care more about how the trip feels than where they sleep."
   ✗ "Guests respond to social proof content." (too vague, not behavioral)

2. WHY — the assumption you are testing. One sentence. Mark it as unconfirmed. Plain language.
   ✓ "Because they want experiences that feel like 'someone like me' — unconfirmed until isolated."
   ✗ "Because social proof drives higher engagement metrics for this segment."

3. TEST — the specific creative swap. One variable only. One sentence.
   ✓ "KOL city exploration vs room showcase. Stage: Stop · Format: Video"
   ✗ "AI-generated or KOL content with aspirational hotel + location combinations"

4. SUCCESS — what a win looks like. Primary metric + threshold + baseline. Secondary metrics listed briefly.
   ✓ "Primary: {metric} ≥ [X] (baseline ~{avg_fmt}). Secondary: CTR, watch time."
   ✗ "We expect the winning creative to outperform the cohort average significantly."

Return JSON in English:
{{
  "customer_insight": "[BELIEF — one sentence, starts with the guest]",
  "hypothesis": "[WHY — the assumption being tested, one sentence, plain language]",
  "variable_tested": "[TEST — the exact swap, one variable, include Stage and Format if known]",
  "expected_outcome": "Primary: {metric} ≥ [X] (baseline ~{avg_fmt}). Secondary: [list 1-2 metrics]",
  "hypothesis_category": "[identity|decision_driver|emotional_trigger|travel_moment|social_proof|experience|value_perception|brand_territory]"
}}

Return ONLY valid JSON. No markdown. All fields in English."""

            try:
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = msg.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                proposed = json.loads(raw)
                proposals.append({
                    **proposed,
                    "branch_name": payload.branch_name,
                    "target_audience": ta if ta != "Unknown" else None,
                    "market": country if country != "Unknown" else None,
                    "primary_metric": metric,
                    "combo_ids": [c.combo_id for c in members],
                    "cohort_label": f"{ta} · {country} · {metric}",
                    "cohort_size": len(members),
                    "top_combo": top[0].combo_id if top else None,
                })
            except Exception:
                logger.warning("[bulk-generate] failed for cohort %s", (ta, country, metric))
                continue

        return {"success": True, "data": {"proposals": proposals, "total_combos": len(combos),
                "skipped": len(already_linked), "total_cohorts": len(groups)}, "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("[bulk-generate] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("")
def list_hypotheses(
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    human_desire: Optional[str] = None,
    hypothesis_category: Optional[str] = None,
    target_audience: Optional[str] = None,
    market: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        q = db.query(CreativeHypothesis)
        if branch_name:
            q = q.filter(CreativeHypothesis.branch_name == branch_name)
        if status:
            q = q.filter(CreativeHypothesis.status == status)
        if human_desire:
            q = q.filter(CreativeHypothesis.human_desire == human_desire)
        if hypothesis_category:
            q = q.filter(CreativeHypothesis.hypothesis_category == hypothesis_category)
        if target_audience:
            q = q.filter(CreativeHypothesis.target_audience == target_audience)
        if market:
            q = q.filter(CreativeHypothesis.market == market)
        total = q.count()
        rows = q.order_by(desc(CreativeHypothesis.created_at)).offset(offset).limit(limit).all()
        combo_ids = [r.combo_id for r in rows if r.combo_id]
        combos = {c.combo_id: c for c in db.query(AdCombo).filter(AdCombo.combo_id.in_(combo_ids)).all()}

        # Bulk-fetch junction links
        hyp_ids = [r.hypothesis_id for r in rows if r.hypothesis_id]
        links = db.query(HypothesisComboLink).filter(HypothesisComboLink.hypothesis_id.in_(hyp_ids)).all()
        linked_combo_ids = list({lk.combo_id for lk in links} - set(combo_ids))
        extra_combos = {c.combo_id: c for c in db.query(AdCombo).filter(AdCombo.combo_id.in_(linked_combo_ids)).all()}
        all_combos = {**combos, **extra_combos}
        links_by_hyp: dict[str, list[AdCombo]] = {}
        for lk in links:
            c = all_combos.get(lk.combo_id)
            if c:
                links_by_hyp.setdefault(lk.hypothesis_id, []).append(c)

        # Bulk-fetch latest approval status per hypothesis_id
        from app.models.approval import ComboApproval as _CA
        approval_statuses: dict[str, str] = {}
        if hyp_ids:
            approvals = db.query(_CA.hypothesis_id, _CA.status, _CA.submitted_at).filter(
                _CA.hypothesis_id.in_(hyp_ids)
            ).order_by(_CA.submitted_at.desc()).all()
            for a in approvals:
                if a.hypothesis_id not in approval_statuses:
                    approval_statuses[a.hypothesis_id] = a.status

        return {"success": True, "data": {"items": [
            _serialize(r, combos.get(r.combo_id), approval_statuses.get(r.hypothesis_id), linked_combos=links_by_hyp.get(r.hypothesis_id, []))
            for r in rows
        ], "total": total}, "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("")
def create_hypothesis(payload: HypothesisCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        data = payload.model_dump()
        combo_ids_to_link: list[str] = data.pop("combo_ids", None) or []
        if data.get("combo_id"):
            combo_ids_to_link = list({data["combo_id"], *combo_ids_to_link})

        # Auto-fill human_desire from branch brand identity
        if not data.get("human_desire") and data.get("branch_name"):
            brand = db.query(BrandIdentity).filter(BrandIdentity.branch_name == data["branch_name"]).first()
            if brand and brand.human_desires:
                desires = brand.human_desires if isinstance(brand.human_desires, list) else []
                data["human_desire"] = ", ".join(desires) if desires else None

        hyp = CreativeHypothesis(hypothesis_id=_next_hypothesis_id(db), **data)
        db.add(hyp)
        db.flush()

        for cid in combo_ids_to_link:
            db.add(HypothesisComboLink(hypothesis_id=hyp.hypothesis_id, combo_id=cid))

        db.commit()
        db.refresh(hyp)
        linked = db.query(AdCombo).filter(AdCombo.combo_id.in_(combo_ids_to_link)).all() if combo_ids_to_link else []
        return {"success": True, "data": _serialize(hyp, linked_combos=linked), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/{hypothesis_id}/combos")
def link_combos(hypothesis_id: str, payload: dict, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Add or remove combo links. Body: { combo_ids: [...], action: 'add'|'remove' }"""
    try:
        action = payload.get("action", "add")
        ids = payload.get("combo_ids", [])
        if action == "add":
            for cid in ids:
                existing = db.query(HypothesisComboLink).filter_by(hypothesis_id=hypothesis_id, combo_id=cid).first()
                if not existing:
                    db.add(HypothesisComboLink(hypothesis_id=hypothesis_id, combo_id=cid))
        elif action == "remove":
            db.query(HypothesisComboLink).filter(
                HypothesisComboLink.hypothesis_id == hypothesis_id,
                HypothesisComboLink.combo_id.in_(ids)
            ).delete(synchronize_session=False)
        db.commit()
        linked = db.query(AdCombo).join(
            HypothesisComboLink, HypothesisComboLink.combo_id == AdCombo.combo_id
        ).filter(HypothesisComboLink.hypothesis_id == hypothesis_id).all()
        return {"success": True, "data": {"linked_combos": [
            {"combo_id": c.combo_id, "ad_name": c.ad_name, "verdict": c.verdict,
             "roas": float(c.roas) if c.roas else None}
            for c in linked
        ]}, "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.patch("/{hypothesis_id}/result")
def update_hypothesis_result(
    hypothesis_id: str,
    payload: HypothesisResultUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        hyp = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id == hypothesis_id
        ).first()
        if not hyp:
            raise HTTPException(status_code=404, detail=f"Hypothesis not found: {hypothesis_id}")
        if payload.status not in HYPOTHESIS_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {payload.status}")

        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(hyp, field, value)

        if payload.status in ("validated", "refuted") and not hyp.validated_at:
            hyp.validated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(hyp)
        return {"success": True, "data": _serialize(hyp), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/{hypothesis_id}/analyze-brief")
def analyze_brief(
    hypothesis_id: str,
    payload: BriefAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Paste a creative brief + script — Claude extracts deep evidence,
    creative principle, human moment, and why it worked.

    Works on any status (running, validated, refuted) — most useful after
    results are in so the analysis is grounded in actual outcome.
    """
    try:
        hyp = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id == hypothesis_id
        ).first()
        if not hyp:
            raise HTTPException(status_code=404, detail=f"Hypothesis not found: {hypothesis_id}")

        from app.services.hypothesis_analysis_service import analyze_brief as _analyze
        result = _analyze(db, hyp, payload.brief_text, payload.script_text)
        if "error" in result:
            return {"success": False, "data": None, "error": result["error"],
                    "timestamp": datetime.now(timezone.utc).isoformat()}
        return {"success": True, "data": {**result, "hypothesis": _serialize(hyp)},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/{hypothesis_id}/analyze-vision")
def analyze_vision(
    hypothesis_id: str,
    payload: VisionAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze ad images (single or carousel) with Claude Vision.

    If image_urls is omitted and the hypothesis has a combo_id, images are
    auto-pulled from ad_materials via the combo's material_id.
    """
    try:
        hyp = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.hypothesis_id == hypothesis_id
        ).first()
        if not hyp:
            raise HTTPException(status_code=404, detail=f"Hypothesis not found: {hypothesis_id}")

        from app.services.hypothesis_analysis_service import analyze_vision as _analyze_vision
        result = _analyze_vision(db, hyp, payload.image_urls)
        if "error" in result:
            return {"success": False, "data": None, "error": result["error"],
                    "timestamp": datetime.now(timezone.utc).isoformat()}
        return {"success": True, "data": {**result, "hypothesis": _serialize(hyp)},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/by-combo/{combo_id}")
def hypotheses_for_combo(combo_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return hypotheses linked to a specific combo (for approval submit form)."""
    try:
        rows = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.combo_id == combo_id
        ).order_by(desc(CreativeHypothesis.created_at)).all()
        return {"success": True, "data": [_serialize(r) for r in rows],
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/summary/{branch_name}")
def hypothesis_summary(branch_name: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Learning Engine summary — validated learnings grouped by human_desire."""
    try:
        rows = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
        ).order_by(desc(CreativeHypothesis.validated_at)).all()

        by_desire: dict[str, list] = {}
        for h in rows:
            desire = h.human_desire or "Unknown"
            by_desire.setdefault(desire, []).append({
                "hypothesis_id": h.hypothesis_id,
                "creative_angle": h.creative_angle,
                "status": h.status,
                "primary_kpi": h.primary_kpi,
                "actual_roas": float(h.actual_roas) if h.actual_roas else None,
                "actual_ctr": float(h.actual_ctr) if h.actual_ctr else None,
                "learning": h.learning,
                "confidence_level": h.confidence_level,
            })

        return {"success": True, "data": {"branch_name": branch_name, "by_desire": by_desire,
                "total_validated": len(rows)},
                "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/benchmark/{branch_name}/{metric}")
def metric_benchmark(
    branch_name: str,
    metric: str,
    ta: Optional[str] = None,
    country: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return 60-day average of a creative metric for a branch.

    Optional query params:
    - ta: target audience (Solo/Couple/Friend/Group/Business) — filters campaigns by parsed TA
    - country: ISO alpha-2 (e.g. TW, VN) — filters ad_sets by parsed country

    Narrowing by ta+country gives a tighter baseline for benchmark hypotheses.
    """
    try:
        from datetime import date, timedelta
        from sqlalchemy import func, and_
        from app.models.metrics import MetricsCache
        from app.models.campaign import Campaign
        from app.models.ad_set import AdSet

        SUPPORTED = {"hook_rate", "thumb_stop_rate", "hold_rate", "CTR", "ctr", "booking_rate", "roas"}
        if metric not in SUPPORTED:
            return {"success": False, "data": None,
                    "error": f"Unsupported metric '{metric}'. Supported: {sorted(SUPPORTED)}",
                    "timestamp": datetime.now(timezone.utc).isoformat()}

        cutoff = date.today() - timedelta(days=60)

        # Base query: join metrics_cache → campaigns to filter by branch
        q = (
            db.query(MetricsCache)
            .join(Campaign, Campaign.id == MetricsCache.campaign_id)
            .filter(
                Campaign.branch_name == branch_name,
                MetricsCache.date >= cutoff,
                MetricsCache.ad_id.isnot(None),         # ad-level rows only
                MetricsCache.impressions > 0,
            )
        )

        # Narrow by TA (parsed on campaign) if provided
        if ta:
            q = q.filter(Campaign.ta == ta)

        # Narrow by country (parsed on adset) if provided
        if country:
            q = (
                q.join(AdSet, AdSet.id == MetricsCache.ad_set_id)
                .filter(AdSet.country == country.upper())
            )

        rows = q.all()

        if not rows:
            return {"success": True, "data": {"branch_name": branch_name, "metric": metric,
                    "average": None, "sample_size": 0, "note": "No data in last 60 days"},
                    "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}

        values: list[float] = []
        for r in rows:
            imp = r.impressions or 0
            if imp == 0:
                continue
            if metric in ("hook_rate", "thumb_stop_rate"):
                # 3s video views / impressions
                if r.video_3s_views:
                    values.append(r.video_3s_views / imp * 100)
            elif metric == "hold_rate":
                # thruplay / impressions
                if r.video_thru_plays:
                    values.append(r.video_thru_plays / imp * 100)
            elif metric in ("CTR", "ctr"):
                if r.ctr:
                    values.append(float(r.ctr) * 100)
            elif metric == "booking_rate":
                # conversions / clicks
                if r.clicks and r.conversions:
                    values.append(float(r.conversions) / r.clicks * 100)
            elif metric == "roas":
                if r.roas:
                    values.append(float(r.roas))

        if not values:
            return {"success": True, "data": {"branch_name": branch_name, "metric": metric,
                    "average": None, "sample_size": 0, "note": "Metric not present in data"},
                    "error": None, "timestamp": datetime.now(timezone.utc).isoformat()}

        average = round(sum(values) / len(values), 2)
        return {
            "success": True,
            "data": {
                "branch_name": branch_name,
                "metric": metric,
                "average": average,
                "sample_size": len(values),
                "unit": "x" if metric == "roas" else "percent",
                "period_days": 60,
                "ta": ta or None,
                "country": country or None,
            },
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("[benchmark] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/learning-dashboard/{branch_name}")
def learning_dashboard(branch_name: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Learning Dashboard — win rates by desire, category, angle, and funnel-stage failure map."""
    try:
        from collections import defaultdict

        MIN_SAMPLE = 5  # spec §5: below this, result is greyed "insufficient data"

        concluded = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted"]),
        ).all()

        all_hyps = db.query(CreativeHypothesis).filter(
            CreativeHypothesis.branch_name == branch_name,
            CreativeHypothesis.status.in_(["validated", "refuted", "inconclusive", "running"]),
        ).all()

        # ── Desire Win Rate ──────────────────────────────────────────────
        # spec: validated / (validated + refuted) per desire, not raw count
        desire_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if not h.human_desire:
                continue
            desire_stats[h.human_desire]["total"] += 1
            if h.status == "validated":
                desire_stats[h.human_desire]["wins"] += 1
        top_desires = sorted(
            [
                {
                    "desire": d,
                    "win_rate": round(v["wins"] / v["total"] * 100, 0),
                    "experiments": v["total"],
                    "wins": v["wins"],
                    "sufficient": v["total"] >= MIN_SAMPLE,
                }
                for d, v in desire_stats.items() if v["total"] > 0
            ],
            key=lambda x: (-x["sufficient"], -x["win_rate"]),
        )[:8]

        # ── Decision Driver Win Rate (hypothesis_category) ────────────────
        cat_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if not h.hypothesis_category:
                continue
            cat_stats[h.hypothesis_category]["total"] += 1
            if h.status == "validated":
                cat_stats[h.hypothesis_category]["wins"] += 1
        top_drivers = sorted(
            [
                {
                    "category": c.replace("_", " ").title(),
                    "raw": c,
                    "win_rate": round(v["wins"] / v["total"] * 100, 0),
                    "experiments": v["total"],
                    "sufficient": v["total"] >= MIN_SAMPLE,
                }
                for c, v in cat_stats.items() if v["total"] > 0
            ],
            key=lambda x: (-x["sufficient"], -x["win_rate"]),
        )

        # ── Angle Win Rate — ONE table, sorted by win rate ────────────────
        # spec: an angle appears only once; grey if below min sample
        angle_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
        for h in concluded:
            if not h.creative_angle:
                continue
            angle_stats[h.creative_angle]["total"] += 1
            if h.status == "validated":
                angle_stats[h.creative_angle]["wins"] += 1
        angle_win_rates = sorted(
            [
                {
                    "angle": angle,
                    "wins": v["wins"],
                    "total": v["total"],
                    "win_rate": round(v["wins"] / v["total"] * 100, 0) if v["total"] > 0 else 0,
                    "sufficient": v["total"] >= MIN_SAMPLE,
                }
                for angle, v in angle_stats.items()
            ],
            key=lambda x: (-x["sufficient"], -x["win_rate"]),
        )

        # ── Funnel-Stage Failure Map ──────────────────────────────────────
        # spec §6 (new card): % of refutes at Stop/Hold/Click/Downstream
        stage_stats: dict[str, dict] = defaultdict(lambda: {"refutes": 0, "total": 0})
        for h in concluded:
            if not h.funnel_stage:
                continue
            stage_stats[h.funnel_stage]["total"] += 1
            if h.status == "refuted":
                stage_stats[h.funnel_stage]["refutes"] += 1
        funnel_failure_map = {
            stage: {
                "refutes": v["refutes"],
                "total": v["total"],
                "refute_rate": round(v["refutes"] / v["total"] * 100, 0) if v["total"] > 0 else 0,
            }
            for stage, v in stage_stats.items()
        }

        # ── Recent validated learnings ─────────────────────────────────────
        recent = sorted(
            [h for h in concluded if h.status == "validated" and h.learning],
            key=lambda x: x.validated_at or x.created_at,
            reverse=True,
        )[:5]
        recent_learnings = [
            {
                "hypothesis_id": h.hypothesis_id,
                "learning": h.learning,
                "human_desire": h.human_desire,
                "funnel_stage": h.funnel_stage,
                "target_audience": h.target_audience,
                "market": h.market,
                "validated_at": h.validated_at.isoformat() if h.validated_at else None,
            }
            for h in recent
        ]

        return {
            "success": True,
            "data": {
                "branch_name": branch_name,
                "total_experiments": len(concluded),
                "total_running": sum(1 for h in all_hyps if h.status == "running"),
                "total_validated": sum(1 for h in concluded if h.status == "validated"),
                "total_refuted": sum(1 for h in concluded if h.status == "refuted"),
                "min_sample": MIN_SAMPLE,
                "top_desires": top_desires,
                "top_drivers": top_drivers,
                "angle_win_rates": angle_win_rates,
                "funnel_failure_map": funnel_failure_map,
                "recent_learnings": recent_learnings,
            },
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("[learning-dashboard] failed")
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}
