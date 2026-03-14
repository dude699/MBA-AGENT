"""
============================================================
AGENT A-01: INTENT SIGNAL SCANNER — INDUSTRIAL GRADE
============================================================
Detects companies actively hiring BEFORE they post on job
boards by monitoring news, RSS feeds, economic indicators,
HR recruiter posts, funding announcements, and expansion
signals via DuckDuckGo dorks and RSS aggregation.

Schedule: 09:00 AM + 04:00 PM IST
AI Model: Cerebras (intent_classify, signal_score)

Architecture:
┌──────────────────────────────────────────────────┐
│            INTENT SIGNAL SCANNER (A-01)          │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌───────────────────────────────────────────┐   │
│  │ 1. RSS Feed Aggregator                    │   │
│  │    - Inc42, YourStory, VCCircle, ET       │   │
│  │    - LiveMint, MoneyControl, BS           │   │
│  │    - TechCrunch India, Entrackr           │   │
│  │    - Parse 20 entries/feed, keyword match  │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 2. Google News RSS Monitor                │   │
│  │    - Company-specific queries             │   │
│  │    - "[Company] hiring intern 2026"       │   │
│  │    - "[Company] MBA internship"           │   │
│  │    - "[Company] campus placement"         │   │
│  │    - Tier 1+2 companies prioritized       │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 3. DDG HR/Recruiter Post Scanner          │   │
│  │    - LinkedIn recruiter post dorks        │   │
│  │    - Twitter hiring announcements         │   │
│  │    - Rate limit: max 5 dorks/hour         │   │
│  │    - Human-like delays 10-20s             │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 4. Funding/Expansion Signal Detector      │   │
│  │    - Series A/B/C/D funding news          │   │
│  │    - Office expansion announcements       │   │
│  │    - Revenue growth signals               │   │
│  │    - Auto-detect → hiring likely          │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 5. AI Signal Scorer (Cerebras)            │   │
│  │    - Classify: hiring/funding/expansion   │   │
│  │    - Score: 0-100 directness/relevance    │   │
│  │    - Multi-factor: recency, credibility   │   │
│  └─────────────────┬─────────────────────────┘   │
│                    ↓                             │
│  ┌───────────────────────────────────────────┐   │
│  │ 6. Signal Persistence & Decay Engine      │   │
│  │    - Store in intent_signals table        │   │
│  │    - Signal decay: -10 pts/day            │   │
│  │    - Reinforcement: duplicate = refresh   │   │
│  │    - Urgent alerts: Tier 1+2, score ≥ 70  │   │
│  │    - Auto-expire after 7 days             │   │
│  └───────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘

Signal Types:
    - news        → Hiring/recruiting mentions in press
    - hr_post     → HR/TA professional posts found via DDG
    - funding     → New fundraise → likely hiring
    - expansion   → New office/market → likely hiring
    - earnings    → Strong results → likely hiring
    - campus      → Campus drive / placement announcements
    - layoff      → NEGATIVE signal, reduce score

Scoring Formula:
    signal_score = base_score × directness_mult × recency_mult
                   × credibility_mult × tier_boost

    base_score:       50 (funding), 60 (news), 65 (hr_post),
                      70 (campus), 80 (direct hiring announce)
    directness_mult:  1.0 (mentions "hiring") to 0.5 (indirect)
    recency_mult:     1.0 (today) to 0.3 (>7 days)
    credibility_mult: 1.0 (ET, Mint) to 0.6 (unknown blog)
    tier_boost:       1.2 (Tier 1), 1.1 (Tier 2), 1.0 (others)

============================================================
"""

import os
import re
import json
import time
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from urllib.parse import quote_plus, urlparse

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None
    FEEDPARSER_AVAILABLE = False

from core.config import (
    get_config, IST, CompanyTier, ECONOMIC_SIGNAL_SOURCES,
    GOOGLE_NEWS_RSS_TEMPLATE, DDG_DORK_TEMPLATES,
)
from core.database import get_db, DatabaseManager, IntentSignal
from core.ai_router import get_router, AIRouter

AGENT_ID = "A-01"
AGENT_NAME = "Intent Signal Scanner"

# ============================================================
# SIGNAL CONFIGURATION CONSTANTS
# ============================================================

# Primary hiring intent keywords (high directness)
HIRING_KEYWORDS_DIRECT = [
    'hiring', 'hiring spree', 'hiring drive', 'recruitment drive',
    'we are hiring', 'join our team', 'join us', 'open position',
    'looking for', 'job opening', 'vacancy', 'vacancies',
    'walk-in interview', 'off-campus drive', 'campus placement',
    'campus recruitment', 'campus drive', 'placement season',
    'internship program', 'summer internship', 'winter internship',
    'mba hiring', 'mba internship', 'management trainee',
    'graduate trainee', 'leadership program', 'young leaders',
    'associate program', 'talent acquisition drive',
    'new positions', 'career opportunities', 'apply now',
    'applications open', 'registration open', 'last date to apply',
]

# Indirect hiring signals (moderate directness)
HIRING_KEYWORDS_INDIRECT = [
    'expanding team', 'growing team', 'scaling', 'headcount',
    'onboarding', 'new hires', 'team expansion', 'building a team',
    'talent pool', 'talent pipeline', 'workforce expansion',
    'new office', 'second office', 'new branch', 'expansion plans',
    'doubling workforce', 'rapid growth', 'hypergrowth',
    'aggressive hiring', 'mass recruitment',
]

# Funding signals (strong indirect → hiring likely)
FUNDING_KEYWORDS = [
    'raised', 'funding', 'fundraise', 'series a', 'series b',
    'series c', 'series d', 'series e', 'seed round', 'pre-series',
    'bridge round', 'growth round', 'valuation', 'unicorn',
    'ipo', 'ipo-bound', 'pre-ipo', 'million', 'billion', 'crore',
    'investment', 'investors', 'backed by', 'led by',
    'tiger global', 'sequoia', 'accel', 'peak xv', 'lightspeed',
    'softbank', 'prosus', 'general atlantic', 'warburg',
]

# Expansion signals
EXPANSION_KEYWORDS = [
    'new market', 'entering india', 'india launch', 'expansion',
    'new vertical', 'new product', 'product launch', 'revenue growth',
    'quarter results', 'strong quarter', 'beat estimates',
    'record revenue', 'profitability', 'turned profitable',
    'doubled revenue', 'market share', 'acquisition', 'acquired',
    'merger', 'partnership', 'strategic alliance', 'joint venture',
]

