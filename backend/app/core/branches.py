"""Branch ↔ account/currency mapping, shared by routers and services.

Single source of truth — do not redeclare BRANCH_ACCOUNT_MAP in individual
modules. Importing sites: routers/accounts.py, routers/campaigns.py,
routers/booking_matches.py, services/budget_service.py, services/changelog.py.
"""
from sqlalchemy.orm import Session

from app.models.account import AdAccount


BRANCH_ACCOUNT_MAP: dict[str, list[str]] = {
    "Saigon": ["Meander Saigon", "Saigon"],
    "Osaka": ["Meander Osaka", "Osaka"],
    # Bare "Taipei" omitted — would ilike-match "Oani (Taipei)".
    "Taipei": ["Meander Taipei"],
    "1948": ["Meander 1948", "1948"],
    "Oani": ["Oani (Taipei)", "Oani"],
    "Bread": ["Bread Espresso", "Bread"],
}

BRANCH_CURRENCY: dict[str, str] = {
    "Saigon": "VND",
    "Osaka": "JPY",
    "Taipei": "TWD",
    "1948": "TWD",
    "Oani": "TWD",
    "Bread": "TWD",
}


def get_account_ids_for_branches(db: Session, branches: list[str]) -> list[str]:
    """Return all active account IDs whose account_name matches any branch pattern."""
    account_ids: list[str] = []
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
    """Flatten canonical branch names to ilike-ready substring patterns used by
    BookingMatch / Reservation / BudgetPlan rows."""
    out: list[str] = []
    for b in branches:
        out.extend(BRANCH_ACCOUNT_MAP.get(b, [b]))
    return out


def resolve_branch_for_account_name(account_name: str) -> str | None:
    """Given an AdAccount.account_name, return the canonical branch key or None."""
    if not account_name:
        return None
    lower = account_name.lower()
    for branch, patterns in BRANCH_ACCOUNT_MAP.items():
        for pattern in patterns:
            if pattern.lower() in lower:
                return branch
    return None


def canonical_branch(branch: str | None) -> str | None:
    """Normalize a user-supplied branch slug to a canonical BRANCH_ACCOUNT_MAP key.

    Case-insensitive. Returns None if the input is empty or doesn't match any
    canonical branch. External consumers commonly send lowercase ("saigon",
    "osaka"); internal storage uses the canonical case ("Saigon", "Osaka").
    """
    if not branch:
        return None
    target = branch.strip().lower()
    if not target:
        return None
    for canonical in BRANCH_ACCOUNT_MAP.keys():
        if canonical.lower() == target:
            return canonical
    return None
