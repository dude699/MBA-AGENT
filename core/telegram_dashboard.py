"""
NEXUS v0.2 — Layer 9: Telegram Intelligence Dashboard
================================================================================

The single human surface for the entire system. Built on python-telegram-bot
v20+ async. Implements the full command + inline-button + digest spec from
the architecture doc, including:

  • Command surface  : /start, /status, /pause, /resume, /pending, /digest,
                        /interview, /score <url>, /apply <url>, /vault,
                        /health, /risk, /reload, /captcha, /followup
  • Inline buttons   : ✅ Apply Now · 🛑 Skip · 📝 Customise · 🔍 Brief Me ·
                        🔁 Refresh Session · ⏸ Pause Portal · ▶ Resume
  • Live alerts      : CAPTCHA T3 relay, REFRESH session, RISK breach,
                        Interview invite, Manual review (60–80 score),
                        Deadline cliff (24h / 6h)
  • Auto digests     : 9 PM IST daily summary (per-portal funnel)
  • Audit            : every command + every callback persisted to telegram_audit

This module is import-safe even when python-telegram-bot is not installed —
heavy imports are guarded with TG_AVAILABLE flag, the rest is plain async
glue + protocols so the orchestrator can wire it without crashing on slim
Render dynos. The actual long-poll loop runs on the worker dyno.

Per the doc, this is the ONLY human-facing surface. Everything else lives
behind it. The Telegram bot is the "cockpit"; NEXUS is the autopilot.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

# ────────────────────────────────────────────────────────────────────────────
# Soft import of python-telegram-bot v20 (heavy dep). Module loads cleanly
# without it; the long-poll loop is a no-op when missing.
# ────────────────────────────────────────────────────────────────────────────
try:
    from telegram import (
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Update,
    )
    from telegram.constants import ParseMode
    from telegram.ext import (
        Application,
        ApplicationBuilder,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
    )

    TG_AVAILABLE = True
except Exception:  # pragma: no cover
    TG_AVAILABLE = False
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore
    Update = Any  # type: ignore
    ContextTypes = Any  # type: ignore
    Application = Any  # type: ignore

from core.nexus_config import (
    PORTALS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    portal_supported,
)

logger = logging.getLogger(__name__)


# ============================================================================
#  Protocols (zero hard dependency on the rest of NEXUS)
# ============================================================================

class OrchestratorAPI(Protocol):
    """The minimum surface telegram_dashboard needs from the orchestrator."""

    async def status_snapshot(self) -> Dict[str, Any]: ...
    async def pause_portal(self, portal: str) -> bool: ...
    async def resume_portal(self, portal: str) -> bool: ...
    async def pending_review(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    async def force_apply(self, job_id: str) -> Dict[str, Any]: ...
    async def force_skip(self, job_id: str) -> bool: ...
    async def score_url(self, url: str) -> Dict[str, Any]: ...


class VaultAPI(Protocol):
    async def health_summary(self) -> List[Dict[str, Any]]: ...
    async def request_refresh(self, portal: str) -> bool: ...


class InterviewAPI(Protocol):
    async def upcoming_briefings(self, limit: int = 5) -> List[Dict[str, Any]]: ...
    async def get_briefing(self, signal_id: str) -> Optional[Dict[str, Any]]: ...


class CaptchaRelayAPI(Protocol):
    """Set when L5 CAPTCHA T3 needs human relay; resolves the future."""

    async def submit_answer(self, challenge_id: str, answer: str) -> bool: ...


class AuditDB(Protocol):
    async def log(self, **fields: Any) -> None: ...


# ============================================================================
#  Data classes
# ============================================================================

@dataclass
class DigestRow:
    portal: str
    discovered: int = 0
    scored: int = 0
    applied: int = 0
    captcha: int = 0
    failed: int = 0
    risk_level: str = "GREEN"  # GREEN / AMBER / RED


@dataclass
class PendingReviewItem:
    job_id: str
    portal: str
    company: str
    title: str
    score: float
    score_band: str  # 60-80 → "MANUAL_REVIEW"
    deadline_hours: Optional[float] = None
    apply_url: str = ""


# ============================================================================
#  Markup helpers (graceful when TG not installed)
# ============================================================================

def _btn(label: str, data: str):
    if not TG_AVAILABLE:
        return None
    return InlineKeyboardButton(label, callback_data=data)


def _kb(rows: List[List[Any]]):
    if not TG_AVAILABLE:
        return None
    return InlineKeyboardMarkup([[b for b in row if b is not None] for row in rows])


def _review_keyboard(item: PendingReviewItem):
    return _kb([
        [
            _btn("✅ Apply Now", f"apply:{item.job_id}"),
            _btn("🛑 Skip", f"skip:{item.job_id}"),
        ],
        [
            _btn("📝 Customise", f"customise:{item.job_id}"),
            _btn("🔍 Brief Me", f"brief:{item.job_id}"),
        ],
    ])


def _captcha_keyboard(challenge_id: str):
    return _kb([
        [
            _btn("✏️ Type Answer", f"captcha_type:{challenge_id}"),
            _btn("🛑 Abort", f"captcha_abort:{challenge_id}"),
        ]
    ])


def _session_keyboard(portal: str):
    return _kb([[_btn(f"🔁 Refresh {portal}", f"refresh:{portal}")]])


def _portal_kb(action: str):
    """Build a 2-col portal selector for /pause /resume."""
    btns: List[List[Any]] = []
    row: List[Any] = []
    for p in PORTALS:
        row.append(_btn(p, f"{action}:{p}"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    return _kb(btns)


# ============================================================================
#  Formatters
# ============================================================================

def _fmt_status(snap: Dict[str, Any]) -> str:
    lines = [
        "*🛰 NEXUS Status*",
        f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"• Queued: *{snap.get('queued', 0)}*",
        f"• Running: *{snap.get('running', 0)}*",
        f"• Applied (24h): *{snap.get('applied_24h', 0)}*",
        f"• Manual review: *{snap.get('manual_review', 0)}*",
        f"• CAPTCHA (24h): *{snap.get('captcha_24h', 0)}*",
        f"• Failed (24h): *{snap.get('failed_24h', 0)}*",
        "",
        "*Portals:*",
    ]
    for portal, info in (snap.get("portals") or {}).items():
        risk = info.get("risk", "GREEN")
        emoji = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(risk, "⚪")
        paused = " ⏸" if info.get("paused") else ""
        lines.append(f"{emoji} `{portal:<14}` {info.get('applied_today', 0):>3}/d{paused}")
    return "\n".join(lines)


def _fmt_digest(rows: List[DigestRow]) -> str:
    lines = [
        "*📊 NEXUS Daily Digest*",
        f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_",
        "",
        "```",
        f"{'Portal':<14}{'Disc':>5}{'Scrd':>5}{'Apld':>5}{'CAP':>4}{'Fail':>5}",
    ]
    for r in rows:
        lines.append(
            f"{r.portal:<14}{r.discovered:>5}{r.scored:>5}{r.applied:>5}{r.captcha:>4}{r.failed:>5}"
        )
    lines.append("```")
    return "\n".join(lines)


def _fmt_review_card(item: PendingReviewItem) -> str:
    deadline = ""
    if item.deadline_hours is not None:
        if item.deadline_hours < 6:
            deadline = f"⚠️ *{item.deadline_hours:.1f}h* deadline cliff"
        elif item.deadline_hours < 24:
            deadline = f"⏳ {item.deadline_hours:.1f}h to deadline"
        elif item.deadline_hours < 72:
            deadline = f"📅 {item.deadline_hours / 24:.1f}d to deadline"
    return (
        f"*🎯 Manual Review · {item.score:.0f}/100*\n"
        f"*{item.title}* — _{item.company}_\n"
        f"`{item.portal}` · ID: `{item.job_id}`\n"
        + (f"{deadline}\n" if deadline else "")
        + (f"\n[Open posting]({item.apply_url})" if item.apply_url else "")
    )


# ============================================================================
#  Dashboard
# ============================================================================

@dataclass
class DashboardConfig:
    bot_token: str = TELEGRAM_BOT_TOKEN or ""
    chat_id: str = TELEGRAM_CHAT_ID or ""
    enable_digest: bool = True
    digest_hour_ist: int = 21  # 9 PM IST


class TelegramDashboard:
    """
    The single human surface. Wires command handlers + inline buttons + alerts.
    Long-poll loop runs in `start()`, alert helpers (alert_*) post to chat.
    """

    def __init__(
        self,
        orch: OrchestratorAPI,
        vault: VaultAPI,
        intel: InterviewAPI,
        captcha_relay: Optional[CaptchaRelayAPI] = None,
        audit: Optional[AuditDB] = None,
        cfg: Optional[DashboardConfig] = None,
    ) -> None:
        self.orch = orch
        self.vault = vault
        self.intel = intel
        self.captcha_relay = captcha_relay
        self.audit = audit
        self.cfg = cfg or DashboardConfig()
        self._app: Optional[Application] = None
        self._captcha_pending: Dict[str, str] = {}  # user_id → challenge_id
        self._pending_cards: Dict[str, PendingReviewItem] = {}

    # ────────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if not TG_AVAILABLE:
            logger.warning("python-telegram-bot not installed; dashboard disabled.")
            return
        if not self.cfg.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN missing; dashboard disabled.")
            return

        self._app = ApplicationBuilder().token(self.cfg.bot_token).build()

        # Commands
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("digest", self._cmd_digest))
        self._app.add_handler(CommandHandler("pending", self._cmd_pending))
        self._app.add_handler(CommandHandler("pause", self._cmd_pause))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("vault", self._cmd_vault))
        self._app.add_handler(CommandHandler("health", self._cmd_health))
        self._app.add_handler(CommandHandler("interview", self._cmd_interview))
        self._app.add_handler(CommandHandler("score", self._cmd_score))
        self._app.add_handler(CommandHandler("apply", self._cmd_apply))
        self._app.add_handler(CommandHandler("risk", self._cmd_risk))
        self._app.add_handler(CommandHandler("captcha", self._cmd_captcha_text))
        self._app.add_handler(CommandHandler("followup", self._cmd_followup))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        # Inline button callbacks
        self._app.add_handler(CallbackQueryHandler(self._on_callback))

        # Daily digest job (9 PM IST = 15:30 UTC)
        if self.cfg.enable_digest and self._app.job_queue is not None:
            self._app.job_queue.run_daily(
                self._job_daily_digest,
                time=self._digest_utc_time(),
                name="nexus_daily_digest",
            )

        await self._app.initialize()
        await self._app.start()
        if self._app.updater is not None:
            await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("NEXUS Telegram dashboard online.")

    async def stop(self) -> None:
        if not self._app:
            return
        try:
            if self._app.updater is not None:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        except Exception:
            logger.exception("Error stopping dashboard.")

    @staticmethod
    def _digest_utc_time():
        # 21:00 IST = 15:30 UTC
        from datetime import time as dtime
        return dtime(hour=15, minute=30, tzinfo=timezone.utc)

    # ────────────────────────────────────────────────────────────────────
    #  Authorisation
    # ────────────────────────────────────────────────────────────────────

    def _is_authorised(self, update: Update) -> bool:
        if not self.cfg.chat_id:
            return True  # dev mode
        try:
            return str(update.effective_chat.id) == str(self.cfg.chat_id)
        except Exception:
            return False

    async def _audit(self, kind: str, payload: Dict[str, Any]) -> None:
        if self.audit is None:
            return
        try:
            await self.audit.log(
                kind=kind,
                payload=payload,
                ts=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            logger.exception("Audit log failed.")

    # ────────────────────────────────────────────────────────────────────
    #  Command handlers
    # ────────────────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        await update.message.reply_text(
            "*🛰 NEXUS v0.2 online.*\n"
            "Zero selectors. Zero bans. Zero manual input.\n\n"
            "Try /status · /pending · /digest · /help",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._audit("cmd_start", {"user": update.effective_user.id})

    async def _cmd_help(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        await update.message.reply_text(
            "*Commands:*\n"
            "/status — live system snapshot\n"
            "/digest — daily funnel digest\n"
            "/pending — manual-review queue (60-80 scores)\n"
            "/pause — pause a portal\n"
            "/resume — resume a portal\n"
            "/vault — session vault health\n"
            "/health — Risk Governor signals\n"
            "/risk — same as /health\n"
            "/interview — upcoming interview briefings\n"
            "/score <url> — score one job posting\n"
            "/apply <url> — force-apply one URL\n"
            "/captcha <answer> — supply pending CAPTCHA answer\n"
            "/followup — applied-but-unviewed >14d list",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_status(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        snap = await self.orch.status_snapshot()
        await update.message.reply_text(_fmt_status(snap), parse_mode=ParseMode.MARKDOWN)
        await self._audit("cmd_status", {})

    async def _cmd_digest(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        snap = await self.orch.status_snapshot()
        rows = self._snap_to_rows(snap)
        await update.message.reply_text(_fmt_digest(rows), parse_mode=ParseMode.MARKDOWN)
        await self._audit("cmd_digest", {})

    async def _cmd_pending(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        items_raw = await self.orch.pending_review(limit=10)
        if not items_raw:
            await update.message.reply_text("✅ No manual-review jobs pending.")
            return
        for raw in items_raw:
            item = PendingReviewItem(
                job_id=raw["job_id"],
                portal=raw.get("portal", "?"),
                company=raw.get("company", "?"),
                title=raw.get("title", "?"),
                score=float(raw.get("score", 0)),
                score_band=raw.get("score_band", "MANUAL_REVIEW"),
                deadline_hours=raw.get("deadline_hours"),
                apply_url=raw.get("apply_url", ""),
            )
            self._pending_cards[item.job_id] = item
            await update.message.reply_text(
                _fmt_review_card(item),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_review_keyboard(item),
                disable_web_page_preview=True,
            )
        await self._audit("cmd_pending", {"count": len(items_raw)})

    async def _cmd_pause(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text(
                "Choose a portal to pause:",
                reply_markup=_portal_kb("pause"),
            )
            return
        portal = args[0]
        if not portal_supported(portal):
            await update.message.reply_text(f"Unknown portal: `{portal}`", parse_mode=ParseMode.MARKDOWN)
            return
        ok = await self.orch.pause_portal(portal)
        await update.message.reply_text(
            f"⏸ Paused `{portal}`" if ok else f"⚠️ Could not pause `{portal}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._audit("cmd_pause", {"portal": portal, "ok": ok})

    async def _cmd_resume(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text(
                "Choose a portal to resume:",
                reply_markup=_portal_kb("resume"),
            )
            return
        portal = args[0]
        if not portal_supported(portal):
            await update.message.reply_text(f"Unknown portal: `{portal}`", parse_mode=ParseMode.MARKDOWN)
            return
        ok = await self.orch.resume_portal(portal)
        await update.message.reply_text(
            f"▶️ Resumed `{portal}`" if ok else f"⚠️ Could not resume `{portal}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._audit("cmd_resume", {"portal": portal, "ok": ok})

    async def _cmd_vault(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        rows = await self.vault.health_summary()
        if not rows:
            await update.message.reply_text("Vault is empty — capture a session first.")
            return
        lines = ["*🔐 Vault — Session Health*", ""]
        for r in rows:
            health = int(r.get("health", 0))
            emoji = "🟢" if health >= 60 else ("🟡" if health >= 30 else "🔴")
            age = r.get("age_days", 0)
            lines.append(
                f"{emoji} `{r.get('portal'):<14}` health={health}/100 age={age:.1f}d"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        await self._audit("cmd_vault", {})

    async def _cmd_health(self, update: Update, context) -> None:
        return await self._cmd_risk(update, context)

    async def _cmd_risk(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        snap = await self.orch.status_snapshot()
        portals = snap.get("portals") or {}
        lines = ["*🛡 Risk Governor*", ""]
        for portal, info in portals.items():
            risk = info.get("risk", "GREEN")
            emoji = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(risk, "⚪")
            apps = info.get("apps_per_hour", 0)
            cap = info.get("captcha_rate", 0.0) * 100
            err = info.get("error_rate", 0.0) * 100
            lines.append(
                f"{emoji} `{portal:<12}` apps/h={apps} cap={cap:.0f}% err={err:.0f}%"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        await self._audit("cmd_risk", {})

    async def _cmd_interview(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        rows = await self.intel.upcoming_briefings(limit=5)
        if not rows:
            await update.message.reply_text("📭 No upcoming interview briefings.")
            return
        for b in rows:
            await update.message.reply_text(
                f"*🎤 Interview · {b.get('company', '?')}*\n"
                f"{b.get('summary', '')}\n\n"
                f"*Likely Q:*\n" + "\n".join(f"• {q}" for q in (b.get('questions') or [])[:6]),
                parse_mode=ParseMode.MARKDOWN,
            )
        await self._audit("cmd_interview", {"count": len(rows)})

    async def _cmd_score(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: `/score <url>`", parse_mode=ParseMode.MARKDOWN)
            return
        url = args[0]
        await update.message.reply_text(f"⏳ Scoring `{url}` …", parse_mode=ParseMode.MARKDOWN)
        result = await self.orch.score_url(url)
        await update.message.reply_text(
            f"*Score:* {result.get('score', 0):.0f}/100\n"
            f"*Band:* `{result.get('band', '?')}`\n"
            f"*Variant:* `{result.get('variant', 'master')}`\n"
            f"*Reason:* {result.get('reason', '')}",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._audit("cmd_score", {"url": url, "score": result.get("score")})

    async def _cmd_apply(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: `/apply <job_id|url>`", parse_mode=ParseMode.MARKDOWN)
            return
        target = args[0]
        await update.message.reply_text(f"🚀 Forcing apply on `{target}` …", parse_mode=ParseMode.MARKDOWN)
        result = await self.orch.force_apply(target)
        ok = bool(result.get("success"))
        await update.message.reply_text(
            f"{'✅' if ok else '❌'} {result.get('message', 'Done.')}",
        )
        await self._audit("cmd_apply", {"target": target, "ok": ok})

    async def _cmd_captcha_text(self, update: Update, context) -> None:
        """`/captcha <answer>` — submit pending CAPTCHA answer in-thread."""
        if not self._is_authorised(update):
            return
        if self.captcha_relay is None:
            await update.message.reply_text("⚠️ CAPTCHA relay not wired.")
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: `/captcha <answer>`", parse_mode=ParseMode.MARKDOWN)
            return
        user_id = str(update.effective_user.id)
        challenge_id = self._captcha_pending.pop(user_id, None)
        if not challenge_id:
            await update.message.reply_text("ℹ️ No pending CAPTCHA for you.")
            return
        answer = " ".join(args)
        ok = await self.captcha_relay.submit_answer(challenge_id, answer)
        await update.message.reply_text(
            "✅ Submitted." if ok else "❌ Challenge expired or invalid.",
        )
        await self._audit("cmd_captcha", {"challenge_id": challenge_id, "ok": ok})

    async def _cmd_followup(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        snap = await self.orch.status_snapshot()
        items = snap.get("followup_needed") or []
        if not items:
            await update.message.reply_text("✅ No applied-but-unviewed jobs older than 14 days.")
            return
        lines = ["*🔁 Follow-up needed (Innovation 12)*", ""]
        for it in items[:15]:
            lines.append(
                f"• `{it.get('portal')}` *{it.get('company')}* — _{it.get('title')}_ "
                f"({it.get('days_since_apply', 0):.0f}d)"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    # ────────────────────────────────────────────────────────────────────
    #  Inline button callbacks
    # ────────────────────────────────────────────────────────────────────

    async def _on_callback(self, update: Update, context) -> None:
        if not self._is_authorised(update):
            return
        q = update.callback_query
        await q.answer()
        data = q.data or ""
        try:
            verb, _, payload = data.partition(":")
            if verb == "apply":
                result = await self.orch.force_apply(payload)
                await q.edit_message_text(
                    (q.message.text or "") + f"\n\n{'✅' if result.get('success') else '❌'} "
                    f"{result.get('message', '')}",
                )
            elif verb == "skip":
                ok = await self.orch.force_skip(payload)
                await q.edit_message_text(
                    (q.message.text or "") + f"\n\n🛑 {'Skipped' if ok else 'Skip failed'}.",
                )
            elif verb == "customise":
                await q.message.reply_text(
                    "📝 Reply to this message with custom answer overrides.\n"
                    "Format: `field=value; field=value`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            elif verb == "brief":
                br = await self.intel.get_briefing(payload)
                if not br:
                    await q.message.reply_text("ℹ️ No briefing yet — try later.")
                else:
                    await q.message.reply_text(
                        f"*🔍 Briefing*\n{br.get('summary', '')}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            elif verb == "refresh":
                ok = await self.vault.request_refresh(payload)
                await q.message.reply_text(
                    f"🔁 Refresh requested for `{payload}` — {'OK' if ok else 'failed'}.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            elif verb == "pause":
                ok = await self.orch.pause_portal(payload)
                await q.edit_message_text(f"⏸ Paused `{payload}`" if ok else f"⚠️ Pause failed.")
            elif verb == "resume":
                ok = await self.orch.resume_portal(payload)
                await q.edit_message_text(f"▶️ Resumed `{payload}`" if ok else f"⚠️ Resume failed.")
            elif verb == "captcha_type":
                user_id = str(update.effective_user.id)
                self._captcha_pending[user_id] = payload
                await q.message.reply_text(
                    "✏️ Reply with `/captcha <answer>` within 45 seconds.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            elif verb == "captcha_abort":
                if self.captcha_relay is not None:
                    await self.captcha_relay.submit_answer(payload, "__ABORT__")
                await q.edit_message_text("🛑 CAPTCHA challenge aborted.")
            else:
                await q.message.reply_text(f"⚠️ Unknown action: `{verb}`")
            await self._audit("callback", {"verb": verb, "payload": payload})
        except Exception:
            logger.exception("Callback handler failed.")
            try:
                await q.message.reply_text("❌ Action failed — see logs.")
            except Exception:
                pass

    # ────────────────────────────────────────────────────────────────────
    #  Outbound alerts (called by orchestrator / L5 / L8 / L0)
    # ────────────────────────────────────────────────────────────────────

    async def _send(self, text: str, **kwargs: Any) -> None:
        if not (TG_AVAILABLE and self._app and self.cfg.chat_id):
            logger.info("[TG-OFFLINE] %s", text)
            return
        try:
            await self._app.bot.send_message(
                chat_id=self.cfg.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                **kwargs,
            )
        except Exception:
            logger.exception("Telegram send failed.")

    async def alert_manual_review(self, item: PendingReviewItem) -> None:
        self._pending_cards[item.job_id] = item
        await self._send(
            _fmt_review_card(item),
            reply_markup=_review_keyboard(item),
        )

    async def alert_captcha_relay(
        self,
        portal: str,
        challenge_id: str,
        screenshot_caption: str = "",
    ) -> None:
        await self._send(
            f"*🧩 CAPTCHA Relay (T3)*\n"
            f"Portal: `{portal}`\n"
            f"Challenge: `{challenge_id}`\n"
            f"45-second window. Tap *✏️ Type Answer* then send `/captcha <answer>`.\n"
            + (f"\n_{screenshot_caption}_" if screenshot_caption else ""),
            reply_markup=_captcha_keyboard(challenge_id),
        )

    async def alert_session_refresh(self, portal: str, health: int) -> None:
        await self._send(
            f"*🔁 Session Refresh Required*\n"
            f"Portal: `{portal}` · Health: *{health}/100*\n"
            f"Tap below to launch the capture flow.",
            reply_markup=_session_keyboard(portal),
        )

    async def alert_risk(self, portal: str, signal: str, action: str) -> None:
        await self._send(
            f"*🛡 Risk Governor*\n"
            f"Portal: `{portal}`\n"
            f"Signal: `{signal}`\n"
            f"Action: *{action}*",
        )

    async def alert_interview(self, briefing: Dict[str, Any]) -> None:
        await self._send(
            f"*🎤 Interview Invite — {briefing.get('company', '?')}*\n"
            f"_When:_ {briefing.get('when', 'TBD')}\n\n"
            f"{briefing.get('summary', '')}\n\n"
            f"*Likely Q:*\n"
            + "\n".join(f"• {q}" for q in (briefing.get('questions') or [])[:6])
            + (f"\n\n*Draft reply:*\n{briefing.get('draft_reply', '')}" if briefing.get('draft_reply') else ""),
        )

    async def alert_deadline_cliff(self, item: PendingReviewItem) -> None:
        urgency = "🚨 6h" if (item.deadline_hours or 99) < 6 else "⚠️ 24h"
        await self._send(
            f"*{urgency} Deadline Cliff*\n" + _fmt_review_card(item),
            reply_markup=_review_keyboard(item),
        )

    async def alert_followup(self, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        lines = ["*🔁 Follow-up Sweep (Innovation 12)*", ""]
        for it in items[:10]:
            lines.append(
                f"• `{it.get('portal')}` *{it.get('company')}* — "
                f"{it.get('days_since_apply', 0):.0f}d unviewed"
            )
        await self._send("\n".join(lines))

    # ────────────────────────────────────────────────────────────────────
    #  Daily digest job
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _snap_to_rows(snap: Dict[str, Any]) -> List[DigestRow]:
        out: List[DigestRow] = []
        for portal, info in (snap.get("portals") or {}).items():
            out.append(
                DigestRow(
                    portal=portal,
                    discovered=int(info.get("discovered_24h", 0)),
                    scored=int(info.get("scored_24h", 0)),
                    applied=int(info.get("applied_24h", 0)),
                    captcha=int(info.get("captcha_24h", 0)),
                    failed=int(info.get("failed_24h", 0)),
                    risk_level=info.get("risk", "GREEN"),
                )
            )
        return out

    async def _job_daily_digest(self, context) -> None:
        try:
            snap = await self.orch.status_snapshot()
            rows = self._snap_to_rows(snap)
            await self._send(_fmt_digest(rows))
            await self._audit("digest_auto", {"portals": len(rows)})
        except Exception:
            logger.exception("Daily digest job failed.")


# ============================================================================
#  Module-level convenience alert helpers (for code paths without dashboard ref)
# ============================================================================

async def alert_manual_review(dash: TelegramDashboard, item: PendingReviewItem) -> None:
    await dash.alert_manual_review(item)


async def alert_captcha_relay(dash: TelegramDashboard, portal: str, challenge_id: str, caption: str = "") -> None:
    await dash.alert_captcha_relay(portal, challenge_id, caption)


async def alert_interview(dash: TelegramDashboard, briefing: Dict[str, Any]) -> None:
    await dash.alert_interview(briefing)


async def alert_risk(dash: TelegramDashboard, portal: str, signal: str, action: str) -> None:
    await dash.alert_risk(portal, signal, action)


__all__ = [
    "TelegramDashboard",
    "DashboardConfig",
    "PendingReviewItem",
    "DigestRow",
    "OrchestratorAPI",
    "VaultAPI",
    "InterviewAPI",
    "CaptchaRelayAPI",
    "AuditDB",
    "alert_manual_review",
    "alert_captcha_relay",
    "alert_interview",
    "alert_risk",
    "TG_AVAILABLE",
]
