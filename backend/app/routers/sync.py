import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.parse_utils import (
    parse_adset_metadata,
    parse_campaign_metadata,
    parse_country,
    parse_google_country,
)
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
        results = sync_all_platforms(db, platform_filter=platform)
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


class TikTokRegisterBody(BaseModel):
    advertiser_ids: list[str]
    branch: str | None = None  # canonical branch key from BRANCH_ACCOUNT_MAP


class TikTokBackfillBody(BaseModel):
    advertiser_id: str
    months_back: int = 24
    date_from: str | None = None  # YYYY-MM-DD — overrides months_back
    date_to: str | None = None    # YYYY-MM-DD — defaults to today


# Track TikTok backfill progress separately from the regular /sync/* state so
# both can run side-by-side without lock contention.
_tiktok_backfill_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "advertiser_id": None,
    "date_from": None,
    "date_to": None,
    "chunks_done": 0,
    "chunks_total": 0,
    "metrics_synced": 0,
    "errors": [],
    "error": None,
}
_tiktok_backfill_lock = threading.Lock()


def _run_tiktok_backfill(
    advertiser_id: str,
    months_back: int,
    date_from_iso: str | None,
    date_to_iso: str | None,
):
    """Walk a date range backwards in 30-day chunks for one TikTok advertiser.

    Re-uses sync_tiktok_metrics_window per chunk — entities (campaigns /
    adgroups / ads) are NOT re-fetched (assumed already in DB from a recent
    /sync/trigger call).
    """
    from datetime import date, timedelta
    from app.models.account import AdAccount
    from app.services.tiktok_sync_engine import sync_tiktok_metrics_window

    CHUNK_DAYS = 30

    db = SessionLocal()
    try:
        end = date.fromisoformat(date_to_iso) if date_to_iso else date.today()
        start = (
            date.fromisoformat(date_from_iso)
            if date_from_iso
            else end - timedelta(days=months_back * 30)
        )
        total_days = (end - start).days + 1
        chunks_total = (total_days + CHUNK_DAYS - 1) // CHUNK_DAYS

        with _tiktok_backfill_lock:
            _tiktok_backfill_state["running"] = True
            _tiktok_backfill_state["started_at"] = datetime.now(timezone.utc).isoformat()
            _tiktok_backfill_state["finished_at"] = None
            _tiktok_backfill_state["advertiser_id"] = advertiser_id
            _tiktok_backfill_state["date_from"] = start.isoformat()
            _tiktok_backfill_state["date_to"] = end.isoformat()
            _tiktok_backfill_state["chunks_done"] = 0
            _tiktok_backfill_state["chunks_total"] = chunks_total
            _tiktok_backfill_state["metrics_synced"] = 0
            _tiktok_backfill_state["errors"] = []
            _tiktok_backfill_state["error"] = None

        account = (
            db.query(AdAccount)
            .filter(AdAccount.platform == "tiktok", AdAccount.account_id == advertiser_id)
            .first()
        )
        if not account:
            with _tiktok_backfill_lock:
                _tiktok_backfill_state["error"] = (
                    f"TikTok advertiser {advertiser_id} not registered — "
                    f"call /sync/tiktok/register first"
                )
            return

        chunk_end = end
        while chunk_end >= start:
            chunk_start = max(chunk_end - timedelta(days=CHUNK_DAYS - 1), start)
            try:
                res = sync_tiktok_metrics_window(db, account, chunk_start, chunk_end)
                with _tiktok_backfill_lock:
                    _tiktok_backfill_state["chunks_done"] += 1
                    _tiktok_backfill_state["metrics_synced"] += res.get("metrics_synced", 0)
                    if res.get("errors"):
                        _tiktok_backfill_state["errors"].extend(
                            f"[{chunk_start}..{chunk_end}] {e}" for e in res["errors"]
                        )
                logger.info(
                    "[tiktok-backfill] %s [%s..%s] metrics=%d errs=%d",
                    advertiser_id, chunk_start, chunk_end,
                    res.get("metrics_synced", 0), len(res.get("errors", [])),
                )
            except Exception as e:
                logger.exception("[tiktok-backfill] chunk failed %s..%s", chunk_start, chunk_end)
                with _tiktok_backfill_lock:
                    _tiktok_backfill_state["errors"].append(
                        f"[{chunk_start}..{chunk_end}] EXCEPTION: {e}"
                    )
                    _tiktok_backfill_state["chunks_done"] += 1
            chunk_end = chunk_start - timedelta(days=1)
    except Exception as e:
        logger.exception("[tiktok-backfill] outer failure")
        with _tiktok_backfill_lock:
            _tiktok_backfill_state["error"] = str(e)
    finally:
        db.close()
        with _tiktok_backfill_lock:
            _tiktok_backfill_state["running"] = False
            _tiktok_backfill_state["finished_at"] = datetime.now(timezone.utc).isoformat()


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


@router.get("/sync/tiktok/diag")
def tiktok_diag():
    """Diagnostic: confirm the backend is reading TIKTOK_ACCESS_TOKEN and that
    its prefix/length match the value pasted on Zeabur. Token value itself is
    NEVER returned — only first 6 chars + length + a fingerprint hash."""
    import hashlib
    from app.config import settings
    token = settings.TIKTOK_ACCESS_TOKEN or ""
    return _api_response(data={
        "token_set": bool(token),
        "token_length": len(token),
        "token_prefix": token[:6] if token else None,
        "token_suffix": token[-4:] if len(token) > 10 else None,
        "token_fingerprint_sha256_8": hashlib.sha256(token.encode()).hexdigest()[:8] if token else None,
        "has_whitespace": token != token.strip() if token else False,
        "app_id_set": bool(settings.TIKTOK_APP_ID),
        "app_secret_set": bool(settings.TIKTOK_APP_SECRET),
    })


