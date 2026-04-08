"""Initialize database tables and seed accounts.

For local dev with SQLite. For production, use Alembic migrations.

Usage:
    cd backend
    python -m scripts.init_db
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine
from app.models.base import Base

# Import all models so they register with Base.metadata
from app.models import (  # noqa: F401
    Ad,
    AdAccount,
    AdSet,
    ActionLog,
    AIConversation,
    AutomationRule,
    Campaign,
    MetricsCache,
)
from scripts.seed_accounts import seed


def init():
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")

    # List tables
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nTables in database ({len(tables)}):")
    for t in tables:
        print(f"  - {t}")

    print("\nSeeding accounts...")
    seed()


if __name__ == "__main__":
    init()
