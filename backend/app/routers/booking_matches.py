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
from app.utils.country_normalize import normalize_country_to_iso

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


# Default window for every endpoint here: the last 7 days (today inclusive).
# It mirrors the dashboard's default preset, and it is deliberately narrow --
# campaign-insights scans every match plus every matched reservation in the
# window, so the window length is the single biggest driver of page load time.
def _default_date_range() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=6), today


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


def _apply_campaign_filter(q, campaign: str | None):
    """Scope a BookingMatch query to one campaign.

    The UI sends the campaign_id when the match row carries one and the
    campaign name otherwise (the matcher leaves campaign_id NULL for rows it
    could only resolve by name), so accept either. campaign_id is a String(36)
    column rather than a native UUID, so both sides are plain string equality.
    """
    if not campaign:
        return q
    return q.filter(or_(
        BookingMatch.campaign_id == campaign,
        BookingMatch.campaign_name == campaign,
    ))


def _campaign_options(q) -> list[dict]:
    """Distinct campaigns in an already-filtered BookingMatch query.

    Feeds the campaign picker. `value` is what the client sends back as
    ?campaign= — the id when there is one, the name otherwise, mirroring
    _apply_campaign_filter.
    """
    rows = q.with_entities(
        BookingMatch.campaign_id, BookingMatch.campaign_name,
    ).distinct().all()
    out: dict[str, dict] = {}
    for cid, name in rows:
        value = str(cid) if cid else (name or "")
        if not value:
            continue
        out.setdefault(value, {
            "value": value,
            "campaign_id": str(cid) if cid else None,
            "campaign_name": name or "(unknown)",
        })
    return sorted(out.values(), key=lambda x: x["campaign_name"].lower())


# --- Lightweight column projections -----------------------------------------
# The analytics endpoints below scan every match/reservation in the window, so
# they must never load full ORM entities: Reservation.raw_data is a multi-KB
# JSONB blob per row that nothing here reads, and hydrating it for thousands of
# rows was the dominant cost of this page (network + JSON decode + ORM identity
# map). Selecting explicit columns returns plain row tuples instead.

_MATCH_COLS = (
    BookingMatch.branch,
    BookingMatch.matched_revenue,
    BookingMatch.ads_revenue,
    BookingMatch.ads_bookings,
    BookingMatch.confidence,
    BookingMatch.ads_country,
    BookingMatch.ads_channel,
    BookingMatch.campaign_id,
    BookingMatch.campaign_name,
    BookingMatch.reservation_numbers,
)

_RES_COLS = (
    Reservation.reservation_number,
    Reservation.reservation_date,
    Reservation.check_in_date,
    Reservation.grand_total,
    Reservation.country_iso,
    Reservation.status,
    Reservation.source,
    Reservation.room_type,
    Reservation.branch,
    Reservation.nights,
    Reservation.adults,
)

# Postgres tops out at 65535 bind params per statement; chunk well under that.
_IN_CHUNK = 5000


def _split_res_numbers(joined: str | None) -> list[str]:
    if not joined:
        return []
    return [n.strip() for n in joined.split(",") if n.strip()]


def _load_reservations(db: Session, numbers: set[str]) -> dict:
    """Fetch the matched reservations as column tuples, keyed by number."""
    out: dict = {}
    nums = list(numbers)
    for i in range(0, len(nums), _IN_CHUNK):
        rows = (
            db.query(*_RES_COLS)
            .filter(Reservation.reservation_number.in_(nums[i:i + _IN_CHUNK]))
            .all()
        )
        for r in rows:
            if r.reservation_number:
                out[r.reservation_number] = r
    return out


