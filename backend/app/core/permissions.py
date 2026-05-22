"""Per-branch + per-section permission helpers.

Model:
- User has 0..N rows in `user_permissions`, each (branch, section, level).
- level='view' => read-only for that (branch, section).
- level='edit' => read + write.
- No row => no access to that (branch, section).
- If user.roles contains 'admin' => bypass everything (full edit on all).
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.user_page_permission import UserPagePermission

# ── Canonical constants ────────────────────────────────────────

BRANCHES: list[str] = ["Saigon", "Osaka", "Taipei", "1948", "Oani", "Bread"]

SECTIONS: list[str] = [
    "analytics",
    "meta_ads",
    "google_ads",
    "budget",
    "automation",
    "ai",
    "settings",
    "landing_pages",
]

# Canonical pages — one screen each, grouped by the section they belong to.
# `page` keys are stored in user_page_permissions.page. Keep in sync with the
# frontend PAGES map (AuthContext) and the Sidebar nav.
PAGES: dict[str, dict[str, str]] = {
    # analytics
    "dashboard": {"section": "analytics", "label": "Dashboard"},
    "booking_matches": {"section": "analytics", "label": "Booking from Ads"},
    # meta_ads
    "meta_recommendations": {"section": "meta_ads", "label": "Recommendations"},
    "angles": {"section": "meta_ads", "label": "Ad Angles"},
    "creative": {"section": "meta_ads", "label": "Creative Library"},
    "figma": {"section": "meta_ads", "label": "Figma"},
    "approvals": {"section": "meta_ads", "label": "Approvals"},
    "keypoints": {"section": "meta_ads", "label": "Keypoints"},
    "ad_research": {"section": "meta_ads", "label": "Spy Ads"},
    # google_ads
    "google_pmax": {"section": "google_ads", "label": "PMax Campaigns"},
    "google_search": {"section": "google_ads", "label": "Search Campaigns"},
    "google_recommendations": {"section": "google_ads", "label": "Recommendations"},
    # budget
    "budget_planner": {"section": "budget", "label": "Budget Planner"},
    # landing_pages
    "landing_pages_all": {"section": "landing_pages", "label": "All Pages"},
    "landing_pages_approvals": {"section": "landing_pages", "label": "Approvals"},
    # automation
    "tactics": {"section": "automation", "label": "Tactics"},
    "logs": {"section": "automation", "label": "Action Logs"},
    # ai
    "insights": {"section": "ai", "label": "AI Insights"},
    "transcriptions": {"section": "ai", "label": "Video Transcriptions"},
    # settings
    "accounts": {"section": "settings", "label": "Accounts"},
    "users": {"section": "settings", "label": "Users"},
    "api_keys": {"section": "settings", "label": "API Keys"},
    "currency_rates": {"section": "settings", "label": "Currency Rates"},
}

LEVELS: list[str] = ["view", "edit"]

# 'edit' implies 'view' — use this for comparisons
_LEVEL_RANK = {"view": 1, "edit": 2}


def pages_for_section(section: str) -> list[str]:
    """All canonical page keys that belong to `section`."""
    return [pg for pg, meta in PAGES.items() if meta["section"] == section]


def section_for_page(page: str) -> str | None:
    meta = PAGES.get(page)
    return meta["section"] if meta else None


# ── Core helpers ───────────────────────────────────────────────


def is_admin(user: User | None) -> bool:
    if user is None:
        return False
    return "admin" in (user.roles or [])


def _level_at_least(have: str, need: str) -> bool:
    return _LEVEL_RANK.get(have, 0) >= _LEVEL_RANK.get(need, 0)


def accessible_branches(
    db: Session,
    user: User,
    section: str,
    min_level: str = "view",
) -> list[str] | None:
    """Return branch names the user can access at >= min_level for `section`.

    Returns None when the user is an admin — meaning "no branch filter, all allowed".
    Returns [] when the user has no access at all (callers should treat as empty result).
    """
    if is_admin(user):
        return None
    if section not in SECTIONS:
        return []

    rows = (
        db.query(UserPermission.branch, UserPermission.level)
        .filter(UserPermission.user_id == user.id, UserPermission.section == section)
        .all()
    )
    return [b for (b, lvl) in rows if _level_at_least(lvl, min_level)]


def has_section_access(
    db: Session,
    user: User,
    section: str,
    min_level: str = "view",
) -> bool:
    """True if user has ANY branch access at >= min_level for `section`."""
    if is_admin(user):
        return True
    branches = accessible_branches(db, user, section, min_level)
    return bool(branches)


def has_branch_access(
    db: Session,
    user: User,
    section: str,
    branch: str,
    min_level: str = "view",
) -> bool:
    """True if user can access `branch` in `section` at >= min_level."""
    if is_admin(user):
        return True
    branches = accessible_branches(db, user, section, min_level)
    return branch in (branches or [])


def accessible_pages(
    db: Session,
    user: User,
    section: str,
    min_level: str = "view",
) -> list[str] | None:
    """Page keys within `section` the user may open at >= min_level.

    Returns None when there is NO page-level restriction for this section —
    meaning the user can open ALL pages of the section (subject to ordinary
    section access). This is the default for any user with no page rows, so
    existing users are unaffected.

    Returns a list (possibly empty) when the user HAS page rows for this
    section — access is then restricted to exactly those pages.

    Admin => None (no restriction).
    """
    if is_admin(user):
        return None

    section_pages = set(pages_for_section(section))
    if not section_pages:
        return None

    rows = (
        db.query(UserPagePermission.page, UserPagePermission.level)
        .filter(UserPagePermission.user_id == user.id)
        .all()
    )
    relevant = [(pg, lvl) for (pg, lvl) in rows if pg in section_pages]
    if not relevant:
        return None  # no page-level restriction for this section
    return [pg for (pg, lvl) in relevant if _level_at_least(lvl, min_level)]


def has_page_access(
    db: Session,
    user: User,
    page: str,
    min_level: str = "view",
) -> bool:
    """True if the user may open `page` at >= min_level.

    Layered on top of section access: the user must first have section access
    (which governs data scope). When no page restriction exists for the page's
    section, this falls back to plain section-level access — identical to the
    old behaviour. When a page restriction exists, the page must be listed at
    >= min_level.
    """
    if is_admin(user):
        return True

    section = section_for_page(page)
    if section is None:
        return False

    # Must have at least view access to the section to see any of its pages.
    if not has_section_access(db, user, section, "view"):
        return False

    pages = accessible_pages(db, user, section, min_level)
    if pages is None:
        # No page restriction — defer to section-level capability.
        return has_section_access(db, user, section, min_level)
    return page in pages


def resolve_branch_filter(
    db: Session,
    user: User,
    section: str,
    requested_branch: str | None,
    min_level: str = "view",
) -> tuple[bool, list[str] | None, str | None]:
    """Helper used by list endpoints to resolve a client-supplied branch param.

    Returns (ok, branches_filter, error_message):
      - ok=False with error when a requested branch is not permitted
      - ok=True with branches_filter=None   -> admin, no filter needed
      - ok=True with branches_filter=[...]  -> filter results to these branch names
      - ok=True with branches_filter=[req]  -> a single specific branch was requested and is allowed
    """
    if is_admin(user):
        if requested_branch:
            return True, [requested_branch], None
        return True, None, None

    allowed = accessible_branches(db, user, section, min_level) or []
    if requested_branch:
        if requested_branch not in allowed:
            return False, None, f"No {min_level} access to branch '{requested_branch}'"
        return True, [requested_branch], None
    return True, allowed, None


def scoped_account_ids(
    db: Session,
    user: User,
    section: str,
    requested_account_id: str | None = None,
    requested_branches: list[str] | None = None,
    min_level: str = "view",
) -> tuple[bool, list[str] | None, str | None]:
    """Resolve the final account-id filter for an analytics-style endpoint.

    Returns (ok, account_ids, error):
      - ok=False + error   -> caller should return 403 with the error string
      - account_ids=None   -> no filter (admin + no params)
      - account_ids=[...]  -> apply .filter(account_id IN (...))
      - account_ids=[]     -> caller should return an empty result

    Branch -> account IDs mapping uses get_account_ids_for_branches in accounts.py.
    """
    # Local import to avoid circular imports at module load time
    from app.routers.accounts import get_account_ids_for_branches

    admin = is_admin(user)

    # Admin: honor whatever the client asked for
    if admin:
        if requested_account_id:
            return True, [requested_account_id], None
        if requested_branches:
            ids = get_account_ids_for_branches(db, requested_branches)
            return True, ids, None
        return True, None, None

    allowed_branches = accessible_branches(db, user, section, min_level) or []
    if not allowed_branches:
        return False, None, f"No {min_level} access to section '{section}'"

    allowed_ids = set(get_account_ids_for_branches(db, allowed_branches))

    # Client asked for a specific account_id — it must be within allowed set
    if requested_account_id:
        if requested_account_id not in allowed_ids:
            return False, None, f"No {min_level} access to account '{requested_account_id}'"
        return True, [requested_account_id], None

    # Client asked for branches — intersect
    if requested_branches:
        req_ids = set(get_account_ids_for_branches(db, requested_branches))
        unauthorized = [
            b for b in requested_branches if b not in allowed_branches
        ]
        if unauthorized:
            return False, None, f"No {min_level} access to branches: {unauthorized}"
        return True, list(req_ids & allowed_ids), None

    # Default: all accounts the user can see for this section
    return True, list(allowed_ids), None


def permission_dict(
    user: User,
    permissions: Iterable[UserPermission],
    page_permissions: Iterable[UserPagePermission] | None = None,
) -> dict:
    """Shape used by /auth/me and /users/{id}/permissions responses."""
    items = [
        {"branch": p.branch, "section": p.section, "level": p.level}
        for p in permissions
    ]
    # accessible_sections is a denormalised view keyed by section for quick UI lookups.
    accessible: dict[str, list[str]] = {s: [] for s in SECTIONS}
    for p in permissions:
        if p.section in accessible and p.branch not in accessible[p.section]:
            accessible[p.section].append(p.branch)

    page_items = [
        {"page": pp.page, "level": pp.level}
        for pp in (page_permissions or [])
        if pp.page in PAGES
    ]
    # restricted_sections lists sections where the user has explicit page rows
    # (i.e. their page access is narrowed). The frontend uses this to know when
    # to apply page filtering vs. show all pages.
    restricted_sections = sorted(
        {PAGES[pi["page"]]["section"] for pi in page_items}
    )
    return {
        "is_admin": is_admin(user),
        "permissions": items,
        "accessible_sections": accessible,
        "page_permissions": page_items,
        "restricted_sections": restricted_sections,
    }
