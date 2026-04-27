"""
NEXUS v0.2 — CV Intake Pipeline (Telegram → Parse → Encrypt → Embed → Supabase)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

The single entry point for every user's CV. Wired onto the Telegram bot's
document handler. Every CV upload flows through this module:

  1. Telegram document received (PDF / DOCX / TXT, max 5 MB)
  2. RBAC gate — must have UPLOAD_CV capability (PENDING users denied)
  3. SHA-256 dedupe — identical re-uploads are a no-op
  4. Parse — pdftotext if available else pypdf, .docx via python-docx fallback
  5. Encrypt — Fernet AES-256 (per-user salt derived from SESSION_VAULT_KEY)
  6. Embed — Groq text-embedding-3-large → 1024-dim vector
  7. Persist — UPDATE nexus_users + INSERT cv_uploads (audit row)
  8. Trigger — enqueue user_id into the scoring_loop backlog (re-score all jobs)

Public surface
--------------
  CVIntake(db, access).
      handle_document(tg_user, file_bytes, filename, mime) -> CVIntakeResult
      get_user_cv_text(user_id)                            -> str | None  (decrypted)

Heavy deps (pypdf, python-docx, cryptography) are all in base requirements.
Groq import is guarded so the module stays import-safe on dev machines.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

from core.access_control import (
    AccessControl,
    Capability,
    TelegramUser,
    User,
)

log = logging.getLogger("nexus.cv_intake")


# ─── Soft imports ──────────────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet                            # type: ignore
    CRYPTO_AVAILABLE = True
except Exception:                                                      # noqa: BLE001
    Fernet = None                                                      # type: ignore
    CRYPTO_AVAILABLE = False

try:
    import pypdf                                                       # type: ignore
    PYPDF_AVAILABLE = True
except Exception:                                                      # noqa: BLE001
    pypdf = None                                                       # type: ignore
    PYPDF_AVAILABLE = False

try:
    import docx as _docx                                              # python-docx
    DOCX_AVAILABLE = True
except Exception:                                                      # noqa: BLE001
    _docx = None                                                       # type: ignore
    DOCX_AVAILABLE = False


# ─── Constants ─────────────────────────────────────────────────────────────
MAX_CV_BYTES   = 5 * 1024 * 1024                                       # 5 MB hard cap
MIN_PARSED_CHARS = 200                                                 # below this = bad parse
ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
}


# ============================================================================
# Result dataclass
# ============================================================================

@dataclass
class CVIntakeResult:
    success:        bool
    user_id:        int
    message:        str
    cv_chars:       int   = 0
    cv_sha256:      str   = ""
    parse_engine:   str   = ""
    rescored_queued: bool = False


# ============================================================================
# Fernet key derivation — per-user salt from SESSION_VAULT_KEY
# ============================================================================

def _derive_user_fernet(user_id: int) -> "Fernet":
    """
    Derive a stable per-user Fernet key from `SESSION_VAULT_KEY` + user_id.
    Avoids one-key-leaks-all-CVs failure mode.
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography not installed")
    base = os.getenv("SESSION_VAULT_KEY", "").encode()
    if not base:
        raise RuntimeError(
            "SESSION_VAULT_KEY not set — required to encrypt CVs at rest. "
            "Generate with `python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`"
        )
    # HKDF-style: SHA256(base || user_id) → urlsafe-b64 32 bytes → Fernet key
    digest = hashlib.sha256(base + str(user_id).encode()).digest()
    key    = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _encrypt_for_user(user_id: int, plaintext: str) -> str:
    f = _derive_user_fernet(user_id)
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decrypt_for_user(user_id: int, ciphertext: str) -> str:
    f = _derive_user_fernet(user_id)
    return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")


# ============================================================================
# Parsers — PDF / DOCX / TXT
# ============================================================================

def _parse_pdf(data: bytes) -> tuple[str, str]:
    """Returns (text, parse_engine_used). Tries pdftotext (fast) → pypdf."""
    # 1. pdftotext (poppler) — fastest, best layout preservation
    if shutil.which("pdftotext"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                fh.write(data)
                tmp_path = fh.name
            try:
                proc = subprocess.run(
                    ["pdftotext", "-layout", tmp_path, "-"],
                    capture_output=True, timeout=20,
                )
                if proc.returncode == 0:
                    text = proc.stdout.decode("utf-8", errors="replace")
                    if len(text) >= MIN_PARSED_CHARS:
                        return text, "pdftotext"
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except Exception as e:                                          # noqa: BLE001
            log.debug("pdftotext failed (%s); falling back", e)

    # 2. pypdf — pure-Python fallback
    if PYPDF_AVAILABLE:
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))                 # type: ignore[union-attr]
            chunks: list[str] = []
            for page in reader.pages:
                try:
                    chunks.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(chunks), "pypdf"
        except Exception as e:                                          # noqa: BLE001
            log.warning("pypdf parse failed: %s", e)
    return "", "none"


