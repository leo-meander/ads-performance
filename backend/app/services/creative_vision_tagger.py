"""Creative Intelligence Phase 1 — vision tagger.

Calls Claude Sonnet's vision API with each material's preview URL and stores
structured tags on creative_visual_tags. The model is asked to emit a strict
JSON schema covering 7 visual dimensions (text density, hook type, CTA, palette,
human presence, scene type, emotional angle).

Batching: `tag_pending_materials` walks ad_materials WHERE vision_analyzed_at
IS NULL OR vision_model != current model. The Zeabur cron endpoint
/internal/tasks/vision-tag-materials calls this with a small limit (default 25)
so a single cron tick stays under the 225s ingress budget.

Cost envelope (claude-sonnet-4-6 vision):
  ~1024-token image + ~600 input + ~200 output ≈ $0.012 / material.

The tagger never throws — failures land on the material row with vision_model
set to "FAILED:<reason-prefix>" so we don't re-retry endlessly. Operators can
clear vision_analyzed_at manually to re-queue.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from anthropic import Anthropic
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.ad_material import AdMaterial
from app.models.creative_visual_tag import CreativeVisualTag

logger = logging.getLogger(__name__)

VISION_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 600

# Allowed values per category. The tagger drops any model output that doesn't
# match this whitelist so downstream code can rely on a finite vocabulary.
TAG_VOCAB: dict[str, set[str]] = {
    "text_density": {"minimal", "medium", "heavy"},
    "hook_type": {
        "question", "statistic", "benefit", "story", "direct_offer", "other",
    },
    "cta_visible": {"yes", "no"},
    "color_palette": {
        "warm", "cool", "neutral", "high_contrast", "pastel", "dark", "other",
    },
    "human_presence": {"solo", "couple", "group", "none"},
    "scene_type": {
        "room", "exterior", "food", "activity", "aerial", "abstract", "mixed",
    },
    "emotional_angle": {
        "aspirational", "calm", "urgency", "informational", "playful", "luxe", "other",
    },
}

SYSTEM_PROMPT = """You are an ad-creative analyst. Look at the attached image and emit a strict JSON object describing it.

Use ONLY values from the allowed vocabulary for each category. Multiple values are allowed when the image truly fits more than one (e.g. a montage with both room + exterior shots), but most categories should have one value.

Output format (no commentary, JUST JSON):

{
  "text_density":   { "values": ["minimal" | "medium" | "heavy"], "confidence": 0.0-1.0 },
  "hook_type":      { "values": ["question" | "statistic" | "benefit" | "story" | "direct_offer" | "other"], "confidence": 0.0-1.0 },
  "cta_visible":    { "values": ["yes" | "no"], "confidence": 0.0-1.0 },
  "color_palette":  { "values": ["warm" | "cool" | "neutral" | "high_contrast" | "pastel" | "dark" | "other"], "confidence": 0.0-1.0 },
  "human_presence": { "values": ["solo" | "couple" | "group" | "none"], "confidence": 0.0-1.0 },
  "scene_type":     { "values": ["room" | "exterior" | "food" | "activity" | "aerial" | "abstract" | "mixed"], "confidence": 0.0-1.0 },
  "emotional_angle":{ "values": ["aspirational" | "calm" | "urgency" | "informational" | "playful" | "luxe" | "other"], "confidence": 0.0-1.0 }
}

