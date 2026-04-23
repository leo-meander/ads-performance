from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
            }
            for a in accounts
        ])
    except Exception as e:
        return _api_response(error=str(e))


# Branch name → account_name patterns for matching
BRANCH_ACCOUNT_MAP = {
    "Saigon": ["Meander Saigon", "Saigon"],
    "Osaka": ["Meander Osaka", "Osaka"],
    "Taipei": ["Meander Taipei"],  # bare "Taipei" would also ilike-match "Oani (Taipei)"
    "1948": ["Meander 1948", "1948"],
    "Oani": ["Oani (Taipei)", "Oani"],
    "Bread": ["Bread Espresso", "Bread"],
}

BRANCH_CURRENCY = {
    "Saigon": "VND",
    "Osaka": "JPY",
    "Taipei": "TWD",
    "1948": "TWD",
    "Oani": "TWD",
    "Bread": "TWD",
}


def get_account_ids_for_branches(db: Session, branches: list[str]) -> list[str]:
    """Get all account IDs that belong to the given branches."""
    account_ids = []
    for branch in branches:
        patterns = BRANCH_ACCOUNT_MAP.get(branch, [branch])
        for pattern in patterns:
            accs = db.query(AdAccount.id).filter(
                AdAccount.account_name.ilike(f"%{pattern}%"),
                AdAccount.is_active.is_(True),
            ).all()
            account_ids.extend([str(a.id) for a in accs])
    return list(set(account_ids))


def branch_name_patterns(branches: list[str]) -> list[str]:
    """Flatten canonical branch names to the ilike-ready substring patterns used
    by BookingMatch / Reservation / BudgetPlan rows (which may store variants like
    'MEANDER Saigon')."""
    out: list[str] = []
    for b in branches:
        out.extend(BRANCH_ACCOUNT_MAP.get(b, [b]))
    return out


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
