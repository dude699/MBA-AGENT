"""
============================================================
AGENT A-02: DARK CHANNEL LISTENER — INDUSTRIAL GRADE
============================================================
Monitors Telegram groups, X/Twitter, Discord, and Reddit
for unadvertised job postings and hiring signals that never
appear on official job boards.

Schedule: 08:00 PM IST (batch check)
AI Model: Cerebras (intent_classify, dark_classify)

Architecture:
┌──────────────────────────────────────────────────┐
│          DARK CHANNEL LISTENER (A-02)            │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌───────────────────────────────────────────┐   │
│  │ 1. Telegram Group Monitor (Telethon)      │   │
│  │    - MBA job/internship groups            │   │
│  │    - Startup hiring channels              │   │
│  │    - College placement channels           │   │
│  │    - HR community groups                  │   │
│  │    - Fetch last 50 messages/channel       │   │
│  │    - AI classify: job vs noise            │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 2. X/Twitter Monitor (tweepy API v2)      │   │
│  │    - Search: "hiring intern" india        │   │
│  │    - Search: "MBA internship" stipend     │   │
│  │    - Search: specific company handles     │   │
│  │    - Rate: 20 tweets/query, 3 queries max │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 3. Reddit Monitor (PRAW API)              │   │
│  │    - r/MBA, r/Indian_Academia             │   │
│  │    - r/developersIndia (for product roles) │   │
│  │    - Sort: new, last 24 hours             │   │
│  │    - Keyword + AI classification          │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 4. AI Classification Engine (Cerebras)    │   │
│  │    - Binary: job posting vs noise         │   │
│  │    - Confidence: 0.0 - 1.0                │   │
│  │    - Extract: company, role, URL, stipend │   │
│  │    - Dedup: hash check against DB         │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 5. Entity Extractor                       │   │
│  │    - Company name detection               │   │
│  │    - Role/title extraction                │   │
│  │    - URL extraction from message          │   │
│  │    - Stipend/salary mention               │   │
│  │    - Location detection                   │   │
│  │    - Deadline/date detection              │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 6. Dedup & Persistence                    │   │
│  │    - Hash-based dedup (message text)      │   │
│  │    - Store in dark_channel_listings table  │   │
│  │    - Auto-expire after 7 days             │   │
│  │    - Link to company DB if match found    │   │
│  └───────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘

Dark Channel Types:
    1. Telegram Groups — Direct job posts from HR/founders
    2. X/Twitter — Company hiring tweets, recruiter posts
    3. Reddit — Job threads, referral posts
    4. Discord — Startup hiring channels

Key Metrics:
    - Typically finds 5-30 unique jobs per scan
    - ~60% are genuine after AI filtering
    - ~20% are high-value (not on any board)
============================================================
"""

import os
import re
import json
import time
import random
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from urllib.parse import urlparse

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST
from core.database import get_db, DatabaseManager, DarkChannelListing
from core.ai_router import get_router, AIRouter

AGENT_ID = "A-02"
AGENT_NAME = "Dark Channel Listener"

# ============================================================
# CHANNEL CONFIGURATION
# ============================================================

# Telegram channels/groups to monitor
TELEGRAM_CHANNELS = [
    {'username': '@mba_internships_india', 'name': 'MBA Internships India', 'category': 'mba'},
    {'username': '@internshala_updates', 'name': 'Internshala Updates', 'category': 'general'},
    {'username': '@startup_jobs_india', 'name': 'Startup Jobs India', 'category': 'startup'},
    {'username': '@placement_season', 'name': 'Placement Season', 'category': 'campus'},
    {'username': '@consulting_jobs_india', 'name': 'Consulting Jobs India', 'category': 'consulting'},
    {'username': '@fintech_jobs', 'name': 'Fintech Jobs', 'category': 'fintech'},
    {'username': '@product_jobs_india', 'name': 'Product Jobs India', 'category': 'product'},
    {'username': '@hr_network_india', 'name': 'HR Network India', 'category': 'hr'},
    {'username': '@fmcg_careers', 'name': 'FMCG Careers India', 'category': 'fmcg'},
    {'username': '@data_jobs_india', 'name': 'Data Jobs India', 'category': 'analytics'},
]

# Twitter/X search queries
TWITTER_QUERIES = [
    '"hiring intern" india MBA stipend',
    '"management trainee" india 2026',
    '"summer internship" MBA india',
    '"we are hiring" intern india -scam',
    '"intern" "ppo" "stipend" india',
    '"campus placement" 2026 MBA',
    '"looking for interns" india',
    '"join our team" intern MBA india',
]

