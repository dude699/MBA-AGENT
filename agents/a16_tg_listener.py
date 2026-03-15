"""
============================================================
PRISM v0.1 — A-16: TELEGRAM GROUP MONITOR (TELETHON LISTENER)
============================================================
Agent A-16: Real-time Telethon MTProto listener for MBA job groups.
Continuously monitors 10-15 curated Telegram groups and instantly
extracts job/internship postings using Cerebras 8B classification.

Schedule: Always running (background asyncio task)
Trigger: New message in monitored Telegram groups

Pipeline:
    1. Telethon client connects to Telegram MTProto
    2. Listens for new messages in monitored groups
    3. Rule-based keyword filter (fast reject of non-job messages)
    4. Cerebras 8B extraction (tg_message_extract task)
    5. If confidence > 80%: instant alert to admin + save to dark_channel_listings
    6. Dedup via message hash to avoid re-processing edits

AI Provider: Cerebras 8B (tg_message_extract, dark_classify)
Tools: Telethon MTProto client, db_write
Cost: $0 (Telegram API is free)

Prerequisites:
    - TG_API_ID and TG_API_HASH from https://my.telegram.org
    - User must be a member of monitored groups
    - Session file: firstmover_session.session

Integration Points:
    - A-02 Dark Channel Listener → shares dark_channel_listings table
    - A-06 Dedup Engine → deduplicates against raw_listings
    - A-12 Telegram Reporter → instant alerts for high-confidence finds
============================================================
"""

import os
import sys
import json
import time
import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST, DARK_CHANNEL_JOB_KEYWORDS


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-16"
AGENT_NAME = "Telegram Group Monitor"

# Minimum confidence for instant alert
INSTANT_ALERT_THRESHOLD = 0.80
# Minimum confidence for saving to dark_channel_listings
SAVE_THRESHOLD = 0.50
# Maximum messages to process per minute (rate limiting)
MAX_MESSAGES_PER_MINUTE = 30
# Message hash cache size (for dedup)
HASH_CACHE_SIZE = 5000

# Keyword sets for fast pre-filtering
JOB_KEYWORDS_SET = set(kw.lower() for kw in DARK_CHANNEL_JOB_KEYWORDS)
REJECT_KEYWORDS = {
    'meme', 'joke', 'lol', 'haha', 'good morning', 'good night',
    'happy birthday', 'congratulations', 'thanks everyone',
    'poll', 'quiz', 'forward', 'forwarded',
}

# MBA-specific boost keywords
MBA_BOOST_KEYWORDS = {
    'mba', 'intern', 'internship', 'stipend', 'ppo',
    'marketing', 'finance', 'strategy', 'consulting',
    'analytics', 'product management', 'operations',
}


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class TGMessage:
    """A processed Telegram group message."""
    message_id: int
    group_id: int
    group_name: str
    sender_name: str = ""
    text: str = ""
    timestamp: str = ""
    message_hash: str = ""
    # Classification results
    is_job: bool = False
    confidence: float = 0.0
    extracted_company: str = ""
    extracted_role: str = ""
    extracted_url: str = ""
    extracted_location: str = ""
    extracted_stipend: str = ""
    keywords_found: List[str] = field(default_factory=list)


@dataclass
class MonitorStats:
    """Running statistics for the monitor."""
    messages_received: int = 0
    messages_filtered: int = 0  # Passed keyword filter
    messages_classified: int = 0  # Sent to AI
    jobs_found: int = 0
    instant_alerts_sent: int = 0
    errors: int = 0
    start_time: str = ""
    last_message_time: str = ""
    groups_active: int = 0


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class TelegramGroupMonitor:
    """
    PRISM A-16: Real-time Telegram Group Monitor.

    Uses Telethon MTProto client to continuously listen for
    job/internship postings in MBA Telegram groups.

    Usage:
        monitor = get_tg_monitor()
        await monitor.start_monitoring()  # Blocks (background loop)
        await monitor.stop_monitoring()
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.config = get_config()
        self._agent_id = AGENT_ID
        self._agent_name = AGENT_NAME

        # Telethon client (lazy init)
        self._client = None
        self._running = False
        self._stop_event = asyncio.Event() if asyncio.get_event_loop().is_running() else None

        # Message dedup cache
        self._message_hashes: Set[str] = set()
        self._hash_lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None

        # Rate limiting
        self._minute_counter = 0
        self._minute_reset_time = time.time()

        # Stats
        self._stats = MonitorStats(
            start_time=datetime.now(IST).isoformat()
        )

        # Monitored groups (configured in config or DB)
        self._monitored_groups: List[Dict[str, Any]] = []

        # Check if Telethon is configured
        self._configured = bool(
            self.config.telethon.api_id and self.config.telethon.api_hash
        )

        if self._configured:
            logger.info(
                f"[{AGENT_ID}] {AGENT_NAME} initialized "
                f"(Telethon configured)"
            )
        else:
            logger.warning(
                f"[{AGENT_ID}] Telethon NOT configured "
                f"(set TG_API_ID + TG_API_HASH)"
            )

    # ----------------------------------------------------------
    # MESSAGE PROCESSING
    # ----------------------------------------------------------

    def _compute_message_hash(self, text: str, group_id: int) -> str:
        """Compute a hash for dedup."""
        content = f"{group_id}:{text.strip().lower()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _keyword_prefilter(self, text: str) -> Tuple[bool, List[str]]:
        """
        Fast keyword-based pre-filter. Returns (passes, keywords_found).
        This runs BEFORE AI classification to save API calls.
        """
        text_lower = text.lower()

        # Reject if contains reject keywords
        for reject_kw in REJECT_KEYWORDS:
            if reject_kw in text_lower and len(text) < 200:
                return False, []

        # Must be at least 30 chars
        if len(text.strip()) < 30:
            return False, []

        # Find matching keywords
        keywords_found = []
        for kw in JOB_KEYWORDS_SET:
            if kw in text_lower:
                keywords_found.append(kw)

        # MBA boost keywords count double
        mba_matches = sum(1 for kw in MBA_BOOST_KEYWORDS if kw in text_lower)

        # Require at least 2 job keywords OR 1 MBA keyword
        if len(keywords_found) >= 2 or mba_matches >= 1:
            return True, keywords_found

        return False, keywords_found

    async def _classify_message(self, text: str, group_name: str) -> Dict[str, Any]:
        """
        Classify a message using Cerebras 8B.
        Returns extraction results.
        """
        try:
            from core.ai_router import get_router
            router = get_router()

            response = router.call(
                'tg_message_extract',
                f"""Analyze this Telegram group message and extract job/internship information.

