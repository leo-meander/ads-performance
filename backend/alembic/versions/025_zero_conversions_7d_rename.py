"""Rename rec_type ZERO_CONVERSIONS_2D -> ZERO_CONVERSIONS_7D.

Revision ID: 025_zero_conversions_7d_rename
Revises: 024_campaigns_country
Create Date: 2026-04-29

The detector threshold moved from 2 consecutive zero-conversion days to 7
consecutive days. Update existing rec_type and dedup_key values so historical
rows stay queryable under the new key. Idempotent: WHERE clauses make
re-running a no-op.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "025_zero_conversions_7d_rename"
down_revision: Union[str, None] = "024_campaigns_country"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE google_recommendations
        SET dedup_key = REPLACE(dedup_key, 'ZERO_CONVERSIONS_2D:', 'ZERO_CONVERSIONS_7D:')
        WHERE rec_type = 'ZERO_CONVERSIONS_2D'
        """
    )
    op.execute(
        """
        UPDATE google_recommendations
        SET rec_type = 'ZERO_CONVERSIONS_7D'
        WHERE rec_type = 'ZERO_CONVERSIONS_2D'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE google_recommendations
        SET rec_type = 'ZERO_CONVERSIONS_2D'
        WHERE rec_type = 'ZERO_CONVERSIONS_7D'
        """
    )
    op.execute(
        """
        UPDATE google_recommendations
        SET dedup_key = REPLACE(dedup_key, 'ZERO_CONVERSIONS_7D:', 'ZERO_CONVERSIONS_2D:')
        WHERE rec_type = 'ZERO_CONVERSIONS_2D'
        """
    )
