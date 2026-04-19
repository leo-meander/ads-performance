-- Migration 013 — Meta Ads playbook recommendation engine tables
-- Paste this entire file into the Supabase SQL editor. Safe to run multiple
-- times thanks to IF NOT EXISTS everywhere and a conditional alembic_version
-- bump at the bottom.
--
-- Mirrors the Google Ads recommendation table (011) but with Meta-specific
-- columns: ad_set_id replaces ad_group_id/asset_group_id, funnel_stage and
-- targeted_country are stored so the UI can filter per-branch / per-country.
-- Seasonality events are shared with Google — no separate table.

BEGIN;

SET LOCAL statement_timeout = 0;

-- ── meta_recommendations ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meta_recommendations (
    id                 VARCHAR(36) PRIMARY KEY,
    rec_type           VARCHAR(80)  NOT NULL,
    severity           VARCHAR(16)  NOT NULL,
    status             VARCHAR(20)  NOT NULL DEFAULT 'pending',

    account_id         VARCHAR(36)  NOT NULL REFERENCES ad_accounts(id) ON DELETE CASCADE,
    campaign_id        VARCHAR(36)  REFERENCES campaigns(id)  ON DELETE CASCADE,
    ad_set_id          VARCHAR(36)  REFERENCES ad_sets(id)    ON DELETE CASCADE,
    ad_id              VARCHAR(36)  REFERENCES ads(id)        ON DELETE CASCADE,

    entity_level       VARCHAR(20)  NOT NULL,
    funnel_stage       VARCHAR(10),
    targeted_country   VARCHAR(2),

    title              VARCHAR(300) NOT NULL,
    detector_finding   JSON         NOT NULL,
    metrics_snapshot   JSON         NOT NULL,
    ai_reasoning       TEXT,
    ai_confidence      NUMERIC(3,2),
    suggested_action   JSON         NOT NULL,
    auto_applicable    BOOLEAN      NOT NULL,
    warning_text       TEXT         NOT NULL,
    sop_reference      VARCHAR(40),

    dedup_key          VARCHAR(180) NOT NULL,
    expires_at         TIMESTAMPTZ  NOT NULL,

    applied_at         TIMESTAMPTZ,
    applied_by         VARCHAR(36),
    dismissed_at       TIMESTAMPTZ,
    dismissed_by       VARCHAR(36),
    dismiss_reason     TEXT,

    action_log_id      VARCHAR(36)  REFERENCES action_logs(id) ON DELETE SET NULL,
    source_task_id     VARCHAR(80),

    created_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Single-column indexes
CREATE INDEX IF NOT EXISTS ix_meta_recs_rec_type         ON meta_recommendations (rec_type);
CREATE INDEX IF NOT EXISTS ix_meta_recs_severity         ON meta_recommendations (severity);
CREATE INDEX IF NOT EXISTS ix_meta_recs_status           ON meta_recommendations (status);
CREATE INDEX IF NOT EXISTS ix_meta_recs_account_id       ON meta_recommendations (account_id);
CREATE INDEX IF NOT EXISTS ix_meta_recs_campaign_id      ON meta_recommendations (campaign_id);
CREATE INDEX IF NOT EXISTS ix_meta_recs_ad_set_id        ON meta_recommendations (ad_set_id);
CREATE INDEX IF NOT EXISTS ix_meta_recs_ad_id            ON meta_recommendations (ad_id);
CREATE INDEX IF NOT EXISTS ix_meta_recs_funnel_stage     ON meta_recommendations (funnel_stage);
CREATE INDEX IF NOT EXISTS ix_meta_recs_targeted_country ON meta_recommendations (targeted_country);
CREATE INDEX IF NOT EXISTS ix_meta_recs_dedup_key        ON meta_recommendations (dedup_key);

-- Composite indexes (match the ones in the alembic migration)
CREATE INDEX IF NOT EXISTS ix_meta_recs_account_status_severity
    ON meta_recommendations (account_id, status, severity);
CREATE INDEX IF NOT EXISTS ix_meta_recs_campaign_status
    ON meta_recommendations (campaign_id, status);
CREATE INDEX IF NOT EXISTS ix_meta_recs_rec_type_status
    ON meta_recommendations (rec_type, status);

-- Partial unique index: at most one pending recommendation per dedup_key
CREATE UNIQUE INDEX IF NOT EXISTS uq_meta_recs_dedup_pending
    ON meta_recommendations (dedup_key)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ix_meta_recs_expires_pending
    ON meta_recommendations (expires_at)
    WHERE status = 'pending';

-- ── Bump alembic_version to 013 ──────────────────────────────────────────
-- Conditional: only bump if the currently recorded head is 012. If you are
-- re-running this file after the version already moved to 013, this block
-- becomes a no-op.
UPDATE alembic_version
   SET version_num = '013_meta_recommendations'
 WHERE version_num = '012_seasonality_country_code';

COMMIT;
