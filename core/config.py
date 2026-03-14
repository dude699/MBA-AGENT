"""
============================================================
OPERATION FIRST MOVER v8.0 -- MASTER CONFIGURATION MODULE
============================================================
THE DEFINITIVE FINAL BLUEPRINT -- Zero-cost, Ban-Free, Self-Learning

Architecture:
    - 5 AI Providers (Groq, Cerebras, Mistral, OpenRouter, HuggingFace)
    - 2 Fallbacks per agent via Agent Fallback Matrix
    - LinkedIn + Naukri Primary portals
    - 3x Weekly Scraping (Tue/Thu/Sat)
    - 6-Layer Keep-Alive Architecture
    - MBA-only filtering: Marketing, Finance, Strategy, Consulting,
      Operations, Product Management, HR, Supply Chain, Analytics
    - STRICT EXCLUSION: Sales, Business Development, BDE, SDR,
      Account Executive, Revenue, Cold Calling, Lead Gen, Outbound

Environment Variables Required (from Render):
    GROQ_API_KEY, CEREBRAS_API_KEY, CF_RELAY_SECRET, CF_WORKER_URL,
    SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY,
    TG_BOT_TOKEN, TG_CHAT_ID, ADMIN_TELEGRAM_ID, SERP_API_KEY,
    WEBSHARE_KEY, SCRAPERAPI_KEY, SCRAPEDO_TOKEN, SCRAPINGBEE_KEY
============================================================
"""

import os
import sys
import json
import hashlib
import logging
import random
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any, Union, FrozenSet
from enum import Enum, IntEnum

# ---------------------------------------------------------------------------
# Third-party imports (graceful fallback)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
    """Retrieve an environment variable as a list of strings."""
    raw = os.environ.get(key)
    if raw is None:
        return default or []
    return [item.strip() for item in raw.split(separator) if item.strip()]


# ============================================================
# SECTION 2: IST TIMEZONE
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


# ============================================================
# SECTION 3: AI PROVIDER CONFIGURATIONS (5 Providers)
# ============================================================

@dataclass(frozen=True)
class GroqConfig:
    """Groq AI provider -- Primary for heavy reasoning tasks.
    Free tier: 30 RPM, 14400 req/day, llama-3.3-70b-versatile."""
    api_key: str = ""
    model: str = "llama-3.3-70b-versatile"
    fallback_model: str = "llama-3.1-8b-instant"
    base_url: str = "https://api.groq.com/openai/v1"
    max_tokens_default: int = 800
    max_tokens_cover_letter: int = 1200
    max_tokens_ats_simulation: int = 1500
    max_tokens_jd_analysis: int = 1200
    max_tokens_company_research: int = 2000
    max_tokens_outreach_draft: int = 800
    max_tokens_resume_tweaks: int = 1000
    max_tokens_report_compile: int = 2500
    max_tokens_question_answer: int = 500
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

    TASKS: FrozenSet[str] = frozenset({
        'cover_letter', 'ats_simulation', 'resume_tweaks',
        'jd_analysis', 'outreach_draft', 'company_research',
        'report_compile', 'economic_analysis', 'package_generate',
        'network_outreach', 'deep_analysis', 'question_answer',
        'interview_prep', 'star_framework', 'negotiation_script',
        'cover_letter_cache', 'alumni_outreach', 'reengagement',
    })


@dataclass(frozen=True)
class CerebrasConfig:
    """Cerebras AI provider -- Primary for fast classification.
    Free tier: 1M tokens/day, 60 RPM, llama3.1-8b."""
    api_key: str = ""
    model: str = "llama3.1-8b"
    fallback_model: str = "llama3.1-8b"
    base_url: str = "https://api.cerebras.ai/v1"
    max_tokens_default: int = 500
    max_tokens_classify: int = 200
    max_tokens_extract: int = 600
    max_tokens_score: int = 300
    max_tokens_parse: int = 800
    max_tokens_tag: int = 200
    max_tokens_filter: int = 300
    daily_token_limit: int = 1000000
    daily_request_limit: int = 100000
    requests_per_minute: int = 60
    requests_per_hour: int = 2000
    temperature_default: float = 0.1
    temperature_classify: float = 0.0
    retry_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 15.0
    timeout_seconds: int = 30

    TASKS: FrozenSet[str] = frozenset({
        'ghost_classify', 'intent_classify', 'extract_basics',
        'dedup_score', 'portal_parse', 'sector_tag',
        'quick_classify', 'listing_quality_score', 'salary_benchmark',
        'duplicate_semantic', 'anomaly_detect', 'enrichment_priority',
        'mba_relevance_filter', 'sales_exclusion_check',
        'ppo_eligibility_check', 'question_match',
    })


@dataclass(frozen=True)
class MistralConfig:
    """Mistral AI provider -- Fallback #1 for reasoning.
    Experiment plan: Limited free usage."""
    api_key: str = ""
    model: str = "mistral-small-latest"
    base_url: str = "https://api.mistral.ai/v1"
    max_tokens_default: int = 800
    daily_request_limit: int = 1000
    requests_per_minute: int = 10
    temperature_default: float = 0.3
    timeout_seconds: int = 60
    retry_attempts: int = 2


@dataclass(frozen=True)
class OpenRouterConfig:
    """OpenRouter AI provider -- Fallback #2 for reasoning.
    50 req/day for Gemini 2.0 Flash free."""
    api_key: str = ""
    model: str = "google/gemini-2.0-flash-exp:free"
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens_default: int = 800
    daily_request_limit: int = 50
    requests_per_minute: int = 5
    temperature_default: float = 0.3
    timeout_seconds: int = 60
    retry_attempts: int = 2


@dataclass(frozen=True)
class HuggingFaceConfig:
    """HuggingFace Inference API -- Emergency fallback.
    Free tier: Rate limited but functional."""
    api_key: str = ""
    model: str = "mistralai/Mistral-7B-Instruct-v0.2"
    base_url: str = "https://api-inference.huggingface.co/models"
    max_tokens_default: int = 500
    daily_request_limit: int = 300
    timeout_seconds: int = 120
    retry_attempts: int = 2


# ============================================================
# SECTION 4: AGENT FALLBACK MATRIX
# ============================================================

