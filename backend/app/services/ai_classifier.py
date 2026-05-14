"""AI-powered ad transcript classifier using Claude API.

Analyzes video transcripts to suggest:
- Angle type (one of 13 strategic types)
- Angle explanation
- Hook examples
- Keypoints (selling points)
- Target audience
"""

import json
import logging

import anthropic

from app.config import settings
from app.models.ad_angle import ANGLE_TYPES

logger = logging.getLogger(__name__)

# Build the angle types list for the prompt
_ANGLE_LIST = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(ANGLE_TYPES))

SYSTEM_PROMPT = """You are an expert advertising strategist for the hospitality industry (hotels, restaurants, resorts).

You analyze ad video transcripts and classify them into strategic categories.

IMPORTANT: Respond ONLY with valid JSON. No markdown, no code blocks, no extra text."""

CLASSIFY_PROMPT = """Analyze this ad video transcript and classify it.

## Transcript
{transcript}

## Context
- Branch/Brand: {branch_name}
- Language detected: {language}

## Tasks

1. **Angle Type** — Pick the BEST matching angle from these 13 types:
{angle_types}

2. **Angle Explanation** — Why this angle works for this specific ad (1-2 sentences)

3. **Hook Examples** — Extract or suggest 2-3 scroll-stopping hook lines from the transcript

4. **Keypoints** — Extract selling points mentioned in the transcript. Each keypoint has:
   - category: one of "location", "amenity", "experience", "value"
   - title: the specific selling point (max 100 chars)

5. **Target Audience** — Who is this ad targeting? One of: Solo, Couple, Family, Group, Business, or null if unclear

6. **Tone** — The overall tone: emotional, informational, urgency, aspirational, humorous, testimonial, or storytelling

7. **Summary** — One-line summary of what the ad is about (max 150 chars)

## Response Format (JSON only)
{{
  "suggested_angle_type": "exact angle type string from the list above",
  "suggested_angle_explain": "why this angle works",
  "suggested_hook_examples": ["hook 1", "hook 2"],
  "suggested_keypoints": [
    {{"category": "experience", "title": "specific selling point"}},
    {{"category": "amenity", "title": "another selling point"}}
  ],
  "detected_ta": "Solo|Couple|Family|Group|Business|null",
  "tone": "emotional|informational|urgency|aspirational|humorous|testimonial|storytelling",
  "summary": "one-line summary"
}}"""


def classify_transcript(
    transcript: str,
    branch_name: str = "Unknown",
    language: str = "en",
) -> dict:
    """Use Claude API to classify a video transcript into angle + keypoints.

    Returns dict with suggested_angle_type, suggested_keypoints, etc.
    Raises on API error.
    """
    if not transcript or len(transcript.strip()) < 10:
        raise ValueError("Transcript too short to analyze")

    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured in .env")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_prompt = CLASSIFY_PROMPT.format(
        transcript=transcript,
        branch_name=branch_name,
        language=language,
        angle_types=_ANGLE_LIST,
    )

    logger.info("Calling Claude API for transcript classification (%d chars)...", len(transcript))

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract text response
    response_text = message.content[0].text.strip()

    # Parse JSON — handle markdown code blocks if present
    if response_text.startswith("```"):
        # Remove code block markers
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        response_text = "\n".join(lines)

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude response as JSON: %s", response_text[:200])
        raise ValueError(f"Claude returned invalid JSON: {e}")

    # Validate angle type
    if result.get("suggested_angle_type") not in ANGLE_TYPES:
        # Try fuzzy match
        suggested = result.get("suggested_angle_type", "")
        for at in ANGLE_TYPES:
            if suggested.lower() in at.lower() or at.lower() in suggested.lower():
                result["suggested_angle_type"] = at
                break
        else:
            logger.warning("Unknown angle type returned: %s", suggested)

    logger.info(
        "Classification complete: angle=%s, %d keypoints, ta=%s",
        result.get("suggested_angle_type", "?"),
        len(result.get("suggested_keypoints", [])),
        result.get("detected_ta", "?"),
    )

    return result
