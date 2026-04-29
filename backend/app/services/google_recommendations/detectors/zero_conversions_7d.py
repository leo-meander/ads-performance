"""ZERO_CONVERSIONS_7D — Seven consecutive days with zero conversions + non-zero spend.

Per SOP Part 7: indicates broken conversion tag or landing page change. Urgent
manual check.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.services.google_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.google_recommendations.registry import register
from app.services.google_recommendations.utils import (
    classify_campaign,
    daily_metric_series,
    snapshot_metrics,
)

WINDOW_DAYS = 7


@register
class ZeroConversions7DDetector(Detector):
    rec_type = "ZERO_CONVERSIONS_7D"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        q = (
            db.query(Campaign)
            .filter(Campaign.platform == "google")
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
                campaign_type=classify_campaign(camp),
                context={"campaign_name": camp.name},
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        yesterday = date.today() - timedelta(days=1)
        window_start = yesterday - timedelta(days=WINDOW_DAYS - 1)

        spend_series = daily_metric_series(
            db, target.campaign_id, "spend", days=WINDOW_DAYS, today=yesterday,
        )
        conv_series = daily_metric_series(
            db, target.campaign_id, "conversions", days=WINDOW_DAYS, today=yesterday,
        )

        total_spend = 0.0
        for offset in range(WINDOW_DAYS):
            d = yesterday - timedelta(days=offset)
            spend_d = float(spend_series.get(d, 0))
            conv_d = float(conv_series.get(d, 0))
            if spend_d <= 0:
                return None
            if conv_d > 0:
                return None
            total_spend += spend_d

        return DetectorFinding(
            evidence={
                "window_days": WINDOW_DAYS,
                "window_start_date": str(window_start),
                "window_end_date": str(yesterday),
                "total_spend": total_spend,
                "total_conversions": 0,
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_metrics(db, target.campaign_id, today=yesterday),
        )