def _parse_docx(data: bytes) -> tuple[str, str]:
    if not DOCX_AVAILABLE:
        return "", "none"
    try:
        d = _docx.Document(io.BytesIO(data))                            # type: ignore[union-attr]
        text = "\n".join(p.text for p in d.paragraphs if p.text)
        return text, "python-docx"
    except Exception as e:                                              # noqa: BLE001
        log.warning("docx parse failed: %s", e)
        return "", "none"


def _parse(data: bytes, mime: str, filename: Optional[str]) -> tuple[str, str]:
    name_low = (filename or "").lower()
    if mime == "application/pdf" or name_low.endswith(".pdf"):
        return _parse_pdf(data)
    if (
        mime in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        }
        or name_low.endswith(".docx")
    ):
        return _parse_docx(data)
    if mime.startswith("text/") or name_low.endswith(".txt"):
        try:
            return data.decode("utf-8", errors="replace"), "plaintext"
        except Exception:
            return "", "none"
    # Unknown — try PDF first, then DOCX, last text
    text, engine = _parse_pdf(data)
    if text:
        return text, engine
    text, engine = _parse_docx(data)
    if text:
        return text, engine
    try:
        return data.decode("utf-8", errors="replace"), "plaintext"
    except Exception:
        return "", "none"


# ============================================================================
# CVIntake — the orchestrator
# ============================================================================

