"""landing_pages: add ver column for manual version override

Revision ID: 063_landing_page_ver
Revises: 062_lp_ad_link_adset
Create Date: 2026-07-17

Allows editors to pin a landing page to a specific version label
(e.g. "Version 1", "Version 2", "Version 3") directly instead of
relying solely on the slug-pattern heuristic in version_overview.
When set, this value takes precedence over the pattern match.
NULL = fall back to pattern heuristic (existing behaviour).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "063_landing_page_ver"
down_revision: Union[str, None] = "062_lp_ad_link_adset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE landing_pages ADD COLUMN IF NOT EXISTS ver VARCHAR(30)"
    ))


def downgrade() -> None:
    op.drop_column("landing_pages", "ver")
