-- ============================================================
-- CV STORAGE — Supabase persistence so CV uploads survive
-- Render's ephemeral filesystem (every redeploy wipes data/).
-- ============================================================
-- Run this ONCE in Supabase SQL Editor:
--   Dashboard → Project → SQL Editor → New Query → paste → Run
--
-- ✅ 100 % NON-DESTRUCTIVE — uses CREATE … IF NOT EXISTS and
-- a guarded DO-block for the trigger so the Supabase SQL editor
-- will NOT show a 'destructive operation' warning when you run
-- this. Safe to re-run as many times as you like.
-- ============================================================

CREATE TABLE IF NOT EXISTS user_cvs (
    telegram_id  TEXT PRIMARY KEY,
    filename     TEXT NOT NULL DEFAULT 'resume.pdf',
    pdf_b64      TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    sha256       TEXT NOT NULL DEFAULT '',
    uploaded_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_cvs_uploaded_at
    ON user_cvs(uploaded_at DESC);

-- updated_at touch function (CREATE OR REPLACE is safe — it does
-- not drop the function, just rewrites the body).
CREATE OR REPLACE FUNCTION user_cvs_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Idempotent trigger creation — only CREATE if it doesn't already
-- exist. This avoids the DROP TRIGGER that triggers Supabase's
-- 'destructive operations' confirmation dialog.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_user_cvs_touch'
    ) THEN
        CREATE TRIGGER trg_user_cvs_touch
        BEFORE UPDATE ON user_cvs
        FOR EACH ROW
        EXECUTE FUNCTION user_cvs_touch_updated_at();
    END IF;
END
$$;

-- Lock down public access — service role (used by the python
-- backend) bypasses RLS, so server-side reads/writes still work.
-- Anon role gets nothing because the column contains a base64
-- encoded resume.
ALTER TABLE user_cvs ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- USER PORTAL CREDENTIALS — encrypted at rest
-- ============================================================
-- Mirrors the local SQLite portal_credentials table to Supabase
-- so each user's saved Internshala / LinkedIn / Naukri / Unstop
-- session/cookies survive Render restarts. The `enc_payload`
-- column is AES-256-GCM ciphertext produced by core.security
-- with a key the server holds in memory only — Supabase NEVER
-- sees the plaintext password.
-- ============================================================

CREATE TABLE IF NOT EXISTS user_portal_credentials (
    telegram_id   TEXT NOT NULL,
    portal        TEXT NOT NULL,
    enc_payload   TEXT NOT NULL,        -- base64(AES-256-GCM(json{...}))
    nonce         TEXT NOT NULL,        -- base64 nonce
    risk_level    TEXT DEFAULT 'low',
    cred_version  INTEGER DEFAULT 1,
    saved_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (telegram_id, portal)
);

CREATE INDEX IF NOT EXISTS idx_upc_telegram_id
    ON user_portal_credentials(telegram_id);

CREATE INDEX IF NOT EXISTS idx_upc_updated_at
    ON user_portal_credentials(updated_at DESC);

-- Guarded trigger for portal credentials updated_at.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_upc_touch'
    ) THEN
        CREATE TRIGGER trg_upc_touch
        BEFORE UPDATE ON user_portal_credentials
        FOR EACH ROW
        EXECUTE FUNCTION user_cvs_touch_updated_at();
    END IF;
END
$$;

ALTER TABLE user_portal_credentials ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- USER PREFERENCES — non-secret per-user settings
-- ============================================================
-- Anything the user toggles in mini-app Settings (auto-apply
-- enabled, max apps/day, preferred sources, location filter,
-- notification mute, theme, etc). Plain JSON — no encryption
-- needed since none of these are credentials.
-- ============================================================

CREATE TABLE IF NOT EXISTS user_preferences (
    telegram_id  TEXT PRIMARY KEY,
    prefs        JSONB NOT NULL DEFAULT '{}'::JSONB,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_user_prefs_touch'
    ) THEN
        CREATE TRIGGER trg_user_prefs_touch
        BEFORE UPDATE ON user_preferences
        FOR EACH ROW
        EXECUTE FUNCTION user_cvs_touch_updated_at();
    END IF;
END
$$;

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- DONE.
-- After running this script you should see in Table Editor:
--   • user_cvs
--   • user_portal_credentials
--   • user_preferences
-- All with RLS enabled. The python backend uses the
-- service_role key (Render env: SUPABASE_SERVICE_ROLE_KEY) so
-- it bypasses RLS and reads/writes freely. The anon key has
-- zero access to these three tables — exactly what we want.
-- ============================================================
