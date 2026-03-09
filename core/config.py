"""
============================================================
OPERATION FIRST MOVER v5 — CORE CONFIGURATION MODULE
============================================================
Complete configuration management system for the zero-cost
MBA Hunt Agent. Handles all environment variables, constants,
rate limits, provider configs, company tiers, MBA categories,
stealth profiles, scheduling, and system-wide settings.

This module is the SINGLE SOURCE OF TRUTH for all configuration
values used across all 12 agents and core infrastructure.

Sections:
    1. Environment Loading & Validation
    2. AI Provider Configuration (Groq + Cerebras)
    3. Telegram Configuration
    4. Proxy & Stealth Configuration
    5. Search & Discovery API Configuration
    6. Database Configuration
    7. Scraping Source Configuration (Internshala, Naukri, etc.)
    8. MBA Categories & Company Tiers
    9. Rate Limit Configuration
    10. PPO Scoring Weights
    11. Ghost Detection Thresholds
    12. Blue Ocean Criteria
    13. CIRS Configuration
    14. Scheduling Configuration (24-hour IST)
    15. User-Agent Pool (20+ agents)
    16. TLS Fingerprint Profiles
    17. Logging Configuration
    18. Render Deployment Settings
    19. Telegram Dark Channel Configuration
    20. Economic Signal Sources
============================================================
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from enum import Enum, IntEnum

# ---------------------------------------------------------------------------
# Third-party imports (graceful fallback)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required if env vars are set directly

try:
    from loguru import logger as loguru_logger
    USE_LOGURU = True
except ImportError:
    USE_LOGURU = False


# ============================================================
# SECTION 1: ENVIRONMENT LOADING & VALIDATION
# ============================================================

class ConfigValidationError(Exception):
    """Raised when a required configuration value is missing or invalid."""
    pass


class EnvironmentType(Enum):
    """Deployment environment types."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    RENDER = "render"
    DOCKER = "docker"
    LOCAL = "local"


def _get_env(key: str, default: Optional[str] = None, required: bool = False,
             cast_type: type = str, description: str = "") -> Any:
    """
    Retrieve an environment variable with type casting, validation, and
    detailed error messages.

    Args:
        key: Environment variable name.
        default: Default value if not set.
        required: If True, raises ConfigValidationError when missing.
        cast_type: Target type for the value (str, int, float, bool).
        description: Human-readable description for error messages.

    Returns:
        The environment variable value cast to the requested type.

    Raises:
        ConfigValidationError: When a required variable is missing or
            cannot be cast to the requested type.
    """
    raw_value = os.environ.get(key, default)

    if raw_value is None and required:
        raise ConfigValidationError(
            f"Required environment variable '{key}' is not set. "
            f"Description: {description or 'No description provided'}. "
            f"Please set it in your .env file or environment."
        )

    if raw_value is None:
        return default

    # Type casting
    try:
        if cast_type is bool:
            return raw_value.lower() in ('true', '1', 'yes', 'on')
        elif cast_type is int:
            return int(raw_value)
        elif cast_type is float:
            return float(raw_value)
        else:
            return str(raw_value)
    except (ValueError, TypeError) as e:
        raise ConfigValidationError(
            f"Environment variable '{key}' has invalid value '{raw_value}' "
            f"for type {cast_type.__name__}: {e}"
        )


def _get_env_list(key: str, default: Optional[List[str]] = None,
                  separator: str = ",") -> List[str]:
    """
    Retrieve an environment variable as a list of strings.

    Args:
        key: Environment variable name.
        default: Default list if not set.
        separator: Delimiter for splitting the string.

    Returns:
        List of stripped string values.
    """
    raw = os.environ.get(key)
    if raw is None:
        return default or []
    return [item.strip() for item in raw.split(separator) if item.strip()]


# ============================================================
# SECTION 2: AI PROVIDER CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class GroqConfig:
    """Configuration for Groq AI provider (heavy tasks)."""
    api_key: str
    model: str = "llama-3.3-70b-versatile"
    base_url: str = "https://api.groq.com/openai/v1"
    max_tokens_default: int = 800
    max_tokens_cover_letter: int = 1200
    max_tokens_ats_simulation: int = 1500
    max_tokens_jd_analysis: int = 1200
    max_tokens_company_research: int = 2000
    max_tokens_outreach_draft: int = 800
    max_tokens_resume_tweaks: int = 1000
    max_tokens_report_compile: int = 2500
    daily_request_limit: int = 14400
    requests_per_minute: int = 30
    requests_per_hour: int = 500
    temperature_default: float = 0.3
    temperature_creative: float = 0.7
    temperature_analytical: float = 0.1
    retry_attempts: int = 3
    retry_base_delay: float = 2.0
    retry_max_delay: float = 30.0
    timeout_seconds: int = 60

    # Task-specific configurations
    TASKS: frozenset = frozenset({
        'cover_letter', 'ats_simulation', 'resume_tweaks',
        'jd_analysis', 'outreach_draft', 'company_research',
        'report_compile', 'economic_analysis', 'package_generate',
        'network_outreach', 'deep_analysis'
    })


@dataclass(frozen=True)
class CerebrasConfig:
    """Configuration for Cerebras AI provider (fast tasks)."""
    api_key: str
    model: str = "llama-3.3-70b"
    base_url: str = "https://api.cerebras.ai/v1"
    max_tokens_default: int = 500
    max_tokens_classify: int = 200
    max_tokens_extract: int = 600
    max_tokens_score: int = 300
    max_tokens_parse: int = 800
    max_tokens_tag: int = 200
    daily_request_limit: int = 100000  # Generous free tier
    requests_per_minute: int = 60
    requests_per_hour: int = 2000
    temperature_default: float = 0.1
    temperature_classify: float = 0.0
    retry_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 15.0
    timeout_seconds: int = 30

    # Task-specific configurations
    TASKS: frozenset = frozenset({
        'ghost_classify', 'intent_classify', 'extract_basics',
        'dedup_score', 'internshala_parse', 'sector_tag',
        'naukri_parse', 'iimjobs_parse', 'ats_extract',
        'dark_classify', 'signal_score', 'quick_classify'
    })


@dataclass
class AIProviderStatus:
    """Runtime tracking for AI provider health and usage."""
    provider: str
    total_requests_today: int = 0
    total_tokens_today: int = 0
    errors_today: int = 0
    rate_limited_count: int = 0
    last_request_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    last_error_message: str = ""
    is_healthy: bool = True
    consecutive_errors: int = 0
    requests_this_hour: int = 0
    requests_this_minute: int = 0
    hour_reset_time: Optional[datetime] = None
    minute_reset_time: Optional[datetime] = None


# Task to temperature mapping
TASK_TEMPERATURE_MAP: Dict[str, float] = {
    # Cerebras tasks (analytical, low temperature)
    'ghost_classify': 0.0,
    'intent_classify': 0.0,
    'extract_basics': 0.1,
    'dedup_score': 0.0,
    'internshala_parse': 0.1,
    'sector_tag': 0.0,
    'naukri_parse': 0.1,
    'iimjobs_parse': 0.1,
    'ats_extract': 0.1,
    'dark_classify': 0.0,
    'signal_score': 0.0,
    'quick_classify': 0.0,
    # Groq tasks (creative / analytical)
    'cover_letter': 0.7,
    'ats_simulation': 0.2,
    'resume_tweaks': 0.3,
    'jd_analysis': 0.2,
    'outreach_draft': 0.6,
    'company_research': 0.3,
    'report_compile': 0.3,
    'economic_analysis': 0.2,
    'package_generate': 0.4,
    'network_outreach': 0.5,
    'deep_analysis': 0.2,
}

