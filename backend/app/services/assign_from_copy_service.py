"""Fill missing angle + keypoints on ad_combos by reading the ad copy text.

Text-only variant of angle_assign_service.py — does NOT fetch the material
image. Cheaper and survives image fetch failures. Different rules:

  - Angle: pick from existing angles ONLY (never creates new).
  - Keypoints: prefer reusing an existing branch keypoint; if the copy raises
    something the branch's library doesn't cover yet, CREATE a new keypoint
    for that branch (the image-based service can't do this).

Incremental: only touches combos where angle_id IS NULL OR keypoint_ids IS NULL.
Idempotent — re-running never overwrites a value that's already filled.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.keypoint import BranchKeypoint

logger = logging.getLogger(__name__)

BATCH = 8  # text-only → bigger batch than the vision flow (which uses 5)
VALID_CATEGORIES = {"location", "amenity", "experience", "value"}


def _load_anthropic_key() -> str:
    """Prefer process env (Zeabur Variables); fall back to .env for local dev."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        env_path = Path(__file__).resolve().parents[3] / ".env"
        return dotenv_values(env_path).get("ANTHROPIC_API_KEY", "") or ""
    except Exception:
        return ""


def assign_from_copy(db: Session) -> dict:
    """Fill missing angle + keypoints on combos from the ad copy text.

    Returns a summary dict: processed / updated / created_keypoints / skipped.
    """
    combos = (
        db.query(AdCombo)
        .filter((AdCombo.angle_id.is_(None)) | (AdCombo.keypoint_ids.is_(None)))
        .all()
    )
    if not combos:
        logger.info("assign-from-copy: nothing to fill")
        return {"processed": 0, "updated": 0, "created_keypoints": 0}

    api_key = _load_anthropic_key()
    if not api_key:
        logger.warning("assign-from-copy: ANTHROPIC_API_KEY missing — skipping")
        return {"processed": 0, "updated": 0, "skipped": "no_api_key"}

    client = Anthropic(api_key=api_key)

    accounts = {a.id: a.account_name for a in db.query(AdAccount).all()}
    copies = {c.copy_id: c for c in db.query(AdCopy).all()}

    # Existing keypoints per branch (active only). Updated in-place as we
    # create new ones during the run so subsequent batches can reuse them.
    keypoints = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True)).all()
    kps_by_branch: dict[str, list] = {}
    for kp in keypoints:
        kps_by_branch.setdefault(kp.branch_id, []).append(
            {"id": kp.id, "category": kp.category, "title": kp.title}
        )

    ang_rows = db.execute(
        text("SELECT angle_id, angle_type, angle_explain FROM ad_angles ORDER BY angle_id")
    ).fetchall()
    all_angles = [
        {"angle_id": r[0], "type": r[1] or "?", "explain": (r[2] or "")[:80]}
        for r in ang_rows
    ]
    if not all_angles:
        logger.info("assign-from-copy: no angles in DB — skipping")
        return {"processed": 0, "updated": 0, "skipped": "no_angles"}
    valid_angle_ids = {a["angle_id"] for a in all_angles}

    logger.info("assign-from-copy: %d combos to fill", len(combos))
    updated = 0
    created_keypoints = 0

    for i in range(0, len(combos), BATCH):
        batch = combos[i : i + BATCH]
        descriptions = []
        for combo in batch:
            copy = copies.get(combo.copy_id)
            descriptions.append({
                "combo_id": combo.combo_id,
                "branch_id": combo.branch_id,
                "branch": accounts.get(combo.branch_id, "?"),
                "ad_name": combo.ad_name or "",
                "headline": (copy.headline[:200] if copy else ""),
                "body": (copy.body_text[:600] if copy else ""),
            })

        branch_ids = list({c.branch_id for c in batch})
        existing_kps = {bid: kps_by_branch.get(bid, []) for bid in branch_ids}

        prompt = f"""You are filling missing tags on hotel ad combos by reading the ad copy text.

COMBOS (with branch and ad copy):
{json.dumps(descriptions, ensure_ascii=False, indent=1)}

AVAILABLE ANGLES (GLOBAL — pick any angle_id for any branch):
{json.dumps(all_angles, ensure_ascii=False, indent=1)}

EXISTING KEYPOINTS per branch_id (reuse these when the copy clearly matches):
{json.dumps(existing_kps, ensure_ascii=False, indent=1)}

For each combo:
1. Pick ONE angle_id from the available angles. Never invent a new angle.
2. Pick 1-3 keypoints the copy actually highlights. Prefer reusing an existing
   keypoint when the copy clearly matches. If the copy raises something the
   branch's existing keypoints don't cover, ADD a new keypoint with category
   from: location | amenity | experience | value.

Keypoint rules:
- Per-branch — never reuse a keypoint id across branches.
- Title is short (under 80 chars) and grounded in what the copy actually says.
- Don't fabricate facts. If the copy is vague, return fewer keypoints rather
  than invent ones.

Return ONLY JSON (no markdown, no commentary):
[
  {{
    "combo_id": "CMB-XXX",
    "angle_id": "ANG-XXX",
    "reuse_keypoint_ids": ["existing-uuid"],
    "new_keypoints": [{{"category": "location", "title": "..."}}]
  }}
]"""

        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            assignments = json.loads(raw)
        except Exception:
            logger.exception("assign-from-copy: batch %d failed", i // BATCH + 1)
            continue

        combo_by_id = {c.combo_id: c for c in batch}

        for asgn in assignments:
            cid = asgn.get("combo_id")
            combo = combo_by_id.get(cid)
            if not combo:
                continue

            aid = asgn.get("angle_id")
            if aid and aid not in valid_angle_ids:
                logger.warning(
                    "assign-from-copy: %s returned bogus angle_id %s — dropped",
                    cid, aid,
                )
                aid = None

            reuse_ids = list(asgn.get("reuse_keypoint_ids", []) or [])
            new_kp_specs = asgn.get("new_keypoints", []) or []

            new_kp_ids: list[str] = []
            for spec in new_kp_specs:
                cat = (spec.get("category") or "").lower().strip()
                title = (spec.get("title") or "").strip()[:120]
                if cat not in VALID_CATEGORIES or not title:
                    continue
                # Dedupe against existing branch keypoints (case-insensitive).
                # Covers both pre-existing keypoints and ones created earlier
                # in this same run (kps_by_branch is mutated below).
                norm = title.lower()
                existing = next(
                    (
                        kp for kp in kps_by_branch.get(combo.branch_id, [])
                        if kp["title"].lower() == norm
                    ),
                    None,
                )
                if existing:
                    if existing["id"] not in reuse_ids:
                        reuse_ids.append(existing["id"])
                    continue
                kp = BranchKeypoint(
                    branch_id=combo.branch_id, category=cat, title=title,
                )
                db.add(kp)
                db.flush()  # get kp.id before we reference it on the combo
                kps_by_branch.setdefault(combo.branch_id, []).append(
                    {"id": kp.id, "category": kp.category, "title": kp.title}
                )
                new_kp_ids.append(kp.id)
                created_keypoints += 1

            # Reused ids must belong to this combo's branch.
            allowed_ids = {kp["id"] for kp in kps_by_branch.get(combo.branch_id, [])}
            final_kp_ids = [k for k in reuse_ids if k in allowed_ids] + new_kp_ids
            final_kp_ids = final_kp_ids[:5]

            # Only fill missing fields — never overwrite a value that exists.
            changed = False
            if aid and combo.angle_id is None:
                combo.angle_id = aid
                changed = True
            if final_kp_ids and not combo.keypoint_ids:
                combo.keypoint_ids = final_kp_ids
                changed = True
            if changed:
                updated += 1

        db.commit()

    logger.info(
        "assign-from-copy: %d combos updated, %d new keypoints created (of %d candidates)",
        updated, created_keypoints, len(combos),
    )
    return {
        "processed": len(combos),
        "updated": updated,
        "created_keypoints": created_keypoints,
    }
