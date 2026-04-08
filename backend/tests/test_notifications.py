"""Tests for notification system."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.notification import Notification
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password

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
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_user(roles=None, email=None):
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=email or f"user_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Test User",
        password_hash=hash_password("pass"),
        roles=roles or ["creator"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _create_notification(user_id, type="REVIEW_REQUESTED", is_read=False):
    db = TestSession()
    notif = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        type=type,
        title="Test notification",
        body="Test body",
        is_read=is_read,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    db.close()
    return notif


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.roles or [])}"}


# ── Tests ────────────────────────────────────────────────────


def test_list_notifications():
    user = _create_user()
    _create_notification(user.id)
    _create_notification(user.id, is_read=True)

    resp = client.get("/api/notifications", headers=_auth_headers(user))
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["total"] == 2
    assert data["data"]["unread_count"] == 1


def test_list_notifications_filter_unread():
    user = _create_user()
    _create_notification(user.id)
    _create_notification(user.id, is_read=True)

    resp = client.get("/api/notifications?is_read=false", headers=_auth_headers(user))
    data = resp.json()
    assert data["data"]["total"] == 1


def test_mark_notification_read():
    user = _create_user()
    notif = _create_notification(user.id)

    resp = client.put(f"/api/notifications/{notif.id}/read", headers=_auth_headers(user))
    assert resp.json()["success"] is True

    # Verify it's read
    resp = client.get("/api/notifications", headers=_auth_headers(user))
    assert resp.json()["data"]["unread_count"] == 0


def test_mark_all_read():
    user = _create_user()
    _create_notification(user.id)
    _create_notification(user.id)
    _create_notification(user.id)

    resp = client.put("/api/notifications/read-all", headers=_auth_headers(user))
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["count"] == 3

    # Verify all read
    resp = client.get("/api/notifications", headers=_auth_headers(user))
    assert resp.json()["data"]["unread_count"] == 0


def test_notifications_isolated_by_user():
    user1 = _create_user()
    user2 = _create_user()
    _create_notification(user1.id)
    _create_notification(user2.id)

    resp = client.get("/api/notifications", headers=_auth_headers(user1))
    assert resp.json()["data"]["total"] == 1


def test_unauthenticated_cannot_access():
    resp = client.get("/api/notifications")
    assert resp.status_code == 401