# Task to max_tokens mapping
TASK_MAX_TOKENS_MAP: Dict[str, int] = {
    # Cerebras tasks
    'ghost_classify': 200,
    'intent_classify': 200,
    'extract_basics': 600,
    'dedup_score': 300,
    'internshala_parse': 800,
    'sector_tag': 200,
    'naukri_parse': 800,
    'iimjobs_parse': 800,
    'ats_extract': 600,
    'dark_classify': 300,
    'signal_score': 300,
    'quick_classify': 150,
    # Groq tasks
    'cover_letter': 1200,
    'ats_simulation': 1500,
    'resume_tweaks': 1000,
    'jd_analysis': 1200,
    'outreach_draft': 800,
    'company_research': 2000,
    'report_compile': 2500,
    'economic_analysis': 1500,
    'package_generate': 2500,
    'network_outreach': 800,
    'deep_analysis': 2000,
}


# ============================================================
# SECTION 3: TELEGRAM CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class TelegramBotConfig:
    """Configuration for the Telegram bot (A-12 command center)."""
    bot_token: str
    chat_id: str
    parse_mode: str = "HTML"
    max_message_length: int = 4096
    max_retries: int = 3
    retry_delay: float = 2.0
    rate_limit_messages_per_minute: int = 20
    rate_limit_messages_per_second: int = 1
    webhook_enabled: bool = False
    webhook_url: str = ""
    polling_timeout: int = 30
    polling_interval: float = 1.0
    connection_pool_size: int = 8
    read_timeout: int = 30
    write_timeout: int = 30
    connect_timeout: int = 15
    flood_control_wait: float = 1.5


@dataclass(frozen=True)
class TelethonConfig:
    """Configuration for Telethon (dark channel monitoring)."""
    api_id: str = ""
    api_hash: str = ""
    session_name: str = "firstmover_session"
    flood_sleep_threshold: int = 60
    connection_retries: int = 5
    retry_delay: float = 5.0
    auto_reconnect: bool = True
    sequential_updates: bool = True

    # Monitored channels (Indian MBA job groups)
    MONITORED_CHANNELS: tuple = (
        # Telegram group usernames or IDs to monitor
        # These should be populated by the user
    )


# ============================================================
# SECTION 4: PROXY & STEALTH CONFIGURATION
# ============================================================

class ProxyType(Enum):
    """Proxy layer types in the stealth system."""
    WEBSHARE = "webshare"       # L1: Primary (10 free IPs)
    CLOUDFLARE = "cloudflare"   # L2: Relay (global edge IPs)
    TOR = "tor"                 # L3: Anonymity (unlimited exits)
    FREE_LIST = "free_list"     # L4: Fallback (50-200 IPs)
    DIRECT = "direct"           # No proxy (for safe APIs)


@dataclass(frozen=True)
class WebshareConfig:
    """Configuration for Webshare proxy (L1 — 10 free IPs)."""
    api_key: str = ""
    api_url: str = "https://proxy.webshare.io/api/v2/proxy/list/"
    download_url: str = "https://proxy.webshare.io/api/v2/proxy/list/download/{api_key}/all/any/hostname/plain/"
    max_ips: int = 10
    rotation_interval_sec: int = 300  # Rotate every 5 minutes
    health_check_interval_sec: int = 3600  # Hourly health check
    max_consecutive_failures: int = 3
    timeout_seconds: int = 30
    auth_type: str = "ip"  # ip or userpass


@dataclass(frozen=True)
class CloudflareRelayConfig:
    """Configuration for Cloudflare Worker relay (L2)."""
    worker_url: str = ""
    relay_secret: str = ""
    daily_request_limit: int = 100000
    timeout_seconds: int = 30
    retry_attempts: int = 2
    retry_delay: float = 3.0


@dataclass(frozen=True)
class TorConfig:
    """Configuration for Tor proxy (L3 — sensitive requests)."""
    socks_port: int = 9050
    control_port: int = 9051
    socks_host: str = "127.0.0.1"
    control_password: str = ""
    circuit_renewal_interval_sec: int = 300
    max_retries: int = 3
    timeout_seconds: int = 60
    enabled: bool = False  # Disabled by default on Render


@dataclass(frozen=True)
class FreeProxyConfig:
    """Configuration for free proxy list fallback (L4)."""
    sources: tuple = (
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    )
    health_check_interval_sec: int = 3600
    max_pool_size: int = 200
    min_healthy_proxies: int = 10
    test_url: str = "https://httpbin.org/ip"
    test_timeout_seconds: int = 10
    max_latency_ms: int = 5000


@dataclass(frozen=True)
class StealthTimingConfig:
    """Timing configuration for human-like behavior simulation."""
    # Per-request delays (seconds)
    min_delay: float = 8.0
    max_delay: float = 25.0
    # Micro-pauses (simulates reading)
    micro_pause_min: float = 0.5
    micro_pause_max: float = 2.0
    # Session parameters
    pages_per_session_min: int = 5
    pages_per_session_max: int = 10
    session_break_min: float = 60.0   # 1 minute
    session_break_max: float = 300.0  # 5 minutes
    # Domain cooldown
    domain_cooldown_seconds: int = 600  # 10 minutes before same IP