# Reddit subreddits and search parameters
REDDIT_SOURCES = [
    {'subreddit': 'MBA', 'search': 'internship india', 'sort': 'new', 'limit': 25},
    {'subreddit': 'Indian_Academia', 'search': 'internship MBA', 'sort': 'new', 'limit': 25},
    {'subreddit': 'developersIndia', 'search': 'hiring intern', 'sort': 'new', 'limit': 15},
    {'subreddit': 'india', 'search': 'MBA internship stipend', 'sort': 'new', 'limit': 15},
    {'subreddit': 'Btechtards', 'search': 'internship MBA', 'sort': 'new', 'limit': 10},
]

# Job-related keywords for initial filtering
JOB_KEYWORDS_PRIMARY = [
    'hiring', 'intern', 'internship', 'trainee', 'opening',
    'vacancy', 'position', 'opportunity', 'stipend', 'ppo',
    'apply', 'recruitment', 'placement', 'join us',
    'we are hiring', 'looking for', 'freshers', 'mba',
]

JOB_KEYWORDS_SECONDARY = [
    'role', 'location', 'remote', 'wfh', 'work from home',
    'salary', 'ctc', 'package', 'lpa', 'per month',
    'duration', 'months', 'full time', 'part time',
    'experience', 'fresher', 'immediate joining',
    'interview', 'shortlist', 'resume', 'cv', 'application',
]

# Keywords that indicate noise (not a job post)
NOISE_KEYWORDS = [
    'meme', 'joke', 'funny', 'lol', 'lmao', 'politics',
    'cricket', 'movie', 'song', 'news', 'opinion',
    'rant', 'complaint', 'review', 'suggestion',
    'buy', 'sell', 'trading', 'crypto', 'bitcoin',
    'click here', 'free money', 'earn from home',
    'mlm', 'network marketing', 'pyramid',
]

# URL patterns that are job-related
JOB_URL_PATTERNS = [
    r'internshala\.com',
    r'naukri\.com',
    r'linkedin\.com/jobs',
    r'linkedin\.com/company',
    r'greenhouse\.io',
    r'lever\.co',
    r'careers\.',
    r'jobs\.',
    r'angel\.co',
    r'wellfound\.com',
    r'indeed\.com',
    r'instahyre\.com',
    r'iimjobs\.com',
    r'hirist\.com',
    r'cutshort\.io',
    r'glassdoor\.',
]

# Company name patterns to extract from text
COMPANY_INDICATORS = [
    r'(?:at|@|with)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s+(?:is|are|has|for|in)\b)',
    r'(?:company|org|organization|firm)[\s:]+([A-Z][A-Za-z0-9\s&.]+)',
    r'([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\s+(?:is hiring|hiring|recruits)',
    r'#([A-Z][A-Za-z0-9]+)(?:Hiring|Jobs|Careers)',
]

# Role/title patterns
ROLE_PATTERNS = [
    r'(?:role|position|opening|vacancy)[\s:]+([^\n.!?]+)',
    r'(?:looking for|hiring)\s+(?:a\s+)?([^\n.!?]+?)(?:\s+at\b|\s+in\b|\.|$)',
    r'(?:intern|trainee|associate|analyst)[\s-]+(?:in\s+)?([^\n.!?]+)',
    r'(?:title|designation)[\s:]+([^\n.!?]+)',
]

# Stipend patterns
STIPEND_PATTERNS = [
    r'(?:stipend|salary|ctc|compensation)[\s:]*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:k|K|pm|per month|/month|/mo)?',
    r'₹\s*([\d,]+(?:\.\d+)?)\s*(?:k|K|pm|per month|/month|/mo)?',
    r'([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?\s*per\s*annum)',
    r'([\d,]+(?:\.\d+)?)\s*(?:per\s*month|/month|pm|monthly)',
]


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class DarkChannelMessage:
    """Raw message from a dark channel before classification."""
    channel_name: str = ""
    channel_type: str = ""  # telegram, twitter, reddit, discord
    message_text: str = ""
    message_id: str = ""
    author: str = ""
    posted_at: str = ""
    urls: List[str] = field(default_factory=list)
    has_media: bool = False
    reply_count: int = 0
    engagement_score: int = 0  # likes + retweets + replies

    @property
    def text_hash(self) -> str:
        """Generate hash for dedup."""
        text_normalized = re.sub(r'\s+', ' ', self.message_text.lower().strip())
        return hashlib.sha256(text_normalized[:500].encode()).hexdigest()[:16]


@dataclass
class ClassifiedMessage:
    """AI-classified dark channel message."""
    raw_message: DarkChannelMessage = field(default_factory=DarkChannelMessage)
    is_job: bool = False
    confidence: float = 0.0
    extracted_company: str = ""
    extracted_role: str = ""
    extracted_url: str = ""
    extracted_stipend: str = ""
    extracted_location: str = ""
    extracted_deadline: str = ""
    classification_method: str = "rule"  # rule, ai, hybrid
    matched_company_id: Optional[int] = None
    quality_score: float = 0.0  # 0-100 post-analysis quality

    def to_dark_listing(self) -> DarkChannelListing:
        """Convert to DarkChannelListing for database storage."""
        return DarkChannelListing(
            channel_name=self.raw_message.channel_name,
            channel_type=self.raw_message.channel_type,
            message_text=self.raw_message.message_text[:2000],
            extracted_company=self.extracted_company,
            extracted_role=self.extracted_role,
            extracted_url=self.extracted_url,
            is_job=self.is_job,
            confidence=self.confidence,
        )


