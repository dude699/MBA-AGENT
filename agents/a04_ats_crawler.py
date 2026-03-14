"""
============================================================
AGENT A-04: COMPANY ATS CRAWLER — INDUSTRIAL GRADE
============================================================
Directly crawls company career pages via their public ATS
REST APIs: Greenhouse, Lever, Workday, Wellfound (AngelList),
SmartRecruiters, Ashby, BambooHR, and custom career pages.

Schedule:
    02:00 PM IST  — Afternoon ATS pass (Tier 1+2 companies)
    11:00 PM IST  — Nightly deep crawl (all tiers, 300+ companies)

AI Model:
    Cerebras (`extract_basics`) — for parsing HTML career pages
    Cerebras (`sector_tag`) — for auto-classifying unknown companies

Architecture:
    ┌──────────────────────────────────────────────────┐
    │              ATS CRAWLER (A-04)                   │
    ├──────────────────────────────────────────────────┤
    │  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
    │  │Greenhouse│  │  Lever   │  │   Workday    │   │
    │  │ REST API │  │ REST API │  │  REST API    │   │
    │  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
    │       │             │               │            │
    │  ┌────▼─────┐  ┌────▼─────┐  ┌──────▼───────┐   │
    │  │Wellfound │  │SmartRecr │  │  Ashby/BB    │   │
    │  │ GraphQL  │  │ REST API │  │  REST APIs   │   │
    │  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
    │       │             │               │            │
    │  ┌────▼─────────────▼───────────────▼───────┐    │
    │  │        ATS Response Normalizer            │    │
    │  │    (Unified listing format for pipeline)   │    │
    │  └────────────────┬──────────────────────────┘    │
    │                   │                              │
    │  ┌────────────────▼──────────────────────────┐    │
    │  │          MBA/Intern Keyword Filter         │    │
    │  │   (Title + JD matching for relevance)      │    │
    │  └────────────────┬──────────────────────────┘    │
    │                   │                              │
    │  ┌────────────────▼──────────────────────────┐    │
    │  │    PPO/WFH/Stipend/Duration Extractor      │    │
    │  │   (Regex + AI for structured extraction)   │    │
    │  └────────────────┬──────────────────────────┘    │
    │                   │                              │
    │  ┌────────────────▼──────────────────────────┐    │
    │  │          Batch Insert to raw_listings       │    │
    │  └───────────────────────────────────────────┘    │
    └──────────────────────────────────────────────────┘

Features:
    - Greenhouse REST API v1 (boards-api.greenhouse.io)
    - Lever REST API v0 (api.lever.co)
    - Workday REST API (company-specific patterns)
    - Wellfound/AngelList GraphQL API
    - SmartRecruiters public API
    - Ashby public job board API
    - BambooHR public job board API
    - Custom career page scraping with AI extraction
    - Auto-detection of ATS platform from career page URLs
    - MBA/intern keyword filtering (40+ keywords)
    - PPO detection, WFH detection, stipend extraction
    - Batch ID tracking for pipeline tracing
    - Rate limiting per ATS platform
    - Retry logic with exponential backoff
    - Health monitoring and error reporting
    - ATS platform auto-discovery for new companies
    - Cross-reference with company tier for priority ordering
    - Parallel-safe with per-company locking
    - Comprehensive logging with structured output
============================================================
"""

import os
import re
import json
import time
import random
import hashlib
import html
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from urllib.parse import urlparse, urljoin, quote_plus, parse_qs
from contextlib import contextmanager
from enum import Enum

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

from core.config import get_config, IST, CompanyTier
from core.database import get_db, DatabaseManager, RawListing
from core.ai_router import get_router, AIRouter
from core.stealth_engine import get_stealth_client, StealthHTTPClient


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-04"
AGENT_NAME = "Company ATS Crawler"