# Per-site stealth profiles
SITE_STEALTH_PROFILES: Dict[str, Dict[str, Any]] = {
    'internshala': {
        'tls_profile': 'chrome120',
        'api_type': 'mobile_ajax',
        'delay_min': 5.0,
        'delay_max': 15.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 50,
        'max_pages_per_session': 10,
        'requires_cookies': True,
        'user_agent_type': 'mobile',
        'base_url': 'https://internshala.com',
        'ajax_url': 'https://internshala.com/internships/ajax/search_ajax',
    },
    'naukri': {
        'tls_profile': 'chrome120',
        'api_type': 'mobile_api',
        'delay_min': 10.0,
        'delay_max': 20.0,
        'proxy_layer': ProxyType.CLOUDFLARE,
        'max_requests_per_hour': 30,
        'max_pages_per_session': 8,
        'requires_cookies': False,
        'user_agent_type': 'mobile',
        'base_url': 'https://www.naukri.com',
        'api_url': 'https://api.naukri.com',
    },
    'linkedin': {
        'tls_profile': None,  # DDG dorks only
        'api_type': 'dork',
        'delay_min': 30.0,
        'delay_max': 60.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 5,
        'max_pages_per_session': 3,
        'requires_cookies': False,
        'user_agent_type': 'desktop',
        'dork_prefix': 'site:linkedin.com/jobs',
    },
    'iimjobs': {
        'tls_profile': None,
        'api_type': 'web',
        'delay_min': 8.0,
        'delay_max': 12.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 40,
        'max_pages_per_session': 10,
        'requires_cookies': False,
        'user_agent_type': 'desktop',
        'base_url': 'https://www.iimjobs.com',
    },
    'glassdoor': {
        'tls_profile': 'chrome120',
        'api_type': 'web',
        'delay_min': 15.0,
        'delay_max': 30.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 20,
        'max_pages_per_session': 5,
        'requires_cookies': True,
        'user_agent_type': 'desktop',
        'base_url': 'https://www.glassdoor.co.in',
    },
    'greenhouse': {
        'tls_profile': None,
        'api_type': 'rest_api',
        'delay_min': 2.0,
        'delay_max': 5.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 100,
        'max_pages_per_session': 50,
        'requires_cookies': False,
        'user_agent_type': 'desktop',
        'api_base': 'https://boards-api.greenhouse.io/v1/boards',
    },
    'lever': {
        'tls_profile': None,
        'api_type': 'rest_api',
        'delay_min': 2.0,
        'delay_max': 5.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 100,
        'max_pages_per_session': 50,
        'requires_cookies': False,
        'user_agent_type': 'desktop',
        'api_base': 'https://api.lever.co/v0/postings',
    },
    'workday': {
        'tls_profile': 'chrome120',
        'api_type': 'web',
        'delay_min': 5.0,
        'delay_max': 10.0,
        'proxy_layer': ProxyType.CLOUDFLARE,
        'max_requests_per_hour': 40,
        'max_pages_per_session': 10,
        'requires_cookies': True,
        'user_agent_type': 'desktop',
    },
    'wellfound': {
        'tls_profile': None,
        'api_type': 'graphql',
        'delay_min': 3.0,
        'delay_max': 8.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 40,
        'max_pages_per_session': 10,
        'requires_cookies': False,
        'user_agent_type': 'desktop',
        'base_url': 'https://wellfound.com',
    },
    'indeed': {
        'tls_profile': 'chrome120',
        'api_type': 'rss',
        'delay_min': 5.0,
        'delay_max': 12.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 30,
        'max_pages_per_session': 10,
        'requires_cookies': False,
        'user_agent_type': 'desktop',
        'rss_base': 'https://www.indeed.co.in/rss',
    },
    'telegram_dark': {
        'tls_profile': None,
        'api_type': 'native',
        'delay_min': 1.0,
        'delay_max': 3.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 500,
        'max_pages_per_session': 100,
        'requires_cookies': False,
    },
    'twitter_x': {
        'tls_profile': None,
        'api_type': 'rest_api',
        'delay_min': 2.0,
        'delay_max': 5.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 50,
        'max_pages_per_session': 20,
        'requires_cookies': False,
    },
    'duckduckgo': {
        'tls_profile': None,
        'api_type': 'search',
        'delay_min': 3.0,
        'delay_max': 8.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 30,
        'max_pages_per_session': 15,
        'requires_cookies': False,
    },
}


# ============================================================
# SECTION 5: SEARCH & DISCOVERY API CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class SerpAPIConfig:
    """
    Configuration for SerpAPI (230+ queries/month plan).

    Budget Allocation Strategy (230 searches/month ≈ 7-8/day):
        - Alumni/Network Discovery (A-09):  ~90/month (3/day)
        - Intent Signal Boosting (A-01):    ~60/month (2/day)
        - HR/Recruiter Discovery (A-09):    ~40/month (1-2/day)
        - Company Careers Page (A-04):      ~20/month (on-demand)
        - On-demand /research commands:     ~20/month (user-triggered)
        - Buffer:                           ~10/month (safety)

    Smart Budget Rules:
        - Weekdays get 8 searches/day, weekends get 5
        - Unused weekday budget does NOT roll over
        - Tier 1-2 companies get priority SerpAPI access
        - Tier 3+ companies use DDG dorks first, SerpAPI only if DDG fails
        - Track monthly usage in api_quotas table
    """
    api_key: str = ""
    base_url: str = "https://serpapi.com/search"
    monthly_limit: int = 230
    daily_budget_weekday: int = 8   # Mon-Fri: ~8 searches/day
    daily_budget_weekend: int = 5   # Sat-Sun: ~5 searches/day
    timeout_seconds: int = 30
    # Per-agent daily sub-budgets (must sum ≤ daily_budget_weekday)
    budget_network_mapper: int = 3    # A-09 alumni/HR discovery
    budget_intent_scanner: int = 2    # A-01 high-value signal search
    budget_ats_crawler: int = 1       # A-04 careers page discovery
    budget_on_demand: int = 2         # User /research, /network commands
    # Tier-based access control
    tier_auto_approve: int = 2        # Tier 1-2: auto-use SerpAPI
    tier_ddg_first: int = 5           # Tier 3-5: try DDG first
    # Allowed task types
    ALLOWED_TASKS: frozenset = frozenset({
        'alumni_discovery',
        'hr_poster_identification',
        'dark_channel_seed',
        'company_careers_page_discovery',
        'intent_signal_boost',
        'company_research',
        'hiring_verification',
    })


@dataclass(frozen=True)
class BingSearchConfig:
    """Configuration for Bing Search API (1000 free/month backup)."""
    api_key: str = ""
    endpoint: str = "https://api.bing.microsoft.com/v7.0/search"
    monthly_limit: int = 1000
    daily_budget: int = 33
    timeout_seconds: int = 15


@dataclass(frozen=True)
class DuckDuckGoConfig:
    """Configuration for DuckDuckGo search (unlimited, rate-limited)."""
    max_results_per_query: int = 20
    max_queries_per_hour: int = 30
    max_queries_per_day: int = 200
    delay_between_queries_min: float = 3.0
    delay_between_queries_max: float = 8.0
    timeout_seconds: int = 15
    region: str = "in-en"  # India English
    safesearch: str = "moderate"

    # Dork templates for various purposes
    DORK_TEMPLATES: dict = field(default_factory=lambda: {})

    def __post_init__(self):
        """Initialize dork templates after creation."""
        pass


# DuckDuckGo dork templates (defined separately to avoid dataclass issues)
DDG_DORK_TEMPLATES: Dict[str, str] = {
    'linkedin_jobs': 'site:linkedin.com/jobs "{query}" india intern',
    'linkedin_alumni': 'site:linkedin.com/in "{college}" "{company}" alumni',
    'linkedin_hr': 'site:linkedin.com/in "{company}" "talent acquisition" OR "HR" OR "recruiter" india',
    'company_hiring': '"{company}" hiring interns 2026 india',
    'company_mba_intern': '"{company}" MBA internship 2026',
    'naukri_jobs': 'site:naukri.com "{query}" intern MBA',
    'glassdoor_reviews': 'site:glassdoor.co.in "{company}" intern review',
    'news_hiring': '"{company}" hiring expansion india 2026',
    'funding_news': '"{company}" funding raised series india 2026',
    'careers_page': '"{company}" careers internship india site:{domain}',
}


# ============================================================
# SECTION 6: DATABASE CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class DatabaseConfig:
    """SQLite database configuration."""
    path: str = "data/firstmover.db"
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size: int = -8000  # 8MB cache
    foreign_keys: bool = True
    busy_timeout_ms: int = 5000
    mmap_size: int = 268435456  # 256MB memory-mapped I/O
    auto_vacuum: str = "INCREMENTAL"
    temp_store: str = "MEMORY"

    # Backup settings (for Render's ephemeral disk)
    backup_interval_hours: int = 6
    backup_to_kv: bool = True
    max_backups_kept: int = 5

    # Maintenance
    vacuum_interval_hours: int = 24
    analyze_interval_hours: int = 12
    checkpoint_interval_minutes: int = 30


# ============================================================
# SECTION 7: SCRAPING SOURCE CONFIGURATION
# ============================================================

class ScrapingSource(Enum):
    """All supported job scraping sources."""
    INTERNSHALA = "internshala"
    NAUKRI = "naukri"
    IIMJOBS = "iimjobs"
    LINKEDIN = "linkedin"
    GLASSDOOR = "glassdoor"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    WELLFOUND = "wellfound"
    INDEED = "indeed"
    TELEGRAM_DARK = "telegram_dark"
    TWITTER_X = "twitter_x"


