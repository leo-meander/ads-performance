import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.email_tasks.send_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_email_task(self, to: str, subject: str, html_body: str):
    """Async email send via Celery. Retries up to 3 times with exponential backoff."""
    from app.services.email_service import send_email

    try:
        success = send_email(to, subject, html_body)
        if not success:
            logger.warning("Email send returned False for %s: %s", to, subject)
        return {"status": "sent" if success else "skipped", "to": to, "subject": subject}
    except Exception as exc:
        logger.exception("Email task failed for %s: %s", to, subject)
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
