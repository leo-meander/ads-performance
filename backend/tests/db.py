"""The one test database every test module shares.

Previously each test module built its own engine against its own sqlite file
and assigned ``app.dependency_overrides[get_db]`` at import time. Because
``app`` is a process-wide singleton, the last module pytest imported silently
won that override for the entire session, so every other module's tests ran
against a foreign database. Modules passed alone and failed together.

There is now exactly one engine, and ``conftest.py`` owns the override.

Importing ``app.models`` is load-bearing: ``Base.metadata`` must know every
table before ``create_all``, or cross-module foreign keys (combo_approvals ->
creative_hypotheses, for one) raise NoReferencedTableError.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register every table before create_all

# In-memory + StaticPool: one connection reused by the whole process, so the
# TestClient's request thread sees the same database the test seeded.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
