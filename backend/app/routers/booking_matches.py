"""Booking matches dashboard endpoints."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.core.permissions import accessible_branches, is_admin
from app.database import get_db
from app.dependencies.auth import get_current_user, require_section
from app.models.account import AdAccount
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.reservation import Reservation
from app.models.user import User
from app.routers.accounts import BRANCH_ACCOUNT_MAP, branch_name_patterns
from app.services.booking_match_service import (
    AMOUNT_TOLERANCE,
    normalize_branch,
    run_matching,
)
from app.services.reservation_sync import (
    extract_rate_plan_from_room_type,
    sync_reservations,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _default_date_range() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=29), today


def _apply_branch_scope(q, column, user, db, requested_branch: str | None):
    """Restrict a query to the user's accessible branches for analytics.

    Returns (ok, query, error). When ok=False, caller should return _api_response(error=err).
    When admin: no scope applied beyond the explicit `requested_branch` filter.
    """
    if requested_branch:
        # Explicit branch from client — validate against permissions
        if not is_admin(user):
            allowed = accessible_branches(db, user, "analytics") or []
            if requested_branch not in allowed and requested_branch not in BRANCH_ACCOUNT_MAP:
                return False, q, f"No view access to branch '{requested_branch}'"
            if requested_branch in BRANCH_ACCOUNT_MAP and requested_branch not in allowed:
                return False, q, f"No view access to branch '{requested_branch}'"
        patterns = BRANCH_ACCOUNT_MAP.get(requested_branch, [requested_branch])
        q = q.filter(or_(*[column.ilike(f"%{p}%") for p in patterns]))
        return True, q, None

    if is_admin(user):
        return True, q, None

    allowed = accessible_branches(db, user, "analytics") or []
    if not allowed:
        # Force empty result
        q = q.filter(column == "__no_match__")
        return True, q, None
    patterns = branch_name_patterns(allowed)
    q = q.filter(or_(*[column.ilike(f"%{p}%") for p in patterns]))
    return True, q, None


def _serialize_match(m: BookingMatch) -> dict:
    return {
        "id": m.id,
        "match_date": m.match_date.isoformat() if m.match_date else None,
        "ads_revenue": float(m.ads_revenue or 0),
        "ads_bookings": m.ads_bookings,
        "ads_country": m.ads_country,
        "ads_channel": m.ads_channel,
        "campaign_name": m.campaign_name,
        "campaign_id": m.campaign_id,
        "reservation_numbers": m.reservation_numbers,
        "guest_names": m.guest_names,
        "guest_emails": m.guest_emails,
        "reservation_statuses": m.reservation_statuses,
        "room_types": m.room_types,
        "rate_plans": m.rate_plans,
        "reservation_sources": m.reservation_sources,
        "matched_country": m.matched_country,
        "branch": m.branch,
        "match_result": m.match_result,
        "matched_at": m.matched_at.isoformat() if m.matched_at else None,
    }


@router.get("/booking-matches")
def list_booking_matches(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None),
    channel: str = Query(None),
    match_result: str = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """List booking matches with filters, sorted by date desc (like the Sheet)."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        q = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        ok, q, err = _apply_branch_scope(q, BookingMatch.branch, current_user, db, branch)
        if not ok:
            return _api_response(error=err)
        if channel:
            q = q.filter(BookingMatch.ads_channel == channel)
        if match_result:
            q = q.filter(BookingMatch.match_result == match_result)

        total = q.count()
        rows = q.order_by(BookingMatch.match_date.desc()).offset(offset).limit(limit).all()

        return _api_response(data={
            "items": [_serialize_match(m) for m in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "period": {"from": date_from, "to": date_to},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/booking-matches/summary")
def booking_matches_summary(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """KPI summary for the dashboard."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        base = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        ok, base, err = _apply_branch_scope(base, BookingMatch.branch, current_user, db, branch)
        if not ok:
            return _api_response(error=err)

        # Total KPIs
        total_matches = base.count()
        total_revenue = float(base.with_entities(func.sum(BookingMatch.ads_revenue)).scalar() or 0)
        total_bookings = int(base.with_entities(func.sum(BookingMatch.ads_bookings)).scalar() or 0)

        # By channel
        by_channel_rows = (
            base.with_entities(
                BookingMatch.ads_channel,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.ads_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            )
            .group_by(BookingMatch.ads_channel)
            .all()
        )
        by_channel = [
            {
                "channel": r.ads_channel or "unknown",
                "matches": int(r.matches or 0),
                "revenue": float(r.revenue or 0),
                "bookings": int(r.bookings or 0),
            }
            for r in by_channel_rows
        ]

        # By branch
        by_branch_rows = (
            base.with_entities(
                BookingMatch.branch,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.ads_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            )
            .group_by(BookingMatch.branch)
            .all()
        )
        by_branch = [
            {
                "branch": r.branch or "unknown",
                "matches": int(r.matches or 0),
                "revenue": float(r.revenue or 0),
                "bookings": int(r.bookings or 0),
            }
            for r in by_branch_rows
        ]

        # By result
        by_result_rows = (
            base.with_entities(
                BookingMatch.match_result,
                func.count(BookingMatch.id).label("count"),
            )
            .group_by(BookingMatch.match_result)
            .all()
        )
        by_result = [
            {"result": r.match_result, "count": int(r.count or 0)}
            for r in by_result_rows
        ]

        return _api_response(data={
            "total_matches": total_matches,
            "total_revenue": total_revenue,
            "total_bookings": total_bookings,
            "by_channel": by_channel,
            "by_branch": by_branch,
            "by_result": by_result,
            "period": {"from": date_from, "to": date_to},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/booking-matches/run")
def trigger_match_run(
    date_from: str = Query(None),
    date_to: str = Query(None),
    skip_sync: bool = Query(False, description="Skip PMS sync, only re-run matching"),
    current_user: User = Depends(require_section("analytics", "edit")),
    db: Session = Depends(get_db),
):
    """Manual trigger: pull reservations from PMS, then run matching."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        sync_summary = None
        if not skip_sync:
            sync_summary = sync_reservations(db, df, dt)

        match_summary = run_matching(db, df, dt)

        return _api_response(data={
            "sync": sync_summary,
            "matching": match_summary,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/booking-matches/reservations")
def list_reservations(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None),
    source: str = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Raw reservations list for debugging."""
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        q = db.query(Reservation).filter(
            Reservation.reservation_date >= df,
            Reservation.reservation_date <= dt,
        )
        ok, q, err = _apply_branch_scope(q, Reservation.branch, current_user, db, branch)
        if not ok:
            return _api_response(error=err)
        if source:
            q = q.filter(Reservation.source == source)

        total = q.count()
        rows = q.order_by(Reservation.reservation_date.desc()).offset(offset).limit(limit).all()

        items = [
            {
                "id": r.id,
                "reservation_number": r.reservation_number,
                "reservation_date": r.reservation_date.isoformat() if r.reservation_date else None,
                "check_in_date": r.check_in_date.isoformat() if r.check_in_date else None,
                "check_out_date": r.check_out_date.isoformat() if r.check_out_date else None,
                "grand_total": float(r.grand_total) if r.grand_total is not None else None,
                "country": r.country,
                "name": r.name,
                "email": r.email,
                "status": r.status,
                "source": r.source,
                "room_type": r.room_type,
                "rate_plan_name": r.rate_plan_name,
                "branch": r.branch,
                "nights": r.nights,
                "adults": r.adults,
            }
            for r in rows
        ]

        return _api_response(data={
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/booking-matches/diagnose")
def diagnose_reservation(
    reservation_number: str = Query(..., description="PMS reservation number"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Explain why a specific reservation did or didn't match any ads row.

    Returns the reservation, the matched BookingMatch (if any), and every
    campaign-level ads row on the same day+branch with the revenue delta so
    we can see whether it's a revenue mismatch, a missing ads row, or a
    branch-normalisation issue.
    """
    try:
        r = (
            db.query(Reservation)
            .filter(Reservation.reservation_number == reservation_number)
            .first()
        )
        if not r:
            return _api_response(error=f"Reservation {reservation_number} not found")

        branch_key = normalize_branch(r.branch)
        grand_total = float(r.grand_total) if r.grand_total is not None else None

        # Existing match (if any) — search the ", "-joined reservation_numbers column.
        existing_match = (
            db.query(BookingMatch)
            .filter(BookingMatch.reservation_numbers.ilike(f"%{reservation_number}%"))
            .order_by(BookingMatch.match_date.desc())
            .first()
        )

        # Candidate ads rows: same date, same branch (via AdAccount.account_name).
        ads_candidates: list[dict] = []
        if branch_key and r.reservation_date:
            patterns = BRANCH_ACCOUNT_MAP.get(branch_key, [branch_key])
            rows = (
                db.query(
                    MetricsCache.date.label("date"),
                    MetricsCache.platform.label("platform"),
                    Campaign.id.label("campaign_id"),
                    Campaign.name.label("campaign_name"),
                    AdAccount.account_name.label("account_name"),
                    func.sum(MetricsCache.revenue).label("revenue"),
                    func.sum(MetricsCache.conversions).label("bookings"),
                )
                .join(Campaign, Campaign.id == MetricsCache.campaign_id)
                .join(AdAccount, AdAccount.id == Campaign.account_id)
                .filter(
                    MetricsCache.date == r.reservation_date,
                    MetricsCache.ad_set_id.is_(None),
                    MetricsCache.ad_id.is_(None),
                    MetricsCache.revenue > 0,
                    or_(*[AdAccount.account_name.ilike(f"%{p}%") for p in patterns]),
                )
                .group_by(
                    MetricsCache.date,
                    MetricsCache.platform,
                    Campaign.id,
                    Campaign.name,
                    AdAccount.account_name,
                )
                .all()
            )
            for row in rows:
                revenue = float(row.revenue or 0)
                delta = (revenue - grand_total) if grand_total is not None else None
                ads_candidates.append({
                    "platform": row.platform,
                    "campaign_id": str(row.campaign_id),
                    "campaign_name": row.campaign_name,
                    "account_name": row.account_name,
                    "ads_revenue": revenue,
                    "ads_bookings": int(row.bookings or 0),
                    "revenue_delta_vs_grand_total": delta,
                    "within_tolerance": (
                        delta is not None and abs(delta) < AMOUNT_TOLERANCE
                    ),
                })

        reasons: list[str] = []
        if not branch_key:
            reasons.append(
                f"branch '{r.branch}' could not be normalised to a hotel key"
            )
        if grand_total is None:
            reasons.append("reservation.grand_total is NULL")
        if not r.reservation_date:
            reasons.append("reservation.reservation_date is NULL")
        if not ads_candidates and branch_key and r.reservation_date:
            reasons.append(
                f"no campaign-level ads metrics with revenue>0 on {r.reservation_date} for branch {branch_key}"
            )
        if ads_candidates and not any(c["within_tolerance"] for c in ads_candidates):
            reasons.append(
                "ads revenue does not equal reservation.grand_total within tolerance "
                f"(±{AMOUNT_TOLERANCE}) on any candidate row"
            )

        return _api_response(data={
            "reservation": {
                "id": r.id,
                "reservation_number": r.reservation_number,
                "reservation_date": r.reservation_date.isoformat() if r.reservation_date else None,
                "check_in_date": r.check_in_date.isoformat() if r.check_in_date else None,
                "grand_total": grand_total,
                "country": r.country,
                "status": r.status,
                "source": r.source,
                "room_type": r.room_type,
                "rate_plan_name": r.rate_plan_name or extract_rate_plan_from_room_type(r.room_type),
                "branch": r.branch,
                "branch_key": branch_key,
            },
            "existing_match": _serialize_match(existing_match) if existing_match else None,
            "ads_candidates": ads_candidates,
            "likely_reasons": reasons,
            "amount_tolerance": AMOUNT_TOLERANCE,
        })
    except Exception as e:
        return _api_response(error=str(e))
