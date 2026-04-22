"""Internal scheduled-task endpoints.

Zeabur cron jobs hit these endpoints instead of Celery Beat. Each endpoint is
protected by a shared secret (X-Internal-Secret header) and kicks off the work
in a background thread so the cron request returns immediately (< 225s Zeabur
ingress limit).

The underlying service functions are the same ones Celery tasks wrapped — we
just call them directly here.
"""

import logging
import secrets
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Path

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_secret(x_internal_secret: str | None) -> None:
    """Verify the shared secret sent by Zeabur cron."""
    expected = settings.INTERNAL_TASK_SECRET
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="INTERNAL_TASK_SECRET not configured on server",
        )
    if not x_internal_secret or not secrets.compare_digest(x_internal_secret, expected):
        raise HTTPException(status_code=401, detail="invalid internal secret")


def _api_response(data=None, error=None, status: int = 202):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _run_in_thread(target, label: str, **kwargs):
    """Fire-and-forget a task in a daemon thread with its own DB session."""
    def _wrapper():
        db = SessionLocal()
        try:
            logger.info("[internal-task:%s] starting", label)
            target(db=db, **kwargs)
            logger.info("[internal-task:%s] finished", label)
        except Exception:
            logger.exception("[internal-task:%s] failed", label)
        finally:
            db.close()

    t = threading.Thread(target=_wrapper, name=f"internal-{label}", daemon=True)
    t.start()


# ------------------------------------------------------------------ sync -----


def _do_sync_all_platforms(db):
    from app.services.sync_engine import sync_all_platforms
    sync_all_platforms(db)


def _do_daily_rule_cycle(db):
    from app.services.rule_engine import reenable_paused_ads
    from app.services.sync_engine import sync_all_platforms
    reenable_paused_ads(db)
    sync_all_platforms(db)


def _do_sync_reservations_and_match(db, days_back: int = 30):
    from app.services.booking_match_service import run_matching
    from app.services.reservation_sync import sync_reservations
    date_to = date.today()
    date_from = date_to - timedelta(days=days_back)
    sync_reservations(db, date_from, date_to)
    run_matching(db, date_from, date_to)


def _do_sync_material_urls(db):
    from app.services.material_url_sync import sync_material_urls
    sync_material_urls(db)


@router.post("/internal/tasks/sync-all-platforms", status_code=202)
def trigger_sync_all_platforms(
    background_tasks: BackgroundTasks,
    x_internal_secret: str | None = Header(default=None),
):
    """Sync all active Meta + Google ad accounts. Intended for 15-min cron."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_sync_all_platforms, "sync-all-platforms")
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/daily-rule-cycle", status_code=202)
def trigger_daily_rule_cycle(
    x_internal_secret: str | None = Header(default=None),
):
    """Daily: re-enable paused ads, sync all platforms, eval rules (eval runs inside sync)."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_daily_rule_cycle, "daily-rule-cycle")
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/sync-reservations-match", status_code=202)
def trigger_sync_reservations_match(
    x_internal_secret: str | None = Header(default=None),
    days_back: int = 30,
):
    """Daily: pull PMS reservations + re-run booking matching over a rolling window."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_sync_reservations_and_match, "sync-reservations-match", days_back=days_back)
    return _api_response(data={"status": "started", "days_back": days_back})


@router.post("/internal/tasks/sync-material-urls", status_code=202)
def trigger_sync_material_urls(
    x_internal_secret: str | None = Header(default=None),
):
    """Weekly: refresh Meta AdCreative preview URLs before CDN expiry."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_sync_material_urls, "sync-material-urls")
    return _api_response(data={"status": "started"})


# --------------------------------------------------------- cloudbeds probe ---


@router.post("/internal/cloudbeds-ping", status_code=200)
def cloudbeds_ping(
    branch: str = "Saigon",
    days_back: int = 7,
    x_internal_secret: str | None = Header(default=None),
):
    """Probe Cloudbeds API for a branch to confirm auth + response shape.

    Runs synchronously (not in a thread) so the caller sees the result. Tries
    each known auth flavour in sequence; the response records which auth
    succeeded and a sample reservation payload so we can design the real sync.
    """
    _require_secret(x_internal_secret)
    from app.services.cloudbeds_client import probe
    try:
        dt = date.today()
        df = dt - timedelta(days=days_back)
        result = probe(branch, df, dt)
        return _api_response(data=result, status=200)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("cloudbeds-ping failed")
        return _api_response(error=str(e), status=500)


# --------------------------------------------------- recommendation engines --

_VALID_CADENCES = {"daily", "weekly", "monthly", "seasonality"}


def _do_run_recommendations(db, engine_module, cadence: str, source: str):
    task_id = f"{source}:{uuid.uuid4().hex[:8]}"
    engine_module.run_recommendations(db, cadence=cadence, source_task_id=task_id)


def _do_expire_recommendations(db, engine_module):
    count = engine_module._expire_stale(db)
    db.commit()
    logger.info("Expired %d stale pending recommendations", count)


@router.post("/internal/tasks/google-recommendations/{cadence}", status_code=202)
def trigger_google_recommendations(
    cadence: str = Path(...),
    x_internal_secret: str | None = Header(default=None),
):
    """Google Ads recommendation engine. cadence: daily|weekly|monthly|seasonality."""
    _require_secret(x_internal_secret)
    if cadence not in _VALID_CADENCES:
        raise HTTPException(status_code=400, detail=f"cadence must be one of {sorted(_VALID_CADENCES)}")
    from app.services.google_recommendations import engine as rec_engine
    _run_in_thread(
        _do_run_recommendations,
        f"google-recs-{cadence}",
        engine_module=rec_engine,
        cadence=cadence,
        source=f"cron:{cadence}",
    )
    return _api_response(data={"status": "started", "cadence": cadence})


@router.post("/internal/tasks/google-recommendations-expire", status_code=202)
def trigger_google_recommendations_expire(
    x_internal_secret: str | None = Header(default=None),
):
    """Hourly: flip stale pending Google recommendations to expired."""
    _require_secret(x_internal_secret)
    from app.services.google_recommendations import engine as rec_engine
    _run_in_thread(
        _do_expire_recommendations,
        "google-recs-expire",
        engine_module=rec_engine,
    )
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/meta-recommendations/{cadence}", status_code=202)
def trigger_meta_recommendations(
    cadence: str = Path(...),
    x_internal_secret: str | None = Header(default=None),
):
    """Meta Ads recommendation engine. cadence: daily|weekly|monthly|seasonality."""
    _require_secret(x_internal_secret)
    if cadence not in _VALID_CADENCES:
        raise HTTPException(status_code=400, detail=f"cadence must be one of {sorted(_VALID_CADENCES)}")
    from app.services.meta_recommendations import engine as rec_engine
    _run_in_thread(
        _do_run_recommendations,
        f"meta-recs-{cadence}",
        engine_module=rec_engine,
        cadence=cadence,
        source=f"cron:{cadence}",
    )
    return _api_response(data={"status": "started", "cadence": cadence})


@router.post("/internal/tasks/meta-recommendations-expire", status_code=202)
def trigger_meta_recommendations_expire(
    x_internal_secret: str | None = Header(default=None),
):
    """Hourly: flip stale pending Meta recommendations to expired."""
    _require_secret(x_internal_secret)
    from app.services.meta_recommendations import engine as rec_engine
    _run_in_thread(
        _do_expire_recommendations,
        "meta-recs-expire",
        engine_module=rec_engine,
    )
    return _api_response(data={"status": "started"})
