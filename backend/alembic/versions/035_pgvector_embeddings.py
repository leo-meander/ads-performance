"""Creative Intelligence Phase 2 — pgvector + embedding columns.

Revision ID: 035_pgvector_embeddings
Revises: 034_creative_visual_tags
Create Date: 2026-05-13

Enables the pgvector extension on Postgres and adds 1024-dim embedding
columns + bookkeeping (embedded_at, embedding_model) to ad_combos,
ad_copies, and ad_materials. The dimension matches Voyage AI's
voyage-3-large output.

Indexes are deliberately NOT created here — IVFFLAT/HNSW indexes need data
to choose their partitioning. We add them in a follow-up after the first
backfill embeds the existing rows. Brute-force cosine search up to ~50k
rows is fast enough on Supabase.

SQLite test path skips the vector column entirely (the embedding service
short-circuits when settings.VOYAGE_API_KEY is empty, which is the test
default). pgvector has no SQLite analog.

Idempotent: CREATE EXTENSION / ADD COLUMN IF NOT EXISTS on Postgres.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "035_pgvector_embeddings"
down_revision: Union[str, None] = "034_creative_visual_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Voyage voyage-3-large emits 1024-dim float vectors.
EMBED_DIM = 1024


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if not is_postgres:
        # SQLite tests don't need the vector column — embedding service is a
        # no-op when VOYAGE_API_KEY is empty. Skip cleanly so test setUp works.
        return

    # 1) Enable pgvector. Idempotent on every Postgres ≥13.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2) Embedding column + bookkeeping on each table that participates in
    #    semantic search. Voyage embedding strings are stored as the pgvector
    #    'vector' type so cosine ops work without casts.
    for table in ("ad_combos", "ad_copies", "ad_materials"):
        op.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN IF NOT EXISTS embedding vector({EMBED_DIM});"
        )
        op.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;"
        )
        op.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(40);"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_embedded_at "
            f"ON {table} (embedded_at);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if not is_postgres:
        return

    for table in ("ad_combos", "ad_copies", "ad_materials"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedded_at;")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding_model;")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedded_at;")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding;")

    # NOTE: We deliberately do NOT drop the pgvector extension — other
    # Supabase apps in the same project may share it.
