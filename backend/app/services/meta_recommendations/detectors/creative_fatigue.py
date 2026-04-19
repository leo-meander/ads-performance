"""Creative fatigue detectors (Section F.6).

- META_CTR_DROP_BASELINE — ad CTR dropped > 25% vs first-7d baseline
- META_CPM_SPIKE         — ad 7d CPM rose > 30% vs prior 7d (auto-pause)
- META_CREATIVE_AGE_30D  — ad has been active continuously 30+ days
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.meta_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.meta_recommendations.registry import register
from app.services.meta_recommendations.utils import (
    ad_age_days,
    ad_set_targeted_country,
    campaign_funnel_stage,
    snapshot_ad,
    sum_ad,
)


def _scope_active_meta_ads(
    db: Session, account_ids: list[str] | None,
) -> Iterable[DetectorTarget]:
    q = (
        db.query(Ad, AdSet, Campaign)
        .join(AdSet, Ad.ad_set_id == AdSet.id)
        .join(Campaign, Ad.campaign_id == Campaign.id)
        .filter(Ad.platform == "meta")
        .filter(Ad.status == "ACTIVE")
    )
    if account_ids:
        q = q.filter(Ad.account_id.in_(account_ids))
    for ad, ad_set, camp in q.all():
        yield DetectorTarget(
            entity_level="ad",
            entity_id=ad.id,
            account_id=ad.account_id,
            campaign_id=camp.id,
            ad_set_id=ad_set.id,
            ad_id=ad.id,
            funnel_stage=campaign_funnel_stage(camp),
            targeted_country=ad_set_targeted_country(ad_set),
            context={
                "ad_name": ad.name,
                "ad_created_at": ad.created_at.isoformat() if ad.created_at else None,
                "ad_age_days": ad_age_days(ad),
            },
        )


# ─────────────────────────────────────────────────────────────────────────
# META_CTR_DROP_BASELINE — ad level
# ─────────────────────────────────────────────────────────────────────────
@register
class CTRDropBaselineDetector(Detector):
    rec_type = "META_CTR_DROP_BASELINE"

    DROP_THRESHOLD = 0.25  # 25% drop

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        yield from _scope_active_meta_ads(db, account_ids)

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        age = target.context.get("ad_age_days")
        if age is None or age < 14:
            # Need at least 14 days so we have a 7d baseline and a 7d current window.
            return None

        ad = db.query(Ad).filter(Ad.id == target.ad_id).first()
        if ad is None or ad.created_at is None:
            return None
        baseline_end = ad.created_at.date() + timedelta(days=7)
        current_end = date.today()
        current_start = current_end - timedelta(days=6)

        impr_base = sum_ad(db, target.ad_id, "impressions", 7, baseline_end)
        clicks_base = sum_ad(db, target.ad_id, "clicks", 7, baseline_end)
        impr_now = sum_ad(db, target.ad_id, "impressions", 7, current_end)
        clicks_now = sum_ad(db, target.ad_id, "clicks", 7, current_end)

        if impr_base < 5000 or impr_now < 5000:
            return None

        ctr_base = float(clicks_base / impr_base) if impr_base > 0 else 0.0
        ctr_now = float(clicks_now / impr_now) if impr_now > 0 else 0.0
        if ctr_base <= 0:
            return None
        drop = (ctr_base - ctr_now) / ctr_base
        if drop < self.DROP_THRESHOLD:
            return None

        return DetectorFinding(
            evidence={
                "ctr_baseline": ctr_base,
                "ctr_current": ctr_now,
                "drop_pct": drop,
                "threshold_pct": self.DROP_THRESHOLD,
                "baseline_window_end": str(baseline_end),
                "current_window": f"{current_start} to {current_end}",
                "ad_name": target.context.get("ad_name"),
                "ad_age_days": age,
            },
            metrics_snapshot=snapshot_ad(db, target.ad_id, current_end),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_CPM_SPIKE — ad level, auto-pause
# ─────────────────────────────────────────────────────────────────────────
@register
class CPMSpikeDetector(Detector):
    rec_type = "META_CPM_SPIKE"

    SPIKE_THRESHOLD = 0.30  # 30% CPM rise

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        yield from _scope_active_meta_ads(db, account_ids)

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        today = date.today()
        prior_window_end = today - timedelta(days=7)

        spend_now = sum_ad(db, target.ad_id, "spend", 7, today)
        impr_now = sum_ad(db, target.ad_id, "impressions", 7, today)
        spend_prior = sum_ad(db, target.ad_id, "spend", 7, prior_window_end)
        impr_prior = sum_ad(db, target.ad_id, "impressions", 7, prior_window_end)

        if impr_now < 5000 or impr_prior < 5000:
            return None

        # CPM = spend / impressions * 1000
        cpm_now = float(spend_now / impr_now * 1000) if impr_now > 0 else 0.0
        cpm_prior = float(spend_prior / impr_prior * 1000) if impr_prior > 0 else 0.0
        if cpm_prior <= 0:
            return None
        rise = (cpm_now - cpm_prior) / cpm_prior
        if rise < self.SPIKE_THRESHOLD:
            return None

        return DetectorFinding(
            evidence={
                "cpm_prior": cpm_prior,
                "cpm_current": cpm_now,
                "rise_pct": rise,
                "threshold_pct": self.SPIKE_THRESHOLD,
                "ad_name": target.context.get("ad_name"),
            },
            metrics_snapshot=snapshot_ad(db, target.ad_id, today),
        )

    def build_action(
        self, target: DetectorTarget, finding: DetectorFinding,
    ) -> dict:
        return {"function": "pause_ad", "kwargs": {}}


# ─────────────────────────────────────────────────────────────────────────
# META_CREATIVE_AGE_30D — ad level
# ─────────────────────────────────────────────────────────────────────────
@register
class CreativeAge30DDetector(Detector):
    rec_type = "META_CREATIVE_AGE_30D"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        yield from _scope_active_meta_ads(db, account_ids)

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        age = target.context.get("ad_age_days")
        if age is None or age < 30:
            return None
        today = date.today()
        spend_7 = sum_ad(db, target.ad_id, "spend", 7, today)
        # Ignore ads that aren't actually running any traffic.
        if spend_7 <= 0:
            return None
        return DetectorFinding(
            evidence={
                "ad_age_days": age,
                "ad_name": target.context.get("ad_name"),
                "ad_created_at": target.context.get("ad_created_at"),
                "spend_7d": float(spend_7),
            },
            metrics_snapshot=snapshot_ad(db, target.ad_id, today),
        )
