"""
============================================================
PRISM v0.1 — AGENT A-03: PRIMARY SCRAPER (PORTAL INTELLIGENCE HARVESTER)
============================================================
The highest-volume agent in PRISM. Scrapes 8+ portals with
PORTAL-SPECIFIC strategies for each target.

PRISM v0.1 Upgrades from OFM v7.0:
    1. Naukri: Direct API v2 as PRIMARY (GET jobapi/v2/search)
       - Headers: appid=109, systemid=Naukri, gid=LOCATION,...
       - Fallback: DDG dorks if API returns 403/406
       - CF Browser Rendering for individual JD extraction
    2. Internshala: Mobile Ajax POST with MBA category_ids
       - POST /internship_listings (mobile JSON endpoint)
       - Headers: app-version: 5.x, mobile User-Agent
       - Category IDs for Finance, Marketing, Ops, DS, AI, HR, Mgmt
       - Rate: 50 req/hour, 10 pages/session, 5-15s delays
    3. IIMjobs: DDG site dorks (site:iimjobs.com "intern")
    4. LinkedIn: DDG site dorks ONLY (NEVER direct scrape)
       - site:linkedin.com/jobs with MBA terms, location=India
       - Max 5 req/hour to avoid DDG throttling
    5. Indeed: RSS feed parsing (zero ban risk)
    6. Wellfound: GraphQL API with MBA category filter
    7. CareerPage: DDG dorks for company career pages
    8. Instahyre: DDG dorks for curated MBA roles

Schedule (PRISM 3-Wave):
    Wave 1 (05:15 IST, Mon/Wed/Fri): Internshala + Naukri API + IIMjobs
    Wave 2 (14:00 IST, Tue/Thu/Sat): LinkedIn DDG + CareerPages + Indeed
    Night  (22:30 IST, Mon/Wed):     Deep crawl all portals

Anti-Detection (Global):
    - curl_cffi for Chrome TLS fingerprints
    - Webshare proxy rotation (10 India-geolocated IPs)
    - Random delays (2-8s between requests, 5-15s between pages)
    - Full header set: Accept-Language, Sec-Fetch-Mode, referer chains
    - Session rotation every 5-10 requests
    - Mobile User-Agent rotation for Internshala/Naukri

AI Provider: Cerebras 8B (extract_basics, naukri_parse, internshala_parse)
Tools: stealth_fetch, cf_render, ddg_search, db_read, db_write
Cost: $0 (all free tier)

Integration Points:
    - A-05 Ghost Detector → receives raw listings for scoring
    - A-06 Dedup Engine → receives for 6-layer dedup
    - A-12 Telegram Reporter → scrape summaries
    - A-17 Adaptive Scheduler → portal health metrics
============================================================
"""

import os
import re
import json
import time
import uuid
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from urllib.parse import urljoin, urlencode, quote_plus
from dataclasses import dataclass, field

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    logger.warning("beautifulsoup4 not installed")

try:
    import feedparser
except ImportError:
    feedparser = None
    logger.warning("feedparser not installed")

from core.config import (
    get_config, MBA_CATEGORIES, SITE_STEALTH_PROFILES,
    ProxyType, ScrapingSource, IST,
)
from core.database import get_db, RawListing, DatabaseManager
from core.stealth_engine import get_stealth_client, StealthHTTPClient
from core.ai_router import get_router, AIRouter


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-03"
AGENT_NAME = "Primary Scraper"

# Internshala configuration — PRISM v0.1: Mobile Ajax API
INTERNSHALA_BASE_URL = "https://internshala.com"
INTERNSHALA_LISTINGS_URL = "https://internshala.com/internships"
INTERNSHALA_AJAX_URL = "https://internshala.com/internships/ajax/search_ajax"
INTERNSHALA_MOBILE_API = "https://internshala.com/api/v1/internship_listings"

# PRISM v0.1: Internshala category IDs for MBA-relevant roles
# EXPANDED: added more categories for broader coverage
INTERNSHALA_CATEGORY_IDS = {
    "finance":             {"id": "4",  "slug": "finance-internship"},
    "marketing":           {"id": "5",  "slug": "marketing-internship"},
    "operations":          {"id": "14", "slug": "operations-internship"},
    "business_development":{"id": "3",  "slug": "business-development-sales-internship"},
    "data_science":        {"id": "23", "slug": "data-science-machine-learning-internship"},
    "analytics":           {"id": "22", "slug": "analytics-internship"},
    "management":          {"id": "6",  "slug": "management-internship"},
    "human_resources":     {"id": "7",  "slug": "hr-internship"},
    "product_management":  {"id": "26", "slug": "product-management-internship"},
    "consulting":          {"id": "18", "slug": "consulting-internship"},
    "strategy":            {"id": "20", "slug": "strategy-internship"},
    "ecommerce":           {"id": "24", "slug": "ecommerce-internship"},
    "supply_chain":        {"id": "25", "slug": "supply-chain-logistics-internship"},
    "media":               {"id": "11", "slug": "media-internship"},
    "research":            {"id": "17", "slug": "research-internship"},
}

# Naukri configuration — PRISM v0.1: Direct API v2 as PRIMARY
NAUKRI_BASE_URL = "https://www.naukri.com"
NAUKRI_API_V2_URL = "https://www.naukri.com/jobapi/v2/search"
NAUKRI_API_V3_URL = "https://www.naukri.com/jobapi/v3/search"

# PRISM v0.1: Naukri API v2 required headers
NAUKRI_API_HEADERS = {
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'appid': '109',
    'systemid': 'Naukri',
    'Content-Type': 'application/json',
    'gid': 'LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://www.naukri.com',
    'Referer': 'https://www.naukri.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'Connection': 'keep-alive',
}

# PRISM v0.2: Naukri MBA search queries for API v2
# EXPANDED for maximum yield — MBA/Data/AI/Analytics ONLY
# NO sales, NO business development, NO generic tech/coding roles
NAUKRI_MBA_QUERIES = [
    # === CORE MBA INTERNSHIPS (highest yield) ===
    {"keyword": "MBA intern", "experience": "0"},
    {"keyword": "MBA internship", "experience": "0"},
    {"keyword": "MBA summer internship", "experience": "0"},
    {"keyword": "management trainee intern", "experience": "0"},
    {"keyword": "management trainee", "experience": "0"},
    {"keyword": "summer internship MBA 2026", "experience": "0"},
    {"keyword": "summer intern business", "experience": "0"},
    {"keyword": "management internship", "experience": "0"},

    # === MARKETING & BRAND ===
    {"keyword": "marketing intern MBA", "experience": "0"},
    {"keyword": "marketing intern", "experience": "0"},
    {"keyword": "digital marketing intern", "experience": "0"},
    {"keyword": "brand management intern", "experience": "0"},
    {"keyword": "brand marketing intern", "experience": "0"},
    {"keyword": "market research intern", "experience": "0"},
    {"keyword": "performance marketing intern", "experience": "0"},
    {"keyword": "growth marketing intern", "experience": "0"},
    {"keyword": "social media marketing intern", "experience": "0"},
    {"keyword": "content marketing intern", "experience": "0"},
    {"keyword": "marketing analytics intern", "experience": "0"},
    {"keyword": "category management intern", "experience": "0"},

    # === FINANCE & INVESTMENT ===
    {"keyword": "finance intern MBA", "experience": "0"},
    {"keyword": "finance intern", "experience": "0"},
    {"keyword": "investment banking intern", "experience": "0"},
    {"keyword": "equity research intern", "experience": "0"},
    {"keyword": "corporate finance intern", "experience": "0"},
    {"keyword": "financial analyst intern", "experience": "0"},
    {"keyword": "financial planning intern", "experience": "0"},
    {"keyword": "private equity intern", "experience": "0"},
    {"keyword": "venture capital intern", "experience": "0"},
    {"keyword": "risk analyst intern", "experience": "0"},
    {"keyword": "credit analyst intern", "experience": "0"},
    {"keyword": "valuation intern", "experience": "0"},
    {"keyword": "treasury intern", "experience": "0"},
    {"keyword": "audit intern", "experience": "0"},

    # === CONSULTING & STRATEGY ===
    {"keyword": "consulting intern", "experience": "0"},
    {"keyword": "strategy intern", "experience": "0"},
    {"keyword": "management consulting intern", "experience": "0"},
    {"keyword": "corporate strategy intern", "experience": "0"},
    {"keyword": "strategy analyst intern", "experience": "0"},

    # === OPERATIONS & SUPPLY CHAIN ===
    {"keyword": "operations intern MBA", "experience": "0"},
    {"keyword": "operations intern", "experience": "0"},
    {"keyword": "supply chain intern MBA", "experience": "0"},
    {"keyword": "supply chain intern", "experience": "0"},
    {"keyword": "logistics intern", "experience": "0"},
    {"keyword": "procurement intern", "experience": "0"},

    # === PRODUCT MANAGEMENT ===
    {"keyword": "product management intern", "experience": "0"},
    {"keyword": "product manager intern", "experience": "0"},
    {"keyword": "product intern", "experience": "0"},
    {"keyword": "program management intern", "experience": "0"},
    {"keyword": "project management intern", "experience": "0"},

    # === HR ===
    {"keyword": "HR intern MBA", "experience": "0"},
    {"keyword": "HR intern", "experience": "0"},
    {"keyword": "human resources intern", "experience": "0"},
    {"keyword": "talent acquisition intern", "experience": "0"},

    # === DATA & ANALYTICS (MBA-relevant) ===
    {"keyword": "data analyst intern", "experience": "0"},
    {"keyword": "data analytics intern", "experience": "0"},
    {"keyword": "business analyst intern", "experience": "0"},
    {"keyword": "business analytics intern", "experience": "0"},
    {"keyword": "analytics intern", "experience": "0"},
    {"keyword": "data science intern", "experience": "0"},
    {"keyword": "business intelligence intern", "experience": "0"},
    {"keyword": "research analyst intern", "experience": "0"},
    {"keyword": "insights analyst intern", "experience": "0"},
    {"keyword": "quantitative analyst intern", "experience": "0"},
    {"keyword": "statistical analyst intern", "experience": "0"},

    # === AI / ML (MBA-relevant analytics) ===
    {"keyword": "AI intern", "experience": "0"},
    {"keyword": "machine learning intern", "experience": "0"},
    {"keyword": "artificial intelligence intern", "experience": "0"},
    {"keyword": "NLP intern", "experience": "0"},
    {"keyword": "deep learning intern", "experience": "0"},
    {"keyword": "generative AI intern", "experience": "0"},
    {"keyword": "AI product intern", "experience": "0"},
    {"keyword": "ML engineer intern", "experience": "0"},
    {"keyword": "data engineering intern", "experience": "0"},

    # === BROADER MBA ROLES ===
    {"keyword": "pricing analyst intern", "experience": "0"},
    {"keyword": "revenue management intern", "experience": "0"},
    {"keyword": "growth intern", "experience": "0"},
    {"keyword": "e-commerce intern", "experience": "0"},
    {"keyword": "sustainability intern", "experience": "0"},
    {"keyword": "compliance intern", "experience": "0"},
    {"keyword": "ESG intern", "experience": "0"},
    {"keyword": "real estate finance intern", "experience": "0"},
    {"keyword": "investor relations intern", "experience": "0"},
    {"keyword": "mergers acquisitions intern", "experience": "0"},
    {"keyword": "M&A intern", "experience": "0"},
    {"keyword": "corporate development intern", "experience": "0"},
    {"keyword": "commercial intern", "experience": "0"},
    {"keyword": "general management intern", "experience": "0"},
    {"keyword": "PGDM internship", "experience": "0"},
]

# IIMjobs configuration
IIMJOBS_BASE_URL = "https://www.iimjobs.com"
IIMJOBS_SEARCH_URL = "https://www.iimjobs.com/search"

# Indeed RSS
INDEED_RSS_BASE = "https://www.indeed.co.in/rss"

# Wellfound GraphQL
WELLFOUND_BASE_URL = "https://wellfound.com"
WELLFOUND_GQL_URL = "https://wellfound.com/graphql"

# LinkedIn DDG dork template — search for DIRECT job listings
LINKEDIN_DORK = 'site:linkedin.com/jobs/view "{query}" india intern'

# PRISM v0.1: Rate limits per portal
PORTAL_RATE_LIMITS = {
    "internshala": {"rpm": 50, "pages_per_session": 15, "delay_range": (4, 12)},
    "naukri":      {"rpm": 40, "pages_per_session": 25, "delay_range": (5, 12)},
    "iimjobs":     {"rpm": 40, "pages_per_session": 8,  "delay_range": (5, 10)},
    "linkedin":    {"rpm": 5,  "pages_per_session": 3,  "delay_range": (15, 30)},
    "indeed":      {"rpm": 25, "pages_per_session": 12, "delay_range": (3, 7)},
    "wellfound":   {"rpm": 20, "pages_per_session": 8,  "delay_range": (4, 10)},
    "career_page": {"rpm": 30, "pages_per_session": 15, "delay_range": (4, 10)},
    "instahyre":   {"rpm": 15, "pages_per_session": 5,  "delay_range": (6, 12)},
}

# PRISM v0.1: Mobile User-Agent pool for Internshala/Naukri
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; RMX3771) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.178 Mobile Safari/537.36",
]

# Desktop User-Agent pool
DESKTOP_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def normalize_stipend(stipend_text: str) -> float:
    """
    Convert stipend text to monthly INR amount.

    Handles formats like:
        "₹15,000 /month"
        "15000"
        "₹ 10,000 - 15,000 /month"
        "Rs 20000/month"
        "₹1,50,000 lump sum"
        "Unpaid"
        "₹10K /month"
    """
    if not stipend_text:
        return 0.0

    text = stipend_text.strip().lower()

    # Unpaid / not specified
    if any(kw in text for kw in ['unpaid', 'none', 'not disclosed', 'n/a']):
        return 0.0

    # Remove currency symbols and spaces
    text = text.replace('₹', '').replace('rs', '').replace('rs.', '')
    text = text.replace('inr', '').replace(',', '').strip()

    # Handle K suffix (10K = 10000)
    if 'k' in text:
        text = text.replace('k', '')
        numbers = re.findall(r'\d+(?:\.\d+)?', text)
        if numbers:
            try:
                return float(numbers[0]) * 1000
            except (ValueError, TypeError):
                return 0.0

    # Extract all numbers (must contain at least one digit, filter out lone dots)
    numbers = [n for n in re.findall(r'\d[\d,.]*', text) if n.replace(',', '').replace('.', '').strip()]

    if not numbers:
        return 0.0

    def _safe_float(s: str) -> float:
        """Safely convert string to float, handling Indian comma format."""
        try:
            return float(s.replace(',', '').strip())
        except (ValueError, TypeError):
            return 0.0

    # If range (e.g., "10000 - 15000"), take average
    if len(numbers) >= 2:
        low = _safe_float(numbers[0])
        high = _safe_float(numbers[1])
        monthly = (low + high) / 2 if high > 0 else low
    else:
        monthly = _safe_float(numbers[0])

    # Handle "lump sum" or "total" — estimate monthly
    if 'lump' in stipend_text.lower() or 'total' in stipend_text.lower():
        monthly = monthly / 3

    # Handle yearly amounts (if > 500000, likely annual)
    if monthly > 500000:
        monthly = monthly / 12

    return round(monthly, 2)


