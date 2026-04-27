-- ============================================================
-- CV STORAGE — Supabase persistence so CV uploads survive
-- Render's ephemeral filesystem (every redeploy wipes data/).
-- ============================================================
-- Run this ONCE in Supabase SQL Editor:
--   Dashboard → Project → SQL Editor → New Query → paste → Run
--
-- After this is applied, every /api/user/upload-cv call will
-- upsert a row here. Cold start of the Render service will
-- automatically restore the local data/user_cvs/{id}.pdf from
-- this table on the first /api/cv/status request, so the
-- "For You" tab keeps ranking against the user's CV across
-- restarts and deploys.
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

-- updated_at trigger so we can audit the latest re-uploads.
CREATE OR REPLACE FUNCTION user_cvs_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_cvs_touch ON user_cvs;
CREATE TRIGGER trg_user_cvs_touch
BEFORE UPDATE ON user_cvs
FOR EACH ROW
EXECUTE FUNCTION user_cvs_touch_updated_at();

-- Optional: lock down access. Service role bypasses RLS by
-- design, so the python backend keeps full read/write. The
-- anon role gets nothing — this column contains a base64
-- encoded resume.
ALTER TABLE user_cvs ENABLE ROW LEVEL SECURITY;

-- (Service role bypasses RLS automatically — no policy needed.)
