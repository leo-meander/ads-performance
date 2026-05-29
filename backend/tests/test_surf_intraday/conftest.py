"""Shared fixtures for the SURF intraday test suite.

Provides a per-test SQLite session that fully exercises the ORM models +
constraints from migration 043 via Base.metadata.create_all.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.models.base import Base
# Import ALL models so create_all sees every table. This is the same trick
# the project's other test files use.
from app.models import (  # noqa: F401
    AdAccount, Campaign, SurfRun, SurfCheckpoint, Tactic,
)


_engine = create_engine(
    "sqlite:///./test_surf_intraday.db",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=_engine)
    s = _TestSession()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=_engine)
