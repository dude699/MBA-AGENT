"""
============================================================
CV STORAGE — Render-Ephemeral-Filesystem-Proof Persistence
============================================================

Background:
    Render's free tier does NOT persist `data/` across deploys
    or restarts. The original CV upload code wrote PDFs to
    `data/user_cvs/{telegram_id}.pdf`, which means **every restart
    silently wipes the user's uploaded CV** — and the "For You"
    tab degrades to a neutral score of 50 for every listing,
    surfacing irrelevant jobs (Tally Accountant in Agra, etc.).

Fix:
    Mirror every CV upload to a single Supabase row keyed by
    telegram_id. On cold start, when CVMatcher.refresh_from_cv()
    cannot find the local PDF, it transparently restores it
    from Supabase before tokenising. End user never notices a
    restart.

Schema (run once in Supabase SQL Editor — also handled
automatically by ensure_user_cv_table()):

    CREATE TABLE IF NOT EXISTS user_cvs (
        telegram_id  TEXT PRIMARY KEY,
        filename     TEXT NOT NULL DEFAULT 'resume.pdf',
        pdf_bytes    BYTEA NOT NULL,
        size_bytes   INTEGER NOT NULL DEFAULT 0,
        sha256       TEXT NOT NULL DEFAULT '',
        uploaded_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    );

Public API:
    save_cv(telegram_id, pdf_bytes, filename) -> bool
    load_cv(telegram_id) -> Optional[bytes]
    restore_local_cv(telegram_id, dest_path) -> bool
    has_remote_cv(telegram_id) -> bool
    delete_cv(telegram_id) -> bool

Failure modes are silent — if Supabase is unconfigured or a
network blip happens, the local file path is still the source
of truth for that boot. This module never raises.
============================================================
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)


MODULE_ID = "CV-STORAGE"
TABLE_NAME = "user_cvs"
_MAX_PDF_BYTES = 5 * 1024 * 1024  # 5 MB hard ceiling — same as the upload endpoint.


def _safe_id(telegram_id: str) -> str:
    return str(telegram_id or "anonymous").replace("/", "").replace("..", "")[:20]


def _client():
    """Return the Supabase singleton, or None if unavailable."""
    try:
        from core.supabase_client import get_supabase
        return get_supabase()
    except Exception as e:  # pragma: no cover
        logger.debug(f"[{MODULE_ID}] supabase import failed: {e}")
        return None


# ============================================================
# WRITE
# ============================================================

def save_cv(telegram_id: str,
            pdf_bytes: bytes,
            filename: str = "resume.pdf") -> bool:
    """
    Mirror an uploaded CV to Supabase so it survives Render restarts.

    The blob is stored as base64 in a TEXT column (pdf_b64) for maximum
    portability across Supabase client versions — BYTEA round-tripping
    through PostgREST is fragile in the python client. 5 MB ceiling.

    Returns True on success, False otherwise. Never raises.
    """
    if not pdf_bytes:
        return False
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        logger.warning(f"[{MODULE_ID}] save_cv rejected: too large ({len(pdf_bytes)} bytes)")
        return False
    if pdf_bytes[:4] != b"%PDF":
        logger.warning(f"[{MODULE_ID}] save_cv rejected: not a PDF")
        return False

    sb = _client()
    if sb is None:
        logger.debug(f"[{MODULE_ID}] save_cv skipped — Supabase not configured")
        return False

    safe = _safe_id(telegram_id)
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    payload = {
        "telegram_id": safe,
        "filename": (filename or "resume.pdf")[:200],
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        "size_bytes": len(pdf_bytes),
        "sha256": sha,
    }

    try:
        # Upsert keyed on telegram_id.
        sb.table(TABLE_NAME).upsert(payload, on_conflict="telegram_id").execute()
        logger.info(
            f"[{MODULE_ID}] CV mirrored to Supabase for {safe}: "
            f"{len(pdf_bytes)} bytes, sha={sha[:8]}"
        )
        return True
    except Exception as e:
        # Most likely cause: table doesn't exist yet. Surface an actionable hint.
        msg = str(e).lower()
        if "does not exist" in msg or "user_cvs" in msg and "404" in msg:
            logger.warning(
                f"[{MODULE_ID}] table `{TABLE_NAME}` not found in Supabase. "
                "Run the migration in data/cv_storage_schema.sql once."
            )
        else:
            logger.warning(f"[{MODULE_ID}] save_cv failed: {e}")
        return False


# ============================================================
# READ
# ============================================================

def has_remote_cv(telegram_id: str) -> bool:
    """Cheap existence check — used for telemetry only."""
    sb = _client()
    if sb is None:
        return False
    try:
        resp = (
            sb.table(TABLE_NAME)
            .select("telegram_id, size_bytes")
            .eq("telegram_id", _safe_id(telegram_id))
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False


def load_cv(telegram_id: str) -> Optional[bytes]:
    """Return the raw PDF bytes from Supabase, or None if absent/unavailable."""
    sb = _client()
    if sb is None:
        return None
    try:
        resp = (
            sb.table(TABLE_NAME)
            .select("pdf_b64, size_bytes")
            .eq("telegram_id", _safe_id(telegram_id))
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        b64 = rows[0].get("pdf_b64") or ""
        if not b64:
            return None
        return base64.b64decode(b64.encode("ascii"))
    except Exception as e:
        logger.debug(f"[{MODULE_ID}] load_cv failed for {telegram_id}: {e}")
        return None


def restore_local_cv(telegram_id: str, dest_path: str) -> bool:
    """
    Repopulate `dest_path` from Supabase if a remote CV exists.
    Used by CVMatcher.refresh_from_cv() on cold start to rehydrate
    the ephemeral data/user_cvs/ directory.

    Returns True iff a CV was restored to disk.
    """
    pdf = load_cv(telegram_id)
    if not pdf:
        return False
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(pdf)
        logger.info(
            f"[{MODULE_ID}] CV restored from Supabase → {dest_path} "
            f"({len(pdf)} bytes)"
        )
        return True
    except Exception as e:
        logger.warning(f"[{MODULE_ID}] restore_local_cv write failed: {e}")
        return False


# ============================================================
# DELETE
# ============================================================

def delete_cv(telegram_id: str) -> bool:
    sb = _client()
    if sb is None:
        return False
    try:
        sb.table(TABLE_NAME).delete().eq("telegram_id", _safe_id(telegram_id)).execute()
        return True
    except Exception as e:
        logger.debug(f"[{MODULE_ID}] delete_cv failed: {e}")
        return False
