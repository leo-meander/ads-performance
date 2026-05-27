"""AI Creative Brief generator.

Takes a target audience + branch + optional vibe text and produces N brief
variants grounded in the branch's actual winning patterns. The generator
is read-only — it never creates ads, just a brief the designer (or the
Figma job pipeline) can act on.

Pipeline:
  1. Pull the top-performing combos for the requested filters (verdict=WIN
     preferred; falls back to TEST sorted by ROAS when WINs are sparse).
  2. If `vibe` text is present, fetch nearest-neighbour combos via
     embedding_service for additional inspiration (works on Postgres only).
  3. Aggregate the patterns: most-used angle, top keypoints, common visual
     tags, hook/CTA patterns from copies.
  4. Hand the structured pattern summary to Claude Sonnet, ask for 3 brief
     variants with strict JSON output.
  5. Optionally pair each brief with a recommended figma_templates row
     (matched by branch + platform + size).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Optional

from anthropic import Anthropic
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.creative_visual_tag import CreativeVisualTag
from app.models.figma import FigmaTemplate
from app.models.keypoint import BranchKeypoint

logger = logging.getLogger(__name__)

BRIEF_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1500
MAX_PATTERNS = 12  # how many top performers feed the model


IMAGE_SYSTEM_PROMPT = """You are a senior performance-marketing strategist for MEANDER Group hotels.

Given a structured summary of the branch's winning ads, generate distinct creative brief variants the designer can execute. Each brief must be grounded in the patterns provided — do NOT invent new claims, prices, or amenities. If a pattern isn't supported by the input, do not assert it.

Output STRICT JSON only — no markdown, no commentary:

{
  "briefs": [
    {
      "title":         "Short label, max 8 words",
      "hook":          "Headline copy, max 60 chars",
      "subhead":       "Optional secondary line, max 120 chars",
      "cta":           "Action verb phrase, max 24 chars",
      "angle":         "One of the 13 strategic angle names",
      "keypoints":     ["keypoint title 1", "keypoint title 2"],
      "visual_direction": {
        "scene":         "room | exterior | food | activity | aerial | abstract | mixed",
        "human_presence":"solo | couple | group | none",
        "color_palette": "warm | cool | neutral | high_contrast | pastel | dark",
        "emotional_angle":"aspirational | calm | urgency | informational | playful | luxe"
      },
      "visual_description": "One concrete sentence describing the literal scene to shoot/design — who is in it, where, doing what. e.g. 'Solo female traveler from Singapore relaxing on a dorm bunk by the window with a city view'",
      "rationale":    "1-2 sentences citing which inputs justify the choice"
    }
  ]
}

Generate exactly the number of briefs the user asks for. Each brief must have a meaningfully different hook + visual direction — don't paraphrase the same idea three times.

Write hook, subhead, cta, keypoints, and visual_description in the language the user requests (default English). Keep all JSON keys and the visual_direction enum values in English."""


VIDEO_SYSTEM_PROMPT = """You are a senior performance-marketing strategist + video scriptwriter for MEANDER Group hotels.

Given a structured summary of the branch's winning VIDEO ads, generate distinct video-ad brief variants the editor can shoot/cut. Ground every brief in the patterns provided — do NOT invent claims, prices, or amenities not supported by the input.

Output STRICT JSON only — no markdown, no commentary:

{
  "briefs": [
    {
      "title":   "Short label, max 8 words",
      "concept": "One sentence: the core scroll-stopping idea",
      "duration_sec": 30,
      "script": [
        {
          "time":           "0:00-0:05",
          "visual":         "What's on screen this beat — who, where, action; add a pacing note like (speed x2) or (slow-mo) when relevant",
          "on_screen_text": "Caption shown on screen this beat",
          "voiceover":      "VO line for this beat"
        }
      ],
      "production": {
        "voiceover": "Tone + 2-3 suggested ElevenLabs voice names",
        "music":     "Background-music direction + a sound cue (e.g. Whoosh / camera shutter) on the first transition",
        "captions":  "Caption style + font note",
        "cta":       "End-card on-screen button text + placement"
      },
      "keypoints":  ["keypoint title 1", "keypoint title 2"],
      "rationale":  "1-2 sentences citing which inputs justify the choices"
    }
  ]
}

House style (follow unless the patterns clearly suggest otherwise):
- Land the hook in the first 0-3 seconds. Total length ~25-45s, 5-7 beats.
- Voiceover: Energetic + Friendly tone; suggest natural ElevenLabs voices (e.g. Bella, Antoni, Rachel).
- Music: upbeat; open with a Whoosh or camera-shutter sound on the first transition.
- Captions: primary-language text centered, plus a small localized subtitle when a market needs it; modern sans-serif (Montserrat / The Bold Font).
- End on a fake on-screen button ("Book Now" / "Check Availability").