# Negative keywords (reduce/negate signal)
NEGATIVE_KEYWORDS = [
    'layoff', 'layoffs', 'laid off', 'downsizing', 'restructuring',
    'reduction in force', 'rif', 'fired', 'firing', 'letting go',
    'shutdown', 'shutting down', 'closed', 'closing', 'bankrupt',
    'insolvency', 'debt', 'default', 'loss-making', 'cost cutting',
    'hiring freeze', 'recruitment freeze', 'attrition', 'exodus',
    'mass resignation', 'employee dissatisfaction', 'pay cuts',
    'salary reduction', 'furlough', 'suspended operations',
]

# Signal base scores by type
SIGNAL_BASE_SCORES = {
    'direct_hiring': 80.0,
    'campus_drive': 75.0,
    'hr_post': 65.0,
    'news_hiring': 60.0,
    'funding': 55.0,
    'expansion': 50.0,
    'earnings_positive': 45.0,
    'indirect_signal': 40.0,
}

# Source credibility multipliers
SOURCE_CREDIBILITY = {
    'economic_times': 1.0,
    'livemint': 1.0,
    'moneycontrol': 0.95,
    'business_standard': 0.95,
    'inc42': 0.9,
    'yourstory': 0.85,
    'entrackr': 0.85,
    'vccircle': 0.9,
    'techcrunch': 0.95,
    'google_news': 0.8,
    'ddg_linkedin': 0.75,
    'unknown': 0.6,
}

# Tier boost multipliers
TIER_BOOST = {
    1: 1.20,   # Elite companies get 20% signal boost
    2: 1.10,   # Strong MNCs get 10% boost
    3: 1.00,   # Unicorns - neutral
    4: 0.95,   # Startups - slight reduction
    5: 0.90,   # Niche - lower priority
}

# Max DDG dorks per scan session
MAX_DDG_DORKS_PER_SESSION = 5
DDG_COOLDOWN_SECONDS = (10, 20)  # Random uniform delay

# RSS extended sources beyond config
ADDITIONAL_RSS_FEEDS = {
    'vccircle': {
        'url': 'https://www.vccircle.com/feed/',
        'credibility': 0.9,
        'focus': 'funding',
    },
    'entrackr': {
        'url': 'https://entrackr.com/feed/',
        'credibility': 0.85,
        'focus': 'startup',
    },
    'techcrunch_india': {
        'url': 'https://techcrunch.com/tag/india/feed/',
        'credibility': 0.95,
        'focus': 'tech',
    },
    'business_standard': {
        'url': 'https://www.business-standard.com/rss/economy-policy-10201.rss',
        'credibility': 0.95,
        'focus': 'economy',
    },
}

# Google News query templates for company-specific monitoring
GNEWS_QUERY_TEMPLATES = [
    '{company} hiring intern 2026',
    '{company} MBA internship india',
    '{company} campus placement 2026',
    '{company} management trainee program',
    '{company} recruitment drive india',
    '{company} summer intern program',
]

# DDG dork templates for HR/recruiter discovery
HR_DDG_TEMPLATES = [
    'site:linkedin.com/in "{company}" "talent acquisition" india',
    'site:linkedin.com/in "{company}" "recruiter" "hiring" india',
    'site:linkedin.com/posts "{company}" "hiring" "intern"',
    '"{company}" "we are hiring" intern OR trainee site:twitter.com',
    '"{company}" hiring intern 2026 site:naukri.com OR site:internshala.com',
]


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class SignalAnalysis:
    """Result of analyzing a single text for hiring signals."""
    has_direct_hiring: bool = False
    has_indirect_hiring: bool = False
    has_funding: bool = False
    has_expansion: bool = False
    has_negative: bool = False
    direct_keywords_found: List[str] = field(default_factory=list)
    indirect_keywords_found: List[str] = field(default_factory=list)
    funding_keywords_found: List[str] = field(default_factory=list)
    expansion_keywords_found: List[str] = field(default_factory=list)
    negative_keywords_found: List[str] = field(default_factory=list)
    signal_type: str = "unknown"
    base_score: float = 0.0

    @property
    def is_positive(self) -> bool:
        return (self.has_direct_hiring or self.has_indirect_hiring or
                self.has_funding or self.has_expansion) and not self.has_negative

    @property
    def keyword_count(self) -> int:
        return (len(self.direct_keywords_found) + len(self.indirect_keywords_found) +
                len(self.funding_keywords_found) + len(self.expansion_keywords_found))


@dataclass
class ScanResult:
    """Complete result of an intent scan session."""
    scan_type: str = "full"  # full, morning, afternoon
    start_time: str = ""
    end_time: str = ""
    duration_sec: float = 0.0
    signals_found: int = 0
    urgent_alerts: int = 0
    sources_scanned: int = 0
    rss_signals: int = 0
    news_signals: int = 0
    hr_signals: int = 0
    funding_signals: int = 0
    signals_reinforced: int = 0
    signals_decayed: int = 0
    companies_scanned: int = 0
    errors: List[str] = field(default_factory=list)
    urgent_companies: List[str] = field(default_factory=list)

    def to_telegram_msg(self) -> str:
        """Format scan result for Telegram display."""
        urgency = ""
        if self.urgent_companies:
            urgency = "\n\n🚨 <b>URGENT ALERTS:</b>\n"
            for c in self.urgent_companies[:5]:
                urgency += f"  • {c}\n"

        return (
            f"📡 <b>Intent Scan Report</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Type: {self.scan_type.upper()}\n"
            f"Duration: {self.duration_sec:.1f}s\n\n"
            f"📊 Signals Found: {self.signals_found}\n"
            f"  • RSS feeds: {self.rss_signals}\n"
            f"  • Company news: {self.news_signals}\n"
            f"  • HR/recruiter: {self.hr_signals}\n"
            f"  • Funding: {self.funding_signals}\n\n"
            f"🔄 Reinforced: {self.signals_reinforced}\n"
            f"📉 Decayed: {self.signals_decayed}\n"
            f"🚨 Urgent: {self.urgent_alerts}\n"
            f"🏢 Companies: {self.companies_scanned}\n"
            f"📡 Sources: {self.sources_scanned}"
            f"{urgency}"
        )


# ============================================================
# SIGNAL ANALYZER
# ============================================================