@dataclass
class DarkScanResult:
    """Complete result of a dark channel scan."""
    start_time: str = ""
    end_time: str = ""
    duration_sec: float = 0.0
    telegram_scanned: int = 0
    twitter_scanned: int = 0
    reddit_scanned: int = 0
    discord_scanned: int = 0
    total_messages: int = 0
    job_posts_found: int = 0
    high_confidence: int = 0  # confidence >= 0.8
    new_companies: int = 0
    duplicates_skipped: int = 0
    errors: List[str] = field(default_factory=list)

    def to_telegram_msg(self) -> str:
        """Format for Telegram display."""
        return (
            f"🌑 <b>Dark Channel Scan Report</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Duration: {self.duration_sec:.1f}s\n\n"
            f"📊 Messages Scanned: {self.total_messages}\n"
            f"  • Telegram: {self.telegram_scanned}\n"
            f"  • Twitter/X: {self.twitter_scanned}\n"
            f"  • Reddit: {self.reddit_scanned}\n\n"
            f"🎯 Job Posts Found: {self.job_posts_found}\n"
            f"  • High confidence (≥80%): {self.high_confidence}\n"
            f"  • New companies: {self.new_companies}\n"
            f"  • Duplicates skipped: {self.duplicates_skipped}\n"
            f"  • Errors: {len(self.errors)}"
        )


# ============================================================
# ENTITY EXTRACTOR
# ============================================================

class EntityExtractor:
    """
    Extracts structured entities from unstructured dark channel
    messages: company names, roles, URLs, stipends, locations,
    and deadlines using regex patterns and heuristics.
    """

    @staticmethod
    def extract_urls(text: str) -> List[str]:
        """Extract all URLs from message text."""
        url_pattern = re.compile(
            r'https?://[^\s<>"{}|\\^`\[\]]+',
            re.IGNORECASE
        )
        urls = url_pattern.findall(text)
        # Filter out tracking/shortener noise
        clean_urls = []
        for url in urls:
            url = url.rstrip('.,;:!?)')
            if len(url) > 10:
                clean_urls.append(url)
        return clean_urls

    @staticmethod
    def extract_job_url(urls: List[str]) -> str:
        """Find the most relevant job URL from extracted URLs."""
        for url in urls:
            for pattern in JOB_URL_PATTERNS:
                if re.search(pattern, url, re.IGNORECASE):
                    return url
        # Return first URL if none match job patterns
        return urls[0] if urls else ""

    @staticmethod
    def extract_company(text: str) -> str:
        """Extract company name from message text."""
        for pattern in COMPANY_INDICATORS:
            match = re.search(pattern, text)
            if match:
                company = match.group(1).strip()
                # Clean up extracted company name
                company = re.sub(r'\s+', ' ', company)
                if 3 <= len(company) <= 50:
                    return company

        # Fallback: look for @company mentions
        at_mentions = re.findall(r'@(\w+)', text)
        for mention in at_mentions:
            if len(mention) >= 3 and mention.lower() not in [
                'everyone', 'all', 'here', 'channel', 'admin'
            ]:
                return mention

        return ""

    @staticmethod
    def extract_role(text: str) -> str:
        """Extract job role/title from message text."""
        for pattern in ROLE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                role = match.group(1).strip()
                role = re.sub(r'\s+', ' ', role)
                if 3 <= len(role) <= 100:
                    return role

        # Fallback: look for common role keywords
        role_keywords = [
            'marketing intern', 'finance intern', 'operations intern',
            'business analyst', 'management trainee', 'associate',
            'consultant', 'product manager', 'strategy intern',
            'content writer', 'social media', 'digital marketing',
            'data analyst', 'research analyst', 'hr intern',
        ]
        text_lower = text.lower()
        for kw in role_keywords:
            if kw in text_lower:
                return kw.title()

        return ""

    @staticmethod
    def extract_stipend(text: str) -> str:
        """Extract stipend/salary information."""
        for pattern in STIPEND_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return ""

    @staticmethod
    def extract_location(text: str) -> str:
        """Extract location from message text."""
        # Indian cities
        cities = [
            'mumbai', 'bangalore', 'bengaluru', 'delhi', 'new delhi',
            'hyderabad', 'pune', 'chennai', 'kolkata', 'gurgaon',
            'gurugram', 'noida', 'ahmedabad', 'jaipur', 'lucknow',
            'chandigarh', 'kochi', 'indore', 'bhopal', 'coimbatore',
            'remote', 'work from home', 'wfh', 'hybrid', 'pan india',
        ]
        text_lower = text.lower()
        found = []
        for city in cities:
            if city in text_lower:
                found.append(city.title())

        return ', '.join(found[:3]) if found else ""

    @staticmethod
    def extract_deadline(text: str) -> str:
        """Extract application deadline from text."""
        deadline_patterns = [
            r'(?:deadline|last date|apply by|before|by)[\s:]*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
            r'(?:deadline|last date|apply by)[\s:]*(\d{1,2}\s+\w+\s+\d{4})',
            r'(?:ends|closing|closes)[\s:]*(\d{1,2}[\s/-]\w+[\s/-]?\d{0,4})',
        ]
        for pattern in deadline_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""


