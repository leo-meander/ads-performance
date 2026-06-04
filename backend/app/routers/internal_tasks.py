"""Internal scheduled-task endpoints.

GitHub Actions (.github/workflows/scheduled-tasks.yml) hits these endpoints
on cron instead of Celery Beat. Each endpoint is protected by a shared secret
(X-Internal-Secret header) and kicks off the work in a background thread so
the request returns immediately (< 225s Zeabur ingress limit).

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
    """Verify the shared secret sent by the GitHub Actions cron workflow."""
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


# Meta Marketing API insights paginate well up to ~90-day windows but get slow
# and can hit per-call limits past that. 30 days is the safe chunk size.
_BACKFILL_CHUNK_DAYS = 30


def _do_sync_backfill(
    db,
    months_back: int = 12,
    date_from_iso: str | None = None,
    date_to_iso: str | None = None,
):
    """Re-pull historical metrics in chunked windows for every active account.

    Step 1: run a regular sync once so entity tables (campaigns/ad sets/ads)
    are current — historical metric upserts skip rows whose entity isn't in DB.

    Step 2: walk the requested range backwards in 30-day chunks and call the
    metrics-only window function for each chunk × each active account.
    """
    from app.models.account import AdAccount
    from app.services.sync_engine import (
        sync_all_platforms,
        sync_meta_metrics_window,
    )
    from app.services.google_sync_engine import sync_google_metrics_window
    from app.services.tiktok_sync_engine import sync_tiktok_metrics_window

    # Resolve range
    if date_to_iso:
        end = date.fromisoformat(date_to_iso)
    else:
        end = date.today()
    if date_from_iso:
        start = date.fromisoformat(date_from_iso)
    else:
        start = end - timedelta(days=months_back * 30)

    logger.info("[backfill] step 1: refreshing entities via sync_all_platforms")
    sync_all_platforms(db)

    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    logger.info(
        "[backfill] step 2: chunked metrics pull from %s to %s for %d accounts",
        start, end, len(accounts),
    )

    chunk_end = end
    chunk_count = 0
    while chunk_end >= start:
        chunk_start = max(chunk_end - timedelta(days=_BACKFILL_CHUNK_DAYS - 1), start)
        chunk_count += 1
        for account in accounts:
            try:
                if account.platform == "meta":
                    res = sync_meta_metrics_window(db, account, chunk_start, chunk_end)
                elif account.platform == "google":
                    res = sync_google_metrics_window(db, account, chunk_start, chunk_end)
                elif account.platform == "tiktok":
                    res = sync_tiktok_metrics_window(db, account, chunk_start, chunk_end)
                else:
                    continue
                logger.info(
                    "[backfill] %s %s [%s..%s] metrics=%d country=%d errs=%d",
                    account.platform, account.account_name, chunk_start, chunk_end,
                    res["metrics_synced"], res["ad_country_rows"], len(res["errors"]),
                )
            except Exception:
                logger.exception(
                    "[backfill] chunk failed account=%s window=%s..%s",
                    account.account_name, chunk_start, chunk_end,
                )
        chunk_end = chunk_start - timedelta(days=1)

    logger.info("[backfill] complete: %d chunks processed", chunk_count)


def _do_daily_rule_cycle(db):
    from app.services.rule_engine import reenable_paused_ads
    from app.services.sync_engine import sync_all_platforms
    reenable_paused_ads(db)
    sync_all_platforms(db)


def _do_run_daily_tactics(db):
    """Once-per-day tactics cycle. Schedule at 17:00 UTC.

    17:00 UTC = 00:00 VN / 01:00 TW / 02:00 JP — start of a new local day
    across all MEANDER branches. Tactics evaluate once here; sync_all_platforms
    on its own (03/13/23 UTC) skips tactic-linked rules to prevent budget
    multiplier compounding across runs.
    """
    from app.services.rule_engine import evaluate_all_rules, reenable_paused_ads
    from app.services.sync_engine import sync_all_platforms
    from app.services.tactic_engine import revert_tactic_actions, stamp_last_run

    # 1) Revert yesterday's tactic mutations (SURF surges, Pause-Today resumes).
    #    Runs BEFORE the legacy reenable so tactic-paused ads come back via the
    #    tactic_revert log entry; the legacy fn then no-ops because status is
    #    already ACTIVE.
    revert_summary = revert_tactic_actions(db)
    logger.info("[run-daily-tactics] revert_summary=%s", revert_summary)

    # 2) Legacy reenable for standalone /rules UI pauses (untouched).
    reenable_paused_ads(db)

    # 3) Sync platforms to get fresh metrics. sync_all_platforms evaluates
    #    non-tactic rules at its tail (tactics_filter='no_tactics'); we'll
    #    handle tactic rules explicitly in step 4.
    sync_all_platforms(db)

    # 4) Evaluate tactic-linked rules exactly once per day.
    tactic_results = evaluate_all_rules(db, tactics_filter="tactic_only")
    total_tactic_actions = sum(r.get("actions_taken", 0) for r in tactic_results)
    logger.info(
        "[run-daily-tactics] tactic rules evaluated: %d rules, %d actions",
        len(tactic_results), total_tactic_actions,
    )

    # 5) Stamp last_run_at on every active tactic for the UI's "Last run" column.
    stamped = stamp_last_run(db)
    logger.info("[run-daily-tactics] stamped last_run_at on %d tactics", stamped)


def _do_sync_reservations_and_match(db, days_back: int = 30):
    from app.services.booking_match_service import run_matching
    from app.services.reservation_sync import sync_reservations
    date_to = date.today()
    date_from = date_to - timedelta(days=days_back)
    sync_reservations(db, date_from, date_to)
    run_matching(db, date_from, date_to)


def _do_sync_material_urls(db, since_days=None):
    from app.services.material_url_sync import sync_material_urls
    sync_material_urls(db, since_days=since_days)


def _do_assign_from_copy(db):
    """Fill missing angle + keypoints on combos by reading the ad copy text."""
    from app.services.assign_from_copy_service import assign_from_copy
    return assign_from_copy(db)


def _do_sync_combo_metrics(db, days_back: int | None = None):
    """Pull ad-level Meta metrics into ad_combos (Creative Library performance).

    `days_back=None` syncs lifetime metrics (matches Meta's "Maximum" view).
    Metrics are overwritten per combo, so re-runs and overlapping windows never
    double-count.
    """
    from app.services.combo_metrics_sync import sync_all_combo_metrics
    sync_all_combo_metrics(db, days_back=days_back)


def _do_vision_tag_materials(db, limit: int = 25):
    """Score the next batch of un-tagged image materials with Claude vision.

    Inline (not background) so the cron response carries the per-call counts;
    work is bounded (limit × ~10s per material call ≈ 4 min on the high end).
    """
    from app.services.creative_vision_tagger import tag_pending_materials
    summary = tag_pending_materials(db, limit=limit)
    logger.info(
        "[vision-tag] scanned=%d tagged=%d errors=%d skipped=%d",
        summary["scanned"], summary["tagged"], summary["errors"], summary["skipped"],
    )
    return summary


def _do_figma_job_poll(db, limit: int = 25):
    """Walk PENDING/RUNNING figma_jobs, export the master frame, mark COMPLETED.

    Cheap path — one Figma /images call per job. Templates that have moved or
    been deleted in Figma surface as FAILED with the API error message.
    """
    from app.services.figma_service import poll_pending_jobs
    counts = poll_pending_jobs(db, limit=limit)
    logger.info(
        "[figma-job-poll] polled=%d completed=%d failed=%d",
        counts["polled"], counts["completed"], counts["failed"],
    )
    return counts


@router.post("/internal/tasks/sync-all-platforms", status_code=202)
def trigger_sync_all_platforms(
    background_tasks: BackgroundTasks,
    x_internal_secret: str | None = Header(default=None),
):
    """Sync all active Meta + Google + TikTok ad accounts. Intended for 15-min cron."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_sync_all_platforms, "sync-all-platforms")
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/sync-backfill", status_code=202)
def trigger_sync_backfill(
    x_internal_secret: str | None = Header(default=None),
    months_back: int = 12,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """One-shot historical backfill of metrics + ad×country for every active
    Meta + Google + TikTok account. Walks backwards in 30-day chunks.

    Defaults to last 12 months. Pass `date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
    to override. Runs async in a thread; expect 5-30 min depending on account
    count and chunk size.
    """
    _require_secret(x_internal_secret)
    if months_back <= 0 or months_back > 37:
        raise HTTPException(status_code=400, detail="months_back must be 1..37 (Meta API max)")
    _run_in_thread(
        _do_sync_backfill,
        "sync-backfill",
        months_back=months_back,
        date_from_iso=date_from,
        date_to_iso=date_to,
    )
    return _api_response(data={
        "status": "started",
        "months_back": months_back,
        "date_from": date_from,
        "date_to": date_to,
        "chunk_days": _BACKFILL_CHUNK_DAYS,
    })


@router.post("/internal/tasks/daily-rule-cycle", status_code=202)
def trigger_daily_rule_cycle(
    x_internal_secret: str | None = Header(default=None),
):
    """Daily: re-enable paused ads, sync all platforms, eval rules (eval runs inside sync)."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_daily_rule_cycle, "daily-rule-cycle")
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/run-daily-tactics", status_code=202)
def trigger_run_daily_tactics(
    x_internal_secret: str | None = Header(default=None),
):
    """Once-per-day tactics cycle. Schedule at 17:00 UTC.

    Pipeline: revert yesterday's REVERT_NEXT_DAY mutations → legacy reenable
    (standalone pause_ad rules) → sync all platforms (rule eval runs in tail)
    → stamp tactic.last_run_at. Idempotent across re-runs in the same day —
    revert dedupes via existing tactic_revert log lookups, evaluate dedupes
    via condition checks against fresh metrics.
    """
    _require_secret(x_internal_secret)
    _run_in_thread(_do_run_daily_tactics, "run-daily-tactics")
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/migrate-rules-to-custom-tactics", status_code=200)
def trigger_migrate_rules_to_custom_tactics(
    x_internal_secret: str | None = Header(default=None),
):
    """One-shot data migration: wrap each standalone AutomationRule in a Custom
    tactic. Run once after deploying the tactics-unified eval pipeline so
    legacy /rules-UI rules continue to fire via the daily tactics cron.

    Idempotent — rules already linked to a tactic are skipped. Safe to re-run.
    Synchronous (returns counts inline) because the operation is bounded
    (one INSERT + one UPDATE per legacy rule, typically <100 rows).
    """
    _require_secret(x_internal_secret)
    from app.services.tactic_service import migrate_standalone_rules_to_custom_tactics
    db = SessionLocal()
    try:
        summary = migrate_standalone_rules_to_custom_tactics(db)
    finally:
        db.close()
    return _api_response(data={"status": "ok", **summary})


@router.post("/internal/tasks/sync-reservations-match", status_code=202)
def trigger_sync_reservations_match(
    x_internal_secret: str | None = Header(default=None),
    days_back: int = 30,
):
    """Daily: pull PMS reservations + re-run booking matching over a rolling window."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_sync_reservations_and_match, "sync-reservations-match", days_back=days_back)
    return _api_response(data={"status": "started", "days_back": days_back})


@router.post("/internal/tasks/assign-from-copy", status_code=202)
def trigger_assign_from_copy(
    x_internal_secret: str | None = Header(default=None),
):
    """Fill missing angle + keypoints on combos by reading the ad copy text.

    Picks angle from existing angles only (never creates a new one). Reuses
    branch keypoints when the copy clearly matches; creates new branch
    keypoints for points the copy raises that aren't already in the library.
    Idempotent — only touches combos where angle_id IS NULL OR keypoint_ids
    IS NULL, and never overwrites a value that's already filled."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_assign_from_copy, "assign-from-copy")
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/sync-material-urls", status_code=202)
def trigger_sync_material_urls(
    x_internal_secret: str | None = Header(default=None),
    since_days: int | None = None,
):
    """Weekly: refresh Meta AdCreative preview URLs before CDN expiry.

    Pass ?since_days=60 to scope a backfill to ads created in the last N days.
    """
    _require_secret(x_internal_secret)
    _run_in_thread(_do_sync_material_urls, "sync-material-urls", since_days=since_days)
    return _api_response(data={"status": "started"})


@router.post("/internal/tasks/sync-combo-metrics", status_code=202)
def trigger_sync_combo_metrics(
    x_internal_secret: str | None = Header(default=None),
    days_back: int | None = None,
):
    """Daily: pull ad-level Meta metrics into ad_combos so the Creative Library
    shows live spend / ROAS / CPP / CTR / hook rate per combo.

    Default is LIFETIME (Meta `maximum` preset) so the numbers match Meta Ads
    Manager's "Maximum" view. Pass `days_back=N` to restrict to a rolling
    last-N-days window instead. Metrics are overwritten on each combo, so
    re-running — or running an overlapping window — never double-counts. Runs
    async in a thread (one paginated Meta call per account; expect a few
    minutes for all branches)."""
    _require_secret(x_internal_secret)
    if days_back is not None and (days_back <= 0 or days_back > 365):
        raise HTTPException(status_code=400, detail="days_back must be 1..365")
    _run_in_thread(_do_sync_combo_metrics, "sync-combo-metrics", days_back=days_back)
    return _api_response(
        data={"status": "started", "days_back": days_back or "lifetime"}
    )


@router.post("/internal/tasks/vision-tag-materials", status_code=200)
def trigger_vision_tag_materials(
    x_internal_secret: str | None = Header(default=None),
    limit: int = 25,
):
    """Every ~10 min: tag the next batch of un-scored image materials with
    Claude vision. Inline so cron sees per-call counts. `limit` capped to 50
    to stay under the 225s ingress budget (~10s per vision call)."""
    _require_secret(x_internal_secret)
    if limit <= 0 or limit > 50:
        raise HTTPException(status_code=400, detail="limit must be 1..50")
    db = SessionLocal()
    try:
        summary = _do_vision_tag_materials(db, limit=limit)
    finally:
        db.close()
    return _api_response(data={"status": "ok", **{k: v for k, v in summary.items() if k != "results"}})


@router.post("/internal/tasks/figma-job-poll", status_code=200)
def trigger_figma_job_poll(
    x_internal_secret: str | None = Header(default=None),
    limit: int = 25,
):
    """Every ~2 min: complete PENDING figma_jobs by exporting their master
    frame as PNG. Inline (work is bounded to limit × 1 HTTP call)."""
    _require_secret(x_internal_secret)
    if limit <= 0 or limit > 50:
        raise HTTPException(status_code=400, detail="limit must be 1..50")
    db = SessionLocal()
    try:
        counts = _do_figma_job_poll(db, limit=limit)
    finally:
        db.close()
    return _api_response(data={"status": "ok", **counts})


# ------------------------------------------------------------ SURF Intraday --


def _do_surf_intraday_poll(db):
    """Poll every active SURF intraday tactic for threshold crossings.

    Inline (synchronous) — the summary is returned to the cron so GitHub
    Actions logs surface "polled N campaigns, took N actions". Work is bounded
    by (active tactics × campaigns per tactic × 1 Meta API call each).
    Typical run: ≤ 5 tactics × 3 campaigns × ~2s = ~30s, well under 225s.
    """
    from app.services.surf_intraday import poll_active_surfs
    return poll_active_surfs(db)


def _do_surf_end_of_day_revert(db):
    """Restore origin_budget on every SurfRun whose local-tz day has rolled.

    Self-filters by branch timezone — Saigon reverts at 17:00 UTC, Osaka at
    15:00 UTC. Cron fires hourly; this function is a no-op when no runs are
    due, so it's cheap to over-fire.
    """
    from app.services.surf_intraday import revert_end_of_day_runs
    return revert_end_of_day_runs(db)


@router.post("/internal/tasks/surf-intraday-poll", status_code=200)
def trigger_surf_intraday_poll(
    x_internal_secret: str | None = Header(default=None),
):
    """Every 15 min: iterate active SURF intraday tactics, fetch Meta intraday
    metrics, apply tier-band budget boost when spend crosses a threshold.

    Inline so the response carries the summary {tactics, polled, actions,
    errors}. If you scale this above ~50 active campaigns, switch to
    _run_in_thread to stay under the 225s ingress budget.
    """
    _require_secret(x_internal_secret)
    db = SessionLocal()
    try:
        summary = _do_surf_intraday_poll(db)
    finally:
        db.close()
    return _api_response(data={"status": "ok", **summary})


@router.post("/internal/tasks/surf-end-of-day-revert", status_code=200)
def trigger_surf_end_of_day_revert(
    x_internal_secret: str | None = Header(default=None),
):
    """Hourly: revert any SurfRun whose local-tz day has ended.

    Inline. Each due run = 1 Meta budget write + DB updates. With 6 MEANDER
    branches, expect ≤ 6 reverts per cron invocation (one per branch as its
    local midnight passes), so well under the ingress budget.
    """
    _require_secret(x_internal_secret)
    db = SessionLocal()
    try:
        summary = _do_surf_end_of_day_revert(db)
    finally:
        db.close()
    return _api_response(data={"status": "ok", **summary})


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


# ------------------------------------------------------ landing pages / clarity

def _do_clarity_sync(db, target_date_iso: str | None = None):
    from app.services.clarity_sync import run_clarity_sync
    target_date = None
    if target_date_iso:
        target_date = date.fromisoformat(target_date_iso)
    run_clarity_sync(db, target_date=target_date)


def _do_landing_page_import(db):
    from app.services.landing_page_importer import import_from_ads
    import_from_ads(db)


@router.post("/internal/tasks/clarity-sync", status_code=202)
def trigger_clarity_sync(
    x_internal_secret: str | None = Header(default=None),
    target_date: str | None = None,
):
    """Daily: pull Microsoft Clarity Data Export API → landing_page_clarity_snapshots.

    Clarity only keeps 3 days of live data so we must run at least daily to
    avoid gaps. Recommended cron: 01:00 UTC every day (writes to yesterday).
    `target_date` (YYYY-MM-DD) overrides the default.
    """
    _require_secret(x_internal_secret)
    _run_in_thread(_do_clarity_sync, "clarity-sync", target_date_iso=target_date)
    return _api_response(data={"status": "started", "target_date": target_date})


@router.post("/internal/tasks/landing-page-import", status_code=202)
def trigger_landing_page_import(
    x_internal_secret: str | None = Header(default=None),
):
    """Periodic: scan all existing ads for destination URLs and upsert
    `external` landing pages + ad-link rows. Safe to run hourly (idempotent)."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_landing_page_import, "landing-page-import")
    return _api_response(data={"status": "started"})


# --------------------------------------------------------------- GA4 sync ---


def _do_ga4_sync(db, days_back: int = 2, branch_filter: str | None = None):
    from app.services.ga4_sync import run_ga4_sync
    run_ga4_sync(db, days_back=days_back, branch_filter=branch_filter)


@router.post("/internal/tasks/ga4-sync", status_code=202)
def trigger_ga4_sync(
    x_internal_secret: str | None = Header(default=None),
    days_back: int = 2,
    branch_filter: str | None = None,
):
    """Daily: pull GA4 traffic + Web Vitals for every branch with ga4_property_id set.

    GA4 has ~24-48h data finalization delay — run cron at 04:00 UTC to capture
    a fully-final day. `days_back=2` re-syncs yesterday + 2 days ago to
    self-heal missed runs. `branch_filter` (AdAccount.id) restricts to a
    single branch for ad-hoc testing.
    """
    _require_secret(x_internal_secret)
    _run_in_thread(_do_ga4_sync, "ga4-sync", days_back=days_back, branch_filter=branch_filter)
    return _api_response(data={"status": "started", "days_back": days_back, "branch_filter": branch_filter})


# --------------------------------------------------- Google country backfill --


def _do_backfill_google_country(db):
    """Re-parse country (last 2 chars of campaign name) for every Google campaign
    and its ad groups. Run once after migration 024 so the Country Dashboard
    has data without waiting for the next regular sync."""
    from app.models.ad_set import AdSet
    from app.models.campaign import Campaign
    from app.services.parse_utils import parse_google_country

    google_campaigns = db.query(Campaign).filter(Campaign.platform == "google").all()
    campaigns_updated = 0
    for c in google_campaigns:
        parsed = parse_google_country(c.name or "")
        if c.country != parsed:
            c.country = parsed
            campaigns_updated += 1

    db.flush()

    # Mirror parsed country onto Search ad groups (AdSet) so Meta-style adset
    # queries still work for Google Search.
    google_adsets = (
        db.query(AdSet)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .filter(Campaign.platform == "google")
        .all()
    )
    adsets_updated = 0
    for a in google_adsets:
        parent = next((c for c in google_campaigns if c.id == a.campaign_id), None)
        if not parent:
            continue
        parsed = parse_google_country(parent.name or "")
        if a.country != parsed:
            a.country = parsed
            adsets_updated += 1

    db.commit()
    logger.info(
        "[backfill-google-country] %d campaigns updated, %d adsets updated",
        campaigns_updated, adsets_updated,
    )


@router.post("/internal/tasks/backfill-google-country", status_code=202)
def trigger_backfill_google_country(
    x_internal_secret: str | None = Header(default=None),
):
    """One-shot: re-parse country for every Google campaign + Search ad group
    using the last-2-chars-of-campaign-name rule. Safe to run multiple times."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_backfill_google_country, "backfill-google-country")
    return _api_response(data={"status": "started"})


# --------------------------------------------------- Combo country backfill --


def _do_backfill_combo_country(db):
    """Populate AdCombo.country from the synced Ad -> AdSet link.

    Creative-library combos are keyed by Meta ad name but never carried a
    country: creative_sync only fetched campaign/ad names, not adset names,
    and country is parsed from the adset-name prefix. AdSet.country is already
    parsed at sync time and Ad.name == AdCombo.ad_name, so we map
    (branch, ad_name) -> AdSet.country and fill combos that lack one.
    Safe to run repeatedly — only touches combos with no usable country."""
    from app.models.ad import Ad
    from app.models.ad_combo import AdCombo
    from app.models.ad_set import AdSet

    rows = (
        db.query(Ad.account_id, Ad.name, AdSet.country)
        .join(AdSet, AdSet.id == Ad.ad_set_id)
        .filter(AdSet.country.isnot(None))
        .all()
    )
    country_by_ad: dict[tuple, str] = {}
    for account_id, name, country in rows:
        if name and country and country != "Unknown":
            country_by_ad.setdefault((account_id, name), country)

    combos = (
        db.query(AdCombo)
        .filter(
            (AdCombo.country.is_(None))
            | (AdCombo.country == "")
            | (AdCombo.country == "Unknown")
        )
        .all()
    )
    updated = 0
    for combo in combos:
        c = country_by_ad.get((combo.branch_id, combo.ad_name))
        if c:
            combo.country = c
            updated += 1
    db.commit()
    logger.info(
        "[backfill-combo-country] %d combos updated (of %d candidates)",
        updated, len(combos),
    )


@router.post("/internal/tasks/backfill-combo-country", status_code=202)
def trigger_backfill_combo_country(
    x_internal_secret: str | None = Header(default=None),
):
    """One-shot: fill AdCombo.country from the Ad -> AdSet link so the keypoints
    country filter has data. Safe to run multiple times."""
    _require_secret(x_internal_secret)
    _run_in_thread(_do_backfill_combo_country, "backfill-combo-country")
    return _api_response(data={"status": "started"})


# ----------------------------------------------------------------- debug ----


@router.post("/internal/tasks/debug-combo", status_code=200)
def debug_combo(
    combo_id: str | None = None,
    q: str | None = None,
    x_internal_secret: str | None = Header(default=None),
):
    """One-shot diagnosis for a single combo: returns the DB ad_name and the
    Meta insights returned for that ad in the last 45 days, so name-mismatch
    vs no-spend can be told apart without direct DB access.

    Pass `combo_id` (exact, e.g. CMB-182) or `q` (ILIKE substring on ad_name).
    Runs synchronously — body is the diagnosis JSON, not a 202 ack.
    """
    _require_secret(x_internal_secret)
    if not combo_id and not q:
        raise HTTPException(status_code=400, detail="pass combo_id or q")

    from datetime import date as _date, timedelta as _timedelta

    from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
    from facebook_business.api import FacebookAdsApi

    from app.models.account import AdAccount
    from app.models.ad_combo import AdCombo

    db = SessionLocal()
    try:
        if combo_id:
            combos = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).all()
        else:
            combos = db.query(AdCombo).filter(AdCombo.ad_name.ilike(f"%{q}%")).all()

        if not combos:
            return _api_response(error="no combo matched")

        results = []
        for combo in combos:
            account = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first()
            info: dict = {
                "combo_id": combo.combo_id,
                "ad_name_db": combo.ad_name,
                "ad_name_db_repr": repr(combo.ad_name),  # exposes hidden chars
                "ad_name_db_len": len(combo.ad_name or ""),
                "branch": account.account_name if account else None,
                "branch_id": str(combo.branch_id) if combo.branch_id else None,
                "platform": account.platform if account else None,
                "account_active": account.is_active if account else None,
                "has_token": bool(account.access_token_enc) if account else False,
                "current_spend": float(combo.spend) if combo.spend else None,
                "current_roas": float(combo.roas) if combo.roas else None,
                "current_conversions": int(combo.conversions) if combo.conversions else None,
                "updated_at": combo.updated_at.isoformat() if combo.updated_at else None,
            }

            if not account or not account.access_token_enc or account.platform != "meta":
                info["meta_lookup"] = "skipped (not Meta or no token)"
                results.append(info)
                continue

            try:
                FacebookAdsApi.init(app_id="", app_secret="", access_token=account.access_token_enc)
                acc_id = (
                    account.account_id
                    if account.account_id.startswith("act_")
                    else f"act_{account.account_id}"
                )
                fb = FBAdAccount(acc_id)
                date_to = _date.today()
                date_from = date_to - _timedelta(days=45)

                rows = list(fb.get_insights(
                    fields=["ad_name", "spend", "impressions"],
                    params={
                        "level": "ad",
                        "time_range": {
                            "since": date_from.isoformat(),
                            "until": date_to.isoformat(),
                        },
                    },
                ))

                db_name = combo.ad_name or ""
                db_name_norm = db_name.strip().lower()

                exact_matches = []
                fuzzy_matches = []
                for r in rows:
                    rn = r.get("ad_name") or ""
                    if rn == db_name:
                        exact_matches.append({
                            "ad_name": rn,
                            "spend": float(r.get("spend", 0) or 0),
                            "impressions": int(r.get("impressions", 0) or 0),
                        })
                        continue
                    rn_norm = rn.strip().lower()
                    # Fuzzy: case/whitespace differences or substring on either side
                    if rn_norm == db_name_norm or db_name_norm in rn_norm or rn_norm in db_name_norm:
                        fuzzy_matches.append({
                            "ad_name_meta": rn,
                            "ad_name_meta_repr": repr(rn),
                            "spend": float(r.get("spend", 0) or 0),
                            "impressions": int(r.get("impressions", 0) or 0),
                        })

                info["meta_window"] = f"{date_from} → {date_to} (45d)"
                info["meta_total_ads_in_window"] = len(rows)
                info["meta_exact_matches"] = exact_matches
                info["meta_fuzzy_matches"] = fuzzy_matches[:5]

                if exact_matches:
                    info["diagnosis"] = (
                        "EXACT MATCH found on Meta — metrics should have been written. "
                        "If combo is still empty, the daily cron either hasn't fired since "
                        "(check Actions → Cron — Creative combo metrics) or errored mid-run."
                    )
                elif fuzzy_matches:
                    info["diagnosis"] = (
                        "NAME MISMATCH — DB ad_name differs from what Meta returns. "
                        "Likely cause: ad was renamed on Meta after the combo was first synced. "
                        "Fix: update combo.ad_name in DB to match Meta, or rename the ad back on Meta."
                    )
                else:
                    info["diagnosis"] = (
                        "NO MATCH — ad_name not found in this account's 45-day insights. "
                        "Either the ad has zero spend in the window, lives in a different ad "
                        "account, or has been deleted/archived without delivery."
                    )
            except Exception as e:
                info["meta_lookup_error"] = str(e)[:500]

            results.append(info)

        return _api_response(data={"results": results})
    finally:
        db.close()
