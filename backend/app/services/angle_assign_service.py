"""Auto-assign angle + keypoints to ad_combos using Claude Vision.

Called from sync_all_platforms after each sync. Only processes combos that
have NULL angle_id OR NULL keypoint_ids — so it's incremental and cheap
(new combos only, not every combo every 15 minutes).

Based on scripts/ai_assign_angles_keypoints_v2.py but refactored as a service
with incremental filtering.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.request
from pathlib import Path

from anthropic import Anthropic
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint

logger = logging.getLogger(__name__)

BATCH = 5
MAX_IMAGE_BYTES = 5_000_000


def _load_anthropic_key() -> str:
    """Load ANTHROPIC_API_KEY from .env (bypass potentially-empty shell env)."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    return dotenv_values(env_path).get("ANTHROPIC_API_KEY", "")


def assign_angles_for_new_combos(db: Session) -> dict:
    """Assign angle + keypoints to combos that are missing either.

    Incremental: only touches combos where angle_id IS NULL OR keypoint_ids IS NULL.
    Returns a summary dict.
    """
    combos = (
        db.query(AdCombo)
        .filter((AdCombo.angle_id.is_(None)) | (AdCombo.keypoint_ids.is_(None)))
        .all()
    )
    if not combos:
        logger.info("angle-assign: no combos need assignment")
        return {"processed": 0, "updated": 0}

    api_key = _load_anthropic_key()
    if not api_key:
        logger.warning("angle-assign: ANTHROPIC_API_KEY missing — skipping")
        return {"processed": 0, "updated": 0, "skipped": "no_api_key"}

    client = Anthropic(api_key=api_key)

    accounts = {a.id: a.account_name for a in db.query(AdAccount).all()}
    copies = {c.copy_id: c for c in db.query(AdCopy).all()}
    materials = {m.material_id: m for m in db.query(AdMaterial).all()}
    keypoints = (
        db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True)).all()
    )

    kps_by_branch: dict = {}
    for kp in keypoints:
        kps_by_branch.setdefault(kp.branch_id, []).append(
            {"id": kp.id, "cat": kp.category, "title": kp.title}
        )

    bind = db.get_bind()
    with bind.connect() as conn:
        ang_rows = conn.execute(
            text(
                "SELECT angle_id, angle_type, angle_explain FROM ad_angles ORDER BY angle_id"
            )
        ).fetchall()
    all_angles = [
        {"angle_id": r[0], "type": r[1] or "?", "explain": (r[2] or "")[:80]}
        for r in ang_rows
    ]
    if not all_angles:
        logger.info("angle-assign: no angles in DB — skipping")
        return {"processed": 0, "updated": 0, "skipped": "no_angles"}

    logger.info("angle-assign: %d combos to process", len(combos))
    updated = 0

    for i in range(0, len(combos), BATCH):
        batch = combos[i : i + BATCH]
        messages_content: list = []

        combo_descriptions = []
        for combo in batch:
            copy = copies.get(combo.copy_id)
            mat = materials.get(combo.material_id)
            branch = accounts.get(combo.branch_id, "?")

            combo_descriptions.append(
                {
                    "combo_id": combo.combo_id,
                    "branch": branch,
                    "ad_name": combo.ad_name,
                    "headline": copy.headline[:200] if copy else "",
                    "body": copy.body_text[:300] if copy else "",
                    "material_type": mat.material_type if mat else "",
                }
            )

            if mat and mat.file_url and mat.file_url.startswith("http"):
                try:
                    req = urllib.request.Request(
                        mat.file_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    resp = urllib.request.urlopen(req, timeout=5)
                    img_data = resp.read()
                    if len(img_data) < MAX_IMAGE_BYTES:
                        content_type = resp.headers.get("Content-Type", "image/jpeg")
                        if "image" in content_type:
                            b64 = base64.standard_b64encode(img_data).decode("utf-8")
                            messages_content.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": content_type.split(";")[0],
                                        "data": b64,
                                    },
                                }
                            )
                            messages_content.append(
                                {
                                    "type": "text",
                                    "text": f"[Thumbnail for {combo.combo_id} - {combo.ad_name}]",
                                }
                            )
                except Exception:
                    pass  # skip image on failure

        branch_ids = list({c.branch_id for c in batch})
        available_kps = {bid: kps_by_branch.get(bid, []) for bid in branch_ids}

        prompt = f"""Analyze these hotel ad combos and assign the best matching ANGLE and KEYPOINTS for each.

COMBOS:
{json.dumps(combo_descriptions, ensure_ascii=False, indent=1)}

AVAILABLE ANGLES (GLOBAL — apply to any branch):
{json.dumps(all_angles, ensure_ascii=False, indent=1)}

AVAILABLE KEYPOINTS (per branch):
{json.dumps(available_kps, ensure_ascii=False, indent=1)}

For each combo, based on the ad copy text, headline, and thumbnail image (if provided):
1. Match the BEST angle by analyzing what hook/approach the ad uses (any global angle is allowed)
2. Match 1-3 keypoints that the ad highlights

Rules:
- Angles are GLOBAL — pick any angle_id, regardless of branch
- Keypoints MUST be from the SAME branch as the combo
- Look at the actual ad copy content to determine the approach
- KOL content that shows the property → match keypoints about what's shown
- If copy mentions location/distance → match location keypoints
- If copy mentions amenities → match amenity keypoints
- If copy mentions price/value → match value keypoints

Return ONLY JSON array:
[{{"combo_id": "CMB-001", "angle_id": "ANG-001", "keypoint_ids": ["uuid1", "uuid2"]}}]
No markdown."""

        messages_content.append({"type": "text", "text": prompt})

        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": messages_content}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            assignments = json.loads(raw)
        except Exception:
            logger.exception("angle-assign: batch %d failed", i // BATCH + 1)
            continue

        with bind.connect() as conn:
            for asgn in assignments:
                cid = asgn.get("combo_id")
                aid = asgn.get("angle_id")
                kpids = asgn.get("keypoint_ids", [])

                set_parts = []
                params = {"cid": cid}
                if aid:
                    set_parts.append("angle_id = :aid")
                    params["aid"] = aid
                if kpids:
                    set_parts.append("keypoint_ids = :kps")
                    params["kps"] = json.dumps(kpids)

                if set_parts:
                    conn.execute(
                        text(
                            f"UPDATE ad_combos SET {', '.join(set_parts)} WHERE combo_id = :cid"
                        ),
                        params,
                    )
                    updated += 1
            conn.commit()

    logger.info("angle-assign: updated %d / %d combos", updated, len(combos))
    return {"processed": len(combos), "updated": updated}