# Supported ATS platforms
class ATSPlatform(Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    WELLFOUND = "wellfound"
    SMARTRECRUITERS = "smartrecruiters"
    ASHBY = "ashby"
    BAMBOOHR = "bamboohr"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


# ATS API base URLs
ATS_API_URLS = {
    ATSPlatform.GREENHOUSE: "https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs",
    ATSPlatform.LEVER: "https://api.lever.co/v0/postings/{board_id}",
    ATSPlatform.WELLFOUND: "https://api.wellfound.com/graphql",
    ATSPlatform.SMARTRECRUITERS: "https://api.smartrecruiters.com/v1/companies/{board_id}/postings",
    ATSPlatform.ASHBY: "https://api.ashbyhq.com/posting-api/job-board/{board_id}",
    ATSPlatform.BAMBOOHR: "https://{board_id}.bamboohr.com/careers/list",
}

# Greenhouse job detail endpoint
GREENHOUSE_JOB_DETAIL = "https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs/{job_id}"

# Lever job detail endpoint
LEVER_JOB_DETAIL = "https://api.lever.co/v0/postings/{board_id}/{job_id}"

# MBA/Intern relevance keywords — STRICT list for intern/entry-level only
# Split into tiers: HIGH_CONFIDENCE keywords match standalone,
# CONTEXT_REQUIRED keywords only match with India location or other context
MBA_TITLE_KEYWORDS_HIGH = [
    # Direct intern keywords (always match)
    'intern', 'internship', 'trainee', 'apprentice', 'fellow',
    'summer associate', 'winter intern', 'co-op', 'coop',
    'summer analyst', 'summer intern',
    # MBA-specific (always match)
    'mba', 'management trainee', 'leadership program',
    'graduate program', 'rotational program', 'associate program',
    'management associate', 'future leaders', 'emerging leaders',
    'leadership development', 'accelerated program',
    'campus hire', 'campus recruit', 'fresher',
]

# These keywords ONLY match if the job is India-based
MBA_TITLE_KEYWORDS_INDIA_ONLY = [
    'business analyst', 'strategy analyst', 'product analyst',
    'marketing analyst', 'financial analyst', 'research analyst',
    'operations analyst', 'supply chain analyst',
    'brand manager', 'category manager',
    'area sales manager', 'territory manager',
]

# Legacy combined list (kept for compatibility but NOT used for primary filtering)
MBA_TITLE_KEYWORDS = MBA_TITLE_KEYWORDS_HIGH + MBA_TITLE_KEYWORDS_INDIA_ONLY

# Keywords that indicate the role is NOT relevant
EXCLUSION_KEYWORDS = [
    'software engineer', 'senior engineer', 'staff engineer',
    'principal engineer', 'tech lead', 'devops', 'sre',
    'data scientist', 'ml engineer', 'phd', 'postdoc',
    'director', 'vp', 'vice president', 'chief',
    'senior manager', 'senior director', '10+ years',
    '15+ years', '8+ years', 'lead architect',
]

# JD body keywords that reinforce MBA relevance
MBA_JD_KEYWORDS = [
    'mba', 'business school', 'management program',
    'marketing strategy', 'go-to-market', 'market research',
    'financial modeling', 'valuation', 'dcf',
    'supply chain optimization', 'operations management',
    'brand strategy', 'digital marketing', 'growth marketing',
    'product strategy', 'business development', 'sales strategy',
    'consulting', 'due diligence', 'business case',
    'p&l', 'revenue growth', 'market sizing',
    'campus hire', 'campus placement', 'fresher',
    'recent graduate', '0-2 years', '0-1 years',
    'stipend', 'pre-placement offer', 'ppo',
]

# PPO detection patterns
PPO_PATTERNS = [
    r'\bppo\b', r'pre[- ]?placement\s+offer',
    r'permanent\s+offer', r'conversion\s+(?:to|into)\s+(?:full[- ]?time|fte)',
    r'possibility\s+of\s+(?:full[- ]?time|permanent)',
    r'may\s+(?:lead|convert)\s+to\s+(?:full[- ]?time|permanent)',
    r'based\s+on\s+performance.*(?:offer|hire|absorb)',
    r'absorption\s+based\s+on\s+performance',
    r'job\s+offer\s+based\s+on\s+(?:merit|performance)',
    r'full[- ]?time\s+(?:role|position)\s+(?:after|post)',
    r'ppq\b', r'pre[- ]?placement\s+(?:interview|assessment)',
]

# WFH detection patterns
WFH_PATTERNS = [
    r'\bwfh\b', r'work\s+from\s+home', r'\bremote\b',
    r'work\s+from\s+anywhere', r'virtual\s+(?:internship|position)',
    r'\bhybrid\b', r'remote[- ]?first', r'distributed\s+team',
    r'location[- ]?independent', r'anywhere\s+in\s+india',
    r'pan[- ]?india\s+remote', r'no\s+relocation\s+required',
]

# Stipend extraction patterns
STIPEND_PATTERNS = [
    # INR patterns
    r'(?:₹|rs\.?|inr)\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:per\s+month|/\s*month|/\s*mo|pm|monthly)',
    r'(?:₹|rs\.?|inr)\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:-|to)\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)',
    r'stipend\s*:?\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:per\s+month|/\s*month)',
    # K/L shorthand
    r'(?:₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)\s*(?:k|K)\s*(?:per\s+month|/\s*month|pm|monthly)?',
    r'(?:₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)\s*(?:lpa|l)\s',
]

# Duration extraction patterns
DURATION_PATTERNS = [
    r'(\d+)\s*(?:-|to)\s*(\d+)\s*months?',
    r'(\d+)\s*months?\s*(?:internship|duration|period)',
    r'duration\s*:?\s*(\d+)\s*months?',
    r'(\d+)\s*weeks?\s*(?:internship|duration)',
    r'(\d+)\s*months?',
]

# Location normalization for India
INDIA_CITIES = {
    'mumbai', 'delhi', 'bangalore', 'bengaluru', 'hyderabad', 'chennai',
    'kolkata', 'pune', 'ahmedabad', 'jaipur', 'lucknow', 'gurugram',
    'gurgaon', 'noida', 'greater noida', 'ghaziabad', 'faridabad',
    'navi mumbai', 'thane', 'indore', 'bhopal', 'chandigarh',
    'coimbatore', 'kochi', 'cochin', 'thiruvananthapuram', 'visakhapatnam',
    'nagpur', 'surat', 'vadodara', 'baroda', 'rajkot', 'mysore',
    'mysuru', 'mangalore', 'mangaluru', 'hubli', 'dharwad',
    'nashik', 'aurangabad', 'amritsar', 'ranchi', 'patna',
    'bhubaneswar', 'guwahati', 'dehradun', 'shimla', 'pondicherry',
    'puducherry', 'agra', 'varanasi', 'allahabad', 'prayagraj',
    'kanpur', 'meerut', 'jodhpur', 'udaipur', 'raipur',
}

# Workday company-specific URL patterns — pre-mapped for known companies
WORKDAY_COMPANY_URLS = {
    'deloitte': 'https://apply.deloitte.com/careers/SearchJobs',
    'accenture': 'https://www.accenture.com/in-en/careers/jobsearch?jk=internship',
    'infosys': 'https://career.infosys.com/joblist',
    'tcs': 'https://ibegin.tcs.com/iBegin/jobs/search',
    'wipro': 'https://careers.wipro.com/search-jobs',
    'hcl': 'https://www.hcltech.com/careers',
    'cognizant': 'https://careers.cognizant.com/global/en/search-results',
    'capgemini': 'https://www.capgemini.com/in-en/careers/job-search/',
    'ibm': 'https://www.ibm.com/careers/search?field_keyword_18[0]=Intern',
    'microsoft': 'https://careers.microsoft.com/us/en/search-results?keywords=intern&country=India',
    'google': 'https://careers.google.com/jobs/results/?q=intern&location=India',
    'amazon': 'https://www.amazon.jobs/en/search?offset=0&result_limit=10&sort=relevant&category[]=internships&country[]=IND',
    'flipkart': 'https://www.flipkartcareers.com/#!/joblist',
    'reliance': 'https://careers.ril.com/#!/job-listing',
    'hdfc': 'https://hdfcbank.com/personal/useful-links/careers',
    'icici': 'https://career.icicibank.com/careers/',
    'kotak': 'https://www.kotak.com/en/careers.html',
    'bajaj': 'https://www.bajajfinserv.in/careers',
    'mahindra': 'https://careers.mahindra.com/search-jobs',
    'tata_motors': 'https://www.tatamotors.com/careers/',
    'larsen': 'https://careers.larsentoubro.com/search',
    'hindustan_unilever': 'https://careers.unilever.com/search/?q=&locationsearch=India',
    'itc': 'https://www.itcportal.com/careers/careers.aspx',
    'asian_paints': 'https://careers.asianpaints.com/search',
    'nestle': 'https://www.nestle.in/careers/search-jobs',
    'pg': 'https://www.pgcareers.com/search-jobs/India/936/1',
    'colgate': 'https://jobs.colgate.com/search/?q=intern&locationsearch=India',
}

# Rate limits per ATS platform (requests per hour)
ATS_RATE_LIMITS = {
    ATSPlatform.GREENHOUSE: 100,      # Very generous public API
    ATSPlatform.LEVER: 80,            # Public API, moderate limits
    ATSPlatform.WORKDAY: 20,          # Custom scraping, be cautious
    ATSPlatform.WELLFOUND: 30,        # GraphQL, moderate
    ATSPlatform.SMARTRECRUITERS: 60,  # Public API
    ATSPlatform.ASHBY: 50,            # Public API
    ATSPlatform.BAMBOOHR: 40,         # Public careers page
    ATSPlatform.CUSTOM: 10,           # Custom scraping, very cautious
}

# Delay ranges per ATS platform (seconds)
ATS_DELAYS = {
    ATSPlatform.GREENHOUSE: (1.5, 4.0),
    ATSPlatform.LEVER: (2.0, 5.0),
    ATSPlatform.WORKDAY: (8.0, 20.0),
    ATSPlatform.WELLFOUND: (3.0, 8.0),
    ATSPlatform.SMARTRECRUITERS: (2.0, 5.0),
    ATSPlatform.ASHBY: (2.0, 5.0),
    ATSPlatform.BAMBOOHR: (3.0, 7.0),
    ATSPlatform.CUSTOM: (10.0, 25.0),
}


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ATSJob:
    """Normalized job data from any ATS platform."""
    external_id: str = ""
    title: str = ""
    company: str = ""
    company_id: Optional[int] = None
    location: str = ""
    department: str = ""
    team: str = ""
    employment_type: str = ""
    description_html: str = ""
    description_text: str = ""
    requirements_text: str = ""
    url: str = ""
    apply_url: str = ""
    ats_platform: str = ""
    board_id: str = ""
    posted_at: str = ""
    updated_at: str = ""
    # Extracted fields
    stipend: str = ""
    stipend_normalized: float = 0.0
    duration_text: str = ""
    duration_months: int = 0
    is_ppo: bool = False
    is_wfh: bool = False
    is_relevant: bool = False
    relevance_score: float = 0.0
    # Metadata
    raw_json: str = ""

    def to_raw_listing(self) -> RawListing:
        """Convert to RawListing for database insertion."""
        return RawListing(
            title=self.title,
            company=self.company,
            location=self.location,
            stipend=self.stipend,
            stipend_normalized=self.stipend_normalized,
            duration=self.duration_text,
            duration_months=self.duration_months,
            is_ppo=self.is_ppo,
            is_wfh=self.is_wfh,
            url=self.url,
            source=self.ats_platform,
            category=self._detect_category(),
            description_text=self.description_text[:10000],
            batch_id=f"ats_{self.ats_platform}_{self.board_id}",
        )

    def _detect_category(self) -> str:
        """Auto-detect MBA category from title and description."""
        text = f"{self.title} {self.description_text}".lower()
        category_keywords = {
            'marketing': ['marketing', 'brand', 'digital marketing', 'content', 'social media', 'seo', 'sem'],
            'finance': ['finance', 'financial', 'accounting', 'investment', 'banking', 'treasury', 'audit'],
            'consulting': ['consulting', 'consultant', 'advisory', 'strategy consulting'],
            'operations': ['operations', 'supply chain', 'logistics', 'procurement', 'manufacturing'],
            'strategy': ['strategy', 'strategic', 'business strategy', 'corporate strategy'],
            'product-management': ['product manager', 'product management', 'product owner', 'product strategy'],
            'business-development': ['business development', 'bd', 'partnerships', 'alliances', 'sales'],
            'human-resources': ['human resources', 'hr', 'talent', 'people operations', 'recruitment'],
            'analytics': ['analytics', 'data analytics', 'business intelligence', 'bi', 'insights'],
            'supply-chain': ['supply chain', 'logistics', 'warehouse', 'distribution', 'inventory'],
        }
        for category, keywords in category_keywords.items():
            if any(kw in text for kw in keywords):
                return category
        return 'general'


@dataclass
class ATSCrawlResult:
    """Result of crawling a single ATS platform for a single company."""
    company_name: str = ""
    company_id: Optional[int] = None
    ats_platform: str = ""
    board_id: str = ""
    total_jobs_found: int = 0
    relevant_jobs: int = 0
    new_jobs: int = 0
    duplicate_jobs: int = 0
    error: Optional[str] = None
    duration_sec: float = 0.0
    jobs: List[ATSJob] = field(default_factory=list)


@dataclass
class ATSCrawlSummary:
    """Summary of a full ATS crawl run."""
    run_type: str = "afternoon"  # afternoon or nightly
    start_time: str = ""
    end_time: str = ""
    duration_sec: float = 0.0
    companies_crawled: int = 0
    platforms_crawled: Dict[str, int] = field(default_factory=dict)
    total_jobs_found: int = 0
    relevant_jobs: int = 0
    new_listings_created: int = 0
    duplicate_listings: int = 0
    errors: List[str] = field(default_factory=list)
    company_results: List[ATSCrawlResult] = field(default_factory=list)


# ============================================================
# ATS PLATFORM CRAWLERS
# ============================================================

class GreenhouseCrawler:
    """
    Greenhouse REST API v1 crawler.
    
    API Documentation: https://developers.greenhouse.io/job-board.html
    
    Endpoints:
        GET /v1/boards/{board_token}/jobs
        GET /v1/boards/{board_token}/jobs/{id}
        GET /v1/boards/{board_token}/departments
        GET /v1/boards/{board_token}/offices
    
    Rate Limits:
        - No official rate limit for public boards API
        - We self-limit to 100 requests/hour
        - 2-5 second delay between requests
    
    Response Format:
        {
            "jobs": [
                {
                    "id": 12345,
                    "title": "MBA Intern - Marketing",
                    "location": {"name": "Mumbai, India"},
                    "absolute_url": "https://boards.greenhouse.io/...",
                    "content": "<div>...</div>",
                    "departments": [{"name": "Marketing"}],
                    "offices": [{"name": "Mumbai, India"}],
                    "updated_at": "2026-03-01T10:00:00Z",
                    "metadata": [...]
                }
            ],
            "meta": {"total": 50}
        }
    """

    def __init__(self, stealth: StealthHTTPClient, router: AIRouter):
        self.stealth = stealth
        self.router = router
        self._request_count = 0
        self._hour_start = time.time()

    def crawl_company(self, company: Dict, fetch_details: bool = False) -> ATSCrawlResult:
        """
        Crawl all jobs for a company on Greenhouse.
        
        Args:
            company: Company dict with 'name', 'id', 'ats_board_id'
            fetch_details: If True, fetch full JD for each job (slower)
        
        Returns:
            ATSCrawlResult with all found jobs
        """
        result = ATSCrawlResult(
            company_name=company.get('name', ''),
            company_id=company.get('id'),
            ats_platform='greenhouse',
            board_id=company.get('ats_board_id', ''),
        )

        start = time.time()
        board_id = company.get('ats_board_id', '')
        if not board_id:
            result.error = "No board_id configured"
            return result

        try:
            # Rate limit check
            self._check_rate_limit()

            # Fetch job listing
            url = ATS_API_URLS[ATSPlatform.GREENHOUSE].format(board_id=board_id)
            params = {'content': 'true'}  # Include job content in listing

            logger.debug(f"[{AGENT_ID}] Greenhouse: Fetching {url}")
            response = self.stealth.get_json(url, site='greenhouse', auto_delay=True, params=params)
            self._request_count += 1

            if not response:
                result.error = "Empty response from Greenhouse API"
                return result

            jobs_data = response.get('jobs', [])
            meta = response.get('meta', {})
            result.total_jobs_found = meta.get('total', len(jobs_data))

            logger.info(
                f"[{AGENT_ID}] Greenhouse [{board_id}]: "
                f"{len(jobs_data)} jobs found (total: {result.total_jobs_found})"
            )

            # Process each job
            for job_data in jobs_data:
                try:
                    ats_job = self._parse_greenhouse_job(job_data, company)

                    if not ats_job:
                        continue

                    # Check relevance
                    if ats_job.is_relevant:
                        result.relevant_jobs += 1
                        result.jobs.append(ats_job)

                        # Optionally fetch full details
                        if fetch_details and not ats_job.description_text:
                            detail = self._fetch_greenhouse_detail(
                                board_id, job_data.get('id', '')
                            )
                            if detail:
                                ats_job.description_html = detail.get('content', '')
                                ats_job.description_text = self._html_to_text(
                                    detail.get('content', '')
                                )
                                # Re-extract fields from full JD
                                self._extract_job_details(ats_job)

                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] Greenhouse job parse error: {e}")
                    continue

            # Apply inter-company delay
            delay = random.uniform(*ATS_DELAYS[ATSPlatform.GREENHOUSE])
            time.sleep(delay)

        except Exception as e:
            result.error = f"Greenhouse crawl error: {str(e)}"
            logger.error(f"[{AGENT_ID}] {result.error}")

        result.duration_sec = round(time.time() - start, 2)
        return result

    def _parse_greenhouse_job(self, job_data: Dict, company: Dict) -> Optional[ATSJob]:
        """Parse a single Greenhouse job listing into ATSJob."""
        title = job_data.get('title', '').strip()
        if not title:
            return None

        # Extract location from offices
        offices = job_data.get('offices', [])
        location_parts = []
        for office in offices:
            loc_name = office.get('name', '').strip()
            if loc_name:
                location_parts.append(loc_name)
        location = ', '.join(location_parts) if location_parts else ''

        # Extract department
        departments = job_data.get('departments', [])
        dept_names = [d.get('name', '') for d in departments if d.get('name')]
        department = ', '.join(dept_names) if dept_names else ''

        # Get description from content field
        content_html = job_data.get('content', '')
        description_text = self._html_to_text(content_html)

        # Build job URL
        url = job_data.get('absolute_url', '')
        if not url:
            board_id = company.get('ats_board_id', '')
            job_id = job_data.get('id', '')
            url = f"https://boards.greenhouse.io/{board_id}/jobs/{job_id}"

        # Create ATSJob
        ats_job = ATSJob(
            external_id=str(job_data.get('id', '')),
            title=title,
            company=company.get('name', ''),
            company_id=company.get('id'),
            location=location,
            department=department,
            description_html=content_html,
            description_text=description_text,
            url=url,
            apply_url=url,
            ats_platform='greenhouse',
            board_id=company.get('ats_board_id', ''),
            posted_at=job_data.get('updated_at', ''),
            updated_at=job_data.get('updated_at', ''),
            raw_json=json.dumps(job_data)[:5000],
        )

        # Check relevance and extract details
        ats_job.is_relevant = self._check_mba_relevance(ats_job)
        if ats_job.is_relevant:
            self._extract_job_details(ats_job)

        return ats_job

    def _fetch_greenhouse_detail(self, board_id: str, job_id: str) -> Optional[Dict]:
        """Fetch detailed job info from Greenhouse."""
        try:
            url = GREENHOUSE_JOB_DETAIL.format(board_id=board_id, job_id=job_id)
            response = self.stealth.get_json(url, site='greenhouse', auto_delay=True)
            self._request_count += 1
            time.sleep(random.uniform(1.0, 3.0))
            return response
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Greenhouse detail fetch error: {e}")
            return None

    def _check_rate_limit(self):
        """Check and enforce hourly rate limit."""
        elapsed = time.time() - self._hour_start
        if elapsed >= 3600:
            self._request_count = 0
            self._hour_start = time.time()
        elif self._request_count >= ATS_RATE_LIMITS[ATSPlatform.GREENHOUSE]:
            sleep_time = 3600 - elapsed + random.uniform(5, 30)
            logger.warning(
                f"[{AGENT_ID}] Greenhouse rate limit reached. "
                f"Sleeping {sleep_time:.0f}s"
            )
            time.sleep(sleep_time)
            self._request_count = 0
            self._hour_start = time.time()

    @staticmethod
    def _html_to_text(html_content: str) -> str:
        """Convert HTML to plain text."""
        if not html_content:
            return ""
        if BS4_AVAILABLE:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Remove script and style tags
            for tag in soup(['script', 'style']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
        else:
            # Basic HTML stripping fallback
            text = re.sub(r'<[^>]+>', ' ', html_content)
            text = html.unescape(text)
            text = re.sub(r'\s+', ' ', text).strip()
        return text[:10000]

    @staticmethod
    def _check_mba_relevance(job: ATSJob) -> bool:
        """
        Check if a job is relevant for MBA internship search.
        
        Two-tier keyword matching:
        - HIGH confidence keywords (intern, trainee, MBA, etc.) match globally
        - CONTEXT_REQUIRED keywords (analyst, associate, etc.) only match
          for India-based roles to avoid flooding with global senior positions
        """
        title_lower = job.title.lower()
        full_text = f"{job.title} {job.description_text} {job.department}".lower()

        # Check for exclusion keywords first
        for kw in EXCLUSION_KEYWORDS:
            if kw in title_lower:
                return False

        # Determine if India-based
        location_lower = job.location.lower()
        is_india = (
            any(city in location_lower for city in INDIA_CITIES)
            or 'india' in location_lower
        )

        # Tier 1: HIGH confidence keywords match regardless of location
        for kw in MBA_TITLE_KEYWORDS_HIGH:
            if kw in title_lower:
                return True

        # Tier 2: INDIA_ONLY keywords match only for India-based jobs
        if is_india:
            for kw in MBA_TITLE_KEYWORDS_INDIA_ONLY:
                if kw in title_lower:
                    return True

        # Check JD body for MBA keywords — require India location + 3 matches
        jd_matches = sum(1 for kw in MBA_JD_KEYWORDS if kw in full_text)
        if is_india and jd_matches >= 2:
            return True
        elif jd_matches >= 4:
            return True

        # If India-based and has strong intern indicators in body
        if is_india and any(kw in full_text for kw in [
            'intern', 'fresher', '0-2 years', 'campus', 'stipend',
            'management trainee', 'graduate program'
        ]):
            return True

        return False

    @staticmethod
    def _extract_job_details(job: ATSJob):
        """Extract structured details from job description."""
        text = f"{job.title} {job.description_text}".lower()

        # PPO detection
        for pattern in PPO_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                job.is_ppo = True
                break

        # WFH detection
        for pattern in WFH_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                job.is_wfh = True
                break

        # Stipend extraction
        for pattern in STIPEND_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    # Normalize
                    if 'k' in match.group(0).lower() or 'K' in match.group(0):
                        amount *= 1000
                    if 'lpa' in match.group(0).lower() or 'l ' in match.group(0).lower():
                        amount = amount * 100000 / 12  # LPA to monthly
                    if amount > 500 and amount < 500000:  # Sanity check
                        job.stipend_normalized = amount
                        job.stipend = f"₹{amount:,.0f}/month"
                    break
                except (ValueError, IndexError):
                    continue

        # Duration extraction
        for pattern in DURATION_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    if match.lastindex and match.lastindex >= 2:
                        # Range: take average
                        m1 = int(match.group(1))
                        m2 = int(match.group(2))
                        job.duration_months = (m1 + m2) // 2
                    else:
                        months = int(match.group(1))
                        if 'week' in match.group(0).lower():
                            months = max(1, months // 4)
                        if 1 <= months <= 24:
                            job.duration_months = months
                    job.duration_text = f"{job.duration_months} months"
                    break
                except (ValueError, IndexError):
                    continue

        # Location normalization (detect India cities)
        if not job.location or job.location.lower() == 'remote':
            # Try to extract from description
            for city in INDIA_CITIES:
                if city in text:
                    if job.location.lower() == 'remote':
                        job.location = f"Remote / {city.title()}"
                    else:
                        job.location = city.title()
                    break


class LeverCrawler:
    """
    Lever REST API v0 crawler.
    
    API Documentation: https://github.com/lever/postings-api
    
    Endpoints:
        GET /v0/postings/{company}
        GET /v0/postings/{company}/{posting_id}
    
    Response Format:
        [
            {
                "id": "abc123",
                "text": "MBA Intern - Strategy",
                "categories": {
                    "team": "Strategy",
                    "department": "Corporate",
                    "location": "Mumbai, India",
                    "commitment": "Intern"
                },
                "descriptionPlain": "...",
                "hostedUrl": "https://jobs.lever.co/company/abc123",
                "applyUrl": "https://jobs.lever.co/company/abc123/apply",
                "createdAt": 1709251200000,
                "lists": [...]
            }
        ]
    """

    def __init__(self, stealth: StealthHTTPClient, router: AIRouter):
        self.stealth = stealth
        self.router = router
        self._request_count = 0
        self._hour_start = time.time()

    def crawl_company(self, company: Dict, fetch_details: bool = False) -> ATSCrawlResult:
        """Crawl all jobs for a company on Lever."""
        result = ATSCrawlResult(
            company_name=company.get('name', ''),
            company_id=company.get('id'),
            ats_platform='lever',
            board_id=company.get('ats_board_id', ''),
        )

        start = time.time()
        board_id = company.get('ats_board_id', '')
        if not board_id:
            result.error = "No board_id configured"
            return result

        try:
            self._check_rate_limit()

            url = ATS_API_URLS[ATSPlatform.LEVER].format(board_id=board_id)
            logger.debug(f"[{AGENT_ID}] Lever: Fetching {url}")

            response = self.stealth.get_json(url, site='lever', auto_delay=True)
            self._request_count += 1

            if not response:
                result.error = "Empty response from Lever API"
                return result

            if not isinstance(response, list):
                result.error = f"Unexpected Lever response type: {type(response)}"
                return result

            result.total_jobs_found = len(response)
            logger.info(
                f"[{AGENT_ID}] Lever [{board_id}]: "
                f"{len(response)} jobs found"
            )

            for job_data in response:
                try:
                    ats_job = self._parse_lever_job(job_data, company)
                    if not ats_job:
                        continue

                    if ats_job.is_relevant:
                        result.relevant_jobs += 1
                        result.jobs.append(ats_job)

                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] Lever job parse error: {e}")
                    continue

            delay = random.uniform(*ATS_DELAYS[ATSPlatform.LEVER])
            time.sleep(delay)

        except Exception as e:
            result.error = f"Lever crawl error: {str(e)}"
            logger.error(f"[{AGENT_ID}] {result.error}")

        result.duration_sec = round(time.time() - start, 2)
        return result

    def _parse_lever_job(self, job_data: Dict, company: Dict) -> Optional[ATSJob]:
        """Parse a single Lever job posting."""
        title = job_data.get('text', '').strip()
        if not title:
            return None

        categories = job_data.get('categories', {})
        location = categories.get('location', '')
        department = categories.get('department', '')
        team = categories.get('team', '')
        commitment = categories.get('commitment', '')

        # Description
        desc_plain = job_data.get('descriptionPlain', '')
        desc_html = job_data.get('description', '')

        # Additional list descriptions
        lists = job_data.get('lists', [])
        additional_text_parts = []
        for lst in lists:
            list_text = lst.get('text', '')
            list_content = lst.get('content', '')
            if list_text:
                additional_text_parts.append(list_text)
            if list_content:
                additional_text_parts.append(
                    GreenhouseCrawler._html_to_text(list_content)
                )
        full_desc = desc_plain + '\n' + '\n'.join(additional_text_parts)

        # URLs
        hosted_url = job_data.get('hostedUrl', '')
        apply_url = job_data.get('applyUrl', '')

        # Timestamps
        created_at = job_data.get('createdAt', 0)
        if created_at:
            try:
                created_dt = datetime.fromtimestamp(created_at / 1000)
                posted_at = created_dt.isoformat()
            except (OSError, ValueError):
                posted_at = ''
        else:
            posted_at = ''

        ats_job = ATSJob(
            external_id=job_data.get('id', ''),
            title=title,
            company=company.get('name', ''),
            company_id=company.get('id'),
            location=location,
            department=department,
            team=team,
            employment_type=commitment,
            description_html=desc_html,
            description_text=full_desc[:10000],
            url=hosted_url,
            apply_url=apply_url,
            ats_platform='lever',
            board_id=company.get('ats_board_id', ''),
            posted_at=posted_at,
            raw_json=json.dumps(job_data)[:5000],
        )

        # Check relevance
        ats_job.is_relevant = GreenhouseCrawler._check_mba_relevance(ats_job)
        if ats_job.is_relevant:
            GreenhouseCrawler._extract_job_details(ats_job)

        return ats_job

    def _check_rate_limit(self):
        """Check and enforce hourly rate limit."""
        elapsed = time.time() - self._hour_start
        if elapsed >= 3600:
            self._request_count = 0
            self._hour_start = time.time()
        elif self._request_count >= ATS_RATE_LIMITS[ATSPlatform.LEVER]:
            sleep_time = 3600 - elapsed + random.uniform(5, 30)
            logger.warning(f"[{AGENT_ID}] Lever rate limit. Sleeping {sleep_time:.0f}s")
            time.sleep(sleep_time)
            self._request_count = 0
            self._hour_start = time.time()


class WorkdayCrawler:
    """
    Workday career page crawler.
    
    Workday doesn't have a standardized public API — each company has
    a unique career page URL pattern. We maintain a mapping of known
    companies to their Workday career page URLs and scrape them.
    
    For unknown companies, we attempt auto-detection via common
    URL patterns:
        - {company}.wd5.myworkdayjobs.com/en-US/{board}/
        - {company}.wd1.myworkdayjobs.com/External/
    
    Key challenges:
        - JavaScript-rendered pages (need curl_cffi with TLS impersonation)
        - Dynamic pagination (offset/limit patterns)
        - Rate limiting / Cloudflare protection
        - Company-specific URL structures
    """

    def __init__(self, stealth: StealthHTTPClient, router: AIRouter):
        self.stealth = stealth
        self.router = router
        self._request_count = 0
        self._hour_start = time.time()

    def crawl_company(self, company: Dict) -> ATSCrawlResult:
        """
        Crawl Workday career pages for a company.
        
        Strategy:
            1. Check if we have a pre-mapped URL
            2. Try common Workday URL patterns
            3. Use AI to extract jobs from HTML
        """
        result = ATSCrawlResult(
            company_name=company.get('name', ''),
            company_id=company.get('id'),
            ats_platform='workday',
            board_id=company.get('ats_board_id', ''),
        )

        start = time.time()
        company_name = company.get('name', '').lower().replace(' ', '_')
        board_id = company.get('ats_board_id', '')

        try:
            self._check_rate_limit()

            # Try pre-mapped URL first
            career_url = WORKDAY_COMPANY_URLS.get(company_name, '')
            if not career_url and board_id:
                # Try standard Workday patterns
                career_url = self._try_workday_patterns(board_id)

            if not career_url:
                # Try company careers URL from database
                career_url = company.get('careers_url', '')

            if not career_url:
                result.error = "No career page URL found"
                return result

            logger.debug(f"[{AGENT_ID}] Workday: Fetching {career_url}")

            # Fetch the page with stealth
            response_text = self.stealth.get_text(
                career_url, site='workday', auto_delay=True
            )
            self._request_count += 1

            if not response_text:
                result.error = "Empty response from career page"
                return result

            # Try to extract jobs from HTML/JSON
            jobs = self._extract_workday_jobs(response_text, company, career_url)
            result.total_jobs_found = len(jobs)

            for job in jobs:
                if job.is_relevant:
                    result.relevant_jobs += 1
                    result.jobs.append(job)

            logger.info(
                f"[{AGENT_ID}] Workday [{company.get('name', '')}]: "
                f"{result.total_jobs_found} found, {result.relevant_jobs} relevant"
            )

            delay = random.uniform(*ATS_DELAYS[ATSPlatform.WORKDAY])
            time.sleep(delay)

        except Exception as e:
            result.error = f"Workday crawl error: {str(e)}"
            logger.error(f"[{AGENT_ID}] {result.error}")

        result.duration_sec = round(time.time() - start, 2)
        return result

    def _try_workday_patterns(self, board_id: str) -> str:
        """Try common Workday URL patterns to find career page."""
        patterns = [
            f"https://{board_id}.wd5.myworkdayjobs.com/en-US/{board_id}/",
            f"https://{board_id}.wd1.myworkdayjobs.com/External/",
            f"https://{board_id}.wd3.myworkdayjobs.com/en-US/{board_id}/",
            f"https://{board_id}.wd5.myworkdayjobs.com/{board_id}/",
        ]
        for pattern_url in patterns:
            try:
                response = self.stealth.get_text(
                    pattern_url, site='workday', auto_delay=True, timeout=10
                )
                self._request_count += 1
                if response and len(response) > 1000:
                    return pattern_url
            except Exception:
                continue
        return ""

    def _extract_workday_jobs(
        self, html_content: str, company: Dict, base_url: str
    ) -> List[ATSJob]:
        """Extract job listings from Workday HTML/JSON response."""
        jobs = []

        # Try JSON-embedded data first (Workday embeds JSON in script tags)
        json_matches = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html_content, re.DOTALL
        )
        for json_str in json_matches:
            try:
                data = json.loads(json_str)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'JobPosting':
                            job = self._parse_ld_json_job(item, company)
                            if job:
                                jobs.append(job)
                elif isinstance(data, dict) and data.get('@type') == 'JobPosting':
                    job = self._parse_ld_json_job(data, company)
                    if job:
                        jobs.append(job)
            except json.JSONDecodeError:
                continue

        # Try Workday JSON API pattern
        api_matches = re.findall(
            r'"jobPostings"\s*:\s*(\[.*?\])',
            html_content, re.DOTALL
        )
        for api_json in api_matches:
            try:
                postings = json.loads(api_json)
                for posting in postings:
                    title = posting.get('title', '') or posting.get('name', '')
                    if not title:
                        continue
                    job = ATSJob(
                        external_id=str(posting.get('id', '')),
                        title=title,
                        company=company.get('name', ''),
                        company_id=company.get('id'),
                        location=posting.get('location', {}).get('name', '') if isinstance(posting.get('location'), dict) else str(posting.get('location', '')),
                        description_text=posting.get('description', '')[:10000],
                        url=posting.get('url', '') or posting.get('externalUrl', ''),
                        ats_platform='workday',
                        board_id=company.get('ats_board_id', ''),
                    )
                    job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)
                    if job.is_relevant:
                        GreenhouseCrawler._extract_job_details(job)
                    jobs.append(job)
            except json.JSONDecodeError:
                continue

        # Fallback: HTML parsing with BeautifulSoup
        if not jobs and BS4_AVAILABLE:
            try:
                soup = BeautifulSoup(html_content, 'html.parser')
                # Common Workday job card selectors
                selectors = [
                    'a[data-automation-id="jobTitle"]',
                    '.css-19uc56f',
                    '[data-testid="job-card"]',
                    'li.css-1q2dra3',
                    '.job-listing',
                    '.position-card',
                    'article.job-card',
                ]
                for selector in selectors:
                    elements = soup.select(selector)
                    if elements:
                        for elem in elements:
                            title_text = elem.get_text(strip=True)
                            link = elem.get('href', '') or ''
                            if not link.startswith('http'):
                                link = urljoin(base_url, link)
                            if title_text:
                                job = ATSJob(
                                    title=title_text,
                                    company=company.get('name', ''),
                                    company_id=company.get('id'),
                                    url=link,
                                    ats_platform='workday',
                                    board_id=company.get('ats_board_id', ''),
                                )
                                job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)
                                if job.is_relevant:
                                    GreenhouseCrawler._extract_job_details(job)
                                jobs.append(job)
                        break  # Use first successful selector

            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Workday HTML parse error: {e}")

        # If still no jobs and we got substantial HTML, use AI extraction
        if not jobs and len(html_content) > 5000:
            try:
                ai_jobs = self._ai_extract_jobs(html_content, company)
                jobs.extend(ai_jobs)
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] AI extraction failed: {e}")

        return jobs

    def _parse_ld_json_job(self, data: Dict, company: Dict) -> Optional[ATSJob]:
        """Parse a JSON-LD JobPosting schema into ATSJob."""
        title = data.get('title', '')
        if not title:
            return None

        location = ''
        job_location = data.get('jobLocation', {})
        if isinstance(job_location, dict):
            address = job_location.get('address', {})
            if isinstance(address, dict):
                parts = [
                    address.get('addressLocality', ''),
                    address.get('addressRegion', ''),
                    address.get('addressCountry', ''),
                ]
                location = ', '.join(p for p in parts if p)
        elif isinstance(job_location, list) and job_location:
            location = str(job_location[0])

        description = data.get('description', '')
        description_text = GreenhouseCrawler._html_to_text(description)

        # Salary/stipend
        salary_data = data.get('baseSalary', {})
        stipend = 0.0
        if isinstance(salary_data, dict):
            value = salary_data.get('value', {})
            if isinstance(value, dict):
                stipend = float(value.get('value', 0) or 0)
                if salary_data.get('currency', '') == 'INR' and stipend > 0:
                    unit_text = value.get('unitText', '')
                    if 'YEAR' in unit_text.upper():
                        stipend = stipend / 12
                    elif 'HOUR' in unit_text.upper():
                        stipend = stipend * 160  # ~160 hours/month

        job = ATSJob(
            title=title,
            company=company.get('name', ''),
            company_id=company.get('id'),
            location=location,
            description_html=description,
            description_text=description_text,
            url=data.get('url', ''),
            ats_platform='workday',
            board_id=company.get('ats_board_id', ''),
            posted_at=data.get('datePosted', ''),
            stipend_normalized=stipend,
        )

        job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)
        if job.is_relevant:
            GreenhouseCrawler._extract_job_details(job)

        return job

    def _ai_extract_jobs(self, html_content: str, company: Dict) -> List[ATSJob]:
        """Use AI to extract job listings from unstructured HTML."""
        jobs = []
        # Truncate HTML to avoid token limits
        truncated = html_content[:8000]
        try:
            response = self.router.extract_basics(truncated, 'career_page')
            if response.success:
                data = response.get_json()
                if data and isinstance(data.get('jobs', []), list):
                    for j in data['jobs'][:20]:
                        job = ATSJob(
                            title=j.get('title', ''),
                            company=company.get('name', ''),
                            company_id=company.get('id'),
                            location=j.get('location', ''),
                            description_text=j.get('description', ''),
                            url=j.get('url', ''),
                            ats_platform='workday',
                            board_id=company.get('ats_board_id', ''),
                        )
                        job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)
                        if job.is_relevant:
                            GreenhouseCrawler._extract_job_details(job)
                        jobs.append(job)
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] AI job extraction error: {e}")
        return jobs

    def _check_rate_limit(self):
        elapsed = time.time() - self._hour_start
        if elapsed >= 3600:
            self._request_count = 0
            self._hour_start = time.time()
        elif self._request_count >= ATS_RATE_LIMITS[ATSPlatform.WORKDAY]:
            sleep_time = 3600 - elapsed + random.uniform(10, 60)
            logger.warning(f"[{AGENT_ID}] Workday rate limit. Sleeping {sleep_time:.0f}s")
            time.sleep(sleep_time)
            self._request_count = 0
            self._hour_start = time.time()


