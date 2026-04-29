-- ============================================================================
-- NEXUS — REMAINING SCHEMA (single-shot, idempotent)
-- ============================================================================
-- Run this ENTIRE file in Supabase SQL Editor → New Query → paste → Run.
-- It is 100% safe to re-run; every CREATE uses IF NOT EXISTS / IF NOT EXISTS
-- guards, and ALTER TABLE statements use ADD COLUMN IF NOT EXISTS.
--
-- This file fixes the previous "type vector does not exist" error by
-- enabling pgvector FIRST, then running the multi-tenant schema.
-- ============================================================================

-- ── STEP 1 — Required extensions (must come before any VECTOR column) ──────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";


-- ============================================================================
-- STEP 2 — nexus_users (multi-tenant identity table)
-- ============================================================================
CREATE TABLE IF NOT EXISTS nexus_users (
    user_id          BIGSERIAL PRIMARY KEY,
    telegram_id      BIGINT      NOT NULL UNIQUE,
    telegram_handle  TEXT,
    display_name     TEXT,
    role             TEXT        NOT NULL DEFAULT 'PENDING'
                                 CHECK (role IN ('ADMIN','POWER_USER','STANDARD_USER','PENDING','REVOKED')),
    auto_apply_on    BOOLEAN     NOT NULL DEFAULT FALSE,
    cv_text_encrypted TEXT,
    cv_embedding     VECTOR(1024),
    cv_uploaded_at   TIMESTAMPTZ,
    cv_filename      TEXT,
    cv_sha256        TEXT,
    profile          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    rate_limit_per_min INT        NOT NULL DEFAULT 30,
    rate_limit_apply_per_hour INT NOT NULL DEFAULT 10,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_role ON nexus_users (role);
CREATE INDEX IF NOT EXISTS idx_users_cv_embedding ON nexus_users
    USING ivfflat (cv_embedding vector_cosine_ops) WITH (lists = 50);


-- ============================================================================
-- STEP 3 — access_grants
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
-- STEP 4 — cv_uploads
-- ============================================================================
CREATE TABLE IF NOT EXISTS cv_uploads (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    filename        TEXT,
    sha256          TEXT,
    size_bytes      INT,
    parsed_chars    INT,
    parse_engine    TEXT        NOT NULL DEFAULT 'pypdf',
    embedding_model TEXT        NOT NULL DEFAULT 'groq-text-embedding-3-large',
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cv_uploads_user ON cv_uploads (user_id, uploaded_at DESC);


-- ============================================================================
-- STEP 5 — Migrate single-tenant job_scores → multi-tenant
-- ============================================================================
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
    routing          TEXT        NOT NULL,
    scored_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_breakdown    JSONB,
    user_action      TEXT,
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
-- STEP 6 — user_dimension_weights (Bayesian per-user reweighting)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_dimension_weights (
    user_id        BIGINT       NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    dimension      TEXT         NOT NULL,
    weight         NUMERIC      NOT NULL DEFAULT 0.0,
    sample_size    INT          NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, dimension)
);


-- ============================================================================
-- STEP 7 — Extend job_queue with multi-tenant + priority columns
-- ============================================================================
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS user_id        BIGINT REFERENCES nexus_users(user_id) ON DELETE CASCADE;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS role_boost     INT NOT NULL DEFAULT 0;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS priority_score INT NOT NULL DEFAULT 0;
ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS source         TEXT NOT NULL DEFAULT 'auto';

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
-- STEP 8 — Extend applied_jobs with user_id
-- ============================================================================
ALTER TABLE applied_jobs ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES nexus_users(user_id) ON DELETE SET NULL;

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
-- STEP 9 — session_vault per-user FK
-- ============================================================================
ALTER TABLE session_vault ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES nexus_users(user_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_vault_user_portal ON session_vault (user_id, portal);


-- ============================================================================
-- STEP 10 — audit_log
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    BIGINT REFERENCES nexus_users(user_id) ON DELETE SET NULL,
    actor_role  TEXT,
    action      TEXT NOT NULL,
    target_id   BIGINT,
    target_kind TEXT,
    target_ref  TEXT,
    payload     JSONB,
    ip          INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_actor  ON audit_log (actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action,   created_at DESC);


-- ============================================================================
-- STEP 11 — rate_limit_buckets
-- ============================================================================
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    user_id     BIGINT      NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    bucket      TEXT        NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    counter     INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, bucket, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rate_user_bucket ON rate_limit_buckets (user_id, bucket, window_start DESC);


-- ============================================================================
-- STEP 12 — callback_tokens (HMAC-signed Telegram inline buttons)
-- ============================================================================
CREATE TABLE IF NOT EXISTS callback_tokens (
    token       TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES nexus_users(user_id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    target      TEXT,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_callback_user_expires ON callback_tokens (user_id, expires_at);


-- ============================================================================
-- STEP 13 — Dashboard views
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
-- STEP 14 — Bootstrap super-admin (idempotent — safe to re-run)
-- ============================================================================
INSERT INTO nexus_users (telegram_id, telegram_handle, display_name, role, auto_apply_on, profile)
VALUES (1284690336, 'abuzarkhan999', 'MD Abuzar Salim', 'ADMIN', TRUE, '{"is_super_admin": true}'::jsonb)
ON CONFLICT (telegram_id) DO UPDATE
   SET role = 'ADMIN',
       auto_apply_on = TRUE,
       profile = nexus_users.profile || '{"is_super_admin": true}'::jsonb;


-- ============================================================================
-- DONE.  Verify by running:
--   SELECT count(*) FROM nexus_users;        -- should be >= 1
--   SELECT count(*) FROM job_scores;         -- should be 0 (table exists)
--   \d nexus_users                           -- shows cv_embedding VECTOR(1024)
-- ============================================================================