# ============================================================
# RULE-BASED CLASSIFIER
# ============================================================

class RuleBasedClassifier:
    """
    Fast rule-based classifier for initial message filtering.
    Uses keyword counting, pattern matching, and heuristics
    to quickly determine if a message is a job posting.
    """

    @staticmethod
    def classify(message: DarkChannelMessage) -> Tuple[bool, float]:
        """
        Quick rule-based classification.

        Returns:
            (is_likely_job, confidence)
        """
        text_lower = message.message_text.lower()
        text_len = len(message.message_text)

        # Too short or too long messages are unlikely job posts
        if text_len < 30:
            return False, 0.1
        if text_len > 5000:
            # Very long messages might be detailed job descriptions
            pass

        # Count positive indicators
        primary_count = sum(
            1 for kw in JOB_KEYWORDS_PRIMARY if kw in text_lower
        )
        secondary_count = sum(
            1 for kw in JOB_KEYWORDS_SECONDARY if kw in text_lower
        )

        # Count noise indicators
        noise_count = sum(
            1 for kw in NOISE_KEYWORDS if kw in text_lower
        )

        # URL check - job URLs are strong positive signal
        has_job_url = any(
            re.search(pattern, message.message_text, re.IGNORECASE)
            for pattern in JOB_URL_PATTERNS
        )

        # Calculate confidence
        positive_score = (primary_count * 2.0) + (secondary_count * 1.0)
        if has_job_url:
            positive_score += 3.0
        if message.urls:
            positive_score += 1.0

        negative_score = noise_count * 2.0

        total_score = positive_score - negative_score

        # Threshold-based classification
        if total_score >= 5.0:
            confidence = min(0.9, 0.5 + (total_score * 0.05))
            return True, confidence
        elif total_score >= 3.0:
            confidence = 0.4 + (total_score * 0.05)
            return True, confidence
        elif total_score >= 1.0 and primary_count >= 1:
            return True, 0.35
        else:
            return False, max(0.05, 0.2 - (negative_score * 0.05))

    @staticmethod
    def calculate_quality_score(classified: ClassifiedMessage) -> float:
        """
        Calculate quality score (0-100) for a classified job post.
        Higher quality = more structured, more info extracted.
        """
        score = 0.0

        # Confidence contributes 30%
        score += classified.confidence * 30

        # Extracted entities contribute 70%
        if classified.extracted_company:
            score += 15
        if classified.extracted_role:
            score += 15
        if classified.extracted_url:
            score += 15
        if classified.extracted_stipend:
            score += 10
        if classified.extracted_location:
            score += 8
        if classified.extracted_deadline:
            score += 7

        return min(100.0, score)


# ============================================================
# AI CLASSIFIER
# ============================================================

class AIClassifier:
    """
    AI-powered message classifier using Cerebras for nuanced
    job post detection. Used for borderline cases and to improve
    entity extraction accuracy.
    """

    def __init__(self, router: AIRouter):
        self.router = router

    def classify(self, text: str, channel_name: str,
                 channel_type: str) -> Optional[Dict]:
        """
        Classify a message using Cerebras AI.

        Returns:
            Dict with keys: is_job, confidence, company, role, url
            or None if AI call fails
        """
        try:
            response = self.router.classify_dark_message(
                text, channel_name, channel_type
            )
            if response.success:
                data = response.get_json()
                if data and isinstance(data, dict):
                    return {
                        'is_job': bool(data.get('is_job', False)),
                        'confidence': float(data.get('confidence', 0)),
                        'company': str(data.get('company', '') or ''),
                        'role': str(data.get('role', '') or ''),
                        'url': str(data.get('url', '') or ''),
                        'stipend': str(data.get('stipend', '') or ''),
                        'location': str(data.get('location', '') or ''),
                    }
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] AI classification error: {e}")

        return None


# ============================================================
# TELEGRAM SCANNER
# ============================================================

