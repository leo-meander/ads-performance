import logging

from app.database import SessionLocal
from app.services.sync_engine import sync_all_platforms
from app.services.rule_engine import evaluate_all_rules, reenable_paused_ads
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.sync_tasks.sync_all_platforms_task", bind=True, max_retries=3)
def sync_all_platforms_task(self):
    """Celery task: sync all active ad accounts across all platforms.

    Runs every 15 minutes via Celery Beat.
    """
    logger.info("Starting scheduled sync for all platforms")
    db = SessionLocal()
    try:
        results = sync_all_platforms(db)
        logger.info("Sync completed: %d accounts processed", len(results))
        return {"accounts_processed": len(results), "results": results}
    except Exception as exc:
        logger.exception("Sync task failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_tasks.daily_rule_cycle_task", bind=True, max_retries=3)
def daily_rule_cycle_task(self):
    """Daily task: re-enable yesterday's paused ads, then sync & evaluate rules.

    Runs once daily (configured in Celery Beat).
    Flow:
    1. Re-enable ads paused by "Pause Ad Today" rules on previous days
    2. Sync all platforms (which also evaluates rules after sync)
    """
    logger.info("Starting daily rule cycle")
    db = SessionLocal()
    try:
        # Step 1: Re-enable ads paused on previous days
        reenable_results = reenable_paused_ads(db)
        reenabled_count = sum(1 for r in reenable_results if r["success"])
        logger.info("Daily re-enable: %d ads re-enabled", reenabled_count)

        # Step 2: Sync all platforms (this also evaluates rules after sync)
        sync_results = sync_all_platforms(db)
        logger.info("Daily sync completed: %d accounts processed", len(sync_results))

        return {
            "reenabled_ads": reenabled_count,
            "reenable_results": reenable_results,
            "accounts_processed": len(sync_results),
            "sync_results": sync_results,
        }
    except Exception as exc:
        logger.exception("Daily rule cycle failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
