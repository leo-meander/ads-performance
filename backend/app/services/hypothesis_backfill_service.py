"""Backfill creative hypotheses for existing ad combos.

For each combo created in the last N days that doesn't already have a linked
hypothesis, this service:
  1. Looks up the combo's angle (if any) for human_desire / creative_angle
  2. Generates a hypothesis statement from available metadata
  3. Creates a CreativeHypothesis row linked to the combo
  4. Immediately evaluates actual metrics via hypothesis_sync_service
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.ad_angle import AdAngle
from app.models.ad_account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.creative_hypothesis import CreativeHypothesis
from app.services.hypothesis_sync_service import sync_hypothesis_results

logger = logging.getLogger(__name__)

# TA → human desire fallback when no angle is linked
_TA_DESIRE_MAP = {
    "Solo": "Belonging",
    "Couple": "Romance",
    "Friend": "Belonging",
    "Group": "Belonging",
    "Business": "Achievement",
}

# Funnel stage → KPI default
_FUNNEL_KPI = {
    "TOF": "CTR",
    "MOF": "CVR",
    "BOF": "ROAS",
}


def _next_hypo_id(db: Session) -> str:
    last = (
        db.query(CreativeHypothesis)
        .order_by(CreativeHypothesis.created_at.desc())
        .first()
    )
    if not last or not last.hypothesis_id:
        return "HYP-001"
    try:
        n = int(last.hypothesis_id.split("-")[1]) + 1
    except (IndexError, ValueError):
        n = 1
    return f"HYP-{n:03d}"


def _branch_name(db: Session, branch_id) -> str:
    acct = db.query(AdAccount).filter(AdAccount.id == str(branch_id)).first()
    return acct.account_name if acct else "Unknown"


def _funnel_from_campaign(combo: AdCombo) -> str | None:
    """Try to read funnel_stage from campaign if available."""
    if combo.campaign_id is None:
        return None
    try:
        from app.models.campaign import Campaign
        c = combo.__class__.__table__.metadata
        # Lazy: just return None — funnel parsed at campaign level
    except Exception:
        pass
    return None


def _generate_hypothesis(
    branch: str,
    ta: str | None,
    country: str | None,
    angle: AdAngle | None,
) -> tuple[str, str | None, str | None]:
    """Return (hypothesis_text, human_desire, creative_angle_name)."""
    if angle:
        desire = angle.human_desire or "Belonging"
        angle_name = angle.angle_type or "—"
        story = angle.story_structure
        ta_str = ta or "all audiences"
        country_str = f" in {country}" if country else ""
        story_str = f" via {story} narrative" if story else ""
        hyp = (
            f"If we present {angle_name} creative targeting {desire} desire "
            f"to {ta_str}{country_str}{story_str}, "
            f"we expect stronger engagement and booking intent than generic room-focused ads."
        )
        return hyp, desire, angle_name
    else:
        desire = _TA_DESIRE_MAP.get(ta or "", "Belonging")
        ta_str = ta or "all audiences"
        country_str = f" in {country}" if country else ""
        hyp = (
            f"Testing {branch} creative for {ta_str}{country_str} "
            f"against {desire} desire — no specific angle assigned yet."
        )
        return hyp, desire, None


def backfill_hypotheses(db: Session, days: int = 60) -> dict:
    """Create hypotheses for combos from the last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Combos in window
    combos = (
        db.query(AdCombo)
        .filter(AdCombo.created_at >= cutoff)
        .all()
    )

    # Already-linked combo_ids
    existing_combo_ids = {
        str(h.combo_id)
        for h in db.query(CreativeHypothesis.combo_id).filter(
            CreativeHypothesis.combo_id.isnot(None)
        ).all()
    }

    created = 0
    skipped = 0

    for combo in combos:
        cid = str(combo.id)
        if cid in existing_combo_ids:
            skipped += 1
            continue

        branch = _branch_name(db, combo.branch_id)
        angle: AdAngle | None = None
        if combo.angle_id:
            angle = db.query(AdAngle).filter(AdAngle.angle_id == combo.angle_id).first()

        hyp_text, desire, angle_name = _generate_hypothesis(
            branch, combo.target_audience, combo.country, angle
        )

        hypo_id = _next_hypo_id(db)

        hyp = CreativeHypothesis(
            hypothesis_id=hypo_id,
            branch_name=branch,
            combo_id=combo.combo_id,   # e.g. "CMB-042"
            angle_id=combo.angle_id,
            human_desire=desire,
            creative_angle=angle_name or (angle.angle_type if angle else None),
            target_audience=combo.target_audience,
            market=combo.country,
            hypothesis=hyp_text,
            variable_tested=angle.angle_type if angle else None,
            primary_kpi=_FUNNEL_KPI.get("TOF", "ROAS"),
            expected_outcome="ROAS >= branch benchmark",
            status="running",
        )
        db.add(hyp)
        db.flush()   # get the id before next _next_hypo_id call
        existing_combo_ids.add(cid)
        created += 1
        logger.info("[hypo-backfill] created %s → combo %s (%s)", hypo_id, combo.combo_id, branch)

    db.commit()

    # Now sync actual metrics for everything we just created (+ any existing running)
    sync_result = sync_hypothesis_results(db)

    return {
        "combos_scanned": len(combos),
        "hypotheses_created": created,
        "already_linked": skipped,
        "sync": sync_result,
    }