def normalize_duration(duration_text: str) -> int:
    """
    Convert duration text to months.

    Handles:
        "3 Months"
        "3 months"
        "2-3 Months"
        "6 weeks"
        "1 Year"
    """
    if not duration_text:
        return 0

    text = duration_text.strip().lower()
    # Only match actual numbers (digits, optionally with decimal point between digits)
    numbers = re.findall(r'\d+(?:\.\d+)?', text)
    if not numbers:
        return 0

    try:
        value = float(numbers[0])
        if len(numbers) >= 2:
            value = float(numbers[1])
    except (ValueError, TypeError):
        return 0

    if 'week' in text:
        return max(1, int(value / 4.33))
    if 'year' in text:
        return int(value * 12)

    return max(1, int(value))


def extract_applicant_count(text: str) -> int:
    """Extract applicant count from text like '2.3K applicants' or '450 Applicants'."""
    if not text:
        return 0
    text = text.strip().lower()
    k_match = re.search(r'([\d.]+)\s*k', text)
    if k_match:
        return int(float(k_match.group(1)) * 1000)
    numbers = re.findall(r'\d+', text)
    if numbers:
        return int(numbers[0])
    return 0


def detect_ppo(text: str) -> bool:
    """Detect if listing mentions PPO (Pre-Placement Offer)."""
    if not text:
        return False
    text_lower = text.lower()
    ppo_patterns = [
        'ppo', 'pre-placement offer', 'pre placement offer',
        'pre-placement', 'permanent position', 'full-time conversion',
        'full time offer', 'convert to full', 'fto',
    ]
    return any(p in text_lower for p in ppo_patterns)


def detect_wfh(text: str) -> bool:
    """Detect if listing is work from home / remote."""
    if not text:
        return False
    text_lower = text.lower()
    wfh_patterns = [
        'work from home', 'wfh', 'remote', 'work-from-home',
        'virtual', 'anywhere', 'home based', 'flexible location',
    ]
    return any(p in text_lower for p in wfh_patterns)


def parse_posted_days(text: str) -> int:
    """Parse 'X days ago' text to integer days."""
    if not text:
        return 0
    text_lower = text.strip().lower()
    if 'today' in text_lower or 'just now' in text_lower:
        return 0
    if 'yesterday' in text_lower:
        return 1
    match = re.search(r'(\d+)\s*day', text_lower)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d+)\s*week', text_lower)
    if match:
        return int(match.group(1)) * 7
    match = re.search(r'(\d+)\s*month', text_lower)
    if match:
        return int(match.group(1)) * 30
    return 0


def generate_batch_id(source: str) -> str:
    """Generate a unique batch ID for tracking."""
    timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{source}_{timestamp}_{short_uuid}"


def _portal_delay(portal: str):
    """Apply portal-specific random delay for anti-detection."""
    limits = PORTAL_RATE_LIMITS.get(portal, {"delay_range": (3, 8)})
    delay = random.uniform(*limits["delay_range"])
    time.sleep(delay)


# ============================================================
# AI RELEVANCE FILTER — v0.2 (MBA + Data/AI ONLY, no sales)
# ============================================================

# Positive signals: titles/descriptions that ARE relevant for MBA/Data/AI
MBA_POSITIVE_KEYWORDS = [
    # Core MBA
    'mba', 'management trainee', 'business analyst', 'strategy',
    'consulting', 'brand management', 'product management', 'product manager',
    'corporate finance', 'investment banking', 'equity research', 'venture capital',
    'private equity', 'market research', 'supply chain', 'operations management',
    'financial analyst', 'business development', 'management consulting',
    'marketing manager', 'marketing analyst', 'digital marketing', 'growth',
    'revenue', 'pricing', 'category management', 'trade marketing',
    'corporate strategy', 'business intelligence', 'project management',
    'program management', 'general management', 'leadership', 'planning',
    # Data & Analytics
    'data analyst', 'data science', 'data scientist', 'data engineering',
    'analytics', 'business analytics', 'quantitative', 'statistical',
    'machine learning', 'deep learning', 'nlp', 'natural language',
    'computer vision', 'predictive', 'forecasting', 'dashboarding',
    'visualization', 'tableau', 'power bi', 'sql', 'python', 'r programming',
    'big data', 'data warehouse', 'etl', 'data pipeline', 'bi analyst',
    'research analyst', 'insights', 'modeling',
    # AI/ML
    'artificial intelligence', 'ai engineer', 'ml engineer', 'ai/ml',
    'generative ai', 'llm', 'prompt engineering', 'ai research',
    'neural network', 'tensorflow', 'pytorch', 'transformer',
    # Finance
    'finance', 'accounting', 'audit', 'risk', 'compliance',
    'treasury', 'credit', 'underwriting', 'actuarial', 'wealth management',
    'portfolio', 'fintech', 'financial planning', 'valuation', 'merger',
    # HR & Ops (MBA relevant)
    'hr analytics', 'people analytics', 'talent management',
    'organizational development', 'compensation', 'hrbp',
    'operations analyst', 'process improvement', 'lean', 'six sigma',
]

# Negative signals: titles/descriptions that are NOT relevant
SALES_NEGATIVE_KEYWORDS = [
    'door to door', 'door-to-door', 'field sales', 'telecaller', 'telecalling',
    'tele caller', 'tele calling', 'cold calling', 'cold-calling',
    'telesales', 'tele sales', 'direct sales', 'street marketing',
    'pamphlet distribution', 'flyer distribution', 'canvassing',
    'appointment setter', 'lead generation executive', 'bpo voice',
    'outbound calling', 'inbound calling', 'call center', 'call centre',
    'medical representative', 'pharma sales', 'insurance agent',
    'real estate agent', 'property sales', 'territory sales',
    'area sales', 'sales executive', 'sales officer', 'sales associate',
    'retail sales', 'counter sales', 'shop assistant', 'store keeper',
    'delivery boy', 'delivery agent', 'rider', 'driver',
    'packing', 'warehouse helper', 'loading', 'manual labor',
    'security guard', 'watchman', 'sweeper', 'cleaner',
    'beautician', 'salon', 'tailoring', 'stitching',
    'cook', 'chef assistant', 'waiter', 'housekeeping',
]

# Strong negative: if these appear in title (not just description), reject
TITLE_BLOCKLIST = [
    'telecaller', 'telecalling', 'cold calling', 'door to door',
    'field sales executive', 'sales executive', 'tele sales',
    'delivery boy', 'delivery agent', 'packing helper',
    'security guard', 'watchman', 'beautician',
    'medical representative', 'pharma rep', 'insurance advisor',
    'real estate', 'property advisor',
]


def is_mba_relevant(title: str, company: str = "", description: str = "",
                    category: str = "") -> Tuple[bool, str]:
    """
    AI-style relevance filter for MBA/Data/AI jobs.
    Returns (is_relevant, reason).
    
    Logic:
      1. Title blocklist → instant reject
      2. Positive keyword match in title → accept
      3. Positive keyword match in description → accept (with lower confidence)
      4. Negative keyword match in title → reject
      5. Category-based filter
      6. Default: accept (let AI enricher handle later)
    """
    title_lower = title.lower().strip()
    desc_lower = (description or "").lower()
    cat_lower = (category or "").lower()

    # Step 1: Title blocklist — instant reject
    for blocked in TITLE_BLOCKLIST:
        if blocked in title_lower:
            return False, f"blocked_title:{blocked}"

    # Step 2: Strong negative in title
    for neg in SALES_NEGATIVE_KEYWORDS:
        if neg in title_lower:
            return False, f"neg_title:{neg}"

    # Step 3: Positive keyword in title — instant accept
    for pos in MBA_POSITIVE_KEYWORDS:
        if pos in title_lower:
            return True, f"pos_title:{pos}"

    # Step 4: Check description for strong signals
    pos_desc_count = sum(1 for pos in MBA_POSITIVE_KEYWORDS if pos in desc_lower)
    neg_desc_count = sum(1 for neg in SALES_NEGATIVE_KEYWORDS if neg in desc_lower)

    if neg_desc_count >= 3 and pos_desc_count == 0:
        return False, f"neg_desc:{neg_desc_count}_hits"

    if pos_desc_count >= 2:
        return True, f"pos_desc:{pos_desc_count}_hits"

    # Step 5: Category filter — accept known MBA categories
    mba_categories = [
        'finance', 'marketing', 'operations', 'analytics', 'data_science',
        'management', 'consulting', 'human_resources', 'product_management',
        'business_development', 'strategy', 'general_management',
    ]
    if cat_lower in mba_categories:
        return True, f"cat_match:{cat_lower}"

    # Step 6: If "intern" in title and no negative signals, accept
    if 'intern' in title_lower and neg_desc_count == 0:
        return True, "intern_no_neg"

    # Default: accept with low confidence (let dedup/enricher handle)
    return True, "default_accept"


def extract_skills_from_text(text: str) -> List[str]:
    """Extract skills from description text using pattern matching."""
    if not text:
        return []

    skills = set()
    text_lower = text.lower()

    # Common skill patterns
    skill_patterns = [
        'python', 'java', 'javascript', 'sql', 'excel', 'r programming',
        'tableau', 'power bi', 'powerbi', 'sas', 'spss', 'stata',
        'machine learning', 'deep learning', 'tensorflow', 'pytorch',
        'nlp', 'computer vision', 'data analysis', 'data visualization',
        'financial modeling', 'valuation', 'dcf', 'lbo',
        'digital marketing', 'seo', 'sem', 'google analytics',
        'social media marketing', 'content marketing', 'email marketing',
        'market research', 'competitive analysis', 'swot',
        'supply chain management', 'logistics', 'inventory management',
        'project management', 'agile', 'scrum', 'jira',
        'communication', 'presentation', 'leadership', 'teamwork',
        'ms office', 'microsoft office', 'powerpoint', 'word',
        'adobe', 'photoshop', 'canva', 'figma',
        'salesforce', 'hubspot', 'crm', 'erp', 'sap',
        'html', 'css', 'react', 'node', 'aws', 'azure', 'gcp',
        'spark', 'hadoop', 'mongodb', 'postgresql', 'mysql',
        'pandas', 'numpy', 'scikit-learn', 'keras',
        'git', 'docker', 'kubernetes', 'linux',
        'risk management', 'compliance', 'audit',
        'strategic planning', 'business strategy',
    ]

    for skill in skill_patterns:
        if skill in text_lower:
            skills.add(skill.title())

    # Extract from "Skills required:" or "Key Skills:" sections
    skills_section = re.search(
        r'(?:skills?\s*required|key\s*skills?|skill\s*set|requirements?)[\s:]+([^\n]+(?:\n(?![A-Z])[^\n]+)*)',
        text, re.IGNORECASE
    )
    if skills_section:
        raw = skills_section.group(1)
        for s in re.split(r'[,;•·\-|\n]+', raw):
            s = s.strip().strip('.')
            if 2 < len(s) < 40:
                skills.add(s.title())

    return list(skills)[:15]  # Cap at 15 skills


def extract_requirements_from_text(text: str) -> List[str]:
    """Extract requirements from description text."""
    if not text:
        return []

    requirements = []

    # Look for requirements sections
    req_section = re.search(
        r'(?:requirements?|who\s+can\s+apply|eligibility|qualifications?)[\s:]+(.+?)(?:(?:responsibilities|about\s+|perks|benefits|skills|apply\s+now|how\s+to|stipend)|$)',
        text, re.IGNORECASE | re.DOTALL
    )
    if req_section:
        raw = req_section.group(1)
        for line in re.split(r'[\n•·\-]+', raw):
            line = line.strip().strip('.')
            if 10 < len(line) < 200:
                requirements.append(line)

    return requirements[:10]


def extract_responsibilities_from_text(text: str) -> List[str]:
    """Extract responsibilities from description text."""
    if not text:
        return []

    responsibilities = []

    resp_section = re.search(
        r'(?:responsibilities|what\s+you.?ll\s+do|job\s+description|role|key\s+deliverables|day\s+to\s+day)[\s:]+(.+?)(?:(?:requirements?|who\s+can\s+apply|eligibility|qualifications?|perks|benefits|skills|apply\s+now)|$)',
        text, re.IGNORECASE | re.DOTALL
    )
    if resp_section:
        raw = resp_section.group(1)
        for line in re.split(r'[\n•·\-]+', raw):
            line = line.strip().strip('.')
            if 10 < len(line) < 200:
                responsibilities.append(line)

    return responsibilities[:10]


def extract_perks_from_text(text: str) -> List[str]:
    """Extract perks from description text."""
    if not text:
        return []

    perks = []

    perks_section = re.search(
        r'(?:perks|benefits|what\s+we\s+offer|why\s+join|we\s+offer)[\s:]+(.+?)(?:(?:requirements?|responsibilities|how\s+to|apply\s+now)|$)',
        text, re.IGNORECASE | re.DOTALL
    )
    if perks_section:
        raw = perks_section.group(1)
        for line in re.split(r'[\n•·,;]+', raw):
            line = line.strip().strip('.')
            if 3 < len(line) < 100:
                perks.append(line)

    # Also check for common perk keywords
    perk_keywords = {
        'certificate': 'Certificate', 'letter of recommendation': 'Letter of Recommendation',
        'lor': 'Letter of Recommendation', 'flexible work': 'Flexible Work Hours',
        'work from home': 'Work From Home', 'free meals': 'Free Meals',
        'health insurance': 'Health Insurance', 'mentorship': 'Mentorship',
        'pre-placement': 'PPO Opportunity', 'ppo': 'PPO Opportunity',
        'travel allowance': 'Travel Allowance', 'accommodation': 'Accommodation',
    }
    text_lower = text.lower()
    for kw, label in perk_keywords.items():
        if kw in text_lower and label not in perks:
            perks.append(label)

    return perks[:10]