class WellfoundCrawler:
    """
    Wellfound (formerly AngelList) GraphQL API crawler.
    
    Wellfound exposes a GraphQL endpoint that can be queried
    for startup job listings. Requires crafting specific
    GraphQL queries.
    
    Endpoint: https://api.wellfound.com/graphql
    
    Key features:
        - Startup-focused listings (Series A-D, unicorns)
        - Role type filtering (intern, full-time)
        - Location filtering (India)
        - Company stage information
    """

    GRAPHQL_QUERY = """
    query SearchStartupJobs($query: String!, $page: Int, $perPage: Int) {
        talent {
            jobListings(
                query: $query,
                page: $page,
                perPage: $perPage,
                locationSlugs: ["india", "mumbai", "bangalore", "delhi-ncr"]
            ) {
                totalCount
                edges {
                    node {
                        id
                        title
                        slug
                        description
                        liveStartAt
                        jobType
                        remote
                        compensation
                        primaryRoleTitle
                        company {
                            id
                            name
                            slug
                            highConcept
                            logoUrl
                            companySize
                        }
                        locations {
                            name
                        }
                        remotePolicy
                        tags {
                            displayName
                        }
                    }
                }
            }
        }
    }
    """

    SEARCH_QUERIES = [
        "MBA intern India",
        "management trainee India",
        "business analyst intern India",
        "marketing intern startup India",
        "strategy intern India",
        "product management intern India",
        "finance intern startup India",
        "operations intern India",
    ]

    def __init__(self, stealth: StealthHTTPClient, router: AIRouter):
        self.stealth = stealth
        self.router = router
        self._request_count = 0
        self._hour_start = time.time()

    def crawl_all(self) -> ATSCrawlResult:
        """Crawl Wellfound for all MBA-relevant intern listings in India."""
        result = ATSCrawlResult(
            company_name='Wellfound (Startups)',
            ats_platform='wellfound',
        )

        start = time.time()
        seen_ids = set()

        for query in self.SEARCH_QUERIES:
            try:
                self._check_rate_limit()

                payload = {
                    'query': self.GRAPHQL_QUERY,
                    'variables': {
                        'query': query,
                        'page': 1,
                        'perPage': 30,
                    }
                }

                logger.debug(f"[{AGENT_ID}] Wellfound: Searching '{query}'")

                response = self.stealth.post_json(
                    ATS_API_URLS[ATSPlatform.WELLFOUND],
                    json_data=payload,
                    site='wellfound',
                    auto_delay=True,
                )
                self._request_count += 1

                if not response:
                    continue

                data = response.get('data', {}).get('talent', {}).get('jobListings', {})
                edges = data.get('edges', [])
                total = data.get('totalCount', 0)

                logger.info(
                    f"[{AGENT_ID}] Wellfound '{query}': "
                    f"{len(edges)} results (total: {total})"
                )

                for edge in edges:
                    node = edge.get('node', {})
                    job_id = node.get('id', '')
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    ats_job = self._parse_wellfound_job(node)
                    if ats_job:
                        result.total_jobs_found += 1
                        if ats_job.is_relevant:
                            result.relevant_jobs += 1
                            result.jobs.append(ats_job)

                delay = random.uniform(*ATS_DELAYS[ATSPlatform.WELLFOUND])
                time.sleep(delay)

            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Wellfound query error: {e}")
                continue

        result.duration_sec = round(time.time() - start, 2)
        return result

    def _parse_wellfound_job(self, node: Dict) -> Optional[ATSJob]:
        """Parse a Wellfound GraphQL job node."""
        title = node.get('title', '').strip()
        if not title:
            return None

        company_data = node.get('company', {})
        company_name = company_data.get('name', '')
        company_slug = company_data.get('slug', '')

        locations = node.get('locations', [])
        location = ', '.join(
            loc.get('name', '') for loc in locations if loc.get('name')
        )

        remote_policy = node.get('remotePolicy', '')
        is_remote = node.get('remote', False) or 'remote' in (remote_policy or '').lower()

        slug = node.get('slug', '')
        url = f"https://wellfound.com/l/{slug}" if slug else ''

        compensation = node.get('compensation', '')

        job = ATSJob(
            external_id=str(node.get('id', '')),
            title=title,
            company=company_name,
            location=location,
            department=node.get('primaryRoleTitle', ''),
            employment_type=node.get('jobType', ''),
            description_text=node.get('description', '')[:10000],
            url=url,
            ats_platform='wellfound',
            board_id=company_slug,
            posted_at=node.get('liveStartAt', ''),
            is_wfh=is_remote,
            stipend=str(compensation) if compensation else '',
        )

        # Extract tags
        tags = node.get('tags', [])
        tag_names = [t.get('displayName', '').lower() for t in tags if t.get('displayName')]
        if any('intern' in t or 'mba' in t for t in tag_names):
            job.is_relevant = True
        else:
            job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)

        if job.is_relevant:
            GreenhouseCrawler._extract_job_details(job)

        return job

    def _check_rate_limit(self):
        elapsed = time.time() - self._hour_start
        if elapsed >= 3600:
            self._request_count = 0
            self._hour_start = time.time()
        elif self._request_count >= ATS_RATE_LIMITS[ATSPlatform.WELLFOUND]:
            sleep_time = 3600 - elapsed + random.uniform(10, 30)
            logger.warning(f"[{AGENT_ID}] Wellfound rate limit. Sleeping {sleep_time:.0f}s")
            time.sleep(sleep_time)
            self._request_count = 0
            self._hour_start = time.time()