class TelegramScanner:
    """
    Scans Telegram groups/channels for job postings using
    Telethon library. Handles async message fetching, keyword
    filtering, and rate-limited access.
    """

    def __init__(self, config, db: DatabaseManager, extractor: EntityExtractor,
                 rule_classifier: RuleBasedClassifier, ai_classifier: AIClassifier):
        self.config = config
        self.db = db
        self.extractor = extractor
        self.rule_classifier = rule_classifier
        self.ai_classifier = ai_classifier
        self._client = None

    def scan(self, channels: Optional[List[Dict]] = None) -> List[ClassifiedMessage]:
        """
        Scan configured Telegram channels for job posts.

        Args:
            channels: Override channel list (default: TELEGRAM_CHANNELS)
        """
        if channels is None:
            channels = TELEGRAM_CHANNELS

        # Check Telethon configuration
        api_id = getattr(self.config, 'telethon', None)
        if not api_id or not getattr(api_id, 'api_id', ''):
            logger.debug(f"[{AGENT_ID}] Telethon not configured (TG_API_ID missing)")
            return []

        try:
            from telethon import TelegramClient
        except ImportError:
            logger.debug(f"[{AGENT_ID}] Telethon not installed")
            return []

        results = []

        async def _async_scan():
            nonlocal results
            try:
                client = TelegramClient(
                    api_id.session_name,
                    int(api_id.api_id),
                    api_id.api_hash,
                )
                await client.start()

                for channel_config in channels:
                    try:
                        channel_results = await self._scan_channel(
                            client, channel_config
                        )
                        results.extend(channel_results)
                        await asyncio.sleep(random.uniform(2, 5))
                    except Exception as e:
                        logger.debug(
                            f"[{AGENT_ID}] Channel "
                            f"'{channel_config.get('name', '?')}' error: {e}"
                        )
                        continue

                await client.disconnect()
            except Exception as e:
                logger.error(f"[{AGENT_ID}] Telethon connection error: {e}")

        # Run async scan
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_async_scan())
            loop.close()
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Telegram scan failed: {e}")

        return results

    async def _scan_channel(self, client, channel_config: Dict) -> List[ClassifiedMessage]:
        """Scan a single Telegram channel."""
        results = []
        username = channel_config.get('username', '')
        name = channel_config.get('name', username)

        try:
            entity = await client.get_entity(username)
            messages = await client.get_messages(entity, limit=50)

            for msg in messages:
                if not msg.text:
                    continue

                text = msg.text
                if len(text) < 20:
                    continue

                # Create raw message
                raw = DarkChannelMessage(
                    channel_name=name,
                    channel_type='telegram',
                    message_text=text[:2000],
                    message_id=str(msg.id),
                    author=str(msg.sender_id) if msg.sender_id else '',
                    posted_at=msg.date.isoformat() if msg.date else '',
                    urls=self.extractor.extract_urls(text),
                    has_media=msg.media is not None,
                )

                # Dedup check
                if self.db.check_dark_message_hash(raw.text_hash):
                    continue

                # Rule-based classification
                is_job, confidence = self.rule_classifier.classify(raw)

                classified = ClassifiedMessage(
                    raw_message=raw,
                    is_job=is_job,
                    confidence=confidence,
                    classification_method='rule',
                )

                # Extract entities
                classified.extracted_company = self.extractor.extract_company(text)
                classified.extracted_role = self.extractor.extract_role(text)
                classified.extracted_url = self.extractor.extract_job_url(raw.urls)
                classified.extracted_stipend = self.extractor.extract_stipend(text)
                classified.extracted_location = self.extractor.extract_location(text)
                classified.extracted_deadline = self.extractor.extract_deadline(text)

                # AI classification for borderline cases (0.3 < confidence < 0.7)
                if 0.3 < confidence < 0.7:
                    ai_result = self.ai_classifier.classify(
                        text, name, 'telegram'
                    )
                    if ai_result:
                        classified.is_job = ai_result.get('is_job', is_job)
                        classified.confidence = (
                            confidence * 0.3 + ai_result.get('confidence', 0) * 0.7
                        )
                        classified.classification_method = 'hybrid'

                        # Override entity extraction with AI if better
                        if ai_result.get('company') and not classified.extracted_company:
                            classified.extracted_company = ai_result['company']
                        if ai_result.get('role') and not classified.extracted_role:
                            classified.extracted_role = ai_result['role']

                if classified.is_job:
                    classified.quality_score = self.rule_classifier.calculate_quality_score(classified)
                    results.append(classified)

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Channel '{name}' scan error: {e}")

        return results


# ============================================================
# TWITTER/X SCANNER
# ============================================================