# Each agent has a primary AI provider and 2 fallbacks
# Format: {agent_id: [primary, fallback_1, fallback_2]}
AGENT_FALLBACK_MATRIX: Dict[str, List[str]] = {
    # Scraping & Parsing Agents (fast, use Cerebras primary)
    'A-01': ['cerebras', 'groq', 'mistral'],      # Intent Scanner
    'A-02': ['cerebras', 'groq', 'openrouter'],    # Dark Channel Listener
    'A-03': ['cerebras', 'groq', 'huggingface'],   # Primary Scraper Parser
    'A-04': ['cerebras', 'groq', 'mistral'],       # ATS Crawler Parser

    # Analysis Agents (heavy reasoning, use Groq primary)
    'A-05': ['cerebras', 'groq', 'mistral'],       # Ghost Detector
    'A-06': ['cerebras', 'groq', 'openrouter'],    # Dedup Engine
    'A-07': ['groq', 'mistral', 'openrouter'],     # Intelligence Enricher
    'A-08': ['groq', 'cerebras', 'mistral'],       # PPO Optimizer

    # Network & Learning Agents
    'A-09': ['groq', 'mistral', 'openrouter'],     # Network Mapper
    'A-10': ['groq', 'cerebras', 'mistral'],       # ATS Simulator
    'A-11': ['cerebras', 'groq', 'mistral'],       # Outcome Learner

    # Communication Agents
    'A-12': ['groq', 'cerebras', 'mistral'],       # Telegram Reporter
    'A-13': ['groq', 'mistral', 'openrouter'],     # Auto Apply
    'A-14': ['groq', 'cerebras', 'mistral'],       # Multi-Model Router
}


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

    def record_success(self):
        """Record a successful API call."""
        self.total_requests_today += 1
        self.requests_this_hour += 1
        self.requests_this_minute += 1
        self.last_request_time = now_ist()
        self.consecutive_errors = 0
        self.is_healthy = True

    def record_error(self, message: str):
        """Record a failed API call."""
        self.errors_today += 1
        self.consecutive_errors += 1
        self.last_error_time = now_ist()
        self.last_error_message = message
        if self.consecutive_errors >= 5:
            self.is_healthy = False

    def record_rate_limit(self):
        """Record a rate limit hit."""
        self.rate_limited_count += 1
        self.record_error("Rate limited")

    def reset_daily(self):
        """Reset daily counters."""
        self.total_requests_today = 0
        self.total_tokens_today = 0
        self.errors_today = 0
        self.rate_limited_count = 0
        self.consecutive_errors = 0
        self.is_healthy = True

    def reset_hourly(self):
        """Reset hourly counters."""
        self.requests_this_hour = 0
        self.hour_reset_time = now_ist()

    def reset_minutely(self):
        """Reset per-minute counters."""
        self.requests_this_minute = 0
        self.minute_reset_time = now_ist()


# Task to temperature mapping (v8.0 comprehensive)
TASK_TEMPERATURE_MAP: Dict[str, float] = {
    # Fast classification tasks (Cerebras, low temp)
    'ghost_classify': 0.0,
    'intent_classify': 0.0,
    'extract_basics': 0.1,
    'dedup_score': 0.0,
    'portal_parse': 0.1,
    'sector_tag': 0.0,
    'quick_classify': 0.0,
    'listing_quality_score': 0.1,
    'salary_benchmark': 0.1,
    'duplicate_semantic': 0.0,
    'anomaly_detect': 0.1,
    'enrichment_priority': 0.0,
    'mba_relevance_filter': 0.0,
    'sales_exclusion_check': 0.0,
    'ppo_eligibility_check': 0.0,
    'question_match': 0.1,
    # Heavy reasoning tasks (Groq, varies)
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
    'question_answer': 0.3,
    'interview_prep': 0.4,
    'star_framework': 0.5,
    'negotiation_script': 0.5,
    'cover_letter_cache': 0.7,
    'alumni_outreach': 0.5,
    'reengagement': 0.4,
}

# Task to max_tokens mapping (v8.0)
TASK_MAX_TOKENS_MAP: Dict[str, int] = {
    # Cerebras tasks
    'ghost_classify': 200,
    'intent_classify': 200,
    'extract_basics': 600,
    'dedup_score': 300,
    'portal_parse': 800,
    'sector_tag': 200,
    'quick_classify': 150,
    'listing_quality_score': 400,
    'salary_benchmark': 300,
    'duplicate_semantic': 200,
    'anomaly_detect': 500,
    'enrichment_priority': 400,
    'mba_relevance_filter': 300,
    'sales_exclusion_check': 200,
    'ppo_eligibility_check': 300,
    'question_match': 400,
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
    'question_answer': 500,
    'interview_prep': 1500,
    'star_framework': 1200,
    'negotiation_script': 1000,
    'cover_letter_cache': 1200,
    'alumni_outreach': 800,
    'reengagement': 600,
}


# ============================================================
# SECTION 5: TELEGRAM CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class TelegramBotConfig:
    """Configuration for the Telegram bot (A-12 command center)."""
    bot_token: str = ""
    chat_id: str = ""
    admin_id: str = ""
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


# ============================================================
# SECTION 6: PROXY & STEALTH CONFIGURATION
# ============================================================

class ProxyType(Enum):
    """Proxy layer types in the stealth system."""
    WEBSHARE = "webshare"
    CLOUDFLARE = "cloudflare"
    SCRAPERAPI = "scraperapi"
    SCRAPEDO = "scrapedo"
    SCRAPINGBEE = "scrapingbee"
    FREE_LIST = "free_list"
    DIRECT = "direct"


@dataclass(frozen=True)
class WebshareConfig:
    """Configuration for Webshare proxy (10 free IPs)."""
    api_key: str = ""
    api_url: str = "https://proxy.webshare.io/api/v2/proxy/list/"
    max_ips: int = 10
    rotation_interval_sec: int = 300
    health_check_interval_sec: int = 3600
    max_consecutive_failures: int = 3
    timeout_seconds: int = 30


@dataclass(frozen=True)
class CloudflareRelayConfig:
    """Configuration for Cloudflare Worker relay."""
    worker_url: str = ""
    relay_secret: str = ""
    daily_request_limit: int = 100000
    timeout_seconds: int = 30
    retry_attempts: int = 2
    retry_delay: float = 3.0