def _load_stay_dates(db: Session, numbers: set[str]) -> dict:
    """Fetch (check_in_date, check_out_date, rate_plan) per reservation number.

    Deliberately narrower than ``_load_reservations``: the list endpoint only
    needs the stay window and the rate plan, and it runs over a full API page
    of matches.

    The rate plan is re-derived from ``room_type`` and only falls back to the
    stored ``rate_plan_name``. That order looks backwards — stored ought to be
    authoritative — but the stored column was written by the old extractor,
    which returned None for the nested-bracket shape that dominates this data
    ("... (Extension Promotion (>2 night))") and, for a multi-room booking,
    returned a *different room's* plan. Trusting it would keep serving those
    wrong values. room_type is the raw field and is parsed correctly now, so it
    wins; the stored column still covers rows whose plan came from the PMS's
    own field rather than from room_type.

    The divergence is temporary: the nightly sync re-reads the last 30 days
    with the fixed extractor, so recent rows self-heal and the fallback only
    ever matters for older history.

    Doing this here rather than trusting ``booking_matches.rate_plans`` means
    the table is correct for all history the moment this deploys, with no
    matcher re-run.
    """
    out: dict = {}
    nums = list(numbers)
    for i in range(0, len(nums), _IN_CHUNK):
        rows = (
            db.query(
                Reservation.reservation_number,
                Reservation.check_in_date,
                Reservation.check_out_date,
                Reservation.room_type,
                Reservation.rate_plan_name,
            )
            .filter(Reservation.reservation_number.in_(nums[i:i + _IN_CHUNK]))
            .all()
        )
        for r in rows:
            if r.reservation_number:
                plan = extract_rate_plan_from_room_type(r.room_type) or r.rate_plan_name
                out[r.reservation_number] = (r.check_in_date, r.check_out_date, plan)
    return out