class CVIntake:
    """
    Wires Telegram document upload → encrypted Supabase row + embedding.

    The optional `on_cv_ready` async callable is invoked after a successful
    intake so the scoring_loop can immediately enqueue a per-user re-score.
    """

    def __init__(
        self,
        db: Any,
        access: AccessControl,
        on_cv_ready: Optional[Any] = None,            # async (user_id) -> None
    ) -> None:
        self.db = db
        self.access = access
        self._on_cv_ready = on_cv_ready

    async def handle_document(
        self,
        tg_user: TelegramUser,
        file_bytes: bytes,
        filename: Optional[str],
        mime: str,
    ) -> CVIntakeResult:
        """Full pipeline. Returns a structured result for the bot to reply with."""

        # 1. RBAC gate
        decision = await self.access.authorize(tg_user, Capability.UPLOAD_CV)
        if not decision.allow:
            return CVIntakeResult(
                success=False, user_id=0, message=decision.reason,
            )
        user: User = decision.user                                     # type: ignore[assignment]

        # 2. Size + mime validation
        size = len(file_bytes)
        if size > MAX_CV_BYTES:
            return CVIntakeResult(
                success=False, user_id=user.user_id,
                message=f"⚠️ File too large ({size/1024/1024:.1f} MB). Max 5 MB.",
            )
        if mime and mime not in ALLOWED_MIME and not (filename or "").lower().endswith(
            (".pdf", ".docx", ".doc", ".txt")
        ):
            return CVIntakeResult(
                success=False, user_id=user.user_id,
                message=f"⚠️ Unsupported file type `{mime}`. Use PDF, DOCX or TXT.",
            )

        # 3. SHA-256 dedupe
        sha = hashlib.sha256(file_bytes).hexdigest()
        existing_emb = await self._safe_get_cv_embedding(user.user_id)
        # Cheap dedupe: if user already has CV with same sha, skip
        existing_sha = await self._existing_sha(user.user_id)
        if existing_sha and existing_sha == sha:
            await self.access.audit(user, "CV_REUPLOAD_NOOP",
                                    target_kind="cv", target_ref=sha[:16])
            return CVIntakeResult(
                success=True, user_id=user.user_id,
                message="ℹ️ Same CV already on file — nothing to update.",
                cv_sha256=sha,
            )

        # 4. Parse
        text, engine = _parse(file_bytes, mime or "", filename)
        text = (text or "").strip()
        if len(text) < MIN_PARSED_CHARS:
            return CVIntakeResult(
                success=False, user_id=user.user_id,
                message=(
                    f"⚠️ Could not extract enough text from the CV "
                    f"(got {len(text)} chars, need ≥ {MIN_PARSED_CHARS}). "
                    f"Try re-exporting as a text-based PDF."
                ),
                parse_engine=engine,
            )

        # 5. Encrypt
        try:
            ciphertext = _encrypt_for_user(user.user_id, text)
        except RuntimeError as e:
            return CVIntakeResult(
                success=False, user_id=user.user_id,
                message=f"⚠️ Encryption unavailable: {e}",
            )

        # 6. Embed
        embedding = await self._embed(text)
        if not embedding or all(v == 0.0 for v in embedding):
            log.warning("cv_intake.embed_zero — Groq missing? Storing zero vector.")

        # 7. Persist
        try:
            await self.db.store_cv(
                user.user_id,
                cv_text_encrypted=ciphertext,
                embedding=embedding,
                filename=filename,
                sha256=sha,
                size_bytes=size,
                parsed_chars=len(text),
                parse_engine=engine,
            )
        except Exception as e:                                          # noqa: BLE001
            log.exception("cv_intake.persist_failed")
            return CVIntakeResult(
                success=False, user_id=user.user_id,
                message=f"❌ Storage failed: {e}",
                cv_chars=len(text), parse_engine=engine,
            )

        await self.access.audit(
            user, "CV_UPLOAD",
            target_kind="cv", target_ref=sha[:16],
            payload={"chars": len(text), "engine": engine, "size": size,
                     "filename": filename},
        )

        # 8. Trigger background re-score (if scoring_loop is wired)
        rescored = False
        if self._on_cv_ready is not None:
            try:
                await self._on_cv_ready(user.user_id)
                rescored = True
            except Exception:                                           # noqa: BLE001
                log.exception("cv_intake.on_cv_ready failed (non-fatal)")

        msg = (
            f"✅ CV stored — *{len(text):,} chars* parsed via `{engine}`\n"
            f"_Sha:_ `{sha[:16]}…`\n"
            f"_Embedding:_ {'live' if any(v != 0.0 for v in embedding) else 'queued (Groq offline)'}\n"
            f"\n"
            f"{'⏳ Re-scoring all jobs against your new CV in the background.' if rescored else '⏳ Re-score will run on the next scoring window.'}"
        )
        return CVIntakeResult(
            success=True, user_id=user.user_id, message=msg,
            cv_chars=len(text), cv_sha256=sha,
            parse_engine=engine, rescored_queued=rescored,
        )

    # ─────────────────────────── helpers ────────────────────────────────

    async def get_user_cv_text(self, user_id: int) -> Optional[str]:
        """Decrypt and return the user's CV text. None if absent."""
        try:
            ct = await self._existing_ciphertext(user_id)
        except Exception:                                               # noqa: BLE001
            return None
        if not ct:
            return None
        try:
            return _decrypt_for_user(user_id, ct)
        except Exception:                                               # noqa: BLE001
            log.exception("cv_intake.decrypt_failed user_id=%s", user_id)
            return None

    async def _existing_sha(self, user_id: int) -> Optional[str]:
        # Try DAO method if exists, else fall back to None gracefully
        getter = getattr(self.db, "get_user_cv_sha", None)
        if getter is None:
            # Direct asyncpg query if available
            pool = getattr(self.db, "_pool", None)
            if pool is None:
                return None
            try:
                async with pool.acquire() as c:
                    row = await c.fetchrow(
                        "SELECT cv_sha256 FROM nexus_users WHERE user_id = $1",
                        user_id,
                    )
                return row["cv_sha256"] if row else None
            except Exception:                                           # noqa: BLE001
                return None
        try:
            return await getter(user_id)
        except Exception:                                               # noqa: BLE001
            return None

    async def _existing_ciphertext(self, user_id: int) -> Optional[str]:
        pool = getattr(self.db, "_pool", None)
        if pool is None:
            return None
        try:
            async with pool.acquire() as c:
                row = await c.fetchrow(
                    "SELECT cv_text_encrypted FROM nexus_users WHERE user_id = $1",
                    user_id,
                )
            return row["cv_text_encrypted"] if row else None
        except Exception:                                               # noqa: BLE001
            return None

    async def _safe_get_cv_embedding(self, user_id: int) -> Optional[list[float]]:
        getter = getattr(self.db, "get_user_cv_embedding", None)
        if getter is None:
            return None
        try:
            return await getter(user_id)
        except Exception:                                               # noqa: BLE001
            return None

    async def _embed(self, text: str) -> list[float]:
        """Defer to core.pgvector_matcher.embed_text (handles Groq guard)."""
        try:
            from core.pgvector_matcher import embed_text                # type: ignore
            return await embed_text(text)
        except Exception as e:                                          # noqa: BLE001
            log.warning("cv_intake.embed_fallback %s", e)
            from core.pgvector_matcher import EMBED_DIM                 # type: ignore
            return [0.0] * EMBED_DIM

    # ─────────────────────────── Dashboard shims ────────────────────────────

    async def ingest_telegram_upload(
        self,
        user_id: int,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> dict:
        """
        Lightweight wrapper called by the Telegram dashboard's _on_document
        handler. The dashboard has already resolved the user via AccessControl,
        so we skip the Capability gate here and call straight into the parse →
        encrypt → embed → persist → on_cv_ready chain.

        Returns a small dict the dashboard formats into a reply:
            {ok: bool, chars: int, embed_dim: int, sha: str, error: str|None}
        """
        # Size + mime guards (mirror handle_document)
        size = len(content)
        if size > MAX_CV_BYTES:
            return {"ok": False,
                    "error": f"File too large ({size/1024/1024:.1f} MB). Max 5 MB."}
        if mime_type and mime_type not in ALLOWED_MIME and not (filename or "").lower().endswith(
            (".pdf", ".docx", ".doc", ".txt")
        ):
            return {"ok": False,
                    "error": f"Unsupported file type `{mime_type}`. Use PDF, DOCX or TXT."}

        # SHA dedupe
        sha = hashlib.sha256(content).hexdigest()
        existing_sha = await self._existing_sha(user_id)
        if existing_sha and existing_sha == sha:
            return {"ok": True, "chars": 0, "embed_dim": 0, "sha": sha,
                    "error": None, "noop": True}

        # Parse
        text, engine = _parse(content, mime_type or "", filename)
        text = (text or "").strip()
        if len(text) < MIN_PARSED_CHARS:
            return {"ok": False,
                    "error": f"Could not extract enough text "
                             f"({len(text)} chars, need ≥ {MIN_PARSED_CHARS})."}

        # Encrypt
        try:
            ciphertext = _encrypt_for_user(user_id, text)
        except RuntimeError as e:
            return {"ok": False, "error": f"Encryption unavailable: {e}"}

        # Embed
        embedding = await self._embed(text)

        # Persist
        try:
            await self.db.store_cv(
                user_id,
                cv_text_encrypted=ciphertext,
                embedding=embedding,
                filename=filename,
                sha256=sha,
                size_bytes=size,
                parsed_chars=len(text),
                parse_engine=engine,
            )
        except Exception as e:                                          # noqa: BLE001
            log.exception("ingest_telegram_upload.persist_failed")
            return {"ok": False, "error": f"Storage failed: {e}"}

        # Trigger background re-score
        if self._on_cv_ready is not None:
            try:
                await self._on_cv_ready(user_id)
            except Exception:                                           # noqa: BLE001
                log.exception("on_cv_ready failed (non-fatal)")

        return {
            "ok": True,
            "chars": len(text),
            "embed_dim": len(embedding) if embedding else 0,
            "sha": sha,
            "engine": engine,
            "error": None,
        }

    async def get_user_cv_summary(self, user_id: int) -> Optional[dict]:
        """Return a compact summary for /me. None if user has no CV."""
        pool = getattr(self.db, "_pool", None)
        if pool is None:
            return None
        try:
            async with pool.acquire() as c:
                row = await c.fetchrow(
                    "SELECT cv_filename, cv_chars, cv_uploaded_at, cv_sha256 "
                    "FROM nexus_users WHERE user_id = $1",
                    user_id,
                )
        except Exception:                                               # noqa: BLE001
            return None
        if not row or not row["cv_sha256"]:
            return None
        from datetime import datetime as _dt, timezone as _tz
        ts = row.get("cv_uploaded_at")
        human = "?"
        if ts:
            try:
                delta = _dt.now(_tz.utc) - (
                    ts if ts.tzinfo else ts.replace(tzinfo=_tz.utc)
                )
                d = delta.days
                if d == 0:
                    human = "today"
                elif d == 1:
                    human = "yesterday"
                else:
                    human = f"{d}d ago"
            except Exception:
                pass
        return {
            "filename": row.get("cv_filename") or "cv",
            "chars": int(row.get("cv_chars") or 0),
            "uploaded_at_human": human,
            "sha": (row.get("cv_sha256") or "")[:12],
        }


__all__ = [
    "CVIntake", "CVIntakeResult",
    "MAX_CV_BYTES", "MIN_PARSED_CHARS", "ALLOWED_MIME",
]