@dataclass(frozen=True)
class ScrapingAPIConfig:
    """Configuration for scraping API fallbacks (v8.0).
    Each service provides ~1000 free credits/month."""
    scraperapi_key: str = ""
    scraperapi_base: str = "http://api.scraperapi.com"
    scraperapi_monthly_credits: int = 1000

    scrapedo_token: str = ""
    scrapedo_base: str = "http://api.scrape.do"
    scrapedo_monthly_credits: int = 1000

    scrapingbee_key: str = ""
    scrapingbee_base: str = "https://app.scrapingbee.com/api/v1/"
    scrapingbee_credits: int = 1000  # One-time

    # Usage tracking
    scraperapi_used_today: int = 0
    scrapedo_used_today: int = 0
    scrapingbee_used_total: int = 0

    def get_best_available(self) -> Optional[str]:
        """Return the scraping service with most credits remaining."""
        options = []
        if self.scraperapi_key and self.scraperapi_used_today < 33:
            options.append(('scraperapi', 33 - self.scraperapi_used_today))
        if self.scrapedo_token and self.scrapedo_used_today < 33:
            options.append(('scrapedo', 33 - self.scrapedo_used_today))
        if self.scrapingbee_key and self.scrapingbee_used_total < self.scrapingbee_credits:
            options.append(('scrapingbee', self.scrapingbee_credits - self.scrapingbee_used_total))
        if not options:
            return None
        return max(options, key=lambda x: x[1])[0]


@dataclass(frozen=True)
class StealthTimingConfig:
    """Timing configuration for human-like behavior simulation.
    Uses Gaussian jitter as specified in v8.0 anti-ban rules."""
    min_delay: float = 8.0
    max_delay: float = 25.0
    gaussian_mean: float = 15.0
    gaussian_std: float = 4.0
    micro_pause_min: float = 0.5
    micro_pause_max: float = 2.0
    pages_per_session_min: int = 5
    pages_per_session_max: int = 10
    session_break_min: float = 60.0
    session_break_max: float = 300.0
    domain_cooldown_seconds: int = 600
    # v8.0: No night scraping (ban prevention)
    scraping_start_hour: int = 6   # 6 AM IST
    scraping_end_hour: int = 23    # 11 PM IST

    def get_gaussian_delay(self) -> float:
        """Get a Gaussian-distributed delay for human-like timing."""
        delay = random.gauss(self.gaussian_mean, self.gaussian_std)
        return max(self.min_delay, min(self.max_delay, delay))


# Per-site stealth profiles (v8.0)
SITE_STEALTH_PROFILES: Dict[str, Dict[str, Any]] = {
    'linkedin': {
        'tls_profile': None,
        'api_type': 'serp_api',
        'delay_min': 30.0,
        'delay_max': 60.0,
        'proxy_layer': ProxyType.DIRECT,
        'max_requests_per_hour': 5,
        'max_pages_per_session': 3,
        'requires_cookies': False,
        'note': 'NEVER scrape LinkedIn directly. Use SerpAPI/DDG dorks only.',
    },
    'naukri': {
        'tls_profile': 'chrome120',
        'api_type': 'mobile_api',
        'delay_min': 10.0,
        'delay_max': 20.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 30,
        'max_pages_per_session': 8,
        'requires_cookies': False,
        'base_url': 'https://www.naukri.com',
        'api_url': 'https://www.naukri.com/jobapi/v3/search',
    },
    'internshala': {
        'tls_profile': 'chrome120',
        'api_type': 'mobile_ajax',
        'delay_min': 5.0,
        'delay_max': 15.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 50,
        'max_pages_per_session': 10,
        'requires_cookies': True,
        'base_url': 'https://internshala.com',
        'ajax_url': 'https://internshala.com/internships_ajax/page-',
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
        'base_url': 'https://www.iimjobs.com',
    },
    'unstop': {
        'tls_profile': 'chrome120',
        'api_type': 'rest_api',
        'delay_min': 5.0,
        'delay_max': 10.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 40,
        'max_pages_per_session': 10,
        'requires_cookies': False,
        'base_url': 'https://unstop.com',
        'api_url': 'https://unstop.com/api/public/opportunity/search-new',
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
        'base_url': 'https://wellfound.com',
    },
    'foundit': {
        'tls_profile': 'chrome120',
        'api_type': 'web',
        'delay_min': 8.0,
        'delay_max': 15.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 30,
        'max_pages_per_session': 8,
        'requires_cookies': False,
        'base_url': 'https://www.foundit.in',
    },
    'timesjobs': {
        'tls_profile': None,
        'api_type': 'web',
        'delay_min': 5.0,
        'delay_max': 10.0,
        'proxy_layer': ProxyType.WEBSHARE,
        'max_requests_per_hour': 40,
        'max_pages_per_session': 10,
        'requires_cookies': False,
        'base_url': 'https://www.timesjobs.com',
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
        'api_base': 'https://api.lever.co/v0/postings',
    },
}


# ============================================================
# SECTION 7: MBA CATEGORIES & EXCLUSION FILTERS
# ============================================================

# v8.0: STRICT MBA-ONLY categories
# NO sales, NO BDE, NO SDR, NO tech-only roles
MBA_CATEGORIES: List[str] = [
    'marketing',
    'finance',
    'strategy',
    'consulting',
    'operations',
    'product-management',
    'human-resources',
    'supply-chain',
    'analytics',
]

