import logging
from functools import wraps

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.permissions import has_page_access, has_section_access
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


def require_section(section: str, level: str = "view"):
    """FastAPI dependency factory that ensures the current user has at least
    `level` access to *some* branch within `section`. Admin bypasses all checks.

    Usage:
        @router.get('/endpoint')
        def my_read(user: User = Depends(require_section('meta_ads'))):
            ...

        @router.post('/endpoint')
        def my_write(user: User = Depends(require_section('meta_ads', 'edit'))):
            ...
    """

    def section_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_section_access(db, current_user, section, level):
            raise HTTPException(
                status_code=403,
                detail=f"No {level} access to section '{section}'",
            )
        return current_user

    return section_checker


def require_page(page: str, level: str = "view"):
    """FastAPI dependency factory enforcing per-page access.

    Stricter cousin of `require_section`: the user must have access to the
    page's section AND, if their page access is restricted, the page must be
    granted at >= `level`. Users with no page rows behave exactly as under
    `require_section` (full section access), so swapping require_section ->
    require_page on a page's routes is backward compatible.

    Usage:
        @router.get('/endpoint')
        def my_read(user: User = Depends(require_page('keypoints'))):
            ...
    """

    def page_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_page_access(db, current_user, page, level):
            raise HTTPException(
                status_code=403,
                detail=f"No {level} access to page '{page}'",
            )
        return current_user

    return page_checker