class SignalAnalyzer:
    """
    Analyzes text for hiring intent signals using keyword matching
    and classification heuristics. Handles multi-signal detection,
    negative keyword cancellation, and signal type assignment.
    """

    @staticmethod
    def analyze_text(text: str) -> SignalAnalysis:
        """
        Analyze a text for all types of hiring signals.

        Args:
            text: The text to analyze (title + summary + body)

        Returns:
            SignalAnalysis with all detected signals
        """
        result = SignalAnalysis()
        text_lower = text.lower()

        # Check direct hiring keywords
        for kw in HIRING_KEYWORDS_DIRECT:
            if kw in text_lower:
                result.has_direct_hiring = True
                result.direct_keywords_found.append(kw)

        # Check indirect hiring signals
        for kw in HIRING_KEYWORDS_INDIRECT:
            if kw in text_lower:
                result.has_indirect_hiring = True
                result.indirect_keywords_found.append(kw)

        # Check funding signals
        for kw in FUNDING_KEYWORDS:
            if kw in text_lower:
                result.has_funding = True
                result.funding_keywords_found.append(kw)

        # Check expansion signals
        for kw in EXPANSION_KEYWORDS:
            if kw in text_lower:
                result.has_expansion = True
                result.expansion_keywords_found.append(kw)

        # Check negative (layoff) signals
        for kw in NEGATIVE_KEYWORDS:
            if kw in text_lower:
                result.has_negative = True
                result.negative_keywords_found.append(kw)

        # Determine signal type and base score
        if result.has_negative:
            result.signal_type = 'layoff'
            result.base_score = -20.0
        elif result.has_direct_hiring:
            # Check for campus-specific
            campus_kws = ['campus', 'placement', 'walk-in']
            if any(ck in text_lower for ck in campus_kws):
                result.signal_type = 'campus'
                result.base_score = SIGNAL_BASE_SCORES['campus_drive']
            else:
                result.signal_type = 'news'
                result.base_score = SIGNAL_BASE_SCORES['direct_hiring']
        elif result.has_funding:
            result.signal_type = 'funding'
            result.base_score = SIGNAL_BASE_SCORES['funding']
        elif result.has_expansion:
            result.signal_type = 'expansion'
            result.base_score = SIGNAL_BASE_SCORES['expansion']
        elif result.has_indirect_hiring:
            result.signal_type = 'news'
            result.base_score = SIGNAL_BASE_SCORES['indirect_signal']

        return result

    @staticmethod
    def calculate_recency_multiplier(published_date: Optional[str] = None) -> float:
        """Calculate recency multiplier based on publication date."""
        if not published_date:
            return 0.8  # Unknown date gets moderate penalty

        try:
            # Try to parse feedparser date
            import calendar
            import email.utils
            parsed = email.utils.parsedate_tz(published_date)
            if parsed:
                timestamp = calendar.timegm(parsed[:9]) - (parsed[9] or 0)
                pub_dt = datetime.fromtimestamp(timestamp, tz=IST)
                days_ago = (datetime.now(IST) - pub_dt).days

                if days_ago <= 0:
                    return 1.0
                elif days_ago <= 1:
                    return 0.95
                elif days_ago <= 3:
                    return 0.85
                elif days_ago <= 7:
                    return 0.7
                elif days_ago <= 14:
                    return 0.5
                else:
                    return 0.3
        except Exception:
            pass

        return 0.7  # Default if parsing fails

    @staticmethod
    def calculate_directness_multiplier(analysis: SignalAnalysis) -> float:
        """Calculate directness multiplier based on keyword types."""
        if analysis.has_direct_hiring:
            # More direct keywords found = higher multiplier
            count = len(analysis.direct_keywords_found)
            if count >= 3:
                return 1.0
            elif count >= 2:
                return 0.95
            else:
                return 0.9
        elif analysis.has_indirect_hiring:
            return 0.7
        elif analysis.has_funding:
            return 0.6
        elif analysis.has_expansion:
            return 0.55
        return 0.5

    @staticmethod
    def extract_monetary_amount(text: str) -> Optional[float]:
        """Extract funding/revenue amounts from text for signal strength."""
        text_lower = text.lower()

        # Match patterns like "$50 million", "₹200 crore", "$1.5 billion"
        patterns = [
            (r'\$\s*([\d.]+)\s*billion', lambda m: float(m.group(1)) * 1000),
            (r'\$\s*([\d.]+)\s*million', lambda m: float(m.group(1))),
            (r'₹\s*([\d,]+)\s*crore', lambda m: float(m.group(1).replace(',', '')) * 12.5),
            (r'([\d.]+)\s*billion\s*dollar', lambda m: float(m.group(1)) * 1000),
            (r'([\d.]+)\s*million\s*dollar', lambda m: float(m.group(1))),
            (r'inr\s*([\d,]+)\s*crore', lambda m: float(m.group(1).replace(',', '')) * 12.5),
        ]

        for pattern, converter in patterns:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    return converter(match)
                except (ValueError, IndexError):
                    continue

        return None


# ============================================================
# COMPANY MATCHER
# ============================================================