# Extended keywords for each category
MBA_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    'marketing': [
        'marketing', 'brand management', 'digital marketing', 'social media',
        'content marketing', 'SEO', 'SEM', 'performance marketing', 'growth marketing',
        'advertising', 'market research', 'brand strategy', 'consumer insights',
        'trade marketing', 'product marketing', 'GTM', 'go-to-market',
        'CRM', 'email marketing', 'influencer marketing', 'PR',
        'media planning', 'campaign management', 'marketing analytics',
        'brand communications', 'media buying', 'creative strategy',
    ],
    'finance': [
        'finance', 'financial analysis', 'investment banking', 'corporate finance',
        'equity research', 'financial modeling', 'valuation', 'M&A',
        'private equity', 'venture capital', 'portfolio management',
        'risk management', 'treasury', 'FP&A', 'financial planning',
        'credit analysis', 'asset management', 'wealth management',
        'accounting', 'audit', 'taxation', 'compliance', 'banking',
        'fund management', 'investment analysis', 'capital markets',
    ],
    'strategy': [
        'strategy', 'management consulting', 'business strategy',
        'corporate strategy', 'strategic planning', 'competitive analysis',
        'market entry', 'growth strategy', 'transformation',
        'due diligence', 'benchmarking', 'feasibility study',
        'business plan', 'strategic initiatives', 'org design',
        'corporate development', 'strategy consulting',
    ],
    'consulting': [
        'consulting', 'management consulting', 'strategy consulting',
        'technology consulting', 'advisory', 'implementation',
        'change management', 'digital transformation',
        'process consulting', 'operations consulting', 'HR consulting',
        'risk advisory', 'compliance consulting', 'business consulting',
    ],
    'operations': [
        'operations', 'supply chain', 'logistics', 'procurement',
        'inventory management', 'warehouse', 'distribution', 'fulfillment',
        'process improvement', 'lean', 'six sigma', 'quality',
        'manufacturing', 'production', 'capacity planning',
        'operational excellence', 'process optimization', 'vendor management',
    ],
    'product-management': [
        'product management', 'product manager', 'PM', 'APM',
        'product strategy', 'product development', 'product design',
        'user research', 'A/B testing', 'experimentation',
        'product analytics', 'feature prioritization', 'roadmap',
        'agile', 'scrum', 'sprint planning', 'PRD', 'user stories',
        'product owner', 'product growth',
    ],
    'human-resources': [
        'human resources', 'HR', 'talent acquisition', 'recruitment',
        'HRBP', 'HR business partner', 'compensation', 'benefits',
        'employee engagement', 'learning & development', 'L&D',
        'organizational development', 'OD', 'performance management',
        'HRIS', 'HR analytics', 'people operations', 'culture',
        'employer branding', 'diversity & inclusion',
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
        'business intelligence', 'data analysis', 'data science',
        'machine learning', 'AI', 'artificial intelligence',
        'statistical analysis', 'predictive analytics', 'data visualization',
        'Tableau', 'Power BI', 'SQL', 'Python', 'R', 'Excel',
        'data engineering', 'ETL', 'reporting', 'dashboards',
        'customer analytics', 'web analytics', 'marketing analytics',
        'deep learning', 'NLP', 'computer vision',
    ],
}

# ============================================================
# STRICT EXCLUSION LISTS (v8.0 - NO SALES, NO PURE TECH)
# ============================================================

# These title patterns MUST be excluded -- they are disguised sales roles
SALES_EXCLUSION_TITLES: List[str] = [
    'sales', 'business development', 'BDE', 'BDM',
    'business development executive', 'business development manager',
    'business development intern', 'business development associate',
    'sales executive', 'sales manager', 'sales intern',
    'sales development representative', 'SDR',
    'account executive', 'AE',
    'revenue', 'revenue growth',
    'cold calling', 'tele-calling', 'telecalling', 'telesales',
    'lead generation', 'lead gen', 'leadgen',
    'outbound sales', 'inbound sales',
    'field sales', 'inside sales',
    'client acquisition', 'customer acquisition',
    'channel sales', 'enterprise sales',
    'B2B sales', 'B2C sales',
    'sales & marketing',  # This is almost always sales-primary
    'BD executive', 'BD manager', 'BD intern',
    'revenue operations',  # Often disguised sales
    'growth hacking',  # Often disguised sales
    'partnership development',  # Sometimes disguised sales
]

# Keywords in description that indicate sales role
SALES_EXCLUSION_KEYWORDS: List[str] = [
    'cold call', 'cold calling', 'cold-calling',
    'tele-calling', 'telecalling', 'telesales',
    'lead generation target', 'sales target',
    'revenue target', 'quota',
    'client acquisition target',
    'door-to-door', 'field visits for sales',
    'pitch to clients', 'close deals',
    'upselling', 'cross-selling',
    'pipeline management', 'sales pipeline',
    'CRM entries for sales', 'sales funnel',
]

# Pure tech roles to exclude (not MBA-relevant)
TECH_EXCLUSION_TITLES: List[str] = [
    'software engineer', 'software developer',
    'frontend developer', 'backend developer',
    'full stack developer', 'full-stack developer',
    'web developer', 'mobile developer',
    'android developer', 'ios developer',
    'devops engineer', 'cloud engineer',
    'system administrator', 'network engineer',
    'QA engineer', 'test engineer',
    'embedded engineer', 'firmware engineer',
    'hardware engineer', 'VLSI', 'chip design',
    'game developer', 'graphics programmer',
    'UI developer', 'UX developer',
    'cybersecurity analyst', 'security engineer',
    'blockchain developer', 'smart contract developer',
    'site reliability engineer', 'SRE',
    'database administrator', 'DBA',
    'IT support', 'technical support',
    'help desk', 'desktop support',
]


# ============================================================
# SECTION 8: COMPANY TIERS & PPO SCORING
# ============================================================

class CompanyTier(IntEnum):
    """Company tier classification for PPO scoring."""
    ELITE = 1
    STRONG_MNC = 2
    INDIAN_UNICORN = 3
    GROWING_STARTUP = 4
    NICHE_SECTOR = 5

TIER_PPO_SCORES: Dict[int, int] = {
    CompanyTier.ELITE: 100,
    CompanyTier.STRONG_MNC: 80,
    CompanyTier.INDIAN_UNICORN: 60,
    CompanyTier.GROWING_STARTUP: 40,
    CompanyTier.NICHE_SECTOR: 20,
}
DEFAULT_TIER_SCORE: int = 30


@dataclass
class PPOWeights:
    """10-variable PPO scoring weights. Must sum to 1.0.
    These are defaults until A-11 Outcome Learner retrains them."""
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
        total = sum([
            self.has_ppo_tag, self.company_tier_score,
            self.low_applicant_bonus, self.stipend_normalized,
            self.duration_fit, self.cirs_score,
            self.sector_momentum, self.intent_signal,
            self.historic_callback, self.recency_bonus,
        ])
        return abs(total - 1.0) < 0.001

    def to_dict(self) -> Dict[str, float]:
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
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


PPO_PARAMS: Dict[str, Any] = {
    'applicant_decay_rate': 0.2,
    'category_median_stipends': {
        'marketing': 10000, 'finance': 15000,
        'operations': 10000, 'strategy': 20000,
        'consulting': 20000, 'product-management': 15000,
        'human-resources': 8000, 'supply-chain': 10000,
        'analytics': 15000,
    },
    'ideal_duration_range': (2, 6),
    'short_duration_score': 70,
    'long_duration_score': 50,
    'min_outcomes_for_historic': 20,
    'default_callback_score': 50,
    'recency_decay_per_day': 15,
}


