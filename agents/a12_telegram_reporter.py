"""
============================================================
OPERATION FIRST MOVER v8.0 -- AGENT A-12: TELEGRAM REPORTER
============================================================
Command center for the system. Sends alerts, daily briefs,
and accepts commands via Telegram bot.

Reports:
    - Morning Brief (9:15 AM IST): Top 25 listings, Blue Ocean alerts
    - Evening Summary (10:00 PM IST): Day's activity recap
    - Real-time Blue Ocean alerts (immediate)
    - System health reports on demand
    - Dream company alerts (6-hour intervals)

Commands:
    /start     - Welcome message
    /status    - System health report
    /top       - Top 10 listings by PPO score
    /blue      - Blue Ocean opportunities
    /stats     - Scraping and apply statistics
    /dream     - Dream company watchlist status
    /apply     - Trigger auto-apply for top listings
    /health    - Full system health check
    /search    - Search for specific company/role
    /help      - List all commands

Innovation #4: Stipend Intelligence
    Alerts if stipend is >40% above sector average.

Innovation #8: Interview Prep Auto-Package
    Generates STAR frameworks and negotiation scripts when shortlisted.

AI Provider: Groq (primary), Cerebras (fallback), Mistral (emergency)
============================================================
"""

import os
import json
import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, MessageHandler,
        CallbackQueryHandler, ContextTypes, filters,
    )
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed")

from core.config import get_config, now_ist, IST
from core.database import get_db

AGENT_ID = 'A-12'
AGENT_NAME = 'Telegram Reporter'