def _empty_stats() -> dict:
    return {"count": 0, "avg": 0, "median": 0, "min": 0, "max": 0}


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
        "reservation_ids": m.reservation_ids,
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
    campaign: str = Query(None, description="campaign_id or campaign_name"),
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
        q = _apply_campaign_filter(q, campaign)

        total = q.count()
        rows = q.order_by(BookingMatch.match_date.desc()).offset(offset).limit(limit).all()

        # Check-in / check-out live on the reservation, not on the match row.
        # Joining them here rather than denormalising them into booking_matches
        # means every match ever made already has them — no migration, and no
        # re-run of the matcher to backfill history. The work is bounded: `rows`
        # is one API page (<= 1000), so this is a single extra indexed lookup.
        stay_numbers: set[str] = set()
        for m in rows:
            stay_numbers.update(_split_res_numbers(m.reservation_numbers))
        stay = _load_stay_dates(db, stay_numbers) if stay_numbers else {}

        items = []
        for m in rows:
            payload = _serialize_match(m)
            payload["ads_revenue"] = _convert_revenue(m.branch, payload["ads_revenue"], convert)
            payload["matched_revenue"] = _convert_revenue(m.branch, payload["matched_revenue"], convert)
            # Same order as reservation_numbers / guest_names / room_types, so a
            # multi-reservation row stays readable column-by-column.
            nums = _split_res_numbers(m.reservation_numbers)
            cells = [stay.get(n) or (None, None, None) for n in nums]
            payload["check_in_dates"] = ", ".join(
                c[0].isoformat() if c[0] else "" for c in cells
            )
            payload["check_out_dates"] = ", ".join(
                c[1].isoformat() if c[1] else "" for c in cells
            )
            # Only override the stored value when we actually resolved the
            # reservations — a match whose reservations are gone keeps whatever
            # the matcher wrote rather than blanking the column.
            if any(c[2] for c in cells):
                payload["rate_plans"] = ", ".join(c[2] or "" for c in cells)
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
    channel: str = Query(None),
    match_result: str = Query(None),
    purchase_kind: str = Query(None, description="website | offline"),
    confidence: str = Query(None, description="confirmed | inferred"),
    campaign: str = Query(None, description="campaign_id or campaign_name"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """KPI summary for the dashboard.

    Revenue follows the dashboard rule: native currency when the scope is one
    branch (or several branches that share a currency), VND otherwise. Counts
    (matches, bookings) are currency-independent.

    Honours the same channel/result/kind/confidence filters as the list so the
    KPI cards reflect exactly what the filtered table shows.
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
        if channel:
            base = base.filter(BookingMatch.ads_channel == channel)
        if match_result:
            base = base.filter(BookingMatch.match_result == match_result)
        if purchase_kind:
            base = base.filter(BookingMatch.purchase_kind == purchase_kind)
        if confidence:
            base = base.filter(BookingMatch.confidence == confidence)
        base = _apply_campaign_filter(base, campaign)

        # One grouped scan feeds every KPI. Grouping by the full
        # (branch, channel, result, confidence) tuple keeps `branch` on each row
        # — which is what lets us FX-convert per branch before rolling up — and
        # its cardinality is tiny (6 branches x 2 channels x 4 results x 2
        # tiers), so collapsing the pivots in Python is free. This replaces six
        # separate aggregate queries, i.e. six round trips to Supabase.
        rows = (
            base.with_entities(
                BookingMatch.branch,
                BookingMatch.ads_channel,
                BookingMatch.match_result,
                BookingMatch.confidence,
                func.count(BookingMatch.id).label("matches"),
                func.sum(BookingMatch.matched_revenue).label("revenue"),
                func.sum(BookingMatch.ads_bookings).label("bookings"),
            )
            .group_by(
                BookingMatch.branch,
                BookingMatch.ads_channel,
                BookingMatch.match_result,
                BookingMatch.confidence,
            )
            .all()
        )

        total_matches = 0
        total_bookings = 0
        total_revenue = 0.0
        by_branch_agg: dict[str, dict] = {}
        by_channel_agg: dict[str, dict] = {}
        by_result_agg: dict[str, dict] = {}
        by_confidence_agg: dict[str, dict] = {}

        for r in rows:
            matches = int(r.matches or 0)
            bookings = int(r.bookings or 0)
            revenue = _convert_revenue(r.branch, float(r.revenue or 0), convert)

            total_matches += matches
            total_bookings += bookings
            total_revenue += revenue

            b = by_branch_agg.setdefault(
                r.branch or "unknown",
                {"branch": r.branch or "unknown", "matches": 0, "revenue": 0.0, "bookings": 0},
            )
            b["matches"] += matches
            b["bookings"] += bookings
            b["revenue"] += revenue

            ch = by_channel_agg.setdefault(
                r.ads_channel or "unknown",
                {"channel": r.ads_channel or "unknown", "matches": 0, "revenue": 0.0, "bookings": 0},
            )
            ch["matches"] += matches
            ch["bookings"] += bookings
            ch["revenue"] += revenue

            res = by_result_agg.setdefault(
                r.match_result, {"result": r.match_result, "count": 0}
            )
            res["count"] += matches

            cf = by_confidence_agg.setdefault(
                r.confidence or "inferred",
                {"confidence": r.confidence or "inferred", "matches": 0, "bookings": 0, "revenue": 0.0},
            )
            cf["matches"] += matches
            cf["bookings"] += bookings
            cf["revenue"] += revenue

        by_branch = list(by_branch_agg.values())
        by_channel = list(by_channel_agg.values())
        by_result = list(by_result_agg.values())
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

        q = db.query(BookingMatch.reservation_numbers).filter(
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

        res_numbers: set[str] = set()
        for (joined,) in q.all():
            res_numbers.update(_split_res_numbers(joined))

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

        reservations = list(_load_reservations(db, res_numbers).values())

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


# Lead-time histogram buckets (days from booking to check-in). Order matters —
# the frontend renders them left-to-right.
LEAD_BUCKETS = ["0", "1-3", "4-7", "8-14", "15+"]


def _lead_bucket(days: int) -> str:
    if days <= 0:
        return "0"
    if days <= 3:
        return "1-3"
    if days <= 7:
        return "4-7"
    if days <= 14:
        return "8-14"
    return "15+"


def _is_canceled(status: str | None) -> bool:
    """True for any cancelled-type PMS status (canceled / cancelled / no-show)."""
    s = (status or "").strip().lower()
    return "cancel" in s or "no_show" in s or "no-show" in s


def _res_is_website(source: str | None) -> bool:
    return (source or "").strip().lower() == "website/booking engine"


@router.get("/booking-matches/campaign-insights")
def booking_matches_campaign_insights(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None, description="Legacy single-branch filter"),
    branches: str = Query(None, description="Comma-separated branch names"),
    channel: str = Query(None),
    match_result: str = Query(None),
    purchase_kind: str = Query(None, description="website | offline"),
    confidence: str = Query(None, description="confirmed | inferred"),
    campaign: str = Query(None, description="campaign_id or campaign_name"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Campaign-segmented intelligence for the Booking-from-Ads page.

    Joins matched BookingMatch rows back to their Reservations and aggregates
    per campaign so each campaign answers, in one row: how many bookings, real
    PMS revenue vs the platform's claimed figure, confirmed share, cancellation
    rate, average lead time, the room types it actually drove, and the actual
    guest countries vs the campaign's targeting country. A separate country-flow
    matrix surfaces the gap between *who the ad targeted* (ads_country) and *who
    actually booked* (reservation country_iso), tagged exact / cross / unknown.

    Honours the same filters as the list/insights endpoints so the panels stay
    in sync with the table. Revenue follows the dashboard display-currency rule.
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

        q = db.query(*_MATCH_COLS).filter(
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

        # The picker's options come from the window BEFORE the campaign filter
        # is applied — otherwise choosing a campaign would collapse the list to
        # that one campaign and there would be no way back to the others.
        campaign_options = _campaign_options(q)

        q = _apply_campaign_filter(q, campaign)
        matches = q.all()

        # Map each matched reservation_number -> its owning match (1:1: the
        # matcher assigns every reservation to at most one ads row).
        res_to_match: dict = {}
        res_numbers: set[str] = set()
        for m in matches:
            for n in _split_res_numbers(m.reservation_numbers):
                res_to_match[n] = m
                res_numbers.add(n)

        res_by_num = _load_reservations(db, res_numbers) if res_numbers else {}

        def _camp_key(m) -> str:
            return str(m.campaign_id) if m.campaign_id else (m.campaign_name or "(unknown)")

        def _new_campaign(m) -> dict:
            return {
                "campaign_id": str(m.campaign_id) if m.campaign_id else None,
                "campaign_name": m.campaign_name or "(unknown)",
                "channel": m.ads_channel,
                "branch": m.branch,
                "matches": 0,
                "bookings": 0,
                "matched_revenue": 0.0,
                "ads_revenue": 0.0,
                "confirmed_bookings": 0,
                "total_ads_bookings": 0,
                "cancel_count": 0,
                "website_bookings": 0,
                "offline_bookings": 0,
                "lead_buckets": {b: 0 for b in LEAD_BUCKETS},
                "_lead_times": [],
                "_nights": [],
                "_adr": [],
                "_rooms": {},
                "_target_counter": {},
                "_actual_counter": {},
            }

        campaigns: dict[str, dict] = {}

        # Pass 1 — match-level: revenue, confirmed share, targeting country.
        for m in matches:
            key = _camp_key(m)
            c = campaigns.setdefault(key, _new_campaign(m))
            c["matches"] += 1
            c["matched_revenue"] += _convert_revenue(m.branch, float(m.matched_revenue or 0), convert)
            c["ads_revenue"] += _convert_revenue(m.branch, float(m.ads_revenue or 0), convert)
            c["total_ads_bookings"] += int(m.ads_bookings or 0)
            if (m.confidence or "") == "confirmed":
                c["confirmed_bookings"] += int(m.ads_bookings or 0)
            tgt = m.ads_country or "ALL"
            c["_target_counter"][tgt] = c["_target_counter"].get(tgt, 0) + 1

        # Pass 2 — reservation-level: cancel, lead time, rooms, actual country.
        # The same walk also accumulates the window-wide reservation stats that
        # /booking-matches/insights returns, so the dashboard gets both panels
        # from a single scan instead of two endpoints repeating the work.
        country_flow: dict[tuple, dict] = {}
        all_leads: list[int] = []
        all_nights: list[int] = []
        all_adults: list[int] = []
        all_adr: list[float] = []
        all_rooms: dict[str, dict] = {}
        for num, m in res_to_match.items():
            r = res_by_num.get(num)
            if not r:
                continue
            c = campaigns[_camp_key(m)]
            gt = float(r.grand_total or 0)
            gt_disp = _convert_revenue(m.branch, gt, convert)

            c["bookings"] += 1
            if _is_canceled(r.status):
                c["cancel_count"] += 1
            if r.reservation_date and r.check_in_date:
                d = (r.check_in_date - r.reservation_date).days
                if d >= 0:
                    c["_lead_times"].append(d)
                    c["lead_buckets"][_lead_bucket(d)] += 1
                    all_leads.append(d)
            if r.adults is not None and r.adults > 0:
                all_adults.append(int(r.adults))
            if r.nights and r.nights > 0:
                c["_nights"].append(int(r.nights))
                all_nights.append(int(r.nights))
                if gt > 0:
                    c["_adr"].append(gt_disp / r.nights)
                    all_adr.append(gt_disp / r.nights)
            if _res_is_website(r.source):
                c["website_bookings"] += 1
            else:
                c["offline_bookings"] += 1

            rt = (r.room_type or "Unknown").strip() or "Unknown"
            rb = c["_rooms"].setdefault(rt, {"room_type": rt, "bookings": 0, "revenue": 0.0})
            rb["bookings"] += 1
            rb["revenue"] += gt_disp

            gb = all_rooms.setdefault(rt, {"room_type": rt, "count": 0, "revenue": 0.0, "nights": 0})
            gb["count"] += 1
            gb["revenue"] += gt_disp
            if r.nights:
                gb["nights"] += int(r.nights)

            actual = (r.country_iso or "").upper() or "Unknown"
            c["_actual_counter"][actual] = c["_actual_counter"].get(actual, 0) + 1

            # Country flow: targeting geo (normalised) vs actual guest ISO.
            target = normalize_country_to_iso(m.ads_country) or (m.ads_country or "ALL")
            if not r.country_iso:
                method = "null_count"
            elif r.country_iso.upper() == (normalize_country_to_iso(m.ads_country) or "\0"):
                method = "exact"
            else:
                method = "cross"
            fk = (target, actual)
            f = country_flow.setdefault(fk, {
                "target": target, "actual": actual,
                "bookings": 0, "revenue": 0.0,
                "exact": 0, "cross": 0, "null_count": 0,
            })
            f["bookings"] += 1
            f["revenue"] += gt_disp
            f[method] += 1

        # Finalise campaigns.
        out_campaigns = []
        tot_bookings = tot_cancel = tot_confirmed = tot_ads_bookings = 0
        for c in campaigns.values():
            bk = c["bookings"]
            leads = c["_lead_times"]
            nights = c["_nights"]
            adrs = c["_adr"]
            tot_bookings += bk
            tot_cancel += c["cancel_count"]
            tot_confirmed += c["confirmed_bookings"]
            tot_ads_bookings += c["total_ads_bookings"]
            target_country = (
                max(c["_target_counter"].items(), key=lambda x: x[1])[0]
                if c["_target_counter"] else None
            )
            out_campaigns.append({
                "campaign_id": c["campaign_id"],
                "campaign_name": c["campaign_name"],
                "channel": c["channel"],
                "branch": c["branch"],
                "target_country": target_country,
                "matches": c["matches"],
                "bookings": bk,
                "matched_revenue": c["matched_revenue"],
                "ads_revenue": c["ads_revenue"],
                "confirmed_share": (c["confirmed_bookings"] / c["total_ads_bookings"] * 100) if c["total_ads_bookings"] else 0,
                "cancel_count": c["cancel_count"],
                "cancel_rate": (c["cancel_count"] / bk * 100) if bk else 0,
                "avg_lead_time": (sum(leads) / len(leads)) if leads else 0,
                "avg_nights": (sum(nights) / len(nights)) if nights else 0,
                "adr": (sum(adrs) / len(adrs)) if adrs else 0,
                "website_bookings": c["website_bookings"],
                "offline_bookings": c["offline_bookings"],
                "lead_buckets": c["lead_buckets"],
                "top_rooms": sorted(
                    c["_rooms"].values(), key=lambda x: (-x["revenue"], -x["bookings"])
                )[:5],
                "top_actual_countries": [
                    {"country": k, "bookings": v}
                    for k, v in sorted(c["_actual_counter"].items(), key=lambda x: -x[1])[:5]
                ],
            })

        out_campaigns.sort(key=lambda x: -x["matched_revenue"])

        flow_rows = sorted(country_flow.values(), key=lambda x: -x["bookings"])
        # Leakage = bookings whose guest country differs from the target, over
        # bookings with a *known* guest country (null/unknown excluded — we can't
        # tell if those leaked). exact + cross only.
        flow_exact = sum(f["exact"] for f in flow_rows)
        flow_cross = sum(f["cross"] for f in flow_rows)
        flow_null = sum(f["null_count"] for f in flow_rows)
        known = flow_exact + flow_cross
        leakage_rate = (flow_cross / known * 100) if known else 0

        return _api_response(data={
            "currency": display_currency,
            "campaigns": out_campaigns,
            "campaign_options": campaign_options,
            "country_flow": flow_rows,
            # Window-wide reservation stats — identical shape to the /insights
            # payload so the dashboard can render its stat cards from here.
            "overall": {
                "lead_time_days": _stats(all_leads),
                "nights": _stats(all_nights),
                "adults": _stats(all_adults),
                "adr": _stats(all_adr),
                "room_types": sorted(
                    all_rooms.values(), key=lambda x: (-x["revenue"], -x["count"])
                ),
                "total_reservations": sum(1 for n in res_to_match if n in res_by_num),
            },
            "totals": {
                "bookings": tot_bookings,
                "cancel_count": tot_cancel,
                "cancel_rate": (tot_cancel / tot_bookings * 100) if tot_bookings else 0,
                "confirmed_share": (tot_confirmed / tot_ads_bookings * 100) if tot_ads_bookings else 0,
                "leakage_rate": leakage_rate,
                "country_known": known,
                "country_exact": flow_exact,
                "country_cross": flow_cross,
                "country_unknown": flow_null,
            },
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


# --- Rate plans --------------------------------------------------------------
# Deliberately PMS-wide, NOT scoped to BookingMatch: plans like "CRM_September
# 2026 Events" or "MEANDER'S FRIEND" are direct/CRM bookings no ad ever touched,
# so joining through matches would hide exactly the plans worth reading.
# rate_plan_name is NULL on rows synced before the extractor existed, so we fall
# back to parsing room_type the same way sync does.

_RATE_PLAN_COLS = (
    Reservation.branch,
    Reservation.rate_plan_name,
    Reservation.room_type,
    Reservation.status,
    Reservation.source,
    Reservation.country,
    Reservation.country_iso,
    Reservation.grand_total,
    Reservation.nights,
    Reservation.adults,
    Reservation.reservation_date,
    Reservation.check_in_date,
)

# How many rows each per-plan breakdown keeps. The whole drill-down ships with
# the list in one response, so these caps are what keep that payload small.
_PLAN_TOP_N = 12


def _bump(bucket: dict, key: str, label_field: str, revenue: float, **extra) -> dict:
    row = bucket.get(key)
    if row is None:
        row = {label_field: key, "bookings": 0, "revenue": 0.0, **extra}
        bucket[key] = row
    row["bookings"] += 1
    row["revenue"] += revenue
    return row


def _top_rows(bucket: dict, n: int = _PLAN_TOP_N) -> list[dict]:
    return sorted(bucket.values(), key=lambda x: (-x["bookings"], -x["revenue"]))[:n]


def _campaign_reservation_numbers(db, df, dt, campaign, user, branches_list) -> set[str] | None:
    """Reservation numbers the given campaign matched inside the window.

    Returns None when the caller lacks access to a requested branch, matching
    _apply_branch_scope's error contract.
    """
    q = db.query(BookingMatch.reservation_numbers).filter(
        BookingMatch.match_date >= df,
        BookingMatch.match_date <= dt,
    )
    ok, q, _err = _apply_branch_scope(
        q, BookingMatch.branch, user, db, branches_list, exact_match=True,
    )
    if not ok:
        return None
    q = _apply_campaign_filter(q, campaign)
    numbers: set[str] = set()
    for (joined,) in q.all():
        numbers.update(_split_res_numbers(joined))
    return numbers


@router.get("/booking-matches/rate-plans")
def booking_matches_rate_plans(
    date_from: str = Query(None),
    date_to: str = Query(None),
    branch: str = Query(None, description="Legacy single-branch filter"),
    branches: str = Query(None, description="Comma-separated branch names"),
    source: str = Query(None),
    campaign: str = Query(
        None,
        description="campaign_id or campaign_name — narrows to that campaign's matched bookings",
    ),
    limit: int = Query(40, le=200, description="Max rate plans returned"),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Rate-plan mix for the window, each plan carrying its own breakdown.

    One pass over the window's reservations produces both the ranked plan list
    and every per-plan drill-down (status, country, branch, source, room, lead
    time, party size), so the UI can open a plan with no second round trip.

    With ?campaign= the panel stops being PMS-wide and reports only the plans
    that campaign's matched bookings bought — the one case where scoping to
    BookingMatch is what was asked for.
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

        q = db.query(*_RATE_PLAN_COLS)
        ok, q, err = _apply_branch_scope(
            q, Reservation.branch, current_user, db, branches_list,
        )
        if not ok:
            return _api_response(error=err)
        if source:
            q = q.filter(Reservation.source == source)

        if campaign:
            # Selection is by reservation number, NOT by reservation_date: the
            # matcher pairs a booking with an ads row up to a day apart, so
            # re-applying the window here would drop the edge bookings that the
            # campaign's own match rows include.
            numbers = _campaign_reservation_numbers(
                db, df, dt, campaign, current_user, branches_list,
            )
            if numbers is None:
                return _api_response(error="No view access to the requested branch")
            nums = sorted(numbers)
            rows = []
            for i in range(0, len(nums), _IN_CHUNK):
                rows.extend(
                    q.filter(
                        Reservation.reservation_number.in_(nums[i:i + _IN_CHUNK]),
                    ).all()
                )
        else:
            rows = q.filter(
                Reservation.reservation_date >= df,
                Reservation.reservation_date <= dt,
            ).all()

        plans: dict[str, dict] = {}
        untagged = 0
        untagged_direct = 0

        for r in rows:
            plan = (r.rate_plan_name or extract_rate_plan_from_room_type(r.room_type) or "").strip()
            if not plan:
                # An OTA booking bought the OTA's own rate, so it has no MEANDER
                # plan to be missing: every OTA source in the table is 0%
                # tagged, structurally. Only a direct booking with no plan is a
                # real gap, and reporting one number for both made that gap look
                # an order of magnitude worse than it is. The second bucket is
                # "other", not "OTA" — Walk-In, Phone and Extension live there
                # too, and those are not OTAs.
                untagged += 1
                if _res_is_website(r.source):
                    untagged_direct += 1
                continue

            p = plans.get(plan)
            if p is None:
                p = plans[plan] = {
                    "rate_plan": plan,
                    "bookings": 0,
                    "canceled": 0,
                    "revenue": 0.0,
                    "revenue_net": 0.0,
                    "_status": {}, "_country": {}, "_branch": {}, "_source": {}, "_room": {},
                    "_lead": {b: 0 for b in LEAD_BUCKETS},
                    "_nights": [], "_adults": [], "_adr": [], "_lead_days": [],
                    "first_booking": None,
                    "last_booking": None,
                }

            branch_key = normalize_branch(r.branch)
            gt = float(r.grand_total) if r.grand_total is not None else 0.0
            revenue = _convert_revenue(branch_key, gt, convert) if gt else 0.0
            canceled = _is_canceled(r.status)

            p["bookings"] += 1
            p["revenue"] += revenue
            if canceled:
                p["canceled"] += 1
            else:
                p["revenue_net"] += revenue

            if r.reservation_date:
                iso = r.reservation_date.isoformat()
                if p["first_booking"] is None or iso < p["first_booking"]:
                    p["first_booking"] = iso
                if p["last_booking"] is None or iso > p["last_booking"]:
                    p["last_booking"] = iso

            _bump(p["_status"], (r.status or "Unknown").strip() or "Unknown", "status", revenue)

            country = (r.country or "").strip() or "Unknown"
            crow = _bump(p["_country"], country, "country", revenue, country_iso=None)
            if not crow.get("country_iso") and r.country_iso:
                crow["country_iso"] = r.country_iso

            _bump(p["_branch"], branch_key or (r.branch or "Unknown"), "branch", revenue)
            _bump(p["_source"], (r.source or "Unknown").strip() or "Unknown", "source", revenue)
            _bump(p["_room"], (r.room_type or "Unknown").strip() or "Unknown", "room_type", revenue)

            # Party size / stay shape read the live bookings only — a cancelled
            # row never happened, and averaging it in flatters nothing.
            if not canceled:
                if r.adults is not None and r.adults > 0:
                    p["_adults"].append(int(r.adults))
                if r.nights is not None and r.nights > 0:
                    p["_nights"].append(int(r.nights))
                    if revenue > 0:
                        p["_adr"].append(revenue / int(r.nights))
                if r.reservation_date and r.check_in_date:
                    delta = (r.check_in_date - r.reservation_date).days
                    if delta >= 0:
                        p["_lead_days"].append(delta)
                        p["_lead"][_lead_bucket(delta)] += 1

        out = []
        ranked = sorted(plans.values(), key=lambda x: (-x["bookings"], -x["revenue_net"]))
        for p in ranked[:limit]:
            bookings = p["bookings"]
            out.append({
                "rate_plan": p["rate_plan"],
                "bookings": bookings,
                "canceled": p["canceled"],
                "live": bookings - p["canceled"],
                "cancel_rate": (p["canceled"] / bookings * 100) if bookings else 0.0,
                "revenue": p["revenue"],
                "revenue_net": p["revenue_net"],
                "first_booking": p["first_booking"],
                "last_booking": p["last_booking"],
                "by_status": sorted(p["_status"].values(), key=lambda x: -x["bookings"]),
                "by_country": _top_rows(p["_country"]),
                "by_branch": _top_rows(p["_branch"]),
                "by_source": _top_rows(p["_source"]),
                "by_room": _top_rows(p["_room"]),
                "lead_buckets": p["_lead"],
                "nights": _stats(p["_nights"]),
                "adults": _stats(p["_adults"]),
                "adr": _stats(p["_adr"]),
                "lead_time_days": _stats(p["_lead_days"]),
            })

        return _api_response(data={
            "plans": out,
            "total_plans": len(plans),
            "total_reservations": len(rows),
            "untagged_reservations": untagged,
            "untagged_direct": untagged_direct,
            "untagged_other": untagged - untagged_direct,
            "campaign": campaign or None,
            "currency": display_currency,
            "period": {"from": date_from, "to": date_to},
        })
    except Exception as e:
        return _api_response(error=str(e))