# ============================================================
# SECTION 9: GHOST DETECTION
# ============================================================

@dataclass(frozen=True)
class GhostDetectionConfig:
    """5-signal ghost job detection thresholds."""
    age_high_threshold_days: int = 30
    age_high_score: int = 25
    age_medium_threshold_days: int = 20
    age_medium_score: int = 15
    age_low_threshold_days: int = 10
    age_low_score: int = 8
    applicant_high_threshold: int = 500
    applicant_high_score: int = 20
    applicant_medium_threshold: int = 300
    applicant_medium_score: int = 12
    applicant_low_threshold: int = 200
    applicant_low_score: int = 5
    repeat_high_count: int = 3
    repeat_high_score: int = 20
    repeat_medium_count: int = 2
    repeat_medium_score: int = 10
    repeat_lookback_days: int = 90
    no_signal_days: int = 30
    no_signal_score: int = 15
    weak_signal_threshold: int = 3
    weak_signal_score: int = 8
    ats_mismatch_score: int = 20
    ats_unknown_score: int = 5
    ghost_threshold: int = 60
    suspicious_threshold: int = 40


# ============================================================
# SECTION 10: BLUE OCEAN CRITERIA
# ============================================================

@dataclass(frozen=True)
class BlueOceanConfig:
    """Blue Ocean = High prestige, low competition listings."""
    min_prestige_score: int = 60
    max_applicant_count: int = 35
    min_stipend: int = 5000
    max_days_posted: int = 7
    include_ppo_only: bool = False
    alert_immediately: bool = True
    max_alerts_per_day: int = 15


# ============================================================
# SECTION 11: 3x WEEKLY SCRAPING SCHEDULE
# ============================================================

@dataclass(frozen=True)
class ScrapeScheduleEntry:
    """A single scrape schedule entry."""
    day: str  # 'tuesday', 'thursday', 'saturday', 'daily'
    hour: int
    minute: int
    agent_id: str
    task: str
    portals: List[str] = field(default_factory=list)
    description: str = ""
    estimated_minutes: int = 30
    priority: int = 1
    depends_on: Optional[str] = None


# v8.0: 3x Weekly Schedule (Tue/Thu/Sat 7 AM IST)
WEEKLY_SCRAPE_SCHEDULE: List[Dict[str, Any]] = [
    # === TUESDAY (Primary Scrape) ===
    {
        'day': 'tuesday', 'hour': 7, 'minute': 0,
        'agent_id': 'A-03', 'task': 'primary_scrape',
        'portals': ['linkedin', 'naukri', 'internshala', 'iimjobs', 'unstop'],
        'description': 'Tuesday Primary: LinkedIn + Naukri + Internshala + IIMJobs + Unstop',
        'estimated_minutes': 60, 'priority': 1,
    },
    # === THURSDAY (Secondary Scrape) ===
    {
        'day': 'thursday', 'hour': 7, 'minute': 0,
        'agent_id': 'A-03', 'task': 'secondary_scrape',
        'portals': ['linkedin', 'naukri', 'wellfound', 'foundit', 'timesjobs'],
        'description': 'Thursday Secondary: LinkedIn + Naukri + Wellfound + Foundit + TimesJobs',
        'estimated_minutes': 60, 'priority': 1,
    },
    # === SATURDAY (Weekend Full Scrape) ===
    {
        'day': 'saturday', 'hour': 7, 'minute': 0,
        'agent_id': 'A-03', 'task': 'full_scrape',
        'portals': ['linkedin', 'naukri', 'internshala', 'iimjobs', 'unstop',
                    'wellfound', 'foundit', 'timesjobs', 'greenhouse', 'lever'],
        'description': 'Saturday Full: All portals + ATS direct crawl',
        'estimated_minutes': 90, 'priority': 1,
    },
]

# Daily pipeline schedule (runs every day)
DAILY_PIPELINE_SCHEDULE: List[Dict[str, Any]] = [
    # 6:00 AM - Session Health Check
    {'hour': 6, 'minute': 0, 'agent_id': 'A-03', 'task': 'session_health_check',
     'description': 'Check portal session cookies validity'},
    # Post-scrape pipeline (runs after scrape days, at 8 AM)
    {'hour': 8, 'minute': 0, 'agent_id': 'A-06', 'task': 'dedup',
     'description': 'Dedup engine on new batch'},
    {'hour': 8, 'minute': 20, 'agent_id': 'A-05', 'task': 'ghost_detect',
     'description': 'Ghost scoring via Cerebras'},
    {'hour': 8, 'minute': 40, 'agent_id': 'A-07', 'task': 'enrich',
     'description': 'Intelligence enrichment + Blue Ocean flagging'},
    {'hour': 9, 'minute': 0, 'agent_id': 'A-08', 'task': 'ppo_rank',
     'description': 'PPO model runs -> top 25 shortlist'},
    {'hour': 9, 'minute': 15, 'agent_id': 'A-12', 'task': 'morning_brief',
     'description': 'MORNING BRIEF -> Telegram'},
    # Afternoon
    {'hour': 14, 'minute': 0, 'agent_id': 'A-01', 'task': 'intent_scan',
     'description': 'Intent signal scan (Tier 1+2 companies)'},
    # Evening
    {'hour': 18, 'minute': 0, 'agent_id': 'A-04', 'task': 'ats_crawl',
     'description': 'ATS direct crawl (Greenhouse/Lever)'},
    {'hour': 20, 'minute': 0, 'agent_id': 'A-09', 'task': 'network_map',
     'description': 'Alumni network mining'},
    {'hour': 22, 'minute': 0, 'agent_id': 'A-12', 'task': 'evening_summary',
     'description': 'EVENING SUMMARY -> Telegram'},
    # Night
    {'hour': 23, 'minute': 0, 'agent_id': 'A-11', 'task': 'learn',
     'description': 'Outcome learner + weight retrain (Sundays only)'},
]

# Dream Company Watchlist (every 6 hours)
DREAM_COMPANY_INTERVAL_HOURS: int = 6

# v8.0 Innovation #10: Rate Optimizer window
OPTIMAL_APPLY_HOURS: Tuple[int, int] = (9, 11)  # 9 AM - 11 AM IST
OPTIMAL_APPLY_DAYS: List[str] = ['tuesday', 'wednesday', 'thursday']