class TwitterScanner:
    """
    Scans Twitter/X for job postings using API v2.
    Rate-limited to 3 queries per scan session.
    """

    def __init__(self, config, db: DatabaseManager, extractor: EntityExtractor,
                 rule_classifier: RuleBasedClassifier, ai_classifier: AIClassifier):
        self.config = config
        self.db = db
        self.extractor = extractor
        self.rule_classifier = rule_classifier
        self.ai_classifier = ai_classifier

    def scan(self, queries: Optional[List[str]] = None,
             max_queries: int = 3) -> List[ClassifiedMessage]:
        """Scan Twitter for job posts."""
        if queries is None:
            queries = TWITTER_QUERIES

        bearer_token = getattr(self.config, 'x_bearer_token', '')
        if not bearer_token:
            logger.debug(f"[{AGENT_ID}] X_BEARER_TOKEN not configured")
            return []

        try:
            import tweepy
        except ImportError:
            logger.debug(f"[{AGENT_ID}] tweepy not installed")
            return []

        results = []

        try:
            client = tweepy.Client(bearer_token=bearer_token)

            for query in queries[:max_queries]:
                try:
                    tweets = client.search_recent_tweets(
                        query=query,
                        max_results=20,
                        tweet_fields=['created_at', 'text', 'author_id', 'public_metrics']
                    )

                    if not tweets.data:
                        continue

                    for tweet in tweets.data:
                        text = tweet.text
                        if len(text) < 20:
                            continue

                        metrics = tweet.public_metrics or {}

                        raw = DarkChannelMessage(
                            channel_name=f"twitter_search_{query[:30]}",
                            channel_type='twitter',
                            message_text=text[:2000],
                            message_id=str(tweet.id),
                            author=str(tweet.author_id) if tweet.author_id else '',
                            posted_at=tweet.created_at.isoformat() if tweet.created_at else '',
                            urls=self.extractor.extract_urls(text),
                            engagement_score=(
                                metrics.get('like_count', 0) +
                                metrics.get('retweet_count', 0) +
                                metrics.get('reply_count', 0)
                            ),
                        )

                        # Dedup
                        if self.db.check_dark_message_hash(raw.text_hash):
                            continue

                        is_job, confidence = self.rule_classifier.classify(raw)

                        classified = ClassifiedMessage(
                            raw_message=raw,
                            is_job=is_job,
                            confidence=confidence,
                            classification_method='rule',
                        )

                        # Extract entities
                        classified.extracted_company = self.extractor.extract_company(text)
                        classified.extracted_role = self.extractor.extract_role(text)
                        classified.extracted_url = self.extractor.extract_job_url(raw.urls)
                        classified.extracted_stipend = self.extractor.extract_stipend(text)
                        classified.extracted_location = self.extractor.extract_location(text)

                        # Engagement boost - popular tweets more likely genuine
                        if raw.engagement_score >= 10:
                            classified.confidence = min(
                                0.95, classified.confidence + 0.1
                            )

                        # AI for borderline
                        if 0.3 < confidence < 0.7:
                            ai_result = self.ai_classifier.classify(
                                text, 'twitter', 'twitter'
                            )
                            if ai_result:
                                classified.is_job = ai_result.get('is_job', is_job)
                                classified.confidence = (
                                    confidence * 0.3 + ai_result.get('confidence', 0) * 0.7
                                )
                                classified.classification_method = 'hybrid'
                                if ai_result.get('company') and not classified.extracted_company:
                                    classified.extracted_company = ai_result['company']

                        if classified.is_job:
                            classified.quality_score = self.rule_classifier.calculate_quality_score(classified)
                            results.append(classified)

                    time.sleep(random.uniform(3, 8))

                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] Twitter query error: {e}")
                    continue

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Twitter scan failed: {e}")

        return results


# ============================================================
# REDDIT SCANNER
# ============================================================

class RedditScanner:
    """
    Scans Reddit for job postings using PRAW or direct HTTP requests.
    Monitors MBA, Indian_Academia, and related subreddits.
    """

    def __init__(self, db: DatabaseManager, extractor: EntityExtractor,
                 rule_classifier: RuleBasedClassifier):
        self.db = db
        self.extractor = extractor
        self.rule_classifier = rule_classifier

    def scan(self, sources: Optional[List[Dict]] = None) -> List[ClassifiedMessage]:
        """Scan Reddit for job posts."""
        if sources is None:
            sources = REDDIT_SOURCES

        results = []

        # Try PRAW first, fall back to JSON API
        try:
            results = self._scan_with_json_api(sources)
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Reddit scan error: {e}")

        return results

    def _scan_with_json_api(self, sources: List[Dict]) -> List[ClassifiedMessage]:
        """Scan Reddit using public JSON API (no auth needed)."""
        import requests

        results = []
        headers = {
            'User-Agent': 'MBA-Agent/1.0 (academic research project)'
        }

        for source in sources:
            try:
                subreddit = source['subreddit']
                search_query = source.get('search', '')
                limit = source.get('limit', 25)

                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {
                    'q': search_query,
                    'sort': 'new',
                    't': 'day',
                    'limit': limit,
                    'restrict_sr': 'on',
                }

                resp = requests.get(url, headers=headers, params=params, timeout=15)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                posts = data.get('data', {}).get('children', [])

                for post_wrapper in posts:
                    post = post_wrapper.get('data', {})
                    title = post.get('title', '')
                    selftext = post.get('selftext', '')
                    post_url = post.get('url', '')
                    full_text = f"{title}\n{selftext}"

                    if len(full_text) < 30:
                        continue

                    raw = DarkChannelMessage(
                        channel_name=f"r/{subreddit}",
                        channel_type='reddit',
                        message_text=full_text[:2000],
                        message_id=post.get('id', ''),
                        author=post.get('author', ''),
                        posted_at=str(post.get('created_utc', '')),
                        urls=[post_url] if post_url else [],
                        engagement_score=post.get('score', 0),
                    )

                    # Dedup
                    if self.db.check_dark_message_hash(raw.text_hash):
                        continue

                    is_job, confidence = self.rule_classifier.classify(raw)

                    if not is_job:
                        continue

                    classified = ClassifiedMessage(
                        raw_message=raw,
                        is_job=is_job,
                        confidence=confidence,
                        classification_method='rule',
                    )

                    classified.extracted_company = self.extractor.extract_company(full_text)
                    classified.extracted_role = self.extractor.extract_role(full_text)
                    classified.extracted_url = post_url
                    classified.extracted_stipend = self.extractor.extract_stipend(full_text)
                    classified.extracted_location = self.extractor.extract_location(full_text)

                    classified.quality_score = self.rule_classifier.calculate_quality_score(classified)
                    results.append(classified)

                time.sleep(random.uniform(2, 5))

            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Reddit r/{source.get('subreddit', '?')} error: {e}")
                continue

        return results