def extract_deadline_from_text(text: str) -> str:
    """Extract application deadline from text."""
    if not text:
        return ""

    # Look for deadline/apply by patterns
    deadline_match = re.search(
        r'(?:deadline|apply\s+by|last\s+date|closing\s+date|applications?\s+close)[\s:]+(\d{1,2}[\s/\-]\w+[\s/\-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})',
        text, re.IGNORECASE
    )
    if deadline_match:
        return deadline_match.group(1).strip()

    # ISO format dates
    iso_match = re.search(r'(?:deadline|apply\s+by|last\s+date)[\s:]+(\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
    if iso_match:
        return iso_match.group(1)

    return ""


def enrich_listing_from_description(listing) -> None:
    """
    Enrich a RawListing with extracted data from its description text.
    Fills: skills, requirements, responsibilities, perks, deadline.
    """
    desc = listing.description_text or ""
    if not desc:
        return

    if not listing.skills:
        listing.skills = extract_skills_from_text(desc)

    if not listing.requirements:
        listing.requirements = extract_requirements_from_text(desc)

    if not listing.responsibilities:
        listing.responsibilities = extract_responsibilities_from_text(desc)

    if not listing.perks:
        listing.perks = extract_perks_from_text(desc)

    if not listing.deadline:
        listing.deadline = extract_deadline_from_text(desc)

    # Build tags
    if not listing.tags:
        tags = []
        if listing.category:
            tags.append(listing.category)
        if listing.is_ppo:
            tags.append('PPO')
        if listing.is_wfh:
            tags.append('WFH')
        if listing.sector:
            tags.append(listing.sector)
        listing.tags = tags


# ============================================================
# DIRECT SUPABASE SYNC FROM SCRAPER (v0.2)
# ============================================================

def sync_listings_to_supabase(listings: list, batch_id: str = "") -> int:
    """
    Directly sync scraped listings to Supabase with ALL fields.
    Called after each portal scrape for immediate availability.
    """
    try:
        from core.supabase_client import is_operational
        if not is_operational():
            return 0

        from core.supabase_db import SupabaseJobDB

        jobs = []
        for listing in listings:
            if hasattr(listing, 'to_supabase_dict'):
                jobs.append(listing.to_supabase_dict())
            elif isinstance(listing, dict):
                jobs.append(listing)

        if not jobs:
            return 0

        count = SupabaseJobDB.insert_latest_jobs(jobs, batch_id)
        if count > 0:
            logger.info(f"[{AGENT_ID}] Direct Supabase sync: {count}/{len(jobs)} jobs ({batch_id})")
        return count

    except Exception as e:
        logger.debug(f"[{AGENT_ID}] Direct Supabase sync error: {e}")
        return 0


# ============================================================
# INTERNSHALA SCRAPER — PRISM v0.1 (Mobile Ajax API)
# ============================================================

class InternshalaHarvester:
    """
    PRISM v0.1: Deep scraper for Internshala using Mobile Ajax API.

    Strategy:
        PRIMARY: POST to /internship_listings (mobile JSON endpoint)
            - Sends category_id in payload for MBA-specific results
            - Returns clean JSON (title, company, stipend, location)
            - Headers: app-version: 5.x, mobile User-Agent
        FALLBACK: Ajax search endpoint /internships/ajax/search_ajax
            - If mobile API returns 403 or empty results
        FALLBACK 2: Standard HTML scraping with BeautifulSoup
            - If both API methods fail

    Session Management:
        - Cookie: _internshala_session (admin provides once)
        - CSRF token extracted from initial page load
        - Rotated every 10 requests

    Rate Control:
        - 1 request every 2-4s with random jitter
        - Max 50 requests per scrape session
        - 10 pages max per category
        - Human-mimicry delays between categories (5-15s)

    Expected Yield: 200-400 listings per full scrape.
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()
        self.config = get_config()
        self.batch_id = ""
        self._session_cookie = os.environ.get("INTERNSHALA_SESSION_COOKIE", "")
        self._csrf_token = ""
        self._request_count = 0
        self._max_requests_per_session = 50

    def scrape_all_categories(self, pages_per_category: int = 5) -> List[RawListing]:
        """
        Scrape all MBA categories from Internshala.

        Strategy: Try mobile API first, fallback to Ajax, then HTML.
        Respects rate limits and session rotation.
        """
        self.batch_id = generate_batch_id("internshala")
        self._request_count = 0
        all_listings = []
        total_start = time.time()

        logger.info(f"[{AGENT_ID}] Starting Internshala PRISM scrape "
                     f"(batch: {self.batch_id}, strategy: mobile_ajax_api)")

        # Try to extract CSRF token from initial page load
        self._extract_csrf_token()

        categories = list(INTERNSHALA_CATEGORY_IDS.items())
        random.shuffle(categories)  # Randomize order for stealth

        for cat_name, cat_info in categories:
            if self._request_count >= self._max_requests_per_session:
                logger.info(f"[{AGENT_ID}] Session limit reached ({self._max_requests_per_session} reqs)")
                break

            try:
                # PRIMARY: Mobile Ajax API
                category_listings = self._scrape_category_mobile_api(
                    cat_name, cat_info, max_pages=pages_per_category
                )

                # FALLBACK: Standard Ajax if mobile API yields nothing
                if not category_listings:
                    logger.info(f"[{AGENT_ID}] Mobile API empty for {cat_name}, trying Ajax")
                    category_listings = self._scrape_category_ajax(
                        cat_name, cat_info, max_pages=min(3, pages_per_category)
                    )

                # FALLBACK 2: HTML scraping
                if not category_listings:
                    logger.info(f"[{AGENT_ID}] Ajax empty for {cat_name}, trying HTML")
                    category_listings = self._scrape_category_html(
                        cat_name, cat_info["slug"], max_pages=min(2, pages_per_category)
                    )

                all_listings.extend(category_listings)
                logger.info(f"[{AGENT_ID}] Internshala/{cat_name}: {len(category_listings)} listings")

                # Inter-category delay (human-mimicry)
                _portal_delay("internshala")

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Internshala/{cat_name} error: {e}")
                continue

        # Store in database
        if all_listings:
            inserted = self.db.insert_raw_listings_batch(all_listings)
            logger.info(
                f"[{AGENT_ID}] Internshala complete: "
                f"{len(all_listings)} scraped, {inserted} new "
                f"({time.time() - total_start:.1f}s, {self._request_count} reqs)"
            )

        return all_listings

    def _extract_csrf_token(self):
        """Extract CSRF token from Internshala page for session auth."""
        try:
            response = self.stealth.get(
                INTERNSHALA_BASE_URL,
                site='internshala',
                auto_delay=True,
            )
            if response and response.get('status_code') == 200:
                html = response.get('text', '')
                # Extract meta CSRF token
                csrf_match = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
                if csrf_match:
                    self._csrf_token = csrf_match.group(1)
                    logger.debug(f"[{AGENT_ID}] Internshala CSRF token extracted")
                # Also try cookie-based CSRF
                cookies = response.get('cookies', {})
                if '_internshala_csrf' in cookies:
                    self._csrf_token = cookies['_internshala_csrf']
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] CSRF extraction failed: {e}")

    def _scrape_category_mobile_api(self, cat_name: str, cat_info: Dict,
                                      max_pages: int = 5) -> List[RawListing]:
        """
        PRISM v0.1 PRIMARY: Scrape via Internshala Mobile Ajax API.

        POST /api/v1/internship_listings
        Payload: {"category_id": "4", "page": 1, "sort": "recency"}
        Headers: app-version: 5.67, mobile User-Agent
        Returns: JSON with internship objects
        """
        listings = []
        seen_urls: Set[str] = set()

        mobile_headers = {
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'app-version': '5.67',
            'app-platform': 'android',
            'app-build': '567',
            'User-Agent': random.choice(MOBILE_USER_AGENTS),
            'X-Requested-With': 'com.internshala.app',
            'Connection': 'keep-alive',
        }

        if self._csrf_token:
            mobile_headers['X-CSRF-Token'] = self._csrf_token
        if self._session_cookie:
            mobile_headers['Cookie'] = f'_internshala_session={self._session_cookie}'

        for page in range(1, max_pages + 1):
            if self._request_count >= self._max_requests_per_session:
                break

            try:
                payload = {
                    "category_id": cat_info.get("id", ""),
                    "page": page,
                    "sort": "recency",
                    "type": "internship",
                    "work_from_home": "",
                }

                response = self.stealth.post(
                    INTERNSHALA_MOBILE_API,
                    site='internshala',
                    json_data=payload,
                    headers=mobile_headers,
                    auto_delay=True,
                )

                self._request_count += 1

                if not response or response.get('status_code', 0) != 200:
                    logger.debug(f"[{AGENT_ID}] Internshala mobile API {cat_name} p{page}: "
                                 f"status {response.get('status_code', 'N/A') if response else 'N/A'}")
                    break

                # Parse JSON response
                data = response.get('json', {})
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        break

                internships = data.get('internships', data.get('data', data.get('listings', [])))
                if not internships:
                    # Try alternate response structure
                    if isinstance(data, list):
                        internships = data
                    else:
                        break

                for item in internships:
                    try:
                        listing = self._parse_mobile_api_item(item, cat_name)
                        if listing and listing.url and listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"[{AGENT_ID}] Parse error: {e}")
                        continue

                # Inter-page delay
                time.sleep(random.uniform(2, 4))

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Internshala mobile API error {cat_name} p{page}: {e}")
                break

        return listings

    def _parse_mobile_api_item(self, item: Dict, category: str) -> Optional[RawListing]:
        """Parse a single internship from the mobile API JSON response — ENRICHED v0.2."""
        listing = RawListing()
        listing.source = "internshala"
        listing.category = category
        listing.batch_id = self.batch_id

        # Title
        listing.title = item.get('title', item.get('profile_name', '')).strip()

        # Company
        listing.company = item.get('company_name', item.get('company', '')).strip()

        # URL
        intern_id = item.get('id', item.get('internship_id', ''))
        slug = item.get('slug', item.get('url', ''))
        if slug:
            listing.url = urljoin(INTERNSHALA_BASE_URL, slug)
        elif intern_id:
            listing.url = f"{INTERNSHALA_BASE_URL}/internship/detail/{intern_id}"

        # Location
        locations = item.get('locations', item.get('location_names', []))
        if isinstance(locations, list):
            listing.location = ', '.join([l.get('string', l) if isinstance(l, dict) else str(l) for l in locations[:3]])
        elif isinstance(locations, str):
            listing.location = locations

        # Work from home
        listing.is_wfh = item.get('work_from_home', False) or item.get('is_work_from_home', False)

        # Stipend
        stipend = item.get('stipend', item.get('salary', ''))
        if isinstance(stipend, dict):
            stipend_min = stipend.get('min', stipend.get('salary1', 0))
            stipend_max = stipend.get('max', stipend.get('salary2', 0))
            listing.stipend = f"₹{stipend_min} - ₹{stipend_max}/month"
            listing.stipend_normalized = (float(stipend_min) + float(stipend_max)) / 2
        elif isinstance(stipend, str):
            listing.stipend = stipend
            listing.stipend_normalized = normalize_stipend(stipend)
        elif isinstance(stipend, (int, float)):
            listing.stipend = f"₹{stipend}/month"
            listing.stipend_normalized = float(stipend)

        # Duration
        duration = item.get('duration', '')
        if isinstance(duration, str):
            listing.duration = duration
            listing.duration_months = normalize_duration(duration)
        elif isinstance(duration, (int, float)):
            listing.duration_months = int(duration)
            listing.duration = f"{int(duration)} months"

        # Applicants — try multiple field names
        applicants = (item.get('applications_count') or item.get('no_of_applications')
                      or item.get('total_applications') or item.get('applicants_count') or 0)
        try:
            listing.applicants = int(applicants) if applicants else 0
        except (ValueError, TypeError):
            listing.applicants = 0

        # Openings
        openings = item.get('no_of_openings', item.get('openings', 1))
        try:
            listing.openings = max(1, int(openings) if openings else 1)
        except (ValueError, TypeError):
            listing.openings = 1

        # PPO detection
        listing.is_ppo = item.get('is_ppo', False) or detect_ppo(
            f"{listing.title} {item.get('description', '')}"
        )

        # Posted date — use real portal date
        posted = item.get('posted_on', item.get('start_date', item.get('posted_by_label', '')))
        if posted:
            listing.posted_days_ago = parse_posted_days(str(posted))
            # Try to compute real date
            if listing.posted_days_ago > 0:
                real_date = datetime.now(IST) - timedelta(days=listing.posted_days_ago)
                listing.posted_date = real_date.isoformat()

        # Deadline / Apply by
        deadline = item.get('deadline', item.get('expiry_date', item.get('apply_by', '')))
        if deadline:
            listing.deadline = str(deadline)

        # Start date
        start = item.get('start_date', item.get('internship_start_date', ''))
        if start and not listing.posted_date:  # Don't overwrite posted_date
            listing.start_date = str(start)

        # Description
        listing.description_text = item.get('description', item.get('about', ''))[:5000]

        # Skills — extract from API fields
        skills_data = item.get('skills', item.get('skill_names', item.get('preferred_skills', [])))
        if isinstance(skills_data, list):
            listing.skills = [s.get('name', s) if isinstance(s, dict) else str(s) for s in skills_data[:15]]
        elif isinstance(skills_data, str) and skills_data:
            listing.skills = [s.strip() for s in skills_data.split(',') if s.strip()]

        # Perks
        perks_data = item.get('perks', item.get('perk_names', []))
        if isinstance(perks_data, list):
            listing.perks = [p.get('name', p) if isinstance(p, dict) else str(p) for p in perks_data[:10]]
        elif isinstance(perks_data, str) and perks_data:
            listing.perks = [p.strip() for p in perks_data.split(',') if p.strip()]

        # Company logo
        logo = item.get('company_logo', item.get('logo', ''))
        if logo:
            listing.company_logo = logo if logo.startswith('http') else f"https://internshala.com/{logo}"

        # v0.2: AI relevance filter
        is_relevant, reason = is_mba_relevant(
            listing.title, listing.company, listing.description_text, listing.category
        )
        if not is_relevant:
            logger.debug(f"[{AGENT_ID}] Filtered: '{listing.title}' ({reason})")
            return None

        # v0.2: Enrich from description text
        enrich_listing_from_description(listing)

        return listing if listing.title and listing.url else None

    def _scrape_category_ajax(self, cat_name: str, cat_info: Dict,
                                max_pages: int = 3) -> List[RawListing]:
        """
        FALLBACK 1: Scrape via Internshala Ajax search endpoint.

        POST /internships/ajax/search_ajax
        Form data: category_ids[]=4&page=1&sort=recency
        """
        listings = []
        seen_urls: Set[str] = set()

        ajax_headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': random.choice(MOBILE_USER_AGENTS),
            'Referer': f'{INTERNSHALA_BASE_URL}/internships/{cat_info["slug"]}',
            'Origin': INTERNSHALA_BASE_URL,
        }

        if self._csrf_token:
            ajax_headers['X-CSRF-Token'] = self._csrf_token

        for page in range(1, max_pages + 1):
            if self._request_count >= self._max_requests_per_session:
                break

            try:
                form_data = {
                    'category_ids[]': cat_info.get('id', ''),
                    'page': str(page),
                    'sort': 'recency',
                    'type': 'internship',
                }

                response = self.stealth.post(
                    INTERNSHALA_AJAX_URL,
                    site='internshala',
                    data=form_data,
                    headers=ajax_headers,
                    auto_delay=True,
                )

                self._request_count += 1

                if not response or response.get('status_code', 0) != 200:
                    break

                # Ajax response often contains HTML fragment in JSON
                data = response.get('json', {})
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        # It might be raw HTML
                        data = {'html': response.get('text', '')}

                html_fragment = data.get('html', data.get('internshipTeaserList', ''))
                if html_fragment and BeautifulSoup:
                    soup = BeautifulSoup(html_fragment, 'html.parser')
                    cards = soup.select('.individual_internship, .internship_meta, [data-internship_id]')
                    for card in cards:
                        listing = self._parse_html_card(card, cat_name)
                        if listing and listing.url and listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            listings.append(listing)

                time.sleep(random.uniform(2, 4))

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Internshala Ajax error: {e}")
                break

        return listings

    def _scrape_category_html(self, cat_name: str, slug: str,
                                max_pages: int = 2) -> List[RawListing]:
        """
        FALLBACK 2: Standard HTML scraping with BeautifulSoup.
        """
        listings = []
        seen_urls: Set[str] = set()

        for page in range(1, max_pages + 1):
            if self._request_count >= self._max_requests_per_session:
                break

            try:
                url = f"{INTERNSHALA_LISTINGS_URL}/{slug}"
                if page > 1:
                    url += f"/page-{page}"

                response = self.stealth.get(url, site='internshala', auto_delay=True)
                self._request_count += 1

                if not response or response.get('status_code', 0) != 200:
                    break

                html = response.get('text', '')
                if not html or not BeautifulSoup:
                    break

                soup = BeautifulSoup(html, 'html.parser')
                cards = soup.select('.individual_internship, .internship_meta, [data-internship_id]')
                if not cards:
                    cards = soup.select('.container-fluid .individual_internship_header')
                if not cards:
                    cards = soup.select('[class*="internship"]')

                for card in cards:
                    listing = self._parse_html_card(card, cat_name)
                    if listing and listing.url and listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        listings.append(listing)

                _portal_delay("internshala")

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Internshala HTML error: {e}")
                break

        return listings

    def _parse_html_card(self, card, category: str) -> Optional[RawListing]:
        """Parse an Internshala listing card HTML element — ENRICHED v0.2."""
        listing = RawListing()
        listing.source = "internshala"
        listing.category = category
        listing.batch_id = self.batch_id

        # Title
        title_elem = card.select_one(
            '.heading_4_5 a, .job-title-href, h3 a, .profile a, '
            '[class*="heading"] a, .internship_heading a'
        )
        if title_elem:
            listing.title = title_elem.get_text(strip=True)
            href = title_elem.get('href', '')
            if href:
                listing.url = urljoin(INTERNSHALA_BASE_URL, href)

        # Company
        company_elem = card.select_one(
            '.heading_6, .company_name, .company-name, '
            'p.company_name, [class*="company"] a, .link_display_like_text'
        )
        if company_elem:
            listing.company = company_elem.get_text(strip=True)

        # Location
        location_elem = card.select_one(
            '.locations, .individual_internship_details .item_body:first-child, '
            '[class*="location"], #location_names a, .location_link'
        )
        if location_elem:
            listing.location = location_elem.get_text(strip=True)

        # Stipend
        stipend_elem = card.select_one(
            '.stipend, [class*="stipend"], .salary, .stipend_container_desktop'
        )
        if stipend_elem:
            listing.stipend = stipend_elem.get_text(strip=True)
            listing.stipend_normalized = normalize_stipend(listing.stipend)

        # Duration
        duration_elem = card.select_one(
            '.desktop-text .item_body:nth-child(2), [class*="duration"]'
        )
        if duration_elem:
            listing.duration = duration_elem.get_text(strip=True)
            listing.duration_months = normalize_duration(listing.duration)

        # Applicants
        applicant_elem = card.select_one('[class*="applicant"], .applications_message')
        if applicant_elem:
            listing.applicants = extract_applicant_count(applicant_elem.get_text(strip=True))

        # PPO / WFH
        full_text = card.get_text(' ', strip=True)
        listing.is_ppo = detect_ppo(full_text)
        listing.is_wfh = detect_wfh(full_text)

        # v0.2: Skills from HTML
        skill_elems = card.select('.tags .badge, .skill_tag, [class*="skill"] span, .round_tabs')
        if skill_elems:
            listing.skills = [s.get_text(strip=True) for s in skill_elems[:15] if s.get_text(strip=True)]

        # v0.2: Posted date from HTML
        posted_elem = card.select_one('[class*="posted"], .status-success, .posted_message')
        if posted_elem:
            listing.posted_days_ago = parse_posted_days(posted_elem.get_text(strip=True))
            if listing.posted_days_ago > 0:
                real_date = datetime.now(IST) - timedelta(days=listing.posted_days_ago)
                listing.posted_date = real_date.isoformat()

        # v0.2: Openings from HTML
        openings_elem = card.select_one('[class*="opening"]')
        if openings_elem:
            nums = re.findall(r'\d+', openings_elem.get_text(strip=True))
            if nums:
                listing.openings = int(nums[0])

        # v0.2: AI relevance filter
        is_relevant, reason = is_mba_relevant(
            listing.title, listing.company, full_text, listing.category
        )
        if not is_relevant:
            return None

        return listing if listing.title and listing.url else None

    def scrape_category(self, category: str, max_pages: int = 5) -> List[RawListing]:
        """Legacy interface: scrape by slug name."""
        cat_info = INTERNSHALA_CATEGORY_IDS.get(category, {})
        if not cat_info:
            cat_info = {"id": "", "slug": f"{category}-internship"}
        return self._scrape_category_mobile_api(category, cat_info, max_pages)


# ============================================================
# NAUKRI SCRAPER — PRISM v0.1 (API v2 PRIMARY)
# ============================================================

class NaukriScraper:
    """
    PRISM v0.1: Naukri scraper with Direct API v2 as PRIMARY.

    Strategy:
        PRIMARY: GET jobapi/v2/search (JSON)
            - Headers: appid=109, systemid=Naukri
            - gid=LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE
            - X-Requested-With: XMLHttpRequest
            - Returns: JSON with jobDetails array
        FALLBACK 1: DDG site dorks (site:naukri.com)
            - If API returns 403/406/429
            - 16 MBA-specific dork queries
        FALLBACK 2: Cloudflare Browser Rendering
            - For individual JD extraction from JS-rendered pages
            - Used when API gives listing URLs but no description

    Session Management:
        - No login required for API v2 search
        - Headers must include appid=109, systemid=Naukri
        - Rotate User-Agent every 5 requests
        - Desktop UA for API, Mobile for DDG

    Rate Control:
        - 30 req/hour for API v2
        - 8 pages per session max
        - 10-20s delays between API calls
        - 6-12s delays between DDG queries

    Expected Yield: 50-100 listings per scrape.
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()
        self.batch_id = ""
        self._ddg = None
        self._request_count = 0
        self._api_available = True  # Tracks if API v2 is responding

    def _get_ddg(self):
        """Lazy-load DuckDuckGo search."""
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    logger.warning(f"[{AGENT_ID}] ddgs not installed")
        return self._ddg

    def scrape_mba_internships(self, max_pages: int = 5) -> List[RawListing]:
        """
        PRISM v0.1.1: Scrape MBA internships from Naukri.

        Strategy: API v2 (PRIMARY) → API v3 (SECONDARY) → DDG dorks (FALLBACK)
        Enhanced: More queries, higher limits, dual-API approach.
        """
        self.batch_id = generate_batch_id("naukri")
        self._request_count = 0
        all_listings = []

        logger.info(f"[{AGENT_ID}] Starting Naukri PRISM scrape "
                     f"(batch: {self.batch_id}, strategy: api_v2_v3_primary)")

        # ── PRIMARY: Naukri API v2 ──
        api_listings = self._scrape_api_v2(max_pages=max_pages)
        all_listings.extend(api_listings)

        if api_listings:
            logger.info(f"[{AGENT_ID}] Naukri API v2 yielded {len(api_listings)} listings")
        else:
            logger.warning(f"[{AGENT_ID}] Naukri API v2 yielded 0 — trying API v3")
            self._api_available = False

        # ── SECONDARY: Try API v3 if v2 failed or yielded moderate results ──
        if len(api_listings) < 50:
            v3_listings = self._scrape_api_v3(max_pages=max_pages)
            all_listings.extend(v3_listings)
            if v3_listings:
                logger.info(f"[{AGENT_ID}] Naukri API v3 yielded {len(v3_listings)} listings")

        # ── FALLBACK: DDG Dorks ──
        # Always run DDG to catch listings not in API results
        # PRISM v0.2: Run more dorks to catch broader coverage
        max_dorks = 5 if (len(api_listings) >= 50) else 16
        ddg_listings = self._scrape_ddg_dorks(max_dorks=max_dorks)
        all_listings.extend(ddg_listings)

        if ddg_listings:
            logger.info(f"[{AGENT_ID}] Naukri DDG dorks yielded {len(ddg_listings)} listings")

        # Deduplicate by URL
        seen = set()
        unique = []
        for l in all_listings:
            clean_url = l.url.split('?')[0] if l.url else ''
            if clean_url and clean_url not in seen:
                seen.add(clean_url)
                unique.append(l)

        if unique:
            inserted = self.db.insert_raw_listings_batch(unique)
            logger.info(
                f"[{AGENT_ID}] Naukri complete: "
                f"{len(unique)} unique, {inserted} new "
                f"(API v2: {len(api_listings)}, DDG: {len(ddg_listings)})"
            )

        return unique

    def _scrape_api_v2(self, max_pages: int = 5) -> List[RawListing]:
        """
        PRISM v0.1.1 PRIMARY: Naukri Direct API v2 search.

        GET https://www.naukri.com/jobapi/v2/search
        Required headers: appid=109, systemid=Naukri, gid, XHR

        Enhanced: Try multiple jobAge values, increase query coverage.
        """
        listings = []
        seen_urls: Set[str] = set()

        # Shuffle queries for variety
        queries = NAUKRI_MBA_QUERIES.copy()
        random.shuffle(queries)

        queries_used = 0
        # PRISM v0.3: Use ALL available queries for maximum coverage
        max_queries = len(queries)

        for query_info in queries:
            if queries_used >= max_queries:
                break

            for page in range(1, max_pages + 1):
                if self._request_count >= PORTAL_RATE_LIMITS["naukri"]["pages_per_session"] * 4:
                    break

                try:
                    # PRISM v0.2: Alternate between relevance and freshness sorting
                    sort_mode = 'f' if queries_used % 3 == 0 else 'r'

                    params = {
                        'noOfResults': '25',
                        'urlType': 'search_by_keyword',
                        'searchType': 'adv',
                        'keyword': query_info["keyword"],
                        'pageNo': str(page),
                        'experience': query_info.get("experience", "0"),
                        'sort': sort_mode,
                        'jobAge': '60',  # PRISM v0.3: 60 days for maximum coverage
                        'seoKey': '',
                        'src': 'jobsearchDesk',
                    }
                    url = f"{NAUKRI_API_V2_URL}?{urlencode(params)}"

                    # Use desktop UA with Naukri-specific headers
                    headers = NAUKRI_API_HEADERS.copy()
                    headers['User-Agent'] = random.choice(DESKTOP_USER_AGENTS)

                    response = self.stealth.get(
                        url, site='naukri', headers=headers, auto_delay=True
                    )
                    self._request_count += 1

                    if not response:
                        logger.debug(f"[{AGENT_ID}] Naukri API v2: no response")
                        break

                    status = response.get('status_code', 0)

                    if status in (403, 406, 429):
                        logger.warning(f"[{AGENT_ID}] Naukri API v2 returned {status} "
                                       f"— API blocked, switching to fallback")
                        return listings  # Return whatever we have

                    if status != 200:
                        logger.debug(f"[{AGENT_ID}] Naukri API v2: status {status}")
                        break

                    # Parse JSON response
                    data = response.get('json', {})
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except json.JSONDecodeError:
                            break

                    # Naukri API v2 response structure
                    job_details = data.get('jobDetails', data.get('jobs', []))
                    if not job_details:
                        break

                    for job in job_details:
                        try:
                            listing = self._parse_api_v2_job(job)
                            if listing and listing.url and listing.url not in seen_urls:
                                seen_urls.add(listing.url)
                                listings.append(listing)
                        except Exception as e:
                            logger.debug(f"[{AGENT_ID}] Naukri API parse error: {e}")
                            continue

                    # Inter-page delay
                    _portal_delay("naukri")

                except Exception as e:
                    logger.error(f"[{AGENT_ID}] Naukri API v2 error: {e}")
                    break

            queries_used += 1
            # Inter-query delay
            time.sleep(random.uniform(5, 10))

        return listings

    def _scrape_api_v3(self, max_pages: int = 5) -> List[RawListing]:
        """
        PRISM v0.1.1 SECONDARY: Naukri API v3 search.

        GET https://www.naukri.com/jobapi/v3/search
        Similar to v2 but with slightly different params and response format.
        Used as secondary source when v2 yields few results.
        """
        listings = []
        seen_urls: Set[str] = set()

        # Use more queries for v3 — PRISM v0.2
        queries = NAUKRI_MBA_QUERIES.copy()
        random.shuffle(queries)
        max_queries = min(len(queries), 15)  # Was 8 — use more queries

        for idx, query_info in enumerate(queries[:max_queries]):
            for page in range(1, max_pages + 1):
                try:
                    params = {
                        'noOfResults': '20',
                        'urlType': 'search_by_keyword',
                        'searchType': 'adv',
                        'keyword': query_info["keyword"],
                        'pageNo': str(page),
                        'experience': query_info.get("experience", "0"),
                        'sort': 'f',  # Freshness sort for v3
                        'jobAge': '30',  # Wider window for v3
                        'src': 'jobsearchDesk',
                        'latLong': '',
                    }
                    url = f"{NAUKRI_API_V3_URL}?{urlencode(params)}"

                    headers = NAUKRI_API_HEADERS.copy()
                    headers['User-Agent'] = random.choice(DESKTOP_USER_AGENTS)

                    response = self.stealth.get(
                        url, site='naukri', headers=headers, auto_delay=True
                    )
                    self._request_count += 1

                    if not response:
                        break

                    status = response.get('status_code', 0)
                    if status in (403, 406, 429):
                        logger.warning(f"[{AGENT_ID}] Naukri API v3 blocked ({status})")
                        return listings
                    if status != 200:
                        break

                    data = response.get('json', {})
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except json.JSONDecodeError:
                            break

                    # v3 can have different response structures
                    job_details = (data.get('jobDetails', []) or
                                   data.get('jobs', []) or
                                   data.get('data', {}).get('jobs', []))
                    if not job_details:
                        break

                    for job in job_details:
                        try:
                            listing = self._parse_api_v2_job(job)  # Same format
                            if listing and listing.url and listing.url not in seen_urls:
                                seen_urls.add(listing.url)
                                listings.append(listing)
                        except Exception:
                            continue

                    _portal_delay("naukri")

                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] Naukri API v3 error: {e}")
                    break

            # Inter-query delay
            time.sleep(random.uniform(4, 8))

        return listings

    def _parse_api_v2_job(self, job: Dict) -> Optional[RawListing]:
        """Parse a single job from Naukri API v2 response — ENRICHED v0.2."""
        listing = RawListing()
        listing.source = "naukri"
        listing.batch_id = self.batch_id

        # Title
        listing.title = job.get('title', job.get('jobTitle', '')).strip()

        # Company
        listing.company = job.get('companyName', job.get('company', '')).strip()

        # URL
        job_id = job.get('jobId', job.get('id', ''))
        seo_url = job.get('jdURL', job.get('seoUrl', ''))
        if seo_url:
            listing.url = urljoin(NAUKRI_BASE_URL, seo_url)
        elif job_id:
            listing.url = f"{NAUKRI_BASE_URL}/job-listings--{job_id}"

        # Location
        locations = job.get('placeholders', [])
        for ph in locations:
            if isinstance(ph, dict) and ph.get('type') == 'location':
                listing.location = ph.get('label', '')
                break
        if not listing.location:
            listing.location = job.get('location', job.get('ambiguity', {}).get('location', ''))

        # Experience
        exp = job.get('experience', '')
        if isinstance(exp, str) and ('0' in exp or 'fresher' in exp.lower()):
            listing.category = "fresher"

        # Salary/Stipend
        salary = job.get('salary', job.get('placeholders', []))
        if isinstance(salary, str):
            listing.stipend = salary
            listing.stipend_normalized = normalize_stipend(salary)
        elif isinstance(salary, list):
            for ph in salary:
                if isinstance(ph, dict) and ph.get('type') == 'salary':
                    listing.stipend = ph.get('label', '')
                    listing.stipend_normalized = normalize_stipend(listing.stipend)
                    break

        # Description / snippet
        snippet = job.get('jobDescription', job.get('snippet', ''))
        listing.description_text = snippet[:5000] if snippet else ''

        # v0.2: Skills — extract from tagsAndSkills AND separate skills field
        tags = job.get('tagsAndSkills', job.get('skills', ''))
        if isinstance(tags, str) and tags:
            listing.skills = [s.strip() for s in tags.split(',') if s.strip()]
            listing.description_text += f"\nSkills: {tags}"
        elif isinstance(tags, list):
            listing.skills = [str(s).strip() for s in tags if s]

        # v0.2: Applicants
        applicants = (job.get('applicationCount') or job.get('applications')
                      or job.get('numberOfApplications') or 0)
        try:
            listing.applicants = int(applicants)
        except (ValueError, TypeError):
            listing.applicants = 0

        # v0.2: Openings
        openings = job.get('numberOfVacancies', job.get('vacancy', 1))
        try:
            listing.openings = max(1, int(openings) if openings else 1)
        except (ValueError, TypeError):
            listing.openings = 1

        # PPO / WFH detection
        full_text = f"{listing.title} {listing.description_text}"
        listing.is_ppo = detect_ppo(full_text)
        listing.is_wfh = detect_wfh(full_text) or job.get('isRemote', False)

        # v0.2: Posted date — real portal date
        created_date = job.get('createdDate', job.get('footerPlaceholderLabel', ''))
        if created_date:
            listing.posted_days_ago = parse_posted_days(str(created_date))
            if listing.posted_days_ago > 0:
                real_date = datetime.now(IST) - timedelta(days=listing.posted_days_ago)
                listing.posted_date = real_date.isoformat()

        # v0.2: Company logo
        logo = job.get('companyLogo', job.get('logoUrl', ''))
        if logo:
            listing.company_logo = logo

        # v0.2: AI relevance filter
        is_relevant, reason = is_mba_relevant(
            listing.title, listing.company, listing.description_text, listing.category
        )
        if not is_relevant:
            logger.debug(f"[{AGENT_ID}] Naukri filtered: '{listing.title}' ({reason})")
            return None

        # v0.2: Enrich from description
        enrich_listing_from_description(listing)

        return listing if listing.title and listing.url else None

    def _scrape_ddg_dorks(self, max_dorks: int = 14) -> List[RawListing]:
        """
        PRISM v0.1 FALLBACK: Naukri listings via DDG site dorks.
        """
        listings = []
        seen_urls: Set[str] = set()

        ddg = self._get_ddg()
        if not ddg:
            logger.warning(f"[{AGENT_ID}] DDG not available for Naukri fallback")
            return listings

        # PRISM v0.2: DDG dork queries for Naukri — MBA/Data/AI focused, NO sales/tech
        dork_queries = [
            'site:naukri.com "MBA intern" india',
            'site:naukri.com "MBA internship" stipend',
            'site:naukri.com "management trainee" internship india',
            'site:naukri.com "summer internship" MBA 2026',
            'site:naukri.com "marketing intern" stipend india',
            'site:naukri.com "finance intern" OR "financial analyst intern"',
            'site:naukri.com "strategy intern" OR "consulting intern" india',
            'site:naukri.com "operations intern" OR "supply chain intern" india',
            'site:naukri.com "product management intern" OR "product intern"',
            'site:naukri.com "analytics intern" OR "data analyst intern"',
            'site:naukri.com "data science intern" OR "ML intern" india',
            'site:naukri.com "HR intern" OR "human resource intern"',
            'site:naukri.com "brand management intern" OR "category intern"',
            'site:naukri.com "investment banking intern" OR "equity research intern"',
            'site:naukri.com "corporate finance intern" india',
            'site:naukri.com "market research intern" OR "consumer insights"',
            'site:naukri.com "AI intern" OR "artificial intelligence intern" india',
            'site:naukri.com "business analytics intern" OR "business intelligence intern"',
            'site:naukri.com "private equity intern" OR "venture capital intern"',
            'site:naukri.com "PGDM internship" OR "general management intern"',
            'site:naukri.com "digital marketing intern" OR "growth marketing intern"',
            'site:naukri.com "pricing analyst intern" OR "revenue management intern"',
            'site:naukri.com "compliance intern" OR "ESG intern" india',
            'site:naukri.com "M&A intern" OR "corporate development intern"',
        ]

        random.shuffle(dork_queries)
        queries_used = 0

        for query in dork_queries:
            if queries_used >= max_dorks:
                break
            try:
                results = ddg.text(query, region='in-en', max_results=20)
                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    if not url or 'naukri.com' not in url:
                        continue
                    if '/job-listings' in url or re.search(r'naukri\.com/.*-\d+', url):
                        listing = self._parse_dork_result(url, title, body)
                        if listing and listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            listings.append(listing)

                queries_used += 1
                time.sleep(random.uniform(6, 12))

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Naukri DDG dork error: {e}")
                continue

        return listings

    def _parse_dork_result(self, url: str, title: str, body: str) -> Optional[RawListing]:
        """Parse a DDG search result for a Naukri listing."""
        listing = RawListing()
        listing.source = "naukri"
        listing.batch_id = self.batch_id
        listing.url = url.split('?')[0]

        title_parts = [p.strip() for p in title.split(' - ') if p.strip()]
        if title_parts:
            listing.title = title_parts[0]
            if len(title_parts) >= 2:
                company_part = title_parts[1] if len(title_parts) > 2 else ''
                if company_part and 'naukri' not in company_part.lower():
                    listing.company = company_part
            if len(title_parts) >= 3:
                loc_part = title_parts[2] if 'naukri' not in title_parts[2].lower() else ''
                if loc_part:
                    listing.location = loc_part

        listing.description_text = body[:3000] if body else ''
        listing.category = self._detect_category(listing.title)

        full_text = f"{listing.title} {body}"
        listing.is_ppo = detect_ppo(full_text)
        listing.is_wfh = detect_wfh(full_text)

        return listing if listing.title and listing.url else None

    def _detect_category(self, title: str) -> str:
        """Detect MBA category from title text."""
        if not title:
            return "general"
        t = title.lower()
        cats = {
            'marketing': ['marketing', 'brand', 'digital marketing', 'content', 'seo', 'social media'],
            'finance': ['finance', 'financial', 'investment', 'equity', 'banking', 'accounting', 'audit'],
            'consulting': ['consulting', 'strategy', 'management consulting', 'advisory'],
            'operations': ['operations', 'supply chain', 'logistics', 'procurement', 'ops'],
            'data_science': ['data science', 'machine learning', 'ml', 'ai ', 'deep learning'],
            'analytics': ['analytics', 'data analyst', 'business analyst', 'data analysis'],
            'hr': ['hr', 'human resource', 'talent', 'recruitment', 'people'],
            'product': ['product management', 'product manager', 'product intern'],
        }
        for cat, keywords in cats.items():
            if any(kw in t for kw in keywords):
                return cat
        return "general"