class ScrapingPriority(IntEnum):
    """Source priority levels for scraping order."""
    P1_CRITICAL = 1     # Internshala, Naukri
    P2_IMPORTANT = 2    # LinkedIn, IIMjobs, Glassdoor
    P3_SUPPLEMENTARY = 3  # Greenhouse, Lever, Workday, Wellfound, Indeed
    P4_EXPLORATORY = 4   # Telegram/X dark channels


# Source metadata
SOURCE_CONFIG: Dict[str, Dict[str, Any]] = {
    'internshala': {
        'priority': ScrapingPriority.P1_CRITICAL,
        'daily_listings_estimate': (200, 400),
        'difficulty': 'easy',
        'method': 'mobile_api',
        'base_url': 'https://internshala.com/internships',
        'ajax_url': 'https://internshala.com/internships/ajax/search_ajax',
        'enabled': True,
    },
    'naukri': {
        'priority': ScrapingPriority.P1_CRITICAL,
        'daily_listings_estimate': (100, 200),
        'difficulty': 'medium',
        'method': 'mobile_api',
        'api_url': 'https://api.naukri.com',
        'base_url': 'https://www.naukri.com',
        'enabled': True,
    },
    'iimjobs': {
        'priority': ScrapingPriority.P2_IMPORTANT,
        'daily_listings_estimate': (30, 80),
        'difficulty': 'easy',
        'method': 'web_scraping',
        'base_url': 'https://www.iimjobs.com',
        'enabled': True,
    },
    'linkedin': {
        'priority': ScrapingPriority.P2_IMPORTANT,
        'daily_listings_estimate': (50, 150),
        'difficulty': 'hard',
        'method': 'ddg_dorks',
        'dork_prefix': 'site:linkedin.com/jobs',
        'enabled': True,
        'note': 'NEVER scrape LinkedIn directly. DDG dorks only.',
    },
    'glassdoor': {
        'priority': ScrapingPriority.P2_IMPORTANT,
        'daily_listings_estimate': (20, 60),
        'difficulty': 'medium',
        'method': 'web_scraping',
        'base_url': 'https://www.glassdoor.co.in',
        'enabled': True,
    },
    'greenhouse': {
        'priority': ScrapingPriority.P3_SUPPLEMENTARY,
        'daily_listings_estimate': (20, 40),
        'difficulty': 'easy',
        'method': 'rest_api',
        'api_base': 'https://boards-api.greenhouse.io/v1/boards',
        'enabled': True,
    },
    'lever': {
        'priority': ScrapingPriority.P3_SUPPLEMENTARY,
        'daily_listings_estimate': (15, 30),
        'difficulty': 'easy',
        'method': 'rest_api',
        'api_base': 'https://api.lever.co/v0/postings',
        'enabled': True,
    },
    'workday': {
        'priority': ScrapingPriority.P3_SUPPLEMENTARY,
        'daily_listings_estimate': (15, 30),
        'difficulty': 'medium',
        'method': 'web_scraping',
        'enabled': True,
    },
    'wellfound': {
        'priority': ScrapingPriority.P3_SUPPLEMENTARY,
        'daily_listings_estimate': (30, 50),
        'difficulty': 'easy',
        'method': 'graphql',
        'base_url': 'https://wellfound.com',
        'enabled': True,
    },
    'indeed': {
        'priority': ScrapingPriority.P3_SUPPLEMENTARY,
        'daily_listings_estimate': (40, 80),
        'difficulty': 'medium',
        'method': 'rss',
        'rss_base': 'https://www.indeed.co.in/rss',
        'enabled': True,
    },
    'telegram_dark': {
        'priority': ScrapingPriority.P4_EXPLORATORY,
        'daily_listings_estimate': (5, 30),
        'difficulty': 'easy',
        'method': 'telethon',
        'enabled': True,
    },
    'twitter_x': {
        'priority': ScrapingPriority.P4_EXPLORATORY,
        'daily_listings_estimate': (2, 15),
        'difficulty': 'easy',
        'method': 'api_v2',
        'enabled': True,
    },
}


# ============================================================
# SECTION 8: MBA CATEGORIES & COMPANY TIERS
# ============================================================

# 10 MBA internship categories for Internshala (and adapted for other sources)
MBA_CATEGORIES: List[str] = [
    'marketing',
    'finance',
    'business-development',
    'operations',
    'strategy',
    'consulting',
    'product-management',
    'human-resources',
    'supply-chain',
    'analytics',
]

# Extended keywords for each category (used for ATS, search dorks, filtering)
MBA_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    'marketing': [
        'marketing', 'brand management', 'digital marketing', 'social media',
        'content marketing', 'SEO', 'SEM', 'performance marketing', 'growth',
        'advertising', 'market research', 'brand strategy', 'consumer insights',
        'trade marketing', 'product marketing', 'GTM', 'go-to-market',
        'CRM', 'email marketing', 'influencer marketing', 'PR',
        'media planning', 'campaign management', 'marketing analytics',
    ],
    'finance': [
        'finance', 'financial analysis', 'investment banking', 'corporate finance',
        'equity research', 'financial modeling', 'valuation', 'M&A',
        'private equity', 'venture capital', 'portfolio management',
        'risk management', 'treasury', 'FP&A', 'financial planning',
        'credit analysis', 'asset management', 'wealth management',
        'accounting', 'audit', 'taxation', 'compliance', 'banking',
    ],
    'business-development': [
        'business development', 'BD', 'sales', 'partnerships', 'alliances',
        'revenue growth', 'client acquisition', 'account management',
        'strategic partnerships', 'channel sales', 'enterprise sales',
        'B2B', 'B2C', 'lead generation', 'market expansion',
        'new business', 'client relations', 'key accounts',
    ],
    'operations': [
        'operations', 'supply chain', 'logistics', 'procurement',
        'inventory management', 'warehouse', 'distribution', 'fulfillment',
        'process improvement', 'lean', 'six sigma', 'quality',
        'manufacturing', 'production', 'plant management', 'capacity planning',
        'operational excellence', 'process optimization', 'vendor management',
    ],
    'strategy': [
        'strategy', 'management consulting', 'business strategy',
        'corporate strategy', 'strategic planning', 'competitive analysis',
        'market entry', 'growth strategy', 'transformation',
        'due diligence', 'benchmarking', 'feasibility study',
        'business plan', 'strategic initiatives', 'org design',
    ],
    'consulting': [
        'consulting', 'management consulting', 'strategy consulting',
        'technology consulting', 'IT consulting', 'advisory',
        'implementation', 'change management', 'digital transformation',
        'process consulting', 'operations consulting', 'HR consulting',
        'risk advisory', 'forensic', 'compliance consulting',
    ],
    'product-management': [
        'product management', 'product manager', 'PM', 'APM',
        'product strategy', 'product development', 'product design',
        'user research', 'UX', 'UI', 'A/B testing', 'experimentation',
        'product analytics', 'feature prioritization', 'roadmap',
        'agile', 'scrum', 'sprint planning', 'PRD', 'user stories',
    ],
    'human-resources': [
        'human resources', 'HR', 'talent acquisition', 'recruitment',
        'HRBP', 'HR business partner', 'compensation', 'benefits',
        'employee engagement', 'learning & development', 'L&D',
        'organizational development', 'OD', 'performance management',
        'HRIS', 'HR analytics', 'people operations', 'culture',
    ],
    'supply-chain': [
        'supply chain', 'SCM', 'logistics', 'procurement', 'sourcing',
        'vendor management', 'inventory', 'demand planning',
        'supply planning', 'S&OP', 'warehouse management', 'WMS',
        'transportation', 'freight', 'last mile', 'distribution',
        'cold chain', 'reverse logistics', 'import export',
    ],
    'analytics': [
        'analytics', 'data analytics', 'business analytics', 'BI',
        'business intelligence', 'data science', 'machine learning',
        'statistical analysis', 'predictive analytics', 'data visualization',
        'Tableau', 'Power BI', 'SQL', 'Python', 'R', 'Excel',
        'data engineering', 'ETL', 'reporting', 'dashboards',
        'customer analytics', 'web analytics', 'marketing analytics',
    ],
}


