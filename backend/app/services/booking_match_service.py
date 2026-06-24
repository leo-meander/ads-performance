"""Booking match service — matches PMS reservations to ads performance.

Matching methodology — per-reservation capacity assignment:
  The ad platforms attribute conversions FRACTIONALLY across touchpoints
  (Google reports 0.33, 6.33, ... conversions and a correspondingly partial
  conversion value). So the platform's reported revenue is NOT the sum of the
  real PMS grand_totals, and its conversion count is NOT a count of distinct
  bookings. The old approach — require a subset of exactly N reservations whose
  grand_totals reconstruct the ads revenue within ±2% — was therefore
  structurally lossy: one campaign-day row that failed to decompose dropped ALL
  its conversions, so 45 attributed conversions collapsed to a handful of
  matches.

  Instead we treat the platform's conversion count as a *booking budget* and
  hand each ads row that many of the most plausible real PMS reservations:
    - Candidate pool: same branch + same purchase kind (website vs offline),
      reservation_date within ±1 day of the ads date (short ad→booking lag).
    - We do NOT require the reservation revenue to reconstruct the ads revenue.
    - capacity = max(round(conversions), 1) for a kind that reported revenue.
    - Each reservation is assigned to at most one ads row (global, greedy).
    - Country-specific campaigns are processed before catch-all ("ALL") ones so
      they claim their same-country reservations first.
  matched_revenue on the resulting match is the real PMS grand_total of the
  assigned reservations (ground truth); ads_revenue keeps the platform figure
  for reference.

Two passes per ads row:
    website revenue  → reservations with source = Website/Booking Engine
    offline revenue  → reservations with other sources (OTA, Walk-in, ...)

Country is a preference, NOT a filter. The ads-side country is the campaign's
targeting geo (Meta's adset ISO-2 prefix / Google's campaign ISO-2 suffix) —
i.e. *who the ad was aimed at*, which is NOT the same as the guest's PMS
nationality. An "HK"-targeted campaign legitimately drives bookings from TW,
KR, US, ... guests. So we never exclude a same-date/branch/kind reservation
just because its nationality differs from the campaign geo. Country only ranks
candidates within a pool, best-confidence first (see _country_rank):
  0. same-country (campaign geo reconciled to guest ISO via
     normalize_country_to_iso, so Google "UK" lines up with reservation "GB"),
  1. country-unknown reservations (country_iso = NULL: junk PMS value
     "Unknown"/"00"/missing — common for OTA bookings),
  2. populated nationality that differs from the campaign geo (cross-country).
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


# Tier-1 (value-confirmed) tolerance. A match is "confirmed" when a subset of
# the candidate reservations sums to the ads revenue within ±5% — looser than
# amount_tolerance because confirmation tolerates the currency/fee/tax drift the
# old strict matcher choked on, while still being tight enough that a coincidental
# sum is unlikely. Bounded subset search keeps it cheap.
CONFIRM_TOLERANCE_PCT = 0.05
CONFIRM_MAX_SUBSET = 5      # largest reservation combo we try to sum-confirm
CONFIRM_POOL_CAP = 20       # only the top-ranked N candidates enter the combo search

CONFIDENCE_CONFIRMED = "confirmed"
CONFIDENCE_INFERRED = "inferred"


def confirm_tolerance(target: float) -> float:
    """Max allowed |sum(grand_total) - ads_revenue| to call a match confirmed."""
    return max(AMOUNT_TOLERANCE_FLOOR, abs(float(target)) * CONFIRM_TOLERANCE_PCT)

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


def _res_key(r: Reservation) -> str:
    """Stable identity for the global 'already assigned' set."""
    return r.reservation_number or str(r.id)


def _country_rank(ads_country: str | None, reservation: Reservation) -> int:
    """Confidence rank of a reservation for an ads row's targeting country.

    Lower is more confident; country never excludes, only orders:
      0 = same country (campaign geo reconciled to guest ISO, e.g. "UK"->"GB"),
      1 = reservation country unknown (country_iso = NULL),
      2 = populated nationality that differs from the campaign geo.
    """
    ads = _normalize_ads_iso(ads_country)
    if not reservation.country_iso:
        return 1
    if ads and reservation.country_iso.upper() == ads:
        return 0
    return 2


def _ranked_candidates(
    *,
    ads_date: date,
    country: str | None,
    branch_key: str,
    kinds: list[str],
    per_booking: float,
    res_by_key: dict[tuple, list["Reservation"]],
    used: set[str],
) -> list[Reservation]:
    """Candidate reservations for one ads row, best-first (no side effects).

    Pool = same branch, reservation source in one of `kinds`, reservation_date
    within ±1 day of the ads date, not already taken by another row. Ranked by:
    same-country first, then same-day before ±1, then closest single-booking
    value (|grand_total - per_booking|) as a soft tiebreak.

    `kinds` is usually a single purchase kind, but Google reports one combined
    PURCHASE total (website + offline upload lumped together; we don't split it),
    so a Google row is handed BOTH ["website", "offline"] pools — otherwise its
    offline/OTA-driven bookings could never match.
    """
    candidates: list[tuple[int, Reservation]] = []
    for delta in (0, -1, 1):
        for kind in kinds:
            bucket = res_by_key.get((ads_date + timedelta(days=delta), branch_key, kind), [])
            for r in bucket:
                if _res_key(r) in used:
                    continue
                candidates.append((0 if delta == 0 else 1, r))

    candidates.sort(
        key=lambda item: (
            _country_rank(country, item[1]),
            item[0],
            abs(float(item[1].grand_total or 0) - per_booking),
        )
    )
    return [r for _, r in candidates]


def _find_value_subset(
    candidates: list[Reservation], revenue: float, max_size: int
) -> list[Reservation] | None:
    """Smallest, best-ranked subset of `candidates` whose grand_totals sum to
    `revenue` within ±5% (confirm_tolerance), or None.

    Sizes are tried ascending (1 first): the fewest bookings that explain the
    campaign's revenue are the most likely to be the real distinct bookings, and
    a smaller confirmed size also corrects the platform's fractional-conversion
    overcount. `candidates` is pre-ranked, so within a size we return the first
    (best-ranked) combination found. Bounded by CONFIRM_POOL_CAP / max_size so
    the combinatorial search stays cheap.
    """
    tol = confirm_tolerance(revenue)
    pool = candidates[:CONFIRM_POOL_CAP]
    upper = min(max_size, CONFIRM_MAX_SUBSET, len(pool))
    if upper < 1:
        return None
    totals = [float(r.grand_total or 0) for r in pool]

    for size in range(1, upper + 1):
        found: list[int] | None = None

        def search(start: int, depth: int, acc: float, picks: list[int]) -> bool:
            nonlocal found
            if depth == size:
                if abs(acc - revenue) <= tol:
                    found = list(picks)
                    return True
                return False
            for i in range(start, len(pool)):
                # Prune: even taking the largest remaining can't be needed —
                # keep it simple and correct, just recurse with early exit.
                picks.append(i)
                if search(i + 1, depth + 1, acc + totals[i], picks):
                    return True
                picks.pop()
            return False

        search(0, 0, 0.0, [])
        if found is not None:
            return [pool[i] for i in found]
    return None


def _assign_row(
    *,
    ads_date: date,
    country: str | None,
    branch_key: str,
    kinds: list[str],
    revenue: float,
    capacity: int,
    res_by_key: dict[tuple, list["Reservation"]],
    used: set[str],
) -> tuple[list[Reservation], str]:
    """Match one ads row to real reservations; return (chosen, confidence).

    Two tiers:
      1. confirmed — a subset (size 1..capacity) of the ranked candidates sums
         to the ads revenue within ±5%. Value AND count agree, so we trust it
         (and the subset size corrects a fractional conversion overcount).
      2. inferred — no subset reconstructs the revenue, so fall back to capacity
         assignment: hand the row its top-`capacity` candidates by rank.
    Chosen reservations are marked in `used` so each booking is attributed once.
    Returns ([], "") when there are no candidates at all.
    """
    per_booking = (revenue / capacity) if capacity else revenue
    ranked = _ranked_candidates(
        ads_date=ads_date, country=country, branch_key=branch_key, kinds=kinds,
        per_booking=per_booking, res_by_key=res_by_key, used=used,
    )
    if not ranked:
        return [], ""

    subset = _find_value_subset(ranked, revenue, min(capacity, len(ranked)))
    if subset is not None:
        chosen, confidence = subset, CONFIDENCE_CONFIRMED
    else:
        chosen, confidence = ranked[:capacity], CONFIDENCE_INFERRED

    for r in chosen:
        used.add(_res_key(r))
    return chosen, confidence


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
    matched_revenue: float,
    confidence: str,
) -> BookingMatch:
    return BookingMatch(
        match_date=row["date"],
        ads_revenue=Decimal(str(revenue)),
        matched_revenue=Decimal(str(matched_revenue)),
        ads_bookings=bookings,
        confidence=confidence,
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
    branch_keys: list[str] | None = None,
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

    When branch_keys is given (canonical keys, e.g. ["Saigon"]), the run is
    scoped to those branches only: we delete and rebuild matches for just those
    branches (other branches' matches in the range are left untouched) and skip
    ads rows / reservations that normalise to a branch outside the scope.
    """
    scope_set = {b for b in (branch_keys or []) if b} or None

    del_q = db.query(BookingMatch).filter(
        BookingMatch.match_date >= date_from,
        BookingMatch.match_date <= date_to,
    )
    if scope_set:
        del_q = del_q.filter(BookingMatch.branch.in_(scope_set))
    del_q.delete(synchronize_session=False)
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
        if scope_set:
            bk = normalize_branch(r.account_name)
            if not bk or bk not in scope_set:
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
    reservations_in_scope = 0
    for r in reservations:
        branch_key = normalize_branch(r.branch)
        if not branch_key:
            continue
        if scope_set and branch_key not in scope_set:
            continue
        reservations_in_scope += 1
        bucket = "website" if _is_website_source(r.source) else "offline"
        res_by_key.setdefault((r.reservation_date, branch_key, bucket), []).append(r)

    matches_created = 0
    matches_confirmed = 0
    matches_by_branch: dict[str, int] = {}
    ads_skipped_no_branch = 0
    ads_no_candidates = 0
    now = datetime.now(timezone.utc)

    # Build the ads "slots": one per (ads row × purchase kind) that reported
    # revenue. capacity = how many real bookings the platform says it drove.
    slots: list[tuple[dict, str, str, float, int]] = []
    for row in ads_rows:
        branch_key = normalize_branch(row["account_name"])
        if not branch_key:
            ads_skipped_no_branch += 1
            continue
        for kind, revenue, conv in (
            ("website", row["revenue_website"], row["conversions_website"]),
            ("offline", row["revenue_offline"], row["conversions_offline"]),
        ):
            if revenue <= 0:
                continue
            capacity = max(int(conv or 0), 1)
            slots.append((row, branch_key, kind, revenue, capacity))

    # Process country-specific campaigns before catch-all ("ALL"/unparseable)
    # ones so they claim their same-country reservations first; bigger campaigns
    # (more revenue) before smaller within each group. `used` enforces that each
    # reservation is attributed to at most one ads row across the whole run.
    slots.sort(key=lambda s: (0 if _normalize_ads_iso(s[0].get("country")) else 1, -s[3]))

    used: set[str] = set()
    for row, branch_key, kind, revenue, capacity in slots:
        # Meta splits website (fb_pixel_purchase) vs offline (offline upload)
        # purchases, so each kind matches its own reservation pool. Google
        # reports one combined PURCHASE total we don't split, so a Google row
        # may match either a website or an OTA/offline reservation.
        match_kinds = ["website", "offline"] if row.get("platform") == "google" else [kind]
        chosen, confidence = _assign_row(
            ads_date=row["date"],
            country=row.get("country"),
            branch_key=branch_key,
            kinds=match_kinds,
            revenue=revenue,
            capacity=capacity,
            res_by_key=res_by_key,
            used=used,
        )
        if not chosen:
            ads_no_candidates += 1
            continue

        matched_revenue = sum(float(r.grand_total or 0) for r in chosen)
        result_label = "Matched (combo)" if len(chosen) > 1 else "Matched"
        db.add(_build_booking_match(
            row, revenue, len(chosen), kind, result_label, chosen,
            branch_key, now, matched_revenue, confidence,
        ))
        matches_created += 1
        matches_by_branch[branch_key] = matches_by_branch.get(branch_key, 0) + 1
        if confidence == CONFIDENCE_CONFIRMED:
            matches_confirmed += 1

    db.commit()

    summary = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "branches": sorted(scope_set) if scope_set else None,
        "ads_rows_processed": len(ads_rows),
        "reservations_loaded": reservations_in_scope,
        "matches_created": matches_created,
        "matches_confirmed": matches_confirmed,
        "matches_inferred": matches_created - matches_confirmed,
        "matches_by_branch": matches_by_branch,
        "ads_rows_no_branch": ads_skipped_no_branch,
        "ads_rows_no_candidates": ads_no_candidates,
    }
    logger.info("Booking match run complete: %s", summary)
    return summary
