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
    # Daily at 23:00 UTC (07:00 Asia/Taipei next day): re-enable yesterday's paused ads,
    # sync all platforms, auto-classify combos, auto-assign angle+keypoints, eval rules.
    "daily-rule-cycle": {
        "task": "app.tasks.sync_tasks.daily_rule_cycle_task",
        "schedule": crontab(hour=23, minute=0),
    },
    # Daily at 00:00 UTC (08:00 Asia/Taipei): sync PMS reservations and run booking matching
    "sync-reservations-and-match": {
        "task": "app.tasks.sync_tasks.sync_reservations_and_match_task",
        "schedule": crontab(hour=0, minute=0),
    },
    # Weekly on Monday at 01:00 UTC (09:00 Asia/Taipei): refresh Meta creative preview URLs
    # (Meta CDN URLs expire after ~a few weeks; weekly refresh keeps thumbnails alive)
    "sync-material-urls-weekly": {
        "task": "app.tasks.sync_tasks.sync_material_urls_task",
        "schedule": crontab(hour=1, minute=0, day_of_week=1),
    },
    # Google Ads Power Pack recommendation engine.
    # Times are UTC; Asia/Ho_Chi_Minh is UTC+7 (i.e. 22:30 UTC = 05:30 local).
    "google-recs-daily": {
        "task": "app.tasks.google_recommendation_tasks.daily_google_recommendations_task",
        "schedule": crontab(hour=22, minute=30),
    },
    "google-recs-weekly": {
        "task": "app.tasks.google_recommendation_tasks.weekly_google_recommendations_task",
        # Monday 23:00 UTC = Tuesday 06:00 Asia/Ho_Chi_Minh.
        "schedule": crontab(hour=23, minute=0, day_of_week=1),
    },
    "google-recs-monthly": {
        "task": "app.tasks.google_recommendation_tasks.monthly_google_recommendations_task",
        # 1st of month 23:30 UTC = 2nd 06:30 local.
        "schedule": crontab(hour=23, minute=30, day_of_month=1),
    },
    "google-recs-seasonality": {
        "task": "app.tasks.google_recommendation_tasks.seasonality_lookahead_task",
        # 21:00 UTC = 04:00 local the next day.
        "schedule": crontab(hour=21, minute=0),
    },
    "google-recs-expire": {
        "task": "app.tasks.google_recommendation_tasks.expire_google_recommendations_task",
        "schedule": crontab(minute=15),  # hourly at :15
    },
    # Meta Ads playbook recommendation engine.
    # Offset 30 min from the Google schedule so the two engines don't
    # contend for the same Anthropic rate limit / DB connection pool.
    "meta-recs-daily": {
        "task": "app.tasks.meta_recommendation_tasks.daily_meta_recommendations_task",
        "schedule": crontab(hour=23, minute=0),
    },
    "meta-recs-weekly": {
        "task": "app.tasks.meta_recommendation_tasks.weekly_meta_recommendations_task",
        # Monday 23:30 UTC = Tuesday 06:30 Asia/Ho_Chi_Minh.
        "schedule": crontab(hour=23, minute=30, day_of_week=1),
    },
    "meta-recs-monthly": {
        "task": "app.tasks.meta_recommendation_tasks.monthly_meta_recommendations_task",
        # 1st of month 00:00 UTC = 07:00 local.
        "schedule": crontab(hour=0, minute=0, day_of_month=1),
    },
    "meta-recs-seasonality": {
        "task": "app.tasks.meta_recommendation_tasks.seasonality_meta_task",
        # 21:30 UTC = 04:30 local the next day.
        "schedule": crontab(hour=21, minute=30),
    },
    "meta-recs-expire": {
        "task": "app.tasks.meta_recommendation_tasks.expire_meta_recommendations_task",
        "schedule": crontab(minute=45),  # hourly at :45
    },
}

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
