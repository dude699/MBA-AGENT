-- ============================================================================
-- NEXUS v0.2 — Supabase / Postgres Schema
-- ============================================================================
-- Author : MD Abuzar Salim · 25IBMMA143
-- Date   : April 2026
-- Target : Supabase Free (500 MB, pgvector enabled)
--
-- Layer mapping:
--   Layer 0  → session_vault, session_health_log
--   Layer 2  → jobs, job_queue, scrape_log
--   Layer 3  → job_scores, profile_embeddings
--   Layer 4  → answer_bank
--   Layer 5  → captcha_events
--   Layer 6  → orchestrator_state, risk_governor_log
--   Layer 7  → applied_jobs (semantic dedup via pgvector)
--   Layer 8  → interview_signals, briefing_cache
--   Layer 9  → telegram_audit
--   Innov.   → portal_health, skyvern_code_cache, resume_variants
-- ============================================================================

-- ── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";        -- pgvector (semantic dedup + RAG)


-- ============================================================================
-- LAYER 0 — Cryptographic Credential Vault + Session Freshness Oracle
-- ============================================================================
CREATE TABLE IF NOT EXISTS session_vault (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portal             TEXT NOT NULL,                          -- linkedin, internshala, naukri…
    user_handle        TEXT NOT NULL,                          -- abuzar_salim
    encrypted_cookies  TEXT NOT NULL,                          -- AES-256 (Supabase Vault key)
    encrypted_storage  TEXT,                                   -- localStorage / sessionStorage blob
    device_fingerprint JSONB NOT NULL,                         -- Camoufox config (UA, screen, tz, WebGL, fonts…)
    fingerprint_hash   TEXT GENERATED ALWAYS AS (md5(device_fingerprint::text)) STORED,
    apparent_ip        INET,                                   -- IP via CF Worker proxy
    health_score       INT NOT NULL DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
    captured_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at       TIMESTAMPTZ,
    last_refreshed_at  TIMESTAMPTZ DEFAULT now(),
    decay_curve        TEXT NOT NULL DEFAULT 'linear_90d',     -- linear_90d | steep_30d
    revoked            BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (portal, user_handle)
);
CREATE INDEX IF NOT EXISTS idx_vault_portal_health ON session_vault (portal, health_score);

