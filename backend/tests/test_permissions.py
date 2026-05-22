"""Tests for the per-branch + per-section permission system."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.permissions import (
    accessible_branches,
    accessible_pages,
    has_branch_access,
    has_page_access,
    has_section_access,
    is_admin,
    permission_dict,
)
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.user_page_permission import UserPagePermission
from app.services.auth_service import create_access_token, hash_password

engine = create_engine("sqlite:///test_platform_perms.db", connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_user(roles=None, email=None):
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=email or f"test_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Test User",
        password_hash=hash_password("pw"),
        roles=roles or [],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _grant(user_id: str, branch: str, section: str, level: str):
    db = TestSession()
    db.add(UserPermission(
        user_id=user_id, branch=branch, section=section, level=level,
    ))
    db.commit()
    db.close()


def _grant_page(user_id: str, page: str, level: str):
    db = TestSession()
    db.add(UserPagePermission(user_id=user_id, page=page, level=level))
    db.commit()
    db.close()


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.roles or [])}"}


# ── Core helpers ─────────────────────────────────────────────


def test_is_admin_true_false():
    admin = _create_user(roles=["admin"])
    creator = _create_user(roles=["creator"])
    assert is_admin(admin) is True
    assert is_admin(creator) is False
    assert is_admin(None) is False


def test_accessible_branches_admin_returns_none():
    admin = _create_user(roles=["admin"])
    db = TestSession()
    try:
        assert accessible_branches(db, admin, "analytics") is None
    finally:
        db.close()


def test_accessible_branches_honors_level():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "analytics", "view")
    _grant(user.id, "Osaka", "analytics", "edit")
    db = TestSession()
    try:
        view_level = set(accessible_branches(db, user, "analytics", "view"))
        edit_level = set(accessible_branches(db, user, "analytics", "edit"))
        assert view_level == {"Saigon", "Osaka"}  # edit ⊂ view
        assert edit_level == {"Osaka"}
    finally:
        db.close()


def test_has_section_access():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "view")
    db = TestSession()
    try:
        assert has_section_access(db, user, "meta_ads") is True
        assert has_section_access(db, user, "meta_ads", "edit") is False
        assert has_section_access(db, user, "google_ads") is False
    finally:
        db.close()


def test_has_branch_access():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "edit")
    db = TestSession()
    try:
        assert has_branch_access(db, user, "meta_ads", "Saigon", "view") is True
        assert has_branch_access(db, user, "meta_ads", "Saigon", "edit") is True
        assert has_branch_access(db, user, "meta_ads", "Osaka", "view") is False
    finally:
        db.close()


def test_permission_dict_shape():
    user = _create_user(roles=["creator"])
    db = TestSession()
    try:
        p1 = UserPermission(user_id=user.id, branch="Saigon", section="meta_ads", level="view")
        p2 = UserPermission(user_id=user.id, branch="Osaka", section="meta_ads", level="edit")
        p3 = UserPermission(user_id=user.id, branch="Saigon", section="budget", level="edit")
        payload = permission_dict(user, [p1, p2, p3])
        assert payload["is_admin"] is False
        assert len(payload["permissions"]) == 3
        assert set(payload["accessible_sections"]["meta_ads"]) == {"Saigon", "Osaka"}
        assert payload["accessible_sections"]["budget"] == ["Saigon"]
        assert payload["accessible_sections"]["google_ads"] == []
    finally:
        db.close()


# ── API endpoints ────────────────────────────────────────────


def test_auth_me_returns_permissions():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "edit")
    resp = client.get("/api/auth/me", headers=_auth(user))
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["is_admin"] is False
    assert any(
        p["branch"] == "Saigon" and p["section"] == "meta_ads" and p["level"] == "edit"
        for p in data["data"]["permissions"]
    )
    assert data["data"]["accessible_sections"]["meta_ads"] == ["Saigon"]


def test_auth_me_admin_marks_is_admin_true():
    admin = _create_user(roles=["admin"])
    resp = client.get("/api/auth/me", headers=_auth(admin))
    assert resp.json()["data"]["is_admin"] is True


def test_require_section_blocks_user_with_no_grant():
    user = _create_user(roles=["creator"])
    resp = client.get("/api/angles", headers=_auth(user))
    # Section-gated endpoint should 403
    assert resp.status_code == 403


def test_require_section_allows_user_with_grant():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "view")
    resp = client.get("/api/angles", headers=_auth(user))
    assert resp.status_code == 200


def test_admin_always_bypasses_section_gate():
    admin = _create_user(roles=["admin"])
    # No permission rows at all
    resp = client.get("/api/angles", headers=_auth(admin))
    assert resp.status_code == 200


def test_write_endpoint_requires_edit_level():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "view")  # only view
    # POST /api/angles requires edit
    resp = client.post(
        "/api/angles",
        json={"angle_type": "Emotional", "angle_explain": "x"},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_admin_can_replace_user_permissions():
    admin = _create_user(roles=["admin"])
    target = _create_user(roles=["creator"])
    resp = client.put(
        f"/api/users/{target.id}/permissions",
        json={"items": [
            {"branch": "Saigon", "section": "meta_ads", "level": "edit"},
            {"branch": "Osaka", "section": "budget", "level": "view"},
        ]},
        headers=_auth(admin),
    )
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["permissions"]) == 2


def test_put_permissions_validates_values():
    admin = _create_user(roles=["admin"])
    target = _create_user(roles=["creator"])
    resp = client.put(
        f"/api/users/{target.id}/permissions",
        json={"items": [{"branch": "Atlantis", "section": "meta_ads", "level": "view"}]},
        headers=_auth(admin),
    )
    data = resp.json()
    assert data["success"] is False
    assert "branch" in data["error"].lower()


def test_non_admin_cannot_manage_permissions():
    user = _create_user(roles=["creator"])
    other = _create_user(roles=["creator"])
    resp = client.put(
        f"/api/users/{other.id}/permissions",
        json={"items": []},
        headers=_auth(user),
    )
    assert resp.status_code == 403


def test_branches_endpoint_scopes_by_user_permissions():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "analytics", "view")
    resp = client.get("/api/branches?section=analytics", headers=_auth(user))
    # Branch list only includes permitted branches (none will show because no AdAccount rows are set up,
    # but the path should still return 200 and success=True)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Page-level permissions ───────────────────────────────────


def test_accessible_pages_none_when_no_page_rows():
    """No page rows for a section => None (no restriction, sees all pages)."""
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "view")
    db = TestSession()
    try:
        assert accessible_pages(db, user, "meta_ads") is None
    finally:
        db.close()


def test_accessible_pages_restricts_to_granted():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "edit")
    _grant_page(user.id, "keypoints", "view")
    db = TestSession()
    try:
        # Only the granted page is returned for that section.
        assert accessible_pages(db, user, "meta_ads") == ["keypoints"]
        # A page row for meta_ads does not affect other sections.
        assert accessible_pages(db, user, "google_ads") is None
    finally:
        db.close()


def test_accessible_pages_admin_returns_none():
    admin = _create_user(roles=["admin"])
    db = TestSession()
    try:
        assert accessible_pages(db, admin, "meta_ads") is None
    finally:
        db.close()


def test_has_page_access_no_restriction_falls_back_to_section():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "view")  # view only, no page rows
    db = TestSession()
    try:
        assert has_page_access(db, user, "keypoints") is True
        assert has_page_access(db, user, "angles") is True
        # Edit falls back to section-level edit, which the user lacks.
        assert has_page_access(db, user, "keypoints", "edit") is False
    finally:
        db.close()


def test_has_page_access_restricted_page_and_level():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "edit")
    _grant_page(user.id, "keypoints", "view")
    db = TestSession()
    try:
        # Granted page at view: open yes, edit no (page level is view).
        assert has_page_access(db, user, "keypoints") is True
        assert has_page_access(db, user, "keypoints", "edit") is False
        # A sibling page in the same section is now blocked entirely.
        assert has_page_access(db, user, "angles") is False
    finally:
        db.close()


def test_has_page_access_requires_section_access():
    """Page rows are meaningless without section access (data scope)."""
    user = _create_user(roles=["creator"])
    _grant_page(user.id, "keypoints", "edit")  # page row but no meta_ads section grant
    db = TestSession()
    try:
        assert has_page_access(db, user, "keypoints") is False
    finally:
        db.close()


def test_has_page_access_admin_bypasses():
    admin = _create_user(roles=["admin"])
    db = TestSession()
    try:
        assert has_page_access(db, admin, "keypoints", "edit") is True
    finally:
        db.close()


def test_require_page_restricts_to_granted_pages_via_api():
    user = _create_user(roles=["creator"])
    _grant(user.id, "Saigon", "meta_ads", "view")
    _grant_page(user.id, "keypoints", "view")
    # Keypoints page granted -> 200
    resp_kp = client.get("/api/keypoints", headers=_auth(user))
    assert resp_kp.status_code == 200
    # Angles page NOT granted while restricted -> 403
    resp_ang = client.get("/api/angles", headers=_auth(user))
    assert resp_ang.status_code == 403


def test_admin_can_replace_page_permissions():
    admin = _create_user(roles=["admin"])
    target = _create_user(roles=["creator"])
    resp = client.put(
        f"/api/users/{target.id}/permissions",
        json={
            "items": [{"branch": "Saigon", "section": "meta_ads", "level": "view"}],
            "page_items": [{"page": "keypoints", "level": "view"}],
        },
        headers=_auth(admin),
    )
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["page_permissions"] == [{"page": "keypoints", "level": "view"}]
    assert data["data"]["restricted_sections"] == ["meta_ads"]


def test_put_page_permissions_validates_page():
    admin = _create_user(roles=["admin"])
    target = _create_user(roles=["creator"])
    resp = client.put(
        f"/api/users/{target.id}/permissions",
        json={"items": [], "page_items": [{"page": "not_a_page", "level": "view"}]},
        headers=_auth(admin),
    )
    data = resp.json()
    assert data["success"] is False
    assert "page" in data["error"].lower()
