"""Tests for auth system: login, JWT, role enforcement, user management."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.user import User
from app.services.auth_service import create_access_token, decode_access_token, hash_password, verify_password

# ── Test database setup ──────────────────────────────────────

engine = create_engine("sqlite:///test_platform.db", connect_args={"check_same_thread": False})
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
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_user(roles=None, email=None, password="testpass123"):
    """Helper to create a user directly in DB."""
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=email or f"test_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Test User",
        password_hash=hash_password(password),
        roles=roles or ["creator"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _auth_headers(user):
    """Generate auth headers for a user."""
    token = create_access_token(user.id, user.roles or [])
    return {"Authorization": f"Bearer {token}"}


# ── Auth service tests ───────────────────────────────────────


def test_hash_and_verify_password():
    hashed = hash_password("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_create_and_decode_token():
    token = create_access_token("user-123", ["admin", "creator"])
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["roles"] == ["admin", "creator"]


def test_decode_invalid_token():
    assert decode_access_token("invalid.token.here") is None


# ── Auth endpoint tests ──────────────────────────────────────


def test_login_success():
    user = _create_user(email="login@meander.com", password="pass123")
    response = client.post("/api/auth/login", json={"email": "login@meander.com", "password": "pass123"})
    data = response.json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    assert data["data"]["user"]["email"] == "login@meander.com"


def test_login_wrong_password():
    _create_user(email="wrong@meander.com", password="pass123")
    response = client.post("/api/auth/login", json={"email": "wrong@meander.com", "password": "wrongpass"})
    data = response.json()
    assert data["success"] is False
    assert "Invalid" in data["error"]


def test_login_nonexistent_user():
    response = client.post("/api/auth/login", json={"email": "nobody@meander.com", "password": "pass"})
    data = response.json()
    assert data["success"] is False


def test_get_me_authenticated():
    user = _create_user(roles=["admin"])
    response = client.get("/api/auth/me", headers=_auth_headers(user))
    data = response.json()
    assert data["success"] is True
    assert data["data"]["email"] == user.email
    assert "admin" in data["data"]["roles"]


def test_get_me_unauthenticated():
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_change_password():
    user = _create_user(password="oldpass")
    headers = _auth_headers(user)
    response = client.put(
        "/api/auth/me/password",
        json={"current_password": "oldpass", "new_password": "newpass"},
        headers=headers,
    )
    data = response.json()
    assert data["success"] is True

    # Login with new password
    response = client.post("/api/auth/login", json={"email": user.email, "password": "newpass"})
    assert response.json()["success"] is True


# ── Role enforcement tests ───────────────────────────────────


def test_admin_can_list_users():
    admin = _create_user(roles=["admin"])
    response = client.get("/api/users", headers=_auth_headers(admin))
    assert response.json()["success"] is True


def test_creator_cannot_list_users():
    creator = _create_user(roles=["creator"])
    response = client.get("/api/users", headers=_auth_headers(creator))
    assert response.status_code == 403


def test_reviewer_cannot_list_users():
    reviewer = _create_user(roles=["reviewer"])
    response = client.get("/api/users", headers=_auth_headers(reviewer))
    assert response.status_code == 403


# ── User management tests ───────────────────────────────────


def test_admin_create_user():
    admin = _create_user(roles=["admin"])
    response = client.post(
        "/api/users",
        json={
            "email": "new@meander.com",
            "full_name": "New User",
            "password": "newpass123",
            "roles": ["creator", "reviewer"],
        },
        headers=_auth_headers(admin),
    )
    data = response.json()
    assert data["success"] is True
    assert data["data"]["email"] == "new@meander.com"
    assert "creator" in data["data"]["roles"]


def test_admin_update_user_roles():
    admin = _create_user(roles=["admin"])
    target = _create_user(roles=["creator"])
    response = client.put(
        f"/api/users/{target.id}",
        json={"roles": ["creator", "reviewer"]},
        headers=_auth_headers(admin),
    )
    data = response.json()
    assert data["success"] is True
    assert "reviewer" in data["data"]["roles"]


def test_admin_soft_delete_user():
    admin = _create_user(roles=["admin"])
    target = _create_user(roles=["creator"])
    response = client.delete(f"/api/users/{target.id}", headers=_auth_headers(admin))
    data = response.json()
    assert data["success"] is True
    assert "deactivated" in data["data"]["message"]


def test_list_reviewers():
    admin = _create_user(roles=["admin"])
    _create_user(roles=["reviewer"], email="rev1@meander.com")
    _create_user(roles=["creator"], email="creator1@meander.com")

    response = client.get("/api/users/reviewers", headers=_auth_headers(admin))
    data = response.json()
    assert data["success"] is True
    # Should include the reviewer and the admin (admins are also reviewers)
    emails = [u["email"] for u in data["data"]["items"]]
    assert "rev1@meander.com" in emails