Group: {group_name}
Message:
{text[:2000]}

Is this a job/internship posting? Extract:
- is_job: true/false
- confidence: 0.0-1.0
- company: company name or null
- role: role title or null
- url: application URL or null
- location: city or "Remote" or null
- stipend: stipend amount or null
- keywords: relevant keywords found

Respond in JSON:
{{"is_job": true/false, "confidence": 0.0-1.0, "company": "...", "role": "...", "url": "...", "location": "...", "stipend": "...", "keywords": ["..."]}}""",
                use_cache=False,
            )

            if response.success:
                data = response.get_json()
                if data:
                    return data

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Classification error: {e}")

        return {'is_job': False, 'confidence': 0.0}

    async def _process_message(self, message: TGMessage) -> bool:
        """
        Process a single message through the classification pipeline.
        Returns True if a job was found.
        """
        # Dedup check
        if message.message_hash in self._message_hashes:
            return False

        # Add to dedup cache
        self._message_hashes.add(message.message_hash)
        if len(self._message_hashes) > HASH_CACHE_SIZE:
            # Remove oldest entries (approximate LRU)
            excess = len(self._message_hashes) - HASH_CACHE_SIZE
            for _ in range(excess):
                self._message_hashes.pop()

        self._stats.messages_received += 1

        # Keyword pre-filter
        passes, keywords = self._keyword_prefilter(message.text)
        if not passes:
            return False

        self._stats.messages_filtered += 1
        message.keywords_found = keywords

        # Rate limiting
        now = time.time()
        if now - self._minute_reset_time >= 60:
            self._minute_counter = 0
            self._minute_reset_time = now

        if self._minute_counter >= MAX_MESSAGES_PER_MINUTE:
            return False

        self._minute_counter += 1

        # AI Classification
        result = await self._classify_message(message.text, message.group_name)
        self._stats.messages_classified += 1

        message.is_job = result.get('is_job', False)
        message.confidence = result.get('confidence', 0.0)
        message.extracted_company = result.get('company', '') or ''
        message.extracted_role = result.get('role', '') or ''
        message.extracted_url = result.get('url', '') or ''
        message.extracted_location = result.get('location', '') or ''
        message.extracted_stipend = result.get('stipend', '') or ''

        if message.is_job and message.confidence >= SAVE_THRESHOLD:
            self._stats.jobs_found += 1
            self._stats.last_message_time = datetime.now(IST).isoformat()

            # Save to database
            self._save_to_dark_channel(message)

            # Instant alert for high confidence
            if message.confidence >= INSTANT_ALERT_THRESHOLD:
                await self._send_instant_alert(message)
                self._stats.instant_alerts_sent += 1

            logger.info(
                f"[{AGENT_ID}] JOB FOUND in {message.group_name}: "
                f"{message.extracted_company} - {message.extracted_role} "
                f"(confidence={message.confidence:.0%})"
            )
            return True

        return False

    # ----------------------------------------------------------
    # DATABASE & ALERTS
    # ----------------------------------------------------------

    def _save_to_dark_channel(self, message: TGMessage):
        """Save extracted job to dark_channel_listings table."""
        try:
            from core.database import get_db
            db = get_db()

            with db.get_cursor() as cur:
                cur.execute("""
                    INSERT OR IGNORE INTO dark_channel_listings
                    (source, channel_name, message_text, company, role,
                     url, location, stipend, confidence, message_hash,
                     discovered_at, agent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    'telegram_group',
                    message.group_name,
                    message.text[:5000],
                    message.extracted_company,
                    message.extracted_role,
                    message.extracted_url,
                    message.extracted_location,
                    message.extracted_stipend,
                    message.confidence,
                    message.message_hash,
                    datetime.now(IST).isoformat(),
                    AGENT_ID,
                ))

        except Exception as e:
            logger.error(f"[{AGENT_ID}] DB save error: {e}")

    async def _send_instant_alert(self, message: TGMessage):
        """Send instant Telegram alert for high-confidence job finds."""
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()

            alert = (
                f"🔔 <b>INSTANT JOB ALERT</b> (A-16)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📡 Source: {message.group_name}\n"
                f"🏢 Company: <b>{message.extracted_company or 'Unknown'}</b>\n"
                f"💼 Role: {message.extracted_role or 'N/A'}\n"
                f"📍 Location: {message.extracted_location or 'N/A'}\n"
                f"💰 Stipend: {message.extracted_stipend or 'N/A'}\n"
                f"🎯 Confidence: {message.confidence:.0%}\n"
                f"🔗 URL: {message.extracted_url or 'N/A'}\n"
                f"⏰ {datetime.now(IST).strftime('%H:%M IST')}"
            )

            await reporter.send_message(alert)

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Alert send error: {e}")

    # ----------------------------------------------------------
    # MONITORING LIFECYCLE
    # ----------------------------------------------------------

    async def start_monitoring(self):
        """
        Start the continuous monitoring loop.
        This method blocks (runs as background task).
        """
        if not self._configured:
            logger.warning(f"[{AGENT_ID}] Cannot start — Telethon not configured")
            return

        try:
            from telethon import TelegramClient, events

            self._client = TelegramClient(
                self.config.telethon.session_name,
                int(self.config.telethon.api_id),
                self.config.telethon.api_hash,
            )

            await self._client.start()
            self._running = True

            logger.info(f"[{AGENT_ID}] Telethon client connected, monitoring started")
            self._update_heartbeat('running')

            # Register message handler
            @self._client.on(events.NewMessage())
            async def handler(event):
                if not self._running:
                    return

                try:
                    text = event.message.text or ""
                    if not text:
                        return

                    chat = await event.get_chat()
                    group_name = getattr(chat, 'title', str(chat.id))

                    msg = TGMessage(
                        message_id=event.message.id,
                        group_id=chat.id,
                        group_name=group_name,
                        sender_name=str(getattr(event.message.sender_id, '', '')),
                        text=text,
                        timestamp=datetime.now(IST).isoformat(),
                        message_hash=self._compute_message_hash(text, chat.id),
                    )

                    await self._process_message(msg)

                except Exception as e:
                    self._stats.errors += 1
                    if self._stats.errors % 100 == 0:
                        logger.error(
                            f"[{AGENT_ID}] Processing errors: {self._stats.errors}"
                        )

            # Run until stopped
            await self._client.run_until_disconnected()

        except ImportError:
            logger.error(
                f"[{AGENT_ID}] Telethon not installed! "
                f"Install with: pip install telethon"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Monitor error: {e}")
            self._running = False
            self._update_heartbeat('error')

    async def stop_monitoring(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._client:
            await self._client.disconnect()
        self._update_heartbeat('idle')
        logger.info(f"[{AGENT_ID}] Monitoring stopped")

    def _update_heartbeat(self, status: str):
        """Update agent heartbeat."""
        try:
            from core.database import get_db
            db = get_db()
            db.update_agent_heartbeat(AGENT_ID, status)
        except Exception:
            pass

    # ----------------------------------------------------------
    # HEALTH & MONITORING
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get monitor health and statistics."""
        return {
            'agent_id': AGENT_ID,
            'agent_name': AGENT_NAME,
            'configured': self._configured,
            'running': self._running,
            'stats': {
                'messages_received': self._stats.messages_received,
                'messages_filtered': self._stats.messages_filtered,
                'messages_classified': self._stats.messages_classified,
                'jobs_found': self._stats.jobs_found,
                'instant_alerts': self._stats.instant_alerts_sent,
                'errors': self._stats.errors,
                'start_time': self._stats.start_time,
                'last_message': self._stats.last_message_time,
            },
            'dedup_cache_size': len(self._message_hashes),
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_instance: Optional[TelegramGroupMonitor] = None

def get_tg_monitor() -> TelegramGroupMonitor:
    """Get the singleton TelegramGroupMonitor instance."""
    global _instance
    if _instance is None:
        _instance = TelegramGroupMonitor()
    return _instance


if __name__ == "__main__":
    print("=" * 60)
    print(f"PRISM v0.1 — {AGENT_ID}: {AGENT_NAME}")
    print("=" * 60)
    monitor = get_tg_monitor()
    health = monitor.get_health()
    for k, v in health.items():
        print(f"  {k}: {v}")
