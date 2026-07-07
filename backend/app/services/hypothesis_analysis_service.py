"""Analyze a creative brief + script to extract deep evidence and principles.

Given:
  - brief_text: the creative direction (what the ad is supposed to do)
  - script_text: actual script / dialogue / scene descriptions
  - hypothesis context: branch, human_desire, creative_angle, actual metrics

Returns:
  - evidence: qualitative observation of WHY metrics moved (hook, emotional arc,
              human moment, implicit promise)
  - creative_principle: abstracted reusable principle (e.g. "Permission to do
                        nothing is more aspirational than luxury amenities")
  - why_it_worked: psychological / behavioral explanation
  - human_moment: the specific human moment category (e.g. "Shared Meal",
                  "Morning Ritual", "Solo Stillness")
  - suggested_learning: one-line learning for the hypothesis.learning field

Reuses the same Anthropic client pattern as creative_brief_service.
"""
from __future__ import annotations

import json
import logging

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.models.creative_hypothesis import CreativeHypothesis

logger = logging.getLogger(__name__)

ANALYSIS_MODEL = "claude-sonnet-4-6"

_SYSTEM = """You are a senior creative strategist who specializes in decoding WHY ads work at a psychological level.

You will receive:
1. A creative brief (the intent)
2. A script or scene description (what was executed)
3. Performance metrics (what happened)
4. Hypothesis context (brand, desire, angle)

Your job is NOT to summarize the ad. Your job is to extract the DEEP PRINCIPLE — the human truth that made this work or fail.

Think in terms of:
- What human moment or behavior does this tap into?
- What is the viewer implicitly being promised?
- What psychological mechanism drove the result?
- What principle, if abstracted, could generate 10 other winning creatives?

Output STRICT JSON only — no markdown, no commentary:
{
  "evidence": "Qualitative observation of what specifically drove the result. Be specific about the creative element and the human response it triggered. 2-4 sentences.",
  "creative_principle": "The abstracted, reusable principle. Must be a complete sentence that could stand alone as a creative guideline. Does NOT mention the specific ad.",
  "why_it_worked": "Psychological or behavioral explanation. Reference known human behavior, not marketing jargon. 1-2 sentences.",
  "human_moment": "The specific human moment category this taps into. 2-4 words. Examples: Shared Meal, Morning Ritual, Solo Stillness, First Connection, Quiet Recovery.",
  "suggested_learning": "One sentence learning for the hypothesis record. Starts with the human_moment or principle, not the brand name."
}"""


def analyze_brief(
    db: Session,
    hypothesis: CreativeHypothesis,
    brief_text: str,
    script_text: str,
) -> dict:
    """Call Claude to extract evidence + principle from brief + script."""

    metrics_ctx = ""
    if hypothesis.actual_roas is not None:
        metrics_ctx += f"ROAS: {float(hypothesis.actual_roas):.2f}x  "
    if hypothesis.actual_ctr is not None:
        metrics_ctx += f"CTR: {float(hypothesis.actual_ctr)*100:.2f}%  "
    if hypothesis.actual_spend is not None:
        metrics_ctx += f"Spend: ${float(hypothesis.actual_spend):,.0f}"

    outcome = hypothesis.status  # validated / refuted / running

    user_msg = f"""BRAND: {hypothesis.branch_name}
HUMAN DESIRE: {hypothesis.human_desire or "—"}
CREATIVE ANGLE: {hypothesis.creative_angle or "—"}
OUTCOME: {outcome.upper()} {f"({metrics_ctx})" if metrics_ctx else ""}

--- BRIEF ---
{brief_text.strip()}

--- SCRIPT / SCENE ---
{script_text.strip()}

--- HYPOTHESIS ---
{hypothesis.hypothesis}

Now extract the deep evidence and creative principle."""

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
    except Exception as e:
        logger.exception("[hypothesis-analysis] Claude call failed")
        return {"error": str(e)}

    # Persist to hypothesis
    hypothesis.brief_text = brief_text
    hypothesis.script_text = script_text
    hypothesis.evidence = result.get("evidence")
    hypothesis.creative_principle = result.get("creative_principle")
    hypothesis.why_it_worked = result.get("why_it_worked")
    hypothesis.human_moment = result.get("human_moment")
    if result.get("suggested_learning") and not hypothesis.learning:
        hypothesis.learning = result.get("suggested_learning")

    db.add(hypothesis)
    db.commit()
    db.refresh(hypothesis)

    return result