class CompanyMatcher:
    """
    Matches company names in text against the 1080+ company database.
    Uses cached name sets with normalized matching, fuzzy fallback,
    and acronym expansion.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._company_names: Dict[str, int] = {}  # normalized_name -> company_id
        self._company_tiers: Dict[int, int] = {}   # company_id -> tier
        self._acronym_map: Dict[str, str] = {}     # acronym -> full name
        self._loaded = False

    def load(self):
        """Load all company names from database for matching."""
        if self._loaded:
            return

        try:
            companies = self.db.get_all_companies_basic()
            for c in companies:
                name = c.get('name', '')
                norm = name.lower().strip()
                cid = c.get('id')
                tier = c.get('tier', 5)

                if norm and cid:
                    self._company_names[norm] = cid
                    self._company_tiers[cid] = tier

                    # Build acronym map for well-known companies
                    words = name.split()
                    if len(words) >= 2:
                        acronym = ''.join(w[0].upper() for w in words if w[0].isalpha())
                        if len(acronym) >= 2:
                            self._acronym_map[acronym.lower()] = norm

            self._loaded = True
            logger.debug(
                f"[{AGENT_ID}] Loaded {len(self._company_names)} companies, "
                f"{len(self._acronym_map)} acronyms"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Failed to load companies: {e}")

    def match(self, text: str) -> List[Tuple[int, str, int]]:
        """
        Find all matching companies in text.

        Returns:
            List of (company_id, company_name, tier) tuples
        """
        self.load()
        text_lower = text.lower()
        matches = []
        seen_ids = set()

        # Direct name matching (longest match first for accuracy)
        sorted_names = sorted(self._company_names.keys(), key=len, reverse=True)
        for norm_name in sorted_names:
            if norm_name in text_lower:
                cid = self._company_names[norm_name]
                if cid not in seen_ids:
                    tier = self._company_tiers.get(cid, 5)
                    matches.append((cid, norm_name, tier))
                    seen_ids.add(cid)

        return matches

    def match_single(self, text: str) -> Optional[Tuple[int, str, int]]:
        """Match the best single company in text."""
        results = self.match(text)
        if results:
            # Prefer higher-tier companies
            results.sort(key=lambda x: x[2])
            return results[0]
        return None

    def get_tier(self, company_id: int) -> int:
        """Get company tier."""
        self.load()
        return self._company_tiers.get(company_id, 5)


# ============================================================
# RSS FEED SCANNER
# ============================================================

class RSSFeedScanner:
    """
    Scans RSS feeds from economic/tech news sources for
    hiring signals. Supports multiple feed formats and
    graceful handling of feed failures.
    """

    def __init__(self, analyzer: SignalAnalyzer, matcher: CompanyMatcher,
                 router: AIRouter, db: DatabaseManager):
        self.analyzer = analyzer
        self.matcher = matcher
        self.router = router
        self.db = db
        self._seen_urls: Set[str] = set()

    def _get_all_feeds(self) -> Dict[str, Dict]:
        """Combine configured and additional RSS feeds."""
        all_feeds = {}
        if ECONOMIC_SIGNAL_SOURCES:
            all_feeds.update(ECONOMIC_SIGNAL_SOURCES)
        all_feeds.update(ADDITIONAL_RSS_FEEDS)
        return all_feeds

    def scan_all_feeds(self) -> List[IntentSignal]:
        """
        Scan all configured RSS feeds for hiring signals.

        Returns:
            List of detected IntentSignal objects
        """
        if not FEEDPARSER_AVAILABLE:
            logger.warning(f"[{AGENT_ID}] feedparser not installed, RSS scanning disabled")
            return []

        signals = []
        all_feeds = self._get_all_feeds()

        for source_name, source_config in all_feeds.items():
            try:
                feed_url = source_config.get('url', '')
                if not feed_url:
                    continue

                credibility = SOURCE_CREDIBILITY.get(
                    source_name, source_config.get('credibility', 0.7)
                )

                feed_signals = self._scan_single_feed(
                    feed_url, source_name, credibility
                )
                signals.extend(feed_signals)

                # Polite delay between feeds
                time.sleep(random.uniform(1.5, 4.0))

            except Exception as e:
                logger.debug(f"[{AGENT_ID}] RSS feed '{source_name}' error: {e}")
                continue

        logger.info(f"[{AGENT_ID}] RSS scan: {len(signals)} signals from {len(all_feeds)} feeds")
        return signals

    def _scan_single_feed(self, feed_url: str, source_name: str,
                          credibility: float) -> List[IntentSignal]:
        """Scan a single RSS feed."""
        signals = []

        try:
            feed = feedparser.parse(feed_url)
            if not feed or not feed.entries:
                return signals

            for entry in feed.entries[:25]:
                try:
                    signal = self._process_feed_entry(
                        entry, source_name, credibility
                    )
                    if signal:
                        signals.append(signal)
                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] Entry processing error: {e}")
                    continue

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Feed parse error for {source_name}: {e}")

        return signals

    def _process_feed_entry(self, entry: Any, source_name: str,
                            credibility: float) -> Optional[IntentSignal]:
        """Process a single RSS feed entry."""
        title = entry.get('title', '') or ''
        summary = entry.get('summary', '') or ''
        link = entry.get('link', '') or ''
        published = entry.get('published', '') or ''

        # Dedup by URL
        if link in self._seen_urls:
            return None
        self._seen_urls.add(link)

        full_text = f"{title} {summary}"
        if len(full_text.strip()) < 20:
            return None

        # Analyze for signals
        analysis = self.analyzer.analyze_text(full_text)
        if not analysis.is_positive:
            return None

        # Match company
        company_match = self.matcher.match_single(full_text)
        if not company_match:
            return None

        company_id, company_name, tier = company_match

        # Calculate final score
        recency_mult = self.analyzer.calculate_recency_multiplier(published)
        directness_mult = self.analyzer.calculate_directness_multiplier(analysis)
        tier_boost = TIER_BOOST.get(tier, 1.0)

        final_score = (
            analysis.base_score
            * directness_mult
            * recency_mult
            * credibility
            * tier_boost
        )

        # Clamp to 0-100
        final_score = max(0.0, min(100.0, final_score))

        # Check for funding amount → boost
        amount = self.analyzer.extract_monetary_amount(full_text)
        if amount and amount > 10:  # $10M+
            final_score = min(100.0, final_score * 1.1)

        # AI scoring for high-potential signals
        if final_score >= 40:
            try:
                ai_resp = self.router.classify_intent(full_text, source_name)
                if ai_resp.success:
                    data = ai_resp.get_json()
                    if data:
                        ai_score = data.get('signal_score', final_score)
                        ai_type = data.get('signal_type', analysis.signal_type)
                        # Blend AI score with rule-based score
                        final_score = (final_score * 0.4) + (ai_score * 0.6)
                        analysis.signal_type = ai_type
            except Exception:
                pass  # Keep rule-based score

        signal = IntentSignal(
            company_id=company_id,
            signal_type=analysis.signal_type,
            signal_text=full_text[:500],
            signal_score=round(final_score, 1),
            source_url=link,
            expires_at=(datetime.now(IST) + timedelta(days=7)).isoformat(),
        )

        # Check if this reinforces an existing signal
        existing = self.db.get_latest_signal_for_company(company_id)
        if existing:
            # Reinforcement: refresh the existing signal
            existing_score = existing.get('signal_score', 0)
            if final_score > existing_score:
                self.db.update_intent_signal_score(
                    existing['id'], final_score
                )
                return None  # Don't create duplicate
            elif final_score > existing_score * 0.7:
                # Refresh expiry
                self.db.refresh_intent_signal_expiry(
                    existing['id'],
                    (datetime.now(IST) + timedelta(days=7)).isoformat()
                )
                return None

        self.db.insert_intent_signal(signal)
        return signal


# ============================================================
# GOOGLE NEWS SCANNER
# ============================================================

class GoogleNewsScanner:
    """
    Scans Google News RSS for company-specific hiring news.
    Uses multiple query templates per company for comprehensive
    coverage. Respects rate limits and adds delays.
    """

    def __init__(self, analyzer: SignalAnalyzer, matcher: CompanyMatcher,
                 router: AIRouter, db: DatabaseManager):
        self.analyzer = analyzer
        self.matcher = matcher
        self.router = router
        self.db = db
        self._seen_urls: Set[str] = set()

    def scan_companies(self, companies: List[Dict],
                       max_queries_per_company: int = 2) -> List[IntentSignal]:
        """
        Scan Google News for hiring news about specific companies.

        Args:
            companies: List of company dicts from database
            max_queries_per_company: Max query templates to try per company
        """
        if not FEEDPARSER_AVAILABLE:
            return []

        signals = []

        for company in companies:
            try:
                company_signals = self._scan_company(
                    company, max_queries_per_company
                )
                signals.extend(company_signals)
                time.sleep(random.uniform(3, 8))
            except Exception as e:
                logger.debug(
                    f"[{AGENT_ID}] News scan error for "
                    f"{company.get('name', '?')}: {e}"
                )
                continue

        logger.info(
            f"[{AGENT_ID}] Google News scan: {len(signals)} signals "
            f"from {len(companies)} companies"
        )
        return signals

    def _scan_company(self, company: Dict,
                      max_queries: int) -> List[IntentSignal]:
        """Scan Google News for a specific company."""
        signals = []
        name = company.get('name', '')
        company_id = company.get('id')
        tier = company.get('tier', 5)

        if not name or not company_id:
            return signals

        # Select query templates based on tier
        templates = GNEWS_QUERY_TEMPLATES[:max_queries]
        if tier <= 2:
            # More thorough search for high-tier companies
            templates = GNEWS_QUERY_TEMPLATES[:min(4, max_queries + 1)]

        for template in templates:
            try:
                query = template.format(company=name)
                feed_url = GOOGLE_NEWS_RSS_TEMPLATE.format(
                    query=quote_plus(query)
                )

                feed = feedparser.parse(feed_url)
                if not feed or not feed.entries:
                    continue

                for entry in feed.entries[:5]:
                    title = entry.get('title', '') or ''
                    summary = entry.get('summary', '') or ''
                    link = entry.get('link', '') or ''
                    published = entry.get('published', '') or ''

                    if link in self._seen_urls:
                        continue
                    self._seen_urls.add(link)

                    full_text = f"{title} {summary}"
                    analysis = self.analyzer.analyze_text(full_text)

                    if not analysis.is_positive:
                        continue

                    recency_mult = self.analyzer.calculate_recency_multiplier(published)
                    directness_mult = self.analyzer.calculate_directness_multiplier(analysis)
                    tier_boost = TIER_BOOST.get(tier, 1.0)
                    credibility = SOURCE_CREDIBILITY.get('google_news', 0.8)

                    score = (
                        analysis.base_score * directness_mult
                        * recency_mult * credibility * tier_boost
                    )
                    score = max(0.0, min(100.0, score))

                    signal = IntentSignal(
                        company_id=company_id,
                        signal_type=analysis.signal_type,
                        signal_text=full_text[:500],
                        signal_score=round(score, 1),
                        source_url=link,
                        expires_at=(
                            datetime.now(IST) + timedelta(days=7)
                        ).isoformat(),
                    )

                    # Check dedup / reinforcement
                    existing = self.db.get_latest_signal_for_company(company_id)
                    if existing:
                        old_score = existing.get('signal_score', 0)
                        if score > old_score:
                            self.db.update_intent_signal_score(existing['id'], score)
                        continue

                    self.db.insert_intent_signal(signal)
                    signals.append(signal)

                time.sleep(random.uniform(2, 5))
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] GNews query error: {e}")
                continue

        return signals


# ============================================================
# SERPAPI SIGNAL SCANNER (230+/month budget)
# ============================================================

class SerpAPISignalScanner:
    """
    Uses SerpAPI for high-value intent signal discovery.
    Budget: ~2 searches/day allocated to A-01 (60/month).

    Searches for:
        - Tier 1-2 company hiring announcements (Google Search)
        - Campus recruitment drives (Google Search)
        - High-value HR recruiter posts (Google Search)

    Only triggers for Tier 1-2 companies where DDG/RSS found
    no signals, to fill coverage gaps.
    """

    # A-01 gets 2 SerpAPI searches per day from the 230+/month pool
    MAX_SERP_PER_SESSION = 2

    SERP_QUERY_TEMPLATES = [
        '"{company}" hiring intern OR internship 2026 india',
        '"{company}" campus placement OR recruitment drive 2026',
        '"{company}" MBA summer intern program india',
    ]

    def __init__(self, analyzer: SignalAnalyzer, matcher: CompanyMatcher,
                 db: DatabaseManager):
        self.analyzer = analyzer
        self.matcher = matcher
        self.db = db
        self._serpapi_key = get_config().serpapi.api_key
        self._session_count = 0

    def scan_priority_companies(self, companies: List[Dict],
                                already_signaled_ids: Set[int]) -> List[IntentSignal]:
        """
        SerpAPI scan for Tier 1-2 companies without existing signals.

        Args:
            companies: Tier 1-2 company list
            already_signaled_ids: Company IDs that already have signals

        Returns:
            List of new IntentSignal objects
        """
        if not self._serpapi_key:
            return []

        signals = []
        self._session_count = 0

        # Only scan companies WITHOUT existing signals (gap-filling)
        gap_companies = [
            c for c in companies
            if c.get('id') not in already_signaled_ids
            and c.get('tier', 5) <= 2
        ]

        # Prioritize: Tier 1 first, then Tier 2
        gap_companies.sort(key=lambda c: c.get('tier', 5))

        for company in gap_companies:
            if self._session_count >= self.MAX_SERP_PER_SESSION:
                break

            try:
                company_signals = self._serp_search_company(company)
                signals.extend(company_signals)
                time.sleep(random.uniform(2, 5))
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] SerpAPI scan error: {e}")
                continue

        logger.info(
            f"[{AGENT_ID}] SerpAPI scan: {len(signals)} signals, "
            f"{self._session_count}/{self.MAX_SERP_PER_SESSION} searches used"
        )
        return signals

    def _serp_search_company(self, company: Dict) -> List[IntentSignal]:
        """Search SerpAPI for a single company's hiring signals."""
        signals = []
        name = company.get('name', '')
        company_id = company.get('id')
        tier = company.get('tier', 5)

        if not name or not company_id:
            return signals

        # Pick the best query template
        template = self.SERP_QUERY_TEMPLATES[
            self._session_count % len(self.SERP_QUERY_TEMPLATES)
        ]
        query = template.format(company=name)

        try:
            import requests as req_lib
            resp = req_lib.get(
                'https://serpapi.com/search.json',
                params={
                    'q': query,
                    'api_key': self._serpapi_key,
                    'num': 10,
                    'gl': 'in',
                    'hl': 'en',
                },
                timeout=15,
            )
            self._session_count += 1

            if resp.status_code != 200:
                logger.debug(f"[{AGENT_ID}] SerpAPI HTTP {resp.status_code}")
                return signals

            data = resp.json()
            for result in data.get('organic_results', [])[:8]:
                title = result.get('title', '') or ''
                snippet = result.get('snippet', '') or ''
                link = result.get('link', '') or ''

                full_text = f"{title} {snippet}"
                analysis = self.analyzer.analyze_text(full_text)

                if not analysis.is_positive:
                    continue

                tier_boost = TIER_BOOST.get(tier, 1.0)
                # SerpAPI results are Google-ranked = higher credibility
                credibility = 0.9
                recency_mult = 0.85  # Can't easily determine date from SerpAPI

                score = (
                    analysis.base_score * credibility
                    * tier_boost * recency_mult
                )
                score = max(0.0, min(100.0, score))

                signal = IntentSignal(
                    company_id=company_id,
                    signal_type=analysis.signal_type,
                    signal_text=f"[SerpAPI] {full_text[:480]}",
                    signal_score=round(score, 1),
                    source_url=link,
                    expires_at=(
                        datetime.now(IST) + timedelta(days=7)
                    ).isoformat(),
                )

                # Dedup check
                existing = self.db.get_latest_signal_for_company(company_id)
                if existing:
                    if score > existing.get('signal_score', 0):
                        self.db.update_intent_signal_score(existing['id'], score)
                    continue

                self.db.insert_intent_signal(signal)
                signals.append(signal)

        except ImportError:
            logger.warning(f"[{AGENT_ID}] requests library not available for SerpAPI")
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] SerpAPI query error: {e}")

        return signals


