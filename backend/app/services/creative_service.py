"""Creative Library service: ID generation, verdict classification, derived verdict propagation."""

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial

logger = logging.getLogger(__name__)


def _next_sequential_id(db: Session, model, id_column: str, prefix: str) -> str:
    """Generate next sequential ID like ANG-001, CPY-042, etc."""
    col = getattr(model, id_column)
    last = db.query(func.max(col)).scalar()
    if last:
        num = int(last.split("-")[1]) + 1
    else:
        num = 1
    return f"{prefix}-{num:03d}"


def next_angle_id(db: Session) -> str:
    return _next_sequential_id(db, AdAngle, "angle_id", "ANG")


def next_copy_id(db: Session) -> str:
    return _next_sequential_id(db, AdCopy, "copy_id", "CPY")


def next_material_id(db: Session) -> str:
    return _next_sequential_id(db, AdMaterial, "material_id", "MAT")


def next_combo_id(db: Session) -> str:
    return _next_sequential_id(db, AdCombo, "combo_id", "CMB")


def classify_verdict(clicks: int, conversions: int, roas: float, benchmark_roas: float) -> str:
    """Classify combo verdict based on MEANDER rules.

    TEST: clicks <= 4500 OR purchases < 5 (insufficient data)
    WIN:  ROAS >= account benchmark ROAS
    LOSE: ROAS < account benchmark ROAS
    """
    # Insufficient data → TEST (need EITHER enough clicks OR enough bookings)
    if clicks <= 4500 and conversions < 5:
        return "TEST"
    # Enough data → compare to benchmark
    if benchmark_roas <= 0:
        return "TEST"
    if roas >= benchmark_roas:
        return "WIN"
    return "LOSE"


def auto_classify_all_combos(db: Session):
    """Auto-classify all combos based on MEANDER verdict rules.

    Benchmark = total ROAS of the account (branch).
    Only overwrite if verdict_source != 'manual'.
    """
    from app.models.account import AdAccount

    # Compute benchmark ROAS per account
    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    benchmarks: dict[str, float] = {}

    for acc in accounts:
        combos = db.query(AdCombo).filter(AdCombo.branch_id == acc.id).all()
        total_spend = sum(float(c.spend or 0) for c in combos)
        total_revenue = sum(float(c.revenue or 0) for c in combos)
        benchmarks[acc.id] = total_revenue / total_spend if total_spend > 0 else 0

    # Classify each combo
    all_combos = db.query(AdCombo).all()
    updated = 0
    for combo in all_combos:
        if combo.verdict_source == "manual":
            continue  # never overwrite manual verdicts
        benchmark = benchmarks.get(combo.branch_id, 0)
        clicks = int(combo.clicks or 0)
        conversions = int(combo.conversions or 0)
        roas = float(combo.roas or 0)

        new_verdict = classify_verdict(clicks, conversions, roas, benchmark)
        if combo.verdict != new_verdict:
            combo.verdict = new_verdict
            combo.verdict_source = "auto"
            combo.verdict_notes = f"Auto: clicks={clicks}, bookings={conversions}, ROAS={roas:.2f}x vs benchmark={benchmark:.2f}x"
            updated += 1

    db.commit()
    propagate_derived_verdicts(db)

    # Also classify angles
    auto_classify_all_angles(db, benchmarks)

    logger.info("Auto-classified %d combos", updated)
    return updated


def auto_classify_all_angles(db: Session, benchmarks: dict[str, float] | None = None):
    """Auto-classify angles based on aggregated combo metrics.

    Angle rules are 2x combo rules:
    TEST: total clicks ≤ 9,000 OR total bookings < 10
    WIN:  aggregated ROAS ≥ account benchmark
    LOSE: aggregated ROAS < account benchmark
    """
    from app.models.account import AdAccount
    from app.models.ad_angle import AdAngle

    if benchmarks is None:
        benchmarks = {}
        for acc in db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all():
            combos = db.query(AdCombo).filter(AdCombo.branch_id == acc.id).all()
            total_spend = sum(float(c.spend or 0) for c in combos)
            total_revenue = sum(float(c.revenue or 0) for c in combos)
            benchmarks[acc.id] = total_revenue / total_spend if total_spend > 0 else 0

    angles = db.query(AdAngle).all()
    updated = 0

    for angle in angles:
        # Aggregate metrics from all combos using this angle
        combos = db.query(AdCombo).filter(AdCombo.angle_id == angle.angle_id).all()
        total_clicks = sum(int(c.clicks or 0) for c in combos)
        total_conversions = sum(int(c.conversions or 0) for c in combos)
        total_spend = sum(float(c.spend or 0) for c in combos)
        total_revenue = sum(float(c.revenue or 0) for c in combos)
        agg_roas = total_revenue / total_spend if total_spend > 0 else 0

        benchmark = benchmarks.get(angle.branch_id, 0)

        # Angle rules = 2x combo rules
        # Need EITHER clicks > 9000 OR bookings >= 10 to have enough data
        if total_clicks <= 9000 and total_conversions < 10:
            new_verdict = "TEST"
        elif benchmark > 0 and agg_roas >= benchmark:
            new_verdict = "WIN"
        else:
            new_verdict = "LOSE"

        if angle.status != new_verdict:
            angle.status = new_verdict
            updated += 1

    db.commit()
    logger.info("Auto-classified %d angles", updated)


def propagate_derived_verdicts(db: Session):
    """Propagate verdict from combos to copies and materials.

    For each copy/material, take the BEST verdict from all combos that use it.
    Priority: WIN > TEST > LOSE
    """
    verdict_priority = {"WIN": 3, "TEST": 2, "LOSE": 1}

    # Get all combos
    combos = db.query(AdCombo).all()

    # Aggregate best verdict per copy and per material
    copy_verdicts: dict[str, str] = {}
    material_verdicts: dict[str, str] = {}

    for combo in combos:
        v = combo.verdict
        vp = verdict_priority.get(v, 0)

        if combo.copy_id:
            current = copy_verdicts.get(combo.copy_id)
            if current is None or vp > verdict_priority.get(current, 0):
                copy_verdicts[combo.copy_id] = v

        if combo.material_id:
            current = material_verdicts.get(combo.material_id)
            if current is None or vp > verdict_priority.get(current, 0):
                material_verdicts[combo.material_id] = v

    # Update copies
    for copy_id, verdict in copy_verdicts.items():
        copy = db.query(AdCopy).filter(AdCopy.copy_id == copy_id).first()
        if copy and copy.derived_verdict != verdict:
            copy.derived_verdict = verdict

    # Update materials
    for mat_id, verdict in material_verdicts.items():
        mat = db.query(AdMaterial).filter(AdMaterial.material_id == mat_id).first()
        if mat and mat.derived_verdict != verdict:
            mat.derived_verdict = verdict

    db.commit()
    logger.info("Propagated derived verdicts: %d copies, %d materials", len(copy_verdicts), len(material_verdicts))
