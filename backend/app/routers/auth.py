from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core.permissions import permission_dict
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password, verify_password

_is_production = settings.APP_ENV == "production"

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Schemas ──────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── Endpoints ────────────────────────────────────────────────


@router.post("/auth/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == body.email, User.is_active == True).first()
        if not user or not verify_password(body.password, user.password_hash):
            return _api_response(error="Invalid email or password")

        token = create_access_token(user.id, user.roles or [])

        # Set httpOnly cookie
        # Production (cross-origin): SameSite=None + Secure required for cross-site cookies
        # Development (same origin): SameSite=Lax + Secure=False
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            samesite="none" if _is_production else "lax",
            secure=_is_production,
            max_age=86400,  # 24 hours
        )

        # Update last_login_at
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()

        return _api_response(
            data={
                "access_token": token,
                "expires_in": 86400,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "roles": user.roles,
                    "must_change_password": bool(user.must_change_password),
                },
            }
        )
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return _api_response(data={"message": "Logged out"})


@router.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    perms_payload = permission_dict(current_user, current_user.permissions or [])
    return _api_response(
        data={
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "roles": current_user.roles,
            "is_active": current_user.is_active,
            "notification_email": current_user.notification_email,
            "must_change_password": bool(current_user.must_change_password),
            "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
            **perms_payload,
        }
    )


@router.get("/auth/me/permissions")
def get_my_permissions(current_user: User = Depends(get_current_user)):
    return _api_response(
        data=permission_dict(current_user, current_user.permissions or [])
    )


@router.put("/auth/me/password")
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if not verify_password(body.current_password, current_user.password_hash):
            return _api_response(error="Current password is incorrect")
        if len(body.new_password or "") < 8:
            return _api_response(error="New password must be at least 8 characters")
        if body.new_password == body.current_password:
            return _api_response(error="New password must be different from the current one")

        current_user.password_hash = hash_password(body.new_password)
        current_user.must_change_password = False
        db.commit()
        return _api_response(data={"message": "Password updated"})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
