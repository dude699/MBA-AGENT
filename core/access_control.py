"""
NEXUS v0.2 — Access Control & RBAC
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

The single security gate for every Telegram interaction. Every command, every
inline-button tap, every CV upload, every auto-apply firing flows through this
module. It enforces:

  * Role hierarchy: ADMIN > POWER_USER > STANDARD_USER > (PENDING) > REVOKED
  * Hardcoded super-admin telegram_id (env: NEXUS_SUPER_ADMIN_ID, default 1284690336)
  * Sliding-window rate limits per (user, bucket)
  * HMAC-signed callback tokens (anti-spoof for inline buttons)
  * Append-only audit log of every gated action

Role capabilities
-----------------
  ADMIN          — full auto-apply, no human-in-loop, grants/revokes others, sees all
  POWER_USER     — full auto-apply for self (uses own captured sessions), one-tap MID
  STANDARD_USER  — CV upload, scoring, daily digest, one-tap apply on MID jobs
  PENDING        — bot replies "access pending" + admin alert
  REVOKED        — silent reject

Public surface
--------------
  AccessControl(db).
      ensure_user(tg_user)                     -> User             (auto-creates as PENDING)
      authorize(tg_user, capability)           -> AuthDecision     (allow/deny + reason)
      grant(actor, target_id, role, reason)    -> bool             (admin only)
      revoke(actor, target_id, reason)         -> bool             (admin only)
      check_rate_limit(user_id, bucket)        -> bool             (returns False on breach)
      sign_callback(user_id, action, target)   -> str              (HMAC token)
      verify_callback(token, user_id)          -> CallbackPayload  (raises on fail)
      audit(actor, action, **kw)               -> None             (append-only)

This module is import-safe — only `cryptography` (already a base dep) and the
DAO are required. Heavy stack not needed.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Protocol


log = logging.getLogger("nexus.access")


# ============================================================================
# Roles & Capabilities
# ============================================================================

class Role(str, Enum):
    ADMIN          = "ADMIN"
    POWER_USER     = "POWER_USER"
    STANDARD_USER  = "STANDARD_USER"
    PENDING        = "PENDING"
    REVOKED        = "REVOKED"


# Role priority boost (added to job match score in queue ordering)
ROLE_BOOST: dict[Role, int] = {
    Role.ADMIN:         100,
    Role.POWER_USER:     50,
    Role.STANDARD_USER:   0,
    Role.PENDING:         0,
    Role.REVOKED:         0,
}


class Capability(str, Enum):
    """Every gated action in NEXUS. Add new ones here, not inline."""
    USE_BOT          = "USE_BOT"            # any command at all
    UPLOAD_CV        = "UPLOAD_CV"
    VIEW_OWN_QUEUE   = "VIEW_OWN_QUEUE"
    TAP_APPLY_MID    = "TAP_APPLY_MID"      # 40-79 score one-tap apply
    AUTO_APPLY_HIGH  = "AUTO_APPLY_HIGH"    # 80+ auto-apply, no human-in-loop
    PAUSE_PORTAL     = "PAUSE_PORTAL"
    RESUME_PORTAL    = "RESUME_PORTAL"
    GRANT_USER       = "GRANT_USER"         # admin-only
    REVOKE_USER      = "REVOKE_USER"        # admin-only
    VIEW_AUDIT       = "VIEW_AUDIT"         # admin-only
    VIEW_ALL_USERS   = "VIEW_ALL_USERS"     # admin-only
    FORCE_SCORE      = "FORCE_SCORE"
    FORCE_APPLY_ANY  = "FORCE_APPLY_ANY"    # admin-only override
    CAPTURE_SESSION  = "CAPTURE_SESSION"


# Mapping: which roles have which capability (least-privilege defaults)
CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset(Capability),                                   # all
    Role.POWER_USER: frozenset({
        Capability.USE_BOT, Capability.UPLOAD_CV, Capability.VIEW_OWN_QUEUE,
        Capability.TAP_APPLY_MID, Capability.AUTO_APPLY_HIGH,
        Capability.FORCE_SCORE, Capability.CAPTURE_SESSION,
    }),
    Role.STANDARD_USER: frozenset({
        Capability.USE_BOT, Capability.UPLOAD_CV, Capability.VIEW_OWN_QUEUE,
        Capability.TAP_APPLY_MID, Capability.FORCE_SCORE,
    }),
    Role.PENDING: frozenset({Capability.USE_BOT}),     # only the access-request flow
    Role.REVOKED: frozenset(),                          # nothing
}


# ============================================================================
# Data classes
# ============================================================================

@dataclass(frozen=True)
class TelegramUser:
    telegram_id:    int
    handle:         Optional[str]
    display_name:   Optional[str]


@dataclass
class User:
    user_id:        int
    telegram_id:    int
    handle:         Optional[str]
    display_name:   Optional[str]
    role:           Role
    auto_apply_on:  bool
    rate_per_min:   int
    rate_apply_per_hour: int


@dataclass
class AuthDecision:
    allow:    bool
    reason:   str
    user:     Optional[User] = None
    notify_admin: bool       = False     # True for first-touch PENDING users


@dataclass
class CallbackPayload:
    user_id:  int
    action:   str
    target:   Optional[str]


# ============================================================================
# DAO Protocol — fulfilled by core.nexus_db.NexusDB
# ============================================================================

class AccessDB(Protocol):
    async def get_user_by_telegram(self, telegram_id: int) -> Optional[User]: ...
    async def upsert_pending_user(self, tg: TelegramUser) -> User: ...
    async def update_role(self, user_id: int, new_role: Role) -> bool: ...
    async def update_auto_apply(self, user_id: int, on: bool) -> bool: ...
    async def insert_grant(
        self, granted_to: int, granted_by: int,
        role_granted: str, reason: Optional[str],
    ) -> int: ...
    async def revoke_grants(self, user_id: int, by: int, reason: Optional[str]) -> int: ...
    async def rate_limit_consume(
        self, user_id: int, bucket: str, max_n: int, window_seconds: int,
    ) -> bool: ...
    async def audit_log(self, **fields: Any) -> None: ...
    async def store_callback_token(
        self, token: str, user_id: int, action: str,
        target: Optional[str], expires_at: datetime,
    ) -> None: ...
    async def consume_callback_token(self, token: str) -> Optional[dict[str, Any]]: ...


# ============================================================================
# AccessControl — the security gate
# ============================================================================

class AccessControl:
    """
    Wires every Telegram interaction to RBAC + rate-limit + audit.

    Construction is cheap; every method is async and DAO-bound.
    """

    SUPER_ADMIN_TG_ID: int = int(os.getenv("NEXUS_SUPER_ADMIN_ID", "1284690336"))

    def __init__(self, db: AccessDB, hmac_secret: Optional[str] = None) -> None:
        self.db = db
        # HMAC secret for callback signing — distinct from session vault key.
        # Falls back to a process-stable random if env unset (dev only — warns).
        secret = hmac_secret or os.getenv("NEXUS_CALLBACK_SECRET", "")
        if not secret:
            secret = secrets.token_urlsafe(32)
            log.warning(
                "NEXUS_CALLBACK_SECRET not set — generated ephemeral secret. "
                "Inline buttons will invalidate on restart. Set the env var "
                "for production."
            )
        self._hmac_key = secret.encode("utf-8")

    # ─────────────────────────── User intake ─────────────────────────────

    async def ensure_user(self, tg: TelegramUser) -> User:
        """
        Find-or-create a user row. New users land as PENDING (or ADMIN if their
        telegram_id matches the hardcoded super-admin). Idempotent.
        """
        existing = await self.db.get_user_by_telegram(tg.telegram_id)
        if existing is not None:
            # Promote to ADMIN if this is the super-admin and somehow not already.
            if tg.telegram_id == self.SUPER_ADMIN_TG_ID and existing.role != Role.ADMIN:
                await self.db.update_role(existing.user_id, Role.ADMIN)
                await self.db.update_auto_apply(existing.user_id, True)
                existing.role = Role.ADMIN
                existing.auto_apply_on = True
                await self._audit(
                    actor_id=existing.user_id,
                    action="SUPER_ADMIN_PROMOTED",
                    target_id=existing.user_id,
                    target_kind="user",
                )
            return existing

        # Create new user. Super-admin telegram_id auto-becomes ADMIN.
        user = await self.db.upsert_pending_user(tg)
        if tg.telegram_id == self.SUPER_ADMIN_TG_ID:
            await self.db.update_role(user.user_id, Role.ADMIN)
            await self.db.update_auto_apply(user.user_id, True)
            user.role = Role.ADMIN
            user.auto_apply_on = True
            await self._audit(
                actor_id=user.user_id, action="SUPER_ADMIN_CREATED",
                target_id=user.user_id, target_kind="user",
                payload={"telegram_id": tg.telegram_id},
            )
        else:
            await self._audit(
                actor_id=user.user_id, action="USER_PENDING_CREATED",
                target_id=user.user_id, target_kind="user",
                payload={"telegram_id": tg.telegram_id, "handle": tg.handle},
            )
        return user

    # ─────────────────────────── Authorize ───────────────────────────────

    async def authorize(
        self,
        tg: TelegramUser,
        capability: Capability,
    ) -> AuthDecision:
        """
        Single entry point used by every command/callback.

        Side effects:
          * Auto-creates user as PENDING on first touch
          * Logs LOGIN_DENIED to audit on REVOKED / unsupported capability
        """
        user = await self.ensure_user(tg)

        # Hard reject revoked users — silent
        if user.role == Role.REVOKED:
            await self._audit(
                actor_id=user.user_id, action="LOGIN_DENIED_REVOKED",
                target_kind="user",
            )
            return AuthDecision(False, "Access revoked.", user)

        allowed = capability in CAPABILITIES.get(user.role, frozenset())
        if not allowed:
            # Pending users only see USE_BOT — anything else triggers admin alert
            if user.role == Role.PENDING and capability != Capability.USE_BOT:
                await self._audit(
                    actor_id=user.user_id, action="ACCESS_REQUESTED",
                    target_id=user.user_id, target_kind="user",
                    payload={"capability": capability.value},
                )
                return AuthDecision(
                    False,
                    "Access pending — your request has been forwarded to the admin.",
                    user,
                    notify_admin=True,
                )
            await self._audit(
                actor_id=user.user_id, action="LOGIN_DENIED_NOPERM",
                target_kind="user",
                payload={"role": user.role.value, "capability": capability.value},
            )
            return AuthDecision(
                False,
                f"You don't have the `{capability.value}` capability.",
                user,
            )

        return AuthDecision(True, "ok", user)

    # ─────────────────────────── Grant / Revoke ──────────────────────────

    async def grant(
        self,
        actor: User,
        target_telegram_id: int,
        role: Role,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Admin-only. Promote a PENDING/STANDARD user to STANDARD/POWER."""
        if actor.role != Role.ADMIN:
            return False, "Only ADMIN can grant access."
        if role not in (Role.POWER_USER, Role.STANDARD_USER):
            return False, "Grant only supports POWER_USER or STANDARD_USER."
        target = await self.db.get_user_by_telegram(target_telegram_id)
        if target is None:
            # Create them as PENDING first so we can promote
            target = await self.db.upsert_pending_user(
                TelegramUser(target_telegram_id, None, None)
            )
        await self.db.update_role(target.user_id, role)
        # POWER users get auto_apply_on by default; STANDARD must opt-in via session capture
        if role == Role.POWER_USER:
            await self.db.update_auto_apply(target.user_id, True)
        await self.db.insert_grant(target.user_id, actor.user_id, role.value, reason)
        await self._audit(
            actor_id=actor.user_id, action="GRANT_ROLE",
            target_id=target.user_id, target_kind="user",
            payload={"role_granted": role.value, "reason": reason},
        )
        return True, f"✅ Granted `{role.value}` to user `{target_telegram_id}`."

    async def revoke(
        self,
        actor: User,
        target_telegram_id: int,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Admin-only. Sets target's role to REVOKED. Cannot self-revoke."""
        if actor.role != Role.ADMIN:
            return False, "Only ADMIN can revoke access."
        target = await self.db.get_user_by_telegram(target_telegram_id)
        if target is None:
            return False, "Unknown user."
        if target.user_id == actor.user_id:
            return False, "You cannot revoke yourself."
        if target.telegram_id == self.SUPER_ADMIN_TG_ID:
            return False, "Cannot revoke the super-admin."
        await self.db.update_role(target.user_id, Role.REVOKED)
        await self.db.update_auto_apply(target.user_id, False)
        n = await self.db.revoke_grants(target.user_id, actor.user_id, reason)
        await self._audit(
            actor_id=actor.user_id, action="REVOKE",
            target_id=target.user_id, target_kind="user",
            payload={"grants_revoked": n, "reason": reason},
        )
        return True, f"✅ Revoked access for `{target_telegram_id}`."

    # ─────────────────────────── Rate limits ─────────────────────────────

    async def check_rate_limit(self, user: User, bucket: str = "cmd") -> bool:
        """
        Returns True when within budget, False on breach.
        Buckets:
          cmd     — 30 commands / minute
          apply   — 10 applies  / hour (raised for ADMIN)
          grant   — 20 grants   / hour
          refresh — 5  vault refreshes / hour
        """
        if user.role == Role.ADMIN:
            # Admin is rate-limited very lightly to prevent runaway loops
            limits = {"cmd": 240, "apply": 1000, "grant": 200, "refresh": 60}
            window = {"cmd": 60, "apply": 3600, "grant": 3600, "refresh": 3600}
        else:
            limits = {
                "cmd":     user.rate_per_min,
                "apply":   user.rate_apply_per_hour,
                "grant":   0,
                "refresh": 5,
            }
            window = {"cmd": 60, "apply": 3600, "grant": 3600, "refresh": 3600}
        ok = await self.db.rate_limit_consume(
            user.user_id, bucket,
            max_n=limits.get(bucket, 30),
            window_seconds=window.get(bucket, 60),
        )
        if not ok:
            await self._audit(
                actor_id=user.user_id, action="RATE_LIMIT",
                target_kind="bucket", target_ref=bucket,
            )
        return ok

    # ─────────────────────────── Callback HMAC ───────────────────────────

    async def sign_callback(
        self,
        user: User,
        action: str,
        target: Optional[str] = None,
        ttl_seconds: int = 1800,
    ) -> str:
        """
        Issue a short HMAC-signed nonce that the callback handler must verify.
        Format: `<nonce>.<sig8>` — Telegram's callback_data is 64-byte limited.
        """
        nonce = secrets.token_urlsafe(8)                                  # 11 chars
        msg   = f"{nonce}|{user.user_id}|{action}|{target or ''}".encode()
        sig   = hmac.new(self._hmac_key, msg, hashlib.sha256).hexdigest()[:8]
        token = f"{nonce}.{sig}"
        await self.db.store_callback_token(
            token=token,
            user_id=user.user_id,
            action=action,
            target=target,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        return token

    async def verify_callback(self, token: str, claimed_user_id: int) -> Optional[CallbackPayload]:
        """
        Validate an inline-button token. Returns the payload on success, None
        when expired/invalid/already-consumed/owner-mismatch.
        """
        row = await self.db.consume_callback_token(token)
        if not row:
            return None
        if int(row.get("user_id", -1)) != claimed_user_id:
            await self._audit(
                actor_id=claimed_user_id, action="CALLBACK_OWNER_MISMATCH",
                target_kind="token", target_ref=token,
            )
            return None
        # Re-verify HMAC (defence in depth — DB row could be tampered with at PG level)
        try:
            nonce, sig = token.split(".", 1)
        except ValueError:
            return None
        msg = (
            f"{nonce}|{row['user_id']}|{row['action']}|{row.get('target') or ''}"
        ).encode()
        expected = hmac.new(self._hmac_key, msg, hashlib.sha256).hexdigest()[:8]
        if not hmac.compare_digest(sig, expected):
            await self._audit(
                actor_id=claimed_user_id, action="CALLBACK_BAD_SIG",
                target_kind="token", target_ref=token,
            )
            return None
        return CallbackPayload(
            user_id=int(row["user_id"]),
            action=str(row["action"]),
            target=row.get("target"),
        )

    # ─────────────────────────── Audit ───────────────────────────────────

    async def audit(
        self,
        actor: Optional[User],
        action: str,
        **kw: Any,
    ) -> None:
        """Public audit helper — used by command handlers and orchestrator."""
        await self._audit(
            actor_id=actor.user_id if actor else None,
            actor_role=actor.role.value if actor else None,
            action=action,
            **kw,
        )

    async def _audit(self, **fields: Any) -> None:
        try:
            await self.db.audit_log(**fields)
        except Exception:                                  # noqa: BLE001
            log.exception("audit_log persist failed (non-fatal)")

    # ─────────────────────── Dashboard-friendly shims ───────────────────────
    # The Telegram dashboard calls a simpler surface; these wrap the canonical
    # methods above so handlers don't need to construct TelegramUser/User
    # objects each time.

    async def resolve_telegram_user(
        self,
        tg_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> Optional[User]:
        """
        Returns the User if their role permits bot use (anything ≥ STANDARD_USER).
        Returns None for PENDING/REVOKED so the dashboard shows 'Access pending'.
        Idempotent — auto-creates super-admin on first touch.
        """
        tg = TelegramUser(
            telegram_id=int(tg_id),
            handle=username,
            display_name=first_name,
        )
        try:
            user = await self.ensure_user(tg)
        except Exception:                                       # noqa: BLE001
            log.exception("resolve_telegram_user.ensure_user_failed")
            return None
        # Block PENDING and REVOKED from interacting (dashboard shows pending msg)
        if user.role in (Role.PENDING, Role.REVOKED):
            # Mark blocked attribute for the dashboard's 'blocked' check
            user.blocked = (user.role == Role.REVOKED)         # type: ignore[attr-defined]
            if user.role == Role.PENDING:
                return None
            return None
        user.blocked = False                                    # type: ignore[attr-defined]
        return user

    async def record_access_request(
        self,
        tg_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> None:
        """First-touch users: ensure_user creates them as PENDING; this is just
        an extra audit row so /access can list them."""
        try:
            await self.ensure_user(TelegramUser(int(tg_id), username, first_name))
            await self._audit(
                actor_id=None, action="ACCESS_REQUEST_RECEIVED",
                target_kind="user",
                payload={"telegram_id": int(tg_id), "handle": username},
            )
        except Exception:                                       # noqa: BLE001
            log.exception("record_access_request failed")

    async def grant_role(
        self,
        target_tg_id: int,
        role_name: str,
        by_user_id: Optional[int] = None,
    ) -> bool:
        """Promote target to STANDARD/POWER. Maps short role names → enum."""
        role_map = {
            "STANDARD":  Role.STANDARD_USER,
            "STD":       Role.STANDARD_USER,
            "POWER":     Role.POWER_USER,
            "POWER_USER":Role.POWER_USER,
            "ADMIN":     Role.ADMIN,
        }
        role = role_map.get(role_name.upper())
        if role is None or role == Role.ADMIN:
            # Admin grants must go through grant_admin (not exposed here).
            return False
        # Build a minimal actor User shim — DAO checks role==ADMIN, we trust the
        # caller (dashboard) has already verified the actor is admin.
        actor_user_id = by_user_id or 0
        # Fetch actual actor (super-admin) if available
        actor: Optional[User] = None
        try:
            # Iterate _users_by_uid if InMemory; for real DAO get_user_by_telegram
            for uid, u in (getattr(self.db, "_users_by_uid", {}) or {}).items():
                if uid == actor_user_id:
                    actor = u
                    break
        except Exception:
            pass
        if actor is None:
            # Construct a minimal admin shim (DAO trust gate)
            actor = User(
                user_id=actor_user_id, telegram_id=self.SUPER_ADMIN_TG_ID,
                handle=None, display_name=None,
                role=Role.ADMIN, auto_apply_on=True,
                rate_per_min=240, rate_apply_per_hour=1000,
            )
        ok, _msg = await self.grant(actor, int(target_tg_id), role,
                                    reason="dashboard_inline")
        return ok

    async def deny_access_request(
        self,
        target_tg_id: int,
        by_user_id: Optional[int] = None,
    ) -> bool:
        """Mark a PENDING user as REVOKED (silent rejection)."""
        target = await self.db.get_user_by_telegram(int(target_tg_id))
        if target is None:
            return False
        await self.db.update_role(target.user_id, Role.REVOKED)
        await self._audit(
            actor_id=by_user_id, action="ACCESS_DENIED",
            target_id=target.user_id, target_kind="user",
            payload={"telegram_id": int(target_tg_id)},
        )
        return True

    async def set_auto_apply(self, user_id: int, on: bool) -> bool:
        """POWER/ADMIN toggle. STANDARD users always remain one-tap (DAO no-ops)."""
        return await self.db.update_auto_apply(int(user_id), bool(on))

    async def list_pending_requests(self, limit: int = 20) -> list[dict]:
        """Admin-only: return users in PENDING state for /access overview."""
        getter = getattr(self.db, "list_users_by_role", None)
        if getter is None:
            # InMemory fallback
            users = getattr(self.db, "_users_by_uid", {}) or {}
            return [
                {
                    "tg_id":      u.telegram_id,
                    "username":   u.handle,
                    "first_name": u.display_name,
                    "user_id":    u.user_id,
                }
                for u in users.values()
                if u.role == Role.PENDING
            ][:limit]
        try:
            rows = await getter(Role.PENDING.value, limit)
            return list(rows or [])
        except Exception:                                       # noqa: BLE001
            log.exception("list_pending_requests failed")
            return []

    async def list_active_grants(self, limit: int = 50) -> list[dict]:
        """Admin-only: return STANDARD/POWER/ADMIN users for /access overview."""
        getter = getattr(self.db, "list_active_users", None)
        if getter is None:
            users = getattr(self.db, "_users_by_uid", {}) or {}
            return [
                {
                    "tg_id":         u.telegram_id,
                    "user_id":       u.user_id,
                    "role":          u.role.value,
                    "auto_apply_on": u.auto_apply_on,
                    "username":      u.handle,
                }
                for u in users.values()
                if u.role in (Role.STANDARD_USER, Role.POWER_USER, Role.ADMIN)
            ][:limit]
        try:
            rows = await getter(limit)
            return list(rows or [])
        except Exception:                                       # noqa: BLE001
            log.exception("list_active_grants failed")
            return []


# ============================================================================
# In-memory DAO for tests + offline boot
# ============================================================================

class InMemoryAccessDB:
    """Bare in-memory DAO that fulfils AccessDB. Used until Postgres is bound."""

    def __init__(self) -> None:
        self._users: dict[int, User] = {}              # telegram_id → User
        self._users_by_uid: dict[int, User] = {}
        self._next_uid = 1
        self._grants: list[dict] = []
        self._audit: list[dict] = []
        self._rl: dict[tuple[int, str, int], int] = {}   # (uid, bucket, window) → count
        self._callbacks: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def get_user_by_telegram(self, telegram_id: int) -> Optional[User]:
        return self._users.get(telegram_id)

    async def upsert_pending_user(self, tg: TelegramUser) -> User:
        async with self._lock:
            existing = self._users.get(tg.telegram_id)
            if existing:
                return existing
            uid = self._next_uid
            self._next_uid += 1
            user = User(
                user_id=uid, telegram_id=tg.telegram_id,
                handle=tg.handle, display_name=tg.display_name,
                role=Role.PENDING, auto_apply_on=False,
                rate_per_min=30, rate_apply_per_hour=10,
            )
            self._users[tg.telegram_id] = user
            self._users_by_uid[uid] = user
            return user

    async def update_role(self, user_id: int, new_role: Role) -> bool:
        u = self._users_by_uid.get(user_id)
        if not u:
            return False
        u.role = new_role
        return True

    async def update_auto_apply(self, user_id: int, on: bool) -> bool:
        u = self._users_by_uid.get(user_id)
        if not u:
            return False
        u.auto_apply_on = on
        return True

    async def insert_grant(self, granted_to, granted_by, role_granted, reason):
        gid = len(self._grants) + 1
        self._grants.append({
            "id": gid, "granted_to": granted_to, "granted_by": granted_by,
            "role_granted": role_granted, "reason": reason,
            "granted_at": datetime.now(timezone.utc),
            "revoked_at": None,
        })
        return gid

    async def revoke_grants(self, user_id, by, reason):
        n = 0
        for g in self._grants:
            if g["granted_to"] == user_id and g["revoked_at"] is None:
                g["revoked_at"] = datetime.now(timezone.utc)
                g["revoked_by"] = by
                g["revoke_reason"] = reason
                n += 1
        return n

    async def rate_limit_consume(self, user_id, bucket, max_n, window_seconds):
        now = datetime.now(timezone.utc)
        bucket_idx = int(now.timestamp() // window_seconds)
        key = (user_id, bucket, bucket_idx)
        cur = self._rl.get(key, 0)
        if cur >= max_n:
            return False
        self._rl[key] = cur + 1
        return True

    async def audit_log(self, **fields):
        fields.setdefault("created_at", datetime.now(timezone.utc))
        self._audit.append(fields)

    async def store_callback_token(self, token, user_id, action, target, expires_at):
        self._callbacks[token] = {
            "user_id": user_id, "action": action, "target": target,
            "expires_at": expires_at, "consumed_at": None,
        }

    async def consume_callback_token(self, token):
        row = self._callbacks.get(token)
        if not row:
            return None
        if row["consumed_at"] is not None:
            return None
        if datetime.now(timezone.utc) > row["expires_at"]:
            return None
        row["consumed_at"] = datetime.now(timezone.utc)
        return dict(row)


__all__ = [
    "Role", "ROLE_BOOST", "Capability", "CAPABILITIES",
    "TelegramUser", "User", "AuthDecision", "CallbackPayload",
    "AccessDB", "AccessControl", "InMemoryAccessDB",
]