class CompanyTier(IntEnum):
    """Company tier classification for PPO scoring."""
    ELITE = 1           # McKinsey, BCG, Goldman, Google, etc.
    STRONG_MNC = 2      # Big 4, TCS, Siemens, Asian Paints, etc.
    INDIAN_UNICORN = 3  # Zepto, CRED, Razorpay, Swiggy, etc.
    GROWING_STARTUP = 4 # Series B/C startups
    NICHE_SECTOR = 5    # PE/VC, boutique consulting


# Tier scoring for PPO formula
TIER_PPO_SCORES: Dict[int, int] = {
    CompanyTier.ELITE: 100,
    CompanyTier.STRONG_MNC: 80,
    CompanyTier.INDIAN_UNICORN: 60,
    CompanyTier.GROWING_STARTUP: 40,
    CompanyTier.NICHE_SECTOR: 20,
}

# Default tier for unknown companies
DEFAULT_TIER_SCORE: int = 30

# Company size bands
COMPANY_SIZE_BANDS: Dict[str, Tuple[int, int]] = {
    'startup': (1, 50),
    'small': (51, 200),
    'mid': (201, 1000),
    'large': (1001, 10000),
    'enterprise': (10001, 1000000),
}

# Sector classifications
COMPANY_SECTORS: List[str] = [
    'Technology', 'FMCG', 'Banking & Finance', 'Consulting',
    'E-Commerce', 'Healthcare', 'Manufacturing', 'Energy',
    'Automotive', 'Telecom', 'Media & Entertainment', 'Education',
    'Real Estate', 'Insurance', 'Agriculture', 'Logistics',
    'Retail', 'Pharma', 'Chemical', 'Infrastructure',
    'Fintech', 'Edtech', 'Healthtech', 'SaaS', 'D2C',
    'AI/ML', 'Cybersecurity', 'Blockchain', 'Gaming',
    'Travel & Hospitality', 'Food & Beverage', 'Fashion',
    'PE/VC', 'Investment Banking', 'Boutique Consulting',
]


# ============================================================
# SECTION 9: RATE LIMIT CONFIGURATION
# ============================================================

@dataclass
class RateLimitConfig:
    """
    Centralized rate limit configuration for all external services.
    These limits are HARD CAPS — never exceed them.
    """
    # AI Providers
    groq_daily_limit: int = 14400
    groq_per_minute: int = 30
    groq_per_hour: int = 500
    cerebras_daily_limit: int = 100000
    cerebras_per_minute: int = 60
    cerebras_per_hour: int = 2000

    # Cloudflare
    cf_worker_daily_limit: int = 100000
    cf_kv_daily_reads: int = 100000
    cf_kv_daily_writes: int = 1000

    # Search APIs
    serpapi_monthly_limit: int = 230
    serpapi_daily_budget_weekday: int = 8
    serpapi_daily_budget_weekend: int = 5
    bing_monthly_limit: int = 1000
    bing_daily_budget: int = 33
    ddg_per_hour: int = 30
    ddg_per_day: int = 200

    # Telegram
    tg_messages_per_minute: int = 20
    tg_messages_per_second: int = 1

    # Twitter/X
    x_tweets_per_15min: int = 180  # Free tier
    x_daily_limit: int = 500

    # Scraping per-site (requests/hour)
    internshala_per_hour: int = 50
    naukri_per_hour: int = 30
    iimjobs_per_hour: int = 40
    glassdoor_per_hour: int = 20
    greenhouse_per_hour: int = 100
    lever_per_hour: int = 100
    workday_per_hour: int = 40
    wellfound_per_hour: int = 40
    indeed_per_hour: int = 30

    # Safety margins (% of limit to use)
    safety_margin: float = 0.85  # Use at most 85% of any limit

    def get_safe_limit(self, limit: int) -> int:
        """Return the safe limit accounting for safety margin."""
        return int(limit * self.safety_margin)


# ============================================================
# SECTION 10: PPO SCORING WEIGHTS
# ============================================================