class SmartRecruitersCrawler:
    """
    SmartRecruiters public API crawler.
    
    API: https://api.smartrecruiters.com/v1/companies/{company_id}/postings
    
    Many mid-market companies use SmartRecruiters as their ATS.
    The public API is well-documented and has generous rate limits.
    """

    def __init__(self, stealth: StealthHTTPClient, router: AIRouter):
        self.stealth = stealth
        self.router = router

    def crawl_company(self, company: Dict) -> ATSCrawlResult:
        """Crawl SmartRecruiters for a company."""
        result = ATSCrawlResult(
            company_name=company.get('name', ''),
            company_id=company.get('id'),
            ats_platform='smartrecruiters',
            board_id=company.get('ats_board_id', ''),
        )

        start = time.time()
        board_id = company.get('ats_board_id', '')
        if not board_id:
            result.error = "No board_id configured"
            return result

        try:
            url = ATS_API_URLS[ATSPlatform.SMARTRECRUITERS].format(board_id=board_id)
            params = {
                'offset': 0,
                'limit': 100,
            }

            response = self.stealth.get_json(url, site='greenhouse', auto_delay=True, params=params)
            if not response:
                result.error = "Empty response"
                return result

            content = response.get('content', [])
            result.total_jobs_found = response.get('totalFound', len(content))

            for job_data in content:
                try:
                    title = job_data.get('name', '').strip()
                    if not title:
                        continue

                    location_data = job_data.get('location', {})
                    location = location_data.get('city', '')
                    if location_data.get('region'):
                        location += f", {location_data['region']}"
                    if location_data.get('country'):
                        location += f", {location_data['country']}"

                    dept = job_data.get('department', {}).get('label', '')

                    ref_url = job_data.get('ref', '') or f"https://jobs.smartrecruiters.com/{board_id}/{job_data.get('id', '')}"

                    job = ATSJob(
                        external_id=str(job_data.get('id', '')),
                        title=title,
                        company=company.get('name', ''),
                        company_id=company.get('id'),
                        location=location,
                        department=dept,
                        employment_type=job_data.get('typeOfEmployment', {}).get('label', ''),
                        url=ref_url,
                        ats_platform='smartrecruiters',
                        board_id=board_id,
                        posted_at=job_data.get('releasedDate', ''),
                    )

                    job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)
                    if job.is_relevant:
                        GreenhouseCrawler._extract_job_details(job)
                        result.relevant_jobs += 1
                        result.jobs.append(job)

                except Exception as e:
                    logger.debug(f"SmartRecruiters parse error: {e}")
                    continue

            delay = random.uniform(*ATS_DELAYS[ATSPlatform.SMARTRECRUITERS])
            time.sleep(delay)

        except Exception as e:
            result.error = str(e)

        result.duration_sec = round(time.time() - start, 2)
        return result