# ============================================================
# SECTION 12: SEARCH CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class SerpAPIConfig:
    """SerpAPI config for LinkedIn/Google jobs search."""
    api_key: str = ""
    base_url: str = "https://serpapi.com/search"
    monthly_limit: int = 230
    daily_budget_weekday: int = 8
    daily_budget_weekend: int = 5
    timeout_seconds: int = 30


DDG_DORK_TEMPLATES: Dict[str, str] = {
    'linkedin_jobs': 'site:linkedin.com/jobs "{query}" india intern',
    'linkedin_mba_intern': 'site:linkedin.com/jobs "MBA intern" OR "management intern" india',
    'linkedin_alumni': 'site:linkedin.com/in "{college}" "{company}" alumni',
    'linkedin_hr': 'site:linkedin.com/in "{company}" "talent acquisition" OR "HR" OR "recruiter" india',
    'company_hiring': '"{company}" hiring interns 2026 india',
    'company_mba_intern': '"{company}" MBA internship 2026',
    'naukri_jobs': 'site:naukri.com "{query}" intern MBA',
    'careers_page': '"{company}" careers internship india',
}


# ============================================================
# SECTION 13: DATABASE CONFIGURATION (Supabase Primary)
# ============================================================

@dataclass(frozen=True)
class SupabaseConfig:
    """Supabase PostgreSQL configuration -- PRIMARY persistent storage.
    Free Tier: 500MB storage, unlimited API requests, 5GB bandwidth/month.
    Projects pause after 7 days inactivity (kept alive by Layer 2)."""
    url: str = ""
    anon_key: str = ""
    service_role_key: str = ""
    ping_interval_days: float = 4.0
    min_ping_gap_hours: float = 4.0

    @property
    def is_configured(self) -> bool:
        return bool(self.url and (self.service_role_key or self.anon_key))


# ============================================================
# SECTION 14: RATE LIMITS
# ============================================================

@dataclass
class RateLimitConfig:
    """Centralized rate limit configuration. HARD CAPS."""
    groq_daily_limit: int = 14400
    groq_per_minute: int = 30
    groq_per_hour: int = 500
    cerebras_daily_tokens: int = 1000000
    cerebras_per_minute: int = 60
    cerebras_per_hour: int = 2000
    mistral_daily_limit: int = 1000
    mistral_per_minute: int = 10
    openrouter_daily_limit: int = 50
    openrouter_per_minute: int = 5
    huggingface_daily_limit: int = 300
    cf_worker_daily_limit: int = 100000
    serpapi_monthly_limit: int = 230
    serpapi_daily_budget_weekday: int = 8
    serpapi_daily_budget_weekend: int = 5
    ddg_per_hour: int = 30
    ddg_per_day: int = 200
    tg_messages_per_minute: int = 20
    tg_messages_per_second: int = 1
    # Per-site scraping caps
    internshala_per_hour: int = 50
    naukri_per_hour: int = 30
    iimjobs_per_hour: int = 40
    wellfound_per_hour: int = 40
    greenhouse_per_hour: int = 100
    lever_per_hour: int = 100
    unstop_per_hour: int = 40
    foundit_per_hour: int = 30
    timesjobs_per_hour: int = 40
    safety_margin: float = 0.85

    def get_safe_limit(self, limit: int) -> int:
        return int(limit * self.safety_margin)


# ============================================================
# SECTION 15: KEEP-ALIVE CONFIGURATION (6 Layers)
# ============================================================

@dataclass(frozen=True)
class KeepAliveConfig:
    """6-Layer Keep-Alive Architecture from v8.0 Blueprint.
    Layer 1: Render Self-Ping (every 4 minutes)
    Layer 2: Supabase Anti-Pause (Mon/Fri 9am IST)
    Layer 3: Portal Session Health (Daily 6am)
    Layer 4: AI Provider Health (Before every dispatch)
    Layer 5: Watchdog (Every 2 minutes)
    Layer 6: Weekly Backup (Sunday 11pm IST)"""
    # Layer 1
    render_self_ping_interval_sec: int = 240  # 4 minutes
    render_health_path: str = "/health"
    # Layer 2
    supabase_ping_days: List[str] = field(default_factory=lambda: ['monday', 'friday'])
    supabase_ping_hour: int = 9
    supabase_ping_query: str = "SELECT 1 FROM clean_listings LIMIT 1"
    # Layer 3
    session_health_hour: int = 6
    # Layer 4
    ai_health_test_tokens: int = 5
    ai_health_test_prompt: str = "Say OK"
    # Layer 5
    watchdog_interval_sec: int = 120  # 2 minutes
    memory_threshold_mb: int = 450
    # Layer 6
    backup_day: str = "sunday"
    backup_hour: int = 23
    backup_tables: List[str] = field(default_factory=lambda: [
        'clean_listings', 'portal_sessions', 'user_profile',
        'outcomes', 'system_pings', 'dream_companies',
    ])


# ============================================================
# SECTION 16: USER AGENTS
# ============================================================

USER_AGENT_POOL: List[str] = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
    # Mobile
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6099.144 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6099.144 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
]

MOBILE_USER_AGENTS: List[str] = [ua for ua in USER_AGENT_POOL if 'Mobile' in ua]
DESKTOP_USER_AGENTS: List[str] = [ua for ua in USER_AGENT_POOL if 'Mobile' not in ua]

TLS_IMPERSONATION_PROFILES: List[str] = [
    'chrome120', 'chrome124', 'chrome126', 'firefox124', 'safari17_4',
]


# ============================================================
# SECTION 17: LOGGING & RENDER
# ============================================================

@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    format_string: str = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
    rotation: str = "10 MB"
    retention: str = "7 days"
    log_dir: str = "logs"
    main_log: str = "logs/firstmover.log"
    error_log: str = "logs/errors.log"
    enable_stdout: bool = True
    enable_file: bool = True


@dataclass(frozen=True)
class RenderConfig:
    """Render free tier deployment configuration."""
    is_render: bool = False
    ram_limit_mb: int = 512
    spin_down_minutes: int = 15
    keep_alive_interval_sec: int = 240
    use_webhook: bool = False
    max_concurrent_agents: int = 3
    batch_size_limit: int = 50


# ============================================================
# SECTION 18: ECONOMIC SIGNAL SOURCES
# ============================================================

ECONOMIC_SIGNAL_SOURCES: Dict[str, Dict[str, str]] = {
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
}