# ============================================================
# DDG HR POST SCANNER
# ============================================================

class DDGHRPostScanner:
    """
    Scans DuckDuckGo for HR/recruiter posts on LinkedIn, Twitter,
    and job boards indicating active hiring at target companies.
    Strictly rate-limited: max 5 dorks per session.
    """

    def __init__(self, analyzer: SignalAnalyzer, matcher: CompanyMatcher,
                 router: AIRouter, db: DatabaseManager):
        self.analyzer = analyzer
        self.matcher = matcher
        self.router = router
        self.db = db
        self._ddg = None
        self._session_dork_count = 0

    def _get_ddg(self):
        """Lazy-load DuckDuckGo search client."""
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    logger.warning(f"[{AGENT_ID}] ddgs not installed (pip install ddgs)")
        return self._ddg

    def scan_companies(self, companies: List[Dict]) -> List[IntentSignal]:
        """
        Scan DDG for HR posts about companies.
        Rate limit: max 5 dorks per session.
        """
        ddg = self._get_ddg()
        if not ddg:
            return []

        signals = []
        self._session_dork_count = 0

        for company in companies:
            if self._session_dork_count >= MAX_DDG_DORKS_PER_SESSION:
                logger.info(
                    f"[{AGENT_ID}] DDG dork limit reached "
                    f"({MAX_DDG_DORKS_PER_SESSION})"
                )
                break

            try:
                company_signals = self._scan_company_hr(company)
                signals.extend(company_signals)
                time.sleep(random.uniform(*DDG_COOLDOWN_SECONDS))
            except Exception as e:
                logger.debug(
                    f"[{AGENT_ID}] DDG scan error for "
                    f"{company.get('name', '?')}: {e}"
                )
                continue

        logger.info(
            f"[{AGENT_ID}] DDG HR scan: {len(signals)} signals, "
            f"{self._session_dork_count} dorks used"
        )
        return signals

    def _scan_company_hr(self, company: Dict) -> List[IntentSignal]:
        """Scan DDG for HR posts about a specific company."""
        signals = []
        name = company.get('name', '')
        company_id = company.get('id')
        tier = company.get('tier', 5)

        if not name or not company_id:
            return signals

        # Select best dork template
        template_idx = min(self._session_dork_count, len(HR_DDG_TEMPLATES) - 1)
        dork_template = HR_DDG_TEMPLATES[template_idx]
        dork = dork_template.format(company=name)

        try:
            ddg = self._get_ddg()
            results = ddg.text(dork, region='in-en', max_results=8)
            self._session_dork_count += 1

            for result in (results or []):
                title = result.get('title', '') or ''
                body = result.get('body', '') or ''
                url = result.get('href', '') or ''
                full_text = f"{title} {body}"

                # Must contain HR/hiring indicators
                hr_indicators = [
                    'talent acquisition', 'recruiter', 'hiring',
                    'we are hiring', 'hr manager', 'people operations',
                    'talent partner', 'recruitment', 'intern', 'trainee',
                ]
                has_hr = any(ind in full_text.lower() for ind in hr_indicators)
                if not has_hr:
                    continue

                analysis = self.analyzer.analyze_text(full_text)
                tier_boost = TIER_BOOST.get(tier, 1.0)
                credibility = SOURCE_CREDIBILITY.get('ddg_linkedin', 0.75)

                base = SIGNAL_BASE_SCORES.get('hr_post', 65.0)
                score = base * credibility * tier_boost

                # LinkedIn posts are more reliable
                if 'linkedin.com' in url:
                    score *= 1.1

                score = max(0.0, min(100.0, score))

                signal = IntentSignal(
                    company_id=company_id,
                    signal_type='hr_post',
                    signal_text=full_text[:500],
                    signal_score=round(score, 1),
                    source_url=url,
                    expires_at=(
                        datetime.now(IST) + timedelta(days=7)
                    ).isoformat(),
                )

                self.db.insert_intent_signal(signal)
                signals.append(signal)

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] DDG HR dork error: {e}")

        return signals


