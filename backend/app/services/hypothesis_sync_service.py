"""Auto-sync hypothesis results from linked combos.

Rules (same as Creative Library verdict):
  - running      : clicks <= 4500 AND bookings < 5  (insufficient data)
  - validated    : ROAS >= branch benchmark
  - refuted      : ROAS < branch benchmark
  - inconclusive : no combo linked or combo has zero spend
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.creative_hypothesis import CreativeHypothesis

logger = logging.getLogger(__name__)

CLICKS_THRESHOLD = 4500
BOOKINGS_THRESHOLD = 5


def _branch_benchmark(db: Session, branch_id: str) -> float:
    row = db.query(
        func.sum(AdCombo.spend).label("s"),
        func.sum(AdCombo.revenue).label("r"),
    ).filter(AdCombo.branch_id == branch_id).one()
    s = float(row.s or 0)
    r = float(row.r or 0)
    return r / s if s > 0 else 0.0


def sync_hypothesis_results(db: Session) -> dict:
    """Evaluate all hypotheses that have a linked combo_id."""
    hypotheses = db.query(CreativeHypothesis).filter(
        CreativeHypothesis.combo_id.isnot(None),
        CreativeHypothesis.status.notin_(["validated", "refuted"]),
    ).all()

    updated = 0
    skipped = 0

    for hyp in hypotheses:
        combo = db.query(AdCombo).filter(AdCombo.combo_id == str(hyp.combo_id)).first()
        if not combo:
            skipped += 1
            continue

        spend = float(combo.spend or 0)
        if spend == 0:
            hyp.status = "inconclusive"
            hyp.result_notes = "Combo has zero spend — no data to evaluate."
            db.add(hyp)
            updated += 1
            continue

        clicks = int(combo.clicks or 0)
        conversions = int(combo.conversions or 0)
        revenue = float(combo.revenue or 0)
        roas = revenue / spend if spend > 0 else 0.0
        ctr = float(combo.ctr or 0)

        # Fill actual metrics
        hyp.actual_spend = spend
        hyp.actual_roas = roas
        hyp.actual_ctr = ctr
        hyp.actual_cvr = conversions / clicks if clicks > 0 else 0.0

        # Evaluate status
        if clicks <= CLICKS_THRESHOLD and conversions < BOOKINGS_THRESHOLD:
            hyp.status = "running"
        else:
            benchmark = _branch_benchmark(db, str(combo.branch_id))
            if benchmark > 0 and roas >= benchmark:
                hyp.status = "validated"
                hyp.validated_at = datetime.now(timezone.utc)
                if not hyp.confidence_level:
                    hyp.confidence_level = "medium"
            else:
                hyp.status = "refuted"
                hyp.validated_at = datetime.now(timezone.utc)
                if not hyp.confidence_level:
                    hyp.confidence_level = "medium"

        db.add(hyp)
        updated += 1
        logger.info(
            "[hypothesis-sync] %s → status=%s roas=%.2f clicks=%d bookings=%d",
            hyp.hypothesis_id, hyp.status, roas, clicks, conversions,
        )

    db.commit()
    return {"evaluated": updated, "skipped": skipped, "total": len(hypotheses)}
