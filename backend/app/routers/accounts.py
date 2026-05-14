from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.branches import (
    BRANCH_ACCOUNT_MAP,
    BRANCH_CURRENCY,
    branch_name_patterns,
    get_account_ids_for_branches,
)
from app.core.permissions import BRANCHES, SECTIONS, is_admin
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.account import AdAccount
from app.models.user import User
from app.models.user_permission import UserPermission

router = APIRouter()


class AccountCreate(BaseModel):
    platform: str  # meta | google | tiktok
    account_id: str  # platform native account ID
    account_name: str
    currency: str = "VND"
    access_token: str | None = None


class AccountResponse(BaseModel):
    id: str
    platform: str
    account_id: str
    account_name: str
    currency: str
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}


class AccountUpdate(BaseModel):
    """Patch the Meta-publish config fields on an ad account.

    Both fields are launch prerequisites surfaced by the launch preflight —
    they're optional here so the caller can set just one at a time.
    """
    meta_page_id: str | None = None
    default_destination_url: str | None = None


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/accounts")
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
        # Non-admins only see accounts from branches they have any permission on
        if not is_admin(current_user):
            user_branches = {
                row[0]
                for row in db.query(UserPermission.branch)
                .filter(UserPermission.user_id == current_user.id)
                .all()
            }
            allowed_ids = set(get_account_ids_for_branches(db, list(user_branches)))
            accounts = [a for a in accounts if str(a.id) in allowed_ids]
        return _api_response(data=[
            {
                "id": str(a.id),
                "platform": a.platform,
                "account_id": a.account_id,
                "account_name": a.account_name,
                "currency": a.currency,
                "is_active": a.is_active,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "meta_page_id": a.meta_page_id,
                "default_destination_url": a.default_destination_url,
            }
            for a in accounts
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/branches")
def list_branches(
    section: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return branches available to the current user.

    Admin: all branches that have at least one active account.
    Non-admin: only branches the user has any permission for (optionally filtered by section).
    """
    try:
        if is_admin(current_user):
            allowed = set(BRANCH_ACCOUNT_MAP.keys())
        else:
            q = db.query(UserPermission.branch).filter(
                UserPermission.user_id == current_user.id
            )
            if section:
                if section not in SECTIONS:
                    return _api_response(error=f"Invalid section: {section}")
                q = q.filter(UserPermission.section == section)
            allowed = {row[0] for row in q.all()}

        branches = []
        for branch, patterns in BRANCH_ACCOUNT_MAP.items():
            if branch not in allowed:
                continue
            has_accounts = False
            for pattern in patterns:
                count = db.query(AdAccount.id).filter(
                    AdAccount.account_name.ilike(f"%{pattern}%"),
                    AdAccount.is_active.is_(True),
                ).count()
                if count > 0:
                    has_accounts = True
                    break
            if has_accounts:
                branches.append({
                    "name": branch,
                    "currency": BRANCH_CURRENCY.get(branch, "VND"),
                })
        return _api_response(data=branches)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/accounts")
def create_account(
    body: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Only admins can create ad accounts
    if not is_admin(current_user):
        return _api_response(error="Only admins can create ad accounts")
    try:
        # Check if account already exists
        existing = (
            db.query(AdAccount)
            .filter(
                AdAccount.platform == body.platform,
                AdAccount.account_id == body.account_id,
            )
            .first()
        )
        if existing:
            return _api_response(error=f"Account {body.account_id} already exists for {body.platform}")

        account = AdAccount(
            platform=body.platform,
            account_id=body.account_id,
            account_name=body.account_name,
            currency=body.currency,
            access_token_enc=body.access_token,  # TODO: encrypt in production
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        return _api_response(data={
            "id": str(account.id),
            "platform": account.platform,
            "account_id": account.account_id,
            "account_name": account.account_name,
            "currency": account.currency,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: str,
    body: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Patch an ad account's Meta-publish config (meta_page_id,
    default_destination_url). Admins and creators can edit — creators need it
    because they're the ones launching ads and hitting the missing-field
    preflight blockers."""
    if not (is_admin(current_user) or "creator" in (current_user.roles or [])):
        return _api_response(error="Only admins or creators can edit ad accounts")
    try:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return _api_response(error="Account not found")

        fields = body.model_dump(exclude_unset=True)
        if "meta_page_id" in fields:
            account.meta_page_id = (fields["meta_page_id"] or "").strip() or None
        if "default_destination_url" in fields:
            account.default_destination_url = (
                (fields["default_destination_url"] or "").strip() or None
            )

        db.commit()
        db.refresh(account)
        return _api_response(data={
            "id": str(account.id),
            "platform": account.platform,
            "account_id": account.account_id,
            "account_name": account.account_name,
            "meta_page_id": account.meta_page_id,
            "default_destination_url": account.default_destination_url,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
