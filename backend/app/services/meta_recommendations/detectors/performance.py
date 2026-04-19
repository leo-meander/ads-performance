"""Performance-critical detectors (Section G.3 + G.4).

- META_BAD_ROAS_7D        — campaign 7d ROAS < 50% of tier benchmark
- META_LOW_CTR_7D         — ad 7d CTR < cold/warm floor
- META_HIGH_CTR_LOW_CVR   — campaign CTR healthy, CVR < 1%
- META_SCALE_TOO_FAST     — campaign daily_budget rose > 25% in 24h (auto-revert)
- META_FREQ_ABOVE_CEILING — ad 7d frequency > 2.5 (auto-pause)

Benchmarks come from playbook G.2 benchmark table; we pick conservative
defaults so the detectors under-fire rather than over-fire.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.booking_match_service import normalize_branch
from app.services.meta_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.meta_recommendations.registry import register
from app.services.meta_recommendations.utils import (
    CTR_COLD_MIN,
    CVR_MIN,
    ad_age_days,
    ad_set_targeted_country,
    avg_ad,
    campaign_funnel_stage,
    snapshot_ad,
    snapshot_campaign,
    sum_ad,
    sum_ad_set,
    sum_campaign,
)

# Conservative tier floors (playbook G.2). ROAS values are multiples of spend.
# Hostels have thinner margins so their floor is lower than the premium tier.
_PREMIUM_BRANCHES = {"Oani"}
_HOSTEL_BRANCHES = {"Saigon", "Taipei", "1948", "Osaka"}

ROAS_FLOOR_PREMIUM = 3.0
ROAS_FLOOR_HOSTEL = 2.0
# We fire when observed < 50% of the tier floor for 7 days.
ROAS_ALERT_RATIO = 0.5


def _roas_floor(branch: str | None) -> float:
    if branch in _PREMIUM_BRANCHES:
        return ROAS_FLOOR_PREMIUM
    if branch in _HOSTEL_BRANCHES:
        return ROAS_FLOOR_HOSTEL
    return ROAS_FLOOR_HOSTEL  # Bread / unknown -> hostel tier floor


def _branch_for_account(db: Session, account_id: str) -> str | None:
    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if account is None:
        return None
    return normalize_branch(account.account_name)


# ─────────────────────────────────────────────────────────────────────────
# META_BAD_ROAS_7D — campaign level
# ─────────────────────────────────────────────────────────────────────────
@register
class BadROASDetector(Detector):
    rec_type = "META_BAD_ROAS_7D"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        q = (
            db.query(Campaign)
            .filter(Campaign.platform == "meta")
            .filter(Campaign.status == "ACTIVE")
        )
        if account_ids:
            q = q.filter(Campaign.account_id.in_(account_ids))
        for camp in q.all():
            yield DetectorTarget(
                entity_level="campaign",
                entity_id=camp.id,
                account_id=camp.account_id,
                campaign_id=camp.id,
                funnel_stage=campaign_funnel_stage(camp),
                context={"campaign_name": camp.name},
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        today = date.today()
        spend_7 = sum_campaign(db, target.campaign_id, "spend", 7, today)
        rev_7 = sum_campaign(db, target.campaign_id, "revenue", 7, today)
        # Need at least 7 days of meaningful spend (Golden Rule #1).
        if spend_7 < Decimal("50"):
            return None

        actual_roas = float(rev_7 / spend_7) if spend_7 > 0 else 0.0
        branch = _branch_for_account(db, target.account_id)
        tier_floor = _roas_floor(branch)
        threshold = tier_floor * ROAS_ALERT_RATIO

        if actual_roas >= threshold:
            return None

        return DetectorFinding(
            evidence={
                "actual_roas_7d": actual_roas,
                "tier_floor": tier_floor,
                "alert_threshold": threshold,
                "branch": branch,
                "funnel_stage": target.funnel_stage,
                "spend_7d": float(spend_7),
                "revenue_7d": float(rev_7),
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id, today),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_LOW_CTR_7D — ad level
# ─────────────────────────────────────────────────────────────────────────
@register
class LowCTRDetector(Detector):
    rec_type = "META_LOW_CTR_7D"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
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
                context={"ad_name": ad.name},
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        today = date.today()
        impr = sum_ad(db, target.ad_id, "impressions", 7, today)
        # Need a meaningful impression volume (>=10k) to call it low-CTR.
        if impr < 10000:
            return None
        clicks = sum_ad(db, target.ad_id, "clicks", 7, today)
        ctr = float(clicks / impr) if impr > 0 else 0.0

        if ctr >= CTR_COLD_MIN:
            return None

        return DetectorFinding(
            evidence={
                "actual_ctr_7d": ctr,
                "cold_floor": CTR_COLD_MIN,
                "impressions_7d": float(impr),
                "clicks_7d": float(clicks),
                "funnel_stage": target.funnel_stage,
                "targeted_country": target.targeted_country,
                "ad_name": target.context.get("ad_name"),
            },
            metrics_snapshot=snapshot_ad(db, target.ad_id, today),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_HIGH_CTR_LOW_CVR — campaign level
# ─────────────────────────────────────────────────────────────────────────
@register
class HighCTRLowCVRDetector(Detector):
    rec_type = "META_HIGH_CTR_LOW_CVR"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        q = (
            db.query(Campaign)
            .filter(Campaign.platform == "meta")
            .filter(Campaign.status == "ACTIVE")
        )
        if account_ids:
            q = q.filter(Campaign.account_id.in_(account_ids))
        for camp in q.all():
            yield DetectorTarget(
                entity_level="campaign",
                entity_id=camp.id,
                account_id=camp.account_id,
                campaign_id=camp.id,
                funnel_stage=campaign_funnel_stage(camp),
                context={"campaign_name": camp.name},
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        today = date.today()
        impr = sum_campaign(db, target.campaign_id, "impressions", 7, today)
        clicks = sum_campaign(db, target.campaign_id, "clicks", 7, today)
        conv = sum_campaign(db, target.campaign_id, "conversions", 7, today)
        if impr < 20000 or clicks < 200:
            return None

        ctr = float(clicks / impr) if impr > 0 else 0.0
        cvr = float(conv / clicks) if clicks > 0 else 0.0
        # Healthy CTR but poor CVR -> landing-page problem.
        if ctr < CTR_COLD_MIN or cvr >= CVR_MIN:
            return None

        return DetectorFinding(
            evidence={
                "ctr_7d": ctr,
                "cvr_7d": cvr,
                "cvr_floor": CVR_MIN,
                "impressions_7d": float(impr),
                "clicks_7d": float(clicks),
                "conversions_7d": float(conv),
                "funnel_stage": target.funnel_stage,
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id, today),
        )


# ─────────────────────────────────────────────────────────────────────────
# META_SCALE_TOO_FAST — campaign level, auto-revert via update_campaign_budget
# ─────────────────────────────────────────────────────────────────────────
@register
class ScaleTooFastDetector(Detector):
    rec_type = "META_SCALE_TOO_FAST"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        q = (
            db.query(Campaign)
            .filter(Campaign.platform == "meta")
            .filter(Campaign.status == "ACTIVE")
            .filter(Campaign.daily_budget.isnot(None))
        )
        if account_ids:
            q = q.filter(Campaign.account_id.in_(account_ids))
        for camp in q.all():
            yield DetectorTarget(
                entity_level="campaign",
                entity_id=camp.id,
                account_id=camp.account_id,
                campaign_id=camp.id,
                funnel_stage=campaign_funnel_stage(camp),
                context={
                    "campaign_name": camp.name,
                    "current_daily_budget": float(camp.daily_budget) if camp.daily_budget else None,
                },
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        today = date.today()
        current_budget = target.context.get("current_daily_budget")
        if not current_budget:
            return None

        # Use the last 3-day spend average as a stand-in for yesterday's budget.
        spend_yesterday = sum_campaign(db, target.campaign_id, "spend", 1, today - timedelta(days=1))
        spend_day_before = sum_campaign(db, target.campaign_id, "spend", 1, today - timedelta(days=2))
        if spend_day_before <= 0:
            return None
        # If the current budget exceeds yesterday's spend by > 25%, flag.
        ratio = float(current_budget) / float(spend_day_before)
        if ratio <= 1.25:
            return None

        capped = float(spend_day_before) * 1.25
        return DetectorFinding(
            evidence={
                "current_daily_budget": float(current_budget),
                "spend_yesterday": float(spend_yesterday),
                "spend_day_before": float(spend_day_before),
                "ratio_over_day_before": ratio,
                "proposed_capped_budget": capped,
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id, today),
            action_kwargs={
                "new_daily_budget": capped,
                # force=True because the revert is a decrease disguised as a
                # scale-down; the guard wouldn't reject it but being explicit
                # keeps audit logs clean.
                "force": True,
            },
        )

    def build_action(
        self, target: DetectorTarget, finding: DetectorFinding,
    ) -> dict:
        return {
            "function": "update_campaign_budget",
            "kwargs": finding.action_kwargs,
        }


# ─────────────────────────────────────────────────────────────────────────
# META_FREQ_ABOVE_CEILING — ad level, auto-pause
# ─────────────────────────────────────────────────────────────────────────
@register
class FrequencyAboveCeilingDetector(Detector):
    rec_type = "META_FREQ_ABOVE_CEILING"

    FREQ_CEILING = 2.5

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
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
                context={"ad_name": ad.name},
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        today = date.today()
        freq = avg_ad(db, target.ad_id, "frequency", 7, today)
        if freq is None or float(freq) <= self.FREQ_CEILING:
            return None

        return DetectorFinding(
            evidence={
                "avg_frequency_7d": float(freq),
                "ceiling": self.FREQ_CEILING,
                "funnel_stage": target.funnel_stage,
                "targeted_country": target.targeted_country,
                "ad_name": target.context.get("ad_name"),
            },
            metrics_snapshot=snapshot_ad(db, target.ad_id, today),
        )

    def build_action(
        self, target: DetectorTarget, finding: DetectorFinding,
    ) -> dict:
        return {"function": "pause_ad", "kwargs": {}}