@router.get("/sync/tiktok/list-advertisers")
def tiktok_list_advertisers():
    """Discover advertiser_ids accessible to the configured access token.

    Requires TIKTOK_APP_ID + TIKTOK_APP_SECRET. If only TIKTOK_ACCESS_TOKEN is
    set, callers should POST advertiser_ids manually to /sync/tiktok/register.
    """
    try:
        from app.services.tiktok_client import TikTokAPIError, list_advertisers
        try:
            data = list_advertisers()
        except TikTokAPIError as e:
            return _api_response(error=str(e))
        return _api_response(data=data)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/sync/tiktok/backfill")
def tiktok_backfill(body: TikTokBackfillBody, background_tasks: BackgroundTasks):
    """Walk a TikTok advertiser's metrics history in 30-day chunks.

    Default: last 24 months. Pass `date_from` / `date_to` (YYYY-MM-DD) to
    override. Entities (campaigns/adgroups/ads) are NOT re-synced — call
    /sync/trigger?platform=tiktok first if you suspect missing entities.

    TikTok's report API typically retains ~13 months of detailed daily data;
    older requests just return empty rows (counted as 0 synced, no error).
    Runs async; poll /sync/tiktok/backfill/status.
    """
    with _tiktok_backfill_lock:
        if _tiktok_backfill_state["running"]:
            return _api_response(
                error="TikTok backfill already running",
                data={"started_at": _tiktok_backfill_state["started_at"]},
            )
    background_tasks.add_task(
        _run_tiktok_backfill,
        body.advertiser_id, body.months_back, body.date_from, body.date_to,
    )
    return _api_response(data={
        "message": "TikTok backfill started in background",
        "advertiser_id": body.advertiser_id,
        "months_back": body.months_back,
        "poll_url": "/api/sync/tiktok/backfill/status",
    })


@router.get("/sync/tiktok/backfill/status")
def tiktok_backfill_status():
    with _tiktok_backfill_lock:
        return _api_response(data=dict(_tiktok_backfill_state))


@router.post("/sync/tiktok/register")
def tiktok_register_advertisers(body: TikTokRegisterBody, db: Session = Depends(get_db)):
    """Upsert TikTok advertisers as ad_accounts rows.

    Pulls name + currency from TikTok's /advertiser/info/ endpoint. When
    `branch` is provided, the saved account_name is prefixed with the
    branch's canonical pattern (e.g. "Meander Saigon TikTok — <name>") so
    BRANCH_ACCOUNT_MAP substring matching picks it up in dashboards.
    """
    try:
        from app.services.tiktok_sync_engine import register_tiktok_advertisers
        summary = register_tiktok_advertisers(
            db, body.advertiser_ids, branch=body.branch,
        )
        if summary.get("errors"):
            return _api_response(data=summary, error="; ".join(summary["errors"]))
        return _api_response(data=summary)
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


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
                # Country lives on Campaign for Google (PMax has no AdSet to
                # carry it). Re-derive whenever names or the parser change.
                if c.platform == "google":
                    c.country = parse_google_country(c.name or "")
                reparsed += 1
                if parsed["ta"] == "Unknown":
                    unknown_ta += 1
                if parsed["funnel_stage"] == "Unknown":
                    unknown_funnel += 1

        # Track per-platform country distribution for diagnostics.
        country_dist: dict[str, dict[str, int]] = {}
        # Sample names of unparseable rows so the user can spot bad naming.
        unknown_samples: dict[str, list[str]] = {}

        if body.scope in ("all", "adsets"):
            q = db.query(AdSet)
            if body.account_id:
                q = q.filter(AdSet.account_id == body.account_id)
            adsets = q.all()

            # Cache campaign names for Google lookups — adgroup names don't carry country.
            campaign_names = {c.id: c.name for c in db.query(Campaign).all()}

            for a in adsets:
                if a.platform == "google":
                    # Google adgroups inherit country from parent campaign's
                    # trailing token, NOT the Meta-style first-segment prefix.
                    source_name = campaign_names.get(a.campaign_id, "")
                    country = parse_google_country(source_name)
                else:
                    source_name = a.name
                    country = parse_adset_metadata(a.name)["country"]
                a.country = country
                reparsed += 1
                if country == "Unknown":
                    unknown_country += 1
                    samples = unknown_samples.setdefault(a.platform, [])
                    if len(samples) < 5 and source_name:
                        samples.append(source_name)
                plat_dist = country_dist.setdefault(a.platform, {})
                plat_dist[country] = plat_dist.get(country, 0) + 1

        db.commit()
        logger.info("Re-parse complete: %d items, %d unknown TA, %d unknown country", reparsed, unknown_ta, unknown_country)

        return _api_response(data={
            "reparsed": reparsed,
            "unknown_ta": unknown_ta,
            "unknown_funnel_stage": unknown_funnel,
            "unknown_country": unknown_country,
            "country_distribution": country_dist,
            "unknown_samples": unknown_samples,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