# ============================================================
# SIGNAL DECAY ENGINE
# ============================================================

class SignalDecayEngine:
    """
    Manages signal decay over time. Signals lose 10 points/day
    without reinforcement. Expired signals are archived.
    Urgent alerts are triggered when Tier 1/2 companies have
    active signals with score >= 70.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def apply_daily_decay(self, decay_per_day: float = 10.0) -> int:
        """
        Apply daily decay to all active signals.

        Returns:
            Number of signals decayed
        """
        try:
            count = self.db.apply_signal_decay(decay_per_day=decay_per_day)
            logger.info(f"[{AGENT_ID}] Signal decay applied to {count} signals")
            return count
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Signal decay error: {e}")
            return 0

    def cleanup_expired(self) -> int:
        """Remove expired signals (score <= 0 or past expiry date)."""
        try:
            count = self.db.cleanup_expired_signals()
            logger.info(f"[{AGENT_ID}] Cleaned up {count} expired signals")
            return count
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Signal cleanup error: {e}")
            return 0

    def get_urgent_alerts(self, min_score: float = 70.0,
                          max_tier: int = 2) -> List[Dict]:
        """
        Get urgent alerts for high-tier companies with strong signals.

        Args:
            min_score: Minimum signal score for urgency
            max_tier: Maximum tier level (1=Elite, 2=Strong MNC)
        """
        try:
            signals = self.db.get_active_signals(
                min_score=min_score, days=3
            )
            urgent = []
            for sig in signals:
                tier = sig.get('tier', 5)
                if tier <= max_tier:
                    urgent.append(sig)
            return urgent
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Urgent alert error: {e}")
            return []

    def get_signal_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get summary of active signals for reporting."""
        try:
            signals = self.db.get_active_signals(min_score=0, days=days)

            summary = {
                'total_active': len(signals),
                'by_type': defaultdict(int),
                'by_tier': defaultdict(int),
                'avg_score': 0.0,
                'top_signals': [],
            }

            scores = []
            for sig in signals:
                sig_type = sig.get('signal_type', 'unknown')
                tier = sig.get('tier', 5)
                score = sig.get('signal_score', 0)

                summary['by_type'][sig_type] += 1
                summary['by_tier'][f"Tier {tier}"] += 1
                scores.append(score)

            if scores:
                summary['avg_score'] = round(sum(scores) / len(scores), 1)

            # Top 5 signals
            sorted_signals = sorted(
                signals,
                key=lambda s: s.get('signal_score', 0),
                reverse=True
            )
            summary['top_signals'] = sorted_signals[:5]

            return summary
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Signal summary error: {e}")
            return {}


