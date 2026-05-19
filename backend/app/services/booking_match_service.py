"""Booking match service — matches PMS reservations to ads performance.

Matching methodology (as used in the team's manual Sheet):
  - Breakdown ads by (date, ad_name, user-country).
  - Two passes per ads row:
      website purchase value  → search reservations with source = Website/Booking Engine
      offline purchase value  → search reservations with other sources (OTA, Walk-in, ...)
  - Candidates are restricted to the same date, branch, and country (ISO-2).
  - A match occurs when the sum of grand_totals equals the ads revenue
    within AMOUNT_TOLERANCE.

Country comparison: both sides are ISO-2. Ads-side ISO comes from Meta/Google
breakdowns; reservation-side ISO is normalised at sync time from Cloudbeds'
mixed-format country field. When a reservation has country_iso = NULL (junk
PMS value: "Unknown", "00", missing), we treat it as country-unknown and
allow it to match any ad ISO — this preserves matches for OTA bookings where
Cloudbeds didn't capture nationality, while strict ISO equality is enforced
for the rest.

Data source:
  - Meta: ad_country_metrics rows at ad_id × date × country level (pulled via
    breakdowns=country on ad insights).
  - Google: ad_country_metrics rows at campaign_id × date × country level
    (pulled from user_location_view with segments.geo_target_country).

Reservations are matched on `reservation_date` (booking date), not check-in.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.reservation import Reservation
from app.services.reservation_sync import extract_rate_plan_from_room_type

logger = logging.getLogger(__name__)

HOTEL_BRANCH_KEYS = ["Saigon", "Taipei", "1948", "Osaka", "Oani"]
AMOUNT_TOLERANCE = 0.5
WEBSITE_SOURCE = "website/booking engine"

# country_match_method values stored on BookingMatch:
#   - "exact":  every matched reservation's country_iso == ads_country
#   - "null_country": every matched reservation has country_iso = NULL
#       (PMS didn't capture nationality — common for OTA/Walk-in bookings).
#       Treated as low-confidence in the UI.
#   - "mixed": a mix of exact-ISO and null-ISO reservations within the same
#       match (only happens on multi-reservation combo matches).
METHOD_EXACT = "exact"
METHOD_NULL = "null_country"
METHOD_MIXED = "mixed"


def normalize_branch(name: str | None) -> str | None:
    if not name:
        return None
    name_lower = name.lower()
    if "oani" in name_lower:
        return "Oani"
    for key in HOTEL_BRANCH_KEYS:
        if key == "Oani":
            continue
        if key.lower() in name_lower:
            return key
    return None


def country_iso_matches_reservation(ads_iso: str | None, reservation: Reservation) -> bool:
    """Strict ISO-2 equality between ads country and reservation country.

    Returns True only when both sides have a populated ISO that matches.
    A reservation with country_iso = NULL is *not* considered a match here —
    callers handle the null-country case separately so it can be flagged in
    the match metadata.
    """
    if not ads_iso or not reservation.country_iso:
        return False
    return ads_iso.upper() == reservation.country_iso.upper()


def _classify_match_method(reservations: list[Reservation], ads_iso: str | None) -> str:
    """Tag a successful match with how its country comparison resolved."""
    has_exact = False
    has_null = False
    for r in reservations:
        if r.country_iso and ads_iso and r.country_iso.upper() == ads_iso.upper():
            has_exact = True
        elif not r.country_iso:
            has_null = True
    if has_exact and has_null:
        return METHOD_MIXED
    if has_exact:
        return METHOD_EXACT
    return METHOD_NULL


def _find_combination(
    candidates: list[Reservation], n: int, target: float
) -> list[Reservation] | None:
    """Find the first combination of exactly n reservations whose grand_totals
    sum to target within AMOUNT_TOLERANCE."""
    result: list[list[Reservation]] = []

    def search(start: int, current: list[Reservation], current_sum: float):
        if result:
            return
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
    seen = set()
    out = []
    for r in reservations:
        if r.reservation_number and r.reservation_number not in seen:
            seen.add(r.reservation_number)
            out.append(r)
    return out


def _try_match(
    candidates: list[Reservation],
    bookings: int,
    revenue: float,
) -> tuple[list[Reservation], str] | None:
    exact = _dedupe([
        r for r in candidates
        if r.grand_total is not None and abs(float(r.grand_total) - revenue) < AMOUNT_TOLERANCE
    ])

    bookings = max(bookings, 1)

    if bookings == 1:
        if len(exact) == 1:
            return exact, "Matched"
        if len(exact) > 1:
            return exact, "Multiple"
        return None

    combo = _find_combination(candidates, bookings, revenue)
    if combo:
        return _dedupe(combo), "Matched (combo)"
    return None


def _is_website_source(source: str | None) -> bool:
    return (source or "").strip().lower() == WEBSITE_SOURCE


def _build_booking_match(
    row,
    revenue: float,
    bookings: int,
    purchase_kind: str,
    result_label: str,
    matched: list[Reservation],
    branch_key: str,
    now: datetime,
) -> BookingMatch:
    return BookingMatch(
        match_date=row["date"],
        ads_revenue=Decimal(str(revenue)),
        ads_bookings=bookings,
        ads_country=row.get("country"),
        ads_channel=row.get("platform"),
        campaign_name=row.get("campaign_name"),
        campaign_id=row.get("campaign_id"),
        ad_id=row.get("ad_id"),
        ad_name=row.get("ad_name"),
        purchase_kind=purchase_kind,
        reservation_ids=", ".join(str(r.id) for r in matched),
        reservation_numbers=", ".join(r.reservation_number or "" for r in matched),
        guest_names=", ".join(r.name or "" for r in matched),
        guest_emails=", ".join(r.email or "" for r in matched),
        reservation_statuses=", ".join(r.status or "" for r in matched),
        room_types=", ".join(r.room_type or "" for r in matched),
        rate_plans=", ".join(
            (r.rate_plan_name or extract_rate_plan_from_room_type(r.room_type) or "")
            for r in matched
        ),
        reservation_sources=", ".join(r.source or "" for r in matched),
        matched_country=", ".join(r.country or "" for r in matched),
        country_match_method=_classify_match_method(matched, row.get("country")),
        branch=branch_key,
        match_result=result_label,
        matched_at=now,
    )


def run_matching(
    db: Session,
    date_from: date,
    date_to: date,
) -> dict:
    """Run the matching algorithm for the given date range.

    Steps:
      1. Clear existing matches in the range (idempotent re-runs).
      2. Load ad×country rows with revenue_website > 0 OR revenue_offline > 0
         joined with campaign/ad/account so we know the ad name + branch.
      3. Pre-bucket reservations by (date, branch, is_website).
      4. For each ads row, run two passes:
           - website revenue → website-source reservations
           - offline revenue → non-website-source reservations
         Country filter (strict ISO-2) applied per pass. Reservations with
         country_iso = NULL count as "unknown country" and can match any ad
         ISO with a `null_country` confidence tag.
      5. Persist one BookingMatch per successful pass.
    """
    db.query(BookingMatch).filter(
        BookingMatch.match_date >= date_from,
        BookingMatch.match_date <= date_to,
    ).delete(synchronize_session=False)
    db.commit()

    # Load ads rows with the entities we need to resolve branch + ad name.
    ads_query = (
        db.query(
            AdCountryMetric.date,
            AdCountryMetric.country,
            AdCountryMetric.platform,
            AdCountryMetric.campaign_id,
            AdCountryMetric.ad_id,
            AdCountryMetric.revenue_website,
            AdCountryMetric.revenue_offline,
            AdCountryMetric.conversions_website,
            AdCountryMetric.conversions_offline,
            Campaign.name.label("campaign_name"),
            AdAccount.account_name.label("account_name"),
            Ad.name.label("ad_name"),
        )
        .join(Campaign, Campaign.id == AdCountryMetric.campaign_id)
        .join(AdAccount, AdAccount.id == Campaign.account_id)
        .outerjoin(Ad, Ad.id == AdCountryMetric.ad_id)
        .filter(
            AdCountryMetric.date >= date_from,
            AdCountryMetric.date <= date_to,
        )
    )
    ads_rows = []
    for r in ads_query.all():
        rev_web = float(r.revenue_website or 0)
        rev_off = float(r.revenue_offline or 0)
        if rev_web <= 0 and rev_off <= 0:
            continue
        ads_rows.append({
            "date": r.date,
            "country": r.country,
            "platform": r.platform,
            "campaign_id": r.campaign_id,
            "ad_id": r.ad_id,
            "revenue_website": rev_web,
            "revenue_offline": rev_off,
            "conversions_website": int(r.conversions_website or 0),
            "conversions_offline": int(r.conversions_offline or 0),
            "campaign_name": r.campaign_name,
            "account_name": r.account_name,
            "ad_name": r.ad_name,
        })

    # Pre-load reservations grouped by (date, branch, is_website).
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
        bucket = "website" if _is_website_source(r.source) else "offline"
        res_by_key.setdefault((r.reservation_date, branch_key, bucket), []).append(r)

    matches_created = 0
    ads_skipped_no_branch = 0
    ads_no_candidates = 0
    now = datetime.now(timezone.utc)

    for row in ads_rows:
        branch_key = normalize_branch(row["account_name"])
        if not branch_key:
            ads_skipped_no_branch += 1
            continue

        for kind, revenue, bookings_hint in (
            ("website", row["revenue_website"], row["conversions_website"]),
            ("offline", row["revenue_offline"], row["conversions_offline"]),
        ):
            if revenue <= 0:
                continue

            key = (row["date"], branch_key, kind)
            candidates_all = res_by_key.get(key, [])

            # Country filter (strict ISO-2 vs ISO-2):
            #   - exact ISO match  → high-confidence pool.
            #   - country_iso NULL → "unknown" pool. PMS didn't capture
            #     nationality (~14% of rows), so we let these match any ad
            #     country, but tag the result as low-confidence in the UI.
            # Reservations whose ISO is *different* from the ad ISO are
            # excluded entirely — they are not the right customer.
            ads_iso = (row.get("country") or "").upper() or None
            exact_pool = [
                r for r in candidates_all
                if country_iso_matches_reservation(ads_iso, r)
            ]
            null_pool = [r for r in candidates_all if not r.country_iso]
            if not exact_pool and not null_pool:
                ads_no_candidates += 1
                continue

            bookings = bookings_hint or 1

            # Try high-confidence pool first, then expand to null-country
            # reservations only if no exact-ISO combination matches the
            # revenue. This is materially stricter than the old behaviour,
            # which dropped the country filter entirely on miss.
            match = _try_match(exact_pool, bookings, revenue) if exact_pool else None
            if not match and null_pool:
                match = _try_match(exact_pool + null_pool, bookings, revenue)
            if not match:
                continue

            matched, result_label = match
            db.add(_build_booking_match(
                row, revenue, bookings, kind, result_label, matched, branch_key, now,
            ))
            matches_created += 1

    db.commit()

    summary = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "ads_rows_processed": len(ads_rows),
        "reservations_loaded": len(reservations),
        "matches_created": matches_created,
        "ads_rows_no_branch": ads_skipped_no_branch,
        "ads_rows_no_candidates": ads_no_candidates,
    }
    logger.info("Booking match run complete: %s", summary)
    return summary
