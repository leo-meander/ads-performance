"""Booking matches dashboard endpoints."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.core.branches import BRANCH_CURRENCY
from app.core.permissions import accessible_branches, is_admin
from app.database import get_db
from app.dependencies.auth import get_current_user, require_section
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.reservation import Reservation
from app.models.user import User
from app.routers.accounts import BRANCH_ACCOUNT_MAP, branch_name_patterns
from app.services.booking_match_service import (
    AMOUNT_TOLERANCE_PCT,
    amount_tolerance,
    country_iso_matches_reservation,
    normalize_branch,
    run_matching,
)
from app.services.reservation_sync import (
    extract_rate_plan_from_room_type,
    sync_reservations,
)

router = APIRouter()


# Mirror of dashboard FX (routers/country.py). Booking revenue is stored in
# the branch's native currency; we only convert when the response aggregates
# across mixed currencies — same rule as the main dashboard.
FX_TO_VND = {
    "VND": 1,
    "TWD": 800,
    "JPY": 170,
    "USD": 25500,
}


def _fx_to_vnd(currency: str) -> float:
    return FX_TO_VND.get(currency or "VND", 1)


def _parse_branches_param(branches: str | None, branch: str | None) -> list[str]:
    """Accept either ?branches=Saigon,Taipei (new) or ?branch=Saigon (legacy)."""
    if branches:
        return [b.strip() for b in branches.split(",") if b.strip()]
    if branch:
        return [branch.strip()]
    return []


def _resolve_currency(branches_list: list[str]) -> tuple[str, bool]:
    """Return (display_currency, convert_to_vnd) using the same rule as dashboard.

    - 0 branches (admin all-branches): VND, convert.
    - 1 branch: that branch's native currency, no conversion.
    - >1 branches all sharing one currency: that currency, no conversion.
    - >1 branches with mixed currencies: VND, convert.
    """
    if not branches_list:
        return "VND", True
    currencies = {BRANCH_CURRENCY.get(b, "VND") for b in branches_list}
    if len(currencies) == 1:
        return currencies.pop(), False
    return "VND", True


def _convert_revenue(branch_key: str | None, native_revenue: float, convert: bool) -> float:
    if not convert:
        return native_revenue
    return native_revenue * _fx_to_vnd(BRANCH_CURRENCY.get(branch_key or "", "VND"))


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


def _apply_branch_scope(q, column, user, db, requested_branches: list[str] | None, exact_match: bool = False):
    """Restrict a query to the user's accessible branches for analytics.

    Returns (ok, query, error). When ok=False, caller should return _api_response(error=err).
    When admin: no scope applied beyond the explicit `requested_branches` filter.

    exact_match=True for columns that store the canonical branch key directly
    (e.g. BookingMatch.branch = "Taipei"). exact_match=False for columns that
    store full account/PMS names (e.g. Reservation.branch = "Meander Taipei"),
    where ilike against BRANCH_ACCOUNT_MAP patterns is needed.

    requested_branches accepts a list so the dashboard can multi-select branches
    and we still apply a single IN / OR filter.
    """
    requested_branches = [b for b in (requested_branches or []) if b]
    if requested_branches:
        # Explicit branches from client — validate each against permissions
        if not is_admin(user):
            allowed = accessible_branches(db, user, "analytics") or []
            for b in requested_branches:
                if b not in allowed:
                    return False, q, f"No view access to branch '{b}'"
        if exact_match:
            q = q.filter(column.in_(requested_branches))
        else:
            patterns: list[str] = []
            for b in requested_branches:
                patterns.extend(BRANCH_ACCOUNT_MAP.get(b, [b]))
            q = q.filter(or_(*[column.ilike(f"%{p}%") for p in patterns]))
        return True, q, None

    if is_admin(user):
        return True, q, None

    allowed = accessible_branches(db, user, "analytics") or []
    if not allowed:
        # Force empty result
        q = q.filter(column == "__no_match__")
        return True, q, None
    if exact_match:
        q = q.filter(column.in_(allowed))
    else:
        patterns = branch_name_patterns(allowed)
        q = q.filter(or_(*[column.ilike(f"%{p}%") for p in patterns]))
    return True, q, None


def _serialize_match(m: BookingMatch) -> dict:
    return {
        "id": m.id,
        "match_date": m.match_date.isoformat() if m.match_date else None,
        "ads_revenue": float(m.ads_revenue or 0),
        "matched_revenue": float(m.matched_revenue or 0),
        "ads_bookings": m.ads_bookings,
        "ads_country": m.ads_country,
        "ads_channel": m.ads_channel,
        "campaign_name": m.campaign_name,
        "campaign_id": m.campaign_id,
        "ad_id": m.ad_id,
        "ad_name": m.ad_name,
        "purchase_kind": m.purchase_kind,
        "reservation_numbers": m.reservation_numbers,
        "guest_names": m.guest_names,
        "guest_emails": m.guest_emails,
        "reservation_statuses": m.reservation_statuses,
        "room_types": m.room_types,
        "rate_plans": m.rate_plans,
        "reservation_sources": m.reservation_sources,
        "matched_country": m.matched_country,
        "country_match_method": m.country_match_method,
        "branch": m.branch,
        "match_result": m.match_result,
        "confidence": m.confidence,
        "matched_at": m.matched_at.isoformat() if m.matched_at else None,
    }


@router.get("/booking-matches")
def list_booking_matches(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None, description="Legacy single-branch filter"),
    branches: str = Query(None, description="Comma-separated branch names"),
    channel: str = Query(None),
    match_result: str = Query(None),
    purchase_kind: str = Query(None, description="website | offline"),
    confidence: str = Query(None, description="confirmed | inferred"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """List booking matches with filters, sorted by date desc (like the Sheet).

    Revenue is returned in the active display currency: native when a single
    branch (or several branches sharing one currency) is selected, VND with
    FX conversion when the scope is mixed-currency or all-branches.
    """
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        branches_list = _parse_branches_param(branches, branch)
        display_currency, convert = _resolve_currency(branches_list)

        q = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        ok, q, err = _apply_branch_scope(q, BookingMatch.branch, current_user, db, branches_list, exact_match=True)
        if not ok:
            return _api_response(error=err)
        if channel:
            q = q.filter(BookingMatch.ads_channel == channel)
        if match_result:
            q = q.filter(BookingMatch.match_result == match_result)
        if purchase_kind:
            q = q.filter(BookingMatch.purchase_kind == purchase_kind)
        if confidence:
            q = q.filter(BookingMatch.confidence == confidence)

        total = q.count()
        rows = q.order_by(BookingMatch.match_date.desc()).offset(offset).limit(limit).all()

        items = []
        for m in rows:
            payload = _serialize_match(m)
            payload["ads_revenue"] = _convert_revenue(m.branch, payload["ads_revenue"], convert)
            payload["matched_revenue"] = _convert_revenue(m.branch, payload["matched_revenue"], convert)
            items.append(payload)

        return _api_response(data={
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "currency": display_currency,
            "period": {"from": date_from, "to": date_to},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/booking-matches/summary")
def booking_matches_summary(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None, description="Legacy single-branch filter"),
    branches: str = Query(None, description="Comma-separated branch names"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """KPI summary for the dashboard.

    Revenue follows the dashboard rule: native currency when the scope is one
    branch (or several branches that share a currency), VND otherwise. Counts
    (matches, bookings) are currency-independent.
    """
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        branches_list = _parse_branches_param(branches, branch)
        display_currency, convert = _resolve_currency(branches_list)

        base = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        ok, base, err = _apply_branch_scope(base, BookingMatch.branch, current_user, db, branches_list, exact_match=True)
        if not ok:
            return _api_response(error=err)

        # Counts don't depend on currency.
        total_matches = base.count()
        total_bookings = int(base.with_entities(func.sum(BookingMatch.ads_bookings)).scalar() or 0)

        # Revenue must be aggregated per branch first so we can apply the
        # right FX rate per branch when converting to VND.
        by_branch_rows = (
            base.with_entities(
                BookingMatch.branch,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.matched_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            )
            .group_by(BookingMatch.branch)
            .all()
        )
        total_revenue = sum(
            _convert_revenue(r.branch, float(r.revenue or 0), convert)
            for r in by_branch_rows
        )
        by_branch = [
            {
                "branch": r.branch or "unknown",
                "matches": int(r.matches or 0),
                "revenue": _convert_revenue(r.branch, float(r.revenue or 0), convert),
                "bookings": int(r.bookings or 0),
            }
            for r in by_branch_rows
        ]

        # By channel — group by (branch, channel) so we can FX-convert per
        # branch, then collapse across branches into channel totals.
        by_channel_raw = (
            base.with_entities(
                BookingMatch.branch,
                BookingMatch.ads_channel,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.matched_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            )
            .group_by(BookingMatch.branch, BookingMatch.ads_channel)
            .all()
        )
        by_channel_agg: dict[str, dict] = {}
        for r in by_channel_raw:
            key = r.ads_channel or "unknown"
            cur = by_channel_agg.setdefault(
                key, {"channel": key, "matches": 0, "revenue": 0.0, "bookings": 0}
            )
            cur["matches"] += int(r.matches or 0)
            cur["bookings"] += int(r.bookings or 0)
            cur["revenue"] += _convert_revenue(r.branch, float(r.revenue or 0), convert)
        by_channel = list(by_channel_agg.values())

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

        # By confidence — confirmed (revenue summed to ads value) vs inferred
        # (capacity/count only). Counts match rows AND bookings AND PMS revenue
        # per tier so the dashboard can show how much of the match is trustworthy.
        by_confidence_rows = (
            base.with_entities(
                BookingMatch.branch,
                BookingMatch.confidence,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
                func.sum(BookingMatch.matched_revenue).label("revenue"),
            )
            .group_by(BookingMatch.branch, BookingMatch.confidence)
            .all()
        )
        by_confidence_agg: dict[str, dict] = {}
        for r in by_confidence_rows:
            key = r.confidence or "inferred"
            cur = by_confidence_agg.setdefault(
                key, {"confidence": key, "matches": 0, "bookings": 0, "revenue": 0.0}
            )
            cur["matches"] += int(r.matches or 0)
            cur["bookings"] += int(r.bookings or 0)
            cur["revenue"] += _convert_revenue(r.branch, float(r.revenue or 0), convert)
        by_confidence = list(by_confidence_agg.values())

        return _api_response(data={
            "total_matches": total_matches,
            "total_revenue": total_revenue,
            "total_bookings": total_bookings,
            "currency": display_currency,
            "by_channel": by_channel,
            "by_branch": by_branch,
            "by_result": by_result,
            "by_confidence": by_confidence,
            "period": {"from": date_from, "to": date_to},
        })
    except Exception as e:
        return _api_response(error=str(e))

@router.get("/booking-matches/insights")
def booking_matches_insights(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None, description="Legacy single-branch filter"),
    branches: str = Query(None, description="Comma-separated branch names"),
    channel: str = Query(None),
    match_result: str = Query(None),
    purchase_kind: str = Query(None, description="website | offline"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Reservation-side insights for matched bookings.

    Joins matched BookingMatch rows back to Reservation by reservation_number
    so we can surface lead time, room type, adults, nights, ADR — fields the
    ads side doesn't have. ADR + revenue use the same display-currency rule
    as the summary endpoint.
    """
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        branches_list = _parse_branches_param(branches, branch)
        display_currency, convert = _resolve_currency(branches_list)

        q = db.query(BookingMatch).filter(
            BookingMatch.match_date >= df,
            BookingMatch.match_date <= dt,
        )
        ok, q, err = _apply_branch_scope(q, BookingMatch.branch, current_user, db, branches_list, exact_match=True)
        if not ok:
            return _api_response(error=err)
        if channel:
            q = q.filter(BookingMatch.ads_channel == channel)
        if match_result:
            q = q.filter(BookingMatch.match_result == match_result)
        if purchase_kind:
            q = q.filter(BookingMatch.purchase_kind == purchase_kind)

        match_rows = q.all()

        res_numbers: set[str] = set()
        for m in match_rows:
            if not m.reservation_numbers:
                continue
            for n in m.reservation_numbers.split(","):
                n = n.strip()
                if n:
                    res_numbers.add(n)

        def _empty_stats() -> dict:
            return {"count": 0, "avg": 0, "median": 0, "min": 0, "max": 0}

        if not res_numbers:
            return _api_response(data={
                "lead_time_days": _empty_stats(),
                "room_types": [],
                "adults": _empty_stats(),
                "nights": _empty_stats(),
                "adr": _empty_stats(),
                "currency": display_currency,
                "total_reservations": 0,
                "period": {"from": date_from, "to": date_to},
            })

        reservations = (
            db.query(Reservation)
            .filter(Reservation.reservation_number.in_(list(res_numbers)))
            .all()
        )

        lead_times: list[int] = []
        adults_list: list[int] = []
        nights_list: list[int] = []
        adr_values: list[float] = []
        room_counter: dict[str, dict] = {}

        for r in reservations:
            branch_key = normalize_branch(r.branch)

            if r.reservation_date and r.check_in_date:
                delta = (r.check_in_date - r.reservation_date).days
                if delta >= 0:
                    lead_times.append(delta)

            if r.adults is not None and r.adults > 0:
                adults_list.append(int(r.adults))

            if r.nights is not None and r.nights > 0:
                nights_list.append(int(r.nights))

            gt = float(r.grand_total) if r.grand_total is not None else 0.0
            gt_disp = _convert_revenue(branch_key, gt, convert) if gt else 0.0

            if r.nights and r.nights > 0 and gt > 0:
                adr_values.append(gt_disp / r.nights)

            rt = (r.room_type or "Unknown").strip() or "Unknown"
            bucket = room_counter.setdefault(rt, {"room_type": rt, "count": 0, "revenue": 0.0, "nights": 0})
            bucket["count"] += 1
            bucket["revenue"] += gt_disp
            if r.nights:
                bucket["nights"] += int(r.nights)

        def _stats(vals: list[float]) -> dict:
            if not vals:
                return _empty_stats()
            sorted_v = sorted(vals)
            n = len(sorted_v)
            if n % 2 == 1:
                median = sorted_v[n // 2]
            else:
                median = (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
            return {
                "count": n,
                "avg": sum(sorted_v) / n,
                "median": median,
                "min": sorted_v[0],
                "max": sorted_v[-1],
            }

        room_types = sorted(
            room_counter.values(),
            key=lambda x: (-x["revenue"], -x["count"]),
        )

        return _api_response(data={
            "lead_time_days": _stats(lead_times),
            "room_types": room_types,
            "adults": _stats(adults_list),
            "nights": _stats(nights_list),
            "adr": _stats(adr_values),
            "currency": display_currency,
            "total_reservations": len(reservations),
            "period": {"from": date_from, "to": date_to},
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/booking-matches/run-async", status_code=202)
def trigger_match_run_async(
    date_from: str = Query(..., description="ISO date, e.g. 2026-01-01"),
    date_to: str = Query(..., description="ISO date"),
    skip_sync: bool = Query(False, description="Skip PMS sync, only re-run matching"),
    current_user: User = Depends(require_section("analytics", "edit")),
):
    """Like /booking-matches/run but spawns a daemon thread so the request
    returns 202 immediately. Use for long windows (e.g. full year) where the
    sync would otherwise exceed Zeabur's 225s ingress timeout."""
    import logging
    import threading

    from app.database import SessionLocal

    log = logging.getLogger(__name__)
    df = date.fromisoformat(date_from)
    dt = date.fromisoformat(date_to)

    def _worker():
        db = SessionLocal()
        try:
            log.info("[booking-sync-async] %s..%s starting", df, dt)
            if not skip_sync:
                sync_reservations(db, df, dt)
            run_matching(db, df, dt)
            log.info("[booking-sync-async] %s..%s done", df, dt)
        except Exception:
            log.exception("[booking-sync-async] %s..%s failed", df, dt)
        finally:
            db.close()

    threading.Thread(
        target=_worker, name=f"booking-sync-{date_from}-{date_to}", daemon=True,
    ).start()
    return _api_response(data={
        "status": "started",
        "date_from": date_from,
        "date_to": date_to,
        "skip_sync": skip_sync,
        "note": "Runs in background. Refresh /booking dashboard after 5-15 min.",
    })


@router.post("/booking-matches/run")
def trigger_match_run(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None, description="Legacy single-branch filter"),
    branches: str = Query(None, description="Comma-separated branch names — scope sync+match to these only"),
    skip_sync: bool = Query(False, description="Skip PMS sync, only re-run matching"),
    current_user: User = Depends(require_section("analytics", "edit")),
    db: Session = Depends(get_db),
):
    """Manual trigger: pull reservations from PMS, then run matching.

    When `branches` (or legacy `branch`) is set, the sync and matching are
    scoped to those branches only — matches for other branches in the range are
    left untouched. With no branch param, the full range is rebuilt as before.
    """
    try:
        if not date_from or not date_to:
            df, dt = _default_date_range()
            date_from = date_from or df.isoformat()
            date_to = date_to or dt.isoformat()

        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)

        branches_list = _parse_branches_param(branches, branch)
        if branches_list and not is_admin(current_user):
            allowed = accessible_branches(db, current_user, "analytics") or []
            for b in branches_list:
                if b not in allowed:
                    return _api_response(error=f"No view access to branch '{b}'")
        scope = branches_list or None

        sync_summary = None
        if not skip_sync:
            sync_summary = sync_reservations(db, df, dt, branch_keys=scope)

        match_summary = run_matching(db, df, dt, branch_keys=scope)

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
        ok, q, err = _apply_branch_scope(
            q, Reservation.branch, current_user, db,
            [branch] if branch else None,
        )
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
                "country_iso": r.country_iso,
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

        # Candidate ads rows — same date + same branch, from ad_country_metrics
        # (ad×country for Meta, campaign×country for Google).
        ads_candidates: list[dict] = []
        if branch_key and r.reservation_date:
            patterns = BRANCH_ACCOUNT_MAP.get(branch_key, [branch_key])
            rows = (
                db.query(
                    AdCountryMetric.date.label("date"),
                    AdCountryMetric.platform.label("platform"),
                    AdCountryMetric.country.label("country"),
                    AdCountryMetric.revenue_website.label("revenue_website"),
                    AdCountryMetric.revenue_offline.label("revenue_offline"),
                    AdCountryMetric.conversions_website.label("conversions_website"),
                    AdCountryMetric.conversions_offline.label("conversions_offline"),
                    Campaign.name.label("campaign_name"),
                    AdAccount.account_name.label("account_name"),
                    Ad.name.label("ad_name"),
                )
                .join(Campaign, Campaign.id == AdCountryMetric.campaign_id)
                .join(AdAccount, AdAccount.id == Campaign.account_id)
                .outerjoin(Ad, Ad.id == AdCountryMetric.ad_id)
                .filter(
                    # Matching uses a ±1-day window, so diagnose the same span.
                    AdCountryMetric.date >= r.reservation_date - timedelta(days=1),
                    AdCountryMetric.date <= r.reservation_date + timedelta(days=1),
                    or_(*[AdAccount.account_name.ilike(f"%{p}%") for p in patterns]),
                )
                .all()
            )
            for row in rows:
                rev_web = float(row.revenue_website or 0)
                rev_off = float(row.revenue_offline or 0)
                if rev_web <= 0 and rev_off <= 0:
                    continue
                country_match = country_iso_matches_reservation(row.country, r)
                entries = []
                if rev_web > 0:
                    entries.append(("website", rev_web, int(row.conversions_website or 0)))
                if rev_off > 0:
                    entries.append(("offline", rev_off, int(row.conversions_offline or 0)))
                for kind, rev, bk in entries:
                    delta = (rev - grand_total) if grand_total is not None else None
                    ads_candidates.append({
                        "date": row.date.isoformat() if row.date else None,
                        "platform": row.platform,
                        "country": row.country,
                        "country_matches_reservation": country_match,
                        "campaign_name": row.campaign_name,
                        "ad_name": row.ad_name,
                        "account_name": row.account_name,
                        "purchase_kind": kind,
                        "ads_revenue": rev,
                        "ads_bookings": bk,
                        "revenue_delta_vs_grand_total": delta,
                        "within_tolerance": (
                            delta is not None and abs(delta) < amount_tolerance(rev)
                        ),
                    })

        reservation_kind = "website" if (r.source or "").strip().lower() == "website/booking engine" else "offline"
        reasons: list[str] = []
        if not branch_key:
            reasons.append(f"branch '{r.branch}' could not be normalised to a hotel key")
        if grand_total is None:
            reasons.append("reservation.grand_total is NULL")
        if not r.reservation_date:
            reasons.append("reservation.reservation_date is NULL")

        same_kind = [c for c in ads_candidates if c["purchase_kind"] == reservation_kind]
        if not ads_candidates and branch_key and r.reservation_date:
            reasons.append(
                f"no ad×country rows for branch {branch_key} within ±1 day of "
                f"{r.reservation_date}"
            )
        elif ads_candidates and not same_kind:
            reasons.append(
                f"no ads revenue of kind '{reservation_kind}' within ±1 day on this branch — "
                f"candidates only have {sorted({c['purchase_kind'] for c in ads_candidates})}. "
                f"Google reports website conversions only, so offline (OTA/walk-in) bookings "
                f"never match Google rows."
            )
        elif same_kind and not existing_match:
            # New model: matching is presence + capacity based, NOT revenue-sum.
            # A same-kind ads row exists, so the only way this booking is unmatched
            # is that every eligible campaign's capacity (= its conversion count)
            # was already filled by other reservations ranked ahead of it
            # (same-country first, then same-day, then closest value).
            reasons.append(
                "same-kind ads row(s) exist within ±1 day — matching is capacity-based "
                "(each campaign claims up to its reported conversion count, best "
                "country/date first), so this booking lost the slot to other "
                "reservations or the campaign's capacity was exhausted."
            )

        return _api_response(data={
            "reservation": {
                "id": r.id,
                "reservation_number": r.reservation_number,
                "reservation_date": r.reservation_date.isoformat() if r.reservation_date else None,
                "check_in_date": r.check_in_date.isoformat() if r.check_in_date else None,
                "grand_total": grand_total,
                "country": r.country,
                "country_iso": r.country_iso,
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
            "amount_tolerance_pct": AMOUNT_TOLERANCE_PCT,
        })
    except Exception as e:
        return _api_response(error=str(e))
