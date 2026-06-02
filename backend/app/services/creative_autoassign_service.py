"""Auto-assign angle + keypoints to a combo — suggest → confirm flow.

Two stages, deliberately split so keypoint creation is never silent:

  suggest(...)  — reads the source text (combo copy / Figma frame / video
                  script), asks Claude to (a) match one of the 13 fixed
                  angles and (b) split benefits into MATCHED existing
                  keypoints vs PROPOSED new ones. Pure — no DB writes.

  apply(...)    — given the user's confirmed choices, creates the confirmed
                  new keypoints and stamps angle_id + keypoint_ids on the
                  combo. The only stage that writes.

This contrasts with the legacy angle_assign_service (post-sync, match-only):
that one never creates keypoints. This service is the interactive,
approval-time path.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from anthropic import Anthropic
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint

logger = logging.getLogger(__name__)

ASSIGN_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1200
KEYPOINT_CATEGORIES = ("location", "amenity", "experience", "value")


class AutoAssignError(ValueError):
    """Caller-facing error (4xx-style)."""


SYSTEM_PROMPT = """You are a hotel ad strategist. Given ad text + the available creative taxonomy, assign:

1. ANGLE — exactly one angle_id from the fixed list. Match the *hook approach* the headline takes.
2. KEYPOINTS — the selling points the ad highlights. For each one, decide:
   - If it matches an EXISTING keypoint (same meaning, even if worded differently) → reference its id.
   - If it's a genuinely new selling point not in the existing list → propose a new keypoint.
   Do NOT propose a new keypoint when an existing one already covers the idea — reuse aggressively.

   Each proposed keypoint must be SINGLE-FOCUS — one landmark / feature / fact, stated
   straight. Do NOT bundle. No em-dash tails that tack on extra description, no lists of
   examples, no "A + B", no parenthetical lists of venues. If the ad mentions several
   distinct things, split them into separate keypoints — one each. A trailing distance
   "(~300m)" or a place's own name "(阿宗麵線)" is fine; a tacked-on descriptor is not.
   Good:  "~5-min walk to Nguyen Hue Walking Street"
   Bad:   "~5-min walk to Nguyen Hue Walking Street — rooftop bars (Chill Skybar, Social Club, EON51)"

Output STRICT JSON only (no markdown):

{
  "angle_id": "ANG-XXX",
  "angle_confidence": 0.0-1.0,
  "angle_rationale": "one sentence — why this angle",
  "matched_keypoint_ids": ["<existing keypoint id>", ...],
  "proposed_keypoints": [
    {"title": "One single selling point, max 60 chars — no bundling",
     "category": "location | amenity | experience | value",
     "rationale": "one sentence — why it's new, not a duplicate"}
  ]
}

Keep proposed_keypoints minimal — only what existing keypoints genuinely don't cover."""


# ── Text source resolution ───────────────────────────────────


def _resolve_source_text(
    db: Session,
    *,
    combo: Optional[AdCombo],
    headline: Optional[str],
    benefits: Optional[list[str]],
    body_text: Optional[str],
    script_text: Optional[str],
    use_figma: bool,
    figma_client=None,
) -> dict[str, Any]:
    """Return {headline, benefits[], body, script, source} from whichever
    input the caller provided. Priority: script > figma > explicit text > combo copy."""
    if script_text and script_text.strip():
        return {
            "headline": "",
            "benefits": [],
            "body": "",
            "script": script_text.strip()[:6000],
            "source": "script",
        }

    if use_figma:
        if not combo:
            raise AutoAssignError("Figma source needs a combo_id to locate the material")
        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == combo.material_id)
            .first()
        )
        figma_file_key = getattr(material, "figma_file_key", None) if material else None
        figma_node_id = getattr(material, "figma_node_id", None) if material else None
        if not (figma_file_key and figma_node_id):
            raise AutoAssignError(
                "This combo's material has no figma_file_key / figma_node_id set — "
                "wire the Figma frame on the material first, or use the copy/script source."
            )
        from app.services.figma_client import FigmaClient
        client = figma_client or FigmaClient()
        placeholders = client.get_placeholders(figma_file_key, figma_node_id)
        text_slots = [p for p in placeholders if p.slot_type == "text"]
        # $headline → headline; $benefit_* / $subhead → benefits
        fh = next((p.characters for p in text_slots if p.name == "headline"), "")
        fbenefits = [
            p.characters for p in text_slots
            if p.name.startswith("benefit") or p.name in ("subhead", "location")
        ]
        return {
            "headline": fh,
            "benefits": [b for b in fbenefits if b],
            "body": "",
            "script": "",
            "source": "figma",
        }

    if headline or benefits or body_text:
        return {
            "headline": (headline or "").strip(),
            "benefits": [b.strip() for b in (benefits or []) if b and b.strip()],
            "body": (body_text or "").strip()[:1000],
            "script": "",
            "source": "explicit",
        }

    if combo:
        copy = (
            db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first()
            if combo.copy_id else None
        )
        if not copy:
            raise AutoAssignError(f"Combo {combo.combo_id} has no linked copy to analyze")
        return {
            "headline": copy.headline or "",
            "benefits": [],
            "body": (copy.body_text or "")[:1000],
            "script": "",
            "source": "combo_copy",
        }

    raise AutoAssignError("No source text — provide combo_id, headline/benefits, or script_text")