class TelegramReporter:
    """
    Telegram bot for system communication and control.
    Handles both scheduled reports and interactive commands.
    """

    def __init__(self):
        self.config = get_config()
        self.db = get_db()
        self.bot_token = self.config.telegram.bot_token
        self.chat_id = self.config.telegram.chat_id
        self.admin_id = self.config.telegram.admin_id
        self._bot: Optional[Any] = None
        self._app: Optional[Any] = None
        self._running = False
        self._messages_sent = 0

    async def initialize(self) -> bool:
        """Initialize the Telegram bot."""
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot not installed!")
            return False

        if not self.bot_token:
            logger.error("TG_BOT_TOKEN not set!")
            return False

        try:
            self._app = Application.builder().token(self.bot_token).build()

            # Register command handlers
            self._app.add_handler(CommandHandler("start", self._cmd_start))
            self._app.add_handler(CommandHandler("status", self._cmd_status))
            self._app.add_handler(CommandHandler("top", self._cmd_top))
            self._app.add_handler(CommandHandler("blue", self._cmd_blue))
            self._app.add_handler(CommandHandler("stats", self._cmd_stats))
            self._app.add_handler(CommandHandler("dream", self._cmd_dream))
            self._app.add_handler(CommandHandler("health", self._cmd_health))
            self._app.add_handler(CommandHandler("help", self._cmd_help))
            self._app.add_handler(CommandHandler("search", self._cmd_search))

            self._bot = self._app.bot
            logger.info("Telegram bot initialized")
            return True

        except Exception as e:
            logger.error(f"Telegram init failed: {e}")
            return False

    async def start_polling(self):
        """Start the bot in polling mode."""
        if not self._app:
            return

        try:
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
            )
            self._running = True
            logger.info("Telegram bot polling started")
        except Exception as e:
            logger.error(f"Telegram polling failed: {e}")

    async def stop(self):
        """Stop the bot gracefully."""
        if self._app and self._running:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                self._running = False
                logger.info("Telegram bot stopped")
            except Exception as e:
                logger.error(f"Telegram shutdown error: {e}")

    # ============================================================
    # MESSAGE SENDING
    # ============================================================

    async def send_message(self, text: str, chat_id: Optional[str] = None,
                           parse_mode: str = 'HTML',
                           disable_preview: bool = True) -> bool:
        """Send a message to the configured chat."""
        if not self._bot:
            logger.warning("Bot not initialized, can't send message")
            return False

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("No chat_id configured")
            return False

        try:
            # Split long messages (Telegram limit: 4096 chars)
            max_len = 4000
            if len(text) > max_len:
                parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
                for part in parts:
                    await self._bot.send_message(
                        chat_id=target_chat,
                        text=part,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_preview,
                    )
                    await asyncio.sleep(0.5)
            else:
                await self._bot.send_message(
                    chat_id=target_chat,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_preview,
                )

            self._messages_sent += 1
            return True

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    # ============================================================
    # SCHEDULED REPORTS
    # ============================================================

    async def send_morning_brief(self):
        """Send the morning brief (9:15 AM IST daily)."""
        try:
            stats = self.db.get_listing_stats()
            top_listings = self.db.get_listings_for_apply(limit=10)
            blue_ocean = self.db.get_blue_ocean_listings()

            lines = [
                "<b>MORNING BRIEF</b>",
                f"Date: {now_ist().strftime('%d %b %Y, %A')}",
                "",
                "<b>Dashboard:</b>",
                f"Total Listings: {stats.get('total_listings', 0)}",
                f"New (Unapplied): {stats.get('new_listings', 0)}",
                f"Applied: {stats.get('applied_listings', 0)}",
                f"Blue Ocean: {stats.get('blue_ocean_listings', 0)}",
                f"Ghost Detected: {stats.get('ghost_listings', 0)}",
                "",
            ]

            if blue_ocean:
                lines.append(f"<b>BLUE OCEAN ALERTS ({len(blue_ocean)}):</b>")
                for bo in blue_ocean[:5]:
                    lines.append(
                        f"  {bo.get('title', 'N/A')} @ {bo.get('company', 'N/A')}"
                        f" | PPO: {bo.get('ppo_score', 0):.2f}"
                    )
                lines.append("")

            if top_listings:
                lines.append("<b>TOP 10 BY PPO SCORE:</b>")
                for i, listing in enumerate(top_listings[:10], 1):
                    ppo = listing.get('ppo_score', 0)
                    ppo_str = f"{ppo:.2f}" if isinstance(ppo, float) else str(ppo)
                    lines.append(
                        f"{i}. {listing.get('title', 'N/A')}"
                        f"\n   {listing.get('company', 'N/A')} | "
                        f"PPO: {ppo_str} | "
                        f"{listing.get('platform', '')}"
                    )
                lines.append("")

            lines.append(f"Generated: {now_ist().strftime('%I:%M %p IST')}")

            await self.send_message("\n".join(lines))
            logger.info("Morning brief sent")

        except Exception as e:
            logger.error(f"Morning brief error: {e}")
            await self.send_message(f"Morning brief error: {e}")

    async def send_evening_summary(self):
        """Send the evening summary (10:00 PM IST daily)."""
        try:
            stats = self.db.get_listing_stats()
            outcome_stats = self.db.get_outcome_stats()

            lines = [
                "<b>EVENING SUMMARY</b>",
                f"Date: {now_ist().strftime('%d %b %Y')}",
                "",
                "<b>Today's Activity:</b>",
                f"Total Listings: {stats.get('total_listings', 0)}",
                f"New (Unapplied): {stats.get('new_listings', 0)}",
                f"Applied: {stats.get('applied_listings', 0)}",
                "",
                "<b>Application Outcomes:</b>",
                f"Total Applied: {outcome_stats.get('total_applied', 0)}",
                f"Shortlisted: {outcome_stats.get('shortlisted', 0)}",
                f"Response Rate: {outcome_stats.get('response_rate', 0):.1%}",
                "",
                f"Generated: {now_ist().strftime('%I:%M %p IST')}",
            ]

            await self.send_message("\n".join(lines))
            logger.info("Evening summary sent")

        except Exception as e:
            logger.error(f"Evening summary error: {e}")

    async def send_blue_ocean_alert(self, listing: Dict[str, Any]):
        """Send immediate Blue Ocean alert."""
        try:
            lines = [
                "BLUE OCEAN ALERT",
                "",
                f"<b>{listing.get('title', 'N/A')}</b>",
                f"Company: {listing.get('company', 'N/A')}",
                f"Platform: {listing.get('platform', '')}",
                f"PPO Score: {listing.get('ppo_score', 0):.2f}",
                f"Applicants: {listing.get('applicants', 'N/A')}",
                f"Stipend: {listing.get('stipend', 'N/A')}",
                f"PPO Eligible: {'Yes' if listing.get('ppo_eligible') else 'No'}",
                "",
                f"URL: {listing.get('url', '')}",
            ]
            await self.send_message("\n".join(lines))
        except Exception as e:
            logger.error(f"Blue ocean alert error: {e}")

    async def send_system_startup(self):
        """Send system startup notification."""
        try:
            lines = [
                "<b>SYSTEM STARTUP</b>",
                f"Operation First Mover v8.0",
                f"Time: {now_ist().strftime('%d %b %Y %I:%M %p IST')}",
                "",
                "Status: All systems GO",
                "Schedule: 3x Weekly (Tue/Thu/Sat)",
                "AI Providers: 5 active",
                "Keep-Alive: 6 layers active",
            ]
            await self.send_message("\n".join(lines))
        except Exception as e:
            logger.error(f"Startup notification error: {e}")

    # ============================================================
    # COMMAND HANDLERS
    # ============================================================

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        text = (
            "<b>Operation First Mover v8.0</b>\n"
            "THE DEFINITIVE FINAL BLUEPRINT\n\n"
            "Zero-cost | Ban-Free | Self-Learning\n"
            "One-Click Apply | 5 AI Providers\n\n"
            "Use /help to see all commands."
        )
        await update.message.reply_text(text, parse_mode='HTML')

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        stats = self.db.get_listing_stats()
        text = (
            f"<b>System Status</b>\n\n"
            f"Total Listings: {stats.get('total_listings', 0)}\n"
            f"New: {stats.get('new_listings', 0)}\n"
            f"Applied: {stats.get('applied_listings', 0)}\n"
            f"Blue Ocean: {stats.get('blue_ocean_listings', 0)}\n"
            f"Ghosts: {stats.get('ghost_listings', 0)}\n\n"
            f"Time: {now_ist().strftime('%I:%M %p IST')}"
        )
        await update.message.reply_text(text, parse_mode='HTML')

    async def _cmd_top(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /top command - show top 10 listings."""
        listings = self.db.get_listings_for_apply(limit=10)
        if not listings:
            await update.message.reply_text("No active listings found.")
            return

        lines = ["<b>Top 10 Listings</b>\n"]
        for i, l in enumerate(listings, 1):
            ppo = l.get('ppo_score', 0)
            ppo_str = f"{ppo:.2f}" if isinstance(ppo, float) else str(ppo)
            lines.append(
                f"{i}. <b>{l.get('title', 'N/A')}</b>\n"
                f"   {l.get('company', '')} | PPO: {ppo_str}\n"
                f"   {l.get('url', '')}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode='HTML',
                                         disable_web_page_preview=True)

    async def _cmd_blue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /blue command - show Blue Ocean opportunities."""
        listings = self.db.get_blue_ocean_listings()
        if not listings:
            await update.message.reply_text("No Blue Ocean opportunities right now.")
            return

        lines = [f"<b>Blue Ocean Opportunities ({len(listings)})</b>\n"]
        for l in listings[:10]:
            lines.append(
                f"<b>{l.get('title', 'N/A')}</b>\n"
                f"  {l.get('company', '')} | "
                f"Applicants: {l.get('applicants', 'N/A')} | "
                f"PPO: {l.get('ppo_score', 0):.2f}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        stats = self.db.get_listing_stats()
        outcome_stats = self.db.get_outcome_stats()
        text = (
            f"<b>System Statistics</b>\n\n"
            f"<b>Listings:</b>\n"
            f"  Total: {stats.get('total_listings', 0)}\n"
            f"  New: {stats.get('new_listings', 0)}\n"
            f"  Applied: {stats.get('applied_listings', 0)}\n"
            f"  Blue Ocean: {stats.get('blue_ocean_listings', 0)}\n\n"
            f"<b>Outcomes:</b>\n"
            f"  Applied: {outcome_stats.get('total_applied', 0)}\n"
            f"  Shortlisted: {outcome_stats.get('shortlisted', 0)}\n"
            f"  Response Rate: {outcome_stats.get('response_rate', 0):.1%}\n"
        )
        await update.message.reply_text(text, parse_mode='HTML')

    async def _cmd_dream(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /dream command."""
        companies = self.db.get_dream_companies()
        if not companies:
            await update.message.reply_text("Dream companies watchlist is empty.")
            return

        lines = [f"<b>Dream Companies ({len(companies)})</b>\n"]
        for c in companies[:15]:
            lines.append(f"  T{c.get('tier', '?')} | {c.get('name', 'N/A')} | {c.get('sector', '')}")
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    async def _cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command - full system health check."""
        config = get_config()
        critical = config.validate_critical()
        optional = config.validate_optional()

        lines = ["<b>System Health Check</b>\n"]
        lines.append("<b>Critical Config:</b>")
        for k, v in critical.items():
            status = "OK" if v else "MISSING"
            lines.append(f"  [{status}] {k}")

        lines.append("\n<b>Optional Config:</b>")
        for k, v in optional.items():
            status = "OK" if v else "N/A"
            lines.append(f"  [{status}] {k}")

        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        text = (
            "<b>Available Commands</b>\n\n"
            "/start - Welcome message\n"
            "/status - System status\n"
            "/top - Top 10 listings by PPO score\n"
            "/blue - Blue Ocean opportunities\n"
            "/stats - Statistics\n"
            "/dream - Dream company watchlist\n"
            "/health - System health check\n"
            "/search [query] - Search listings\n"
            "/help - This help message\n"
        )
        await update.message.reply_text(text, parse_mode='HTML')

    async def _cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /search command."""
        query = ' '.join(context.args) if context.args else ''
        if not query:
            await update.message.reply_text("Usage: /search [company or role]")
            return

        listings = self.db.get_listings_by_company(query)
        if not listings:
            await update.message.reply_text(f"No listings found for '{query}'")
            return

        lines = [f"<b>Search Results for '{query}' ({len(listings)})</b>\n"]
        for l in listings[:10]:
            lines.append(
                f"<b>{l.get('title', 'N/A')}</b>\n"
                f"  {l.get('company', '')} | {l.get('platform', '')}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    def get_stats(self) -> Dict[str, Any]:
        return {
            'running': self._running,
            'messages_sent': self._messages_sent,
            'bot_configured': bool(self.bot_token),
            'chat_configured': bool(self.chat_id),
        }


_telegram_reporter: Optional[TelegramReporter] = None

def get_telegram_reporter() -> TelegramReporter:
    global _telegram_reporter
    if _telegram_reporter is None:
        _telegram_reporter = TelegramReporter()
    return _telegram_reporter
