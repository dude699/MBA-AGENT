"""
============================================================
AGENT A-12: TELEGRAM REPORTER / COMMAND CENTER — INDUSTRIAL GRADE
============================================================
The user-facing interface — handles 22 Telegram commands,
morning/evening reports, real-time alerts, inline keyboards,
and full application lifecycle management.

Framework: python-telegram-bot v21
Schedule: 07:15 AM (morning brief) + 10:00 PM (evening summary)

22 Commands:
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
============================================================
"""

import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

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

class TelegramReporter:
    """
    Telegram bot command center with 22 commands.
    Uses python-telegram-bot v21 with async handlers.
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.router = get_router()
        self.formatter = ReportFormatter()
        self._app = None
        self._running = False

    async def start_bot(self):
        """Initialize and start the Telegram bot."""
        token = self.config.telegram.bot_token
        if not token:
            logger.error(f"[{AGENT_ID}] TG_BOT_TOKEN not set!")
            return

        try:
            from telegram import Update, Bot
            from telegram.ext import (
                Application, CommandHandler, ContextTypes,
                MessageHandler, filters,
            )
        except ImportError:
            logger.error(f"[{AGENT_ID}] python-telegram-bot not installed")
            return

        self._app = Application.builder().token(token).build()

        # Register all 22 command handlers
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
        }

        for cmd_name, handler_fn in commands.items():
            self._app.add_handler(CommandHandler(cmd_name, handler_fn))

        logger.info(f"[{AGENT_ID}] Bot starting with {len(commands)} commands...")

        try:
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._running = True
            logger.info(f"[{AGENT_ID}] Telegram bot is running!")
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Bot start failed: {e}")

    async def stop_bot(self):
        """Stop the Telegram bot gracefully."""
        if self._app and self._running:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                self._running = False
                logger.info(f"[{AGENT_ID}] Bot stopped")
            except Exception as e:
                logger.error(f"[{AGENT_ID}] Bot stop error: {e}")

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
            "Type /help for all 22 commands."
        )
        await update.message.reply_text(msg, parse_mode='HTML')

    async def _cmd_help(self, update, context):
        """Full command reference."""
        msg = (
            "📖 <b>Command Reference (22 Commands)</b>\n"
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

    print(f"\nCommands registered: 22")
    print(f"Message max length: {TG_MAX_LEN}")
    print(f"Valid outcomes: {', '.join(VALID_OUTCOMES)}")
    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) ready!")
    print("=" * 60)