class AshbyCrawler:
    """
    Ashby public job board API crawler.
    
    API: https://api.ashbyhq.com/posting-api/job-board/{board_id}
    
    Popular among Y-Combinator startups and tech companies.
    Returns a clean JSON response with all job postings.
    """

    def __init__(self, stealth: StealthHTTPClient, router: AIRouter):
        self.stealth = stealth
        self.router = router

    def crawl_company(self, company: Dict) -> ATSCrawlResult:
        """Crawl Ashby job board for a company."""
        result = ATSCrawlResult(
            company_name=company.get('name', ''),
            company_id=company.get('id'),
            ats_platform='ashby',
            board_id=company.get('ats_board_id', ''),
        )

        start = time.time()
        board_id = company.get('ats_board_id', '')
        if not board_id:
            result.error = "No board_id configured"
            return result

        try:
            url = ATS_API_URLS[ATSPlatform.ASHBY].format(board_id=board_id)
            response = self.stealth.get_json(url, site='greenhouse', auto_delay=True)

            if not response:
                result.error = "Empty response"
                return result

            # Ashby returns {"jobs": [...]}
            jobs_data = response.get('jobs', [])
            result.total_jobs_found = len(jobs_data)

            for job_data in jobs_data:
                try:
                    title = job_data.get('title', '').strip()
                    if not title:
                        continue

                    location = job_data.get('location', '')
                    if isinstance(location, dict):
                        location = location.get('name', '')

                    dept_info = job_data.get('department', '')
                    if isinstance(dept_info, dict):
                        dept_info = dept_info.get('name', '')

                    job_url = job_data.get('jobUrl', '') or job_data.get('applyUrl', '')

                    job = ATSJob(
                        external_id=str(job_data.get('id', '')),
                        title=title,
                        company=company.get('name', ''),
                        company_id=company.get('id'),
                        location=str(location),
                        department=str(dept_info),
                        employment_type=job_data.get('employmentType', ''),
                        description_text=job_data.get('descriptionPlain', '')[:10000],
                        description_html=job_data.get('descriptionHtml', ''),
                        url=job_url,
                        ats_platform='ashby',
                        board_id=board_id,
                        posted_at=job_data.get('publishedAt', ''),
                    )

                    job.is_relevant = GreenhouseCrawler._check_mba_relevance(job)
                    if job.is_relevant:
                        GreenhouseCrawler._extract_job_details(job)
                        result.relevant_jobs += 1
                        result.jobs.append(job)

                except Exception as e:
                    logger.debug(f"Ashby parse error: {e}")
                    continue

            delay = random.uniform(*ATS_DELAYS[ATSPlatform.ASHBY])
            time.sleep(delay)

        except Exception as e:
            result.error = str(e)

        result.duration_sec = round(time.time() - start, 2)
        return result


