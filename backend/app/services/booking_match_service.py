"""Booking match service — port of Google Sheet matching logic.

Matches PMS reservations to Ads campaign metrics by date + revenue + country.
Operates at campaign level, hotel branches only.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.reservation import Reservation
from app.services.reservation_sync import extract_rate_plan_from_room_type

logger = logging.getLogger(__name__)

# Hotel branch keys (canonical, used as bridge between AdAccount.account_name and PMS branch)
HOTEL_BRANCH_KEYS = ["Saigon", "Taipei", "1948", "Osaka", "Oani"]

# Tolerance for revenue/grand_total comparison (rounding/float precision)
AMOUNT_TOLERANCE = 0.5


def normalize_branch(name: str | None) -> str | None:
    """Map an ad account name or PMS branch label to a canonical branch key.

    Examples:
        "Meander Saigon" -> "Saigon"
        "MEANDER Taipei" -> "Taipei"
        "Oani (Taipei)" -> "Oani" (Oani checked first to avoid Taipei collision)
    """
    if not name:
        return None
    name_lower = name.lower()
    # Check Oani first because "Oani (Taipei)" contains both
    if "oani" in name_lower:
        return "Oani"
    for key in HOTEL_BRANCH_KEYS:
        if key == "Oani":
            continue
        if key.lower() in name_lower:
            return key
    return None


def _find_combination(candidates: list[Reservation], n: int, target: float) -> list[Reservation] | None:
    """Find a combination of exactly n reservations whose grand_totals sum to target.

    Same recursive search as the Google Sheet logic.
    """
    result: list[list[Reservation]] = []

    def search(start: int, current: list[Reservation], current_sum: float):
        if result:
            return  # only need first match
        if len(current) == n:
            if abs(current_sum - target) < AMOUNT_TOLERANCE:
                result.append(list(current))
            return
        for i in range(start, len(candidates)):
            amount = float(candidates[i].grand_total or 0)
            current.append(candidates[i])
            search(i + 1, current, current_sum + amount)
            current.pop()
            if result:
                return

    search(0, [], 0.0)
    return result[0] if result else None


def _dedupe(reservations: list[Reservation]) -> list[Reservation]:
    """Deduplicate by reservation_number, preserving order."""
    seen = set()
    out = []
    for r in reservations:
        if r.reservation_number not in seen:
            seen.add(r.reservation_number)
            out.append(r)
    return out


def _country_matches(reservation_country: str | None, ads_country: str | None) -> bool:
    """Loose country comparison (case-insensitive substring)."""
    if not reservation_country or not ads_country:
        return False
    return ads_country.lower() in reservation_country.lower() or \
        reservation_country.lower() in ads_country.lower()


def _try_match(
    candidates: list[Reservation],
    bookings: int,
    revenue: float,
    ads_country: str | None,
) -> tuple[list[Reservation], str] | None:
    """Try to match revenue against reservation candidates.

    Returns (matched_reservations, result_label) or None.
    """
    exact = _dedupe([
        r for r in candidates
        if r.grand_total is not None and abs(float(r.grand_total) - revenue) < AMOUNT_TOLERANCE
    ])

    if bookings == 1:
        if len(exact) == 1:
            return exact, "Matched"
        if len(exact) > 1:
            by_country = _dedupe([r for r in exact if _country_matches(r.country, ads_country)])
            pool = by_country if by_country else exact
            if len(pool) == 1:
                return pool, "Matched (country)"
            return pool, "Multiple"
        return None

    # bookings > 1: combinatorial search
    combo = _find_combination(candidates, bookings, revenue)
    if combo:
        return _dedupe(combo), "Matched (combo)"
    return None


def run_matching(
    db: Session,
    date_from: date,
    date_to: date,
) -> dict:
    """Run the matching algorithm for the given date range.

    Steps:
    1. Delete existing matches in date range (idempotent re-run).
    2. Aggregate ads metrics at campaign-day level (hotel branches only).
    3. For each ads row with revenue > 0, try to match against reservations.
    4. Persist results to booking_matches table.
    """
    # 1. Clear old matches in this date range so re-runs are idempotent
    db.query(BookingMatch).filter(
        BookingMatch.match_date >= date_from,
        BookingMatch.match_date <= date_to,
    ).delete(synchronize_session=False)
    db.commit()

    # 2. Build ads aggregation: campaign-level rows only (ad_set_id NULL, ad_id NULL)
    ads_rows = (
        db.query(
            MetricsCache.date.label("date"),
            MetricsCache.campaign_id.label("campaign_id"),
            MetricsCache.platform.label("platform"),
            Campaign.name.label("campaign_name"),
            AdAccount.account_name.label("account_name"),
            func.sum(MetricsCache.revenue).label("revenue"),
            func.sum(MetricsCache.conversions).label("bookings"),
        )
        .join(Campaign, Campaign.id == MetricsCache.campaign_id)
        .join(AdAccount, AdAccount.id == Campaign.account_id)
        .filter(
            MetricsCache.date >= date_from,
            MetricsCache.date <= date_to,
            MetricsCache.ad_set_id.is_(None),
            MetricsCache.ad_id.is_(None),
            MetricsCache.revenue > 0,
        )
        .group_by(
            MetricsCache.date,
            MetricsCache.campaign_id,
            MetricsCache.platform,
            Campaign.name,
            AdAccount.account_name,
        )
        .all()
    )

    # 3. Pre-load reservations grouped by (date, branch_key)
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.reservation_date >= date_from,
            Reservation.reservation_date <= date_to,
            Reservation.grand_total.isnot(None),
        )
        .all()
    )

    res_by_key: dict[tuple, list[Reservation]] = {}
    for r in reservations:
        branch_key = normalize_branch(r.branch)
        if not branch_key:
            continue
        key = (r.reservation_date, branch_key)
        res_by_key.setdefault(key, []).append(r)

    # 4. Match loop
    matches_created = 0
    matches_skipped = 0
    now = datetime.now(timezone.utc)

    for row in ads_rows:
        branch_key = normalize_branch(row.account_name)
        if not branch_key:
            matches_skipped += 1
            continue

        revenue = float(row.revenue or 0)
        if revenue <= 0:
            continue

        bookings = int(row.bookings or 1) or 1
        candidates = res_by_key.get((row.date, branch_key), [])

        if not candidates:
            continue

        # Priority: try website/booking engine first, then other sources
        website = [r for r in candidates if (r.source or "").lower() == "website/booking engine"]
        other = [r for r in candidates if (r.source or "").lower() != "website/booking engine"]

        # Ads "country" is unknown at campaign level here — pass branch-level country if available
        ads_country = None  # placeholder; could be enhanced via campaign country parsing

        match = _try_match(website, bookings, revenue, ads_country)
        if not match:
            match = _try_match(other, bookings, revenue, ads_country)

        if not match:
            continue

        matched_reservations, result_label = match

        bm = BookingMatch(
            match_date=row.date,
            ads_revenue=Decimal(str(revenue)),
            ads_bookings=bookings,
            ads_country=None,
            ads_channel=row.platform,
            campaign_name=row.campaign_name,
            campaign_id=row.campaign_id,
            reservation_ids=", ".join(str(r.id) for r in matched_reservations),
            reservation_numbers=", ".join(r.reservation_number or "" for r in matched_reservations),
            guest_names=", ".join(r.name or "" for r in matched_reservations),
            guest_emails=", ".join(r.email or "" for r in matched_reservations),
            reservation_statuses=", ".join(r.status or "" for r in matched_reservations),
            room_types=", ".join(r.room_type or "" for r in matched_reservations),
            rate_plans=", ".join(
                (r.rate_plan_name or extract_rate_plan_from_room_type(r.room_type) or "")
                for r in matched_reservations
            ),
            reservation_sources=", ".join(r.source or "" for r in matched_reservations),
            matched_country=", ".join(r.country or "" for r in matched_reservations),
            branch=branch_key,
            match_result=result_label,
            matched_at=now,
        )
        db.add(bm)
        matches_created += 1

    db.commit()

    summary = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "ads_rows_processed": len(ads_rows),
        "reservations_loaded": len(reservations),
        "matches_created": matches_created,
        "ads_rows_no_branch": matches_skipped,
    }
    logger.info("Booking match run complete: %s", summary)
    return summary