# ============================================================
# FUNDING SIGNAL DETECTOR
# ============================================================

class FundingSignalDetector:
    """
    Specialized detector for funding announcements that
    strongly correlate with upcoming hiring. Detects round type,
    amount, and estimates hiring probability based on funding stage.
    """

    # Hiring probability by funding round
    ROUND_HIRING_PROBABILITY = {
        'seed': 0.6,
        'pre-series a': 0.65,
        'series a': 0.75,
        'series b': 0.85,
        'series c': 0.80,
        'series d': 0.70,
        'series e': 0.65,
        'growth': 0.75,
        'ipo': 0.50,
    }

    @staticmethod
    def detect_round(text: str) -> Optional[str]:
        """Detect the funding round type from text."""
        text_lower = text.lower()
        for round_name in ['series e', 'series d', 'series c', 'series b',
                           'series a', 'pre-series a', 'seed', 'growth',
                           'bridge', 'ipo', 'pre-ipo']:
            if round_name in text_lower:
                return round_name
        return None

    def calculate_funding_signal_score(self, text: str,
                                       base_score: float) -> float:
        """
        Boost signal score based on funding details.

        Returns:
            Adjusted score
        """
        round_type = self.detect_round(text)
        if round_type:
            prob = self.ROUND_HIRING_PROBABILITY.get(round_type, 0.5)
            base_score *= (1.0 + (prob - 0.5))  # Boost by hiring probability

        # Amount-based boost
        amount = SignalAnalyzer.extract_monetary_amount(text)
        if amount:
            if amount >= 100:    # $100M+
                base_score *= 1.15
            elif amount >= 50:   # $50M+
                base_score *= 1.10
            elif amount >= 20:   # $20M+
                base_score *= 1.05

        return min(100.0, base_score)


# ============================================================
# MASTER INTENT SCANNER
# ============================================================