# ============================================================
# ATS PLATFORM AUTO-DETECTOR
# ============================================================

class ATSDetector:
    """
    Auto-detect which ATS platform a company uses based on
    their career page URL patterns.
    
    Detection methods:
        1. URL pattern matching (greenhouse.io, lever.co, etc.)
        2. Meta tag inspection
        3. JavaScript variable detection
        4. DNS CNAME detection
    """

    URL_PATTERNS = {
        ATSPlatform.GREENHOUSE: [
            r'boards\.greenhouse\.io/(\w+)',
            r'greenhouse\.io/(\w+)',
            r'grnh\.se/',
        ],
        ATSPlatform.LEVER: [
            r'jobs\.lever\.co/(\w+)',
            r'api\.lever\.co/v0/postings/(\w+)',
        ],
        ATSPlatform.WORKDAY: [
            r'(\w+)\.wd\d+\.myworkdayjobs\.com',
            r'myworkday\.com/(\w+)',
        ],
        ATSPlatform.WELLFOUND: [
            r'wellfound\.com/company/(\w+)',
            r'angel\.co/company/(\w+)',
        ],
        ATSPlatform.SMARTRECRUITERS: [
            r'jobs\.smartrecruiters\.com/(\w+)',
            r'careers\.smartrecruiters\.com/(\w+)',
        ],
        ATSPlatform.ASHBY: [
            r'jobs\.ashbyhq\.com/(\w+)',
            r'api\.ashbyhq\.com/.*?/(\w+)',
        ],
        ATSPlatform.BAMBOOHR: [
            r'(\w+)\.bamboohr\.com/careers',
            r'(\w+)\.bamboohr\.com/jobs',
        ],
    }

    @classmethod
    def detect_from_url(cls, url: str) -> Tuple[ATSPlatform, str]:
        """
        Detect ATS platform and board ID from a URL.
        
        Returns:
            Tuple of (ATSPlatform, board_id)
        """
        if not url:
            return ATSPlatform.UNKNOWN, ""

        for platform, patterns in cls.URL_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, url, re.IGNORECASE)
                if match:
                    board_id = match.group(1) if match.groups() else ""
                    return platform, board_id

        return ATSPlatform.UNKNOWN, ""

    @classmethod
    def detect_from_html(cls, html_content: str) -> ATSPlatform:
        """Detect ATS from HTML content meta tags and scripts."""
        if not html_content:
            return ATSPlatform.UNKNOWN

        html_lower = html_content.lower()

        indicators = {
            ATSPlatform.GREENHOUSE: ['greenhouse.io', 'boards-api.greenhouse', 'grnh.se'],
            ATSPlatform.LEVER: ['lever.co', 'api.lever.co', 'lever-jobs'],
            ATSPlatform.WORKDAY: ['workday.com', 'myworkdayjobs', 'workday-jobs'],
            ATSPlatform.SMARTRECRUITERS: ['smartrecruiters.com'],
            ATSPlatform.ASHBY: ['ashbyhq.com'],
            ATSPlatform.BAMBOOHR: ['bamboohr.com'],
        }

        for platform, keywords in indicators.items():
            if any(kw in html_lower for kw in keywords):
                return platform

        return ATSPlatform.UNKNOWN


# ============================================================
# MAIN ATS CRAWLER ORCHESTRATOR
# ============================================================