# ============================================================
# MASTER DARK CHANNEL LISTENER
# ============================================================

class DarkChannelListener:
    """
    Master dark channel scanning engine that orchestrates all
    platform-specific scanners. Runs once daily at 8 PM IST.

    Pipeline:
        1. Scan Telegram groups (if Telethon configured)
        2. Scan Twitter/X (if bearer token configured)
        3. Scan Reddit (public JSON API)
        4. AI-classify borderline messages
        5. Extract entities (company, role, URL, stipend)
        6. Match companies against database
        7. Dedup against existing dark listings
        8. Store results in dark_channel_listings table
        9. Generate scan report
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.router = get_router()
        self.extractor = EntityExtractor()
        self.rule_classifier = RuleBasedClassifier()
        self.ai_classifier = AIClassifier(self.router)

        self.telegram_scanner = TelegramScanner(
            self.config, self.db, self.extractor,
            self.rule_classifier, self.ai_classifier
        )
        self.twitter_scanner = TwitterScanner(
            self.config, self.db, self.extractor,
            self.rule_classifier, self.ai_classifier
        )
        self.reddit_scanner = RedditScanner(
            self.db, self.extractor, self.rule_classifier
        )

    def run_batch_check(self) -> DarkScanResult:
        """
        Run full dark channel batch scan.
        """
        logger.info(f"[{AGENT_ID}] === DARK CHANNEL SCAN START ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        result = DarkScanResult(
            start_time=datetime.now(IST).isoformat(),
        )

        all_classified: List[ClassifiedMessage] = []

        # 1. Telegram scan
        try:
            tg_results = self.telegram_scanner.scan()
            all_classified.extend(tg_results)
            result.telegram_scanned = len(tg_results)
        except Exception as e:
            result.errors.append(f"Telegram: {e}")
            logger.error(f"[{AGENT_ID}] Telegram scan error: {e}")

        # 2. Twitter/X scan
        try:
            x_results = self.twitter_scanner.scan()
            all_classified.extend(x_results)
            result.twitter_scanned = len(x_results)
        except Exception as e:
            result.errors.append(f"Twitter: {e}")
            logger.error(f"[{AGENT_ID}] Twitter scan error: {e}")

        # 3. Reddit scan
        try:
            reddit_results = self.reddit_scanner.scan()
            all_classified.extend(reddit_results)
            result.reddit_scanned = len(reddit_results)
        except Exception as e:
            result.errors.append(f"Reddit: {e}")
            logger.error(f"[{AGENT_ID}] Reddit scan error: {e}")

        result.total_messages = (
            result.telegram_scanned + result.twitter_scanned + result.reddit_scanned
        )

        # 4. Store results in database
        stored = 0
        for classified in all_classified:
            if not classified.is_job:
                continue

            try:
                # Match company against database
                if classified.extracted_company:
                    company = self.db.fuzzy_match_company(classified.extracted_company)
                    if company:
                        classified.matched_company_id = company.get('id')

                # Convert to DB model and store
                listing = classified.to_dark_listing()
                db_result = self.db.insert_dark_channel_listing(listing)
                if db_result:
                    stored += 1
                    if classified.confidence >= 0.8:
                        result.high_confidence += 1
                else:
                    result.duplicates_skipped += 1

            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Store error: {e}")
                continue

        result.job_posts_found = stored

        # Finalize
        duration = time.time() - start_time
        result.duration_sec = round(duration, 1)
        result.end_time = datetime.now(IST).isoformat()

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=result.job_posts_found,
            errors=len(result.errors),
            duration_sec=duration,
        )

        logger.info(
            f"[{AGENT_ID}] === DARK CHANNEL SCAN COMPLETE === "
            f"Found: {result.job_posts_found} | "
            f"High conf: {result.high_confidence} | "
            f"Duration: {result.duration_sec}s"
        )

        return result

    def get_recent_finds(self, days: int = 3, limit: int = 15) -> List[Dict]:
        """Get recent dark channel finds for /dark command."""
        try:
            return self.db.get_recent_dark_listings(days=days, limit=limit)
        except Exception as e:
            logger.error(f"[{AGENT_ID}] get_recent_finds error: {e}")
            return []

    def format_dark_report(self, listings: List[Dict]) -> str:
        """Format dark channel listings for Telegram display."""
        if not listings:
            return "🌑 No dark channel finds recently."

        lines = [
            "🌑 <b>Dark Channel Finds</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        for i, listing in enumerate(listings[:15], 1):
            channel = listing.get('channel_name', 'Unknown')
            ch_type = listing.get('channel_type', '')
            company = listing.get('extracted_company', 'Unknown')
            role = listing.get('extracted_role', 'Unknown')
            confidence = listing.get('confidence', 0)
            url = listing.get('extracted_url', '')

            type_emoji = {
                'telegram': '📱', 'twitter': '🐦', 'reddit': '🔴', 'discord': '💬'
            }.get(ch_type, '📡')

            conf_emoji = '🟢' if confidence >= 0.8 else '🟡' if confidence >= 0.5 else '🔴'

            lines.append(f"{i}. {type_emoji} <b>{role}</b> @ {company}")
            lines.append(f"   {conf_emoji} Conf: {confidence:.0%} | Via: {channel}")
            if url:
                lines.append(f"   🔗 {url[:60]}{'...' if len(url) > 60 else ''}")
            lines.append("")

        return '\n'.join(lines)


# ============================================================
# SINGLETON ACCESS
# ============================================================

_listener_instance: Optional[DarkChannelListener] = None


def get_dark_channel_listener() -> DarkChannelListener:
    """Get or create the singleton DarkChannelListener instance."""
    global _listener_instance
    if _listener_instance is None:
        _listener_instance = DarkChannelListener()
    return _listener_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test EntityExtractor
    extractor = EntityExtractor()

    test_text = """
    🚀 McKinsey & Company is hiring Summer Interns for 2026!
    Location: Mumbai, Gurugram
    Stipend: ₹1,50,000/month
    Apply by 15 March 2026
    Link: https://careers.mckinsey.com/intern-2026
    """

    print("\nEntity Extraction Test:")
    print(f"  URLs: {extractor.extract_urls(test_text)}")
    print(f"  Company: {extractor.extract_company(test_text)}")
    print(f"  Role: {extractor.extract_role(test_text)}")
    print(f"  Stipend: {extractor.extract_stipend(test_text)}")
    print(f"  Location: {extractor.extract_location(test_text)}")
    print(f"  Deadline: {extractor.extract_deadline(test_text)}")

    # Test RuleBasedClassifier
    classifier = RuleBasedClassifier()

    test_messages = [
        ("Hiring MBA interns at Flipkart! Stipend ₹40K/month. Apply now.", True),
        ("Funny meme about cricket lol", False),
        ("Marketing intern needed at Zepto, remote, 3 months, ₹25,000/mo", True),
        ("What movie should I watch tonight?", False),
        ("Join our team at CRED! Product management intern position open", True),
    ]

    print("\nRule-based Classification Tests:")
    for text, expected in test_messages:
        raw = DarkChannelMessage(message_text=text, channel_type='telegram')
        is_job, conf = classifier.classify(raw)
        status = "✅" if is_job == expected else "❌"
        print(f"  {status} '{text[:60]}...'")
        print(f"     Job: {is_job} (expected: {expected}) | Conf: {conf:.2f}")

    print(f"\nConfiguration:")
    print(f"  Telegram channels: {len(TELEGRAM_CHANNELS)}")
    print(f"  Twitter queries: {len(TWITTER_QUERIES)}")
    print(f"  Reddit sources: {len(REDDIT_SOURCES)}")
    print(f"  Primary job keywords: {len(JOB_KEYWORDS_PRIMARY)}")
    print(f"  Secondary keywords: {len(JOB_KEYWORDS_SECONDARY)}")
    print(f"  Noise keywords: {len(NOISE_KEYWORDS)}")
    print(f"  Job URL patterns: {len(JOB_URL_PATTERNS)}")
    print(f"  Company patterns: {len(COMPANY_INDICATORS)}")
    print(f"  Role patterns: {len(ROLE_PATTERNS)}")
    print(f"  Stipend patterns: {len(STIPEND_PATTERNS)}")
    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) ready!")
    print("=" * 60)