GOOGLE_NEWS_RSS_TEMPLATE: str = (
    "https://news.google.com/rss/search?q={query}+india+hiring&hl=en-IN&gl=IN&ceid=IN:en"
)


# ============================================================
# SECTION 19: AUTO-APPLY PORTAL REQUIREMENTS (v8.0)
# ============================================================

AUTO_APPLY_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    'linkedin': {
        'auth_type': 'cookie',
        'required_cookies': ['li_at', 'JSESSIONID'],
        'fields': ['work_auth_status', 'question_bank_answers'],
        'cover_letter_limit': None,  # LinkedIn doesn't use cover letters
        'resume_upload': False,  # Already on profile
        'notes': 'Use li_at cookie from browser. Never automate login.',
    },
    'naukri': {
        'auth_type': 'credentials',
        'required_fields': ['email', 'password', 'resume_id'],
        'cover_letter_limit': 1000,
        'resume_upload': True,
        'notes': 'Login via credentials. Resume ID from profile.',
    },
    'internshala': {
        'auth_type': 'cookie',
        'required_cookies': ['csrf_token'],
        'cover_letter_limit': 500,
        'resume_upload': False,  # Profile-based
        'notes': 'CSRF token required for each submission.',
    },
    'wellfound': {
        'auth_type': 'bearer_token',
        'required_fields': ['bearer_token'],
        'method': 'graphql_mutation',
        'resume_upload': True,
        'notes': 'GraphQL mutation for resume upload.',
    },
    'greenhouse': {
        'auth_type': 'none',
        'method': 'multipart_form_data',
        'required_fields': ['name', 'email', 'phone', 'resume_file'],
        'resume_upload': True,
        'notes': 'Direct POST to job application endpoint.',
    },
    'lever': {
        'auth_type': 'none',
        'method': 'multipart_form_data',
        'required_fields': ['name', 'email', 'phone', 'resume_file'],
        'resume_upload': True,
        'notes': 'Direct POST to job application endpoint.',
    },
}


# ============================================================
# SECTION 20: DREAM COMPANIES (Watchlist)
# ============================================================

DEFAULT_DREAM_COMPANIES: List[Dict[str, Any]] = [
    {'name': 'McKinsey & Company', 'tier': 1, 'sector': 'Consulting'},
    {'name': 'BCG', 'tier': 1, 'sector': 'Consulting'},
    {'name': 'Bain & Company', 'tier': 1, 'sector': 'Consulting'},
    {'name': 'Goldman Sachs', 'tier': 1, 'sector': 'Banking & Finance'},
    {'name': 'JPMorgan Chase', 'tier': 1, 'sector': 'Banking & Finance'},
    {'name': 'Google', 'tier': 1, 'sector': 'Technology'},
    {'name': 'Amazon', 'tier': 1, 'sector': 'E-Commerce'},
    {'name': 'Microsoft', 'tier': 1, 'sector': 'Technology'},
    {'name': 'Unilever', 'tier': 1, 'sector': 'FMCG'},
    {'name': 'P&G', 'tier': 1, 'sector': 'FMCG'},
    {'name': 'Deloitte', 'tier': 2, 'sector': 'Consulting'},
    {'name': 'PwC', 'tier': 2, 'sector': 'Consulting'},
    {'name': 'EY', 'tier': 2, 'sector': 'Consulting'},
    {'name': 'KPMG', 'tier': 2, 'sector': 'Consulting'},
    {'name': 'Tata Group', 'tier': 2, 'sector': 'Conglomerate'},
    {'name': 'Reliance Industries', 'tier': 2, 'sector': 'Conglomerate'},
    {'name': 'Aditya Birla Group', 'tier': 2, 'sector': 'Conglomerate'},
    {'name': 'ITC', 'tier': 2, 'sector': 'FMCG'},
    {'name': 'Asian Paints', 'tier': 2, 'sector': 'Manufacturing'},
    {'name': 'HDFC Bank', 'tier': 2, 'sector': 'Banking & Finance'},
    {'name': 'ICICI Bank', 'tier': 2, 'sector': 'Banking & Finance'},
    {'name': 'Razorpay', 'tier': 3, 'sector': 'Fintech'},
    {'name': 'CRED', 'tier': 3, 'sector': 'Fintech'},
    {'name': 'Zepto', 'tier': 3, 'sector': 'E-Commerce'},
    {'name': 'Swiggy', 'tier': 3, 'sector': 'E-Commerce'},
    {'name': 'Zomato', 'tier': 3, 'sector': 'E-Commerce'},
    {'name': 'PhonePe', 'tier': 3, 'sector': 'Fintech'},
    {'name': 'Meesho', 'tier': 3, 'sector': 'E-Commerce'},
    {'name': 'Groww', 'tier': 3, 'sector': 'Fintech'},
]


# ============================================================
# MASTER CONFIGURATION CLASS
# ============================================================

