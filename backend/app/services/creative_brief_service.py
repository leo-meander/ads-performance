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


SYSTEM_PROMPT = """You are a senior performance-marketing strategist for MEANDER Group hotels.

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
      "rationale":    "1-2 sentences citing which inputs justify the choice"
    }
  ]
}

Generate exactly the number of briefs the user asks for. Each brief must have a meaningfully different hook + visual direction — don't paraphrase the same idea three times."""


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
        pattern=pattern,
    )

    try:
        resp = client.messages.create(
            model=BRIEF_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
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
            "performance_goal": performance_goal,
        },
        "patterns": pattern,
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
) -> dict[str, Any]:
    """Pull top performers + extract the patterns that feed the brief generator."""
    sort_col = {
        "roas": AdCombo.roas,
        "spend": AdCombo.spend,
        "conversions": AdCombo.conversions,
    }.get(performance_goal, AdCombo.roas)

    q = db.query(AdCombo).filter(AdCombo.branch_id == branch_id)
    if target_audience:
        q = q.filter(AdCombo.target_audience == target_audience)
    if country:
        q = q.filter(AdCombo.country == country.upper())

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

    # Add semantic neighbours when vibe is present (Postgres only — silently
    # no-ops on SQLite tests).
    if vibe and db.bind.dialect.name == "postgresql":
        try:
            from app.services.embedding_service import cosine_search, embed_text
            qvec = embed_text(vibe, input_type="query")
            neighbour_ids = [
                pk for pk, _ in cosine_search(
                    db, "ad_combos", "combo_id", qvec, limit=10,
                    where_sql="branch_id = :b",
                    where_params={"b": branch_id},
                )
            ]
            seen_ids = {c.combo_id for c in combos}
            extra = [
                c for c in db.query(AdCombo).filter(AdCombo.combo_id.in_(neighbour_ids)).all()
                if c.combo_id not in seen_ids
            ]
            combos.extend(extra[: max(0, MAX_PATTERNS - len(combos))])
        except RuntimeError as e:
            logger.warning("Vibe embedding skipped: %s", e)

    if not combos:
        return {
            "sample_size": 0,
            "samples": [],
            "angle_distribution": {},
            "keypoint_distribution": {},
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

        samples.append({
            "combo_id": c.combo_id,
            "ad_name": c.ad_name,
            "verdict": c.verdict,
            "roas": float(c.roas) if c.roas is not None else None,
            "headline": copy.headline if copy else None,
        })

    return {
        "sample_size": len(combos),
        "samples": samples,
        "angle_distribution": dict(angle_counter.most_common(5)),
        "keypoint_distribution": dict(keypoint_counter.most_common(8)),
        "visual_distribution": dict(visual_counter.most_common(12)),
        "headline_examples": headlines[:8],
    }


def _build_user_prompt(
    *,
    branch_name: str,
    target_audience: Optional[str],
    country: Optional[str],
    vibe: Optional[str],
    n_variants: int,
    pattern: dict[str, Any],
) -> str:
    """Stitch the pattern summary into a model-facing prompt."""
    lines = [
        f"Branch: {branch_name}",
        f"Number of brief variants requested: {n_variants}",
    ]
    if target_audience:
        lines.append(f"Target audience: {target_audience}")
    if country:
        lines.append(f"Country / market: {country}")
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
        lines.append("Headline examples from winners:")
        for h in pattern["headline_examples"]:
            lines.append(f"  - {h}")

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
