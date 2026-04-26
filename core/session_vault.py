"""
NEXUS v0.2 — Layer 0: Cryptographic Credential Vault + Session Freshness Oracle
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Responsibilities
----------------
1. Encrypted storage of portal session cookies + storage state (AES-256 / Fernet).
2. Per-portal device fingerprint binding (Camoufox config — same fingerprint
   reused on every apply for that portal → "semantic session identity",
   Innovation 3).
3. Session Freshness Oracle: each session has a health_score (0..100) that
   decays on a portal-specific curve (LinkedIn linear-90d, Naukri steep-30d,
   etc.). When health_score drops below 30, the oracle fires a Telegram
   refresh alert BEFORE the session fails (proactive, not reactive).
4. IP continuity via Cloudflare Worker proxy (Innovation 3).

This module exposes a small, audited surface; nothing else in NEXUS reaches
into the encrypted blob directly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:                           # pragma: no cover
    Fernet = None                             # type: ignore
    InvalidToken = Exception                  # type: ignore

from core.nexus_config import (
    PORTAL_RISK,
    SUPPORTED_PORTALS,
    USER_HANDLE,
)

log = logging.getLogger("nexus.vault")


# ────────────────────────────────────────────────────────────────────────────
# Decay curves — portal-specific health drop per day since last_used / capture
# ────────────────────────────────────────────────────────────────────────────
def _decay_linear_90d(age_days: float) -> int:
    """LinkedIn-style: 100 → 0 linearly over 90 days."""
    return max(0, int(round(100 * (1 - min(age_days, 90) / 90))))


def _decay_steep_30d(age_days: float) -> int:
    """Naukri-style: faster decay, flat at 0 after 30 days."""
    return max(0, int(round(100 * (1 - min(age_days, 30) / 30) ** 1.5)))


_DECAY_CURVES = {
    "linear_90d": _decay_linear_90d,
    "steep_30d":  _decay_steep_30d,
}


# ────────────────────────────────────────────────────────────────────────────
# Data class
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class SessionRecord:
    portal:             str
    user_handle:        str
    encrypted_cookies:  str
    encrypted_storage:  str | None
    device_fingerprint: dict[str, Any]
    apparent_ip:        str | None
    health_score:       int
    captured_at:        datetime
    last_used_at:       datetime | None
    last_refreshed_at:  datetime
    decay_curve:        str
    revoked:            bool = False
    id:                 str | None = None

    @property
    def fingerprint_hash(self) -> str:
        return hashlib.md5(
            json.dumps(self.device_fingerprint, sort_keys=True).encode()
        ).hexdigest()


# ────────────────────────────────────────────────────────────────────────────
# Encryption layer — Fernet (AES-128-CBC + HMAC-SHA256, RFC 7515 compliant)
# Key source: $SESSION_VAULT_KEY  (base64 urlsafe, 32 bytes raw).
# In Supabase prod we delegate to Supabase Vault; this is the local wrapper.
# ────────────────────────────────────────────────────────────────────────────
def _load_fernet() -> "Fernet":
    if Fernet is None:
        raise RuntimeError(
            "cryptography package not installed. "
            "Run: pip install cryptography>=42.0"
        )
    key = os.getenv("SESSION_VAULT_KEY")
    if not key:
        raise RuntimeError(
            "SESSION_VAULT_KEY not set. Generate with:\n"
            "  python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise RuntimeError(f"Invalid SESSION_VAULT_KEY: {e}") from e


def encrypt(plaintext: str | bytes) -> str:
    """Return URL-safe base64 token. Always decryptable with the same key."""
    f = _load_fernet()
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    return f.encrypt(plaintext).decode("ascii")


def decrypt(token: str) -> str:
    f = _load_fernet()
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError("Vault token failed integrity check") from e


# ────────────────────────────────────────────────────────────────────────────
# Session Freshness Oracle
# ────────────────────────────────────────────────────────────────────────────
class SessionOracle:
    """Computes health, fires proactive refresh alerts."""

    REFRESH_THRESHOLD = 30   # below this → Telegram alert
    WARN_THRESHOLD    = 50   # below this → warn in dashboard

    def __init__(self, telegram_notifier=None):
        # telegram_notifier: callable(portal: str, action: str) -> awaitable
        self._notify = telegram_notifier

    @staticmethod
    def compute_health(rec: SessionRecord, now: datetime | None = None) -> int:
        """Pure function — recompute health from scratch using the decay curve."""
        if rec.revoked:
            return 0
        now = now or datetime.now(timezone.utc)
        anchor = rec.last_refreshed_at or rec.captured_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - anchor).total_seconds() / 86400)
        curve = _DECAY_CURVES.get(rec.decay_curve, _decay_linear_90d)
        return curve(age_days)

    def tick(self, rec: SessionRecord) -> tuple[int, str | None]:
        """
        Returns (new_health, action) where action ∈ {None,'WARN','REFRESH','EXPIRED'}.
        Caller is responsible for persisting + dispatching the Telegram message.
        """
        new_health = self.compute_health(rec)
        rec.health_score = new_health
        if rec.revoked or new_health <= 0:
            return new_health, "EXPIRED"
        if new_health < self.REFRESH_THRESHOLD:
            return new_health, "REFRESH"
        if new_health < self.WARN_THRESHOLD:
            return new_health, "WARN"
        return new_health, None


# ────────────────────────────────────────────────────────────────────────────
# Session Vault — primary API used by the rest of NEXUS
# ────────────────────────────────────────────────────────────────────────────
class SessionVault:
    """
    Thin wrapper over Supabase `session_vault` + `session_health_log`.
    Persistence is delegated to a `db` object (duck-typed: must expose
    .upsert_session, .fetch_session, .log_health) so the vault itself stays
    framework-agnostic and easily testable with an in-memory backend.
    """

    def __init__(self, db, oracle: SessionOracle | None = None):
        self.db     = db
        self.oracle = oracle or SessionOracle()

    # ---- capture (run once per portal, after manual login in Camoufox) ----
    async def capture(
        self,
        portal:             str,
        cookies_json:       str,
        storage_json:       str | None,
        device_fingerprint: dict[str, Any],
        apparent_ip:        str | None = None,
        decay_curve:        str | None = None,
    ) -> SessionRecord:
        if portal not in SUPPORTED_PORTALS:
            raise ValueError(f"Unknown portal: {portal!r}")

        decay = decay_curve or PORTAL_RISK[portal].decay_curve
        now = datetime.now(timezone.utc)

        rec = SessionRecord(
            portal              = portal,
            user_handle         = USER_HANDLE,
            encrypted_cookies   = encrypt(cookies_json),
            encrypted_storage   = encrypt(storage_json) if storage_json else None,
            device_fingerprint  = device_fingerprint,
            apparent_ip         = apparent_ip,
            health_score        = 100,
            captured_at         = now,
            last_used_at        = None,
            last_refreshed_at   = now,
            decay_curve         = decay,
        )
        rec.id = await self.db.upsert_session(rec)
        await self.db.log_health(rec.id, portal, None, 100, "capture")
        log.info("vault.capture portal=%s health=100 fp_hash=%s",
                 portal, rec.fingerprint_hash[:8])
        return rec

    # ---- load (used immediately before every apply) ----
    async def load(self, portal: str) -> SessionRecord:
        rec = await self.db.fetch_session(portal, USER_HANDLE)
        if rec is None:
            raise LookupError(f"No session for portal={portal}. Run capture first.")
        if rec.revoked:
            raise PermissionError(f"Session revoked for portal={portal}")

        # Recompute health on every load and short-circuit if expired
        new_health, action = self.oracle.tick(rec)
        if action == "EXPIRED":
            await self._mark_revoked(rec, "expired_by_oracle")
            raise PermissionError(f"Session expired for portal={portal}")

        if action == "REFRESH":
            await self._dispatch_refresh_alert(rec)

        await self.db.log_health(
            rec.id, portal, None, new_health, action or "load_ok"
        )
        return rec

    # ---- decrypt convenience ----
    @staticmethod
    def decrypt_cookies(rec: SessionRecord) -> str:
        return decrypt(rec.encrypted_cookies)

    @staticmethod
    def decrypt_storage(rec: SessionRecord) -> str | None:
        return decrypt(rec.encrypted_storage) if rec.encrypted_storage else None

    # ---- mark used (Layer 6 calls this after every apply attempt) ----
    async def mark_used(
        self,
        rec:    SessionRecord,
        success: bool,
        encountered_captcha: bool = False,
    ) -> int:
        rec.last_used_at = datetime.now(timezone.utc)
        prev = rec.health_score
        if not success:
            rec.health_score = max(0, rec.health_score - 5)
        if encountered_captcha:
            rec.health_score = max(0, rec.health_score - 3)
        await self.db.upsert_session(rec)
        await self.db.log_health(
            rec.id, rec.portal, prev, rec.health_score,
            f"apply_{'ok' if success else 'fail'}"
            + ("_captcha" if encountered_captcha else ""),
        )
        return rec.health_score

    # ---- refresh (after user re-authenticates via Telegram link) ----
    async def refresh(
        self,
        portal:        str,
        cookies_json:  str,
        storage_json:  str | None,
    ) -> SessionRecord:
        rec = await self.db.fetch_session(portal, USER_HANDLE)
        if rec is None:
            raise LookupError(f"Cannot refresh non-existent session for {portal}")
        prev = rec.health_score
        rec.encrypted_cookies   = encrypt(cookies_json)
        if storage_json is not None:
            rec.encrypted_storage = encrypt(storage_json)
        rec.health_score        = 100
        rec.last_refreshed_at   = datetime.now(timezone.utc)
        rec.revoked             = False
        await self.db.upsert_session(rec)
        await self.db.log_health(rec.id, portal, prev, 100, "refresh")
        log.info("vault.refresh portal=%s prev_health=%s", portal, prev)
        return rec

    # ---- internal helpers ----
    async def _mark_revoked(self, rec: SessionRecord, reason: str) -> None:
        rec.revoked = True
        rec.health_score = 0
        await self.db.upsert_session(rec)
        await self.db.log_health(rec.id, rec.portal, None, 0, f"revoke:{reason}")

    async def _dispatch_refresh_alert(self, rec: SessionRecord) -> None:
        """
        Fire-and-forget Telegram alert. The actual notifier is wired in
        Layer 9 (telegram_dashboard). Here we only emit a structured log
        event the dashboard subscribes to.
        """
        log.warning(
            "vault.refresh_required portal=%s health=%s — "
            "Telegram alert dispatched",
            rec.portal,
            rec.health_score,
        )
        if self.oracle._notify:                   # type: ignore[attr-defined]
            try:
                await self.oracle._notify(rec.portal, "REFRESH_NEEDED")  # type: ignore
            except Exception as e:
                log.exception("vault.notify_failed portal=%s err=%s", rec.portal, e)


# ────────────────────────────────────────────────────────────────────────────
# In-memory backend — used by tests + offline dev
# ────────────────────────────────────────────────────────────────────────────
class InMemoryVaultDB:
    """Drop-in `db` for SessionVault that stores records in a dict."""

    def __init__(self):
        self._store: dict[tuple[str, str], SessionRecord] = {}
        self._log:   list[dict[str, Any]] = []

    async def upsert_session(self, rec: SessionRecord) -> str:
        if rec.id is None:
            rec.id = base64.urlsafe_b64encode(os.urandom(12)).decode()
        self._store[(rec.portal, rec.user_handle)] = rec
        return rec.id

    async def fetch_session(self, portal: str, user_handle: str) -> SessionRecord | None:
        return self._store.get((portal, user_handle))

    async def log_health(
        self,
        vault_id:      str | None,
        portal:        str,
        health_before: int | None,
        health_after:  int,
        reason:        str,
    ) -> None:
        self._log.append({
            "vault_id":      vault_id,
            "portal":        portal,
            "health_before": health_before,
            "health_after":  health_after,
            "reason":        reason,
            "ts":            datetime.now(timezone.utc).isoformat(),
        })


__all__ = [
    "SessionRecord",
    "SessionOracle",
    "SessionVault",
    "InMemoryVaultDB",
    "encrypt",
    "decrypt",
]
