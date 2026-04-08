from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_role
from app.models.user import User
from app.services.auth_service import hash_password

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "roles": u.roles,
        "is_active": u.is_active,
        "notification_email": u.notification_email,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# ── Schemas ──────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    email: str
    full_name: str
    password: str
    roles: list[str] = ["creator"]


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    notification_email: bool | None = None


# ── Endpoints ────────────────────────────────────────────────


@router.get("/users/reviewers")
def list_reviewers(
    current_user: User = Depends(require_role(["admin", "creator"])),
    db: Session = Depends(get_db),
):
    """List users with reviewer role — for reviewer selection dropdown."""
    try:
        users = db.query(User).filter(User.is_active == True).all()
        reviewers = [u for u in users if "reviewer" in (u.roles or []) or "admin" in (u.roles or [])]
        return _api_response(
            data={
                "items": [
                    {"id": u.id, "email": u.email, "full_name": u.full_name, "roles": u.roles}
                    for u in reviewers
                ]
            }
        )
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/users")
def list_users(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(User)
        total = q.count()
        users = q.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
        return _api_response(data={"items": [_user_to_dict(u) for u in users], "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/users")
def create_user(
    body: CreateUserRequest,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        # Check for duplicate email
        existing = db.query(User).filter(User.email == body.email).first()
        if existing:
            return _api_response(error=f"User with email {body.email} already exists")

        user = User(
            email=body.email,
            full_name=body.full_name,
            password_hash=hash_password(body.password),
            roles=body.roles,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return _api_response(data=_user_to_dict(user))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return _api_response(error="User not found")

        if body.full_name is not None:
            user.full_name = body.full_name
        if body.roles is not None:
            user.roles = body.roles
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.notification_email is not None:
            user.notification_email = body.notification_email

        db.commit()
        db.refresh(user)
        return _api_response(data=_user_to_dict(user))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return _api_response(error="User not found")

        # Soft delete
        user.is_active = False
        db.commit()
        return _api_response(data={"message": f"User {user.email} deactivated"})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
