import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.parse_utils import parse_adset_metadata, parse_campaign_metadata, parse_country
from app.services.sync_engine import sync_all_platforms

logger = logging.getLogger(__name__)
router = APIRouter()

# Track sync state so client can poll
_sync_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "platform": None,
    "results": None,
    "error": None,
}
_sync_lock = threading.Lock()


def _run_sync_background(platform: str | None):
    """Run sync_all_platforms in a separate DB session (background thread)."""
    with _sync_lock:
        _sync_state["running"] = True
        _sync_state["started_at"] = datetime.now(timezone.utc).isoformat()
        _sync_state["finished_at"] = None
        _sync_state["platform"] = platform
        _sync_state["results"] = None
        _sync_state["error"] = None

    db = SessionLocal()
    try:
        results = sync_all_platforms(db)
        if platform:
            results = [r for r in results if r.get("platform") == platform]
        logger.info("Background sync completed: %d accounts processed", len(results))
        with _sync_lock:
            _sync_state["results"] = {"accounts_processed": len(results), "results": results}
    except Exception as exc:  # pragma: no cover — logged for ops
        logger.exception("Background sync failed: %s", exc)
        with _sync_lock:
            _sync_state["error"] = str(exc)
    finally:
        db.close()
        with _sync_lock:
            _sync_state["running"] = False
            _sync_state["finished_at"] = datetime.now(timezone.utc).isoformat()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ReparseBody(BaseModel):
    scope: str = "all"  # all | campaigns | adsets
    account_id: str | None = None


@router.post("/sync/trigger")
def trigger_sync(background_tasks: BackgroundTasks, platform: str | None = None):
    """Manually trigger a data sync for one or all platforms.

    Runs in a background thread so the HTTP request returns immediately
    (previously synchronous execution hit Zeabur's 225s ingress timeout).
    Client should poll GET /sync/status for progress.
    """
    with _sync_lock:
        if _sync_state["running"]:
            return _api_response(
                error="Sync already running",
                data={"started_at": _sync_state["started_at"]},
            )

    background_tasks.add_task(_run_sync_background, platform)
    return _api_response(data={
        "message": "Sync started in background",
        "platform": platform or "all",
        "poll_url": "/api/sync/status",
    })


@router.get("/sync/status")
def sync_status():
    """Return the state of the most recent /sync/trigger call."""
    with _sync_lock:
        return _api_response(data=dict(_sync_state))


@router.post("/sync/reparse")
def reparse_names(body: ReparseBody = ReparseBody(), db: Session = Depends(get_db)):
    """Re-parse all campaign/adset names without full sync."""
    try:
        reparsed = 0
        unknown_ta = 0
        unknown_funnel = 0
        unknown_country = 0

        if body.scope in ("all", "campaigns"):
            q = db.query(Campaign)
            if body.account_id:
                q = q.filter(Campaign.account_id == body.account_id)
            campaigns = q.all()

            for c in campaigns:
                parsed = parse_campaign_metadata(c.name)
                c.ta = parsed["ta"]
                c.funnel_stage = parsed["funnel_stage"]
                reparsed += 1
                if parsed["ta"] == "Unknown":
                    unknown_ta += 1
                if parsed["funnel_stage"] == "Unknown":
                    unknown_funnel += 1

        if body.scope in ("all", "adsets"):
            q = db.query(AdSet)
            if body.account_id:
                q = q.filter(AdSet.account_id == body.account_id)
            adsets = q.all()

            # Cache campaign names for Google lookups — adgroup names don't carry country.
            campaign_names = {c.id: c.name for c in db.query(Campaign).all()}

            for a in adsets:
                if a.platform == "google":
                    country = parse_country(campaign_names.get(a.campaign_id, ""))
                else:
                    country = parse_adset_metadata(a.name)["country"]
                a.country = country
                reparsed += 1
                if country == "Unknown":
                    unknown_country += 1

        db.commit()
        logger.info("Re-parse complete: %d items, %d unknown TA, %d unknown country", reparsed, unknown_ta, unknown_country)

        return _api_response(data={
            "reparsed": reparsed,
            "unknown_ta": unknown_ta,
            "unknown_funnel_stage": unknown_funnel,
            "unknown_country": unknown_country,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
