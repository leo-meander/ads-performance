"""Analyze a creative brief + script (or images) to extract deep evidence and principles.

Given:
  - brief_text + script_text: text-based creative analysis
  - image_urls: list of base64 data URLs or http(s) URLs (carousel = multiple)
  - hypothesis context: branch, human_desire, creative_angle, actual metrics

Returns:
  - evidence, creative_principle, why_it_worked, human_moment, suggested_learning

Reuses the same Anthropic client pattern as creative_brief_service.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

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


# ---------------------------------------------------------------------------
# Vision analysis (image / carousel)
# ---------------------------------------------------------------------------

_VISION_SYSTEM = """You are a senior creative strategist who decodes WHY visual ads work at a psychological level.

You will receive one or more ad images (single image or carousel slides) along with performance context.

Your job is to extract the DEEP PRINCIPLE from the visuals — not to describe what you see, but to decode the human truth being communicated.

Think in terms of:
- What human moment or behavior does the visual tap into?
- What emotion or implicit promise is being conveyed without words?
- What compositional or visual choice drove the viewer's response?
- What principle could generate 10 other winning visuals?

For carousel: also analyze the narrative arc across all slides — does it build tension, tell a story, or repeat a motif?

Output STRICT JSON only — no markdown, no commentary:
{
  "evidence": "What specific visual elements drove the result. Mention composition, color, human presence, text overlays, scene type. 2-4 sentences.",
  "creative_principle": "The abstracted, reusable visual principle. A complete sentence that could stand alone as a creative guideline. Does NOT mention the specific ad.",
  "why_it_worked": "Psychological or behavioral explanation for the visual impact. Reference known visual cognition or human behavior. 1-2 sentences.",
  "human_moment": "The specific human moment captured in the visual. 2-4 words. Examples: Shared Meal, Morning Ritual, Solo Stillness, First Connection, Quiet Recovery.",
  "suggested_learning": "One sentence learning. Starts with the human_moment or visual principle, not the brand name."
}"""


def _image_content_block(image_url: str) -> dict:
    """Build Anthropic image content block. Handles both data: URLs and http(s) URLs."""
    if image_url.startswith("data:"):
        header, _, b64 = image_url.partition(",")
        media_type = header[5:].split(";", 1)[0] or "image/jpeg"
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    return {
        "type": "image",
        "source": {"type": "url", "url": image_url},
    }


def _pull_combo_images(db: Session, combo_id: str) -> list[str]:
    """Load file_url(s) from ad_materials linked via the combo's material_id."""
    from app.models.ad_combo import AdCombo
    from app.models.ad_material import AdMaterial

    combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
    if not combo or not combo.material_id:
        return []

    material = db.query(AdMaterial).filter(
        AdMaterial.material_id == combo.material_id
    ).first()
    if not material or not material.file_url:
        return []

    # carousel: file_url may be JSON array of URLs, or single URL
    url = material.file_url
    if url.startswith("["):
        try:
            urls = json.loads(url)
            return [u for u in urls if u]
        except json.JSONDecodeError:
            pass
    return [url]


def analyze_vision(
    db: Session,
    hypothesis: CreativeHypothesis,
    image_urls: Optional[list[str]] = None,
) -> dict:
    """Call Claude Vision to extract evidence + principle from images.

    If image_urls is empty/None and hypothesis.combo_id is set, auto-pulls
    the material's file_url (base64 or live URL) from ad_materials.
    """
    # Auto-pull from combo if no images supplied
    if not image_urls and hypothesis.combo_id:
        image_urls = _pull_combo_images(db, hypothesis.combo_id)

    if not image_urls:
        return {"error": "No images available — either provide image_urls or link a combo with a material."}

    metrics_ctx = ""
    if hypothesis.actual_roas is not None:
        metrics_ctx += f"ROAS: {float(hypothesis.actual_roas):.2f}x  "
    if hypothesis.actual_ctr is not None:
        metrics_ctx += f"CTR: {float(hypothesis.actual_ctr)*100:.2f}%  "
    if hypothesis.actual_spend is not None:
        metrics_ctx += f"Spend: ${float(hypothesis.actual_spend):,.0f}"

    is_carousel = len(image_urls) > 1
    image_label = f"{len(image_urls)}-slide carousel" if is_carousel else "single image ad"

    text_intro = (
        f"BRAND: {hypothesis.branch_name}\n"
        f"HUMAN DESIRE: {hypothesis.human_desire or '—'}\n"
        f"CREATIVE ANGLE: {hypothesis.creative_angle or '—'}\n"
        f"FORMAT: {image_label}\n"
        f"OUTCOME: {hypothesis.status.upper()} {f'({metrics_ctx})' if metrics_ctx else ''}\n"
        f"HYPOTHESIS: {hypothesis.hypothesis}\n\n"
        f"{'Analyze all slides as a unified carousel narrative.' if is_carousel else 'Analyze the image and extract the deep visual principle.'}"
    )

    # Build content: text intro + all images
    content: list[dict] = [{"type": "text", "text": text_intro}]
    for i, url in enumerate(image_urls):
        if is_carousel:
            content.append({"type": "text", "text": f"Slide {i + 1}:"})
        content.append(_image_content_block(url))

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=800,
            system=_VISION_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
    except Exception as e:
        logger.exception("[hypothesis-vision] Claude call failed")
        return {"error": str(e)}

    # Persist same fields as brief analysis
    hypothesis.evidence = result.get("evidence")
    hypothesis.creative_principle = result.get("creative_principle")
    hypothesis.why_it_worked = result.get("why_it_worked")
    hypothesis.human_moment = result.get("human_moment")
    if result.get("suggested_learning") and not hypothesis.learning:
        hypothesis.learning = result.get("suggested_learning")

    db.add(hypothesis)
    db.commit()
    db.refresh(hypothesis)

    return {**result, "images_analyzed": len(image_urls), "format": image_label}
