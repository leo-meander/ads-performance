"""SEASONALITY_TCPA_ADJUST_DUE — seasonal event active and tCPA still at baseline.

Per SOP Part 6.2. Similar scope to SEASONALITY_LEAD_TIME_APPROACHING but fires
once the event WINDOW is active (not just the lead-time countdown), and only
when the event has a non-zero tCPA adjustment.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.google_seasonality_event import GoogleSeasonalityEvent
from app.services.google_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.google_recommendations.registry import register
from app.services.google_recommendations.seasonality_scope import (
    relevant_country_codes_for_campaign,
)
from app.services.google_recommendations.utils import (
    classify_campaign,
    snapshot_metrics,
    sum_metric_for_campaign,
)


def _event_window_contains(event: GoogleSeasonalityEvent, today: date) -> bool:
    try:
        start = date(today.year, event.start_month, event.start_day)
        end_year = today.year if event.end_month >= event.start_month else today.year + 1
        end = date(end_year, event.end_month, event.end_day)
    except ValueError:
        return False
    return start <= today <= end


@register
class SeasonalityTcpaAdjustDueDetector(Detector):
    rec_type = "SEASONALITY_TCPA_ADJUST_DUE"

    def scope(self, db: Session, account_ids: list[str] | None = None) -> Iterable[DetectorTarget]:
        today = date.today()
        active_events: list[GoogleSeasonalityEvent] = []
        for ev in db.query(GoogleSeasonalityEvent).all():
            if (ev.tcpa_adjust_pct_max or 0) == 0:
                continue
            if _event_window_contains(ev, today):
                active_events.append(ev)
        if not active_events:
            return

        q = (
            db.query(Campaign)
            .filter(Campaign.platform == "google")
            .filter(Campaign.status == "ACTIVE")
        )
        if account_ids:
            q = q.filter(Campaign.account_id.in_(account_ids))
        for camp in q.all():
            if classify_campaign(camp) != "PMAX":
                continue
            relevant_countries = relevant_country_codes_for_campaign(db, camp)
            if not relevant_countries:
                continue
            for ev in active_events:
                if ev.country_code not in relevant_countries:
                    continue
                yield DetectorTarget(
                    entity_level="campaign",
                    entity_id=f"{camp.id}:{ev.country_code}:{ev.event_key}:tcpa",
                    account_id=camp.account_id,
                    campaign_id=camp.id,
                    campaign_type="PMAX",
                    context={
                        "campaign_name": camp.name,
                        "country_code": ev.country_code,
                        "event_key": ev.event_key,
                        "event_name": ev.name,
                        "tcpa_adjust_pct_min": float(ev.tcpa_adjust_pct_min or 0),
                        "tcpa_adjust_pct_max": float(ev.tcpa_adjust_pct_max or 0),
                        "raw_data": camp.raw_data or {},
                    },
                )

    def evaluate(self, db: Session, target: DetectorTarget) -> DetectorFinding | None:
        pct_min = target.context.get("tcpa_adjust_pct_min") or 0
        pct_max = target.context.get("tcpa_adjust_pct_max") or 0
        mid_pct = (pct_min + pct_max) / 2 if pct_max else pct_min
        if mid_pct == 0:
            return None

        raw = target.context.get("raw_data") or {}
        bidding = raw.get("bidding_strategy") or {}
        current_tcpa = bidding.get("target_cpa_micros")
        if current_tcpa:
            current_tcpa = float(current_tcpa) / 1_000_000
        else:
            # Fall back to actual 30-day CPA as the baseline.
            spend_30 = float(sum_metric_for_campaign(db, target.campaign_id, "spend", 30))
            conv_30 = float(sum_metric_for_campaign(db, target.campaign_id, "conversions", 30))
            current_tcpa = spend_30 / conv_30 if conv_30 > 0 else None
        if not current_tcpa:
            return None
        new_tcpa = float(Decimal(str(current_tcpa)) * (Decimal("100") + Decimal(str(mid_pct))) / Decimal("100"))

        return DetectorFinding(
            evidence={
                "country_code": target.context.get("country_code"),
                "event_key": target.context.get("event_key"),
                "event_name": target.context.get("event_name"),
                "current_tcpa": current_tcpa,
                "recommended_tcpa": new_tcpa,
                "pct_adjust": mid_pct,
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_metrics(db, target.campaign_id),
            action_kwargs={
                "campaign_id": target.campaign_id,
                "new_tcpa": new_tcpa,
                "new_tcpa_micros": int(new_tcpa * 1_000_000),
                "pct_adjust": mid_pct,
            },
            warning_vars={"pct": int(mid_pct)},
        )

    def build_action(self, target: DetectorTarget, finding: DetectorFinding) -> dict[str, Any]:
        return {
            "function": "update_tcpa_target",
            "kwargs": {
                "campaign_id": target.campaign_id,
                "new_tcpa_micros": int(finding.action_kwargs["new_tcpa_micros"]),
            },
        }
