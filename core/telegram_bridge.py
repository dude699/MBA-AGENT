"""
NEXUS v0.2 — Telegram Bridge
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Mounts every NEXUS Telegram command + callback + document handler onto the
EXISTING PRISM TGApplication (a12_telegram_reporter._build_app), instead of
spinning up a second bot.

Why a bridge:
  * The Telegram Bot API only allows ONE poller per token. Running both
    PRISM's a12 reporter AND NEXUS's TelegramDashboard against the same
    bot token would constantly throw `Conflict: terminated by other
    getUpdates request`.
  * PRISM owns the polling loop (proven, with stale-session kill, instance
    lock, retry/backoff). NEXUS just borrows handler slots.

Public surface
--------------
  attach_nexus_to_prism_app(prism_app, *, dashboard, runtime) -> int
      Registers all NEXUS handlers on the given Application. Returns the
      number of handlers added. Idempotent — safe to call twice (it tracks
      a `_nexus_attached` marker on the app object).

  detach_nexus(prism_app) -> int
      Removes the NEXUS handlers (best-effort; PTB has no native remove).

Wiring (called from main.py, AFTER NexusRuntime starts):

    from core.telegram_bridge import attach_nexus_to_prism_app
    attach_nexus_to_prism_app(
        prism_telegram_reporter._app,           # the PTB Application
        dashboard=runtime._dashboard,           # NEXUS dashboard instance
        runtime=runtime,                        # for /nexus snapshot, etc.
    )

Conflict resolution with PRISM commands
---------------------------------------
PRISM already registers /apply, /status, /help, /cancel, /queue, /jobs etc.
We rename overlapping NEXUS commands with an `n` prefix:

    /napply, /nstatus, /nhelp, /ncancel, /nqueue, /napps

NEXUS-only commands keep their natural names since PRISM doesn't use them:

    /me, /cv, /auto, /access, /pending, /digest, /pause, /resume,
    /vault, /risk, /interview, /score, /captcha, /followup, /nexus

Document handler: PRISM does NOT register one for documents, so we attach
the NEXUS _on_document handler at high priority (group=-1) to claim CV
PDFs/DOCX/TXT before any text fallthrough.

Inline button callbacks: registered with a `pattern` so they only fire on
NEXUS-prefixed callback_data (apply:, skip:, snooze:, grant:, brief:,
refresh:, captcha_*:, pause:, resume:, customise:).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("nexus.telegram_bridge")


# ============================================================================
# Soft import — telegram (PTB v20+). Bridge is a no-op without it.
# ============================================================================
try:
    from telegram.ext import (
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )
    TG_AVAILABLE = True
except Exception:                                                    # pragma: no cover
    TG_AVAILABLE = False
    CommandHandler = None        # type: ignore
    CallbackQueryHandler = None  # type: ignore
    MessageHandler = None        # type: ignore
    filters = None               # type: ignore


# ============================================================================
# Command map — NEXUS commands → renamed slots that don't collide with PRISM
# ============================================================================
#
# Format:  (telegram_command, dashboard_handler_attr_name)
#
NEXUS_COMMANDS: list[tuple[str, str]] = [
    # ── overlapping with PRISM → renamed with `n` prefix ──────────────
    ("napply",   "_cmd_apply"),       # PRISM has /apply
    ("nstatus",  "_cmd_status"),      # PRISM has /status
    ("nhelp",    "_cmd_help"),        # PRISM has /help
    # ── NEXUS-only (no clash) ────────────────────────────────────────
    ("me",       "_cmd_me"),
    ("cv",       "_cmd_cv"),
    ("auto",     "_cmd_auto"),
    ("access",   "_cmd_access"),
    ("pending",  "_cmd_pending"),
    ("digest",   "_cmd_digest"),
    ("pause",    "_cmd_pause"),
    ("resume",   "_cmd_resume"),
    ("vault",    "_cmd_vault"),
    ("risk",     "_cmd_risk"),
    ("interview","_cmd_interview"),
    ("score",    "_cmd_score"),
    ("captcha",  "_cmd_captcha_text"),
    ("followup", "_cmd_followup"),
]

# Inline callback verbs that NEXUS owns. Pattern is anchored at start.
NEXUS_CALLBACK_VERBS = (
    "apply", "skip", "snooze", "grant",
    "brief", "refresh", "customise",
    "pause", "resume",
    "captcha_type", "captcha_abort",
)


# ============================================================================
# Public API
# ============================================================================

def attach_nexus_to_prism_app(
    prism_app: Any,
    *,
    dashboard: Any,
    runtime: Optional[Any] = None,
) -> int:
    """
    Register every NEXUS handler on the live PRISM TGApplication.

    Args:
        prism_app: The python-telegram-bot Application instance built by
                   PRISM's a12 reporter (see _build_app).
        dashboard: A live NEXUS TelegramDashboard instance (constructed but
                   NOT started — we don't want it to spin up its own polling
                   loop). Its command handler methods are reused as-is.
        runtime:   The NexusRuntime instance — used for the optional /nexus
                   snapshot command and for cross-references like the
                   scoring loop's enqueue_user trigger.

    Returns:
        Number of handlers added.
    """
    if not TG_AVAILABLE:
        log.warning("telegram_bridge.skip — python-telegram-bot not installed")
        return 0
    if prism_app is None:
        log.warning("telegram_bridge.skip — prism_app is None")
        return 0
    if dashboard is None:
        log.warning("telegram_bridge.skip — dashboard is None")
        return 0
    if getattr(prism_app, "_nexus_attached", False):
        log.info("telegram_bridge.idempotent — already attached, skipping")
        return 0

    added = 0

    # ── 1. Command handlers ──────────────────────────────────────────────
    for cmd, attr in NEXUS_COMMANDS:
        handler_fn = getattr(dashboard, attr, None)
        if handler_fn is None:
            log.debug("telegram_bridge.skip cmd=%s missing handler %s", cmd, attr)
            continue
        try:
            prism_app.add_handler(CommandHandler(cmd, handler_fn))
            added += 1
        except Exception:                                            # noqa: BLE001
            log.exception("telegram_bridge.add_command_failed cmd=%s", cmd)

    # ── 2. /nexus — runtime snapshot ────────────────────────────────────
    if runtime is not None:
        try:
            prism_app.add_handler(CommandHandler("nexus", _make_nexus_cmd(runtime)))
            added += 1
        except Exception:                                            # noqa: BLE001
            log.exception("telegram_bridge.add_nexus_cmd_failed")

    # ── 3. Inline callback handler — gated by pattern so PRISM callbacks
    #     never get hijacked. ─────────────────────────────────────────────
    on_callback = getattr(dashboard, "_on_callback", None)
    if on_callback is not None:
        try:
            verbs = "|".join(NEXUS_CALLBACK_VERBS)
            pattern = rf"^({verbs}):"
            prism_app.add_handler(
                CallbackQueryHandler(on_callback, pattern=pattern),
            )
            added += 1
        except Exception:                                            # noqa: BLE001
            log.exception("telegram_bridge.add_callback_failed")

    # ── 4. Document upload (CV intake) — PRISM doesn't claim Document.ALL
    #     so we register at default group with high priority. ─────────────
    on_document = getattr(dashboard, "_on_document", None)
    if on_document is not None and MessageHandler is not None and filters is not None:
        try:
            prism_app.add_handler(
                MessageHandler(filters.Document.ALL, on_document),
                group=-1,        # before any default-group catchall
            )
            added += 1
        except Exception:                                            # noqa: BLE001
            log.exception("telegram_bridge.add_document_failed")

    # ── 5. Daily digest job — only schedule if PRISM's job_queue is alive
    #     and the dashboard's config asks for it. ────────────────────────
    job_queue = getattr(prism_app, "job_queue", None)
    cfg = getattr(dashboard, "cfg", None)
    if job_queue is not None and cfg is not None and getattr(cfg, "enable_digest", False):
        digest_job = getattr(dashboard, "_job_daily_digest", None)
        digest_time = getattr(dashboard.__class__, "_digest_utc_time", None)
        if digest_job is not None and digest_time is not None:
            try:
                job_queue.run_daily(
                    digest_job,
                    time=digest_time(),                              # 21:00 IST = 15:30 UTC
                    name="nexus_daily_digest",
                )
                added += 1
            except Exception:                                        # noqa: BLE001
                log.exception("telegram_bridge.schedule_digest_failed")

    # Mark the app so a second call is a no-op
    try:
        prism_app._nexus_attached = True                              # type: ignore[attr-defined]
        prism_app._nexus_dashboard = dashboard                        # type: ignore[attr-defined]
    except Exception:
        pass

    log.info(
        "telegram_bridge.attached commands=%d cb=1 doc=1 digest=%s total=%d",
        len([c for c, a in NEXUS_COMMANDS if hasattr(dashboard, a)]),
        bool(getattr(prism_app, "job_queue", None) and cfg and cfg.enable_digest),
        added,
    )
    return added


def detach_nexus(prism_app: Any) -> int:
    """
    Best-effort detach. PTB has no first-class remove API, so we rebuild the
    handlers list filtered for handlers we added.

    Returns the number of handlers removed.
    """
    if not TG_AVAILABLE or prism_app is None:
        return 0
    if not getattr(prism_app, "_nexus_attached", False):
        return 0
    nexus_cmds = {c for c, _ in NEXUS_COMMANDS} | {"nexus"}
    removed = 0
    try:
        # PTB v20: handlers live under prism_app.handlers (dict[group, list])
        for group_id, handlers in list(prism_app.handlers.items()):
            keep = []
            for h in handlers:
                # CommandHandler.commands → frozenset of command names
                cmds = getattr(h, "commands", None)
                if cmds and isinstance(cmds, (set, frozenset, tuple, list)):
                    if any(c in nexus_cmds for c in cmds):
                        removed += 1
                        continue
                # CallbackQueryHandler we added uses a pattern starting with our verbs
                pat = getattr(h, "pattern", None)
                if pat is not None and hasattr(pat, "pattern"):
                    if pat.pattern.startswith("^(") and "apply" in pat.pattern and "skip" in pat.pattern:
                        removed += 1
                        continue
                keep.append(h)
            prism_app.handlers[group_id] = keep
    except Exception:                                                # noqa: BLE001
        log.exception("telegram_bridge.detach_failed")
        return 0
    try:
        prism_app._nexus_attached = False                             # type: ignore[attr-defined]
    except Exception:
        pass
    log.info("telegram_bridge.detached removed=%d", removed)
    return removed


# ============================================================================
# /nexus command — runtime snapshot for the bot
# ============================================================================

def _make_nexus_cmd(runtime: Any):
    """Curry the runtime into a /nexus handler that prints the layer map."""
    async def _cmd_nexus(update, context):
        try:
            snap = runtime.snapshot() if hasattr(runtime, "snapshot") else {}
        except Exception:                                            # noqa: BLE001
            snap = {}
        layers_ok = snap.get("layers_ok") or []
        layers_fail = snap.get("layers_fail") or []
        triad = snap.get("triad_live")
        backend = snap.get("db_backend") or "in-memory"
        portals = snap.get("portals") or {}
        text = (
            f"*🛰 NEXUS v{snap.get('version', '0.2.0')}*\n"
            f"Started: `{snap.get('started_at', '?')}`\n"
            f"DB backend: `{backend}`\n"
            f"Stealth triad live: *{'YES' if triad else 'no'}*\n\n"
            f"*Layers OK ({len(layers_ok)}):*\n"
            + "\n".join(f"• `{x}`" for x in layers_ok[:10])
            + (f"\n\n*Layers failed ({len(layers_fail)}):*\n"
               + "\n".join(f"• `{x}`" for x in layers_fail) if layers_fail else "")
            + (f"\n\n*Portals:* {len(portals)} configured" if portals else "")
        )
        try:
            from telegram.constants import ParseMode
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(text)
    return _cmd_nexus


__all__ = [
    "attach_nexus_to_prism_app",
    "detach_nexus",
    "NEXUS_COMMANDS",
    "NEXUS_CALLBACK_VERBS",
    "TG_AVAILABLE",
]
