"""meta_ad_states: per-ad delivery status + shareable preview link

Revision ID: 070_meta_ad_states
Revises: 069_wam_scope
Create Date: 2026-08-17

The Ad Name Performance page could show what an ad spent but not whether it is
still running, and gave no way to look at the creative. Both live on the Meta
Ad object (effective_status, preview_shareable_link) and describe the ad as it
is NOW -- so they cannot be columns on ad_daily_metrics, whose grain is a day.
A pause today would otherwise have to be written back across every past day.

One row per (account_id, ad_id), refreshed by services/meta_ad_state_sync.py
alongside the daily ad-metrics sync.

Id columns are VARCHAR(36), NOT the native UUID type: app.models.base defines
UUIDType = String(36) and ad_accounts.id is a varchar, so a native UUID column
here makes the FK un-creatable. Ids come from TimestampMixin in Python, so no
DB-side default.

Ids stay short -- alembic_version.version_num is VARCHAR(32).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "070_meta_ad_states"
down_revision: Union[str, None] = "069_wam_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_ad_states (
            id               VARCHAR(36) PRIMARY KEY,
            account_id       VARCHAR(36) NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
            ad_id            VARCHAR(64) NOT NULL,
            ad_name          VARCHAR(500),
            status           VARCHAR(40),
            effective_status VARCHAR(40),
            preview_url      VARCHAR(1000),
            synced_at        TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_meta_ad_states_acc_ad UNIQUE (account_id, ad_id)
        );
        CREATE INDEX IF NOT EXISTS ix_mas_account_id  ON meta_ad_states(account_id);
        CREATE INDEX IF NOT EXISTS ix_mas_ad_id       ON meta_ad_states(ad_id);
        CREATE INDEX IF NOT EXISTS ix_mas_eff_status  ON meta_ad_states(effective_status);
        -- The page's pivot grain: every ad sharing a name inside one branch.
        CREATE INDEX IF NOT EXISTS ix_mas_acc_name    ON meta_ad_states(account_id, ad_name);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meta_ad_states;")
