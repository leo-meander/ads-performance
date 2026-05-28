"""Booking match service — matches PMS reservations to ads performance.

Matching methodology (as used in the team's manual Sheet):
  - Breakdown ads by (date, ad_name, user-country).
  - Two passes per ads row:
      website purchase value  → search reservations with source = Website/Booking Engine
      offline purchase value  → search reservations with other sources (OTA, Walk-in, ...)
  - Candidates share the same branch and purchase kind. The real match key is
    date + branch + kind + revenue (single or combo). Date is matched same-day
    first (reservation_date == ad date); if nothing matches, the candidate pool
    expands to ±1 day to absorb the short lag between an ad and the booking it
    drives. Country is a *ranking preference*, not a hard restriction (below).
  - A match occurs when the sum of grand_totals equals the ads revenue within
    the amount tolerance (±2%, see amount_tolerance()).

Country ranks (and gates) candidate pools, best-confidence first:
  1. same-country (campaign geo reconciled to guest ISO via
     normalize_country_to_iso, so Google "UK" lines up with reservation "GB"),
  2. + country-unknown reservations (country_iso = NULL: junk PMS value
     "Unknown"/"00"/missing — common for OTA bookings),
  3. the full same-date/branch/kind pool, any nationality —
     ONLY when tiers 1 & 2 are empty (no same-country and no null-country
     candidates in the window at all). If a same-country candidate exists but
     its amount doesn't fit, we'd rather miss than fabricate a cross-country
     match (almost always a coincidence amount hit on common room rates).
This is stricter than the pre-2026-05 behaviour where tier-3 fired whenever
tiers 1 & 2 failed to *match*. Cross-country matches still happen — only when
the campaign's geo has zero candidate guests on that date.

Reservations are also claimed globally per matching run (see run_matching):
once a reservation is attributed to one ad row, it can't be reused by another.
This stops the same booking from being double-counted across adjacent ads
days when Meta reports the same conversion on multiple attribution dates.

The campaign geo is still recorded on the match (ads_country) so the dashboard
can break results down by campaign country.

Data source:
  - Meta: ad_country_metrics rows at ad_id × date × country level (pulled via
    breakdowns=country on ad insights).
  - Google: ad_country_metrics rows at campaign_id × date × country level
    (pulled from user_location_view with segments.geo_target_country).

Reservations are matched on `reservation_date` (booking date), not check-in.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.booking_match import BookingMatch
from app.models.campaign import Campaign
from app.models.reservation import Reservation
from app.services.reservation_sync import extract_rate_plan_from_room_type
from app.utils.country_normalize import normalize_country_to_iso

logger = logging.getLogger(__name__)

HOTEL_BRANCH_KEYS = ["Saigon", "Taipei", "1948", "Osaka", "Oani"]
WEBSITE_SOURCE = "website/booking engine"

# Amount match tolerance. The ad platforms report a purchase value that drifts a
# few % from the PMS grand_total — currency conversion, rounding, fees — so a
# flat ±0.5 was far too tight (e.g. Google reports 2686.91 for a 2,700 booking,
# 5249.67 for 5,400). We allow ±2% of the ads revenue, with a tiny absolute
# floor so near-zero values don't collapse the window to nothing.
AMOUNT_TOLERANCE_PCT = 0.02
AMOUNT_TOLERANCE_FLOOR = 0.5


def amount_tolerance(target: float) -> float:
    """Max allowed |grand_total - ads_revenue| for a match: ±2% (floor ±0.5)."""
    return max(AMOUNT_TOLERANCE_FLOOR, abs(float(target)) * AMOUNT_TOLERANCE_PCT)

# country_match_method records how a match's country comparison resolved. It is
# bookkeeping only (the UI does not filter on it); the field exists so a future
# audit can tell same-country matches from cross-country ones.
#   - "exact":  every matched reservation's country_iso == ads_country
#   - "null_country": every matched reservation has country_iso = NULL
#       (PMS didn't capture nationality — common for OTA/Walk-in bookings).
#   - "mixed": a mix of exact-ISO and null-ISO reservations in one combo match.
#   - "cross_country": at least one matched reservation has a populated ISO that
#       differs from the campaign geo (matched on date+revenue via the tier-3
#       fallback). Expected and valid — targeting geo != guest nationality.
METHOD_EXACT = "exact"
METHOD_NULL = "null_country"
METHOD_MIXED = "mixed"
METHOD_CROSS = "cross_country"


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


def _normalize_ads_iso(ads_country: str | None) -> str | None:
    """Reconcile an ads-side country onto the reservation ISO-2 vocabulary.

    The ads pipeline stores the country as parsed from the campaign/adset name
    ("UK", "VN", "TW", ...). Routing it through the same normaliser the
    reservation side uses lets divergent codes line up — most importantly
    Google's "UK", which the reservation side stores as "GB". Valid ISO-2 codes
    pass through unchanged; junk / multi-country markers ("ALL") return None.
    """
    return normalize_country_to_iso(ads_country)


def country_iso_matches_reservation(ads_iso: str | None, reservation: Reservation) -> bool:
    """Strict ISO-2 equality between ads country and reservation country.

    Returns True only when both sides have a populated ISO that matches. The
    ads side is normalised first (see _normalize_ads_iso) so that vocabulary
    differences like "UK" vs "GB" don't cause false misses. A reservation with
    country_iso = NULL is *not* considered a match here — callers handle the
    null-country case separately so it can be flagged in the match metadata.
    """
    ads = _normalize_ads_iso(ads_iso)
    if not ads or not reservation.country_iso:
        return False
    return ads == reservation.country_iso.upper()


def _classify_match_method(reservations: list[Reservation], ads_iso: str | None) -> str:
    """Tag a successful match with how its country comparison resolved."""
    ads = _normalize_ads_iso(ads_iso)
    has_exact = False
    has_null = False
    has_cross = False
    for r in reservations:
        if not r.country_iso:
            has_null = True
        elif ads and r.country_iso.upper() == ads:
            has_exact = True
        else:
            # Populated nationality that differs from the campaign geo — a
            # tier-3 fallback match (or the ad country didn't normalise).
            has_cross = True
    if has_cross:
        return METHOD_CROSS
    if has_exact and has_null:
        return METHOD_MIXED
    if has_exact:
        return METHOD_EXACT
    return METHOD_NULL


def _find_combination(
    candidates: list[Reservation], n: int, target: float
) -> list[Reservation] | None:
    """Find the first combination of exactly n reservations whose grand_totals
    sum to target within the amount tolerance (±2%)."""
    result: list[list[Reservation]] = []
    tol = amount_tolerance(target)

    def search(start: int, current: list[Reservation], current_sum: float):
        if result:
            return
        if len(current) == n:
            if abs(current_sum - target) < tol:
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
    tol = amount_tolerance(revenue)
    exact = _dedupe([
        r for r in candidates
        if r.grand_total is not None and abs(float(r.grand_total) - revenue) < tol
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


def _match_country_tiers(
    candidates: list[Reservation],
    ads_country: str | None,
    bookings: int,
    revenue: float,
) -> tuple[list[Reservation], str] | None:
    """Match within a candidate pool, gated by country confidence.

    Pools, tried in order:
      1. same-country (campaign geo reconciled to guest ISO, e.g. ad "UK"->"GB"),
      2. + country-unknown reservations (country_iso = NULL),
      3. the full pool, any nationality — ONLY when tiers 1 & 2 are empty.

    Tier-3 is gated on *candidate presence*, not on tier-1/2 match failure.
    If any same-country or null-country candidate exists in the window — even
    one whose amount doesn't fit — we refuse to fall through to a cross-country
    match. That stops the algorithm from picking a coincidentally-amount-equal
    booking from an unrelated nationality (the dominant failure mode at common
    rates like Taipei 1.44M VND, where many guests share the same total).
    """
    if not candidates:
        return None
    exact_pool = [
        r for r in candidates if country_iso_matches_reservation(ads_country, r)
    ]
    null_pool = [r for r in candidates if not r.country_iso]

    if exact_pool:
        match = _try_match(exact_pool, bookings, revenue)
        if match:
            return match

    if exact_pool or null_pool:
        match = _try_match(exact_pool + null_pool, bookings, revenue)
        if match:
            return match
        # Same-country/null signal exists but doesn't fit — refuse tier-3.
        return None

    return _try_match(candidates, bookings, revenue)


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
      4. Two-pass matching with global reservation claim tracking:
           Pass A — same-day only (reservation_date == ad date) for every ad
                    row. This is the highest-confidence pairing.
           Pass B — ±1 day fallback for ad rows that didn't match in pass A,
                    excluding reservations already claimed in pass A.
         Inside each pass, country tiers gate cross-country fallback
         (_match_country_tiers). Within a pass, ad rows are processed by
         descending revenue so larger (rarer) bookings claim their match
         before smaller, more ambiguous amounts.
      5. Once a reservation is matched, it's removed from the candidate pool
         for every later ad row. This stops the same booking from being
         attributed to multiple ads when Meta reports the same conversion on
         several attribution dates (a 7-day window means the same $X often
         appears on ad rows for D, D+1, D+2 — without de-dupe each gets the
         same reservation).
      6. Persist one BookingMatch per successful pass.
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

    # Pre-load reservations grouped by (date, branch, is_website). Widen the
    # reservation date range by ±1 day so pass B's fallback window has data
    # at the edges of the requested period.
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.reservation_date >= date_from - timedelta(days=1),
            Reservation.reservation_date <= date_to + timedelta(days=1),
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

    # Flatten ads_rows into one (row, branch_key, kind, revenue, bookings)
    # entry per purchase kind, dropping rows with no resolvable branch. Sort
    # by descending revenue so larger bookings (rarer amounts) claim first.
    ads_skipped_no_branch = 0
    passes: list[tuple] = []
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
            passes.append((row, branch_key, kind, revenue, bookings_hint or 1))
    passes.sort(key=lambda p: -p[3])

    claimed_reservation_ids: set = set()
    matches_created = 0
    ads_no_candidates = 0
    now = datetime.now(timezone.utc)

    def _persist_match(row, branch_key, kind, revenue, bookings, match):
        nonlocal matches_created
        matched, result_label = match
        for r in matched:
            claimed_reservation_ids.add(r.id)
        db.add(_build_booking_match(
            row, revenue, bookings, kind, result_label, matched, branch_key, now,
        ))
        matches_created += 1

    def _available(reservations: list[Reservation]) -> list[Reservation]:
        return [r for r in reservations if r.id not in claimed_reservation_ids]

    # Pass A — same-day only. Highest-confidence pairings first.
    leftover: list[tuple] = []
    for row, branch_key, kind, revenue, bookings in passes:
        sameday = _available(res_by_key.get((row["date"], branch_key, kind), []))
        match = _match_country_tiers(sameday, row.get("country"), bookings, revenue)
        if match:
            _persist_match(row, branch_key, kind, revenue, bookings, match)
        else:
            leftover.append((row, branch_key, kind, revenue, bookings))

    # Pass B — ±1 day fallback for unmatched rows. Same-day reservations that
    # weren't claimed in pass A remain eligible here too.
    for row, branch_key, kind, revenue, bookings in leftover:
        window: list[Reservation] = []
        for delta in (-1, 0, 1):
            window += _available(
                res_by_key.get((row["date"] + timedelta(days=delta), branch_key, kind), [])
            )
        match = _match_country_tiers(window, row.get("country"), bookings, revenue)
        if match:
            _persist_match(row, branch_key, kind, revenue, bookings, match)
        elif not window:
            ads_no_candidates += 1

    db.commit()

    summary = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "ads_rows_processed": len(ads_rows),
        "reservations_loaded": len(reservations),
        "matches_created": matches_created,
        "reservations_claimed": len(claimed_reservation_ids),
        "ads_rows_no_branch": ads_skipped_no_branch,
        "ads_rows_no_candidates": ads_no_candidates,
    }
    logger.info("Booking match run complete: %s", summary)
    return summary
