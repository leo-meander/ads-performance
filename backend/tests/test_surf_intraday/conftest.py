"""Shared fixtures for the SURF intraday test suite.

Provides a per-test SQLite session that fully exercises the ORM models +
constraints from migration 043. The schema itself is created and dropped per
test by the root tests/conftest.py, against the one shared engine.
"""

import pytest

from tests.db import TestSession


@pytest.fixture
def db():
    s = TestSession()
    try:
        yield s
    finally:
        s.close()
