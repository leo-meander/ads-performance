"""Orchestrator: run Meta detectors for a cadence, enrich via Claude, upsert rows.

Public entry point:
    run_recommendations(db, cadence, account_ids=None, source_task_id=None)

Invariants:
- Upsert by dedup_key where status='pending' — the same finding on the same
  run updates the existing pending row instead of creating duplicates.
- Missed detections: a pending rec whose detector doesn't fire this run is
  marked 'superseded' so the UI stops showing it.
- Expiry: pending recs past expires_at are flipped to 'expired' after each run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.meta_recommendation import MetaRecommendation
from app.services.meta_recommendations import registry
from app.services.meta_recommendations.ai_enricher import (
    EnrichedFinding,
    enrich_batch,
)
from app.services.meta_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)

logger = logging.getLogger(__name__)

DEFAULT_EXPIRY_DAYS = 14


def run_recommendations(
    db: Session,
    cadence: str,
    account_ids: list[str] | None = None,
    source_task_id: str | None = None,
) -> dict[str, int]:
    """Main orchestrator. Returns a stats dict with counts per action."""
    detectors = registry.by_cadence(cadence)
    if not detectors:
        logger.info("run_meta_recommendations: no detectors for cadence=%s", cadence)
        return {"inserted": 0, "updated": 0, "superseded": 0, "expired": 0}

    findings: list[tuple[Detector, DetectorTarget, DetectorFinding]] = []
    for det in detectors:
        try:
            for target in det.scope(db, account_ids=account_ids):
                try:
                    f = det.evaluate(db, target)
                except Exception:
                    logger.exception(
                        "meta detector %s evaluate failed for target=%s",
                        det.rec_type, target.entity_id,
                    )
                    continue
                if f is not None:
                    findings.append((det, target, f))
        except Exception:
            logger.exception("meta detector %s scope failed", det.rec_type)

    account_ids_seen = {t.account_id for _, t, _ in findings}
    campaign_ids_seen = {t.campaign_id for _, t, _ in findings if t.campaign_id}
    account_map: dict[str, AdAccount] = {}
    campaign_map: dict[str, Campaign] = {}
    if account_ids_seen:
        for a in db.query(AdAccount).filter(AdAccount.id.in_(account_ids_seen)).all():
            account_map[a.id] = a
    if campaign_ids_seen:
        for c in db.query(Campaign).filter(Campaign.id.in_(campaign_ids_seen)).all():
            campaign_map[c.id] = c

    enriched = enrich_batch(findings, account_map, campaign_map)
    stats = _upsert_findings(db, enriched, source_task_id=source_task_id)
    stats["superseded"] = _supersede_missing(
        db, cadence=cadence,
        active_dedup_keys={t.dedup_key(d.rec_type) for d, t, _ in findings},
        account_ids=account_ids,
    )
    stats["expired"] = _expire_stale(db)

    db.commit()
    logger.info(
        "run_meta_recommendations(cadence=%s, accounts=%s) -> %s",
        cadence, account_ids, stats,
    )
    return stats


def _upsert_findings(
    db: Session,
    enriched: list[EnrichedFinding],
    *,
    source_task_id: str | None,
) -> dict[str, int]:
    inserted = 0
    updated = 0
    now = datetime.now(timezone.utc)

    for item in enriched:
        det = item.detector
        target = item.target
        finding = item.finding
        dedup_key = target.dedup_key(det.rec_type)

        existing = (
            db.query(MetaRecommendation)
            .filter(MetaRecommendation.dedup_key == dedup_key)
            .filter(MetaRecommendation.status == "pending")
            .first()
        )

        suggested_action = det.build_action(target, finding) if (
            det.auto_applicable or det.build_action.__qualname__ != "Detector.build_action"
        ) else {"function": None, "kwargs": {}}
        if item.tailored_action_params and isinstance(suggested_action.get("kwargs"), dict):
            merged = dict(suggested_action["kwargs"])
            merged.update({k: v for k, v in item.tailored_action_params.items()})
            suggested_action = {**suggested_action, "kwargs": merged}

        warning_text = det.render_warning(finding)
        title = det.render_title(finding)

        if existing:
            existing.detector_finding = finding.evidence
            existing.metrics_snapshot = finding.metrics_snapshot
            existing.ai_reasoning = item.reasoning
            existing.ai_confidence = item.confidence
            existing.suggested_action = suggested_action
            existing.warning_text = warning_text
            existing.title = title
            existing.expires_at = now + timedelta(days=DEFAULT_EXPIRY_DAYS)
            existing.source_task_id = source_task_id
            updated += 1
        else:
            row = MetaRecommendation(
                rec_type=det.rec_type,
                severity=det.severity,
                status="pending",
                account_id=target.account_id,
                campaign_id=target.campaign_id,
                ad_set_id=target.ad_set_id,
                ad_id=target.ad_id,
                entity_level=target.entity_level,
                funnel_stage=target.funnel_stage,
                targeted_country=target.targeted_country,
                title=title,
                detector_finding=finding.evidence,
                metrics_snapshot=finding.metrics_snapshot,
                ai_reasoning=item.reasoning,
                ai_confidence=item.confidence,
                suggested_action=suggested_action,
                auto_applicable=det.auto_applicable,
                warning_text=warning_text,
                sop_reference=det.sop_reference,
                dedup_key=dedup_key,
                expires_at=now + timedelta(days=DEFAULT_EXPIRY_DAYS),
                source_task_id=source_task_id,
            )
            db.add(row)
            inserted += 1

    db.flush()
    return {"inserted": inserted, "updated": updated}


def _supersede_missing(
    db: Session,
    *,
    cadence: str,
    active_dedup_keys: set[str],
    account_ids: list[str] | None,
) -> int:
    """Mark pending rows from this cadence as superseded when the detector
    no longer fires for them."""
    from app.services.meta_recommendations.catalog import CATALOG

    rec_types_this_cadence = [
        rt for rt, spec in CATALOG.items() if spec.cadence == cadence
    ]
    if not rec_types_this_cadence:
        return 0

    q = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.status == "pending")
        .filter(MetaRecommendation.rec_type.in_(rec_types_this_cadence))
    )
    if account_ids:
        q = q.filter(MetaRecommendation.account_id.in_(account_ids))

    n = 0
    for rec in q.all():
        if rec.dedup_key in active_dedup_keys:
            continue
        rec.status = "superseded"
        n += 1
    return n


def _expire_stale(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.status == "pending")
        .filter(MetaRecommendation.expires_at < now)
        .all()
    )
    for r in rows:
        r.status = "expired"
    return len(rows)


def regenerate_recommendation(
    db: Session,
    recommendation_id: str,
) -> MetaRecommendation | None:
    """Re-run a single detector for a single recommendation's entity."""
    rec = (
        db.query(MetaRecommendation)
        .filter(MetaRecommendation.id == recommendation_id)
        .first()
    )
    if not rec:
        return None

    try:
        det = registry.get_detector(rec.rec_type)
    except KeyError:
        return rec

    target = DetectorTarget(
        entity_level=rec.entity_level,
        entity_id=_entity_id_for(rec),
        account_id=rec.account_id,
        campaign_id=rec.campaign_id,
        ad_set_id=rec.ad_set_id,
        ad_id=rec.ad_id,
        funnel_stage=rec.funnel_stage,
        targeted_country=rec.targeted_country,
        context={},
    )
    finding = det.evaluate(db, target)
    if finding is None:
        rec.status = "superseded"
        db.commit()
        return rec

    account = db.query(AdAccount).filter(AdAccount.id == rec.account_id).first()
    campaign = (
        db.query(Campaign).filter(Campaign.id == rec.campaign_id).first()
        if rec.campaign_id else None
    )
    enriched = enrich_batch(
        [(det, target, finding)],
        {rec.account_id: account} if account else {},
        {rec.campaign_id: campaign} if campaign else {},
    )
    if enriched:
        _apply_enrichment_to_row(rec, det, target, finding, enriched[0])
        db.commit()
    return rec


