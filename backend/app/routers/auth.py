from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password, verify_password

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
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            samesite="lax",
            secure=False,  # Set True in production with HTTPS
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
    return _api_response(
        data={
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "roles": current_user.roles,
            "is_active": current_user.is_active,
            "notification_email": current_user.notification_email,
            "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
        }
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

        current_user.password_hash = hash_password(body.new_password)
        db.commit()
        return _api_response(data={"message": "Password updated"})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