If you cannot see the image clearly enough to judge a category, use the "other" / "none" / "no" / "minimal" fallback for that category and set confidence to 0.3 or less. NEVER invent categories outside the schema."""


class _VisionTagResult:
    __slots__ = ("tags", "raw_response", "error")

    def __init__(
        self,
        tags: list[tuple[str, str, Optional[Decimal]]],
        raw_response: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.tags = tags
        self.raw_response = raw_response
        self.error = error


def _call_claude_vision(
    client: Anthropic, image_url: str
) -> _VisionTagResult:
    """One vision call. Returns parsed (category, value, confidence) tuples or an error."""
    try:
        resp = client.messages.create(
            model=VISION_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "url", "url": image_url},
                        },
                        {
                            "type": "text",
                            "text": "Tag this ad creative using the schema. JSON only.",
                        },
                    ],
                }
            ],
        )
    except Exception as e:
        return _VisionTagResult(tags=[], error=f"api_error: {e!r}"[:200])

    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    raw = (text_blocks[0] if text_blocks else "").strip()
    # Some models wrap in ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`")
        # Strip a leading "json\n"
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _VisionTagResult(tags=[], raw_response=raw, error="invalid_json")

    out: list[tuple[str, str, Optional[Decimal]]] = []
    for category, allowed in TAG_VOCAB.items():
        block = parsed.get(category)
        if not isinstance(block, dict):
            continue
        values = block.get("values") or []
        confidence_raw = block.get("confidence")
        try:
            confidence = (
                Decimal(str(confidence_raw)).quantize(Decimal("0.001"))
                if confidence_raw is not None
                else None
            )
        except (TypeError, ValueError):
            confidence = None

        for v in values:
            if isinstance(v, str) and v in allowed:
                out.append((category, v, confidence))

    return _VisionTagResult(tags=out, raw_response=raw)


def tag_material(
    db: Session,
    material: AdMaterial,
    *,
    client: Optional[Anthropic] = None,
) -> dict[str, Any]:
    """Score one material and upsert its visual tags.

    Returns a summary dict: {material_id, status, tags_written, error?}.

    Skips video / carousel materials — vision is image-only for now (a video
    tagging path will sample N frames in a follow-up).
    """
    if not material.file_url:
        material.vision_analyzed_at = datetime.now(timezone.utc)
        material.vision_model = "FAILED:no_url"
        return {"material_id": material.material_id, "status": "skipped", "reason": "no_file_url"}

    if (material.material_type or "").lower() != "image":
        material.vision_analyzed_at = datetime.now(timezone.utc)
        material.vision_model = "FAILED:non_image"
        return {
            "material_id": material.material_id,
            "status": "skipped",
            "reason": f"material_type={material.material_type}",
        }

    if client is None:
        if not settings.ANTHROPIC_API_KEY:
            return {
                "material_id": material.material_id,
                "status": "error",
                "error": "ANTHROPIC_API_KEY not configured",
            }
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    result = _call_claude_vision(client, material.file_url)

    if result.error and not result.tags:
        material.vision_analyzed_at = datetime.now(timezone.utc)
        material.vision_model = f"FAILED:{result.error}"[:40]
        return {"material_id": material.material_id, "status": "error", "error": result.error}

    # Wipe prior tags from THIS material (fresh re-tag), then insert.
    db.query(CreativeVisualTag).filter(
        CreativeVisualTag.material_id == material.material_id
    ).delete(synchronize_session=False)

    written = 0
    for category, value, confidence in result.tags:
        db.add(CreativeVisualTag(
            material_id=material.material_id,
            tag_category=category,
            tag_value=value,
            confidence=confidence,
            model_version=VISION_MODEL,
        ))
        written += 1

    material.vision_analyzed_at = datetime.now(timezone.utc)
    material.vision_model = VISION_MODEL

    return {
        "material_id": material.material_id,
        "status": "ok",
        "tags_written": written,
    }


def tag_pending_materials(
    db: Session,
    *,
    limit: int = 25,
    client: Optional[Anthropic] = None,
) -> dict[str, Any]:
    """Tag the next batch of materials with no fresh vision tags.

    Targets materials where vision_analyzed_at IS NULL, OR vision_model differs
    from the current VISION_MODEL constant (model-upgrade re-tagging). Failed
    rows (vision_model starting with "FAILED:") are NOT re-picked here — clear
    the column manually if you want to retry.

    Caps at `limit` rows per call to stay under the cron 225s budget.
    """
    rows = (
        db.query(AdMaterial)
        .filter(AdMaterial.material_type == "image")
        .filter(
            or_(
                AdMaterial.vision_analyzed_at.is_(None),
                AdMaterial.vision_model != VISION_MODEL,
            )
        )
        .filter(
            or_(
                AdMaterial.vision_model.is_(None),
                ~AdMaterial.vision_model.like("FAILED:%"),
            )
        )
        .order_by(AdMaterial.created_at.asc())
        .limit(limit)
        .all()
    )

    summary = {"scanned": len(rows), "tagged": 0, "errors": 0, "skipped": 0, "results": []}
    if not rows:
        return summary

    if client is None:
        if not settings.ANTHROPIC_API_KEY:
            summary["errors"] = len(rows)
            summary["results"] = [
                {"material_id": m.material_id, "status": "error", "error": "ANTHROPIC_API_KEY not configured"}
                for m in rows
            ]
            return summary
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    for material in rows:
        try:
            r = tag_material(db, material, client=client)
        except Exception as e:
            logger.exception("Vision tagger crashed on %s", material.material_id)
            r = {"material_id": material.material_id, "status": "error", "error": str(e)}
            material.vision_analyzed_at = datetime.now(timezone.utc)
            material.vision_model = "FAILED:exception"

        summary["results"].append(r)
        if r["status"] == "ok":
            summary["tagged"] += 1
        elif r["status"] == "skipped":
            summary["skipped"] += 1
        else:
            summary["errors"] += 1

    db.commit()
    return summary
