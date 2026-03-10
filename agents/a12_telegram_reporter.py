"""
============================================================
AGENT A-12: TELEGRAM REPORTER / COMMAND CENTER — INDUSTRIAL GRADE
============================================================
The user-facing interface — handles 26 Telegram commands,
morning/evening reports, real-time alerts, inline keyboards,
and full application lifecycle management.

Framework: python-telegram-bot v21
Schedule: 07:15 AM (morning brief) + 10:00 PM (evening summary)

24 Commands:
    /start        — Welcome message + setup wizard
    /help         — Full command reference
    /morning      — Morning brief (top 10, ghost filter, signals)
    /top [N]      — Top N listings by PPO score
    /ocean        — Blue Ocean listings (high prestige, low applicants)
    /internshala  — Live Internshala search
    /dark         — Latest dark channel finds
    /signals      — Active intent signals this week
    /package [id] — Full application package (cover + ATS + intro)
    /ats [id]     — ATS simulation + keyword gap + resume tweaks
    /cover [id]   — 200-word tailored cover letter
    /network [co] — Alumni/warm intro map + outreach draft
    /apply [id]   — Mark listing as applied
    /outcome [id] — Log outcome (interview/reject/offer/ppo)
    /cirs [co]    — Company Intern Readiness Score breakdown
    /research [co]— Full company brief (News+Glassdoor+CIRS)
    /stats        — Weekly funnel + top sector performance
    /health       — Agent heartbeats and system health
    /quota        — Daily API usage (Groq, Cerebras, SerpAPI)
    /export       — Export top listings to formatted text
    /settings     — User preferences (college, specialization)
    /refresh      — Force re-scrape current sources
    /run [agent]  — Run agent NOW (pipeline/scrape/dedup/ghost/enrich/ppo/intent/ats)
    /schedule     — Show full 24-hour schedule + next run times
    /status       — Show currently running background agents
    /cancel       — Cancel a running background agent task
============================================================
"""

import os
import json
import time
import asyncio
import signal
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from core.config import get_config, IST, MBA_CATEGORIES
from core.database import get_db, DatabaseManager, Outcome, OutcomeStatus
from core.ai_router import get_router, AIRouter

AGENT_ID = "A-12"
AGENT_NAME = "Telegram Reporter"

# Valid outcome statuses
VALID_OUTCOMES = ['applied', 'shortlisted', 'interview', 'rejected', 'offer', 'ppo', 'withdrawn']

# Message length limit for Telegram
TG_MAX_LEN = 4096


# ============================================================
# REPORT FORMATTERS
# ============================================================

class ReportFormatter:
    """Formats data for Telegram HTML display."""

    @staticmethod
    def morning_brief(data: Dict) -> str:
        """Format morning brief report."""
        total_new = data.get('total_new', 0)
        after_ghost = data.get('after_ghost_filter', 0)
        blue_ocean = data.get('blue_ocean_count', 0)
        signals = data.get('signals_fired', 0)
        top_10 = data.get('top_10', [])
        dark = data.get('dark_finds', [])
        urgent = data.get('urgent_deadlines', [])

        lines = [
            f"🌅 <b>MORNING BRIEF — {datetime.now(IST).strftime('%d %b %Y')}</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📊 Total New: {total_new} | After Ghost Filter: {after_ghost}",
            f"🌊 Blue Ocean Alerts: {blue_ocean}",
            f"📡 Intent Signals Fired: {signals}",
            f"",
            f"🏆 <b>TOP 10 BY PPO SCORE:</b>",
        ]

        for i, listing in enumerate(top_10[:10], 1):
            title = listing.get('title', 'Unknown')[:40]
            company = listing.get('company', 'Unknown')[:25]
            ppo = listing.get('ppo_score', 0)
            bo = " 🌊" if listing.get('is_blue_ocean') else ""
            ppo_tag = " 🎯" if listing.get('is_ppo') else ""
            stipend = listing.get('stipend_monthly', 0) or 0
            lines.append(
                f"{i}. <b>{title}</b> @ {company}\n"
                f"   PPO: {ppo:.1f}{bo}{ppo_tag} | ₹{stipend:,.0f}/mo"
            )

        if dark:
            lines.append(f"\n🌑 <b>Dark Channel:</b> {len(dark)} new finds")

        if urgent:
            lines.append(f"\n⏰ <b>Urgent Deadlines (48h):</b> {len(urgent)}")

        lines.append(f"\n💡 Use /top 25 for extended list | /ocean for Blue Ocean")
        return '\n'.join(lines)

    @staticmethod
    def evening_summary(data: Dict) -> str:
        """Format evening summary report."""
        today_total = data.get('today_total', 0)
        afternoon_new = data.get('afternoon_new', 0)
        applied_today = data.get('applied_today', 0)
        dark_finds = data.get('dark_finds', 0)

        return (
            f"🌆 <b>EVENING SUMMARY — {datetime.now(IST).strftime('%d %b %Y')}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"📊 Today's Total: {today_total}\n"
            f"🆕 Afternoon New: {afternoon_new}\n"
            f"📝 Applied Today: {applied_today}\n"
            f"🌑 Dark Channel: {dark_finds}\n"
            f"\n"
            f"💡 Use /stats for weekly funnel | /health for system status"
        )

    @staticmethod
    def listing_detail(listing: Dict) -> str:
        """Format a single listing for detailed view."""
        title = listing.get('title', 'Unknown')
        company = listing.get('company', 'Unknown')
        location = listing.get('location', 'N/A')
        stipend = listing.get('stipend_monthly', 0) or 0
        duration = listing.get('duration_months', 0) or 0
        applicants = listing.get('applicants', 0) or 0
        ppo_score = listing.get('ppo_score', 0)
        ghost_score = listing.get('ghost_score', 0)
        is_ppo = listing.get('is_ppo', False)
        is_wfh = listing.get('is_wfh', False)
        is_bo = listing.get('is_blue_ocean', False)
        source = listing.get('source', 'Unknown')
        url = listing.get('url', '')
        lid = listing.get('id', 0)

        tags = []
        if is_ppo: tags.append("🎯PPO")
        if is_wfh: tags.append("🏠WFH")
        if is_bo: tags.append("🌊Blue Ocean")
        tag_str = ' '.join(tags) if tags else "—"

        return (
            f"📋 <b>Listing #{lid}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{title}</b>\n"
            f"🏢 {company}\n"
            f"📍 {location}\n"
            f"💰 ₹{stipend:,.0f}/month\n"
            f"⏱ {duration} months\n"
            f"👥 {applicants} applicants\n"
            f"\n"
            f"📊 PPO Score: {ppo_score:.1f}/100\n"
            f"👻 Ghost Score: {ghost_score:.0f}/100\n"
            f"🏷 Tags: {tag_str}\n"
            f"📡 Source: {source}\n"
            f"\n"
            f"🔗 {url[:80] if url else 'No URL'}\n"
            f"\n"
            f"Commands: /ats {lid} | /cover {lid} | /apply {lid}"
        )

    @staticmethod
    def health_report(heartbeats: List[Dict]) -> str:
        """Format agent health report."""
        lines = [
            "💚 <b>Agent Health Dashboard</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        status_emojis = {
            'idle': '😴', 'running': '🏃', 'error': '❌',
            'completed': '✅', 'disabled': '⛔',
        }

        for h in heartbeats:
            agent_id = h.get('agent_id', '?')
            name = h.get('agent_name', '?')
            status = h.get('status', 'idle')
            emoji = status_emojis.get(status, '❓')
            runs = h.get('total_runs', 0)
            items = h.get('total_items', 0)
            errors = h.get('errors_last_run', 0)
            last_run = h.get('last_run', 'Never')

            lines.append(
                f"{emoji} <b>{agent_id}</b>: {name}\n"
                f"   Runs: {runs} | Items: {items} | "
                f"Errors: {errors}\n"
                f"   Last: {str(last_run)[:19]}"
            )

        return '\n'.join(lines)

    @staticmethod
    def stats_report(stats: Dict) -> str:
        """Format weekly stats report."""
        lines = [
            "📈 <b>Weekly Statistics</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "<b>Application Funnel:</b>",
        ]

        funnel = stats.get('funnel', {})
        for status, count in funnel.items():
            emoji = {
                'applied': '📝', 'shortlisted': '📋', 'interview': '🎤',
                'rejected': '❌', 'offer': '🎉', 'ppo': '🏆',
            }.get(status, '•')
            lines.append(f"  {emoji} {status.title()}: {count}")

        by_source = stats.get('by_source', {})
        if by_source:
            lines.append(f"\n<b>By Source:</b>")
            for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
                lines.append(f"  {src}: {count}")

        by_tier = stats.get('by_tier', {})
        if by_tier:
            lines.append(f"\n<b>By Company Tier:</b>")
            for tier, count in sorted(by_tier.items()):
                lines.append(f"  {tier}: {count}")

        return '\n'.join(lines)


