"""Audience hygiene detectors (Section E.4).

All three are guidance-only — auto-applying targeting overwrites is risky
because Meta's ad_set.targeting JSON often contains operator edits we don't
want to stomp. The detectors inspect the `targeting` JSONB column populated
at sync time and flag missing exclusion blocks.

- META_MISSING_RECENT_BOOKER_EXCLUSION — no Purchase:30d exclusion on cold/warm
- META_TEMPERATURE_OVERLAP             — cold campaign not excluding warm/hot
- META_MISSING_STAFF_EXCLUSION         — no staff Custom Audience exclusion

These detectors work on a best-effort basis — the targeting JSON is
operator-authored so our keyword heuristics may miss edge cases. Errors on
the side of under-firing.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.meta_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.meta_recommendations.registry import register
from app.services.meta_recommendations.utils import (
    ad_set_targeted_country,
    campaign_funnel_stage,
    snapshot_campaign,
)


def _scope_active_ad_sets(
    db: Session, account_ids: list[str] | None,
) -> Iterable[tuple[AdSet, Campaign]]:
    q = (
        db.query(AdSet, Campaign)
        .join(Campaign, AdSet.campaign_id == Campaign.id)
        .filter(AdSet.platform == "meta")
        .filter(AdSet.status == "ACTIVE")
        .filter(Campaign.status == "ACTIVE")
    )
    if account_ids:
        q = q.filter(AdSet.account_id.in_(account_ids))
    for ad_set, camp in q.all():
        yield ad_set, camp


def _targeting_text(ad_set: AdSet) -> str:
    """Flatten the targeting JSON into a searchable lowercase string."""
    import json

    if not ad_set.targeting:
        return ""
    try:
        return json.dumps(ad_set.targeting, ensure_ascii=False).lower()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────
# META_MISSING_RECENT_BOOKER_EXCLUSION — ad_set level
# ─────────────────────────────────────────────────────────────────────────
@register
class MissingRecentBookerExclusionDetector(Detector):
    rec_type = "META_MISSING_RECENT_BOOKER_EXCLUSION"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        for ad_set, camp in _scope_active_ad_sets(db, account_ids):
            yield DetectorTarget(
                entity_level="ad_set",
                entity_id=ad_set.id,
                account_id=ad_set.account_id,
                campaign_id=camp.id,
                ad_set_id=ad_set.id,
                funnel_stage=campaign_funnel_stage(camp),
                targeted_country=ad_set_targeted_country(ad_set),
                context={
                    "ad_set_name": ad_set.name,
                    "campaign_name": camp.name,
                },
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        ad_set = db.query(AdSet).filter(AdSet.id == target.ad_set_id).first()
        if ad_set is None:
            return None
        text = _targeting_text(ad_set)
        if not text:
            # No targeting payload — we can't audit; treat as no finding.
            return None

        # Look for the combination of "exclusion / excluded_custom_audiences"
        # and any purchase/booker keyword.
        has_exclusion_block = (
            "excluded_custom_audiences" in text
            or "exclusions" in text
        )
        has_booker_signal = (
            "purchase" in text
            or "booker" in text
            or "past_guest" in text
            or "booked" in text
        )
        if has_exclusion_block and has_booker_signal:
            return None

        return DetectorFinding(
            evidence={
                "ad_set_name": target.context.get("ad_set_name"),
                "campaign_name": target.context.get("campaign_name"),
                "funnel_stage": target.funnel_stage,
                "has_exclusion_block": has_exclusion_block,
                "has_booker_signal": has_booker_signal,
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_TEMPERATURE_OVERLAP — ad_set level (cold campaigns only)
# ─────────────────────────────────────────────────────────────────────────
@register
class TemperatureOverlapDetector(Detector):
    rec_type = "META_TEMPERATURE_OVERLAP"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        for ad_set, camp in _scope_active_ad_sets(db, account_ids):
            stage = campaign_funnel_stage(camp)
            if stage != "TOF":
                continue
            yield DetectorTarget(
                entity_level="ad_set",
                entity_id=ad_set.id,
                account_id=ad_set.account_id,
                campaign_id=camp.id,
                ad_set_id=ad_set.id,
                funnel_stage=stage,
                targeted_country=ad_set_targeted_country(ad_set),
                context={
                    "ad_set_name": ad_set.name,
                    "campaign_name": camp.name,
                },
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        ad_set = db.query(AdSet).filter(AdSet.id == target.ad_set_id).first()
        if ad_set is None:
            return None
        text = _targeting_text(ad_set)
        if not text:
            return None

        # A cold (TOF) ad set should exclude warm+hot pools. We look for any
        # signal that retargeting audiences are being excluded.
        has_warm_exclusion = (
            "excluded_custom_audiences" in text
            and (
                "video_viewer" in text
                or "page_engager" in text
                or "website_visitor" in text
                or "warm" in text
                or "add_to_cart" in text
                or "initiate_checkout" in text
            )
        )
        if has_warm_exclusion:
            return None

        return DetectorFinding(
            evidence={
                "ad_set_name": target.context.get("ad_set_name"),
                "campaign_name": target.context.get("campaign_name"),
                "funnel_stage": target.funnel_stage,
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_MISSING_STAFF_EXCLUSION — ad_set level
# ─────────────────────────────────────────────────────────────────────────
@register
class MissingStaffExclusionDetector(Detector):
    rec_type = "META_MISSING_STAFF_EXCLUSION"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        for ad_set, camp in _scope_active_ad_sets(db, account_ids):
            yield DetectorTarget(
                entity_level="ad_set",
                entity_id=ad_set.id,
                account_id=ad_set.account_id,
                campaign_id=camp.id,
                ad_set_id=ad_set.id,
                funnel_stage=campaign_funnel_stage(camp),
                targeted_country=ad_set_targeted_country(ad_set),
                context={
                    "ad_set_name": ad_set.name,
                    "campaign_name": camp.name,
                },
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        ad_set = db.query(AdSet).filter(AdSet.id == target.ad_set_id).first()
        if ad_set is None:
            return None
        text = _targeting_text(ad_set)
        if not text:
            return None
        if "staff" in text or "employee" in text or "internal" in text:
            return None

        return DetectorFinding(
            evidence={
                "ad_set_name": target.context.get("ad_set_name"),
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_BRANCH_ICP_IMBALANCE — account level, guidance-only
# ─────────────────────────────────────────────────────────────────────────
# We stub the detector scope + evaluate but intentionally return no findings
# today because ICP mapping (which ad_set maps to which ICP) requires a
# human-maintained mapping table that doesn't exist yet. The rec_type is
# reserved in the catalog so the migration + UI treat it as a valid type;
# we will wire the actual detection after the ICP-mapping table lands.
@register
class BranchICPImbalanceDetector(Detector):
    rec_type = "META_BRANCH_ICP_IMBALANCE"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        return []  # stub — see module docstring.

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        return None