@dataclass
class PPOWeights:
    """
    10-variable PPO (Probability of Positive Outcome) scoring weights.
    These are the DEFAULT weights used until A-11 retrains them.
    Weights MUST sum to 1.0.
    """
    has_ppo_tag: float = 0.20
    company_tier_score: float = 0.18
    low_applicant_bonus: float = 0.15
    stipend_normalized: float = 0.08
    duration_fit: float = 0.05
    cirs_score: float = 0.12
    sector_momentum: float = 0.07
    intent_signal: float = 0.08
    historic_callback: float = 0.05
    recency_bonus: float = 0.02

    def validate(self) -> bool:
        """Verify weights sum to 1.0 (within floating point tolerance)."""
        total = (
            self.has_ppo_tag + self.company_tier_score +
            self.low_applicant_bonus + self.stipend_normalized +
            self.duration_fit + self.cirs_score +
            self.sector_momentum + self.intent_signal +
            self.historic_callback + self.recency_bonus
        )
        return abs(total - 1.0) < 0.001

    def to_list(self) -> List[float]:
        """Return weights as ordered list for vector operations."""
        return [
            self.has_ppo_tag, self.company_tier_score,
            self.low_applicant_bonus, self.stipend_normalized,
            self.duration_fit, self.cirs_score,
            self.sector_momentum, self.intent_signal,
            self.historic_callback, self.recency_bonus,
        ]

    def to_dict(self) -> Dict[str, float]:
        """Return weights as dictionary."""
        return {
            'has_ppo_tag': self.has_ppo_tag,
            'company_tier_score': self.company_tier_score,
            'low_applicant_bonus': self.low_applicant_bonus,
            'stipend_normalized': self.stipend_normalized,
            'duration_fit': self.duration_fit,
            'cirs_score': self.cirs_score,
            'sector_momentum': self.sector_momentum,
            'intent_signal': self.intent_signal,
            'historic_callback': self.historic_callback,
            'recency_bonus': self.recency_bonus,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> 'PPOWeights':
        """Create PPOWeights from a dictionary (e.g., from A-11 retrain)."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


# PPO variable computation parameters
PPO_PARAMS: Dict[str, Any] = {
    # v3: low_applicant_bonus
    'applicant_decay_rate': 0.2,  # 100 - (applicants × 0.2)
    # v4: stipend_normalized
    'category_median_stipends': {
        'marketing': 10000,
        'finance': 15000,
        'business-development': 10000,
        'operations': 10000,
        'strategy': 20000,
        'consulting': 20000,
        'product-management': 15000,
        'human-resources': 8000,
        'supply-chain': 10000,
        'analytics': 15000,
    },
    # v5: duration_fit
    'ideal_duration_range': (2, 6),  # months
    'short_duration_score': 70,  # 1 month
    'long_duration_score': 50,   # >6 months
    # v9: historic_callback
    'min_outcomes_for_historic': 20,
    'default_callback_score': 50,
    # v10: recency_bonus
    'recency_decay_per_day': 15,  # -15 points per day
}


# ============================================================
# SECTION 11: GHOST DETECTION THRESHOLDS
# ============================================================

@dataclass(frozen=True)
class GhostDetectionConfig:
    """
    5-signal ghost job detection thresholds.
    Ghost Score is the sum of all 5 signal scores (0-100).
    """
    # Signal 1: Listing Age
    age_high_threshold_days: int = 30  # +25 points
    age_high_score: int = 25
    age_medium_threshold_days: int = 20  # +15 points
    age_medium_score: int = 15
    age_low_threshold_days: int = 10  # +8 points
    age_low_score: int = 8

    # Signal 2: Applicant Overload
    applicant_high_threshold: int = 500  # +20 points
    applicant_high_score: int = 20
    applicant_medium_threshold: int = 300  # +12 points
    applicant_medium_score: int = 12
    applicant_low_threshold: int = 200  # +5 points
    applicant_low_score: int = 5

    # Signal 3: Repetitive Posting
    repeat_high_count: int = 3  # +20 points (3+ times)
    repeat_high_score: int = 20
    repeat_medium_count: int = 2  # +10 points (2 times)
    repeat_medium_score: int = 10
    repeat_lookback_days: int = 90  # Look back 3 months

    # Signal 4: No HR Response Signal
    no_signal_days: int = 30  # +15 points (0 signals in 30d)
    no_signal_score: int = 15
    weak_signal_threshold: int = 3  # +8 points (<3 signals)
    weak_signal_score: int = 8

    # Signal 5: ATS Mismatch
    ats_mismatch_score: int = 20  # Listing NOT on ATS
    ats_unknown_score: int = 5  # ATS platform unknown

    # Classification thresholds
    ghost_threshold: int = 60   # ≥60 = GHOST
    suspicious_threshold: int = 40  # 40-59 = SUSPICIOUS
    # <40 = CLEAN


# ============================================================
# SECTION 12: BLUE OCEAN CRITERIA
# ============================================================

@dataclass(frozen=True)
class BlueOceanConfig:
    """
    Blue Ocean = High prestige, low competition listings.
    These are the PRIORITY opportunities to apply to.
    """
    min_prestige_score: int = 60   # Company tier ≥ 60 (Tier 1 or 2)
    max_applicant_count: int = 35  # Applicants ≤ 35
    min_stipend: int = 5000        # At least ₹5,000/month
    max_days_posted: int = 7       # Posted within last 7 days
    include_ppo_only: bool = False  # Don't require PPO tag
    alert_immediately: bool = True  # Send Telegram alert instantly
    max_alerts_per_day: int = 15    # Don't spam


# ============================================================
# SECTION 13: CIRS CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class CIRSConfig:
    """
    CIRS (Company Intern Readiness Score) configuration.
    Measures how likely a company is to actually hire and convert interns.
    """
    default_score: float = 40.0
    min_score: float = 0.0
    max_score: float = 100.0

    # Component weights
    intent_signal_weight: float = 0.30
    historical_ppo_weight: float = 0.25
    glassdoor_rating_weight: float = 0.15
    funding_recency_weight: float = 0.15
    linkedin_posting_weight: float = 0.15

    # Decay
    signal_decay_per_day: float = 2.0  # -2 points/day without new signal
    min_signals_for_update: int = 1

    # Funding recency scoring
    funding_recent_days: int = 180  # Within 6 months = full score
    funding_stale_days: int = 365  # Over 1 year = minimal score


# ============================================================
# SECTION 14: SCHEDULING CONFIGURATION
# ============================================================

# IST Timezone
IST = timezone(timedelta(hours=5, minutes=30))

@dataclass(frozen=True)
class ScheduleEntry:
    """A single scheduled agent task."""
    agent_id: str
    agent_name: str
    hour: int
    minute: int
    task_description: str
    estimated_duration_minutes: int
    day_of_week: str = "mon-sat"  # mon-sat, sun, daily
    enabled: bool = True
    priority: int = 1  # Lower = higher priority
    depends_on: Optional[str] = None  # Agent that must complete first


# Complete 24-hour schedule (IST)
DAILY_SCHEDULE: List[ScheduleEntry] = [
    ScheduleEntry(
        agent_id="A-03", agent_name="Primary Scraper",
        hour=5, minute=30,
        task_description="Internshala full scrape (10 categories)",
        estimated_duration_minutes=45,
        day_of_week="daily", priority=1,
    ),
    ScheduleEntry(
        agent_id="A-06", agent_name="Dedup Engine",
        hour=6, minute=0,
        task_description="Dedup engine on overnight batch",
        estimated_duration_minutes=15,
        day_of_week="daily", priority=2,
        depends_on="A-03",
    ),
    ScheduleEntry(
        agent_id="A-05", agent_name="Ghost Detector",
        hour=6, minute=15,
        task_description="Ghost scoring (Cerebras)",
        estimated_duration_minutes=20,
        day_of_week="daily", priority=3,
        depends_on="A-06",
    ),
    ScheduleEntry(
        agent_id="A-07", agent_name="Intelligence Enricher",
        hour=6, minute=30,
        task_description="Intelligence enrichment + Blue Ocean flagging",
        estimated_duration_minutes=15,
        day_of_week="daily", priority=4,
        depends_on="A-05",
    ),
    ScheduleEntry(
        agent_id="A-08", agent_name="PPO Optimizer",
        hour=7, minute=0,
        task_description="PPO model runs -> top 25 shortlist",
        estimated_duration_minutes=10,
        day_of_week="daily", priority=5,
        depends_on="A-07",
    ),
    ScheduleEntry(
        agent_id="A-12", agent_name="Telegram Reporter",
        hour=7, minute=15,
        task_description="MORNING BRIEF -> Telegram",
        estimated_duration_minutes=1,
        day_of_week="daily", priority=6,
        depends_on="A-08",
    ),
    ScheduleEntry(
        agent_id="A-01", agent_name="Intent Scanner",
        hour=9, minute=0,
        task_description="Intent signal scan (Tier 1+2 companies)",
        estimated_duration_minutes=30,
        day_of_week="daily", priority=7,
    ),
    ScheduleEntry(
        agent_id="A-03", agent_name="Primary Scraper",
        hour=12, minute=0,
        task_description="Naukri + IIMjobs scrape",
        estimated_duration_minutes=30,
        day_of_week="daily", priority=8,
    ),
    ScheduleEntry(
        agent_id="A-04", agent_name="ATS Crawler",
        hour=14, minute=0,
        task_description="Company ATS pages (Greenhouse/Lever/Workday)",
        estimated_duration_minutes=45,
        day_of_week="daily", priority=9,
    ),
    ScheduleEntry(
        agent_id="A-01", agent_name="Intent Scanner",
        hour=16, minute=0,
        task_description="Second intent scan (RSS + LinkedIn HR via DDG)",
        estimated_duration_minutes=30,
        day_of_week="daily", priority=10,
    ),
    ScheduleEntry(
        agent_id="A-06", agent_name="Dedup Engine",
        hour=18, minute=0,
        task_description="Afternoon batch dedup + enrichment",
        estimated_duration_minutes=20,
        day_of_week="daily", priority=11,
    ),
    ScheduleEntry(
        agent_id="A-07", agent_name="Intelligence Enricher",
        hour=18, minute=20,
        task_description="Afternoon enrichment pass",
        estimated_duration_minutes=15,
        day_of_week="daily", priority=12,
        depends_on="A-06",
    ),
    ScheduleEntry(
        agent_id="A-02", agent_name="Dark Channel Listener",
        hour=20, minute=0,
        task_description="Telegram dark channel batch check",
        estimated_duration_minutes=15,
        day_of_week="daily", priority=13,
    ),
    ScheduleEntry(
        agent_id="A-12", agent_name="Telegram Reporter",
        hour=22, minute=0,
        task_description="EVENING SUMMARY -> Telegram",
        estimated_duration_minutes=1,
        day_of_week="daily", priority=14,
    ),
    ScheduleEntry(
        agent_id="A-04", agent_name="ATS Crawler",
        hour=23, minute=0,
        task_description="Nightly company career page crawl (300 companies)",
        estimated_duration_minutes=60,
        day_of_week="daily", priority=15,
    ),
    ScheduleEntry(
        agent_id="A-11", agent_name="Outcome Learner",
        hour=21, minute=0,
        task_description="Weekly outcome learner / retrain PPO weights",
        estimated_duration_minutes=10,
        day_of_week="sun", priority=16,
    ),
]


# ============================================================
# SECTION 15: USER-AGENT POOL (20+ Agents)
# ============================================================

USER_AGENT_POOL: List[str] = [
    # Chrome Desktop (Windows)
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    # Chrome Desktop (Mac)
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    # Safari Desktop (Mac)
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15',
    # Firefox Desktop
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:121.0) Gecko/20100101 Firefox/121.0',
    # Edge Desktop
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    # Chrome Mobile (Android)
    'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; OnePlus 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    # Safari Mobile (iOS)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    # Chrome Mobile (iOS)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1',
]

# Mobile-only user agents (for Internshala/Naukri mobile APIs)
MOBILE_USER_AGENTS: List[str] = [ua for ua in USER_AGENT_POOL if 'Mobile' in ua]

# Desktop-only user agents
DESKTOP_USER_AGENTS: List[str] = [ua for ua in USER_AGENT_POOL if 'Mobile' not in ua]


# ============================================================
# SECTION 16: TLS FINGERPRINT PROFILES
# ============================================================

TLS_IMPERSONATION_PROFILES: List[str] = [
    'chrome120',
    'chrome119',
    'chrome124',
    'firefox121',
    'safari17_0',
]

# Profile rotation weights (some are more common than others)
TLS_PROFILE_WEIGHTS: Dict[str, float] = {
    'chrome120': 0.35,
    'chrome119': 0.20,
    'chrome124': 0.20,
    'firefox121': 0.15,
    'safari17_0': 0.10,
}


# ============================================================
# SECTION 17: LOGGING CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class LoggingConfig:
    """Logging configuration for all components."""
    level: str = "INFO"
    format_string: str = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
    rotation: str = "10 MB"
    retention: str = "7 days"
    compression: str = "zip"
    log_dir: str = "logs"
    main_log: str = "logs/firstmover.log"
    agent_log_prefix: str = "logs/agent_"
    error_log: str = "logs/errors.log"
    scraping_log: str = "logs/scraping.log"
    ai_log: str = "logs/ai_calls.log"
    telegram_log: str = "logs/telegram.log"
    enable_stdout: bool = True
    enable_file: bool = True
    serialize_json: bool = False  # JSON log format


# ============================================================
# SECTION 18: RENDER DEPLOYMENT SETTINGS
# ============================================================

@dataclass(frozen=True)
class RenderConfig:
    """Render free tier deployment configuration."""
    is_render: bool = False
    ram_limit_mb: int = 512
    spin_down_minutes: int = 15
    keep_alive_interval_sec: int = 600  # Ping every 10 minutes
    use_webhook: bool = False  # Use polling on Render free tier
    ephemeral_disk: bool = True
    max_concurrent_agents: int = 3  # Memory constraint
    lazy_load_models: bool = True  # Don't load sentence-transformers at startup
    batch_size_limit: int = 50  # Smaller batches for memory


# ============================================================
# SECTION 19: TELEGRAM DARK CHANNEL CONFIGURATION
# ============================================================

# Known MBA job-related Telegram channels/groups to monitor
TELEGRAM_DARK_CHANNELS: List[Dict[str, str]] = [
    # These should be configured by the user
    # Example format:
    # {'name': 'MBA Jobs India', 'username': '@mbajobsindia', 'type': 'channel'},
    # {'name': 'Internship Alerts', 'username': '@internshipalerts', 'type': 'group'},
]

# X/Twitter search queries for dark channel monitoring
TWITTER_SEARCH_QUERIES: List[str] = [
    '"MBA intern" OR "MBA internship" india hiring',
    '"summer intern" marketing OR finance OR strategy india',
    '#MBAintern #india',
    '"internship opening" MBA india 2026',
    'hiring interns MBA india stipend',
]

# Keywords that indicate a job posting in dark channels
DARK_CHANNEL_JOB_KEYWORDS: List[str] = [
    'hiring', 'intern', 'internship', 'opening', 'position',
    'vacancy', 'opportunity', 'role', 'looking for', 'we are hiring',
    'join us', 'apply now', 'stipend', 'WFH', 'remote',
    'MBA', 'business', 'marketing', 'finance', 'strategy',
    'consulting', 'operations', 'analytics', 'product',
]


# ============================================================
# SECTION 20: ECONOMIC SIGNAL SOURCES
# ============================================================

ECONOMIC_SIGNAL_SOURCES: Dict[str, Dict[str, str]] = {
    'rbi_monetary_policy': {
        'url': 'https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx',
        'type': 'rss',
        'relevance': 'Banking & Finance sector momentum',
    },
    'inc42_funding': {
        'url': 'https://inc42.com/feed/',
        'type': 'rss',
        'relevance': 'Startup funding signals',
    },
    'economic_times_companies': {
        'url': 'https://economictimes.indiatimes.com/rssfeedstopstories.cms',
        'type': 'rss',
        'relevance': 'Corporate hiring/expansion news',
    },
    'moneycontrol_news': {
        'url': 'https://www.moneycontrol.com/rss/latestnews.xml',
        'type': 'rss',
        'relevance': 'Market and corporate news',
    },
    'livemint_companies': {
        'url': 'https://www.livemint.com/rss/companies',
        'type': 'rss',
        'relevance': 'Company expansion and hiring',
    },
    'yourstory_funding': {
        'url': 'https://yourstory.com/feed',
        'type': 'rss',
        'relevance': 'Startup ecosystem signals',
    },
    'vccircle_deals': {
        'url': 'https://www.vccircle.com/feed/',
        'type': 'rss',
        'relevance': 'PE/VC deal flow and portfolio hiring',
    },
}

# Google News RSS for company-specific monitoring
GOOGLE_NEWS_RSS_TEMPLATE: str = (
    "https://news.google.com/rss/search?q={query}+india+hiring&hl=en-IN&gl=IN&ceid=IN:en"
)


# ============================================================
# MASTER CONFIGURATION CLASS
# ============================================================

class Config:
    """
    Master configuration class that assembles all sub-configurations.
    This is the SINGLE entry point for all configuration access.

    Usage:
        config = Config()
        groq_key = config.groq.api_key
        cerebras_model = config.cerebras.model
        telegram_token = config.telegram.bot_token
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern — only one Config instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize all configuration sub-components."""
        if self._initialized:
            return
        self._initialized = True
        self._load_all()

    def _load_all(self):
        """Load all configuration from environment variables."""
        # Determine environment
        self.environment = _get_env(
            'ENVIRONMENT', default='production',
            description='Deployment environment'
        )
        self.is_render = bool(
            _get_env('RENDER_DEPLOY', default='false', cast_type=bool,
                     description='Running on Render platform')
            or _get_env('RENDER', default='', description='Render env flag')
        )
        self.is_docker = _get_env(
            'DOCKER_DEPLOY', default='false', cast_type=bool,
            description='Running in Docker'
        )

        # AI Providers
        self.groq = GroqConfig(
            api_key=_get_env(
                'GROQ_API_KEY', default='',
                description='Groq API key for llama-3.3-70b-versatile'
            ),
        )
        self.cerebras = CerebrasConfig(
            api_key=_get_env(
                'CEREBRAS_API_KEY', default='',
                description='Cerebras API key for llama-3.3-70b'
            ),
        )

        # AI Provider runtime status
        self.groq_status = AIProviderStatus(provider='groq')
        self.cerebras_status = AIProviderStatus(provider='cerebras')

        # Telegram
        self.telegram = TelegramBotConfig(
            bot_token=_get_env(
                'TG_BOT_TOKEN', default='',
                description='Telegram bot token'
            ),
            chat_id=_get_env(
                'TG_CHAT_ID', default='',
                description='Telegram chat ID for reports'
            ),
        )
        self.telethon = TelethonConfig(
            api_id=_get_env(
                'TG_API_ID', default='',
                description='Telegram API ID for Telethon'
            ),
            api_hash=_get_env(
                'TG_API_HASH', default='',
                description='Telegram API hash for Telethon'
            ),
        )

        # Proxy & Stealth
        self.webshare = WebshareConfig(
            api_key=_get_env(
                'WEBSHARE_KEY', default='',
                description='Webshare proxy API key'
            ),
        )
        self.cloudflare_relay = CloudflareRelayConfig(
            worker_url=_get_env(
                'CF_WORKER_URL', default='',
                description='Cloudflare Worker relay URL'
            ),
            relay_secret=_get_env(
                'CF_RELAY_SECRET', default='',
                description='Cloudflare Worker relay secret'
            ),
        )
        self.tor = TorConfig(
            enabled=_get_env(
                'TOR_ENABLED', default='false', cast_type=bool,
                description='Enable Tor proxy'
            ),
        )
        self.free_proxy = FreeProxyConfig()
        self.stealth_timing = StealthTimingConfig()

        # Search & Discovery
        self.serpapi = SerpAPIConfig(
            api_key=_get_env(
                'SERP_API_KEY', default='',
                description='SerpAPI key (230+/month plan)'
            ),
        )
        self.bing = BingSearchConfig(
            api_key=_get_env(
                'BING_API_KEY', default='',
                description='Bing Search API key'
            ),
        )
        self.ddg = DuckDuckGoConfig()

        # Twitter/X
        self.x_bearer_token = _get_env(
            'X_BEARER_TOKEN', default='',
            description='X/Twitter Bearer Token'
        )

        # Database
        db_path = _get_env(
            'DATABASE_PATH', default='data/firstmover.db',
            description='SQLite database file path'
        )
        self.database = DatabaseConfig(path=db_path)

        # Rate Limits
        self.rate_limits = RateLimitConfig()

        # PPO Scoring
        self.ppo_weights = PPOWeights()
        assert self.ppo_weights.validate(), "PPO weights must sum to 1.0!"

        # Ghost Detection
        self.ghost = GhostDetectionConfig()

        # Blue Ocean
        self.blue_ocean = BlueOceanConfig()

        # CIRS
        self.cirs = CIRSConfig()

        # Logging
        log_level = _get_env('LOG_LEVEL', default='INFO')
        self.logging = LoggingConfig(level=log_level)

        # Render
        self.render = RenderConfig(is_render=self.is_render)

        # Timezone
        self.timezone_name = _get_env('TIMEZONE', default='Asia/Kolkata')
        self.ist = IST

    def validate_critical(self) -> Dict[str, bool]:
        """
        Validate that critical configuration values are present.
        Returns a dict of {config_name: is_valid}.
        """
        checks = {
            'groq_api_key': bool(self.groq.api_key),
            'cerebras_api_key': bool(self.cerebras.api_key),
            'telegram_bot_token': bool(self.telegram.bot_token),
            'telegram_chat_id': bool(self.telegram.chat_id),
            'ppo_weights_valid': self.ppo_weights.validate(),
        }
        return checks

    def validate_optional(self) -> Dict[str, bool]:
        """Validate optional but recommended configuration."""
        checks = {
            'serpapi_key': bool(self.serpapi.api_key),
            'webshare_key': bool(self.webshare.api_key),
            'cf_worker_url': bool(self.cloudflare_relay.worker_url),
            'cf_relay_secret': bool(self.cloudflare_relay.relay_secret),
            'telethon_api_id': bool(self.telethon.api_id),
            'telethon_api_hash': bool(self.telethon.api_hash),
            'x_bearer_token': bool(self.x_bearer_token),
            'bing_api_key': bool(self.bing.api_key),
        }
        return checks

    def get_health_report(self) -> Dict[str, Any]:
        """Generate a comprehensive configuration health report."""
        critical = self.validate_critical()
        optional = self.validate_optional()
        return {
            'environment': self.environment,
            'is_render': self.is_render,
            'critical_config': critical,
            'all_critical_ok': all(critical.values()),
            'optional_config': optional,
            'optional_configured': sum(1 for v in optional.values() if v),
            'optional_total': len(optional),
            'ppo_weights': self.ppo_weights.to_dict(),
            'database_path': self.database.path,
            'log_level': self.logging.level,
            'mba_categories': len(MBA_CATEGORIES),
            'schedule_entries': len(DAILY_SCHEDULE),
            'user_agents': len(USER_AGENT_POOL),
            'tls_profiles': len(TLS_IMPERSONATION_PROFILES),
            'economic_sources': len(ECONOMIC_SIGNAL_SOURCES),
            'scraping_sources': len(SOURCE_CONFIG),
        }

    def __repr__(self) -> str:
        health = self.get_health_report()
        return (
            f"Config(env={health['environment']}, "
            f"render={health['is_render']}, "
            f"critical_ok={health['all_critical_ok']}, "
            f"optional={health['optional_configured']}/{health['optional_total']})"
        )


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

def get_config() -> Config:
    """Get the singleton Config instance."""
    return Config()


# Pre-initialize on import (optional — can be lazy)
# config = get_config()


if __name__ == "__main__":
    """Test configuration loading."""
    cfg = get_config()
    print("=" * 60)
    print("OPERATION FIRST MOVER v5 — Configuration Report")
    print("=" * 60)

    health = cfg.get_health_report()
    for key, value in health.items():
        if isinstance(value, dict):
            print(f"\n{key}:")
            for k, v in value.items():
                status = "✅" if v else "❌"
                print(f"  {status} {k}: {v}")
        else:
            print(f"  {key}: {value}")

    print(f"\n{cfg}")
    print("=" * 60)