CREATE TABLE IF NOT EXISTS session_health_log (
    id            BIGSERIAL PRIMARY KEY,
    vault_id      UUID REFERENCES session_vault(id) ON DELETE CASCADE,
    portal        TEXT NOT NULL,
    health_before INT,
    health_after  INT,
    reason        TEXT,                                       -- decay_tick | apply_ok | apply_fail | captcha | refresh
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_health_log_vault ON session_health_log (vault_id, created_at DESC);


-- ============================================================================
-- LAYER 2 — Universal Job Discovery
-- ============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,                            -- portal:hash
    portal        TEXT NOT NULL,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    remote        BOOLEAN DEFAULT FALSE,
    stipend_inr_monthly INT,                                   -- normalised by Innovation 13
    stipend_raw   TEXT,                                        -- whatever the portal said
    deadline      TIMESTAMPTZ,
    posted_at     TIMESTAMPTZ NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    discovery_mode TEXT NOT NULL DEFAULT 'cron',               -- cron | reactive_rss | reactive_webhook
    jd_text       TEXT NOT NULL,
    jd_embedding  VECTOR(1024),                                -- Groq embeddings (1024 dim)
    raw_url       TEXT NOT NULL,
    applicant_count INT,                                       -- Innovation 7
    raw_payload   JSONB
);
CREATE INDEX IF NOT EXISTS idx_jobs_portal_posted ON jobs (portal, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs (company);
CREATE INDEX IF NOT EXISTS idx_jobs_jd_embedding ON jobs USING ivfflat (jd_embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS scrape_log (
    id          BIGSERIAL PRIMARY KEY,
    portal      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    jobs_found  INT DEFAULT 0,
    jobs_new    INT DEFAULT 0,
    mode        TEXT NOT NULL DEFAULT 'cron',
    status      TEXT NOT NULL DEFAULT 'running',               -- running | ok | failed
    error       TEXT
);


-- ============================================================================
-- LAYER 3 — Multi-Dimensional Scoring (9 dimensions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_scores (
    job_id            TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    profile_match     INT,    -- 0..100 (pgvector cosine)
    compensation_fit  INT,
    role_type_match   INT,
    company_tier      INT,
    location_fit      INT,
    recency           INT,
    competitive_pos   INT,    -- Innovation 7
    cultural_fit      INT,    -- NEW v0.2
    trajectory        INT,    -- NEW v0.2 (Crawl4AI news → Cerebras sentiment)
    final_score       INT NOT NULL,
    routing           TEXT NOT NULL,   -- AUTO_APPLY | MANUAL_REVIEW | REJECT
    scored_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_breakdown     JSONB
);
CREATE INDEX IF NOT EXISTS idx_scores_routing ON job_scores (routing, final_score DESC);

CREATE TABLE IF NOT EXISTS profile_embeddings (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_handle  TEXT NOT NULL,
    profile_text TEXT NOT NULL,
    embedding    VECTOR(1024) NOT NULL,
    variant      TEXT NOT NULL DEFAULT 'master',              -- master | ai_tech | finance | ib | generalist
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_profile_emb ON profile_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);


-- ============================================================================
-- LAYER 4 — Adaptive Answer Generation (RAG)
-- ============================================================================
CREATE TABLE IF NOT EXISTS answer_bank (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_handle     TEXT NOT NULL,
    question_text   TEXT NOT NULL,
    question_embedding VECTOR(1024) NOT NULL,
    answer_text     TEXT NOT NULL,
    company         TEXT,
    role            TEXT,
    portal          TEXT,
    word_count      INT,
    quality_score   INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_answer_emb ON answer_bank USING ivfflat (question_embedding vector_cosine_ops) WITH (lists = 100);


-- ============================================================================
-- LAYER 5 — CAPTCHA event log
-- ============================================================================
CREATE TABLE IF NOT EXISTS captcha_events (
    id          BIGSERIAL PRIMARY KEY,
    job_id      TEXT REFERENCES jobs(job_id) ON DELETE SET NULL,
    portal      TEXT NOT NULL,
    tier        TEXT NOT NULL,         -- T1 | T2 | T3 | T4
    method      TEXT NOT NULL,         -- gemini_vision | groq_whisper | telegram_relay | skyvern_surgical
    duration_ms INT,
    solved      BOOLEAN NOT NULL,
    fallback_to TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_captcha_portal_recent ON captcha_events (portal, created_at DESC);


-- ============================================================================
-- LAYER 6 — Orchestrator (priority queue + Risk Governor)
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_queue (
    id                  BIGSERIAL PRIMARY KEY,
    job_id              TEXT NOT NULL UNIQUE REFERENCES jobs(job_id) ON DELETE CASCADE,
    portal              TEXT NOT NULL,
    score               INT NOT NULL,
    deadline_urgency    INT NOT NULL DEFAULT 0,
    apply_window_open   BOOLEAN NOT NULL DEFAULT TRUE,
    risk_level          TEXT NOT NULL DEFAULT 'LOW',          -- LOW | MED | HIGH
    state               TEXT NOT NULL DEFAULT 'QUEUED',       -- QUEUED | DISPATCHING | RUNNING | DONE | FAILED | HELD
    attempts            INT NOT NULL DEFAULT 0,
    last_error          TEXT,
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    rescore_at          TIMESTAMPTZ NOT NULL DEFAULT now() + interval '2 hours',
    dispatch_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_queue_state_score ON job_queue (state, score DESC, deadline_urgency DESC);
CREATE INDEX IF NOT EXISTS idx_queue_rescore ON job_queue (rescore_at) WHERE state = 'QUEUED';

CREATE TABLE IF NOT EXISTS risk_governor_log (
    id          BIGSERIAL PRIMARY KEY,
    portal      TEXT NOT NULL,
    signal      TEXT NOT NULL,         -- apps_per_hour | captcha_rate | session_age | error_rate | tod_variance
    value       NUMERIC,
    threshold   NUMERIC,
    action      TEXT NOT NULL,         -- THROTTLE | PAUSE | NOTIFY | NORMALISE
    portal_paused BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_risk_portal_recent ON risk_governor_log (portal, created_at DESC);

CREATE TABLE IF NOT EXISTS orchestrator_state (
    portal              TEXT PRIMARY KEY,
    paused              BOOLEAN NOT NULL DEFAULT FALSE,
    paused_reason       TEXT,
    paused_until        TIMESTAMPTZ,
    rate_multiplier     NUMERIC NOT NULL DEFAULT 1.0,
    last_apply_at       TIMESTAMPTZ,
    apply_window_spec   JSONB                                  -- e.g. [{from:"07:00",to:"11:00"},{from:"15:00",to:"19:00"}]
);


-- ============================================================================
-- LAYER 7 — Applied jobs (semantic dedup source-of-truth)
-- ============================================================================
CREATE TABLE IF NOT EXISTS applied_jobs (
    id                BIGSERIAL PRIMARY KEY,
    job_id            TEXT UNIQUE REFERENCES jobs(job_id) ON DELETE SET NULL,
    portal            TEXT NOT NULL,
    company           TEXT NOT NULL,
    title             TEXT NOT NULL,
    title_hash        TEXT NOT NULL,                          -- SHA256 of normalised title
    jd_embedding      VECTOR(1024),                           -- redundant with jobs but kept for fast dedup RPC
    resume_variant    TEXT NOT NULL DEFAULT 'master',
    answers_used      JSONB,
    submission_status TEXT NOT NULL,                          -- SUCCESS | FAILED | CAPTCHA_NEEDED
    skyvern_code_used BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms       INT,
    applied_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    recruiter_viewed  BOOLEAN NOT NULL DEFAULT FALSE,         -- Innovation 12
    recruiter_viewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_applied_company_title ON applied_jobs (company, title_hash);
CREATE INDEX IF NOT EXISTS idx_applied_jd_emb ON applied_jobs USING ivfflat (jd_embedding vector_cosine_ops) WITH (lists = 100);


-- pgvector RPC used by Layer 7 dedup engine
CREATE OR REPLACE FUNCTION find_similar_jds(
    query_embedding VECTOR(1024),
    company         TEXT,
    threshold       FLOAT DEFAULT 0.88,
    days_back       INT DEFAULT 60
)
RETURNS TABLE (job_id TEXT, similarity FLOAT)
LANGUAGE sql STABLE
AS $$
    SELECT a.job_id,
           1 - (a.jd_embedding <=> query_embedding) AS similarity
    FROM applied_jobs a
    WHERE a.company = $2
      AND a.applied_at > now() - ($4 || ' days')::interval
      AND a.jd_embedding IS NOT NULL
      AND 1 - (a.jd_embedding <=> $1) >= $3
    ORDER BY similarity DESC
    LIMIT 5;
$$;


-- ============================================================================
-- LAYER 8 — Interview Intelligence
-- ============================================================================
CREATE TABLE IF NOT EXISTS interview_signals (
    id            BIGSERIAL PRIMARY KEY,
    company       TEXT NOT NULL,
    role          TEXT,
    source        TEXT NOT NULL,         -- gmail | linkedin | whatsapp
    signal_type   TEXT NOT NULL,         -- INTERVIEW_INVITE | TEST_LINK | OFFER | REJECTION | GENERIC
    raw_subject   TEXT,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    briefing_ready BOOLEAN NOT NULL DEFAULT FALSE,
    briefing_id   UUID,
    user_acked    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS briefing_cache (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company         TEXT NOT NULL,
    snapshot        TEXT,
    recent_news     JSONB,
    glassdoor_intel TEXT,
    likely_questions JSONB,
    draft_reply     TEXT,
    application_id  BIGINT REFERENCES applied_jobs(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_briefing_company ON briefing_cache (company, created_at DESC);


-- ============================================================================
-- LAYER 9 — Telegram audit (commands + button taps)
-- ============================================================================
CREATE TABLE IF NOT EXISTS telegram_audit (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    command     TEXT,
    button_data TEXT,
    payload     JSONB,
    response    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ============================================================================
-- INNOVATIONS — supporting tables
-- ============================================================================
-- Innovation 2: Skyvern code cache (per-portal, per-task)
CREATE TABLE IF NOT EXISTS skyvern_code_cache (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portal        TEXT NOT NULL,
    task_kind     TEXT NOT NULL,         -- apply | profile_save | search
    code_blob     TEXT NOT NULL,
    code_hash     TEXT NOT NULL,
    success_count INT NOT NULL DEFAULT 0,
    fail_count    INT NOT NULL DEFAULT 0,
    last_ok_at    TIMESTAMPTZ,
    last_fail_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (portal, task_kind)
);

-- Innovation 8: Multi-resume variants
CREATE TABLE IF NOT EXISTS resume_variants (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_handle  TEXT NOT NULL,
    variant      TEXT NOT NULL,          -- ai_tech | finance | ib | generalist
    file_url     TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_handle, variant)
);

-- Innovation 9: Portal Health Benchmarking
CREATE TABLE IF NOT EXISTS portal_health (
    portal               TEXT PRIMARY KEY,
    apps_sent_4w         INT NOT NULL DEFAULT 0,
    callbacks_4w         INT NOT NULL DEFAULT 0,
    callback_rate        NUMERIC GENERATED ALWAYS AS (
        CASE WHEN apps_sent_4w = 0 THEN 0 ELSE callbacks_4w::numeric / apps_sent_4w END
    ) STORED,
    captcha_rate_4w      NUMERIC NOT NULL DEFAULT 0,
    avg_apply_ms         INT,
    last_benchmarked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    scrape_freq_minutes  INT NOT NULL DEFAULT 60               -- auto-reweighted
);


-- ============================================================================
-- VIEWS — quick dashboards for /portal_status, /nexus, /analytics
-- ============================================================================
CREATE OR REPLACE VIEW v_portal_overview AS
SELECT
    s.portal,
    s.health_score                        AS session_health,
    COALESCE(o.paused, FALSE)             AS paused,
    COALESCE(o.rate_multiplier, 1.0)      AS rate_multiplier,
    COALESCE(p.callback_rate, 0)          AS callback_rate_4w,
    (SELECT count(*) FROM job_queue q WHERE q.portal = s.portal AND q.state = 'QUEUED') AS queued_jobs,
    s.last_used_at
FROM session_vault s
LEFT JOIN orchestrator_state o ON o.portal = s.portal
LEFT JOIN portal_health p ON p.portal = s.portal;


CREATE OR REPLACE VIEW v_funnel_7d AS
SELECT
    portal,
    count(*) FILTER (WHERE submission_status = 'SUCCESS')  AS applied,
    count(*) FILTER (WHERE recruiter_viewed)               AS viewed,
    count(*) FILTER (WHERE submission_status = 'FAILED')   AS failed
FROM applied_jobs
WHERE applied_at > now() - interval '7 days'
GROUP BY portal;


-- ============================================================================
-- DONE — apply with:  psql $DATABASE_URL -f data/nexus_v02_schema.sql
-- ============================================================================