# ============================================================
# IIMJOBS SCRAPER — PRISM v0.1 (DDG Site Dorks)
# ============================================================

class IIMJobsScraper:
    """
    PRISM v0.1: IIMjobs scraper via DDG site dorks.

    Strategy:
        PRIMARY: DDG site dorks (site:iimjobs.com "intern")
            - IIMjobs is MBA-specific by design — every listing is relevant
            - Dork queries target MBA sectors + recency
        FALLBACK: Direct HTML scraping with stealth
            - Only if DDG is throttled

    Rate Control:
        - 40 req/hour
        - 5 pages per session
        - 6-12s delays

    Expected Yield: 20-50 listings per scrape.
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()
        self.batch_id = ""
        self._ddg = None

    def _get_ddg(self):
        """Lazy-load DuckDuckGo search."""
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    logger.warning(f"[{AGENT_ID}] ddgs not installed")
        return self._ddg

    def scrape_mba_internships(self, max_dorks: int = 8) -> List[RawListing]:
        """Scrape IIMjobs MBA internships via DDG site dorks."""
        self.batch_id = generate_batch_id("iimjobs")
        all_listings = []
        seen_urls: Set[str] = set()

        logger.info(f"[{AGENT_ID}] Starting IIMjobs PRISM scrape via DDG dorks")

        ddg = self._get_ddg()
        if not ddg:
            return self._direct_scrape_fallback()

        dork_queries = [
            'site:iimjobs.com "intern" 2026',
            'site:iimjobs.com "MBA internship"',
            'site:iimjobs.com "summer intern"',
            'site:iimjobs.com "management trainee"',
            'site:iimjobs.com "internship" stipend',
            'site:iimjobs.com "finance intern" OR "marketing intern"',
            'site:iimjobs.com "consulting" internship',
            'site:iimjobs.com "analytics intern" OR "data science intern"',
            'site:iimjobs.com "operations" internship',
            'site:iimjobs.com "product management" intern',
        ]

        random.shuffle(dork_queries)
        queries_used = 0

        for query in dork_queries:
            if queries_used >= max_dorks:
                break
            try:
                results = ddg.text(query, region='in-en', max_results=15)
                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    if not url or 'iimjobs.com' not in url:
                        continue

                    # Parse result
                    listing = RawListing()
                    listing.source = "iimjobs"
                    listing.batch_id = self.batch_id
                    listing.url = url.split('?')[0]

                    title_parts = [p.strip() for p in title.split(' | ') if p.strip()]
                    listing.title = title_parts[0] if title_parts else title
                    if len(title_parts) >= 2 and 'iimjobs' not in title_parts[-1].lower():
                        listing.company = title_parts[-1]

                    listing.description_text = body[:3000] if body else ''
                    listing.is_ppo = detect_ppo(f"{title} {body}")
                    listing.is_wfh = detect_wfh(f"{title} {body}")

                    if listing.title and listing.url and listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        all_listings.append(listing)

                queries_used += 1
                time.sleep(random.uniform(6, 12))

            except Exception as e:
                logger.error(f"[{AGENT_ID}] IIMjobs DDG error: {e}")
                continue

        if all_listings:
            inserted = self.db.insert_raw_listings_batch(all_listings)
            logger.info(f"[{AGENT_ID}] IIMjobs complete: {len(all_listings)} unique, {inserted} new")

        return all_listings

    def _direct_scrape_fallback(self) -> List[RawListing]:
        """Fallback: direct HTML scraping of IIMjobs search page."""
        listings = []
        logger.info(f"[{AGENT_ID}] IIMjobs: DDG unavailable, trying direct scrape")

        try:
            search_url = f"{IIMJOBS_SEARCH_URL}?q=internship&sort=date"
            response = self.stealth.get(search_url, site='iimjobs', auto_delay=True)

            if response and response.get('status_code') == 200 and BeautifulSoup:
                soup = BeautifulSoup(response.get('text', ''), 'html.parser')
                cards = soup.select('.job-listing, .job-card, [class*="job"]')
                for card in cards[:30]:
                    title_elem = card.select_one('a[href*="job"], h3 a, .title a')
                    if title_elem:
                        listing = RawListing()
                        listing.source = "iimjobs"
                        listing.batch_id = self.batch_id
                        listing.title = title_elem.get_text(strip=True)
                        listing.url = urljoin(IIMJOBS_BASE_URL, title_elem.get('href', ''))
                        if listing.title and listing.url:
                            listings.append(listing)
        except Exception as e:
            logger.error(f"[{AGENT_ID}] IIMjobs direct scrape error: {e}")

        return listings


# ============================================================
# LINKEDIN DDG DORK SCRAPER — PRISM v0.1 (DDG ONLY)
# ============================================================

class LinkedInDorkScraper:
    """
    PRISM v0.1: LinkedIn job discovery via DDG site dorks ONLY.

    CRITICAL: NEVER scrape LinkedIn directly. All access via DDG dorks.

    Strategy:
        DDG dorks: site:linkedin.com/jobs "MBA intern" india
        - Maximum 5 req/hour to avoid DDG throttling
        - MBA-specific queries with location=India filter
        - Also captures posts: site:linkedin.com/posts "hiring intern"
        - Apply links extracted but application is MANUAL (via mini-app)

    Rate Control:
        - 5 req/hour MAX
        - 3 pages per session
        - 15-30s delays between queries

    Expected Yield: 10-30 listings per scrape.
    """

    def __init__(self, db: DatabaseManager = None):
        self.db = db or get_db()
        self.batch_id = ""
        self._ddg = None

    def _get_ddg(self):
        """Lazy-load DuckDuckGo search."""
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    pass
        return self._ddg

    def search_jobs(self, max_dorks: int = 5) -> List[RawListing]:
        """Search LinkedIn jobs via DDG dorks."""
        self.batch_id = generate_batch_id("linkedin")
        all_listings = []
        seen_urls: Set[str] = set()

        logger.info(f"[{AGENT_ID}] Starting LinkedIn DDG dork search (PRISM)")

        ddg = self._get_ddg()
        if not ddg:
            return all_listings

        # PRISM v0.1: LinkedIn dork queries
        dork_queries = [
            'site:linkedin.com/jobs/view "MBA intern" india',
            'site:linkedin.com/jobs/view "summer internship" MBA india',
            'site:linkedin.com/jobs/view "management trainee" intern india',
            'site:linkedin.com/jobs/view "marketing intern" india stipend',
            'site:linkedin.com/jobs/view "finance intern" india MBA',
            'site:linkedin.com/jobs/view "consulting intern" india',
            'site:linkedin.com/jobs/view "data analyst intern" india',
            'site:linkedin.com/jobs/view "product management intern" india',
            # LinkedIn posts about hiring
            'site:linkedin.com/posts "hiring" "intern" "MBA" india',
            'site:linkedin.com/posts "looking for" "intern" MBA',
        ]

        random.shuffle(dork_queries)
        queries_used = 0

        for query in dork_queries:
            if queries_used >= max_dorks:
                break
            try:
                results = ddg.text(query, region='in-en', max_results=15)
                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    if not url or 'linkedin.com' not in url:
                        continue

                    listing = RawListing()
                    listing.source = "linkedin"
                    listing.batch_id = self.batch_id
                    listing.url = url.split('?')[0]

                    # Parse LinkedIn title format
                    listing.title = title.replace(' | LinkedIn', '').replace(' - LinkedIn', '').strip()
                    # Try to extract company from title
                    parts = listing.title.split(' at ')
                    if len(parts) >= 2:
                        listing.title = parts[0].strip()
                        listing.company = parts[1].strip().split(' - ')[0].strip()
                    elif ' - ' in listing.title:
                        parts = listing.title.split(' - ')
                        listing.title = parts[0].strip()
                        if len(parts) >= 2:
                            listing.company = parts[1].strip()

                    listing.description_text = body[:3000] if body else ''
                    listing.is_ppo = detect_ppo(f"{title} {body}")
                    listing.is_wfh = detect_wfh(f"{title} {body}")
                    listing.location = "India"  # Default from query

                    if listing.title and listing.url and listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        all_listings.append(listing)

                queries_used += 1
                # LinkedIn DDG: longer delays (15-30s)
                time.sleep(random.uniform(15, 30))

            except Exception as e:
                logger.error(f"[{AGENT_ID}] LinkedIn DDG error: {e}")
                continue

        if all_listings:
            inserted = self.db.insert_raw_listings_batch(all_listings)
            logger.info(f"[{AGENT_ID}] LinkedIn complete: {len(all_listings)} unique, {inserted} new")

        return all_listings


# ============================================================
# CAREER PAGE SCRAPER (DDG Dorks for Company Sites)
# ============================================================

class CareerPageScraper:
    """
    PRISM v0.1: Company career page discovery via DDG dorks.

    Strategy:
        DDG dorks: site:company.com/careers "intern"
        - Targets Tier 1-3 company career pages
        - ATS detection (Greenhouse, Lever, Workday, SmartRecruiters, Ashby)
        - Extracts apply links for A-04 (ATS Crawler) and A-13 (Auto Applier)

    Rate Control:
        - 30 req/hour
        - 15 companies per session
        - 4-10s delays
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()
        self.batch_id = ""
        self._ddg = None

        # Tier 1-3 company career page patterns
        self.company_career_dorks = [
            'site:mckinsey.com/careers "intern"',
            'site:bcg.com/careers "intern"',
            'site:bain.com/careers "intern"',
            'site:deloitte.com/careers "intern"',
            'site:ey.com/careers "intern"',
            'site:kpmg.com/careers "intern"',
            'site:pwc.com/careers "intern"',
            'site:accenture.com/careers "intern"',
            'site:amazon.jobs "MBA intern" india',
            'site:microsoft.com/careers "intern" india',
            'site:google.com/careers "intern" india',
            'site:flipkart.com/careers "intern"',
            'site:meesho.io/careers "intern"',
            'site:zerodha.com/careers "intern"',
            'site:razorpay.com/careers "intern"',
            'site:cred.club/careers "intern"',
        ]

    def _get_ddg(self):
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    pass
        return self._ddg

    def scrape_career_pages(self, max_companies: int = 15,
                             max_dorks_per_company: int = 2) -> List[RawListing]:
        """Scrape company career pages via DDG dorks."""
        self.batch_id = generate_batch_id("career_page")
        all_listings = []
        seen_urls: Set[str] = set()

        ddg = self._get_ddg()
        if not ddg:
            return all_listings

        dorks = self.company_career_dorks.copy()
        random.shuffle(dorks)
        dorks_used = 0

        for query in dorks:
            if dorks_used >= max_companies:
                break
            try:
                results = ddg.text(query, region='in-en', max_results=10)
                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    if not url:
                        continue

                    listing = RawListing()
                    listing.source = "career_page"
                    listing.batch_id = self.batch_id
                    listing.url = url.split('?')[0]
                    listing.title = title[:200]
                    listing.description_text = body[:3000] if body else ''
                    listing.is_ppo = detect_ppo(f"{title} {body}")
                    listing.is_wfh = detect_wfh(f"{title} {body}")

                    # Detect ATS platform from URL
                    listing.ats_platform = self._detect_ats_platform(url)

                    if listing.title and listing.url and listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        all_listings.append(listing)

                dorks_used += 1
                _portal_delay("career_page")

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Career page DDG error: {e}")
                continue

        if all_listings:
            inserted = self.db.insert_raw_listings_batch(all_listings)
            logger.info(f"[{AGENT_ID}] Career pages: {len(all_listings)} found, {inserted} new")

        return all_listings

    def _detect_ats_platform(self, url: str) -> str:
        """Detect ATS platform from URL pattern."""
        url_lower = url.lower()
        if 'greenhouse.io' in url_lower or 'boards.greenhouse' in url_lower:
            return 'greenhouse'
        elif 'lever.co' in url_lower or 'jobs.lever' in url_lower:
            return 'lever'
        elif 'myworkdayjobs.com' in url_lower or 'workday' in url_lower:
            return 'workday'
        elif 'smartrecruiters.com' in url_lower:
            return 'smartrecruiters'
        elif 'ashbyhq.com' in url_lower:
            return 'ashby'
        elif 'wellfound.com' in url_lower:
            return 'wellfound'
        return 'direct'