class Config:
    """
    Master configuration class -- SINGLE entry point for all config.
    Singleton pattern ensures one instance across the application.

    Usage:
        config = Config()
        groq_key = config.groq.api_key
        cerebras_model = config.cerebras.model
        telegram_token = config.telegram.bot_token
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
        self._load_all()

    def _load_all(self):
        """Load all configuration from environment variables."""
        # Environment detection
        self.environment = _get_env('ENVIRONMENT', default='production')
        self.is_render = bool(
            _get_env('RENDER_DEPLOY', default='false', cast_type=bool)
            or _get_env('RENDER', default='')
        )

        # ---- AI Providers (5 total) ----
        self.groq = GroqConfig(
            api_key=_get_env('GROQ_API_KEY', default=''),
        )
        self.cerebras = CerebrasConfig(
            api_key=_get_env('CEREBRAS_API_KEY', default=''),
        )
        self.mistral = MistralConfig(
            api_key=_get_env('MISTRAL_API_KEY', default=''),
        )
        self.openrouter = OpenRouterConfig(
            api_key=_get_env('OPENROUTER_API_KEY', default=''),
        )
        self.huggingface = HuggingFaceConfig(
            api_key=_get_env('HF_API_KEY', default=''),
        )

        # AI Provider runtime status
        self.ai_status: Dict[str, AIProviderStatus] = {
            'groq': AIProviderStatus(provider='groq'),
            'cerebras': AIProviderStatus(provider='cerebras'),
            'mistral': AIProviderStatus(provider='mistral'),
            'openrouter': AIProviderStatus(provider='openrouter'),
            'huggingface': AIProviderStatus(provider='huggingface'),
        }

        # ---- Telegram ----
        self.telegram = TelegramBotConfig(
            bot_token=_get_env('TG_BOT_TOKEN', default=''),
            chat_id=_get_env('TG_CHAT_ID', default=''),
            admin_id=_get_env('ADMIN_TELEGRAM_ID', default=''),
        )

        # ---- Proxy & Stealth ----
        self.webshare = WebshareConfig(
            api_key=_get_env('WEBSHARE_KEY', default=''),
        )
        self.cloudflare_relay = CloudflareRelayConfig(
            worker_url=_get_env('CF_WORKER_URL', default=''),
            relay_secret=_get_env('CF_RELAY_SECRET', default=''),
        )
        self.scraping_apis = ScrapingAPIConfig(
            scraperapi_key=_get_env('SCRAPERAPI_KEY', default=''),
            scrapedo_token=_get_env('SCRAPEDO_TOKEN', default=''),
            scrapingbee_key=_get_env('SCRAPINGBEE_KEY', default=''),
        )
        self.stealth_timing = StealthTimingConfig()

        # ---- Search ----
        self.serpapi = SerpAPIConfig(
            api_key=_get_env('SERP_API_KEY', default=''),
        )

        # ---- Database (Supabase Primary) ----
        self.supabase = SupabaseConfig(
            url=_get_env('SUPABASE_URL', default=''),
            anon_key=_get_env('SUPABASE_ANON_KEY', default=''),
            service_role_key=_get_env('SUPABASE_SERVICE_ROLE_KEY', default=''),
        )

        # Schedule mode
        self.schedule_mode = _get_env('SCHEDULE_MODE', default='weekly')

        # ---- Rate Limits ----
        self.rate_limits = RateLimitConfig()

        # ---- Scoring ----
        self.ppo_weights = PPOWeights()
        assert self.ppo_weights.validate(), "PPO weights must sum to 1.0!"

        self.ghost = GhostDetectionConfig()
        self.blue_ocean = BlueOceanConfig()

        # ---- Keep-Alive ----
        self.keepalive = KeepAliveConfig()

        # ---- Logging ----
        log_level = _get_env('LOG_LEVEL', default='INFO')
        self.logging = LoggingConfig(level=log_level)

        # ---- Render ----
        self.render = RenderConfig(is_render=self.is_render)

        # ---- Timezone ----
        self.timezone_name = _get_env('TIMEZONE', default='Asia/Kolkata')
        self.ist = IST

    def get_ai_provider_config(self, provider_name: str) -> Any:
        """Get config for a specific AI provider."""
        providers = {
            'groq': self.groq,
            'cerebras': self.cerebras,
            'mistral': self.mistral,
            'openrouter': self.openrouter,
            'huggingface': self.huggingface,
        }
        return providers.get(provider_name)

    def get_agent_providers(self, agent_id: str) -> List[str]:
        """Get the ordered provider list for an agent (primary + fallbacks)."""
        return AGENT_FALLBACK_MATRIX.get(agent_id, ['groq', 'cerebras', 'mistral'])

    def validate_critical(self) -> Dict[str, bool]:
        """Validate critical config values."""
        return {
            'groq_api_key': bool(self.groq.api_key),
            'cerebras_api_key': bool(self.cerebras.api_key),
            'telegram_bot_token': bool(self.telegram.bot_token),
            'telegram_chat_id': bool(self.telegram.chat_id),
            'supabase_configured': self.supabase.is_configured,
            'ppo_weights_valid': self.ppo_weights.validate(),
        }

    def validate_optional(self) -> Dict[str, bool]:
        """Validate optional but recommended config."""
        return {
            'serpapi_key': bool(self.serpapi.api_key),
            'webshare_key': bool(self.webshare.api_key),
            'cf_worker_url': bool(self.cloudflare_relay.worker_url),
            'cf_relay_secret': bool(self.cloudflare_relay.relay_secret),
            'mistral_key': bool(self.mistral.api_key),
            'openrouter_key': bool(self.openrouter.api_key),
            'huggingface_key': bool(self.huggingface.api_key),
            'scraperapi_key': bool(self.scraping_apis.scraperapi_key),
            'scrapedo_token': bool(self.scraping_apis.scrapedo_token),
            'scrapingbee_key': bool(self.scraping_apis.scrapingbee_key),
        }

    def get_health_report(self) -> Dict[str, Any]:
        """Generate comprehensive configuration health report."""
        critical = self.validate_critical()
        optional = self.validate_optional()
        return {
            'version': '8.0.0',
            'environment': self.environment,
            'is_render': self.is_render,
            'critical_config': critical,
            'all_critical_ok': all(critical.values()),
            'optional_config': optional,
            'optional_configured': sum(1 for v in optional.values() if v),
            'optional_total': len(optional),
            'ai_providers_active': sum(
                1 for s in self.ai_status.values() if s.is_healthy
            ),
            'ai_providers_total': len(self.ai_status),
            'ppo_weights': self.ppo_weights.to_dict(),
            'mba_categories': len(MBA_CATEGORIES),
            'sales_exclusions': len(SALES_EXCLUSION_TITLES),
            'tech_exclusions': len(TECH_EXCLUSION_TITLES),
            'dream_companies': len(DEFAULT_DREAM_COMPANIES),
            'schedule_mode': self.schedule_mode,
        }

    def __repr__(self) -> str:
        health = self.get_health_report()
        return (
            f"Config(v{health['version']}, env={health['environment']}, "
            f"render={health['is_render']}, "
            f"critical_ok={health['all_critical_ok']}, "
            f"ai_active={health['ai_providers_active']}/{health['ai_providers_total']}, "
            f"optional={health['optional_configured']}/{health['optional_total']})"
        )


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

def get_config() -> Config:
    """Get the singleton Config instance."""
    return Config()


if __name__ == "__main__":
    cfg = get_config()
    print("=" * 60)
    print("OPERATION FIRST MOVER v8.0 -- Configuration Report")
    print("=" * 60)
    health = cfg.get_health_report()
    for key, value in health.items():
        if isinstance(value, dict):
            print(f"\n{key}:")
            for k, v in value.items():
                status = "OK" if v else "MISSING"
                print(f"  [{status}] {k}: {v}")
        else:
            print(f"  {key}: {value}")
    print(f"\n{cfg}")
    print("=" * 60)