# ============================================================
# TELEGRAM BOT
# ============================================================

# ============================================================
# CONSTANTS
# ============================================================

# Max retries for bot startup when Conflict is hit
BOT_START_MAX_RETRIES = 5
BOT_START_RETRY_BASE_DELAY = 15  # seconds — must be long enough for old instance to die
BOT_CONFLICT_COOLDOWN = 20  # seconds to wait after killing stale session

# Pre-flight drain: number of rapid getUpdates calls to forcefully
# terminate any lingering long-poll connection from a previous instance.
PREFLIGHT_DRAIN_ROUNDS = 8
PREFLIGHT_DRAIN_INTERVAL = 2  # seconds between drain calls

# Pre-flight: max time to wait for old instance to die (checked via health endpoint)
PREFLIGHT_OLD_INSTANCE_CHECK_TIMEOUT = 30  # seconds
PREFLIGHT_OLD_INSTANCE_CHECK_INTERVAL = 5  # seconds


class TelegramReporter:
    """
    Telegram bot command center with 26 commands.
    Uses python-telegram-bot v21 with async handlers.

    ROBUSTNESS FEATURES:
        1. Pre-flight cleanup: deletes any stale webhook AND
           calls getUpdates with offset=-1 to flush the queue
           and release any lingering polling lock.
        2. Conflict-aware startup with exponential backoff:
           If Conflict is detected, waits and retries up to 5 times.
        3. Custom error handler that catches Conflict during runtime
           and auto-restarts polling instead of crashing.
        4. Graceful shutdown ensures polling is fully stopped
           before the process exits (SIGTERM from Render).
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.router = get_router()
        self.formatter = ReportFormatter()
        self._app = None
        self._running = False
        self._restart_lock = asyncio.Lock()
        self._restart_count = 0
        self._max_runtime_restarts = 10  # max auto-restarts during runtime

        # Background task tracking for /run, /status, /cancel
        self._running_tasks: Dict[str, Dict[str, Any]] = {}
        self._task_lock = asyncio.Lock()

    # ================================================================
    # PRE-FLIGHT: CLEAN STALE SESSIONS
    # ================================================================

    async def _wait_for_old_instance_death(self):
        """
        If running on Render, check the external URL to see if the
        OLD instance has stopped its Telegram polling. This is more
        reliable than a fixed sleep timer.
        """
        import aiohttp

        external_url = os.getenv('RENDER_EXTERNAL_URL', '')
        if not external_url:
            return  # Not on Render or no external URL

        status_url = f"{external_url}/telegram-status"
        timeout = aiohttp.ClientTimeout(total=10)

        logger.info(
            f"[{AGENT_ID}] Checking old instance Telegram status at "
            f"{status_url}..."
        )

        elapsed = 0
        while elapsed < PREFLIGHT_OLD_INSTANCE_CHECK_TIMEOUT:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(status_url) as resp:
                        if resp.status == 200:
                            import json as _json
                            data = _json.loads(await resp.text())
                            tg_running = data.get('telegram_running', False)
                            if not tg_running:
                                logger.info(
                                    f"[{AGENT_ID}] Old instance confirms "
                                    f"Telegram is OFF — safe to proceed"
                                )
                                return
                            else:
                                logger.info(
                                    f"[{AGENT_ID}] Old instance still has "
                                    f"Telegram ON — waiting..."
                                )
                        else:
                            # Non-200 means old instance may be dead
                            logger.info(
                                f"[{AGENT_ID}] Old instance returned "
                                f"HTTP {resp.status} — likely shutting down"
                            )
                            return
            except Exception as e:
                # Connection error = old instance is dead
                logger.info(
                    f"[{AGENT_ID}] Old instance unreachable ({e}) — "
                    f"proceeding"
                )
                return

            await asyncio.sleep(PREFLIGHT_OLD_INSTANCE_CHECK_INTERVAL)
            elapsed += PREFLIGHT_OLD_INSTANCE_CHECK_INTERVAL

        logger.warning(
            f"[{AGENT_ID}] Old instance check timed out after "
            f"{PREFLIGHT_OLD_INSTANCE_CHECK_TIMEOUT}s — proceeding anyway"
        )

    async def _kill_stale_sessions(self, token: str):
        """
        NUCLEAR CLEANUP — Call this BEFORE starting polling.

        The REAL fix for Conflict errors:

        1. Call Telegram Bot API `close()` — this explicitly tells
           Telegram's servers to LOG OUT any active session for this
           bot token. Unlike getUpdates(offset=-1) which only interrupts
           the current long-poll, `close` server-side revokes the session.

        2. Call `logOut()` as a fallback — forces re-authentication.
           (Only needed in extreme cases, skipped if close succeeds.)

        3. deleteWebhook(drop_pending_updates=True) — standard cleanup.

        4. DRAIN LOOP — multiple rapid getUpdates calls to flush any
           queued updates and interrupt PTB's auto-retry on old instance.

        5. Final getUpdates with offset to acknowledge all pending.

        6. Cooldown for Telegram servers to release connection state.
        """
        import aiohttp

        base = f"https://api.telegram.org/bot{token}"
        timeout = aiohttp.ClientTimeout(total=15)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Step 1: CLOSE the bot session server-side
                # This is the KEY fix — `close` tells Telegram to drop
                # ALL active connections for this bot token.
                logger.info(f"[{AGENT_ID}] Pre-flight: calling /close...")
                try:
                    async with session.post(f"{base}/close") as resp:
                        result = await resp.json()
                        logger.info(
                            f"[{AGENT_ID}] Pre-flight: /close → "
                            f"{result.get('ok', False)} "
                            f"(desc: {result.get('description', 'n/a')})"
                        )
                except Exception as close_err:
                    logger.warning(
                        f"[{AGENT_ID}] Pre-flight: /close failed: {close_err}"
                    )

                # After /close, Telegram requires a 10-second cooldown
                # before the bot can make new requests
                logger.info(
                    f"[{AGENT_ID}] Pre-flight: post-close cooldown (12s)..."
                )
                await asyncio.sleep(12)

                # Step 2: Delete webhook + flush pending
                logger.info(f"[{AGENT_ID}] Pre-flight: deleting webhook...")
                try:
                    async with session.post(
                        f"{base}/deleteWebhook",
                        json={"drop_pending_updates": True}
                    ) as resp:
                        result = await resp.json()
                        logger.info(
                            f"[{AGENT_ID}] Pre-flight: deleteWebhook → "
                            f"{result.get('ok', False)}"
                        )
                except Exception as wh_err:
                    logger.warning(
                        f"[{AGENT_ID}] Pre-flight: deleteWebhook failed: "
                        f"{wh_err}"
                    )

                # Step 3: DRAIN LOOP — repeatedly call getUpdates to
                # flush any remaining queued updates and interrupt
                # the old instance's retry mechanism.
                logger.info(
                    f"[{AGENT_ID}] Pre-flight: drain loop "
                    f"({PREFLIGHT_DRAIN_ROUNDS} rounds, "
                    f"{PREFLIGHT_DRAIN_INTERVAL}s apart)..."
                )
                last_update_id = None
                conflict_count = 0
                for i in range(1, PREFLIGHT_DRAIN_ROUNDS + 1):
                    try:
                        async with session.post(
                            f"{base}/getUpdates",
                            json={"offset": -1, "timeout": 1}
                        ) as resp:
                            result = await resp.json()
                            if result.get('ok'):
                                updates = result.get('result', [])
                                if updates:
                                    last_update_id = updates[-1].get(
                                        'update_id', 0
                                    )
                                logger.debug(
                                    f"[{AGENT_ID}] Pre-flight drain #{i}: "
                                    f"ok=True, updates={len(updates)}"
                                )
                            else:
                                err_code = result.get('error_code', 0)
                                desc = result.get('description', '')
                                if err_code == 409:  # Conflict
                                    conflict_count += 1
                                    logger.info(
                                        f"[{AGENT_ID}] Pre-flight drain #{i}: "
                                        f"Conflict detected (old instance alive)"
                                    )
                                else:
                                    logger.debug(
                                        f"[{AGENT_ID}] Pre-flight drain #{i}: "
                                        f"err={err_code} desc={desc}"
                                    )
                    except Exception as drain_err:
                        logger.debug(
                            f"[{AGENT_ID}] Pre-flight drain #{i} error: "
                            f"{drain_err}"
                        )
                    if i < PREFLIGHT_DRAIN_ROUNDS:
                        await asyncio.sleep(PREFLIGHT_DRAIN_INTERVAL)

                logger.info(
                    f"[{AGENT_ID}] Pre-flight: drain loop complete "
                    f"({PREFLIGHT_DRAIN_ROUNDS} rounds, "
                    f"{conflict_count} conflicts)"
                )

                # Step 4: Acknowledge the last update so the queue is clean
                if last_update_id is not None:
                    try:
                        async with session.post(
                            f"{base}/getUpdates",
                            json={
                                "offset": last_update_id + 1,
                                "timeout": 1,
                            }
                        ) as resp:
                            await resp.json()
                            logger.info(
                                f"[{AGENT_ID}] Pre-flight: acknowledged up to "
                                f"update_id {last_update_id}"
                            )
                    except Exception:
                        pass

                # Step 5: Final cooldown
                cooldown = 8 if conflict_count > 0 else 3
                logger.info(
                    f"[{AGENT_ID}] Pre-flight: final cooldown ({cooldown}s)..."
                )
                await asyncio.sleep(cooldown)

        except Exception as e:
            logger.warning(
                f"[{AGENT_ID}] Pre-flight cleanup error (non-fatal): {e}"
            )
            # Non-fatal — we still try to start

    # ================================================================
    # BOT START WITH RETRY
    # ================================================================

    def _build_app(self, token: str):
        """
        Build a fresh TGApplication with all handlers registered.
        Extracted to avoid duplication in retry loop.
        """
        from telegram.ext import (
            Application as TGApplication,
            CommandHandler,
        )

        app = (
            TGApplication.builder()
            .token(token)
            .connect_timeout(20)
            .read_timeout(20)
            .write_timeout(20)
            .pool_timeout(10)
            .get_updates_connect_timeout(15)
            .get_updates_read_timeout(15)
            .get_updates_write_timeout(15)
            .get_updates_pool_timeout(10)
            .build()
        )

        # Register custom error handler for runtime Conflict errors
        app.add_error_handler(self._on_telegram_error)

        # Register all 26 command handlers
        commands = {
            'start': self._cmd_start,
            'help': self._cmd_help,
            'morning': self._cmd_morning,
            'top': self._cmd_top,
            'ocean': self._cmd_ocean,
            'internshala': self._cmd_internshala,
            'dark': self._cmd_dark,
            'signals': self._cmd_signals,
            'package': self._cmd_package,
            'ats': self._cmd_ats,
            'cover': self._cmd_cover,
            'network': self._cmd_network,
            'apply': self._cmd_apply,
            'outcome': self._cmd_outcome,
            'cirs': self._cmd_cirs,
            'research': self._cmd_research,
            'stats': self._cmd_stats,
            'health': self._cmd_health,
            'quota': self._cmd_quota,
            'export': self._cmd_export,
            'settings': self._cmd_settings,
            'refresh': self._cmd_refresh,
            'run': self._cmd_run,
            'schedule': self._cmd_schedule,
            'status': self._cmd_status,
            'cancel': self._cmd_cancel,
        }

        for cmd_name, handler_fn in commands.items():
            app.add_handler(CommandHandler(cmd_name, handler_fn))

        return app

    async def _safe_cleanup_app(self, app):
        """
        Safely cleanup a TGApplication instance.
        Each step is individually try/excepted and timed out.
        """
        if not app:
            return

        # Stop updater
        try:
            if app.updater and app.updater.running:
                await asyncio.wait_for(app.updater.stop(), timeout=5.0)
        except Exception:
            pass

        # Stop application
        try:
            if app.running:
                await asyncio.wait_for(app.stop(), timeout=5.0)
        except Exception:
            pass

        # Shutdown
        try:
            await asyncio.wait_for(app.shutdown(), timeout=5.0)
        except Exception:
            pass

    async def start_bot(self):
        """
        Initialize and start the Telegram bot with full robustness:
        1. Wait for old instance to die (Render health check)
        2. Kill stale sessions via Telegram /close API
        3. Build application with error handler
        4. Start polling with exponential backoff retries
        """
        token = self.config.telegram.bot_token
        if not token:
            logger.error(f"[{AGENT_ID}] TG_BOT_TOKEN not set!")
            return

        try:
            from telegram import Update, Bot
            from telegram.ext import (
                Application as TGApplication,
                CommandHandler, ContextTypes,
                MessageHandler, filters,
            )
            from telegram.error import Conflict, TimedOut, NetworkError
        except ImportError:
            logger.error(f"[{AGENT_ID}] python-telegram-bot not installed")
            return

        # ---- STEP 0: Check if old instance is still alive ----
        await self._wait_for_old_instance_death()

        # ---- STEP 1: Kill any stale polling session ----
        await self._kill_stale_sessions(token)

        # ---- STEP 2: Build application ----
        self._app = self._build_app(token)

        logger.info(
            f"[{AGENT_ID}] Bot starting with 26 commands "
            f"(max {BOT_START_MAX_RETRIES} attempts)..."
        )

        # ---- STEP 3: Start polling with retry ----
        last_error = None
        for attempt in range(1, BOT_START_MAX_RETRIES + 1):
            try:
                await self._app.initialize()
                await self._app.start()
                await self._app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query"],
                    poll_interval=1.0,
                    read_timeout=10,
                )
                self._running = True
                logger.info(
                    f"[{AGENT_ID}] Telegram bot is running! "
                    f"(started on attempt {attempt}/{BOT_START_MAX_RETRIES})"
                )
                return  # SUCCESS

            except Conflict as e:
                last_error = e
                # Calculate delay with capped exponential backoff
                delay = min(
                    BOT_START_RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                    120  # cap at 2 minutes
                )
                logger.warning(
                    f"[{AGENT_ID}] Conflict on attempt "
                    f"{attempt}/{BOT_START_MAX_RETRIES}: {e}. "
                    f"Retrying in {delay}s..."
                )

                # Clean up current app
                await self._safe_cleanup_app(self._app)

                # Wait before retrying
                await asyncio.sleep(delay)

                # Re-kill stale sessions (use /close again)
                await self._kill_stale_sessions(token)

                # Rebuild the application for retry
                self._app = self._build_app(token)

            except Exception as e:
                last_error = e
                logger.error(
                    f"[{AGENT_ID}] Bot start attempt {attempt} failed: "
                    f"{type(e).__name__}: {e}"
                )

                # Clean up
                await self._safe_cleanup_app(self._app)

                if attempt < BOT_START_MAX_RETRIES:
                    delay = min(
                        BOT_START_RETRY_BASE_DELAY * attempt,
                        90
                    )
                    logger.info(
                        f"[{AGENT_ID}] Waiting {delay}s before retry..."
                    )
                    await asyncio.sleep(delay)

                    # Rebuild for retry
                    self._app = self._build_app(token)

        # All retries exhausted
        logger.error(
            f"[{AGENT_ID}] Bot failed to start after "
            f"{BOT_START_MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )
        logger.error(
            f"[{AGENT_ID}] System will continue WITHOUT Telegram. "
            f"Fix: ensure only ONE instance uses this bot token."
        )

    # ================================================================
    # RUNTIME ERROR HANDLER (catches Conflict during polling)
    # ================================================================

    async def _on_telegram_error(self, update, context):
        """
        Custom error handler for runtime errors.

        CRITICAL CHANGE: We do NOT auto-restart on Conflict errors.

        WHY: Auto-restarting polling on Conflict creates a feedback loop:
          1. Instance A is polling
          2. Instance B starts polling → A gets Conflict
          3. A's error handler restarts polling → B gets Conflict
          4. B's error handler restarts polling → A gets Conflict
          5. → infinite loop of Conflict errors

        CORRECT BEHAVIOR: If we get a Conflict, it means another instance
        legitimately took over. We should STOP polling and let it win.
        The old instance will be killed by SIGTERM shortly anyway.
        """
        from telegram.error import Conflict, TimedOut, NetworkError

        error = context.error

        if isinstance(error, Conflict):
            logger.warning(
                f"[{AGENT_ID}] RUNTIME Conflict: another instance took over. "
                f"STOPPING polling (this is expected during redeployment)."
            )
            # Do NOT restart. Let the other instance win.
            # PTB will keep retrying internally — we stop it.
            asyncio.create_task(self._surrender_polling())

        elif isinstance(error, (TimedOut, NetworkError)):
            logger.warning(
                f"[{AGENT_ID}] Network issue (auto-recoverable): {error}"
            )
            # PTB handles these automatically, just log

        else:
            logger.error(
                f"[{AGENT_ID}] Unhandled error: {type(error).__name__}: {error}"
            )

    async def _surrender_polling(self):
        """
        Gracefully surrender polling when a Conflict is detected.
        This means another instance legitimately started polling.
        We stop our updater so we don't keep fighting.
        """
        async with self._restart_lock:
            try:
                if self._app and self._app.updater and self._app.updater.running:
                    logger.info(
                        f"[{AGENT_ID}] Surrendering: stopping updater..."
                    )
                    await asyncio.wait_for(
                        self._app.updater.stop(), timeout=10.0
                    )
                    self._running = False
                    logger.info(
                        f"[{AGENT_ID}] Updater stopped. "
                        f"This instance will NOT restart polling."
                    )
            except Exception as e:
                logger.error(
                    f"[{AGENT_ID}] Surrender stop error: {e}"
                )

    # ================================================================
    # GRACEFUL SHUTDOWN
    # ================================================================

    async def stop_bot(self):
        """
        Stop the Telegram bot with FULL cleanup.

        Order matters:
        1. Stop polling (releases getUpdates lock)
        2. Call Telegram /close API to release server-side session
        3. Stop application
        4. Shutdown (cleanup resources)

        The /close call is CRITICAL for Render redeployments:
        it tells Telegram's servers to drop the connection immediately,
        so the NEW instance can start polling without conflict.
        """
        if not self._app:
            return

        logger.info(f"[{AGENT_ID}] Stopping bot (4-step shutdown)...")

        # Step 1: Stop updater/polling FIRST
        try:
            if self._app.updater and self._app.updater.running:
                await asyncio.wait_for(
                    self._app.updater.stop(), timeout=8.0
                )
                logger.info(f"[{AGENT_ID}] Updater stopped")
        except asyncio.TimeoutError:
            logger.warning(f"[{AGENT_ID}] Updater stop timed out (8s)")
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Updater stop error: {e}")

        # Step 2: Call /close to release server-side session
        # This is the KEY step that prevents the next instance from
        # hitting Conflict. It tells Telegram's backend to drop
        # our session immediately.
        try:
            import aiohttp
            token = self.config.telegram.bot_token
            if token:
                base = f"https://api.telegram.org/bot{token}"
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(f"{base}/close") as resp:
                        result = await resp.json()
                        logger.info(
                            f"[{AGENT_ID}] /close called: "
                            f"{result.get('ok', False)}"
                        )
        except Exception as e:
            logger.warning(
                f"[{AGENT_ID}] /close call failed (non-critical): {e}"
            )

        # Step 3: Stop the application
        try:
            if self._app.running:
                await asyncio.wait_for(
                    self._app.stop(), timeout=8.0
                )
                logger.info(f"[{AGENT_ID}] Application stopped")
        except asyncio.TimeoutError:
            logger.warning(f"[{AGENT_ID}] App stop timed out (8s)")
        except Exception as e:
            logger.error(f"[{AGENT_ID}] App stop error: {e}")

        # Step 4: Shutdown (cleanup)
        try:
            await asyncio.wait_for(
                self._app.shutdown(), timeout=8.0
            )
            logger.info(f"[{AGENT_ID}] Application shutdown complete")
        except asyncio.TimeoutError:
            logger.warning(f"[{AGENT_ID}] App shutdown timed out (8s)")
        except Exception as e:
            logger.error(f"[{AGENT_ID}] App shutdown error: {e}")

        self._running = False
        logger.info(f"[{AGENT_ID}] Bot fully stopped (session released)")

    async def send_message(self, text: str, chat_id: str = None):
        """Send a message to configured chat, with auto-splitting."""
        if chat_id is None:
            chat_id = self.config.telegram.chat_id
        if not chat_id:
            logger.warning(f"[{AGENT_ID}] No chat_id configured")
            return

        try:
            from telegram import Bot
            bot = Bot(token=self.config.telegram.bot_token)

            # Split long messages
            for i in range(0, len(text), TG_MAX_LEN):
                chunk = text[i:i + TG_MAX_LEN]
                try:
                    await bot.send_message(
                        chat_id=chat_id, text=chunk, parse_mode='HTML'
                    )
                except Exception:
                    # Fallback without HTML parse mode
                    await bot.send_message(chat_id=chat_id, text=chunk)
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Send message failed: {e}")

    # ================================================================
    # COMMAND HANDLERS — 22 Commands
    # ================================================================

    async def _cmd_start(self, update, context):
        """Welcome message and setup wizard."""
        msg = (
            "⚡ <b>Operation First Mover v5</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Your zero-cost MBA internship hunting agent.\n\n"
            "🤖 <b>12 AI agents</b> working 24/7\n"
            "📊 <b>1080+</b> Indian companies tracked\n"
            "🔍 <b>8+</b> job boards scraped daily\n"
            "💰 Total cost: <b>₹0.00/day</b>\n\n"
            "🔧 <b>Quick Setup:</b>\n"
            "1. /settings college Your College Name\n"
            "2. /settings spec Marketing\n\n"
            "🚀 <b>Run agents on demand:</b>\n"
            "/run pipeline — Full scrape+process+report\n"
            "/run scrape — Just scrape now\n\n"
            "Type /help for all 26 commands."
        )
        await update.message.reply_text(msg, parse_mode='HTML')

    async def _cmd_help(self, update, context):
        """Full command reference."""
        msg = (
            "📖 <b>Command Reference (26 Commands)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 <b>Reports</b>\n"
            "/morning — Full morning brief\n"
            "/top [N] — Top N by PPO score (default 10)\n"
            "/ocean — Blue Ocean listings\n"
            "/dark — Dark channel finds\n"
            "/signals — Active intent signals\n"
            "/stats — Weekly funnel stats\n\n"
            "🔍 <b>Search</b>\n"
            "/internshala [query] — Live search\n"
            "/refresh — Force re-scrape all sources\n\n"
            "📝 <b>Application</b>\n"
            "/package [id] — Full app package\n"
            "/ats [id] — ATS keyword simulation\n"
            "/cover [id] — Tailored cover letter\n"
            "/network [company] — Alumni map\n"
            "/apply [id] — Mark as applied\n"
            "/outcome [id] [result] — Log result\n\n"
            "🏢 <b>Company Intel</b>\n"
            "/cirs [company] — CIRS breakdown\n"
            "/research [company] — Full research\n\n"
            "🚀 <b>Manual Agent Control</b>\n"
            "/run — Run agents NOW (see /run for options)\n"
            "/schedule — Full 24h schedule + next runs\n"
            "/status — Currently running background tasks\n"
            "/cancel [task] — Cancel a running task\n\n"
            "⚙️ <b>System</b>\n"
            "/health — Agent heartbeats\n"
            "/quota — API usage\n"
            "/export — Export listings\n"
            "/settings — Preferences"
        )
        await update.message.reply_text(msg, parse_mode='HTML')

    async def _cmd_morning(self, update, context):
        """Morning brief report."""
        await update.message.reply_text("🌅 Generating morning brief...")
        data = self.db.get_morning_brief_data()
        msg = self.formatter.morning_brief(data)
        await self._send_long_message(update, msg)

    async def _cmd_top(self, update, context):
        """Top N listings by PPO score."""
        n = 10
        if context.args:
            try:
                n = int(context.args[0])
                n = max(1, min(50, n))
            except ValueError:
                pass

        listings = self.db.get_top_listings(n=n)
        if not listings:
            await update.message.reply_text("📊 No listings available yet.")
            return

        lines = [
            f"🏆 <b>Top {len(listings)} by PPO Score</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━", "",
        ]

        for i, l in enumerate(listings, 1):
            ppo = l.get('ppo_score', 0)
            bo = " 🌊" if l.get('is_blue_ocean') else ""
            ppo_tag = " 🎯" if l.get('is_ppo') else ""
            stipend = l.get('stipend_monthly', 0) or 0
            lid = l.get('id', 0)
            title = l.get('title', '')[:40]
            company = l.get('company', '')[:25]
            location = l.get('location', '')[:20]

            lines.append(
                f"{i}. <b>{title}</b> @ {company}\n"
                f"   PPO: {ppo:.1f}{bo}{ppo_tag} | ₹{stipend:,.0f} | "
                f"{location} | #{lid}"
            )

        await self._send_long_message(update, '\n'.join(lines))

    async def _cmd_ocean(self, update, context):
        """Blue Ocean listings."""
        listings = self.db.get_blue_ocean_listings(limit=15)
        if not listings:
            await update.message.reply_text("🌊 No Blue Ocean listings found yet.\nCriteria: Prestige ≥ 60 AND Applicants ≤ 35")
            return

        lines = [
            "🌊 <b>Blue Ocean Listings</b>",
            "<i>High prestige + Low competition</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━", "",
        ]

        for i, l in enumerate(listings, 1):
            lid = l.get('id', 0)
            title = l.get('title', '')[:40]
            company = l.get('company', '')[:25]
            applicants = l.get('applicants', 0) or 0
            ppo = l.get('ppo_score', 0)
            stipend = l.get('stipend_monthly', 0) or 0

            lines.append(
                f"{i}. <b>{title}</b> @ {company}\n"
                f"   👥 {applicants} applicants | PPO: {ppo:.1f} | ₹{stipend:,.0f} | #{lid}"
            )

        await self._send_long_message(update, '\n'.join(lines))

    async def _cmd_internshala(self, update, context):
        """Live Internshala search."""
        if not context.args:
            await update.message.reply_text(
                "Usage: /internshala <query>\n"
                "Example: /internshala digital marketing\n\n"
                f"Categories: {', '.join(MBA_CATEGORIES[:5])}..."
            )
            return

        query = ' '.join(context.args)
        await update.message.reply_text(f"🔍 Searching Internshala for: {query}...")

        try:
            from agents.a03_primary_scraper import get_primary_scraper
            scraper = get_primary_scraper()
            listings = scraper.search_on_demand(query)

            if not listings:
                await update.message.reply_text(f"No results found for '{query}'")
                return

            lines = [f"🔍 <b>Internshala: '{query}'</b> — {len(listings)} results\n"]
            for i, l in enumerate(listings[:10], 1):
                lines.append(
                    f"{i}. <b>{l.title}</b> @ {l.company}\n"
                    f"   📍 {l.location} | 💰 {l.stipend}"
                )

            await self._send_long_message(update, '\n'.join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ Search failed: {e}")

    async def _cmd_dark(self, update, context):
        """Dark channel finds."""
        try:
            from agents.a02_dark_channel import get_dark_channel_listener
            listener = get_dark_channel_listener()
            listings = listener.get_recent_finds(days=3, limit=15)
            msg = listener.format_dark_report(listings)
            await self._send_long_message(update, msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_signals(self, update, context):
        """Active intent signals."""
        try:
            from agents.a01_intent_scanner import get_intent_scanner
            scanner = get_intent_scanner()
            msg = scanner.get_signal_report(days=7)
            await self._send_long_message(update, msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_package(self, update, context):
        """Generate full application package."""
        lid = self._parse_listing_id(context.args)
        if lid is None:
            await update.message.reply_text("Usage: /package <listing_id>\nFind IDs with /top or /ocean")
            return

        listing = self.db.get_clean_listing_by_id(lid)
        if not listing:
            await update.message.reply_text(f"❌ Listing #{lid} not found")
            return

        await update.message.reply_text(f"📦 Generating application package for #{lid}... (30-60s)")

        profile = {
            'college': self.db.get_setting('college', 'a top MBA program'),
            'specialization': self.db.get_setting('specialization', 'Marketing'),
        }

        try:
            response = self.router.generate_package(listing, profile)
            if response.success:
                title = listing.get('title', '')
                company = listing.get('company', '')
                msg = (
                    f"📦 <b>Application Package</b>\n"
                    f"<b>{title}</b> @ {company}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{response.content[:3800]}"
                )
                await self._send_long_message(update, msg)
            else:
                await update.message.reply_text(f"❌ Generation failed: {response.error}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_ats(self, update, context):
        """ATS keyword simulation."""
        lid = self._parse_listing_id(context.args)
        if lid is None:
            await update.message.reply_text("Usage: /ats <listing_id>")
            return

        await update.message.reply_text(f"🔬 Running ATS simulation for #{lid}...")

        try:
            from agents.a10_ats_simulator import get_ats_simulator
            sim = get_ats_simulator()
            result = sim.simulate(lid)

            if hasattr(result, 'to_telegram_msg'):
                await self._send_long_message(update, result.to_telegram_msg())
            elif isinstance(result, dict) and 'error' in result:
                await update.message.reply_text(f"❌ {result['error']}")
            else:
                msg = f"🔬 ATS Match: {result.match_percentage:.0f}%\n"
                msg += f"Missing: {', '.join(result.missing_keywords[:10])}"
                await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_cover(self, update, context):
        """Generate cover letter."""
        lid = self._parse_listing_id(context.args)
        if lid is None:
            await update.message.reply_text("Usage: /cover <listing_id>")
            return

        listing = self.db.get_clean_listing_by_id(lid)
        if not listing:
            await update.message.reply_text(f"❌ Listing #{lid} not found")
            return

        await update.message.reply_text(f"✍️ Generating cover letter...")

        try:
            profile = {'college': self.db.get_setting('college', 'a top MBA program')}
            response = self.router.generate_cover_letter(listing, profile)
            if response.success:
                company = listing.get('company', '')
                msg = (
                    f"✍️ <b>Cover Letter — {company}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{response.content[:3800]}"
                )
                await self._send_long_message(update, msg)
            else:
                await update.message.reply_text(f"❌ Failed: {response.error}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_network(self, update, context):
        """Alumni/network mapping."""
        if not context.args:
            await update.message.reply_text("Usage: /network <company name>")
            return

        company = ' '.join(context.args)
        await update.message.reply_text(f"🔗 Mapping network for {company}...")

        try:
            from agents.a09_network_mapper import get_network_mapper
            mapper = get_network_mapper()
            college = self.db.get_setting('college', '')
            spec = self.db.get_setting('specialization', '')
            result = mapper.map_network(company, college, spec)

            if hasattr(result, 'to_telegram_msg'):
                await self._send_long_message(update, result.to_telegram_msg())
            else:
                await update.message.reply_text(
                    f"🔗 Network for {company}: {result.get('alumni_found', 0)} alumni found"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_apply(self, update, context):
        """Mark listing as applied."""
        lid = self._parse_listing_id(context.args)
        if lid is None:
            await update.message.reply_text("Usage: /apply <listing_id>")
            return

        listing = self.db.get_clean_listing_by_id(lid)
        if not listing:
            await update.message.reply_text(f"❌ Listing #{lid} not found")
            return

        outcome = Outcome(
            listing_id=lid,
            company_id=listing.get('company_id'),
            status='applied',
            ppo_score_at_apply=listing.get('ppo_score', 0),
        )
        self.db.insert_outcome(outcome)
        self.db.update_clean_listing_scores(lid, status='applied')

        title = listing.get('title', '')
        company = listing.get('company', '')
        await update.message.reply_text(
            f"✅ <b>Marked as Applied!</b>\n"
            f"{title} @ {company}\n\n"
            f"Track: /outcome {lid} interview (when called)\n"
            f"Or: /outcome {lid} rejected | /outcome {lid} offer",
            parse_mode='HTML'
        )

    async def _cmd_outcome(self, update, context):
        """Log application outcome."""
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /outcome <listing_id> <result>\n\n"
                f"Valid results: {', '.join(VALID_OUTCOMES)}\n\n"
                "Example: /outcome 42 interview"
            )
            return

        lid = self._parse_listing_id([context.args[0]])
        if lid is None:
            await update.message.reply_text("❌ Invalid listing ID")
            return

        status = context.args[1].lower()
        if status not in VALID_OUTCOMES:
            await update.message.reply_text(
                f"❌ Invalid status '{status}'\n"
                f"Valid: {', '.join(VALID_OUTCOMES)}"
            )
            return

        notes = ' '.join(context.args[2:]) if len(context.args) > 2 else ''

        outcome = Outcome(listing_id=lid, status=status, notes=notes)
        self.db.insert_outcome(outcome)

        emoji = {
            'applied': '📝', 'shortlisted': '📋', 'interview': '🎤',
            'rejected': '❌', 'offer': '🎉', 'ppo': '🏆', 'withdrawn': '🔙',
        }.get(status, '📝')

        await update.message.reply_text(
            f"{emoji} Outcome logged: <b>{status.upper()}</b> for #{lid}",
            parse_mode='HTML'
        )

    async def _cmd_cirs(self, update, context):
        """Company Intern Readiness Score."""
        if not context.args:
            await update.message.reply_text("Usage: /cirs <company name>")
            return

        company_name = ' '.join(context.args)
        company = self.db.fuzzy_match_company(company_name)

        if not company:
            await update.message.reply_text(f"❌ Company '{company_name}' not found")
            return

        name = company.get('name', '')
        tier = company.get('tier', 5)
        sector = company.get('sector', 'Unknown')
        cirs = company.get('cirs', 40)
        ats = company.get('ats_platform', '') or 'Unknown'
        city = company.get('hq_city', '') or 'Unknown'

        tier_name = {1: 'Elite', 2: 'Strong MNC', 3: 'Unicorn', 4: 'Startup', 5: 'Niche'}.get(tier, '?')

        msg = (
            f"🏢 <b>CIRS: {name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Tier: {tier} ({tier_name})\n"
            f"Sector: {sector}\n"
            f"HQ: {city}\n"
            f"ATS: {ats}\n\n"
            f"📊 <b>CIRS Score: {cirs:.0f}/100</b>\n\n"
            f"Components:\n"
            f"  • Intent Signal Strength: —\n"
            f"  • Historical PPO Rate: —\n"
            f"  • Glassdoor Rating: —\n"
            f"  • Funding Recency: —\n"
            f"  • Posting Frequency: —\n"
            f"  • Career Page Health: —\n"
            f"\n💡 CIRS updates after each A-01 signal scan"
        )
        await update.message.reply_text(msg, parse_mode='HTML')

    async def _cmd_research(self, update, context):
        """Full company research brief."""
        if not context.args:
            await update.message.reply_text("Usage: /research <company name>")
            return

        company = ' '.join(context.args)
        await update.message.reply_text(f"🔍 Researching {company}... (30-60s)")

        try:
            response = self.router.research_company(company)
            if response.success:
                msg = (
                    f"🔍 <b>Research: {company}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{response.content[:3800]}"
                )
                await self._send_long_message(update, msg)
            else:
                await update.message.reply_text(f"❌ Failed: {response.error}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_stats(self, update, context):
        """Weekly funnel stats."""
        try:
            stats = self.db.get_weekly_stats()
            msg = self.formatter.stats_report(stats)
            await self._send_long_message(update, msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_health(self, update, context):
        """Agent health dashboard."""
        heartbeats = self.db.get_all_heartbeats()
        msg = self.formatter.health_report(heartbeats)
        await self._send_long_message(update, msg)

    async def _cmd_quota(self, update, context):
        """API quota usage including SerpAPI, Groq, Cerebras, DDG."""
        try:
            report = self.router.get_quota_report()
            await update.message.reply_text(report, parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _cmd_export(self, update, context):
        """Export top listings."""
        n = 50
        if context.args:
            try:
                n = int(context.args[0])
            except ValueError:
                pass

        listings = self.db.get_top_listings(n=min(n, 100))
        if not listings:
            await update.message.reply_text("📤 No listings to export")
            return

        lines = ["RANK | TITLE | COMPANY | PPO | STIPEND | LOCATION | SOURCE | URL"]
        lines.append("-" * 100)

        for i, l in enumerate(listings, 1):
            lines.append(
                f"{i} | {l.get('title', '')[:30]} | {l.get('company', '')[:20]} | "
                f"{l.get('ppo_score', 0):.1f} | ₹{l.get('stipend_monthly', 0) or 0:,.0f} | "
                f"{l.get('location', '')[:15]} | {l.get('source', '')} | {l.get('url', '')[:50]}"
            )

        text = '\n'.join(lines)
        # Split into chunks for Telegram
        for i in range(0, len(text), TG_MAX_LEN):
            await update.message.reply_text(text[i:i + TG_MAX_LEN])

    async def _cmd_settings(self, update, context):
        """User preferences."""
        if not context.args:
            college = self.db.get_setting('college', 'Not set')
            spec = self.db.get_setting('specialization', 'Not set')
            resume = 'Set ✅' if self.db.get_setting('user_resume', '') else 'Not set ❌'

            msg = (
                f"⚙️ <b>Settings</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎓 College: {college}\n"
                f"📚 Specialization: {spec}\n"
                f"📄 Resume: {resume}\n\n"
                f"<b>Set with:</b>\n"
                f"/settings college Your College Name\n"
                f"/settings spec Marketing\n"
                f"/settings resume [paste your resume text]"
            )
            await update.message.reply_text(msg, parse_mode='HTML')
            return

        key = context.args[0].lower()
        value = ' '.join(context.args[1:])

        if not value:
            await update.message.reply_text(f"Usage: /settings {key} <value>")
            return

        key_map = {
            'college': 'college',
            'spec': 'specialization',
            'specialization': 'specialization',
            'resume': 'user_resume',
        }

        db_key = key_map.get(key)
        if not db_key:
            await update.message.reply_text(
                f"❌ Unknown setting '{key}'\n"
                f"Available: college, spec, resume"
            )
            return

        self.db.set_setting(db_key, value)
        await update.message.reply_text(f"✅ <b>{key}</b> updated!", parse_mode='HTML')

    async def _cmd_refresh(self, update, context):
        """Force re-scrape."""
        await update.message.reply_text("🔄 Triggering refresh scrape... This may take 2-5 minutes.")

        try:
            from agents.a03_primary_scraper import get_primary_scraper
            scraper = get_primary_scraper()
            result = scraper.run_morning_scrape()

            total = result.get('total', 0) if isinstance(result, dict) else 0
            await update.message.reply_text(
                f"🔄 Refresh complete! {total} listings scraped.\n"
                f"Use /top to see latest rankings."
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Refresh failed: {e}")

    # ================================================================
    # /run COMMAND — MANUAL AGENT TRIGGER WITH STREAMING PROGRESS
    # ================================================================

    # Map of runnable agent names to their runner info
    _RUN_AGENTS = {
        'pipeline': {
            'desc': 'Full pipeline: scrape → dedup → ghost → enrich → PPO → brief',
            'steps': ['scrape', 'dedup', 'ghost', 'enrich', 'ppo', 'brief'],
        },
        'scrape': {
            'desc': 'A-03: Internshala full scrape (10 categories)',
            'agent': 'A-03',
        },
        'afternoon': {
            'desc': 'A-03: Naukri + IIMjobs afternoon scrape',
            'agent': 'A-03',
        },
        'dedup': {
            'desc': 'A-06: Deduplication engine',
            'agent': 'A-06',
        },
        'ghost': {
            'desc': 'A-05: Ghost job detection & scoring',
            'agent': 'A-05',
        },
        'enrich': {
            'desc': 'A-07: Intelligence enrichment + CIRS',
            'agent': 'A-07',
        },
        'ppo': {
            'desc': 'A-08: PPO scoring & ranking',
            'agent': 'A-08',
        },
        'intent': {
            'desc': 'A-01: Hiring intent signal scan',
            'agent': 'A-01',
        },
        'ats_crawl': {
            'desc': 'A-04: Company ATS career page crawl',
            'agent': 'A-04',
        },
        'dark': {
            'desc': 'A-02: Dark channel batch check',
            'agent': 'A-02',
        },
        'brief': {
            'desc': 'A-12: Generate & send morning brief',
            'agent': 'A-12',
        },
    }

    async def _cmd_run(self, update, context):
        """
        Run an agent or the full pipeline manually.
        Runs in the BACKGROUND so Telegram stays responsive.
        Streams real-time progress updates to the chat.
        """
        if not context.args:
            lines = [
                "🚀 <b>Manual Agent Runner</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "",
                "Usage: <code>/run &lt;agent&gt;</code>",
                "",
                "⚡ <b>Full Pipeline:</b>",
                "  <code>/run pipeline</code> — Runs ALL steps in order",
                "",
                "🔧 <b>Individual Agents:</b>",
            ]
            for name, info in self._RUN_AGENTS.items():
                if name == 'pipeline':
                    continue
                lines.append(f"  <code>/run {name}</code> — {info['desc']}")

            lines.append("")
            lines.append("📊 <b>Background Task Control:</b>")
            lines.append("  <code>/status</code> — See running tasks")
            lines.append("  <code>/cancel &lt;task&gt;</code> — Cancel a task")
            lines.append("")
            lines.append("💡 Agents run in background. You'll get live progress updates.")
            lines.append("💡 Scheduled cycles are NOT affected — they run at their normal times.")
            await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
            return

        agent_name = context.args[0].lower()

        if agent_name not in self._RUN_AGENTS:
            await update.message.reply_text(
                f"❌ Unknown agent '{agent_name}'\n"
                f"Available: {', '.join(self._RUN_AGENTS.keys())}\n"
                f"Use /run for full list."
            )
            return

        # Check if this agent is already running
        async with self._task_lock:
            if agent_name in self._running_tasks:
                task_info = self._running_tasks[agent_name]
                elapsed = time.time() - task_info['start_time']
                await update.message.reply_text(
                    f"⚠️ <b>{agent_name}</b> is already running "
                    f"({elapsed:.0f}s elapsed)\n"
                    f"Use /cancel {agent_name} to stop it first.",
                    parse_mode='HTML'
                )
                return

        info = self._RUN_AGENTS[agent_name]
        chat_id = update.effective_chat.id

        # Pipeline mode: run multiple agents in sequence
        if 'steps' in info:
            task = asyncio.create_task(
                self._run_pipeline_bg(chat_id, agent_name, info['steps'])
            )
        else:
            task = asyncio.create_task(
                self._run_single_agent_bg(chat_id, agent_name, info)
            )

        async with self._task_lock:
            self._running_tasks[agent_name] = {
                'task': task,
                'start_time': time.time(),
                'desc': info['desc'],
                'chat_id': chat_id,
                'status': 'running',
            }

        await update.message.reply_text(
            f"🏃 <b>{info['desc']}</b> — started in background\n"
            f"You'll get live progress updates here.\n"
            f"Use /status to check | /cancel {agent_name} to stop",
            parse_mode='HTML'
        )

    async def _stream_msg(self, chat_id: int, text: str):
        """Send a progress message to a specific chat."""
        try:
            if self._app and self._app.bot:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode='HTML'
                )
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Stream msg failed: {e}")

    async def _run_single_agent_bg(self, chat_id: int, agent_name: str, info: Dict):
        """Background task: Run a single agent with streaming updates."""
        start_time = time.time()
        try:
            result = await self._execute_agent(agent_name)
            duration = time.time() - start_time

            # Format result
            if isinstance(result, dict):
                result_str = '\n'.join(
                    f"  {k}: {v}" for k, v in result.items()
                    if k not in ('raw', 'listings', 'html')
                )
            elif result is not None:
                result_str = str(result)[:500]
            else:
                result_str = "  (completed, no detailed output)"

            await self._stream_msg(
                chat_id,
                f"✅ <b>{info['desc']}</b> — DONE\n"
                f"⏱ Duration: {duration:.1f}s\n\n"
                f"📊 Results:\n{result_str}"
            )

        except asyncio.CancelledError:
            duration = time.time() - start_time
            await self._stream_msg(
                chat_id,
                f"🛑 <b>{info['desc']}</b> — CANCELLED\n"
                f"⏱ Ran for: {duration:.1f}s"
            )
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{AGENT_ID}] /run {agent_name} failed: {e}")
            tb_str = traceback.format_exc()[-300:]
            await self._stream_msg(
                chat_id,
                f"❌ <b>{info['desc']}</b> — FAILED\n"
                f"⏱ Duration: {duration:.1f}s\n"
                f"Error: {str(e)[:200]}\n\n"
                f"<code>{tb_str}</code>"
            )
        finally:
            async with self._task_lock:
                self._running_tasks.pop(agent_name, None)

    async def _run_pipeline_bg(self, chat_id: int, task_name: str, steps: list):
        """Background task: Run full pipeline with per-step streaming."""
        total_start = time.time()
        await self._stream_msg(
            chat_id,
            "🚀 <b>FULL PIPELINE STARTING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Steps: {' → '.join(steps)}\n\n"
            "You'll get a progress update after each step."
        )

        results = {}
        failed = []

        for i, step in enumerate(steps, 1):
            info = self._RUN_AGENTS.get(step, {})
            desc = info.get('desc', step)
            step_start = time.time()

            await self._stream_msg(
                chat_id,
                f"⏳ [{i}/{len(steps)}] <b>{desc}</b>..."
            )

            try:
                result = await self._execute_agent(step)
                duration = time.time() - step_start

                # Extract summary
                if isinstance(result, dict):
                    summary = ', '.join(
                        f"{k}={v}" for k, v in result.items()
                        if k in ('total', 'new', 'processed', 'enriched',
                                 'scored', 'signals', 'duplicates', 'blue_ocean')
                    ) or 'OK'
                else:
                    summary = 'OK'

                results[step] = f"✅ {duration:.0f}s — {summary}"

                # Stream per-step completion
                await self._stream_msg(
                    chat_id,
                    f"  ✅ [{i}/{len(steps)}] {step}: {duration:.0f}s — {summary}"
                )

            except asyncio.CancelledError:
                results[step] = f"🛑 CANCELLED"
                failed.append(step)
                break
            except Exception as e:
                duration = time.time() - step_start
                results[step] = f"❌ {duration:.0f}s — {str(e)[:80]}"
                failed.append(step)
                logger.error(f"[{AGENT_ID}] Pipeline step '{step}' failed: {e}")
                # Continue with next step — partial processing is better than none

        # Final summary
        total_duration = time.time() - total_start
        lines = [
            f"🏁 <b>PIPELINE COMPLETE</b> — {total_duration:.0f}s",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        for step, result_str in results.items():
            lines.append(f"  {step}: {result_str}")

        if failed:
            lines.append(f"\n⚠️ {len(failed)} step(s) failed: {', '.join(failed)}")
        else:
            lines.append(f"\n🎉 All {len(steps)} steps completed!")

        lines.append(f"\n💡 Use /top or /morning to see results.")
        await self._stream_msg(chat_id, '\n'.join(lines))

        async with self._task_lock:
            self._running_tasks.pop(task_name, None)

    async def _execute_agent(self, agent_name: str):
        """
        Execute a specific agent and return its result.
        Handles both sync and async agent methods seamlessly.
        """
        loop = asyncio.get_event_loop()

        if agent_name == 'scrape':
            from agents.a03_primary_scraper import get_primary_scraper
            # run_morning_scrape is SYNC — run in executor to not block
            return await loop.run_in_executor(
                None, get_primary_scraper().run_morning_scrape
            )

        elif agent_name == 'afternoon':
            from agents.a03_primary_scraper import get_primary_scraper
            return await loop.run_in_executor(
                None, get_primary_scraper().run_afternoon_scrape
            )

        elif agent_name == 'dedup':
            from agents.a06_dedup_engine import get_dedup_engine
            return await loop.run_in_executor(
                None, get_dedup_engine().run_dedup
            )

        elif agent_name == 'ghost':
            from agents.a05_ghost_detector import get_ghost_detector
            return await loop.run_in_executor(
                None, get_ghost_detector().score_batch
            )

        elif agent_name == 'enrich':
            from agents.a07_intelligence_enricher import get_intelligence_enricher
            return await loop.run_in_executor(
                None, get_intelligence_enricher().run_enrichment
            )

        elif agent_name == 'ppo':
            from agents.a08_ppo_optimizer import get_ppo_optimizer
            return await loop.run_in_executor(
                None, get_ppo_optimizer().run_optimization
            )

        elif agent_name == 'intent':
            from agents.a01_intent_scanner import get_intent_scanner
            return await loop.run_in_executor(
                None, get_intent_scanner().run_scan
            )

        elif agent_name == 'ats_crawl':
            from agents.a04_ats_crawler import get_ats_crawler
            return await loop.run_in_executor(
                None, get_ats_crawler().run_crawl
            )

        elif agent_name == 'dark':
            from agents.a02_dark_channel import get_dark_channel_listener
            return await loop.run_in_executor(
                None, get_dark_channel_listener().run_batch_check
            )

        elif agent_name == 'brief':
            await self.send_morning_brief()
            return {'status': 'sent'}

        else:
            raise ValueError(f"Unknown agent: {agent_name}")

    # ================================================================
    # /status COMMAND — SHOW RUNNING BACKGROUND TASKS
    # ================================================================

    async def _cmd_status(self, update, context):
        """Show currently running background tasks."""
        async with self._task_lock:
            if not self._running_tasks:
                await update.message.reply_text(
                    "💤 No background tasks running.\n"
                    "Use /run to start an agent."
                )
                return

            lines = [
                "🏃 <b>Running Background Tasks</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "",
            ]
            for name, info in self._running_tasks.items():
                elapsed = time.time() - info['start_time']
                desc = info.get('desc', name)
                lines.append(
                    f"  🔄 <b>{name}</b>: {desc}\n"
                    f"     Running for {elapsed:.0f}s"
                )
            lines.append(f"\n💡 Use /cancel <task> to stop a task.")

        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')

    # ================================================================
    # /cancel COMMAND — CANCEL A RUNNING TASK
    # ================================================================

    async def _cmd_cancel(self, update, context):
        """Cancel a running background task."""
        if not context.args:
            async with self._task_lock:
                if not self._running_tasks:
                    await update.message.reply_text("💤 No tasks running.")
                    return
                names = ', '.join(self._running_tasks.keys())
            await update.message.reply_text(
                f"Usage: /cancel <task_name>\n"
                f"Running tasks: {names}"
            )
            return

        task_name = context.args[0].lower()

        async with self._task_lock:
            task_info = self._running_tasks.get(task_name)
            if not task_info:
                await update.message.reply_text(
                    f"❌ No task '{task_name}' is running.\n"
                    f"Use /status to see running tasks."
                )
                return

            task = task_info.get('task')
            if task and not task.done():
                task.cancel()
                await update.message.reply_text(
                    f"🛑 Cancelling <b>{task_name}</b>...",
                    parse_mode='HTML'
                )
            else:
                self._running_tasks.pop(task_name, None)
                await update.message.reply_text(
                    f"Task '{task_name}' already finished."
                )

    # ================================================================
    # /schedule COMMAND — SHOW SCHEDULE
    # ================================================================

    async def _cmd_schedule(self, update, context):
        """Show the full 24-hour schedule with next run times."""
        try:
            from core.scheduler import get_scheduler
            scheduler = get_scheduler()
            msg = scheduler.get_schedule_display()

            # Also show next runs from APScheduler
            jobs = scheduler.get_job_list()
            if jobs:
                msg += "\n\n📅 <b>Next Scheduled Runs:</b>\n"
                for job in jobs[:15]:
                    name = job.get('name', '')
                    next_run = job.get('next_run', 'N/A')
                    msg += f"  {name}\n    → {next_run}\n"

            await self._send_long_message(update, msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    # ================================================================
    # SCHEDULED REPORTS
    # ================================================================

    async def send_morning_brief(self):
        """Send scheduled morning brief at 07:15 IST."""
        logger.info(f"[{AGENT_ID}] Sending morning brief...")
        data = self.db.get_morning_brief_data()
        msg = self.formatter.morning_brief(data)
        await self.send_message(msg)

    async def send_evening_summary(self):
        """Send scheduled evening summary at 10:00 PM IST."""
        logger.info(f"[{AGENT_ID}] Sending evening summary...")
        data = {
            'today_total': self.db.count_clean_listings(hours=24),
            'afternoon_new': self.db.count_clean_listings(hours=12),
            'applied_today': self.db.count_outcomes_today(),
            'dark_finds': self.db.count_dark_listings_today(),
        }
        msg = self.formatter.evening_summary(data)
        await self.send_message(msg)

    async def send_urgent_alert(self, company: str, signal_score: float,
                                 signal_type: str):
        """Send urgent alert for high-value signals."""
        msg = (
            f"🚨 <b>URGENT SIGNAL ALERT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏢 <b>{company}</b>\n"
            f"📡 Signal: {signal_type}\n"
            f"💪 Score: {signal_score:.0f}/100\n\n"
            f"💡 Use /research {company} for details"
        )
        await self.send_message(msg)

    async def send_blue_ocean_alert(self, listing: Dict):
        """Send Blue Ocean discovery alert."""
        title = listing.get('title', 'Unknown')
        company = listing.get('company', 'Unknown')
        applicants = listing.get('applicants', 0)
        lid = listing.get('id', 0)

        msg = (
            f"🌊 <b>BLUE OCEAN ALERT!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>{title}</b> @ {company}\n"
            f"👥 Only {applicants} applicants!\n\n"
            f"Quick: /package {lid}"
        )
        await self.send_message(msg)

    # ================================================================
    # UTILITY METHODS
    # ================================================================

    async def _send_long_message(self, update, text: str):
        """Send a message, splitting if too long."""
        for i in range(0, len(text), TG_MAX_LEN):
            chunk = text[i:i + TG_MAX_LEN]
            try:
                await update.message.reply_text(chunk, parse_mode='HTML')
            except Exception:
                try:
                    await update.message.reply_text(chunk)
                except Exception as e:
                    logger.error(f"[{AGENT_ID}] Message send error: {e}")
                    break

    @staticmethod
    def _parse_listing_id(args) -> Optional[int]:
        """Parse listing ID from command arguments."""
        if not args:
            return None
        try:
            return int(args[0])
        except (ValueError, IndexError):
            return None


# ============================================================
# SINGLETON ACCESS
# ============================================================

_reporter_instance: Optional[TelegramReporter] = None


def get_telegram_reporter() -> TelegramReporter:
    """Get or create the singleton TelegramReporter instance."""
    global _reporter_instance
    if _reporter_instance is None:
        _reporter_instance = TelegramReporter()
    return _reporter_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test ReportFormatter
    formatter = ReportFormatter()

    # Test morning brief format
    test_data = {
        'total_new': 150,
        'after_ghost_filter': 95,
        'blue_ocean_count': 3,
        'signals_fired': 7,
        'top_10': [
            {'title': 'Marketing Intern', 'company': 'McKinsey', 'ppo_score': 85.2,
             'is_blue_ocean': True, 'is_ppo': True, 'stipend_monthly': 50000},
        ],
        'dark_finds': [],
        'urgent_deadlines': [],
    }
    print("\nMorning Brief Preview:")
    print(formatter.morning_brief(test_data)[:500])

    print(f"\nCommands registered: 26")
    print(f"Message max length: {TG_MAX_LEN}")
    print(f"Valid outcomes: {', '.join(VALID_OUTCOMES)}")
    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) ready!")
    print("=" * 60)