# ============================================================
# INSTAHYRE SCRAPER (DDG Dorks)
# ============================================================

class InstahyreScraper:
    """PRISM v0.1: Instahyre curated MBA job discovery via DDG dorks."""

    def __init__(self, db: DatabaseManager = None):
        self.db = db or get_db()
        self.batch_id = ""
        self._ddg = None

    def _get_ddg(self):
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    pass
        return self._ddg

    def scrape_jobs(self, max_dorks: int = 4) -> List[RawListing]:
        """Scrape Instahyre MBA jobs via DDG dorks."""
        self.batch_id = generate_batch_id("instahyre")
        listings = []
        seen_urls: Set[str] = set()

        ddg = self._get_ddg()
        if not ddg:
            return listings

        queries = [
            'site:instahyre.com "MBA intern"',
            'site:instahyre.com "management" internship',
            'site:instahyre.com "intern" stipend',
            'site:instahyre.com "summer intern" 2026',
        ]
        random.shuffle(queries)

        for query in queries[:max_dorks]:
            try:
                results = ddg.text(query, region='in-en', max_results=10)
                for r in results:
                    url = r.get('href', '') or r.get('link', '')
                    if url and 'instahyre.com' in url and url not in seen_urls:
                        listing = RawListing()
                        listing.source = "instahyre"
                        listing.batch_id = self.batch_id
                        listing.url = url.split('?')[0]
                        listing.title = r.get('title', '')[:200]
                        listing.description_text = r.get('body', '')[:3000]
                        seen_urls.add(listing.url)
                        listings.append(listing)

                _portal_delay("instahyre")
            except Exception as e:
                logger.error(f"[{AGENT_ID}] Instahyre error: {e}")
                continue

        if listings:
            inserted = self.db.insert_raw_listings_batch(listings)
            logger.info(f"[{AGENT_ID}] Instahyre: {len(listings)} found, {inserted} new")

        return listings


