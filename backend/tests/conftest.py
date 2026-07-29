"""Session-wide test fixtures.

Owns the two pieces of global state that made the suite order-dependent:
the database schema and ``app.dependency_overrides[get_db]``. Both are set up
and torn down per test, so no module can leak either onto the next one.
"""
import pytest

from app.database import get_db
from app.main import app
from app.models.base import Base
from tests.db import TestSession, engine


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def db_session():
    """Give every test an empty schema and a live get_db override."""
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
