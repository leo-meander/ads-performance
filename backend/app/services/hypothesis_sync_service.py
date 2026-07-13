"""Auto-sync hypothesis results from linked combos.

Verdict logic (per-hypothesis, metric-aware):
  Gate    : n_concluded_combos >= min_sample  (combo.verdict IN WIN/LOSE)
  Metric  : if win_threshold set → avg(primary_metric) vs threshold
            if no threshold    → combo WIN rate (n_win / n_concluded)
  validated : metric beats threshold (or WIN rate >= 60%)
  refuted   : metric misses threshold (or WIN rate < 60%)
  running   : gate not reached yet — still accumulating samples
  inconclusive : no linked combos with spend
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.creative_hypothesis import CreativeHypothesis
from app.models.hypothesis_combo_link import HypothesisComboLink

logger = logging.getLogger(__name__)

WIN_RATE_THRESHOLD = 0.60  # fallback when no win_threshold set


def _extract_metric(combo: AdCombo, metric: str) -> float | None:
    """Pull the relevant metric value from a combo row."""
    m = metric.upper().replace(" ", "_").replace("-", "_")
    if m == "CTR":
        return float(combo.ctr) if combo.ctr else None
    if m == "ROAS":
        return float(combo.roas) if combo.roas else None
    if m == "HOOK_RATE":
        return float(combo.hook_rate) if combo.hook_rate else None
    if m == "HOLD_RATE":
        return float(combo.thruplay_rate) if combo.thruplay_rate else None
    if m == "CVR":
        if combo.conversions and combo.clicks and combo.clicks > 0:
            return combo.conversions / combo.clicks
    if m == "ENGAGEMENT_RATE":
        return float(combo.engagement_rate) if combo.engagement_rate else None
    # Fallback: ROAS
    return float(combo.roas) if combo.roas else None


def sync_hypothesis_results(db: Session) -> dict:
    """Evaluate all non-concluded hypotheses that have linked combos."""
    hypotheses = db.query(CreativeHypothesis).filter(
        CreativeHypothesis.status.notin_(["validated", "refuted"]),
    ).all()

    updated = 0
    skipped = 0

    for hyp in hypotheses:
        # ── Collect linked combos via junction table + legacy FK ──────────
        junction_ids = [
            r.combo_id for r in db.query(HypothesisComboLink.combo_id).filter(
                HypothesisComboLink.hypothesis_id == hyp.hypothesis_id
            ).all()
        ]
        legacy_ids = [str(hyp.combo_id)] if hyp.combo_id else []
        all_combo_ids = list(set(junction_ids + legacy_ids))

        if not all_combo_ids:
            skipped += 1
            continue

        combos = db.query(AdCombo).filter(AdCombo.combo_id.in_(all_combo_ids)).all()
        combos_with_spend = [c for c in combos if float(c.spend or 0) > 0]

        if not combos_with_spend:
            hyp.status = "inconclusive"
            hyp.result_notes = "No linked combos have spend data yet."
            db.add(hyp)
            updated += 1
            continue

        # ── Aggregate actual metrics from all linked combos ───────────────
        total_spend = sum(float(c.spend or 0) for c in combos_with_spend)
        total_revenue = sum(float(c.revenue or 0) for c in combos_with_spend)
        total_clicks = sum(int(c.clicks or 0) for c in combos_with_spend)
        total_conversions = sum(int(c.conversions or 0) for c in combos_with_spend)

        hyp.actual_spend = total_spend
        hyp.actual_roas = total_revenue / total_spend if total_spend > 0 else 0.0
        hyp.actual_ctr = total_clicks / sum(int(c.impressions or 0) for c in combos_with_spend) \
            if sum(int(c.impressions or 0) for c in combos_with_spend) > 0 else 0.0
        hyp.actual_cvr = total_conversions / total_clicks if total_clicks > 0 else 0.0

        # ── Verdict gate: n concluded combos >= min_sample ────────────────
        min_s = int(hyp.min_sample or 5)
        concluded = [c for c in combos_with_spend if c.verdict in ("WIN", "LOSE")]
        n_concluded = len(concluded)
        n_win = len([c for c in concluded if c.verdict == "WIN"])

        if n_concluded < min_s:
            hyp.status = "running"
            db.add(hyp)
            updated += 1
            logger.info(
                "[hypothesis-sync] %s → running (%d/%d samples)",
                hyp.hypothesis_id, n_concluded, min_s,
            )
            continue

        # ── Enough samples — evaluate verdict ─────────────────────────────
        primary_metric = hyp.primary_metric or hyp.primary_kpi
        win_threshold = float(hyp.win_threshold) if hyp.win_threshold else None

        if win_threshold is not None and primary_metric:
            # Threshold-based verdict: avg metric across concluded combos vs threshold
            metric_vals = [_extract_metric(c, primary_metric) for c in concluded]
            metric_vals = [v for v in metric_vals if v is not None]
            avg_metric = sum(metric_vals) / len(metric_vals) if metric_vals else None

            if avg_metric is not None:
                won = avg_metric >= win_threshold
                verdict_note = (
                    f"{primary_metric} avg={avg_metric:.4f} vs threshold={win_threshold:.4f} "
                    f"({'✓' if won else '✗'}) across {n_concluded} combos"
                )
            else:
                # Metric not available on combos — fall back to WIN rate
                won = (n_win / n_concluded) >= WIN_RATE_THRESHOLD
                verdict_note = (
                    f"No {primary_metric} data on combos — used WIN rate "
                    f"{n_win}/{n_concluded} ({n_win/n_concluded*100:.0f}%)"
                )
        else:
            # No threshold — use combo WIN rate
            won = (n_win / n_concluded) >= WIN_RATE_THRESHOLD
            verdict_note = (
                f"No win_threshold set — used WIN rate "
                f"{n_win}/{n_concluded} ({n_win/n_concluded*100:.0f}%)"
            )

        hyp.status = "validated" if won else "refuted"
        hyp.validated_at = datetime.now(timezone.utc)
        hyp.result_notes = verdict_note
        if not hyp.confidence_level:
            hyp.confidence_level = "medium"

        db.add(hyp)
        updated += 1
        logger.info(
            "[hypothesis-sync] %s → %s | %s",
            hyp.hypothesis_id, hyp.status, verdict_note,
        )

    db.commit()
    return {"evaluated": updated, "skipped": skipped, "total": len(hypotheses)}