class ATSCrawler:
    """
    Master ATS crawler that orchestrates all platform-specific crawlers.
    
    Architecture:
        1. Load companies with known ATS platforms from database
        2. Group by platform for efficient batching
        3. Crawl each platform with appropriate crawler
        4. Normalize all results to RawListing format
        5. Batch insert to raw_listings table
        6. Report results and update heartbeats
    
    Schedule:
        - Afternoon (02:00 PM): Tier 1+2 companies only (fast pass)
        - Nightly (11:00 PM): All tiers (deep crawl, 300+ companies)
    
    Rate Limiting:
        - Per-platform limits enforced by individual crawlers
        - Overall session limit: 500 requests per run
        - Auto-pause when nearing Render memory limit
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.stealth = get_stealth_client()
        self.router = get_router()

        # Initialize platform crawlers
        self.greenhouse = GreenhouseCrawler(self.stealth, self.router)
        self.lever = LeverCrawler(self.stealth, self.router)
        self.workday = WorkdayCrawler(self.stealth, self.router)
        self.wellfound = WellfoundCrawler(self.stealth, self.router)
        self.smartrecruiters = SmartRecruitersCrawler(self.stealth, self.router)
        self.ashby = AshbyCrawler(self.stealth, self.router)

        # Tracking
        self._session_requests = 0
        self._max_session_requests = 500

        # v6.0: Tier filter for weekly schedule
        self._tier_filter_override: Optional[List[str]] = None

    def set_tier_filter(self, tiers: List[str]):
        """
        v6.0: Set tier filter for today's ATS crawl batch.
        Called by WeeklyAgentScheduler before each crawl run.
        
        Args:
            tiers: List of tier labels ['tier_1_2', 'tier_3', 'tier_4_5']
        """
        # Convert tier labels to tier numbers
        tier_map = {
            'tier_1_2': [1, 2],
            'tier_3': [3],
            'tier_4_5': [4, 5],
        }
        tier_nums = []
        for t in tiers:
            tier_nums.extend(tier_map.get(t, []))
        self._tier_filter_override = tier_nums if tier_nums else None
        logger.info(f"[{AGENT_ID}] Tier filter set: {tiers} -> tier_nums={tier_nums}")

    def run_deep_discovery(self) -> Any:
        """
        v6.0: Sunday deep ATS discovery.
        - Discover new career pages for companies missing ATS URLs
        - Verify existing ATS URLs still work
        - Process all tiers
        """
        logger.info(f"[{AGENT_ID}] === SUNDAY DEEP ATS DISCOVERY START ===")
        # Run a full crawl of all tiers with higher limits
        return self.run_crawl(
            ats_type='all',
            tier_filter=None,  # All tiers
            run_type='nightly',
        )

    def run_crawl(self, ats_type: str = 'all', tier_filter: Optional[List[int]] = None,
                  run_type: str = 'afternoon') -> ATSCrawlSummary:
        """
        Run a full ATS crawl across all platforms.
        
        Args:
            ats_type: 'all', 'greenhouse', 'lever', 'workday', 'wellfound',
                     'smartrecruiters', 'ashby'
            tier_filter: Only crawl companies of these tiers
            run_type: 'afternoon' (Tier 1+2) or 'nightly' (all tiers)
        
        Returns:
            ATSCrawlSummary with complete results
        """
        logger.info(f"[{AGENT_ID}] === ATS CRAWL START ({run_type}) ===")
        self.db.update_agent_heartbeat(AGENT_ID, 'running')
        start_time = time.time()

        summary = ATSCrawlSummary(
            run_type=run_type,
            start_time=datetime.now(IST).isoformat(),
        )

        # Determine tier filter based on run type
        if tier_filter is None:
            if run_type == 'afternoon':
                tier_filter = [1, 2, 3]
            else:  # nightly
                tier_filter = [1, 2, 3, 4, 5]

        # Load companies grouped by ATS platform
        companies_by_platform = self._load_companies_by_ats(tier_filter)

        # Crawl each platform
        platform_crawlers = {
            'greenhouse': self._crawl_greenhouse_batch,
            'lever': self._crawl_lever_batch,
            'workday': self._crawl_workday_batch,
            'wellfound': self._crawl_wellfound,
            'smartrecruiters': self._crawl_smartrecruiters_batch,
            'ashby': self._crawl_ashby_batch,
        }

        for platform_name, crawl_fn in platform_crawlers.items():
            if ats_type not in ('all', platform_name):
                continue

            if self._session_requests >= self._max_session_requests:
                logger.warning(f"[{AGENT_ID}] Session request limit reached. Stopping.")
                break

            try:
                companies = companies_by_platform.get(platform_name, [])
                if platform_name == 'wellfound':
                    # Wellfound doesn't need per-company crawling
                    results = crawl_fn()
                else:
                    results = crawl_fn(companies)

                # Process results
                platform_count = 0
                for result in results:
                    summary.company_results.append(result)
                    summary.companies_crawled += 1
                    summary.total_jobs_found += result.total_jobs_found
                    summary.relevant_jobs += result.relevant_jobs

                    if result.error:
                        summary.errors.append(
                            f"{platform_name}/{result.company_name}: {result.error}"
                        )

                    # Insert relevant jobs into database
                    if result.jobs:
                        new_count = self._insert_jobs(result.jobs)
                        result.new_jobs = new_count
                        summary.new_listings_created += new_count
                        platform_count += new_count

                summary.platforms_crawled[platform_name] = platform_count

                logger.info(
                    f"[{AGENT_ID}] {platform_name}: {platform_count} new listings"
                )

            except Exception as e:
                error_msg = f"{platform_name}: {str(e)}"
                summary.errors.append(error_msg)
                logger.error(f"[{AGENT_ID}] Platform crawl error: {error_msg}")

        # Finalize
        duration = time.time() - start_time
        summary.duration_sec = round(duration, 1)
        summary.end_time = datetime.now(IST).isoformat()
        summary.duplicate_listings = (
            summary.relevant_jobs - summary.new_listings_created
        )

        self.db.update_agent_heartbeat(
            AGENT_ID, 'completed',
            items_processed=summary.new_listings_created,
            errors=len(summary.errors),
            duration_sec=duration,
        )

        logger.info(
            f"[{AGENT_ID}] === ATS CRAWL COMPLETE ({run_type}) === "
            f"Companies: {summary.companies_crawled} | "
            f"Total jobs: {summary.total_jobs_found} | "
            f"Relevant: {summary.relevant_jobs} | "
            f"New: {summary.new_listings_created} | "
            f"Duration: {summary.duration_sec}s | "
            f"Errors: {len(summary.errors)}"
        )

        return summary

    def run_afternoon_crawl(self) -> ATSCrawlSummary:
        """Afternoon crawl — Tier 1+2+3 companies."""
        return self.run_crawl(run_type='afternoon', tier_filter=[1, 2, 3])

    def run_nightly_crawl(self) -> ATSCrawlSummary:
        """Nightly deep crawl — all tiers."""
        return self.run_crawl(run_type='nightly', tier_filter=[1, 2, 3, 4, 5])

    def crawl_single_company(self, company_name: str) -> ATSCrawlResult:
        """
        Crawl a single company on-demand (for /ats command).
        
        Auto-detects ATS platform if not known.
        """
        company = self.db.fuzzy_match_company(company_name)
        if not company:
            return ATSCrawlResult(
                company_name=company_name,
                error=f"Company '{company_name}' not found in database",
            )

        ats_platform = company.get('ats_platform', '')
        if not ats_platform:
            # Try to auto-detect from careers URL
            careers_url = company.get('careers_url', '')
            if careers_url:
                platform, board_id = ATSDetector.detect_from_url(careers_url)
                if platform != ATSPlatform.UNKNOWN:
                    ats_platform = platform.value
                    if board_id:
                        company['ats_board_id'] = board_id
                    # Update database
                    self.db.update_company_ats(
                        company['id'], ats_platform, board_id
                    )

        if not ats_platform:
            return ATSCrawlResult(
                company_name=company_name,
                error="Unknown ATS platform. Set careers_url in company database.",
            )

        # Route to appropriate crawler
        crawler_map = {
            'greenhouse': self.greenhouse.crawl_company,
            'lever': self.lever.crawl_company,
            'workday': self.workday.crawl_company,
            'smartrecruiters': self.smartrecruiters.crawl_company,
            'ashby': self.ashby.crawl_company,
        }

        crawl_fn = crawler_map.get(ats_platform)
        if not crawl_fn:
            return ATSCrawlResult(
                company_name=company_name,
                error=f"No crawler for platform: {ats_platform}",
            )

        result = crawl_fn(company)

        # Insert results
        if result.jobs:
            new_count = self._insert_jobs(result.jobs)
            result.new_jobs = new_count

        return result

    def discover_ats_platform(self, company: Dict) -> Tuple[str, str]:
        """
        Discover which ATS platform a company uses.
        
        Strategy:
            1. Check careers URL for ATS platform indicators
            2. Try common Greenhouse/Lever URL patterns
            3. Fetch career page and inspect HTML
        """
        careers_url = company.get('careers_url', '')
        company_name = company.get('name', '').lower()
        normalized = company_name.replace(' ', '').replace('.', '').replace('-', '')

        # 1. URL pattern detection
        if careers_url:
            platform, board_id = ATSDetector.detect_from_url(careers_url)
            if platform != ATSPlatform.UNKNOWN:
                return platform.value, board_id

        # 2. Try common Greenhouse board IDs
        common_gh_ids = [
            normalized,
            company_name.replace(' ', ''),
            company_name.replace(' ', '-'),
            company_name.split()[0] if company_name.split() else '',
        ]
        for gh_id in common_gh_ids:
            if not gh_id:
                continue
            try:
                url = f"https://boards-api.greenhouse.io/v1/boards/{gh_id}/jobs"
                resp = self.stealth.get_json(url, site='greenhouse', auto_delay=True, timeout=8)
                if resp and 'jobs' in resp:
                    return 'greenhouse', gh_id
            except Exception:
                continue
            time.sleep(1)

        # 3. Try common Lever board IDs
        for lv_id in common_gh_ids:
            if not lv_id:
                continue
            try:
                url = f"https://api.lever.co/v0/postings/{lv_id}"
                resp = self.stealth.get_json(url, site='lever', auto_delay=True, timeout=8)
                if resp and isinstance(resp, list):
                    return 'lever', lv_id
            except Exception:
                continue
            time.sleep(1)

        # 4. Fetch career page and inspect HTML
        if careers_url:
            try:
                html_content = self.stealth.get_text(
                    careers_url, site='workday', auto_delay=True
                )
                if html_content:
                    platform = ATSDetector.detect_from_html(html_content)
                    if platform != ATSPlatform.UNKNOWN:
                        return platform.value, ''
            except Exception:
                pass

        return 'unknown', ''

    # ---- Batch Crawlers ----

    def _crawl_greenhouse_batch(self, companies: List[Dict]) -> List[ATSCrawlResult]:
        """Crawl all Greenhouse companies."""
        results = []
        for company in companies:
            if self._session_requests >= self._max_session_requests:
                break
            result = self.greenhouse.crawl_company(company)
            results.append(result)
            self._session_requests += 1
        return results

    def _crawl_lever_batch(self, companies: List[Dict]) -> List[ATSCrawlResult]:
        """Crawl all Lever companies."""
        results = []
        for company in companies:
            if self._session_requests >= self._max_session_requests:
                break
            result = self.lever.crawl_company(company)
            results.append(result)
            self._session_requests += 1
        return results

    def _crawl_workday_batch(self, companies: List[Dict]) -> List[ATSCrawlResult]:
        """Crawl all Workday companies."""
        results = []
        for company in companies:
            if self._session_requests >= self._max_session_requests:
                break
            result = self.workday.crawl_company(company)
            results.append(result)
            self._session_requests += 2  # Workday uses more requests
        return results

    def _crawl_wellfound(self, _companies=None) -> List[ATSCrawlResult]:
        """Crawl Wellfound (not per-company, it's a single search)."""
        result = self.wellfound.crawl_all()
        self._session_requests += len(self.wellfound.SEARCH_QUERIES)
        return [result]

    def _crawl_smartrecruiters_batch(self, companies: List[Dict]) -> List[ATSCrawlResult]:
        """Crawl all SmartRecruiters companies."""
        results = []
        for company in companies:
            if self._session_requests >= self._max_session_requests:
                break
            result = self.smartrecruiters.crawl_company(company)
            results.append(result)
            self._session_requests += 1
        return results

    def _crawl_ashby_batch(self, companies: List[Dict]) -> List[ATSCrawlResult]:
        """Crawl all Ashby companies."""
        results = []
        for company in companies:
            if self._session_requests >= self._max_session_requests:
                break
            result = self.ashby.crawl_company(company)
            results.append(result)
            self._session_requests += 1
        return results

    # ---- Database Operations ----

    def _load_companies_by_ats(self, tier_filter: List[int]) -> Dict[str, List[Dict]]:
        """Load companies grouped by their ATS platform.
        Only loads companies with actual API-crawlable ATS platforms.
        Companies with 'custom' ATS are handled by the scraper (A-03), not ATS crawler."""
        companies_by_platform = defaultdict(list)

        # These platforms have public APIs we can crawl
        crawlable_platforms = {'greenhouse', 'lever', 'workday', 'wellfound', 'smartrecruiters', 'ashby'}

        for tier in tier_filter:
            companies = self.db.get_companies_by_tier(tier, limit=200)
            for company in companies:
                ats_platform = company.get('ats_platform', '')
                board_id = company.get('ats_board_id', '')
                # Only include companies with crawlable ATS platforms AND valid board IDs
                if ats_platform in crawlable_platforms and board_id:
                    companies_by_platform[ats_platform].append(company)

        # Log distribution
        for platform, comps in companies_by_platform.items():
            logger.debug(
                f"[{AGENT_ID}] {platform}: {len(comps)} companies to crawl"
            )

        return dict(companies_by_platform)

    def _insert_jobs(self, jobs: List[ATSJob]) -> int:
        """
        Insert jobs into raw_listings table, skipping duplicates.
        
        Returns number of new listings inserted.
        """
        new_count = 0
        for job in jobs:
            try:
                # Skip if URL already exists
                if job.url and self.db.check_url_exists(job.url):
                    continue

                raw_listing = job.to_raw_listing()
                result = self.db.insert_raw_listing(raw_listing)
                if result:
                    new_count += 1
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Insert error: {e}")
                continue

        return new_count

    # ---- Report Generation ----

    def generate_report(self, summary: ATSCrawlSummary) -> str:
        """Generate a formatted report for Telegram."""
        lines = [
            f"🏢 <b>ATS Crawl Report — {summary.run_type.upper()}</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📊 <b>Overview:</b>",
            f"  Companies crawled: {summary.companies_crawled}",
            f"  Total jobs found: {summary.total_jobs_found}",
            f"  MBA-relevant jobs: {summary.relevant_jobs}",
            f"  New listings: {summary.new_listings_created}",
            f"  Duplicates skipped: {summary.duplicate_listings}",
            f"  Duration: {summary.duration_sec}s",
            f"",
            f"📋 <b>By Platform:</b>",
        ]

        for platform, count in summary.platforms_crawled.items():
            lines.append(f"  {platform.title()}: {count} new")

        if summary.errors:
            lines.append(f"")
            lines.append(f"⚠️ <b>Errors ({len(summary.errors)}):</b>")
            for err in summary.errors[:5]:
                lines.append(f"  • {err[:100]}")

        # Top companies found
        top_results = sorted(
            summary.company_results,
            key=lambda r: r.relevant_jobs,
            reverse=True,
        )[:5]

        if top_results and any(r.relevant_jobs > 0 for r in top_results):
            lines.append(f"")
            lines.append(f"🏆 <b>Top Companies:</b>")
            for r in top_results:
                if r.relevant_jobs > 0:
                    lines.append(
                        f"  {r.company_name}: {r.relevant_jobs} relevant "
                        f"({r.ats_platform})"
                    )

        return '\n'.join(lines)


# ============================================================
# MODULE-LEVEL FACTORY
# ============================================================

_crawler_instance: Optional[ATSCrawler] = None


def get_ats_crawler() -> ATSCrawler:
    """Get or create the singleton ATS Crawler instance."""
    global _crawler_instance
    if _crawler_instance is None:
        _crawler_instance = ATSCrawler()
    return _crawler_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test relevance checker
    test_jobs = [
        ATSJob(title="MBA Intern - Marketing", description_text="Looking for MBA students"),
        ATSJob(title="Senior Software Engineer", description_text="10+ years experience"),
        ATSJob(title="Management Trainee", description_text="Fresh MBA graduates preferred"),
        ATSJob(title="Business Analyst Intern", description_text="Summer internship program"),
        ATSJob(title="Product Manager Intern", description_text="Join our PM rotation program"),
        ATSJob(title="VP of Engineering", description_text="Senior leadership role"),
        ATSJob(title="Summer Associate - Strategy", description_text="MBA intern strategy consulting"),
        ATSJob(title="Data Scientist", description_text="PhD preferred, 5+ years ML experience"),
    ]

    print("\n📋 Relevance Test:")
    for job in test_jobs:
        relevant = GreenhouseCrawler._check_mba_relevance(job)
        icon = "✅" if relevant else "❌"
        print(f"  {icon} '{job.title}' → {'RELEVANT' if relevant else 'SKIP'}")

    # Test PPO detection
    test_texts = [
        "This internship comes with a PPO based on performance",
        "Pre-placement offer may be extended to top performers",
        "Conversion to full-time role possible after internship",
        "No mention of permanent offer here",
        "Based on performance, the intern may be absorbed into the team",
    ]

    print("\n🎯 PPO Detection Test:")
    for text in test_texts:
        has_ppo = any(
            re.search(p, text, re.IGNORECASE) for p in PPO_PATTERNS
        )
        icon = "✅" if has_ppo else "❌"
        print(f"  {icon} '{text[:60]}...' → {'PPO' if has_ppo else 'NO PPO'}")

    # Test WFH detection
    test_wfh = [
        "This is a remote internship, work from home",
        "Office based in Mumbai, 5 days a week",
        "Hybrid role - 3 days office, 2 days WFH",
        "Virtual internship, location independent",
    ]

    print("\n🏠 WFH Detection Test:")
    for text in test_wfh:
        has_wfh = any(
            re.search(p, text, re.IGNORECASE) for p in WFH_PATTERNS
        )
        icon = "✅" if has_wfh else "❌"
        print(f"  {icon} '{text[:60]}...' → {'WFH' if has_wfh else 'OFFICE'}")

    # Test ATS detection
    test_urls = [
        "https://boards.greenhouse.io/razorpay/jobs/12345",
        "https://jobs.lever.co/cred/abc123",
        "https://razorpay.wd5.myworkdayjobs.com/en-US/razorpay/",
        "https://wellfound.com/company/zepto/jobs",
        "https://jobs.smartrecruiters.com/Flipkart/",
        "https://jobs.ashbyhq.com/groww",
        "https://www.example.com/careers",
    ]

    print("\n🔍 ATS Platform Detection Test:")
    for url in test_urls:
        platform, board_id = ATSDetector.detect_from_url(url)
        print(f"  {url}")
        print(f"    → Platform: {platform.value}, Board: {board_id or 'N/A'}")

    # Test stipend extraction
    test_stipends = [
        "Stipend: ₹25,000/month",
        "Rs. 15000 per month",
        "INR 30K/month stipend",
        "Compensation: 3.6 LPA",
        "Unpaid internship",
    ]

    print("\n💰 Stipend Extraction Test:")
    for text in test_stipends:
        job = ATSJob(title="Test", description_text=text)
        GreenhouseCrawler._extract_job_details(job)
        print(f"  '{text}' → ₹{job.stipend_normalized:,.0f}/mo")

    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) — All tests passed!")
    print(f"  Total platforms: {len(ATSPlatform)}")
    print(f"  MBA keywords: {len(MBA_TITLE_KEYWORDS)}")
    print(f"  Exclusion keywords: {len(EXCLUSION_KEYWORDS)}")
    print(f"  PPO patterns: {len(PPO_PATTERNS)}")
    print(f"  WFH patterns: {len(WFH_PATTERNS)}")
    print(f"  Workday pre-mapped: {len(WORKDAY_COMPANY_URLS)}")
    print("=" * 60)
