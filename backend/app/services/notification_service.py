import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.notification import Notification

logger = logging.getLogger(__name__)


def create_notification(
    db: Session,
    user_id: str,
    type: str,
    title: str,
    body: str,
    reference_id: str | None = None,
    reference_type: str | None = None,
) -> Notification:
    """Create an in-system notification for a user."""
    notif = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        reference_id=reference_id,
        reference_type=reference_type,
    )
    db.add(notif)
    db.flush()
    return notif


def get_notifications(
    db: Session,
    user_id: str,
    is_read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Notification], int, int]:
    """Get notifications for a user. Returns (notifications, total, unread_count)."""
    q = db.query(Notification).filter(Notification.user_id == user_id)

    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .count()
    )

    if is_read is not None:
        q = q.filter(Notification.is_read == is_read)

    total = q.count()
    notifications = q.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()

    return notifications, total, unread_count


def mark_as_read(db: Session, notification_id: str, user_id: str) -> bool:
    """Mark a single notification as read. Returns True if found and updated."""
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notif:
        return False
    notif.is_read = True
    notif.read_at = datetime.now(timezone.utc)
    return True


def mark_all_as_read(db: Session, user_id: str) -> int:
    """Mark all notifications as read for a user. Returns count of updated rows."""
    now = datetime.now(timezone.utc)
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .update({"is_read": True, "read_at": now})
    )
    return count
