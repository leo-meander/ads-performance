"""Reservation sync engine — pull from PMS API and upsert into DB."""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.services.pms_client import fetch_reservations

logger = logging.getLogger(__name__)

# Only sync hotel branches (exclude Bread restaurant)
HOTEL_BRANCHES = {
    "MEANDER Saigon", "Meander Saigon",
    "MEANDER Taipei", "Meander Taipei",
    "MEANDER 1948", "Meander 1948",
    "MEANDER Osaka", "Meander Osaka",
    "Oani", "OANI",
}


def _parse_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def _parse_numeric(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


import re

# Rate plan lives inside the room_type field — "Standard Twin (KOL_whatweieats)"
# → "KOL_whatweieats". We take the last parenthesised group so room types with
# nested descriptors still resolve correctly.
_RATE_PLAN_PAREN_RE = re.compile(r"\(([^()]+)\)\s*$")


def extract_rate_plan_from_room_type(room_type: str | None) -> str | None:
    if not room_type:
        return None
    match = _RATE_PLAN_PAREN_RE.search(room_type)
    if not match:
        return None
    val = match.group(1).strip()
    return val or None


def _extract_rate_plan(raw: dict) -> str | None:
    return extract_rate_plan_from_room_type(raw.get("room_type"))


def sync_reservations(
    db: Session,
    date_from: date,
    date_to: date,
) -> dict:
    """Pull reservations from PMS and upsert into DB.

    Returns:
        Summary dict with created, updated, skipped, errors counts.
    """
    raw_reservations = fetch_reservations(date_from, date_to)

    created = 0
    updated = 0
    skipped = 0
    errors = []

    for raw in raw_reservations:
        try:
            branch = (raw.get("branch") or "").strip()

            # Skip non-hotel branches
            if branch not in HOTEL_BRANCHES:
                skipped += 1
                continue

            res_number = raw.get("reservation_number")
            if not res_number:
                skipped += 1
                continue

            existing = db.query(Reservation).filter(
                Reservation.reservation_number == str(res_number),
            ).first()

            fields = {
                "reservation_date": _parse_date(raw.get("reservation_date")),
                "check_in_date": _parse_date(raw.get("check_in_date")),
                "check_out_date": _parse_date(raw.get("check_out_date")),
                "grand_total": _parse_numeric(raw.get("grand_total")),
                "country": raw.get("country") or None,
                "name": raw.get("name") or None,
                "email": raw.get("email") or None,
                "status": raw.get("status") or None,
                "source": raw.get("source") or None,
                "room_type": raw.get("room_type") or None,
                "rate_plan_name": _extract_rate_plan(raw),
                "branch": branch,
                "nights": _parse_int(raw.get("nights")),
                "adults": _parse_int(raw.get("adults")),
                "raw_data": raw,
            }

            if existing:
                for key, value in fields.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.now(timezone.utc)
                updated += 1
            else:
                reservation = Reservation(
                    reservation_number=str(res_number),
                    **fields,
                )
                db.add(reservation)
                db.flush()
                created += 1

        except Exception as e:
            db.rollback()
            errors.append(str(e))
            logger.warning("Failed to process reservation %s: %s", raw.get("reservation_number"), e)

    db.commit()

    summary = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_fetched": len(raw_reservations),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info("Reservation sync complete: %s", summary)
    return summary