class IntentScanner:
    """
    Master intent signal scanner that orchestrates all sub-scanners.
    Runs twice daily (09:00 AM + 04:00 PM IST) to detect companies
    actively hiring BEFORE they post on job boards.

    Pipeline:
        1. Load company database for matching
        2. Scan RSS feeds (economic + tech news)
        3. Scan Google News (company-specific queries)
        4. Scan DDG for HR/recruiter posts
        5. Detect funding signals
        6. AI-score high-potential signals
        7. Apply signal decay
        8. Generate urgent alerts
        9. Store results in intent_signals table
        10. Update agent heartbeat
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.router = get_router()
        self.analyzer = SignalAnalyzer()
        self.matcher = CompanyMatcher(self.db)
        self.decay_engine = SignalDecayEngine(self.db)
        self.funding_detector = FundingSignalDetector()
        self.rss_scanner = RSSFeedScanner(
            self.analyzer, self.matcher, self.router, self.db
        )
        self.news_scanner = GoogleNewsScanner(
            self.analyzer, self.matcher, self.router, self.db
        )
        self.hr_scanner = DDGHRPostScanner(
            self.analyzer, self.matcher, self.router, self.db
        )
        self.serp_scanner = SerpAPISignalScanner(
            self.analyzer, self.matcher, self.db
        )

    def run_scan(self, tier_filter: Optional[List[int]] = None,
                 scan_type: str = "full") -> ScanResult:
        """
        Run a complete intent signal scan.

        Args:
            tier_filter: Tiers to scan (default: [1, 2] for Tier 1+2)
            scan_type: "full", "morning", "afternoon"
        """
        logger.info(f"[{AGENT_ID}] === INTENT SCAN START ({scan_type}) ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        result = ScanResult(
            scan_type=scan_type,
            start_time=datetime.now(IST).isoformat(),
        )

        if tier_filter is None:
            tier_filter = [1, 2]

        # Preload company database
        self.matcher.load()

        # 1. Scan RSS feeds
        try:
            rss_signals = self.rss_scanner.scan_all_feeds()
            result.rss_signals = len(rss_signals)
            result.signals_found += len(rss_signals)
            result.sources_scanned += len(self.rss_scanner._get_all_feeds())
        except Exception as e:
            result.errors.append(f"RSS: {e}")
            logger.error(f"[{AGENT_ID}] RSS scan failed: {e}")

        # 2. Scan company-specific Google News
        try:
            companies = []
            for tier in tier_filter:
                tier_companies = self.db.get_companies_by_tier(tier, limit=50)
                companies.extend(tier_companies)
            result.companies_scanned = len(companies)

            # Limit to avoid rate limiting
            max_news = 30 if scan_type == "full" else 15
            news_signals = self.news_scanner.scan_companies(
                companies[:max_news],
                max_queries_per_company=2 if scan_type == "full" else 1
            )
            result.news_signals = len(news_signals)
            result.signals_found += len(news_signals)
        except Exception as e:
            result.errors.append(f"News: {e}")
            logger.error(f"[{AGENT_ID}] News scan failed: {e}")

        # 3. DDG HR posts (Tier 1 only for budget)
        try:
            tier1_companies = [c for c in companies if c.get('tier', 5) <= 2]
            hr_signals = self.hr_scanner.scan_companies(
                tier1_companies[:MAX_DDG_DORKS_PER_SESSION]
            )
            result.hr_signals = len(hr_signals)
            result.signals_found += len(hr_signals)
        except Exception as e:
            result.errors.append(f"DDG: {e}")
            logger.error(f"[{AGENT_ID}] DDG scan failed: {e}")

        # 4. SerpAPI gap-fill for Tier 1-2 (230+/month budget)
        try:
            already_signaled = set()
            existing_signals = self.db.get_active_signals(min_score=10, days=7)
            for sig in existing_signals:
                cid = sig.get('company_id')
                if cid:
                    already_signaled.add(cid)

            serp_signals = self.serp_scanner.scan_priority_companies(
                [c for c in companies if c.get('tier', 5) <= 2],
                already_signaled
            )
            result.signals_found += len(serp_signals)
        except Exception as e:
            result.errors.append(f"SerpAPI: {e}")
            logger.error(f"[{AGENT_ID}] SerpAPI scan failed: {e}")

        # 5. Apply signal decay (renumbered after SerpAPI step)
        try:
            decayed = self.decay_engine.apply_daily_decay(decay_per_day=10.0)
            result.signals_decayed = decayed
        except Exception as e:
            result.errors.append(f"Decay: {e}")

        # 6. Cleanup expired signals
        try:
            self.decay_engine.cleanup_expired()
        except Exception:
            pass

        # 7. Count urgent alerts
        try:
            urgent = self.decay_engine.get_urgent_alerts(
                min_score=70.0, max_tier=2
            )
            result.urgent_alerts = len(urgent)
            result.urgent_companies = [
                u.get('company_name', 'Unknown') for u in urgent[:10]
            ]
        except Exception as e:
            result.errors.append(f"Urgent: {e}")

        # Finalize result
        duration = time.time() - start_time
        result.duration_sec = round(duration, 1)
        result.end_time = datetime.now(IST).isoformat()

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=result.signals_found,
            errors=len(result.errors),
            duration_sec=duration,
        )

        logger.info(
            f"[{AGENT_ID}] === INTENT SCAN COMPLETE === "
            f"Signals: {result.signals_found} | "
            f"Urgent: {result.urgent_alerts} | "
            f"Duration: {result.duration_sec}s | "
            f"Errors: {len(result.errors)}"
        )

        return result

    def get_signal_report(self, days: int = 7) -> str:
        """Generate signal report for Telegram /signals command."""
        summary = self.decay_engine.get_signal_summary(days=days)
        if not summary:
            return "📡 No active signals this week."

        lines = [
            f"📡 <b>Active Intent Signals ({days}d)</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"Total Active: {summary.get('total_active', 0)}",
            f"Avg Score: {summary.get('avg_score', 0):.0f}",
            f"",
        ]

        # By type
        by_type = summary.get('by_type', {})
        if by_type:
            lines.append("<b>By Type:</b>")
            for sig_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
                emoji = {
                    'news': '📰', 'hr_post': '👤', 'funding': '💰',
                    'expansion': '🏗', 'campus': '🎓', 'layoff': '⚠️',
                }.get(sig_type, '📡')
                lines.append(f"  {emoji} {sig_type}: {count}")
            lines.append("")

        # By tier
        by_tier = summary.get('by_tier', {})
        if by_tier:
            lines.append("<b>By Tier:</b>")
            for tier_name, count in sorted(by_tier.items()):
                lines.append(f"  {tier_name}: {count}")
            lines.append("")

        # Top signals
        top = summary.get('top_signals', [])
        if top:
            lines.append("<b>Top Signals:</b>")
            for i, sig in enumerate(top[:5], 1):
                company_name = sig.get('company_name', 'Unknown')
                score = sig.get('signal_score', 0)
                sig_type = sig.get('signal_type', '')
                lines.append(
                    f"  {i}. <b>{company_name}</b> — {score:.0f} [{sig_type}]"
                )

        return '\n'.join(lines)

    def search_company_signals(self, company_name: str) -> Dict[str, Any]:
        """Search for signals about a specific company (for /research command)."""
        self.matcher.load()
        match = self.matcher.match_single(company_name)
        if not match:
            return {'error': f'Company "{company_name}" not found'}

        company_id, name, tier = match
        signals = self.db.get_signals_for_company(company_id, days=30)

        return {
            'company': name,
            'tier': tier,
            'signals': signals,
            'total': len(signals),
            'avg_score': (
                round(sum(s.get('signal_score', 0) for s in signals) / len(signals), 1)
                if signals else 0
            ),
        }


# ============================================================
# SINGLETON ACCESS
# ============================================================

_scanner_instance: Optional[IntentScanner] = None


def get_intent_scanner() -> IntentScanner:
    """Get or create the singleton IntentScanner instance."""
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = IntentScanner()
    return _scanner_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test SignalAnalyzer
    analyzer = SignalAnalyzer()

    test_texts = [
        ("McKinsey hiring MBA interns for 2026 summer program", "direct_hiring"),
        ("Zepto raises $200 million in Series F round", "funding"),
        ("Flipkart opens new office in Pune, expanding team", "expansion"),
        ("Byju's lays off 1000 employees in restructuring", "layoff"),
        ("Tata Group campus placement drive at IIM Ahmedabad", "campus"),
    ]

    print("\nSignal Analyzer Tests:")
    for text, expected_type in test_texts:
        analysis = analyzer.analyze_text(text)
        status = "✅" if analysis.signal_type == expected_type else "❌"
        print(f"  {status} '{text[:60]}...'")
        print(f"     Type: {analysis.signal_type} (expected: {expected_type})")
        print(f"     Score: {analysis.base_score:.0f}")
        print(f"     Keywords: {analysis.keyword_count}")

    # Test monetary extraction
    print("\nMonetary Extraction Tests:")
    test_amounts = [
        ("raised $50 million", 50.0),
        ("raised $1.5 billion", 1500.0),
        ("₹200 crore funding", 2500.0),
    ]
    for text, expected in test_amounts:
        amount = analyzer.extract_monetary_amount(text)
        status = "✅" if amount and abs(amount - expected) < 1 else "❌"
        print(f"  {status} '{text}' → ${amount}M (expected: ${expected}M)")

    # Test FundingSignalDetector
    print("\nFunding Round Detection:")
    fsd = FundingSignalDetector()
    for text in ["Series B round", "seed funding", "IPO filing"]:
        round_type = fsd.detect_round(text)
        print(f"  '{text}' → {round_type}")

    print(f"\nConfiguration:")
    print(f"  Direct hiring keywords: {len(HIRING_KEYWORDS_DIRECT)}")
    print(f"  Indirect keywords: {len(HIRING_KEYWORDS_INDIRECT)}")
    print(f"  Funding keywords: {len(FUNDING_KEYWORDS)}")
    print(f"  Expansion keywords: {len(EXPANSION_KEYWORDS)}")
    print(f"  Negative keywords: {len(NEGATIVE_KEYWORDS)}")
    print(f"  RSS feeds: {len(ADDITIONAL_RSS_FEEDS) + len(ECONOMIC_SIGNAL_SOURCES if ECONOMIC_SIGNAL_SOURCES else {})}")
    print(f"  GNews templates: {len(GNEWS_QUERY_TEMPLATES)}")
    print(f"  DDG templates: {len(HR_DDG_TEMPLATES)}")
    print(f"  Source credibility: {len(SOURCE_CREDIBILITY)} sources")
    print(f"  feedparser: {'✅' if FEEDPARSER_AVAILABLE else '❌'}")
    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) ready!")
    print("=" * 60)
