"""SEASONALITY_LEAD_TIME_APPROACHING — Seasonal event is within lead-time window.

Per SOP Part 6.2. For each active Google campaign, if the current date is
within `lead_time_days` of an event whose country_code applies to that
campaign (branch home country ∪ targeted countries) and the daily budget
hasn't been raised above baseline, fire a recommendation.

Fires per (account, campaign, event) target so the applier can bump each
campaign's daily budget independently.
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


def _event_start_date(event: GoogleSeasonalityEvent, today: date) -> date:
    """Return the event start date in the current or next year.

    If the event already ended this year, roll over to next year.
    """
    year = today.year
    try:
        start = date(year, event.start_month, event.start_day)
        end_year = year if event.end_month >= event.start_month else year + 1
        end = date(end_year, event.end_month, event.end_day)
    except ValueError:
        return today + timedelta(days=365)
    if end < today:
        try:
            start = date(year + 1, event.start_month, event.start_day)
        except ValueError:
            return today + timedelta(days=365)
    return start


@register
class SeasonalityLeadTimeApproachingDetector(Detector):
    rec_type = "SEASONALITY_LEAD_TIME_APPROACHING"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        today = date.today()
        events = (
            db.query(GoogleSeasonalityEvent)
            .filter(
                # Peak events only — low season handled by a separate detector.
                (GoogleSeasonalityEvent.budget_bump_pct_max.isnot(None))
                & (GoogleSeasonalityEvent.budget_bump_pct_max > 0)
            )
            .all()
        )
        upcoming: list[tuple[GoogleSeasonalityEvent, int]] = []
        for ev in events:
            start = _event_start_date(ev, today)
            days_until = (start - today).days
            if 0 < days_until <= ev.lead_time_days:
                upcoming.append((ev, days_until))
        if not upcoming:
            return

        q = (
            db.query(Campaign)
            .filter(Campaign.platform == "google")
            .filter(Campaign.status == "ACTIVE")
        )
        if account_ids:
            q = q.filter(Campaign.account_id.in_(account_ids))
        for camp in q.all():
            campaign_type = classify_campaign(camp)
            if campaign_type not in ("PMAX", "SEARCH", "DEMAND_GEN"):
                continue
            relevant_countries = relevant_country_codes_for_campaign(db, camp)
            if not relevant_countries:
                # Unknown branch + no targeted countries → skip rather than
                # risk firing the wrong country's calendar.
                continue
            for ev, days_until in upcoming:
                if ev.country_code not in relevant_countries:
                    continue
                yield DetectorTarget(
                    entity_level="campaign",
                    entity_id=f"{camp.id}:{ev.country_code}:{ev.event_key}",
                    account_id=camp.account_id,
                    campaign_id=camp.id,
                    campaign_type=campaign_type,
                    context={
                        "campaign_name": camp.name,
                        "daily_budget": float(camp.daily_budget) if camp.daily_budget else None,
                        "country_code": ev.country_code,
                        "event_key": ev.event_key,
                        "event_name": ev.name,
                        "days_until_event": days_until,
                        "budget_bump_pct_min": float(ev.budget_bump_pct_min or 0),
                        "budget_bump_pct_max": float(ev.budget_bump_pct_max or 0),
                        "notes": ev.notes,
                    },
                )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        daily_budget = target.context.get("daily_budget") or 0
        if not daily_budget:
            return None

        # Only fire if the current daily budget isn't already clearly above the
        # 30-day average spend — a proxy for "already bumped".
        spend_30 = float(sum_metric_for_campaign(db, target.campaign_id, "spend", 30))
        avg_daily_spend = spend_30 / 30 if spend_30 > 0 else 0
        if avg_daily_spend > 0 and daily_budget >= avg_daily_spend * 1.25:
            # Budget already substantially above 30-day average — treat as bumped.
            return None

        pct_min = target.context.get("budget_bump_pct_min") or 0
        pct_max = target.context.get("budget_bump_pct_max") or 0
        mid_pct = (pct_min + pct_max) / 2 if pct_max else pct_min
        new_daily = float(
            (Decimal(str(daily_budget)) * (Decimal("100") + Decimal(str(mid_pct)))) / Decimal("100"),
        )

        evidence: dict[str, Any] = {
            "country_code": target.context.get("country_code"),
            "event_key": target.context.get("event_key"),
            "event_name": target.context.get("event_name"),
            "days_until_event": target.context.get("days_until_event"),
            "current_daily_budget": daily_budget,
            "avg_daily_spend_30d": avg_daily_spend,
            "recommended_bump_pct": mid_pct,
            "recommended_new_daily_budget": new_daily,
            "campaign_name": target.context.get("campaign_name"),
        }
        warning_vars = {
            "event_name": target.context.get("event_name"),
            "days": target.context.get("days_until_event"),
            "pct": int(mid_pct),
        }
        return DetectorFinding(
            evidence=evidence,
            metrics_snapshot=snapshot_metrics(db, target.campaign_id),
            action_kwargs={
                "campaign_id": target.campaign_id,
                "new_daily_budget": new_daily,
                "bump_pct": mid_pct,
            },
            warning_vars=warning_vars,
            title_override=(
                f"{target.context.get('event_name')} "
                f"in {target.context.get('days_until_event')} days — raise budget"
            ),
        )

    def build_action(
        self, target: DetectorTarget, finding: DetectorFinding,
    ) -> dict[str, Any]:
        return {
            "function": "update_campaign_budget",
            "kwargs": {
                "campaign_id": target.campaign_id,
                "new_daily_budget": finding.action_kwargs["new_daily_budget"],
            },
        }