# ── Claude call ──────────────────────────────────────────────


def _build_user_prompt(
    src: dict[str, Any],
    angles: list[dict],
    existing_keypoints: list[dict],
) -> str:
    lines = ["AD TEXT:"]
    if src["headline"]:
        lines.append(f"Headline: {src['headline']}")
    if src["body"]:
        lines.append(f"Body: {src['body']}")
    if src["benefits"]:
        lines.append("Benefits / selling points:")
        for b in src["benefits"]:
            lines.append(f"  - {b}")
    if src["script"]:
        lines.append(f"Video script:\n{src['script']}")
    lines.append("")
    lines.append("AVAILABLE ANGLES (pick exactly one angle_id):")
    lines.append(json.dumps(angles, ensure_ascii=False, indent=1))
    lines.append("")
    lines.append("EXISTING KEYPOINTS for this branch (reuse by id when the meaning matches):")
    lines.append(json.dumps(existing_keypoints, ensure_ascii=False, indent=1))
    lines.append("")
    lines.append("Return the STRICT JSON object per the system prompt.")
    return "\n".join(lines)


def _call_claude(
    client: Anthropic,
    src: dict[str, Any],
    angles: list[dict],
    existing_keypoints: list[dict],
) -> dict[str, Any]:
    resp = client.messages.create(
        model=ASSIGN_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(src, angles, existing_keypoints)}],
    )
    blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    raw = (blocks[0] if blocks else "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    return json.loads(raw)


# ── Public: suggest ──────────────────────────────────────────


def suggest(
    db: Session,
    *,
    branch_id: str,
    combo_id: Optional[str] = None,
    headline: Optional[str] = None,
    benefits: Optional[list[str]] = None,
    body_text: Optional[str] = None,
    script_text: Optional[str] = None,
    use_figma: bool = False,
    client: Optional[Anthropic] = None,
    figma_client=None,
) -> dict[str, Any]:
    """Suggest an angle + keypoint split. NO DB writes.

    Returns:
      {
        "source": "combo_copy|figma|script|explicit",
        "angle": {"angle_id", "angle_type", "confidence", "rationale"} | None,
        "keypoints": {
          "matched": [{"id", "title", "category"}],     # existing
          "proposed": [{"title", "category", "rationale"}]  # NEW — not yet created
        }
      }
    """
    combo = None
    if combo_id:
        combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
        if not combo:
            raise AutoAssignError(f"Combo {combo_id} not found")
        if combo.branch_id != branch_id:
            # branch_id is authoritative for keypoint scoping; trust the combo's.
            branch_id = combo.branch_id

    src = _resolve_source_text(
        db,
        combo=combo,
        headline=headline,
        benefits=benefits,
        body_text=body_text,
        script_text=script_text,
        use_figma=use_figma,
        figma_client=figma_client,
    )

    angles = [
        {"angle_id": a.angle_id, "type": a.angle_type or "", "explain": (a.angle_explain or "")[:120]}
        for a in db.query(AdAngle).order_by(AdAngle.angle_id).all()
    ]
    if not angles:
        raise AutoAssignError("No angles seeded in the database")

    existing_kps = [
        {"id": k.id, "title": k.title, "category": k.category}
        for k in db.query(BranchKeypoint)
        .filter(BranchKeypoint.branch_id == branch_id)
        .filter(BranchKeypoint.is_active.is_(True))
        .all()
    ]

    if client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise AutoAssignError("ANTHROPIC_API_KEY not configured")
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        parsed = _call_claude(client, src, angles, existing_kps)
    except json.JSONDecodeError as e:
        raise AutoAssignError(f"Model returned invalid JSON: {e}") from e
    except Exception as e:
        raise AutoAssignError(f"Model call failed: {e!r}"[:200]) from e

    # Resolve the angle against the real list (guard against hallucinated ids).
    angle_by_id = {a.angle_id: a for a in db.query(AdAngle).all()}
    aid = parsed.get("angle_id")
    angle_out = None
    if aid and aid in angle_by_id:
        a = angle_by_id[aid]
        angle_out = {
            "angle_id": a.angle_id,
            "angle_type": a.angle_type or "",
            "confidence": parsed.get("angle_confidence"),
            "rationale": parsed.get("angle_rationale", ""),
        }

    # Matched keypoints — keep only ids that really exist on this branch.
    kp_by_id = {k["id"]: k for k in existing_kps}
    matched = [
        kp_by_id[i] for i in (parsed.get("matched_keypoint_ids") or []) if i in kp_by_id
    ]

    # Proposed keypoints — validate category, drop dupes vs existing titles.
    existing_titles = {k["title"].strip().lower() for k in existing_kps}
    proposed = []
    for p in parsed.get("proposed_keypoints") or []:
        title = (p.get("title") or "").strip()
        category = (p.get("category") or "").strip().lower()
        if not title or category not in KEYPOINT_CATEGORIES:
            continue
        if title.lower() in existing_titles:
            # Model proposed something we already have — treat as matched instead.
            existing = next(
                (k for k in existing_kps if k["title"].strip().lower() == title.lower()),
                None,
            )
            if existing and existing not in matched:
                matched.append(existing)
            continue
        proposed.append({
            "title": title[:200],
            "category": category,
            "rationale": p.get("rationale", ""),
        })

    return {
        "source": src["source"],
        "branch_id": branch_id,
        "combo_id": combo_id,
        "angle": angle_out,
        "keypoints": {"matched": matched, "proposed": proposed},
    }


# ── Public: apply ────────────────────────────────────────────


def apply(
    db: Session,
    *,
    combo_id: str,
    angle_id: Optional[str] = None,
    keypoint_ids: Optional[list[str]] = None,
    new_keypoints: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Persist the user's confirmed assignment.

    - Creates each `new_keypoints` row (title + category) on the combo's branch.
    - Sets combo.angle_id + combo.keypoint_ids (existing ids + freshly created).

    `keypoint_ids` are the existing ones the user kept; `new_keypoints` are the
    proposed ones the user confirmed.
    """
    combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
    if not combo:
        raise AutoAssignError(f"Combo {combo_id} not found")

    final_keypoint_ids: list[str] = list(keypoint_ids or [])

    created = []
    for nk in new_keypoints or []:
        title = (nk.get("title") or "").strip()
        category = (nk.get("category") or "").strip().lower()
        if not title or category not in KEYPOINT_CATEGORIES:
            continue
        # Guard against double-create: reuse an existing active keypoint with
        # the same branch + title (case-insensitive) if one already exists.
        existing = (
            db.query(BranchKeypoint)
            .filter(BranchKeypoint.branch_id == combo.branch_id)
            .filter(BranchKeypoint.is_active.is_(True))
            .filter(func.lower(BranchKeypoint.title) == title.lower())
            .first()
        )
        if existing:
            if existing.id not in final_keypoint_ids:
                final_keypoint_ids.append(existing.id)
            continue
        kp = BranchKeypoint(branch_id=combo.branch_id, category=category, title=title)
        db.add(kp)
        db.flush()
        created.append({"id": kp.id, "title": kp.title, "category": kp.category})
        final_keypoint_ids.append(kp.id)

    if angle_id is not None:
        combo.angle_id = angle_id or None
    if keypoint_ids is not None or new_keypoints:
        combo.keypoint_ids = final_keypoint_ids or None

    db.commit()
    return {
        "combo_id": combo_id,
        "angle_id": combo.angle_id,
        "keypoint_ids": combo.keypoint_ids or [],
        "created_keypoints": created,
    }
