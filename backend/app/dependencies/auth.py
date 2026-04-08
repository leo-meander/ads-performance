import logging
from functools import wraps

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import decode_access_token

logger = logging.getLogger(__name__)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Extract JWT from httpOnly cookie, decode, and return the User object.

    Raises 401 if token is missing, invalid, or user is inactive.
    """
    # Check Authorization header first (preferred for API clients and tests)
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Fall back to httpOnly cookie (used by browser frontend)
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return user


def require_role(allowed_roles: list[str]):
    """FastAPI dependency factory that checks if the current user has one of the allowed roles.

    Usage:
        @router.post('/endpoint')
        def my_endpoint(user: User = Depends(require_role(['admin', 'creator']))):
            ...
    """

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_roles = current_user.roles or []
        if not any(role in allowed_roles for role in user_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {allowed_roles}",
            )
        return current_user

    return role_checker
