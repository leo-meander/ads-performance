"""Seasonal detectors (shared GoogleSeasonalityEvent table).

Seasonality data is keyed by country_code and lives in the
`google_seasonality_events` table seeded by migrations 011/012. Both Google
and Meta detectors read from it — per the memory rule, Meta simply filters
events by the union of the branch's home country and the ad set's parsed
targeted country.

- META_SEASONAL_BUDGET_BUMP — event lead-time window open -> raise budget
- META_SEASONAL_BUDGET_CUT  — event ended yesterday -> cut budget back
- META_LOW_SEASON_SHIFT     — branch in low-season window -> guidance only
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.google_seasonality_event import GoogleSeasonalityEvent
from app.services.meta_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.meta_recommendations.registry import register
from app.services.meta_recommendations.seasonality_scope import (
    home_country_for_account,
    relevant_country_codes_for_campaign,
)
from app.services.meta_recommendations.utils import (
    campaign_funnel_stage,
    snapshot_campaign,
)


def _in_event_window(event: GoogleSeasonalityEvent, today: date) -> tuple[bool, date, date]:
    """Return (is_today_within_window_including_lead_time, window_start, window_end)."""
    start = date(today.year, event.start_month, event.start_day)
    end = date(today.year, event.end_month, event.end_day)
    if end < start:
        # Wrap-around events (e.g. Shogatsu Dec 20 -> Jan 5)
        end = end.replace(year=today.year + 1)
    lead = start - timedelta(days=int(event.lead_time_days))
    return lead <= today <= end, start, end


def _past_event_window(event: GoogleSeasonalityEvent, today: date) -> tuple[bool, date, date]:
    """Did the event end yesterday (so we should cut budget today)?"""
    start = date(today.year, event.start_month, event.start_day)
    end = date(today.year, event.end_month, event.end_day)
    if end < start:
        end = end.replace(year=today.year + 1)
    ended_yesterday = end == today - timedelta(days=1)
    return ended_yesterday, start, end


def _scope_active_meta_campaigns_with_budget(
    db: Session, account_ids: list[str] | None,
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


def _match_event(
    db: Session,
    target: DetectorTarget,
    check: callable,
) -> tuple[GoogleSeasonalityEvent, date, date] | None:
    """Find the first seasonal event whose country_code is relevant AND the
    date check passes.

    Skips low_* events (those belong to LowSeasonShiftDetector).
    """
    countries = relevant_country_codes_for_campaign(
        db, db.query(Campaign).filter(Campaign.id == target.campaign_id).first(),
    )
    if not countries:
        return None
    today = date.today()
    events = (
        db.query(GoogleSeasonalityEvent)
        .filter(GoogleSeasonalityEvent.country_code.in_(countries))
        .all()
    )
    for ev in events:
        if ev.event_key.startswith("low_"):
            continue
        ok, start, end = check(ev, today)
        if ok:
            return ev, start, end
    return None


# ─────────────────────────────────────────────────────────────────────────
# META_SEASONAL_BUDGET_BUMP — campaign level, auto-apply
# ─────────────────────────────────────────────────────────────────────────
@register
class SeasonalBudgetBumpDetector(Detector):
    rec_type = "META_SEASONAL_BUDGET_BUMP"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        yield from _scope_active_meta_campaigns_with_budget(db, account_ids)

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        current_budget = target.context.get("current_daily_budget")
        if not current_budget or current_budget <= 0:
            return None

        match = _match_event(db, target, _in_event_window)
        if not match:
            return None
        ev, start, end = match
        # Use the midpoint of the playbook bump range, capped at +25% per
        # Golden Rule #4.
        lo = float(ev.budget_bump_pct_min or 0)
        hi = float(ev.budget_bump_pct_max or 0)
        if lo <= 0 and hi <= 0:
            return None
        mid_pct = (lo + hi) / 2 if hi > 0 else lo
        apply_pct = min(mid_pct, 25.0)  # cap at Golden Rule #4
        new_budget = round(float(current_budget) * (1 + apply_pct / 100.0), 2)

        return DetectorFinding(
            evidence={
                "event_key": ev.event_key,
                "event_name": ev.name,
                "country_code": ev.country_code,
                "event_start": str(start),
                "event_end": str(end),
                "lead_time_days": int(ev.lead_time_days),
                "playbook_bump_pct_min": lo,
                "playbook_bump_pct_max": hi,
                "applied_bump_pct": apply_pct,
                "current_daily_budget": float(current_budget),
                "proposed_daily_budget": new_budget,
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id),
            action_kwargs={"new_daily_budget": new_budget},
        )

    def build_action(
        self, target: DetectorTarget, finding: DetectorFinding,
    ) -> dict:
        return {
            "function": "update_campaign_budget",
            "kwargs": finding.action_kwargs,
        }


# ─────────────────────────────────────────────────────────────────────────
# META_SEASONAL_BUDGET_CUT — campaign level, auto-apply
# ─────────────────────────────────────────────────────────────────────────
@register
class SeasonalBudgetCutDetector(Detector):
    rec_type = "META_SEASONAL_BUDGET_CUT"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        yield from _scope_active_meta_campaigns_with_budget(db, account_ids)

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        current_budget = target.context.get("current_daily_budget")
        if not current_budget or current_budget <= 0:
            return None

        match = _match_event(db, target, _past_event_window)
        if not match:
            return None
        ev, start, end = match
        # Cut by playbook bump midpoint (inverse) but cap at -25%.
        lo = float(ev.budget_bump_pct_min or 0)
        hi = float(ev.budget_bump_pct_max or 0)
        mid_pct = (lo + hi) / 2 if hi > 0 else lo
        cut_pct = min(mid_pct, 25.0)
        new_budget = round(float(current_budget) * (1 - cut_pct / 100.0), 2)

        return DetectorFinding(
            evidence={
                "event_key": ev.event_key,
                "event_name": ev.name,
                "country_code": ev.country_code,
                "event_ended": str(end),
                "cut_pct": cut_pct,
                "current_daily_budget": float(current_budget),
                "proposed_daily_budget": new_budget,
                "campaign_name": target.context.get("campaign_name"),
            },
            metrics_snapshot=snapshot_campaign(db, target.campaign_id),
            action_kwargs={"new_daily_budget": new_budget},
        )

    def build_action(
        self, target: DetectorTarget, finding: DetectorFinding,
    ) -> dict:
        return {
            "function": "update_campaign_budget",
            "kwargs": finding.action_kwargs,
        }


# ─────────────────────────────────────────────────────────────────────────
# META_LOW_SEASON_SHIFT — account level, guidance-only
# ─────────────────────────────────────────────────────────────────────────
@register
class LowSeasonShiftDetector(Detector):
    rec_type = "META_LOW_SEASON_SHIFT"

    def scope(
        self, db: Session, account_ids: list[str] | None = None,
    ) -> Iterable[DetectorTarget]:
        # Account-level — one finding per branch when a low_* event is active
        # in the branch's home country.
        from app.models.account import AdAccount

        q = (
            db.query(AdAccount)
            .filter(AdAccount.platform == "meta")
            .filter(AdAccount.is_active.is_(True))
        )
        if account_ids:
            q = q.filter(AdAccount.id.in_(account_ids))
        for acc in q.all():
            yield DetectorTarget(
                entity_level="account",
                entity_id=acc.id,
                account_id=acc.id,
                context={"account_name": acc.account_name},
            )

    def evaluate(
        self, db: Session, target: DetectorTarget,
    ) -> DetectorFinding | None:
        home = home_country_for_account(db, target.account_id)
        if not home:
            return None
        today = date.today()
        events = (
            db.query(GoogleSeasonalityEvent)
            .filter(GoogleSeasonalityEvent.country_code == home)
            .filter(GoogleSeasonalityEvent.event_key.like("low_%"))
            .all()
        )
        for ev in events:
            ok, start, end = _in_event_window(ev, today)
            if ok:
                return DetectorFinding(
                    evidence={
                        "event_key": ev.event_key,
                        "event_name": ev.name,
                        "country_code": ev.country_code,
                        "window_start": str(start),
                        "window_end": str(end),
                        "home_country": home,
                        "account_name": target.context.get("account_name"),
                    },
                    metrics_snapshot={},
                )
        return None
