"""
============================================================
CREDENTIAL VAULT — Per-User, Per-Portal, Encrypted at Rest
============================================================

Goals
-----
1. Each user's portal logins (Internshala / Naukri / LinkedIn / Unstop /
   ...) are stored encrypted with a server-side Fernet key the user
   never sees and that does NOT live in the database itself.
2. Encrypted blobs are mirrored to Supabase so they survive Render
   redeploys (data/firstmover.db is ephemeral on the free tier).
3. Plaintext credentials only ever exist in process memory during an
   active auto-apply call — they are never logged, never returned via
   any API endpoint, never echoed in error messages.
4. Read access is scoped: a credential set saved by user A cannot be
   read by user B. The DB row key is (telegram_id, portal).

Threat model
------------
* Supabase row dump → leaks ciphertext only; useless without the key.
* Render ENV dump  → leaks the master key. Mitigation: rotate the
  vault key any time (re-encrypts all rows in place via rotate()).
* Compromised admin → can read every user's plaintext (by design —
  this is "auto-apply on the user's behalf"; the vault is functional,
  not zero-knowledge).
* Stolen X-Session-Token → attacker becomes that user; vault gives
  them what the user themselves could have. Same blast radius as the
  user clicking auto-apply.

Public API
----------
    vault = get_credential_vault()
    vault.save(telegram_id, portal, payload_dict, risk_level="medium")
    vault.load(telegram_id, portal)              -> dict | None
    vault.list_portals(telegram_id)              -> list[str]
    vault.delete(telegram_id, portal)            -> bool
    vault.delete_all_for_user(telegram_id)       -> int   (right-to-erase)
    vault.rotate_key(new_key)                    -> int   (re-encrypts)

Master key precedence
---------------------
1. CREDENTIAL_VAULT_KEY env var  (preferred)
2. SESSION_VAULT_KEY env var     (re-used so we don't multiply secrets)
3. Auto-generated 32-byte key written to data/.vault.key (DEV-ONLY,
   loud warning emitted — Render will lose it on every restart).
============================================================
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTO = True
except ImportError:                         # pragma: no cover
    Fernet = None                           # type: ignore
    InvalidToken = Exception                # type: ignore
    HAS_CRYPTO = False

try:
    from loguru import logger
except ImportError:                         # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

MODULE_ID = "CRED-VAULT"
TABLE_NAME = "user_portal_credentials"
DEV_KEY_PATH = os.path.join("data", ".vault.key")


# ============================================================
# KEY MANAGEMENT
# ============================================================

def _load_master_key() -> Optional[bytes]:
    """Resolve the master Fernet key from env or fall back to a dev file."""
    for var in ("CREDENTIAL_VAULT_KEY", "SESSION_VAULT_KEY"):
        raw = os.getenv(var, "").strip()
        if raw:
            try:
                # Verify it's a valid Fernet key (32 url-safe base64 bytes).
                Fernet(raw.encode())
                return raw.encode()
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] env {var} is set but invalid: {e}")

    # Dev fallback — file-based, will not survive Render restart but at
    # least keeps the vault working on a local laptop.
    try:
        if os.path.isfile(DEV_KEY_PATH):
            with open(DEV_KEY_PATH, "rb") as f:
                key = f.read().strip()
            Fernet(key)  # validate
            return key
    except Exception as e:
        logger.warning(f"[{MODULE_ID}] dev key file invalid: {e}")

    # First boot — generate one.
    try:
        os.makedirs(os.path.dirname(DEV_KEY_PATH), exist_ok=True)
        key = Fernet.generate_key()
        with open(DEV_KEY_PATH, "wb") as f:
            f.write(key)
        os.chmod(DEV_KEY_PATH, 0o600)
        logger.warning(
            f"[{MODULE_ID}] !!! NO CREDENTIAL_VAULT_KEY env var set — "
            f"auto-generated dev key at {DEV_KEY_PATH}. On Render this "
            f"will NOT survive restarts. Set CREDENTIAL_VAULT_KEY in the "
            f"dashboard for production use. Generate one with: "
            f"python -c 'from cryptography.fernet import Fernet; "
            f"print(Fernet.generate_key().decode())'"
        )
        return key
    except Exception as e:
        logger.error(f"[{MODULE_ID}] failed to generate dev key: {e}")
        return None


# ============================================================
# CORE VAULT
# ============================================================

class CredentialVault:
    """Encrypts portal credentials with Fernet (AES-128-CBC + HMAC SHA-256)."""

    def __init__(self, master_key: bytes):
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography package missing — install it.")
        self._fernet = Fernet(master_key)
        self._lock = threading.Lock()
        self._mem_cache: Dict[str, Dict[str, Any]] = {}  # local hot cache

    # ------------------------------------------------------------------
    # safe_id helper — same scheme as the rest of the codebase
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_id(telegram_id: Any) -> str:
        return str(telegram_id or "anonymous").replace("/", "").replace("..", "")[:20]

    @staticmethod
    def _portal_key(portal: str) -> str:
        return (portal or "").strip().lower()[:32]

    @staticmethod
    def _cache_key(telegram_id: str, portal: str) -> str:
        return f"{CredentialVault._safe_id(telegram_id)}::{CredentialVault._portal_key(portal)}"

    # ------------------------------------------------------------------
    # encrypt / decrypt primitives
    # ------------------------------------------------------------------
    def _encrypt(self, payload: Dict[str, Any]) -> str:
        plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(plaintext).decode("ascii")

    def _decrypt(self, ciphertext: str) -> Optional[Dict[str, Any]]:
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("ascii"))
            return json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, ValueError, json.JSONDecodeError) as e:
            logger.warning(f"[{MODULE_ID}] decrypt failed: {e.__class__.__name__}")
            return None

    # ------------------------------------------------------------------
    # Supabase mirror — best-effort, never raises
    # ------------------------------------------------------------------
    def _supabase(self):
        try:
            from core.supabase_client import get_supabase
            return get_supabase()
        except Exception:
            return None

    def _supa_upsert(self, telegram_id: str, portal: str,
                     enc_payload: str, risk_level: str) -> bool:
        sb = self._supabase()
        if sb is None:
            return False
        try:
            sb.table(TABLE_NAME).upsert({
                "telegram_id":  self._safe_id(telegram_id),
                "portal":       self._portal_key(portal),
                "enc_payload":  enc_payload,
                "nonce":        "",  # Fernet bakes nonce into ciphertext
                "risk_level":   (risk_level or "low")[:16],
                "cred_version": 1,
            }, on_conflict="telegram_id,portal").execute()
            return True
        except Exception as e:
            msg = str(e).lower()
            if "does not exist" in msg or "404" in msg:
                logger.warning(
                    f"[{MODULE_ID}] table `{TABLE_NAME}` missing — "
                    f"run data/cv_storage_schema.sql in Supabase."
                )
            else:
                logger.debug(f"[{MODULE_ID}] supabase upsert failed: {e}")
            return False

    def _supa_select_one(self, telegram_id: str, portal: str) -> Optional[str]:
        sb = self._supabase()
        if sb is None:
            return None
        try:
            resp = (
                sb.table(TABLE_NAME)
                .select("enc_payload")
                .eq("telegram_id", self._safe_id(telegram_id))
                .eq("portal", self._portal_key(portal))
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return rows[0].get("enc_payload") if rows else None
        except Exception:
            return None

    def _supa_select_portals(self, telegram_id: str) -> List[Dict[str, Any]]:
        sb = self._supabase()
        if sb is None:
            return []
        try:
            resp = (
                sb.table(TABLE_NAME)
                .select("portal, risk_level, updated_at")
                .eq("telegram_id", self._safe_id(telegram_id))
                .execute()
            )
            return list(resp.data or [])
        except Exception:
            return []

    def _supa_delete(self, telegram_id: str, portal: Optional[str]) -> int:
        sb = self._supabase()
        if sb is None:
            return 0
        try:
            q = sb.table(TABLE_NAME).delete().eq("telegram_id", self._safe_id(telegram_id))
            if portal:
                q = q.eq("portal", self._portal_key(portal))
            resp = q.execute()
            return len(resp.data or [])
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def save(self, telegram_id: Any, portal: str,
             payload: Dict[str, Any],
             risk_level: str = "low") -> bool:
        """Encrypt + persist credentials to Supabase. Returns True on success."""
        if not isinstance(payload, dict) or not payload:
            return False
        try:
            enc = self._encrypt(payload)
        except Exception as e:
            logger.error(f"[{MODULE_ID}] encrypt failed: {e}")
            return False

        ok = self._supa_upsert(telegram_id, portal, enc, risk_level)
        # Hot cache so the same request can read it back without a round-trip.
        with self._lock:
            self._mem_cache[self._cache_key(telegram_id, portal)] = {
                "enc": enc, "loaded_at": datetime.utcnow().isoformat(),
            }
        if ok:
            logger.info(
                f"[{MODULE_ID}] saved creds — user={self._safe_id(telegram_id)} "
                f"portal={self._portal_key(portal)} risk={risk_level} "
                f"size={len(enc)}b"
            )
        return ok

    def load(self, telegram_id: Any, portal: str) -> Optional[Dict[str, Any]]:
        """Decrypt and return the credentials, or None if not found."""
        ckey = self._cache_key(telegram_id, portal)
        enc: Optional[str]
        with self._lock:
            cached = self._mem_cache.get(ckey)
            enc = cached["enc"] if cached else None

        if enc is None:
            enc = self._supa_select_one(telegram_id, portal)
            if enc:
                with self._lock:
                    self._mem_cache[ckey] = {
                        "enc": enc, "loaded_at": datetime.utcnow().isoformat(),
                    }

        if enc is None:
            return None
        return self._decrypt(enc)

    def list_portals(self, telegram_id: Any) -> List[Dict[str, Any]]:
        """List which portals a user has saved credentials for (no plaintext)."""
        return self._supa_select_portals(telegram_id)

    def delete(self, telegram_id: Any, portal: str) -> bool:
        with self._lock:
            self._mem_cache.pop(self._cache_key(telegram_id, portal), None)
        return self._supa_delete(telegram_id, portal) >= 0

    def delete_all_for_user(self, telegram_id: Any) -> int:
        """GDPR-style right to erase. Returns rows deleted."""
        prefix = self._safe_id(telegram_id) + "::"
        with self._lock:
            for k in list(self._mem_cache.keys()):
                if k.startswith(prefix):
                    self._mem_cache.pop(k, None)
        return self._supa_delete(telegram_id, None)

    def rotate_key(self, new_key: bytes) -> int:
        """Re-encrypt every row with a new master key. Returns rows rotated.

        Atomic per-row — if any single row fails to decrypt with the OLD
        key (corrupted ciphertext) we skip it and continue. Only when the
        whole sweep is done do we swap self._fernet to the new key.
        """
        sb = self._supabase()
        if sb is None:
            return 0
        try:
            new_fernet = Fernet(new_key)
        except Exception as e:
            logger.error(f"[{MODULE_ID}] rotate_key invalid new key: {e}")
            return 0

        try:
            resp = sb.table(TABLE_NAME).select("telegram_id, portal, enc_payload").execute()
            rows = resp.data or []
        except Exception as e:
            logger.error(f"[{MODULE_ID}] rotate_key list failed: {e}")
            return 0

        rotated = 0
        for r in rows:
            try:
                plaintext = self._fernet.decrypt(r["enc_payload"].encode("ascii"))
                new_cipher = new_fernet.encrypt(plaintext).decode("ascii")
                sb.table(TABLE_NAME).update({
                    "enc_payload": new_cipher
                }).eq("telegram_id", r["telegram_id"]).eq("portal", r["portal"]).execute()
                rotated += 1
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] rotate skip row: {e}")

        with self._lock:
            self._fernet = new_fernet
            self._mem_cache.clear()
        logger.warning(f"[{MODULE_ID}] key rotation complete: {rotated}/{len(rows)} rows")
        return rotated


# ============================================================
# SINGLETON
# ============================================================

_vault: Optional[CredentialVault] = None
_singleton_lock = threading.Lock()


def get_credential_vault() -> Optional[CredentialVault]:
    """Return the process-wide vault singleton, or None if crypto unavailable."""
    global _vault
    if _vault is not None:
        return _vault
    with _singleton_lock:
        if _vault is not None:
            return _vault
        if not HAS_CRYPTO:
            logger.warning(f"[{MODULE_ID}] cryptography package missing — vault disabled")
            return None
        key = _load_master_key()
        if not key:
            logger.error(f"[{MODULE_ID}] no usable master key — vault disabled")
            return None
        _vault = CredentialVault(key)
        logger.info(f"[{MODULE_ID}] credential vault ready (Fernet AES-128-CBC + HMAC)")
        return _vault


# ============================================================
# Tiny convenience wrapper (used by miniapp_api endpoints)
# ============================================================

def save_portal_credentials(telegram_id: Any, portal: str,
                            payload: Dict[str, Any],
                            risk_level: str = "low") -> bool:
    v = get_credential_vault()
    if v is None:
        return False
    return v.save(telegram_id, portal, payload, risk_level)


def load_portal_credentials(telegram_id: Any, portal: str) -> Optional[Dict[str, Any]]:
    v = get_credential_vault()
    if v is None:
        return None
    return v.load(telegram_id, portal)


def list_user_portals(telegram_id: Any) -> List[Dict[str, Any]]:
    v = get_credential_vault()
    if v is None:
        return []
    return v.list_portals(telegram_id)


def delete_portal_credentials(telegram_id: Any, portal: str) -> bool:
    v = get_credential_vault()
    if v is None:
        return False
    return v.delete(telegram_id, portal)
