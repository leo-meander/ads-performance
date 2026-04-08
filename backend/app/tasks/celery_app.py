from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "ads_platform",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Celery Beat schedule (times in UTC — Asia/Taipei is UTC+8)
celery_app.conf.beat_schedule = {
    # Sync at 9:00 AM Taipei (01:00 UTC) and 3:00 PM Taipei (07:00 UTC)
    "sync-all-platforms": {
        "task": "app.tasks.sync_tasks.sync_all_platforms_task",
        "schedule": crontab(hour="1,7", minute=0),
    },
    # Daily at 00:05 UTC (08:05 Asia/Taipei): re-enable yesterday's paused ads, then sync & evaluate
    "daily-rule-cycle": {
        "task": "app.tasks.sync_tasks.daily_rule_cycle_task",
        "schedule": crontab(hour=0, minute=5),
    },
}

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