# ============================================================
# INDEED RSS SCRAPER — PRISM v0.1 (Zero Ban Risk)
# ============================================================

class IndeedRSSScraper:
    """
    PRISM v0.1: Indeed RSS feed parser for MBA India categories.

    Strategy:
        RSS feed parsing — zero ban risk
        Feeds for: management, analytics, consulting MBA roles
        No authentication, no session, no stealth needed

    Rate Control:
        - 20 req/hour
        - 10 feeds per session
        - 3-8s delays

    Expected Yield: 10-30 listings per scrape.
    """

    def __init__(self, db: DatabaseManager = None):
        self.db = db or get_db()
        self.batch_id = ""

    def scrape_feeds(self) -> List[RawListing]:
        """Scrape MBA internship listings from Indeed RSS feeds."""
        self.batch_id = generate_batch_id("indeed")
        all_listings = []
        seen_urls: Set[str] = set()

        if not feedparser:
            logger.warning(f"[{AGENT_ID}] feedparser not installed, skipping Indeed RSS")
            return all_listings

        # MBA-specific RSS feed queries
        feed_queries = [
            "MBA+intern+india",
            "management+trainee+intern+india",
            "marketing+intern+india",
            "finance+intern+india",
            "data+analyst+intern+india",
            "consulting+intern+india",
            "operations+intern+india",
            "business+analyst+intern+india",
            "product+management+intern+india",
            "strategy+intern+india",
        ]

        for query in feed_queries:
            try:
                feed_url = f"{INDEED_RSS_BASE}?q={query}&l=India&sort=date"
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:10]:
                    url = entry.get('link', '')
                    if not url or url in seen_urls:
                        continue

                    listing = RawListing()
                    listing.source = "indeed"
                    listing.batch_id = self.batch_id
                    listing.url = url.split('?')[0]
                    listing.title = entry.get('title', '')[:200]
                    listing.description_text = entry.get('summary', '')[:3000]
                    listing.company = entry.get('source', {}).get('title', '') if hasattr(entry, 'source') else ''

                    # Extract published date
                    published = entry.get('published_parsed')
                    if published:
                        try:
                            from datetime import datetime as dt
                            pub_date = dt(*published[:6])
                            listing.posted_days = (datetime.now() - pub_date).days
                        except Exception:
                            pass

                    listing.is_ppo = detect_ppo(f"{listing.title} {listing.description_text}")
                    listing.is_wfh = detect_wfh(f"{listing.title} {listing.description_text}")

                    seen_urls.add(listing.url)
                    all_listings.append(listing)

                _portal_delay("indeed")

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Indeed RSS error for {query}: {e}")
                continue

        if all_listings:
            inserted = self.db.insert_raw_listings_batch(all_listings)
            logger.info(f"[{AGENT_ID}] Indeed RSS: {len(all_listings)} found, {inserted} new")

        return all_listings


# ============================================================
# WELLFOUND / ANGELLIST SCRAPER — PRISM v0.1 (GraphQL API)
# ============================================================

