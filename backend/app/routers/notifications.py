from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.notification_service import get_notifications, mark_all_as_read, mark_as_read

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/notifications")
def list_notifications(
    is_read: bool | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List notifications for current user."""
    try:
        notifications, total, unread_count = get_notifications(
            db, current_user.id, is_read=is_read, limit=limit, offset=offset
        )
        items = [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "reference_id": n.reference_id,
                "reference_type": n.reference_type,
                "is_read": n.is_read,
                "read_at": n.read_at.isoformat() if n.read_at else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ]
        return _api_response(data={"items": items, "total": total, "unread_count": unread_count})
    except Exception as e:
        return _api_response(error=str(e))


@router.put("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a single notification as read."""
    try:
        found = mark_as_read(db, notification_id, current_user.id)
        if not found:
            return _api_response(error="Notification not found")
        db.commit()
        return _api_response(data={"message": "Marked as read"})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.put("/notifications/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for current user."""
    try:
        count = mark_all_as_read(db, current_user.id)
        db.commit()
        return _api_response(data={"message": f"Marked {count} notifications as read", "count": count})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
