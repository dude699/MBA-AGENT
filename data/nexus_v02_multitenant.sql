-- ============================================================================
-- NEXUS v0.2 — Multi-Tenant Extension Schema
-- ============================================================================
-- Author : MD Abuzar Salim · 25IBMMA143
-- Date   : April 2026
-- Target : Supabase (Postgres + pgvector)
--
-- This file extends data/nexus_v02_schema.sql with the tables required for
-- multi-tenant operation: per-user CVs, per-user job scores, RBAC grants,
-- audit log, and the priority/role columns added to the queue + applied_jobs.
--
-- Apply AFTER nexus_v02_schema.sql:
--   psql $DATABASE_URL -f data/nexus_v02_schema.sql
--   psql $DATABASE_URL -f data/nexus_v02_multitenant.sql
--
-- Idempotent: every CREATE/ALTER uses IF NOT EXISTS / IF EXISTS guards.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ============================================================================
-- USERS — every Telegram user who interacts with the bot
-- ============================================================================
CREATE TABLE IF NOT EXISTS nexus_users (
    user_id          BIGSERIAL PRIMARY KEY,
    telegram_id      BIGINT      NOT NULL UNIQUE,
    telegram_handle  TEXT,
    display_name     TEXT,
    role             TEXT        NOT NULL DEFAULT 'PENDING'
                                 CHECK (role IN ('ADMIN','POWER_USER','STANDARD_USER','PENDING','REVOKED')),
    auto_apply_on    BOOLEAN     NOT NULL DEFAULT FALSE,    -- ADMIN/POWER only
    cv_text_encrypted TEXT,                                  -- Fernet AES-256
    cv_embedding     VECTOR(1024),                           -- Groq embedding
    cv_uploaded_at   TIMESTAMPTZ,
    cv_filename      TEXT,
    cv_sha256        TEXT,
    profile          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    rate_limit_per_min INT        NOT NULL DEFAULT 30,
    rate_limit_apply_per_hour INT NOT NULL DEFAULT 10,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_role         ON nexus_users (role);
CREATE INDEX IF NOT EXISTS idx_users_cv_embedding ON nexus_users
    USING ivfflat (cv_embedding vector_cosine_ops) WITH (lists = 50);


-- ============================================================================
-- ACCESS GRANTS — admin-issued capability tokens (audit trail of grants)
-- ============================================================================
CREATE TABLE IF NOT EXISTS access_grants (
    id              BIGSERIAL PRIMARY KEY,
    granted_to      BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    granted_by      BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE RESTRICT,
    role_granted    TEXT        NOT NULL CHECK (role_granted IN ('POWER_USER','STANDARD_USER')),
    reason          TEXT,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ,
    revoked_by      BIGINT REFERENCES nexus_users(user_id) ON DELETE SET NULL,
    revoke_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_grants_to ON access_grants (granted_to, revoked_at);


-- ============================================================================
-- CV UPLOADS — every CV intake event (kept for diff/rollback + analytics)
-- ============================================================================
CREATE TABLE IF NOT EXISTS cv_uploads (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    filename        TEXT,
    sha256          TEXT,
    size_bytes      INT,
    parsed_chars    INT,
    parse_engine    TEXT        NOT NULL DEFAULT 'pypdf',     -- pypdf | pdftotext | docx
    embedding_model TEXT        NOT NULL DEFAULT 'groq-text-embedding-3-large',
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cv_uploads_user ON cv_uploads (user_id, uploaded_at DESC);


-- ============================================================================
-- JOB_SCORES — REPLACE the single-tenant version with a multi-tenant one.
-- ============================================================================
-- The original single-tenant job_scores table (one row per job_id) is
-- preserved by renaming it. The new multi-tenant table is keyed (user_id,job_id).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'job_scores' AND table_schema = current_schema()
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'job_scores' AND column_name = 'user_id'
          AND table_schema = current_schema()
    ) THEN
        ALTER TABLE job_scores RENAME TO job_scores_legacy_single_tenant;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS job_scores (
    user_id          BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    job_id           TEXT        NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    profile_match    INT,
    compensation_fit INT,
    role_type_match  INT,
    company_tier     INT,
    location_fit     INT,
    recency          INT,
    competitive_pos  INT,
    cultural_fit     INT,
    trajectory       INT,
    final_score      INT         NOT NULL,
    routing          TEXT        NOT NULL,         -- AUTO_APPLY | MANUAL_REVIEW | REJECT
    scored_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_breakdown    JSONB,
    -- Usage-pattern learning feedback
    user_action      TEXT,                          -- APPLIED | SKIPPED | SNOOZED | NONE
    user_action_at   TIMESTAMPTZ,
    PRIMARY KEY (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_jscore_user_routing
    ON job_scores (user_id, routing, final_score DESC);
CREATE INDEX IF NOT EXISTS idx_jscore_pending
    ON job_scores (user_id, scored_at DESC)
    WHERE user_action IS NULL;
CREATE INDEX IF NOT EXISTS idx_jscore_unscored_lookup
    ON job_scores (job_id, user_id);


-- ============================================================================
-- USER_DIMENSION_WEIGHTS — Bayesian per-user dimension reweighting (learning)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_dimension_weights (
    user_id        BIGINT       NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    dimension      TEXT         NOT NULL,           -- profile_match | compensation_fit | …
    weight         NUMERIC      NOT NULL DEFAULT 0.0,    -- delta from base SCORING_WEIGHTS
    sample_size    INT          NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, dimension)
);


-- ============================================================================
-- JOB_QUEUE — extend with user_id + priority columns
-- ============================================================================
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS user_id        BIGINT REFERENCES nexus_users(user_id) ON DELETE CASCADE;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS role_boost     INT NOT NULL DEFAULT 0;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS priority_score INT NOT NULL DEFAULT 0;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS source         TEXT NOT NULL DEFAULT 'auto';
                                                              -- auto | tap_apply | force_apply

-- Drop the old UNIQUE constraint on (job_id) since multi-tenant means
-- the same job can be queued for multiple users.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'job_queue'
          AND constraint_type = 'UNIQUE'
          AND constraint_name = 'job_queue_job_id_key'
    ) THEN
        ALTER TABLE job_queue DROP CONSTRAINT job_queue_job_id_key;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_queue_user_job
    ON job_queue (COALESCE(user_id, 0), job_id);

CREATE INDEX IF NOT EXISTS idx_queue_priority
    ON job_queue (state, priority_score DESC, score DESC, deadline_urgency DESC);


-- ============================================================================
-- APPLIED_JOBS — extend with user_id (multi-tenant)
-- ============================================================================
ALTER TABLE applied_jobs ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES nexus_users(user_id) ON DELETE SET NULL;

-- Drop old single-tenant unique-on-job_id constraint (same job_id can be applied
-- by multiple users from their own sessions).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'applied_jobs'
          AND constraint_type = 'UNIQUE'
          AND constraint_name = 'applied_jobs_job_id_key'
    ) THEN
        ALTER TABLE applied_jobs DROP CONSTRAINT applied_jobs_job_id_key;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_applied_user_job
    ON applied_jobs (COALESCE(user_id, 0), job_id);


-- ============================================================================
-- SESSION_VAULT — ensure per-user (already had user_handle, add user_id FK)
-- ============================================================================
ALTER TABLE session_vault ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES nexus_users(user_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_vault_user_portal ON session_vault (user_id, portal);


-- ============================================================================
-- AUDIT_LOG — append-only security audit (admin actions, grants, applies)
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    BIGINT REFERENCES nexus_users(user_id) ON DELETE SET NULL,
    actor_role  TEXT,
    action      TEXT NOT NULL,         -- GRANT_ROLE | REVOKE | AUTO_APPLY | TAP_APPLY | CV_UPLOAD | LOGIN_DENIED | RATE_LIMIT | …
    target_id   BIGINT,                -- user_id of target (when applicable)
    target_kind TEXT,                  -- user | job | portal | session
    target_ref  TEXT,                  -- free-form (job_id, portal name, …)
    payload     JSONB,
    ip          INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_actor   ON audit_log (actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action  ON audit_log (action, created_at DESC);


-- ============================================================================
-- RATE_LIMIT — sliding-window counters per (user, bucket)
-- ============================================================================
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    user_id     BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    bucket      TEXT        NOT NULL,   -- cmd | apply | grant | refresh
    window_start TIMESTAMPTZ NOT NULL,
    counter     INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, bucket, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rate_user_bucket ON rate_limit_buckets (user_id, bucket, window_start DESC);


-- ============================================================================
-- CALLBACK_TOKENS — HMAC-signed Telegram inline-button tokens (anti-spoof)
-- ============================================================================
CREATE TABLE IF NOT EXISTS callback_tokens (
    token       TEXT PRIMARY KEY,           -- short HMAC nonce
    user_id     BIGINT NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    action      TEXT NOT NULL,              -- apply | skip | snooze | grant_user | …
    target      TEXT,                       -- job_id, user_id, portal
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_callback_user_expires ON callback_tokens (user_id, expires_at);


-- ============================================================================
-- VIEWS for the new dashboard
-- ============================================================================
CREATE OR REPLACE VIEW v_user_overview AS
SELECT
    u.user_id,
    u.telegram_id,
    u.telegram_handle,
    u.role,
    u.auto_apply_on,
    (u.cv_embedding IS NOT NULL) AS cv_ready,
    u.cv_uploaded_at,
    (SELECT count(*) FROM job_scores js
       WHERE js.user_id = u.user_id AND js.user_action IS NULL) AS pending_review,
    (SELECT count(*) FROM applied_jobs a
       WHERE a.user_id = u.user_id
         AND a.applied_at > now() - interval '7 days'
         AND a.submission_status = 'SUCCESS') AS applied_7d
FROM nexus_users u
WHERE u.role NOT IN ('PENDING', 'REVOKED');


CREATE OR REPLACE VIEW v_admin_queue AS
SELECT
    q.id,
    q.user_id,
    u.telegram_handle,
    u.role,
    q.job_id,
    j.company,
    j.title,
    q.portal,
    q.score,
    q.role_boost,
    q.priority_score,
    q.deadline_urgency,
    q.state,
    q.source,
    q.queued_at
FROM job_queue q
LEFT JOIN nexus_users u ON u.user_id = q.user_id
LEFT JOIN jobs j        ON j.job_id  = q.job_id
ORDER BY q.priority_score DESC, q.score DESC, q.queued_at ASC;


-- ============================================================================
-- BOOTSTRAP — seed the super-admin (idempotent)
-- ============================================================================
-- Override via env: NEXUS_ADMIN_TELEGRAM_ID. Default = 1284690336.
INSERT INTO nexus_users (telegram_id, telegram_handle, display_name, role, auto_apply_on, profile)
VALUES (1284690336, 'abuzarkhan999', 'MD Abuzar Salim', 'ADMIN', TRUE, '{"is_super_admin": true}'::jsonb)
ON CONFLICT (telegram_id) DO UPDATE
   SET role = 'ADMIN',
       auto_apply_on = TRUE,
       profile = nexus_users.profile || '{"is_super_admin": true}'::jsonb;


-- ============================================================================
-- DONE — apply with:
--   psql $DATABASE_URL -f data/nexus_v02_multitenant.sql
-- ============================================================================