class WellfoundScraper:
    """
    PRISM v0.1: Wellfound (AngelList) scraper via GraphQL API.

    Strategy:
        PRIMARY: GraphQL API query with MBA-relevant category filter
            - POST to /graphql with query for startup jobs
            - Filters: Management, Finance, Operations, Data Science
        FALLBACK: DDG site dorks

    Rate Control:
        - 20 req/hour
        - 5 pages per session
        - 5-12s delays

    Expected Yield: 15-40 listings per scrape.
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()
        self.batch_id = ""
        self._ddg = None

    def scrape_mba_roles(self, max_pages: int = 3) -> List[RawListing]:
        """Scrape Wellfound MBA internships via GraphQL + DDG fallback."""
        self.batch_id = generate_batch_id("wellfound")
        all_listings = []

        # PRIMARY: GraphQL API
        gql_listings = self._scrape_graphql(max_pages=max_pages)
        all_listings.extend(gql_listings)

        if gql_listings:
            logger.info(f"[{AGENT_ID}] Wellfound GraphQL yielded {len(gql_listings)}")
        else:
            # FALLBACK: DDG dorks
            ddg_listings = self._scrape_ddg_fallback()
            all_listings.extend(ddg_listings)

        # Deduplicate
        seen = set()
        unique = []
        for l in all_listings:
            if l.url and l.url not in seen:
                seen.add(l.url)
                unique.append(l)

        if unique:
            inserted = self.db.insert_raw_listings_batch(unique)
            logger.info(f"[{AGENT_ID}] Wellfound complete: {len(unique)} unique, {inserted} new")

        return unique

    def _scrape_graphql(self, max_pages: int = 3) -> List[RawListing]:
        """PRISM v0.1: Wellfound GraphQL API for MBA startup jobs."""
        listings = []

        # GraphQL query for internship/MBA roles at startups
        gql_query = """
        query SearchStartupJobs($query: String!, $page: Int!) {
            talent {
                jobSearchResults(query: $query, page: $page) {
                    jobs {
                        id
                        title
                        slug
                        description
                        remote
                        primaryRoleTitle
                        compensation
                        startup {
                            name
                            slug
                            companySize
                            highConcept
                            logoUrl
                        }
                        locationNames
                    }
                    totalCount
                    perPage
                }
            }
        }
        """

        mba_queries = [
            "MBA intern",
            "management intern",
            "business analyst intern",
            "finance intern startup",
            "marketing intern startup",
            "product management intern",
        ]

        for query_text in mba_queries:
            for page in range(1, max_pages + 1):
                try:
                    payload = {
                        "query": gql_query,
                        "variables": {
                            "query": query_text,
                            "page": page,
                        }
                    }

                    headers = {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'User-Agent': random.choice(DESKTOP_USER_AGENTS),
                        'Origin': WELLFOUND_BASE_URL,
                        'Referer': f'{WELLFOUND_BASE_URL}/jobs',
                    }

                    response = self.stealth.post(
                        WELLFOUND_GQL_URL,
                        site='wellfound',
                        json_data=payload,
                        headers=headers,
                        auto_delay=True,
                    )

                    if not response or response.get('status_code', 0) != 200:
                        break

                    data = response.get('json', {})
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except json.JSONDecodeError:
                            break

                    jobs = (data.get('data', {})
                            .get('talent', {})
                            .get('jobSearchResults', {})
                            .get('jobs', []))

                    if not jobs:
                        break

                    for job in jobs:
                        listing = self._parse_gql_job(job)
                        if listing:
                            listings.append(listing)

                    _portal_delay("wellfound")

                except Exception as e:
                    logger.error(f"[{AGENT_ID}] Wellfound GraphQL error: {e}")
                    break

        return listings

    def _parse_gql_job(self, job: Dict) -> Optional[RawListing]:
        """Parse a Wellfound GraphQL job object."""
        listing = RawListing()
        listing.source = "wellfound"
        listing.batch_id = self.batch_id
        listing.ats_platform = "wellfound"

        listing.title = job.get('title', '').strip()
        slug = job.get('slug', '')
        if slug:
            listing.url = f"{WELLFOUND_BASE_URL}/jobs/{slug}"
        else:
            listing.url = f"{WELLFOUND_BASE_URL}/jobs/{job.get('id', '')}"

        # Company info
        startup = job.get('startup', {})
        listing.company = startup.get('name', '').strip()

        # Location
        locations = job.get('locationNames', [])
        listing.location = ', '.join(locations[:3]) if locations else ''

        # Remote
        listing.is_wfh = job.get('remote', False)

        # Compensation
        comp = job.get('compensation', '')
        if comp:
            listing.stipend = str(comp)
            listing.stipend_normalized = normalize_stipend(str(comp))

        # Description
        listing.description_text = job.get('description', '')[:5000]

        listing.is_ppo = detect_ppo(f"{listing.title} {listing.description_text}")

        return listing if listing.title and listing.url else None

    def _scrape_ddg_fallback(self) -> List[RawListing]:
        """Fallback: Wellfound via DDG dorks."""
        listings = []
        if self._ddg is None:
            try:
                from ddgs import DDGS
                self._ddg = DDGS()
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                    self._ddg = DDGS()
                except ImportError:
                    return listings

        queries = [
            'site:wellfound.com "intern" MBA india',
            'site:wellfound.com "internship" management',
            'site:wellfound.com "intern" startup india',
        ]

        for q in queries:
            try:
                results = self._ddg.text(q, region='in-en', max_results=10)
                for r in results:
                    url = r.get('href', '')
                    if url and 'wellfound.com' in url:
                        listing = RawListing()
                        listing.source = "wellfound"
                        listing.batch_id = self.batch_id
                        listing.url = url.split('?')[0]
                        listing.title = r.get('title', '')[:200]
                        listing.description_text = r.get('body', '')[:3000]
                        listings.append(listing)
                _portal_delay("wellfound")
            except Exception as e:
                logger.error(f"[{AGENT_ID}] Wellfound DDG error: {e}")
        return listings


# ============================================================
# ASHBY DIRECT API SCRAPER — PRISM v0.1
# ============================================================

class AshbyDirectScraper:
    """
    PRISM v0.1: Ashby Job Board API Scraper.

    Ashby provides a public, zero-auth REST API for job boards:
        API: https://api.ashbyhq.com/posting-api/job-board/{board_slug}
        Rate: No documented rate limit, but we respect 100 req/hr.

    Strategy:
        1. Maintain a list of known Ashby board slugs from company DB
        2. Hit /job-board/{slug} to get all open positions as JSON
        3. Filter for MBA-relevant categories using keyword matching
        4. Parse structured data (title, team, location, employmentType)
        5. Insert into raw_listings with source='ashby'

    Anti-Detection:
        - Public API, zero ban risk
        - Standard browser headers for courtesy
        - 2-4s delays between companies
    """

    ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"

    # Known Ashby board slugs for companies that hire MBA interns in India
    DEFAULT_BOARD_SLUGS = [
        "notion", "ramp", "plaid", "brex", "coinbase", "figma", "vercel",
        "anthropic", "openai", "stripe", "linear", "retool", "runway",
        "loom", "deel", "rippling", "mercury", "pilot", "gusto",
    ]

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()

    def scrape_boards(self, slugs: List[str] = None,
                      max_companies: int = 20) -> List[RawListing]:
        """
        Scrape Ashby job boards for MBA-relevant intern roles.

        Args:
            slugs: List of Ashby board slugs. Defaults to built-in list
                   merged with company DB Ashby slugs.
            max_companies: Maximum companies to scrape per run.

        Returns:
            List of RawListing objects inserted into DB.
        """
        all_slugs = list(set(slugs or self.DEFAULT_BOARD_SLUGS))

        # Merge with company DB slugs (companies where ats_platform='ashby')
        try:
            db_companies = self.db.get_companies_by_ats('ashby')
            for c in db_companies:
                if c.get('ats_slug'):
                    all_slugs.append(c['ats_slug'])
            all_slugs = list(set(all_slugs))
        except Exception:
            pass

        all_slugs = all_slugs[:max_companies]
        logger.info(f"[{AGENT_ID}] Ashby: Scanning {len(all_slugs)} boards")

        all_listings = []
        batch_id = generate_batch_id("ashby")

        for slug in all_slugs:
            try:
                url = f"{self.ASHBY_API_BASE}/{slug}"
                resp = self.stealth.get(url, headers={
                    'Accept': 'application/json',
                    'User-Agent': random.choice(DESKTOP_USER_AGENTS),
                })
                if resp and resp.get('status_code') == 200:
                    try:
                        data = json.loads(resp.get('text', '{}'))
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    jobs = data.get('jobs', [])
                    for job in jobs:
                        listing = self._parse_ashby_job(job, slug, batch_id)
                        if listing:
                            try:
                                self.db.insert_raw_listing(listing)
                                all_listings.append(listing)
                            except Exception:
                                pass
                    logger.info(f"[{AGENT_ID}] Ashby/{slug}: {len(jobs)} jobs found (total: {len(jobs)})")
                else:
                    logger.debug(f"[{AGENT_ID}] Ashby/{slug}: HTTP {resp.get('status_code', 'N/A') if resp else 'N/A'}")
            except Exception as e:
                logger.error(f"[{AGENT_ID}] Ashby/{slug} error: {e}")

            _portal_delay("career_page")  # Reuse career_page delay (4-10s)

        logger.info(f"[{AGENT_ID}] Ashby: {len(all_listings)} MBA-relevant listings from {len(all_slugs)} boards")
        return all_listings

    def _parse_ashby_job(self, job: Dict, board_slug: str,
                         batch_id: str) -> Optional[RawListing]:
        """Parse an Ashby API job object into a RawListing."""
        title = job.get('title', '')
        if not title:
            return None

        # Filter for intern/MBA-relevant roles
        title_lower = title.lower()
        is_intern = any(kw in title_lower for kw in [
            'intern', 'trainee', 'co-op', 'summer', 'graduate',
            'mba', 'analyst', 'associate',
        ])
        if not is_intern:
            return None

        # Kill list check
        kill_terms = ['software engineer', 'backend', 'frontend', 'devops',
                      'sre', 'designer', 'content writer', 'seo']
        if any(k in title_lower for k in kill_terms):
            return None

        location = job.get('location', '') or job.get('locationName', '') or 'Not specified'
        team = job.get('team', '') or job.get('departmentName', '') or ''
        employment_type = job.get('employmentType', '') or ''
        job_url = job.get('jobUrl', '') or job.get('applyUrl', '') or \
                  f"https://jobs.ashbyhq.com/{board_slug}/{job.get('id', '')}"

        listing = RawListing()
        listing.title = title
        listing.company = board_slug.replace('-', ' ').title()
        listing.location = location
        listing.source = 'ashby'
        listing.source_url = job_url
        listing.source_id = f"ashby_{board_slug}_{job.get('id', uuid.uuid4().hex[:8])}"
        listing.batch_id = batch_id
        listing.raw_json = json.dumps(job)[:5000]
        listing.category = self._detect_category_ashby(title, team)
        listing.is_wfh = 'remote' in location.lower()
        listing.posted_days_ago = 0
        listing.description_text = job.get('descriptionPlain', '')[:3000] or \
                                   job.get('description', '')[:3000]
        listing.scraped_at = datetime.now(IST).isoformat()
        return listing

    def _detect_category_ashby(self, title: str, team: str) -> str:
        """Detect MBA category from Ashby job title and team."""
        text = f"{title} {team}".lower()
        cat_map = {
            'finance': ['finance', 'investment', 'accounting', 'treasury'],
            'consulting': ['consult', 'strategy', 'advisory'],
            'marketing': ['marketing', 'brand', 'growth', 'content market'],
            'operations': ['operations', 'supply chain', 'logistics', 'ops'],
            'product_management': ['product', 'pm '],
            'data_science': ['data sci', 'machine learn', 'ml ', 'ai '],
            'analytics': ['analy', 'data analy', 'business intel'],
            'hr': ['hr', 'human resource', 'people', 'talent'],
        }
        for cat, keywords in cat_map.items():
            if any(kw in text for kw in keywords):
                return cat
        return 'general_management'


class SmartRecruitersScraper:
    """
    PRISM v0.1: SmartRecruiters Public API Scraper.

    SmartRecruiters provides a public REST API:
        API: https://api.smartrecruiters.com/v1/companies/{company_id}/postings
        Rate: No documented limit for public API; we respect 60 req/hr.

    Strategy:
        1. Get company IDs from DB (ats_platform='smartrecruiters')
        2. GET /v1/companies/{id}/postings?offset=0&limit=100
        3. Filter for intern/MBA roles via title keyword matching
        4. Parse structured JSON (title, location, department, refUrl)
        5. Insert as raw_listings with source='smartrecruiters'

    Anti-Detection:
        - Public API, zero ban risk
        - Standard headers
        - 3-6s delays between companies
    """

    SR_API_BASE = "https://api.smartrecruiters.com/v1/companies"

    # Known SmartRecruiters company IDs
    DEFAULT_COMPANIES = [
        "BoschGroup", "Visa", "Accenture1", "Booking",
        "Walmart", "Target", "McDonalds", "PepsiCo",
        "Uber", "Lyft", "DoorDash", "Airbnb",
    ]

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()

    def scrape_companies(self, company_ids: List[str] = None,
                         max_companies: int = 15) -> List[RawListing]:
        """Scrape SmartRecruiters for MBA intern roles."""
        all_ids = list(set(company_ids or self.DEFAULT_COMPANIES))

        # Merge with DB
        try:
            db_companies = self.db.get_companies_by_ats('smartrecruiters')
            for c in db_companies:
                if c.get('ats_slug'):
                    all_ids.append(c['ats_slug'])
            all_ids = list(set(all_ids))
        except Exception:
            pass

        all_ids = all_ids[:max_companies]
        logger.info(f"[{AGENT_ID}] SmartRecruiters: Scanning {len(all_ids)} companies")

        all_listings = []
        batch_id = generate_batch_id("smartrecruiters")

        for company_id in all_ids:
            try:
                url = f"{self.SR_API_BASE}/{company_id}/postings"
                params = {'offset': '0', 'limit': '100'}
                resp = self.stealth.get(url, params=params, headers={
                    'Accept': 'application/json',
                    'User-Agent': random.choice(DESKTOP_USER_AGENTS),
                })
                if resp and resp.get('status_code') == 200:
                    try:
                        data = json.loads(resp.get('text', '{}'))
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    postings = data.get('content', [])
                    for posting in postings:
                        listing = self._parse_sr_posting(posting, company_id, batch_id)
                        if listing:
                            try:
                                self.db.insert_raw_listing(listing)
                                all_listings.append(listing)
                            except Exception:
                                pass
                    logger.info(f"[{AGENT_ID}] SmartRecruiters/{company_id}: {len(postings)} postings")
                else:
                    logger.debug(f"[{AGENT_ID}] SmartRecruiters/{company_id}: HTTP {resp.get('status_code', 'N/A') if resp else 'N/A'}")
            except Exception as e:
                logger.error(f"[{AGENT_ID}] SmartRecruiters/{company_id} error: {e}")

            time.sleep(random.uniform(3, 6))

        logger.info(f"[{AGENT_ID}] SmartRecruiters: {len(all_listings)} MBA-relevant listings")
        return all_listings

    def _parse_sr_posting(self, posting: Dict, company_id: str,
                          batch_id: str) -> Optional[RawListing]:
        """Parse a SmartRecruiters posting into RawListing."""
        name = posting.get('name', '')
        if not name:
            return None

        name_lower = name.lower()
        is_intern = any(kw in name_lower for kw in [
            'intern', 'trainee', 'summer', 'graduate', 'co-op',
            'mba', 'analyst', 'associate',
        ])
        if not is_intern:
            return None

        kill_terms = ['software', 'backend', 'frontend', 'devops', 'designer', 'seo']
        if any(k in name_lower for k in kill_terms):
            return None

        loc = posting.get('location', {})
        location = f"{loc.get('city', '')}, {loc.get('country', '')}".strip(', ')
        ref_url = posting.get('ref', '') or \
                  f"https://jobs.smartrecruiters.com/{company_id}/{posting.get('id', '')}"
        department = posting.get('department', {}).get('label', '')

        listing = RawListing()
        listing.title = name
        listing.company = posting.get('company', {}).get('name', '') or \
                          company_id.replace('-', ' ').title()
        listing.location = location or 'Not specified'
        listing.source = 'smartrecruiters'
        listing.source_url = ref_url
        listing.source_id = f"sr_{company_id}_{posting.get('id', uuid.uuid4().hex[:8])}"
        listing.batch_id = batch_id
        listing.raw_json = json.dumps(posting)[:5000]
        listing.category = self._detect_category_sr(name, department)
        listing.is_wfh = posting.get('location', {}).get('remote', False)
        listing.posted_days_ago = 0
        listing.scraped_at = datetime.now(IST).isoformat()
        return listing

    def _detect_category_sr(self, title: str, department: str) -> str:
        """Detect category from SmartRecruiters posting."""
        text = f"{title} {department}".lower()
        cat_map = {
            'finance': ['finance', 'accounting', 'treasury', 'investment'],
            'consulting': ['consult', 'strategy', 'advisory'],
            'marketing': ['marketing', 'brand', 'growth'],
            'operations': ['operations', 'supply chain', 'logistics'],
            'product_management': ['product'],
            'data_science': ['data sci', 'machine learn'],
            'analytics': ['analy', 'business intel'],
            'hr': ['hr', 'human resource', 'people ops', 'talent'],
        }
        for cat, keywords in cat_map.items():
            if any(kw in text for kw in keywords):
                return cat
        return 'general_management'


# ============================================================
# MASTER ORCHESTRATOR — PRISM v0.1 (3-WAVE SCHEDULE)
# ============================================================

class PrimaryScraper:
    """
    PRISM v0.1: Master orchestrator for Agent A-03.

    Coordinates all 8 portal scrapers with the PRISM 3-wave schedule:
        Wave 1 (05:15 IST, Mon/Wed/Fri): Internshala + Naukri API + IIMjobs
        Wave 2 (14:00 IST, Tue/Thu/Sat): LinkedIn DDG + CareerPages + Indeed
        Night  (22:30 IST, Mon/Wed):     Deep crawl all portals + Wellfound

    Portal Health Tracking:
        - Records success/failure per portal per run
        - Reports to A-17 (Adaptive Scheduler) for dynamic adjustment
        - Auto-skips portals with >3 consecutive failures
    """

    def __init__(self):
        self.db = get_db()
        self.stealth = get_stealth_client()

        # Initialize all portal scrapers
        self.internshala = InternshalaHarvester(self.stealth, self.db)
        self.naukri = NaukriScraper(self.stealth, self.db)
        self.iimjobs = IIMJobsScraper(self.stealth, self.db)
        self.linkedin = LinkedInDorkScraper(self.db)
        self.indeed = IndeedRSSScraper(self.db)
        self.career_page = CareerPageScraper(self.stealth, self.db)
        self.instahyre = InstahyreScraper(self.db)
        self.wellfound = WellfoundScraper(self.stealth, self.db)
        self.ashby = AshbyDirectScraper(self.stealth, self.db)
        self.smartrecruiters = SmartRecruitersScraper(self.stealth, self.db)

        # v6.0 compatibility: Day-routed portal control
        self._active_portals: Optional[list] = None
        self._proxy_pool_indices: Optional[list] = None

        # PRISM v0.1: Portal health tracking
        self._portal_health: Dict[str, Dict[str, Any]] = {
            portal: {"consecutive_failures": 0, "last_success": None, "total_runs": 0}
            for portal in PORTAL_RATE_LIMITS.keys()
        }

    def set_active_portals(self, portals: Optional[list]):
        """Set which portals to scrape this session. Pass None to scrape ALL portals."""
        self._active_portals = portals
        if portals is not None:
            logger.info(f"[{AGENT_ID}] Active portals set: {portals}")
        else:
            logger.info(f"[{AGENT_ID}] Active portals cleared — ALL portals will be scraped")

    def set_proxy_pool_indices(self, indices: list):
        """Set proxy pool indices (v6.0 compat)."""
        self._proxy_pool_indices = indices

    def _should_scrape_portal(self, portal_name: str) -> bool:
        """Check if a portal should be scraped this session."""
        if self._active_portals is not None:
            if portal_name not in self._active_portals:
                return False

        # Skip portals with >5 consecutive failures (increased from 3 for resilience)
        health = self._portal_health.get(portal_name, {})
        if health.get("consecutive_failures", 0) >= 5:
            logger.warning(
                f"[{AGENT_ID}] Skipping {portal_name} — "
                f"{health['consecutive_failures']} consecutive failures"
            )
            return False

        return True

    def _record_portal_result(self, portal: str, success: bool, count: int = 0):
        """Record portal scrape result for health tracking."""
        if portal not in self._portal_health:
            self._portal_health[portal] = {"consecutive_failures": 0, "last_success": None, "total_runs": 0}

        self._portal_health[portal]["total_runs"] += 1
        if success:
            self._portal_health[portal]["consecutive_failures"] = 0
            self._portal_health[portal]["last_success"] = datetime.now(IST).isoformat()
        else:
            self._portal_health[portal]["consecutive_failures"] += 1

    def get_portal_health(self) -> Dict[str, Any]:
        """Get portal health status for A-17 Adaptive Scheduler."""
        return self._portal_health.copy()

    # ============================================================
    # PRISM 3-WAVE SCRAPE METHODS
    # ============================================================

    def run_wave1_morning(self) -> Dict[str, Any]:
        """
        PRISM Wave 1: Morning Portals (05:15 IST, Mon/Wed/Fri)
        Targets: Internshala + Naukri API v2 + IIMjobs
        """
        logger.info(f"[{AGENT_ID}] === PRISM WAVE 1: MORNING PORTALS ===")
        start_time = time.time()
        results = {'wave': 'wave1_morning', 'source': {}, 'total': 0, 'new': 0, 'errors': []}
        pre_count = self.db.count_raw_listings()
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        # Internshala — PRISM: Mobile Ajax API with category_ids
        if self._should_scrape_portal('internshala'):
            try:
                listings = self.internshala.scrape_all_categories(pages_per_category=5)
                results['source']['internshala'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('internshala', True, len(listings))
            except Exception as e:
                results['errors'].append(f"Internshala: {str(e)}")
                self._record_portal_result('internshala', False)
                logger.error(f"[{AGENT_ID}] Internshala failed: {e}")

        # Naukri — PRISM: API v2 PRIMARY, DDG fallback
        if self._should_scrape_portal('naukri'):
            try:
                listings = self.naukri.scrape_mba_internships(max_pages=5)
                results['source']['naukri'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('naukri', True, len(listings))
            except Exception as e:
                results['errors'].append(f"Naukri: {str(e)}")
                self._record_portal_result('naukri', False)
                logger.error(f"[{AGENT_ID}] Naukri failed: {e}")

        # IIMjobs — PRISM: DDG site dorks
        if self._should_scrape_portal('iimjobs'):
            try:
                listings = self.iimjobs.scrape_mba_internships(max_dorks=8)
                results['source']['iimjobs'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('iimjobs', True, len(listings))
            except Exception as e:
                results['errors'].append(f"IIMjobs: {str(e)}")
                self._record_portal_result('iimjobs', False)

        # Finalize
        post_count = self.db.count_raw_listings()
        results['new'] = max(0, post_count - pre_count)
        results['duration_sec'] = round(time.time() - start_time, 1)
        results['portal_health'] = self.get_portal_health()

        # v0.2: Direct Supabase sync for immediate availability
        try:
            recent = self.db.get_raw_listings_since(hours=1)
            if recent:
                supabase_jobs = []
                for row in recent:
                    listing = RawListing(**{k: v for k, v in row.items() if k in RawListing.__dataclass_fields__})
                    enrich_listing_from_description(listing)
                    supabase_jobs.append(listing)
                synced = sync_listings_to_supabase(supabase_jobs, f"wave1_{datetime.now(IST).strftime('%Y%m%d_%H%M')}")
                results['supabase_synced'] = synced
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Wave 1 Supabase sync error: {e}")

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=results['new'],
            errors=len(results['errors']),
            duration_sec=results['duration_sec']
        )

        logger.info(
            f"[{AGENT_ID}] === WAVE 1 COMPLETE === "
            f"Total: {results['total']} | New: {results['new']} | "
            f"Duration: {results['duration_sec']}s"
        )
        return results

    def run_wave2_afternoon(self) -> Dict[str, Any]:
        """
        PRISM Wave 2: ATS + LinkedIn (14:00 IST, Tue/Thu/Sat)
        Targets: LinkedIn DDG + Career Pages + Indeed RSS + Instahyre
        """
        logger.info(f"[{AGENT_ID}] === PRISM WAVE 2: AFTERNOON PORTALS ===")
        start_time = time.time()
        results = {'wave': 'wave2_afternoon', 'source': {}, 'total': 0, 'new': 0, 'errors': []}
        pre_count = self.db.count_raw_listings()
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        # LinkedIn DDG dorks
        if self._should_scrape_portal('linkedin'):
            try:
                listings = self.linkedin.search_jobs(max_dorks=5)
                results['source']['linkedin'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('linkedin', True, len(listings))
            except Exception as e:
                results['errors'].append(f"LinkedIn: {str(e)}")
                self._record_portal_result('linkedin', False)

        # Career Pages
        if self._should_scrape_portal('career_page'):
            try:
                listings = self.career_page.scrape_career_pages(max_companies=15)
                results['source']['career_page'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('career_page', True, len(listings))
            except Exception as e:
                results['errors'].append(f"CareerPage: {str(e)}")
                self._record_portal_result('career_page', False)

        # Indeed RSS
        if self._should_scrape_portal('indeed'):
            try:
                listings = self.indeed.scrape_feeds()
                results['source']['indeed'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('indeed', True, len(listings))
            except Exception as e:
                results['errors'].append(f"Indeed: {str(e)}")
                self._record_portal_result('indeed', False)

        # Instahyre
        if self._should_scrape_portal('instahyre'):
            try:
                listings = self.instahyre.scrape_jobs(max_dorks=4)
                results['source']['instahyre'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('instahyre', True, len(listings))
            except Exception as e:
                results['errors'].append(f"Instahyre: {str(e)}")
                self._record_portal_result('instahyre', False)

        # Wellfound — PRISM v0.1: Also runs in Wave 2 (not just night)
        if self._should_scrape_portal('wellfound'):
            try:
                listings = self.wellfound.scrape_mba_roles(max_pages=2)
                results['source']['wellfound'] = len(listings)
                results['total'] += len(listings)
                self._record_portal_result('wellfound', True, len(listings))
            except Exception as e:
                results['errors'].append(f"Wellfound: {str(e)}")
                self._record_portal_result('wellfound', False)

        # Ashby Direct API — PRISM v0.1: Zero ban risk, public API
        try:
            listings = self.ashby.scrape_boards(max_companies=10)
            results['source']['ashby'] = len(listings)
            results['total'] += len(listings)
        except Exception as e:
            results['errors'].append(f"Ashby: {str(e)}")

        # SmartRecruiters Direct API — PRISM v0.1: Zero ban risk
        try:
            listings = self.smartrecruiters.scrape_companies(max_companies=8)
            results['source']['smartrecruiters'] = len(listings)
            results['total'] += len(listings)
        except Exception as e:
            results['errors'].append(f"SmartRecruiters: {str(e)}")

        # Finalize
        post_count = self.db.count_raw_listings()
        results['new'] = max(0, post_count - pre_count)
        results['duration_sec'] = round(time.time() - start_time, 1)
        results['portal_health'] = self.get_portal_health()

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=results['new'],
            errors=len(results['errors']),
            duration_sec=results['duration_sec']
        )

        logger.info(
            f"[{AGENT_ID}] === WAVE 2 COMPLETE === "
            f"Total: {results['total']} | New: {results['new']} | "
            f"Duration: {results['duration_sec']}s"
        )
        return results

    def run_night_deep_crawl(self) -> Dict[str, Any]:
        """
        PRISM Wave 3: Night Deep Crawl (22:30 IST, Mon/Wed)
        Targets: ALL portals, all tiers, maximum coverage
        Includes Wellfound GraphQL
        ENHANCED: Higher page counts, retry on failure, reset health on manual trigger
        """
        logger.info(f"[{AGENT_ID}] === PRISM WAVE 3: NIGHT DEEP CRAWL ===")
        start_time = time.time()
        results = {'wave': 'night_deep_crawl', 'source': {}, 'total': 0, 'new': 0, 'errors': []}
        pre_count = self.db.count_raw_listings()
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        # Reset portal health for deep crawl — give all portals a fresh chance
        for portal in self._portal_health:
            if self._portal_health[portal]["consecutive_failures"] < 5:
                self._portal_health[portal]["consecutive_failures"] = 0

        # ALL portals in deep mode with HIGHER limits
        portal_scrapers = [
            ('internshala', lambda: self.internshala.scrape_all_categories(pages_per_category=10)),
            ('naukri', lambda: self.naukri.scrape_mba_internships(max_pages=10)),
            ('iimjobs', lambda: self.iimjobs.scrape_mba_internships(max_dorks=14)),
            ('linkedin', lambda: self.linkedin.search_jobs(max_dorks=8)),
            ('indeed', lambda: self.indeed.scrape_feeds()),
            ('career_page', lambda: self.career_page.scrape_career_pages(max_companies=25)),
            ('instahyre', lambda: self.instahyre.scrape_jobs(max_dorks=6)),
            ('wellfound', lambda: self.wellfound.scrape_mba_roles(max_pages=5)),
            ('ashby', lambda: self.ashby.scrape_boards(max_companies=25)),
            ('smartrecruiters', lambda: self.smartrecruiters.scrape_companies(max_companies=20)),
        ]

        for portal_name, scraper_fn in portal_scrapers:
            if not self._should_scrape_portal(portal_name):
                continue

            # Retry up to 2 times on failure
            for attempt in range(2):
                try:
                    listings = scraper_fn()
                    results['source'][portal_name] = len(listings)
                    results['total'] += len(listings)
                    self._record_portal_result(portal_name, True, len(listings))
                    break  # Success, no retry needed
                except Exception as e:
                    if attempt == 0:
                        logger.warning(f"[{AGENT_ID}] Night crawl {portal_name} attempt 1 failed: {e}, retrying...")
                        time.sleep(random.uniform(3, 8))
                    else:
                        results['errors'].append(f"{portal_name}: {str(e)}")
                        self._record_portal_result(portal_name, False)
                        logger.error(f"[{AGENT_ID}] Night crawl {portal_name} failed after 2 attempts: {e}")

        # Finalize
        post_count = self.db.count_raw_listings()
        results['new'] = max(0, post_count - pre_count)
        results['duration_sec'] = round(time.time() - start_time, 1)
        results['portal_health'] = self.get_portal_health()

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=results['new'],
            errors=len(results['errors']),
            duration_sec=results['duration_sec']
        )

        logger.info(
            f"[{AGENT_ID}] === NIGHT CRAWL COMPLETE === "
            f"Total: {results['total']} | New: {results['new']} | "
            f"Duration: {results['duration_sec']}s"
        )
        return results

    # ============================================================
    # LEGACY COMPATIBILITY METHODS
    # ============================================================

    def run_morning_scrape(self) -> Dict[str, Any]:
        """Legacy: Morning scrape (routes to wave1 or wave2 based on active_portals)."""
        return self.run_wave1_morning()

    def run_afternoon_scrape(self) -> Dict[str, Any]:
        """Legacy: Afternoon scrape."""
        return self.run_wave2_afternoon()

    def run_full_scrape(self) -> Dict[str, Any]:
        """Full scrape of all portals (used for deep crawl or manual trigger)."""
        return self.run_night_deep_crawl()


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_primary_scraper: Optional[PrimaryScraper] = None


def get_primary_scraper() -> PrimaryScraper:
    """Get or create the singleton PrimaryScraper instance."""
    global _primary_scraper
    if _primary_scraper is None:
        _primary_scraper = PrimaryScraper()
    return _primary_scraper