Each variant must be a meaningfully different concept. Write concept, visual, on_screen_text, voiceover, and keypoints in the language the user requests (default English). Keep all JSON keys in English."""


def _system_prompt(ad_format: str) -> str:
    return VIDEO_SYSTEM_PROMPT if ad_format == "video" else IMAGE_SYSTEM_PROMPT


def _max_tokens(ad_format: str) -> int:
    # Video scripts are longer (beat-by-beat) — give the model more room.
    return 3000 if ad_format == "video" else MAX_TOKENS


# ── Entry point ──────────────────────────────────────────────


def generate_brief(
    db: Session,
    *,
    branch_id: str,
    target_audience: Optional[str] = None,
    country: Optional[str] = None,
    vibe: Optional[str] = None,
    n_variants: int = 3,
    performance_goal: str = "roas",
    language: Optional[str] = None,
    ad_format: str = "image",
    client: Optional[Anthropic] = None,
) -> dict[str, Any]:
    """Build an AI brief grounded in the branch's winning patterns.

    Returns a dict with the model's brief variants + the patterns that fed it +
    a short list of recommended figma_templates.
    """
    if n_variants <= 0 or n_variants > 6:
        raise ValueError("n_variants must be 1..6")

    branch = db.query(AdAccount).filter(AdAccount.id == branch_id).first()
    if not branch:
        raise ValueError(f"Branch {branch_id} not found")

    pattern = _gather_patterns(
        db,
        branch_id=branch_id,
        target_audience=target_audience,
        country=country,
        vibe=vibe,
        performance_goal=performance_goal,
        ad_format=ad_format,
    )

    if pattern["sample_size"] == 0:
        return {
            "branch_id": branch_id,
            "branch_name": branch.account_name,
            "patterns": pattern,
            "briefs": [],
            "templates": [],
            "warning": "No combos matched the filters — relax target_audience or country to seed the generator.",
        }

    # Call Claude Sonnet with the patterns to draft briefs
    if client is None:
        if not settings.ANTHROPIC_API_KEY:
            return {
                "branch_id": branch_id,
                "branch_name": branch.account_name,
                "patterns": pattern,
                "briefs": [],
                "templates": [],
                "error": "ANTHROPIC_API_KEY not configured",
            }
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_message = _build_user_prompt(
        branch_name=branch.account_name,
        target_audience=target_audience,
        country=country,
        vibe=vibe,
        n_variants=n_variants,
        language=language,
        ad_format=ad_format,
        pattern=pattern,
    )

    try:
        resp = client.messages.create(
            model=BRIEF_MODEL,
            max_tokens=_max_tokens(ad_format),
            system=_system_prompt(ad_format),
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.exception("Brief model call failed")
        return {
            "branch_id": branch_id,
            "branch_name": branch.account_name,
            "patterns": pattern,
            "briefs": [],
            "templates": [],
            "error": f"model_error: {e!r}"[:300],
        }

    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    raw = (text_blocks[0] if text_blocks else "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()

    try:
        parsed = json.loads(raw)
        briefs = parsed.get("briefs") or []
    except json.JSONDecodeError:
        briefs = []
        logger.warning("Brief model returned non-JSON: %s", raw[:200])

    templates = _recommend_templates(db, branch_id=branch_id, platform="meta")

    return {
        "branch_id": branch_id,
        "branch_name": branch.account_name,
        "filters": {
            "target_audience": target_audience,
            "country": country,
            "vibe": vibe,
            "language": language,
            "ad_format": ad_format,
            "performance_goal": performance_goal,
        },
        "patterns": pattern,
        "top_creatives": pattern.get("top_creatives", []),
        "briefs": briefs,
        "templates": templates,
    }


# ── Pattern aggregation ──────────────────────────────────────


def _gather_patterns(
    db: Session,
    *,
    branch_id: str,
    target_audience: Optional[str],
    country: Optional[str],
    vibe: Optional[str],
    performance_goal: str,
    ad_format: Optional[str] = None,
) -> dict[str, Any]:
    """Pull top performers + extract the patterns that feed the brief generator.

    When ad_format is given (image|video|carousel), only winners of that
    material_type seed the brief — so a video brief learns from video winners.
    """
    sort_col = {
        "roas": AdCombo.roas,
        "spend": AdCombo.spend,
        "conversions": AdCombo.conversions,
    }.get(performance_goal, AdCombo.roas)

    fmt = ad_format if ad_format in ("image", "video", "carousel") else None

    q = db.query(AdCombo).filter(AdCombo.branch_id == branch_id)
    if target_audience:
        q = q.filter(AdCombo.target_audience == target_audience)
    if country:
        q = q.filter(AdCombo.country == country.upper())
    if fmt:
        q = q.join(AdMaterial, AdMaterial.material_id == AdCombo.material_id).filter(
            AdMaterial.material_type == fmt
        )

    # Prefer WIN; fall back to TEST sorted by perf if WINs are thin
    win_q = q.filter(AdCombo.verdict == "WIN").order_by(desc(sort_col)).limit(MAX_PATTERNS)
    combos = win_q.all()
    if len(combos) < 3:
        # Top up with TEST/non-WIN by perf
        top_up = (
            q.filter(AdCombo.verdict != "LOSE")
            .order_by(desc(sort_col))
            .limit(MAX_PATTERNS - len(combos) + 3)
            .all()
        )
        seen = {c.id for c in combos}
        for c in top_up:
            if c.id not in seen:
                combos.append(c)
            if len(combos) >= MAX_PATTERNS:
                break

    # Top up with vibe-relevant combos via keyword match (no embeddings):
    # ILIKE the vibe text over ad_name + headline + body_text. The vibe also
    # flows into the model prompt directly, so this is just extra grounding.
    if vibe and vibe.strip() and len(combos) < MAX_PATTERNS:
        like = f"%{vibe.strip()}%"
        seen_ids = {c.combo_id for c in combos}
        vibe_q = (
            db.query(AdCombo)
            .outerjoin(AdCopy, AdCopy.copy_id == AdCombo.copy_id)
            .filter(AdCombo.branch_id == branch_id)
            .filter(AdCombo.verdict != "LOSE")
            .filter(
                (AdCombo.ad_name.ilike(like))
                | (AdCopy.headline.ilike(like))
                | (AdCopy.body_text.ilike(like))
            )
            .order_by(desc(sort_col))
            .limit(MAX_PATTERNS)
        )
        if fmt:
            vibe_q = vibe_q.join(
                AdMaterial, AdMaterial.material_id == AdCombo.material_id
            ).filter(AdMaterial.material_type == fmt)
        for c in vibe_q.all():
            if c.combo_id not in seen_ids:
                combos.append(c)
            if len(combos) >= MAX_PATTERNS:
                break

    if not combos:
        return {
            "sample_size": 0,
            "samples": [],
            "top_creatives": [],
            "angle_distribution": {},
            "angle_performance": {},
            "keypoint_distribution": {},
            "keypoint_performance": {},
            "visual_distribution": {},
            "headline_examples": [],
        }

    # Bulk-fetch joined entities
    copy_ids = {c.copy_id for c in combos if c.copy_id}
    material_ids = {c.material_id for c in combos if c.material_id}
    angle_ids = {c.angle_id for c in combos if c.angle_id}
    kp_ids: set[str] = set()
    for c in combos:
        if isinstance(c.keypoint_ids, list):
            kp_ids.update(c.keypoint_ids)

    copies = {c.copy_id: c for c in db.query(AdCopy).filter(AdCopy.copy_id.in_(copy_ids)).all()} if copy_ids else {}
    angles = {a.angle_id: a for a in db.query(AdAngle).filter(AdAngle.angle_id.in_(angle_ids)).all()} if angle_ids else {}
    keypoints = {k.id: k for k in db.query(BranchKeypoint).filter(BranchKeypoint.id.in_(kp_ids)).all()} if kp_ids else {}
    materials = {m.material_id: m for m in db.query(AdMaterial).filter(AdMaterial.material_id.in_(material_ids)).all()} if material_ids else {}
    visual_tags: dict[str, list[CreativeVisualTag]] = {}
    if material_ids:
        for t in db.query(CreativeVisualTag).filter(CreativeVisualTag.material_id.in_(material_ids)).all():
            visual_tags.setdefault(t.material_id, []).append(t)

    # Distributions
    angle_counter: Counter[str] = Counter()
    keypoint_counter: Counter[str] = Counter()
    visual_counter: Counter[str] = Counter()
    samples = []
    headlines = []

    for c in combos:
        if c.angle_id and c.angle_id in angles:
            angle = angles[c.angle_id]
            label = angle.angle_type or angle.hook or c.angle_id
            angle_counter[label] += 1
        if isinstance(c.keypoint_ids, list):
            for kid in c.keypoint_ids:
                kp = keypoints.get(kid)
                if kp:
                    keypoint_counter[kp.title] += 1
        if c.material_id and c.material_id in visual_tags:
            for tag in visual_tags[c.material_id]:
                visual_counter[f"{tag.tag_category}={tag.tag_value}"] += 1

        copy = copies.get(c.copy_id) if c.copy_id else None
        if copy:
            headlines.append(copy.headline)

        material = materials.get(c.material_id) if c.material_id else None
        samples.append({
            "combo_id": c.combo_id,
            "ad_name": c.ad_name,
            "verdict": c.verdict,
            "target_audience": c.target_audience,
            "country": c.country,
            "roas": float(c.roas) if c.roas is not None else None,
            "hook_rate": float(c.hook_rate) if c.hook_rate is not None else None,
            "thruplay_rate": float(c.thruplay_rate) if c.thruplay_rate is not None else None,
            "headline": copy.headline if copy else None,
            "material_type": material.material_type if material else None,
            "file_url": material.file_url if material else None,
        })

    # Top winning creatives the user can reference (highest ROAS first). These
    # are the same combos that seeded the brief — surfaced so the marketer can
    # tick one and drop its creative link into the brief.
    top_creatives = sorted(
        [s for s in samples if s["roas"] is not None],
        key=lambda s: s["roas"],
        reverse=True,
    )[:8]

    return {
        "sample_size": len(combos),
        "samples": samples,
        "top_creatives": top_creatives,
        "angle_distribution": dict(angle_counter.most_common(5)),
        "angle_performance": _angle_performance(db, branch_id, target_audience),
        "keypoint_distribution": dict(keypoint_counter.most_common(8)),
        "keypoint_performance": _keypoint_performance(db, branch_id, target_audience),
        "visual_distribution": dict(visual_counter.most_common(12)),
        "headline_examples": headlines[:8],
    }


def _keypoint_performance(
    db: Session, branch_id: str, target_audience: Optional[str]
) -> dict[str, dict[str, Any]]:
    """Per-keypoint ROAS for the branch (scoped to TA when given).

    Lets the marketer sanity-check the keypoints the brief leans on — keyed by
    keypoint title so the frontend can show ROAS next to each one. Aggregates
    spend/revenue across every combo that carries the keypoint, not just the
    sampled winners, so the figure reflects the keypoint's true track record.
    """
    q = db.query(AdCombo).filter(
        AdCombo.branch_id == branch_id,
        AdCombo.keypoint_ids.isnot(None),
    )
    if target_audience:
        q = q.filter(AdCombo.target_audience == target_audience)
    combos = q.all()
    if not combos:
        return {}

    ids: set[str] = set()
    for c in combos:
        if isinstance(c.keypoint_ids, list):
            ids.update(c.keypoint_ids)
    if not ids:
        return {}
    kps = {k.id: k for k in db.query(BranchKeypoint).filter(BranchKeypoint.id.in_(ids)).all()}

    agg: dict[str, dict[str, float]] = {}
    for c in combos:
        kl = c.keypoint_ids if isinstance(c.keypoint_ids, list) else []
        for kid in kl:
            kp = kps.get(kid)
            if not kp or not kp.title:
                continue
            a = agg.setdefault(kp.title, {"spend": 0.0, "revenue": 0.0, "conversions": 0, "combos": 0})
            a["spend"] += float(c.spend or 0)
            a["revenue"] += float(c.revenue or 0)
            a["conversions"] += int(c.conversions or 0)
            a["combos"] += 1

    out: dict[str, dict[str, Any]] = {}
    for title, a in agg.items():
        roas = a["revenue"] / a["spend"] if a["spend"] > 0 else None
        out[title] = {
            "roas": round(roas, 2) if roas is not None else None,
            "conversions": int(a["conversions"]),
            "combos": int(a["combos"]),
            "spend": round(a["spend"], 2),
        }
    return out


def _angle_performance(
    db: Session, branch_id: str, target_audience: Optional[str]
) -> dict[str, dict[str, Any]]:
    """Per-angle ROAS for the branch (scoped to TA when given).

    Keyed by the same angle label used in angle_distribution (angle_type or
    hook), so the frontend can show ROAS next to each angle.
    """
    q = db.query(AdCombo).filter(
        AdCombo.branch_id == branch_id,
        AdCombo.angle_id.isnot(None),
    )
    if target_audience:
        q = q.filter(AdCombo.target_audience == target_audience)
    combos = q.all()
    if not combos:
        return {}

    angle_ids = {c.angle_id for c in combos if c.angle_id}
    angles = {a.angle_id: a for a in db.query(AdAngle).filter(AdAngle.angle_id.in_(angle_ids)).all()}

    agg: dict[str, dict[str, float]] = {}
    for c in combos:
        a = angles.get(c.angle_id)
        if not a:
            continue
        label = a.angle_type or a.hook or c.angle_id
        d = agg.setdefault(label, {"spend": 0.0, "revenue": 0.0, "conversions": 0, "combos": 0})
        d["spend"] += float(c.spend or 0)
        d["revenue"] += float(c.revenue or 0)
        d["conversions"] += int(c.conversions or 0)
        d["combos"] += 1

    out: dict[str, dict[str, Any]] = {}
    for label, d in agg.items():
        roas = d["revenue"] / d["spend"] if d["spend"] > 0 else None
        out[label] = {
            "roas": round(roas, 2) if roas is not None else None,
            "conversions": int(d["conversions"]),
            "combos": int(d["combos"]),
            "spend": round(d["spend"], 2),
        }
    return out


_LANGUAGE_NAMES = {
    "en": "English",
    "vi": "Vietnamese",
    "zh": "Traditional Chinese",
    "ja": "Japanese",
}


def _build_user_prompt(
    *,
    branch_name: str,
    target_audience: Optional[str],
    country: Optional[str],
    vibe: Optional[str],
    n_variants: int,
    language: Optional[str],
    ad_format: str,
    pattern: dict[str, Any],
) -> str:
    """Stitch the pattern summary into a model-facing prompt."""
    lines = [
        f"Branch: {branch_name}",
        f"Ad format: {ad_format}",
        f"Number of brief variants requested: {n_variants}",
    ]
    if ad_format == "video":
        lines.append(
            "These are the branch's winning VIDEO ads. Prioritize a strong "
            "0-3s hook and produce a beat-by-beat script + production notes."
        )
    if target_audience:
        lines.append(f"Target audience: {target_audience}")
    if country:
        lines.append(f"Country / market: {country}")
    if language:
        lang_name = _LANGUAGE_NAMES.get(language.lower(), language)
        lines.append(f"Write all copy (hook, subhead, cta, keypoints, visual_description) in: {lang_name}")
    if vibe:
        lines.append(f"Desired vibe: {vibe}")
    lines.append("")
    lines.append(f"Sample size of winning ads: {pattern['sample_size']}")

    if pattern["angle_distribution"]:
        lines.append("Top angles in winners (count):")
        for name, count in pattern["angle_distribution"].items():
            lines.append(f"  - {name}: {count}")
    if pattern["keypoint_distribution"]:
        lines.append("Top keypoints in winners (count):")
        for name, count in pattern["keypoint_distribution"].items():
            lines.append(f"  - {name}: {count}")
    if pattern["visual_distribution"]:
        lines.append("Top visual tags in winners (count):")
        for name, count in pattern["visual_distribution"].items():
            lines.append(f"  - {name}: {count}")
    if pattern["headline_examples"]:
        lines.append("Headline / opening examples from winners:")
        for h in pattern["headline_examples"]:
            lines.append(f"  - {h}")

    if ad_format == "video":
        vids = [s for s in pattern.get("samples", []) if s.get("hook_rate") is not None][:6]
        if vids:
            lines.append("Winning video hook/thruplay rates (mirror what opens strong):")
            for s in vids:
                name = s.get("ad_name") or s.get("combo_id")
                lines.append(
                    f"  - {name}: hook_rate={s.get('hook_rate')}, thruplay={s.get('thruplay_rate')}"
                )

    lines.append("")
    lines.append("Generate the briefs as STRICT JSON per the system prompt schema.")
    return "\n".join(lines)


# ── Template recommendations ─────────────────────────────────


def _recommend_templates(
    db: Session, *, branch_id: str, platform: str = "meta", limit: int = 3
) -> list[dict[str, Any]]:
    """Top N active Figma templates the brief recipient can clone."""
    rows = (
        db.query(FigmaTemplate)
        .filter(FigmaTemplate.is_active.is_(True))
        .filter(FigmaTemplate.platform == platform)
        .filter(
            (FigmaTemplate.branch_id == branch_id)
            | (FigmaTemplate.branch_id.is_(None))
        )
        .order_by(FigmaTemplate.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "size": f"{t.width}x{t.height}",
            "preview_image_url": t.preview_image_url,
            "placeholder_keys": list((t.placeholder_schema or {}).keys()),
        }
        for t in rows
    ]
