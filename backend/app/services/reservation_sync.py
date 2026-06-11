"""Reservation sync engine — pull from PMS API and upsert into DB."""

import logging
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.services.pms_client import fetch_reservations
from app.utils.country_normalize import normalize_country_to_iso

logger = logging.getLogger(__name__)

# Commit every N rows so a single sync doesn't hold a 1000-row write lock for
# longer than Supabase's statement_timeout (default 60s).
COMMIT_BATCH_SIZE = 100

# Postgres advisory lock key — anyone calling sync_reservations grabs this
# first, so two overlapping cron+UI runs serialise instead of fighting over
# row locks. Arbitrary 64-bit int, just needs to be unique per intent.
_RESERVATION_SYNC_LOCK_KEY = 7423180001

# Only sync hotel branches (exclude Bread restaurant). Matched case-insensitively
# (see _is_hotel_branch) so a PMS casing change like "MEANDER Oani" vs "Meander
# Oani" can't silently drop a whole branch — the bug that hid every Oani booking.
HOTEL_BRANCHES = {
    "meander saigon",
    "meander taipei",
    "meander 1948",
    "meander osaka",
    "meander oani", "oani",
}


def _is_hotel_branch(branch: str) -> bool:
    return branch.strip().lower() in HOTEL_BRANCHES


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


def _try_advisory_lock(db: Session) -> bool:
    """Acquire a non-blocking Postgres advisory lock for this sync run."""
    try:
        row = db.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": _RESERVATION_SYNC_LOCK_KEY},
        ).scalar()
        return bool(row)
    except Exception:
        # Non-Postgres backend (e.g. SQLite in tests) — skip locking.
        logger.debug("advisory lock unavailable, continuing without it")
        return True


def _release_advisory_lock(db: Session) -> None:
    try:
        db.execute(
            text("SELECT pg_advisory_unlock(:k)"),
            {"k": _RESERVATION_SYNC_LOCK_KEY},
        )
        db.commit()
    except Exception:
        pass


def sync_reservations(
    db: Session,
    date_from: date,
    date_to: date,
) -> dict:
    """Pull reservations from PMS and upsert into DB.

    Behaviour notes:
      - Holds a Postgres advisory lock so two overlapping syncs don't deadlock
        on row updates. If another run already holds it, we exit early with
        skipped_concurrent=True instead of waiting.
      - Commits every COMMIT_BATCH_SIZE rows so write locks release promptly
        and a single batch can't exceed Supabase's statement_timeout.
      - On a row-level OperationalError (e.g. statement_timeout), rolls back
        only the current batch and continues — the rest of the dataset still
        lands.

    Returns:
        Summary dict with created, updated, skipped, errors counts.
    """
    if not _try_advisory_lock(db):
        logger.warning("Reservation sync already running on another worker — skipping")
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "skipped_concurrent": True,
        }

    try:
        raw_reservations = fetch_reservations(date_from, date_to)

        created = 0
        updated = 0
        skipped = 0
        errors: list[str] = []
        in_batch = 0
        batches_committed = 0

        def _flush() -> None:
            nonlocal in_batch, batches_committed
            try:
                db.commit()
                batches_committed += 1
            except OperationalError as e:
                # Statement timeout / lock conflict on this batch — drop it,
                # log, keep going. We'll re-pick the same rows on next run.
                db.rollback()
                errors.append(f"batch rollback: {e}")
                logger.warning("Batch commit hit OperationalError, rolling back: %s", e)
            in_batch = 0

        for raw in raw_reservations:
            try:
                branch = (raw.get("branch") or "").strip()

                # Skip non-hotel branches
                if not _is_hotel_branch(branch):
                    skipped += 1
                    continue

                res_number = raw.get("reservation_number")
                if not res_number:
                    skipped += 1
                    continue

                existing = db.query(Reservation).filter(
                    Reservation.reservation_number == str(res_number),
                ).first()

                raw_country = raw.get("country") or None
                fields = {
                    "reservation_date": _parse_date(raw.get("reservation_date")),
                    "check_in_date": _parse_date(raw.get("check_in_date")),
                    "check_out_date": _parse_date(raw.get("check_out_date")),
                    "grand_total": _parse_numeric(raw.get("grand_total")),
                    "country": raw_country,
                    "country_iso": normalize_country_to_iso(raw_country),
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

                in_batch += 1
                if in_batch >= COMMIT_BATCH_SIZE:
                    _flush()

            except Exception as e:
                db.rollback()
                errors.append(str(e))
                logger.warning(
                    "Failed to process reservation %s: %s",
                    raw.get("reservation_number"), e,
                )
                in_batch = 0  # rollback already discarded the in-flight batch

        if in_batch > 0:
            _flush()

        summary = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_fetched": len(raw_reservations),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "batches_committed": batches_committed,
            "errors": errors,
        }
        logger.info("Reservation sync complete: %s", summary)
        return summary

    finally:
        _release_advisory_lock(db)