def _entity_id_for(rec: MetaRecommendation) -> str:
    if rec.entity_level == "account":
        return rec.account_id
    if rec.entity_level == "campaign":
        return rec.campaign_id or rec.account_id
    if rec.entity_level == "ad_set":
        return rec.ad_set_id or rec.account_id
    if rec.entity_level == "ad":
        return rec.ad_id or rec.account_id
    return rec.account_id


def _apply_enrichment_to_row(
    rec: MetaRecommendation,
    det: Detector,
    target: DetectorTarget,
    finding: DetectorFinding,
    enriched: EnrichedFinding,
) -> None:
    rec.detector_finding = finding.evidence
    rec.metrics_snapshot = finding.metrics_snapshot
    rec.ai_reasoning = enriched.reasoning
    rec.ai_confidence = enriched.confidence
    suggested = det.build_action(target, finding) if det.auto_applicable or (
        det.build_action.__qualname__ != "Detector.build_action"
    ) else {"function": None, "kwargs": {}}
    if enriched.tailored_action_params and isinstance(suggested.get("kwargs"), dict):
        merged = dict(suggested["kwargs"])
        merged.update(enriched.tailored_action_params)
        suggested = {**suggested, "kwargs": merged}
    rec.suggested_action = suggested
    rec.warning_text = det.render_warning(finding)
    rec.title = det.render_title(finding)
    rec.expires_at = datetime.now(timezone.utc) + timedelta(days=DEFAULT_EXPIRY_DAYS)
