from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
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
from app.services.changelog import log_change

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


class BudgetLimitsUpdate(BaseModel):
    """Per-branch limits for the Raise/Cut budget buttons on /action-needed.

    All fields optional — only sent fields are written. To CLEAR an absolute
    cap (back to "no limit"), POST with the field set to null explicitly.
    The pydantic exclude_unset on body.model_dump() distinguishes "omitted"
    from "explicitly null".

    Validation:
      - raise_pct: (0, 1] — 1.0 means double the budget (extreme, but legal)
      - cut_pct:   (0, 1) — must be strictly < 1 or you'd cut to zero
      - max_*_per_click_abs: > 0 if set, else NULL
    """
    raise_pct: float | None = Field(None, gt=0, le=1)
    cut_pct: float | None = Field(None, gt=0, lt=1)
    max_raise_per_click_abs: float | None = Field(None, ge=0)
    max_cut_per_click_abs: float | None = Field(None, ge=0)


@router.get("/accounts/{account_id}/budget-limits")
def get_budget_limits(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the 4 budget-limit fields for one account, plus currency for
    UI label formatting ("Raise budget (max NT$50)")."""
    try:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return _api_response(error="Account not found")
        return _api_response(data={
            "account_id": str(account.id),
            "account_name": account.account_name,
            "currency": account.currency,
            "raise_pct": float(account.raise_pct) if account.raise_pct is not None else None,
            "cut_pct": float(account.cut_pct) if account.cut_pct is not None else None,
            "max_raise_per_click_abs": (
                float(account.max_raise_per_click_abs)
                if account.max_raise_per_click_abs is not None else None
            ),
            "max_cut_per_click_abs": (
                float(account.max_cut_per_click_abs)
                if account.max_cut_per_click_abs is not None else None
            ),
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.patch("/accounts/{account_id}/budget-limits")
def update_budget_limits(
    account_id: str,
    body: BudgetLimitsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update per-branch raise/cut budget limits. Admins + creators only —
    this directly affects money flow on /action-needed.

    Audits to change_log_entries with before/after so the Activity Timeline
    surfaces who changed the cap and from what value (critical for tracing
    a budget overshoot back to a setting change).
    """
    if not (is_admin(current_user) or "creator" in (current_user.roles or [])):
        return _api_response(error="Only admins or creators can edit budget limits")

    try:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return _api_response(error="Account not found")

        # Snapshot before — for the audit diff.
        before = {
            "raise_pct": float(account.raise_pct) if account.raise_pct is not None else None,
            "cut_pct": float(account.cut_pct) if account.cut_pct is not None else None,
            "max_raise_per_click_abs": (
                float(account.max_raise_per_click_abs)
                if account.max_raise_per_click_abs is not None else None
            ),
            "max_cut_per_click_abs": (
                float(account.max_cut_per_click_abs)
                if account.max_cut_per_click_abs is not None else None
            ),
        }

        fields = body.model_dump(exclude_unset=True)
        if "raise_pct" in fields:
            account.raise_pct = fields["raise_pct"]
        if "cut_pct" in fields:
            account.cut_pct = fields["cut_pct"]
        if "max_raise_per_click_abs" in fields:
            # 0 sent explicitly is rejected by pydantic ge=0? actually ge=0
            # allows 0 — but 0 cap = "never raise", probably a typo. Treat
            # 0 as "clear cap" (NULL) to be safe.
            v = fields["max_raise_per_click_abs"]
            account.max_raise_per_click_abs = v if v else None
        if "max_cut_per_click_abs" in fields:
            v = fields["max_cut_per_click_abs"]
            account.max_cut_per_click_abs = v if v else None

        db.flush()

        after = {
            "raise_pct": float(account.raise_pct) if account.raise_pct is not None else None,
            "cut_pct": float(account.cut_pct) if account.cut_pct is not None else None,
            "max_raise_per_click_abs": (
                float(account.max_raise_per_click_abs)
                if account.max_raise_per_click_abs is not None else None
            ),
            "max_cut_per_click_abs": (
                float(account.max_cut_per_click_abs)
                if account.max_cut_per_click_abs is not None else None
            ),
        }

        # Only audit if something actually changed.
        if before != after:
            log_change(
                db,
                category="other",
                source="manual",
                triggered_by="manual",
                title=f"Budget limits updated · {account.account_name}"[:200],
                description=(
                    f"Per-branch Raise/Cut budget limits for {account.account_name} "
                    f"({account.currency}) changed by {current_user.email}."
                ),
                platform=account.platform,
                account_id=str(account.id),
                before_value=before,
                after_value=after,
                author_user_id=str(current_user.id),
            )

        db.commit()
        return _api_response(data={"account_id": str(account.id), **after})
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
