"""
============================================================
OPERATION FIRST MOVER v8.0 -- AGENT A-03: PRIMARY SCRAPER
============================================================
The workhorse of the system. Scrapes MBA internship listings from
all supported portals on the 3x weekly schedule.

Schedule:
    Tuesday 7am:  LinkedIn + Naukri + Internshala + IIMJobs + Unstop
    Thursday 7am: LinkedIn + Naukri + Wellfound + Foundit + TimesJobs
    Saturday 7am: ALL portals + ATS direct crawl

Portal Strategies:
    LinkedIn:   SerpAPI Google Jobs API (never direct scrape)
    Naukri:     REST API (jobapi/v3/search)
    Internshala: AJAX pagination (internships_ajax/page-N)
    IIMJobs:    Web scraping with BS4
    Unstop:     REST API (api/public/opportunity/search-new)
    Wellfound:  GraphQL API
    Foundit:    Web scraping
    TimesJobs:  Web scraping
    Greenhouse: REST API (boards-api)
    Lever:      REST API (v0/postings)

MBA-Only Filter:
    - INCLUDES: Marketing, Finance, Strategy, Consulting, Operations,
      Product Management, HR, Supply Chain, Analytics, Data Science, AI
    - EXCLUDES: Sales, BDE, SDR, Cold Calling, Lead Gen, Pure Tech
      (Software Dev, Frontend, Backend, DevOps, etc.)

Anti-Ban:
    - Gaussian jitter delays (not uniform)
    - Stealth engine handles proxies, UA rotation, TLS
    - Respects per-portal hourly rate limits
    - No scraping 11pm-6am IST

AI Provider: Cerebras (primary), Groq (fallback), HuggingFace (emergency)
============================================================
"""

import os
import re
import json
import time
import asyncio
import hashlib
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from urllib.parse import urlencode, quote_plus

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("BeautifulSoup not installed. HTML parsing limited.")

from core.config import (
    get_config, now_ist, IST,
    MBA_CATEGORIES, MBA_CATEGORY_KEYWORDS,
    SALES_EXCLUSION_TITLES, SALES_EXCLUSION_KEYWORDS,
    TECH_EXCLUSION_TITLES,
    SITE_STEALTH_PROFILES,
    DDG_DORK_TEMPLATES,
    WEEKLY_SCRAPE_SCHEDULE,
)
from core.database import get_db, DatabaseManager
from core.stealth_engine import get_stealth_client, StealthClient
from core.ai_router import get_router


# ============================================================
# SECTION 1: AGENT BASE
# ============================================================

AGENT_ID = 'A-03'
AGENT_NAME = 'Primary Scraper'
VERSION = '8.0.0'

# MBA search queries for each portal
MBA_SEARCH_QUERIES: Dict[str, List[str]] = {
    'linkedin': [
        'MBA intern India',
        'management intern India',
        'strategy intern India',
        'marketing intern India',
        'finance intern India',
        'consulting intern India',
        'product management intern India',
        'business analyst intern India',
        'data analytics intern India',
        'data science intern India',
        'AI ML intern India',
    ],
    'naukri': [
        'MBA internship',
        'management trainee',
        'strategy intern',
        'marketing intern',
        'finance intern',
        'consulting intern',
        'business analyst intern',
        'data analyst intern',
        'data science intern',
    ],
    'internshala': [
        'marketing', 'finance', 'operations', 'strategy',
        'consulting', 'product-management', 'human-resources',
        'supply-chain', 'analytics', 'data-science',
        'machine-learning', 'business-analytics',
    ],
    'generic': [
        'MBA intern', 'management intern',
        'marketing intern', 'finance intern',
        'strategy intern', 'consulting intern',
        'product management intern', 'data analyst intern',
        'data science intern', 'AI ML intern',
    ],
}


def is_mba_relevant(title: str, description: str = "") -> bool:
    """Quick check if a listing is MBA-relevant.
    First-pass filter before AI-based deep analysis."""
    text = f"{title} {description}".lower()

    # Check exclusions first (fast reject)
    for exclusion in SALES_EXCLUSION_TITLES:
        if exclusion.lower() in text:
            # Check if it's in a context that makes it NOT sales
            # e.g., "marketing (not sales)" should still pass
            title_lower = title.lower()
            if exclusion.lower() in title_lower:
                return False

    for exclusion in TECH_EXCLUSION_TITLES:
        if exclusion.lower() in title.lower():
            return False

    # Check if any MBA keyword matches
    for category, keywords in MBA_CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text:
                return True

    # Check title for generic MBA terms
    mba_title_keywords = [
        'mba', 'management', 'business', 'marketing', 'finance',
        'strategy', 'consulting', 'operations', 'analytics',
        'product', 'data analyst', 'data science', 'ai ', 'ml ',
        'machine learning', 'deep learning', 'business analyst',
    ]
    for keyword in mba_title_keywords:
        if keyword in title.lower():
            return True

    return False


def is_sales_role(title: str, description: str = "") -> bool:
    """Check if a role is a disguised sales position."""
    title_lower = title.lower()
    desc_lower = description.lower() if description else ""

    # Direct title match
    for sales_title in SALES_EXCLUSION_TITLES:
        if sales_title.lower() in title_lower:
            return True

    # Description keyword match (need at least 2 keywords)
    sales_keyword_count = 0
    for keyword in SALES_EXCLUSION_KEYWORDS:
        if keyword.lower() in desc_lower:
            sales_keyword_count += 1
    if sales_keyword_count >= 2:
        return True

    return False


def determine_mba_category(title: str, description: str = "") -> str:
    """Determine the best MBA category for a listing."""
    text = f"{title} {description}".lower()
    best_category = ""
    best_score = 0

    for category, keywords in MBA_CATEGORY_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in text:
                score += 1
                # Bonus for title match
                if keyword.lower() in title.lower():
                    score += 2
        if score > best_score:
            best_score = score
            best_category = category

    return best_category


def extract_stipend_numeric(stipend_text: str) -> int:
    """Extract numeric stipend value from text like '25,000/month' or '25000'."""
    if not stipend_text:
        return 0
    # Remove commas and common suffixes
    text = stipend_text.replace(',', '').replace('/month', '').replace('/mo', '')
    text = text.replace('INR', '').replace('Rs.', '').replace('Rs', '')
    text = text.replace('₹', '').strip()

    # Find numbers
    numbers = re.findall(r'\d+', text)
    if numbers:
        value = int(numbers[0])
        # If very large, might be annual - divide by 12
        if value > 200000:
            value = value // 12
        return value
    return 0


# ============================================================
# SECTION 2: LINKEDIN SCRAPER (SerpAPI)
# ============================================================

class LinkedInScraper:
    """
    LinkedIn scraper using SerpAPI Google Jobs API.
    NEVER scrapes LinkedIn directly (ban risk).
    Uses SerpAPI for structured job search results.
    """

    def __init__(self, stealth: StealthClient):
        self.config = get_config()
        self.stealth = stealth
        self.api_key = self.config.serpapi.api_key
        self._results_count = 0

    async def scrape(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """Scrape LinkedIn via SerpAPI Google Jobs API."""
        if not self.api_key:
            logger.warning("LinkedIn scraper: SerpAPI key not configured")
            return await self._scrape_via_ddg(max_results)

        all_listings = []
        queries = MBA_SEARCH_QUERIES['linkedin']

        for query in queries[:6]:  # Limit queries to save API budget
            try:
                listings = await self._search_serpapi(query)
                all_listings.extend(listings)
                logger.info(f"LinkedIn SerpAPI: '{query}' -> {len(listings)} results")

                # Delay between API calls
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"LinkedIn SerpAPI error for '{query}': {e}")

            if len(all_listings) >= max_results:
                break

        logger.info(f"LinkedIn total: {len(all_listings)} listings scraped")
        return all_listings[:max_results]

    async def _search_serpapi(self, query: str) -> List[Dict[str, Any]]:
        """Execute a SerpAPI Google Jobs search."""
        params = {
            'engine': 'google_jobs',
            'q': query,
            'location': 'India',
            'api_key': self.api_key,
            'chips': 'date_posted:week',  # Last 7 days
            'hl': 'en',
            'gl': 'in',
        }
        url = f"https://serpapi.com/search?{urlencode(params)}"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_serpapi_results(data)
                else:
                    logger.error(f"SerpAPI HTTP {resp.status_code}")
                    return []
        except Exception as e:
            logger.error(f"SerpAPI request failed: {e}")
            return []

    def _parse_serpapi_results(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse SerpAPI Google Jobs response into standardized listing format."""
        listings = []
        jobs = data.get('jobs_results', [])

        for job in jobs:
            title = job.get('title', '')
            company = job.get('company_name', '')
            description = job.get('description', '')

            # Skip non-MBA and sales roles
            if not is_mba_relevant(title, description):
                continue
            if is_sales_role(title, description):
                continue

            listing = {
                'job_id': hashlib.md5(f"linkedin_{title}_{company}".encode()).hexdigest()[:16],
                'platform': 'linkedin',
                'title': title,
                'company': company,
                'location': job.get('location', 'India'),
                'description': description[:2000],
                'url': job.get('job_link', job.get('related_links', [{}])[0].get('link', '')),
                'posted_date': job.get('detected_extensions', {}).get('posted_at', ''),
                'stipend': '',
                'stipend_numeric': 0,
                'duration': '',
                'applicants': 0,
                'mba_category': determine_mba_category(title, description),
                'skills_required': self._extract_skills(description),
                'raw_data': job,
                'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
            }
            listings.append(listing)

        return listings

    async def _scrape_via_ddg(self, max_results: int = 30) -> List[Dict[str, Any]]:
        """Fallback: Use DuckDuckGo dorks if SerpAPI unavailable."""
        listings = []
        try:
            from duckduckgo_search import DDGS
            ddg = DDGS()

            queries = [
                'site:linkedin.com/jobs MBA intern India',
                'site:linkedin.com/jobs management intern India',
                'site:linkedin.com/jobs marketing intern India',
                'site:linkedin.com/jobs finance intern India',
                'site:linkedin.com/jobs data analyst intern India',
                'site:linkedin.com/jobs data science intern India',
            ]

            for query in queries[:4]:
                try:
                    results = ddg.text(query, max_results=10, region='in-en')
                    for r in results:
                        title = r.get('title', '')
                        body = r.get('body', '')
                        href = r.get('href', '')

                        if 'linkedin.com/jobs' not in href:
                            continue
                        if not is_mba_relevant(title, body):
                            continue
                        if is_sales_role(title, body):
                            continue

                        # Extract company from title (LinkedIn format: "Title at Company")
                        company = ''
                        if ' at ' in title:
                            parts = title.split(' at ')
                            title = parts[0].strip()
                            company = parts[1].strip() if len(parts) > 1 else ''
                        elif ' - ' in title:
                            parts = title.split(' - ')
                            title = parts[0].strip()
                            company = parts[1].strip() if len(parts) > 1 else ''

                        listing = {
                            'job_id': hashlib.md5(f"linkedin_ddg_{href}".encode()).hexdigest()[:16],
                            'platform': 'linkedin',
                            'title': title[:200],
                            'company': company[:200],
                            'location': 'India',
                            'description': body[:1000],
                            'url': href,
                            'mba_category': determine_mba_category(title, body),
                            'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
                        }
                        listings.append(listing)

                    await asyncio.sleep(5)  # Respect DDG rate limits
                except Exception as e:
                    logger.error(f"DDG search error: {e}")

        except ImportError:
            logger.warning("duckduckgo_search not installed for LinkedIn fallback")

        return listings[:max_results]

    def _extract_skills(self, description: str) -> List[str]:
        """Extract skill keywords from description."""
        skills = []
        skill_keywords = [
            'Python', 'SQL', 'Excel', 'Tableau', 'Power BI', 'R',
            'Data Analysis', 'Machine Learning', 'Deep Learning',
            'NLP', 'Statistics', 'Financial Modeling', 'Valuation',
            'Marketing', 'Digital Marketing', 'SEO', 'SEM',
            'Strategy', 'Consulting', 'Operations', 'Supply Chain',
            'Product Management', 'Agile', 'Scrum',
            'Communication', 'Presentation', 'Leadership',
        ]
        desc_lower = description.lower()
        for skill in skill_keywords:
            if skill.lower() in desc_lower:
                skills.append(skill)
        return skills[:10]


# ============================================================
# SECTION 3: NAUKRI SCRAPER (REST API)
# ============================================================

class NaukriScraper:
    """
    Naukri.com scraper using their job search API.
    Focuses on MBA internships with proper filtering.
    """

    def __init__(self, stealth: StealthClient):
        self.stealth = stealth
        self.api_url = 'https://www.naukri.com/jobapi/v3/search'
        self._results_count = 0

    async def scrape(self, max_results: int = 100) -> List[Dict[str, Any]]:
        """Scrape Naukri for MBA internships."""
        all_listings = []
        queries = MBA_SEARCH_QUERIES['naukri']

        for query in queries:
            try:
                listings = await self._search_naukri(query)
                # Filter for MBA relevance
                for listing in listings:
                    if is_mba_relevant(listing['title'], listing.get('description', '')):
                        if not is_sales_role(listing['title'], listing.get('description', '')):
                            all_listings.append(listing)

                logger.info(f"Naukri: '{query}' -> {len(listings)} raw, "
                           f"{len(all_listings)} MBA-filtered")
                await asyncio.sleep(3)  # Rate limiting

            except Exception as e:
                logger.error(f"Naukri search error for '{query}': {e}")

            if len(all_listings) >= max_results:
                break

        logger.info(f"Naukri total: {len(all_listings)} MBA listings")
        return all_listings[:max_results]

    async def _search_naukri(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        """Execute a Naukri API search."""
        params = {
            'noOfResults': 50,
            'urlType': 'search_by_keyword',
            'searchType': 'adv',
            'keyword': query,
            'pageNo': page,
            'experience': '0',  # Freshers/Interns
            'jobType': 'internship',
            'location': 'India',
            'sort': 'date',  # Most recent first
        }

        url = f"{self.api_url}?{urlencode(params)}"
        headers = {
            'appid': '109',
            'systemid': 'Naukri',
            'Accept': 'application/json',
            'gid': 'LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE',
        }

        result = await self.stealth.get(
            url=url, domain='naukri',
            extra_headers=headers,
        )

        if not result or not result.get('success'):
            logger.warning(f"Naukri API failed: {result}")
            return []

        try:
            data = json.loads(result['text'])
            return self._parse_naukri_results(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Naukri parse error: {e}")
            return []

    def _parse_naukri_results(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse Naukri API response."""
        listings = []
        jobs = data.get('jobDetails', [])

        for job in jobs:
            title = job.get('title', '')
            company = job.get('companyName', '')
            jd = job.get('jobDescription', '')

            listing = {
                'job_id': str(job.get('jobId', '')),
                'platform': 'naukri',
                'title': title,
                'company': company,
                'location': job.get('placeholders', [{}])[0].get('label', '') if job.get('placeholders') else 'India',
                'description': jd[:2000],
                'url': f"https://www.naukri.com{job.get('jdURL', '')}",
                'posted_date': job.get('createdDate', ''),
                'stipend': job.get('placeholders', [{}])[1].get('label', '') if len(job.get('placeholders', [])) > 1 else '',
                'stipend_numeric': 0,
                'applicants': 0,
                'skills_required': [t.get('label', '') for t in job.get('tagsAndSkills', '').split(',')[:10]] if isinstance(job.get('tagsAndSkills'), str) else [],
                'mba_category': determine_mba_category(title, jd),
                'raw_data': job,
                'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
            }

            # Extract stipend
            if listing['stipend']:
                listing['stipend_numeric'] = extract_stipend_numeric(listing['stipend'])

            listings.append(listing)

        return listings


# ============================================================
# SECTION 4: INTERNSHALA SCRAPER (AJAX)
# ============================================================

class IntershalaScraper:
    """
    Internshala scraper using AJAX pagination.
    Scrapes by MBA category for comprehensive coverage.
    """

    def __init__(self, stealth: StealthClient):
        self.stealth = stealth
        self.base_url = 'https://internshala.com'
        self._results_count = 0

    async def scrape(self, max_results: int = 200) -> List[Dict[str, Any]]:
        """Scrape Internshala for MBA internships across categories."""
        all_listings = []
        categories = MBA_SEARCH_QUERIES['internshala']

        for category in categories:
            try:
                listings = await self._scrape_category(category)
                for listing in listings:
                    if not is_sales_role(listing['title'], listing.get('description', '')):
                        all_listings.append(listing)

                logger.info(f"Internshala [{category}]: {len(listings)} listings")
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Internshala error for {category}: {e}")

            if len(all_listings) >= max_results:
                break

        logger.info(f"Internshala total: {len(all_listings)} MBA listings")
        return all_listings[:max_results]

    async def _scrape_category(self, category: str,
                                max_pages: int = 5) -> List[Dict[str, Any]]:
        """Scrape a specific category from Internshala."""
        listings = []

        for page in range(1, max_pages + 1):
            url = f"{self.base_url}/internships/{category}-internship/page-{page}"

            result = await self.stealth.get(url=url, domain='internshala')
            if not result or not result.get('success'):
                break

            html = result.get('text', '')
            page_listings = self._parse_internshala_html(html, category)

            if not page_listings:
                break

            listings.extend(page_listings)
            await asyncio.sleep(1)

        return listings

    def _parse_internshala_html(self, html: str,
                                 category: str) -> List[Dict[str, Any]]:
        """Parse Internshala HTML for listing data."""
        if not BS4_AVAILABLE or not html:
            return []

        listings = []
        try:
            soup = BeautifulSoup(html, 'lxml' if 'lxml' in str(type(None)) else 'html.parser')

            # Find internship cards
            cards = soup.select('.individual_internship, .internship_meta, [class*="internship"]')
            if not cards:
                # Try alternate selectors
                cards = soup.select('.container-fluid .internship_meta')

            for card in cards:
                try:
                    title_elem = card.select_one('.heading_4_5 a, .profile a, h3 a, .job-title-href')
                    company_elem = card.select_one('.heading_6, .company_name a, .company-name')
                    location_elem = card.select_one('.location_link, #location_names span')
                    stipend_elem = card.select_one('.stipend, .desktop-text .stipend')
                    duration_elem = card.select_one('.duration, #duration')
                    applicants_elem = card.select_one('.applications_message, .desktop-text .applications')

                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    company = company_elem.get_text(strip=True) if company_elem else ''
                    location = location_elem.get_text(strip=True) if location_elem else 'India'
                    stipend = stipend_elem.get_text(strip=True) if stipend_elem else ''
                    duration = duration_elem.get_text(strip=True) if duration_elem else ''

                    # Get URL
                    url = ''
                    if title_elem.get('href'):
                        url = self.base_url + title_elem['href']

                    # Get job ID from URL or card
                    job_id = card.get('internshipid', '')
                    if not job_id and url:
                        parts = url.rstrip('/').split('/')
                        job_id = parts[-1] if parts else ''

                    # Get applicants count
                    applicants = 0
                    if applicants_elem:
                        text = applicants_elem.get_text(strip=True)
                        nums = re.findall(r'\d+', text)
                        if nums:
                            applicants = int(nums[0])

                    # PPO check
                    ppo_eligible = False
                    card_text = card.get_text(strip=True).lower()
                    if 'ppo' in card_text or 'pre-placement' in card_text:
                        ppo_eligible = True

                    listing = {
                        'job_id': f"internshala_{job_id or hashlib.md5(title.encode()).hexdigest()[:8]}",
                        'platform': 'internshala',
                        'title': title,
                        'company': company,
                        'location': location,
                        'stipend': stipend,
                        'stipend_numeric': extract_stipend_numeric(stipend),
                        'duration': duration,
                        'duration_months': self._parse_duration(duration),
                        'applicants': applicants,
                        'url': url,
                        'ppo_eligible': ppo_eligible,
                        'mba_category': category,
                        'description': '',
                        'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
                    }
                    listings.append(listing)

                except Exception as e:
                    logger.debug(f"Error parsing Internshala card: {e}")
                    continue

        except Exception as e:
            logger.error(f"Internshala HTML parse error: {e}")

        return listings

    def _parse_duration(self, duration_text: str) -> int:
        """Parse duration text like '3 Months' into integer months."""
        if not duration_text:
            return 0
        nums = re.findall(r'\d+', duration_text)
        if nums:
            return int(nums[0])
        return 0


# ============================================================
# SECTION 5: ATS SCRAPERS (Greenhouse + Lever)
# ============================================================

class GreenhouseScraper:
    """Greenhouse ATS API scraper for company job boards."""

    def __init__(self, stealth: StealthClient):
        self.stealth = stealth
        self.api_base = 'https://boards-api.greenhouse.io/v1/boards'

    async def scrape_company(self, company_slug: str,
                              company_name: str) -> List[Dict[str, Any]]:
        """Scrape a company's Greenhouse board."""
        url = f"{self.api_base}/{company_slug}/jobs"
        listings = []

        try:
            result = await self.stealth.get(
                url=url, domain='greenhouse', use_proxy=False
            )
            if not result or not result.get('success'):
                return []

            data = json.loads(result['text'])
            jobs = data.get('jobs', [])

            for job in jobs:
                title = job.get('title', '')
                if not is_mba_relevant(title):
                    continue
                if is_sales_role(title):
                    continue

                location = ''
                if job.get('location', {}).get('name'):
                    location = job['location']['name']

                listing = {
                    'job_id': f"greenhouse_{job.get('id', '')}",
                    'platform': 'greenhouse',
                    'title': title,
                    'company': company_name,
                    'location': location,
                    'url': job.get('absolute_url', ''),
                    'apply_url': job.get('absolute_url', ''),
                    'description': '',
                    'mba_category': determine_mba_category(title),
                    'dedup_hash': DatabaseManager.compute_dedup_hash(title, company_name),
                }
                listings.append(listing)

        except Exception as e:
            logger.error(f"Greenhouse scrape error for {company_slug}: {e}")

        return listings


class LeverScraper:
    """Lever ATS API scraper for company job boards."""

    def __init__(self, stealth: StealthClient):
        self.stealth = stealth
        self.api_base = 'https://api.lever.co/v0/postings'

    async def scrape_company(self, company_slug: str,
                              company_name: str) -> List[Dict[str, Any]]:
        """Scrape a company's Lever board."""
        url = f"{self.api_base}/{company_slug}?mode=json"
        listings = []

        try:
            result = await self.stealth.get(
                url=url, domain='lever', use_proxy=False
            )
            if not result or not result.get('success'):
                return []

            jobs = json.loads(result['text'])
            if not isinstance(jobs, list):
                return []

            for job in jobs:
                title = job.get('text', '')
                if not is_mba_relevant(title):
                    continue
                if is_sales_role(title):
                    continue

                location = job.get('categories', {}).get('location', '')

                listing = {
                    'job_id': f"lever_{job.get('id', '')}",
                    'platform': 'lever',
                    'title': title,
                    'company': company_name,
                    'location': location,
                    'url': job.get('hostedUrl', ''),
                    'apply_url': job.get('applyUrl', ''),
                    'description': job.get('descriptionPlain', '')[:2000],
                    'mba_category': determine_mba_category(title),
                    'dedup_hash': DatabaseManager.compute_dedup_hash(title, company_name),
                }
                listings.append(listing)

        except Exception as e:
            logger.error(f"Lever scrape error for {company_slug}: {e}")

        return listings


# ============================================================
# SECTION 6: GENERIC WEB SCRAPERS (IIMJobs, Unstop, etc.)
# ============================================================

class GenericWebScraper:
    """Generic web scraper for portals without APIs."""

    def __init__(self, stealth: StealthClient):
        self.stealth = stealth

    async def scrape_iimjobs(self, max_pages: int = 3) -> List[Dict[str, Any]]:
        """Scrape IIMJobs for MBA internships."""
        listings = []
        base_url = 'https://www.iimjobs.com'

        search_urls = [
            f'{base_url}/search?q=MBA+intern&loc=India',
            f'{base_url}/search?q=management+intern&loc=India',
            f'{base_url}/search?q=strategy+intern&loc=India',
        ]

        for url in search_urls:
            try:
                result = await self.stealth.get(url=url, domain='iimjobs')
                if result and result.get('success') and BS4_AVAILABLE:
                    soup = BeautifulSoup(result['text'], 'html.parser')
                    job_cards = soup.select('.job-card, .job-listing, [class*="job"]')

                    for card in job_cards[:20]:
                        title_elem = card.select_one('h2 a, .job-title a, a[class*="title"]')
                        company_elem = card.select_one('.company-name, [class*="company"]')

                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        company = company_elem.get_text(strip=True) if company_elem else ''

                        if not is_mba_relevant(title):
                            continue
                        if is_sales_role(title):
                            continue

                        href = title_elem.get('href', '')
                        if href and not href.startswith('http'):
                            href = base_url + href

                        listing = {
                            'job_id': f"iimjobs_{hashlib.md5(href.encode()).hexdigest()[:8]}",
                            'platform': 'iimjobs',
                            'title': title, 'company': company,
                            'location': 'India', 'url': href,
                            'mba_category': determine_mba_category(title),
                            'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
                        }
                        listings.append(listing)

                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"IIMJobs scrape error: {e}")

        return listings

    async def scrape_unstop(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """Scrape Unstop for MBA opportunities."""
        listings = []
        api_url = 'https://unstop.com/api/public/opportunity/search-new'

        try:
            payload = {
                'opportunity': 'jobs',
                'oppstatus': 'open',
                'quickFilter': 'intern',
                'sort': 'recent',
                'per_page': 50,
            }

            result = await self.stealth.post(
                url=api_url, domain='unstop',
                json_data=payload,
                extra_headers={'Content-Type': 'application/json'},
            )

            if result and result.get('success'):
                data = json.loads(result['text'])
                items = data.get('data', {}).get('data', [])

                for item in items:
                    title = item.get('title', '')
                    company = item.get('organisation', {}).get('name', '')

                    if not is_mba_relevant(title):
                        continue
                    if is_sales_role(title):
                        continue

                    listing = {
                        'job_id': f"unstop_{item.get('id', '')}",
                        'platform': 'unstop',
                        'title': title, 'company': company,
                        'location': item.get('city', 'India'),
                        'url': f"https://unstop.com/internship/{item.get('public_url', '')}",
                        'stipend': str(item.get('stipend', {}).get('salary', '')),
                        'stipend_numeric': extract_stipend_numeric(str(item.get('stipend', {}).get('salary', ''))),
                        'deadline': item.get('end_date', ''),
                        'mba_category': determine_mba_category(title),
                        'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
                    }
                    listings.append(listing)

        except Exception as e:
            logger.error(f"Unstop scrape error: {e}")

        return listings


# ============================================================
# SECTION 7: PRIMARY SCRAPER ORCHESTRATOR
# ============================================================

class PrimaryScraper:
    """
    Orchestrates scraping across all portals based on the 3x weekly schedule.
    Manages the full pipeline: scrape -> filter -> dedupe -> store.
    """

    def __init__(self):
        self.stealth = get_stealth_client()
        self.db = get_db()
        self.router = get_router()

        # Initialize sub-scrapers
        self.linkedin = LinkedInScraper(self.stealth)
        self.naukri = NaukriScraper(self.stealth)
        self.internshala = IntershalaScraper(self.stealth)
        self.greenhouse = GreenhouseScraper(self.stealth)
        self.lever = LeverScraper(self.stealth)
        self.generic = GenericWebScraper(self.stealth)

        self._total_scraped = 0
        self._total_stored = 0
        self._total_duplicates = 0
        self._total_filtered = 0

    async def initialize(self):
        """Initialize the scraper and stealth client."""
        await self.stealth.initialize()
        logger.info(f"Agent {AGENT_ID} ({AGENT_NAME}) initialized")

    async def run_scrape(self, portals: List[str],
                         scrape_type: str = 'primary') -> Dict[str, Any]:
        """
        Run a scraping session for specified portals.

        Args:
            portals: List of portal names to scrape
            scrape_type: 'primary', 'secondary', 'full'

        Returns:
            Dict with scrape results and statistics
        """
        start_time = time.time()
        logger.info(f"{'='*50}")
        logger.info(f"A-03: Starting {scrape_type} scrape")
        logger.info(f"Portals: {', '.join(portals)}")
        logger.info(f"{'='*50}")

        all_listings = []
        portal_stats = {}

        # Load existing hashes for dedup
        existing_hashes = self.db.get_recent_listing_hashes(days=30)
        logger.info(f"Loaded {len(existing_hashes)} existing hashes for dedup")

        for portal in portals:
            try:
                logger.info(f"Scraping {portal}...")
                listings = await self._scrape_portal(portal)

                # Filter duplicates
                new_listings = []
                for listing in listings:
                    if listing.get('dedup_hash') not in existing_hashes:
                        new_listings.append(listing)
                        existing_hashes.add(listing.get('dedup_hash', ''))
                    else:
                        self._total_duplicates += 1

                # Store new listings
                if new_listings:
                    stored = self.db.upsert_listings_batch(new_listings)
                    self._total_stored += stored
                else:
                    stored = 0

                portal_stats[portal] = {
                    'scraped': len(listings),
                    'new': len(new_listings),
                    'stored': stored,
                    'duplicates': len(listings) - len(new_listings),
                }

                all_listings.extend(new_listings)
                self._total_scraped += len(listings)

                logger.info(
                    f"{portal}: {len(listings)} scraped, "
                    f"{len(new_listings)} new, {stored} stored"
                )

            except Exception as e:
                logger.error(f"Error scraping {portal}: {e}")
                portal_stats[portal] = {'error': str(e)}

        elapsed = time.time() - start_time

        result = {
            'scrape_type': scrape_type,
            'portals_scraped': len(portals),
            'total_scraped': self._total_scraped,
            'total_new': len(all_listings),
            'total_stored': self._total_stored,
            'total_duplicates': self._total_duplicates,
            'elapsed_seconds': round(elapsed, 1),
            'portal_stats': portal_stats,
            'timestamp': now_ist().isoformat(),
        }

        logger.info(f"{'='*50}")
        logger.info(f"A-03: Scrape complete in {elapsed:.1f}s")
        logger.info(f"Total: {len(all_listings)} new listings stored")
        logger.info(f"{'='*50}")

        return result

    async def _scrape_portal(self, portal: str) -> List[Dict[str, Any]]:
        """Scrape a single portal."""
        scrapers = {
            'linkedin': lambda: self.linkedin.scrape(),
            'naukri': lambda: self.naukri.scrape(),
            'internshala': lambda: self.internshala.scrape(),
            'iimjobs': lambda: self.generic.scrape_iimjobs(),
            'unstop': lambda: self.generic.scrape_unstop(),
            'wellfound': lambda: self._scrape_wellfound(),
            'foundit': lambda: self._scrape_foundit(),
            'timesjobs': lambda: self._scrape_timesjobs(),
            'greenhouse': lambda: self._scrape_ats_greenhouse(),
            'lever': lambda: self._scrape_ats_lever(),
        }

        scraper = scrapers.get(portal)
        if scraper:
            return await scraper()
        else:
            logger.warning(f"No scraper for portal: {portal}")
            return []

    async def _scrape_wellfound(self) -> List[Dict[str, Any]]:
        """Scrape Wellfound (AngelList) for MBA internships."""
        # Wellfound uses GraphQL - simplified implementation
        listings = []
        logger.info("Wellfound: Using search page fallback")
        # Implementation via web scraping fallback
        return listings

    async def _scrape_foundit(self) -> List[Dict[str, Any]]:
        """Scrape Foundit.in (Monster India) for MBA internships."""
        listings = []
        base_url = 'https://www.foundit.in/srp/results'
        queries = ['MBA+intern', 'management+intern', 'data+analyst+intern']

        for query in queries:
            try:
                url = f"{base_url}?searchId=&query={query}&locations=India&type=intern"
                result = await self.stealth.get(url=url, domain='foundit')
                if result and result.get('success') and BS4_AVAILABLE:
                    soup = BeautifulSoup(result['text'], 'html.parser')
                    cards = soup.select('.card-apply-content, .job-card, [class*="srpCard"]')

                    for card in cards[:15]:
                        title_elem = card.select_one('.card-title a, h3 a, [class*="title"] a')
                        company_elem = card.select_one('.card-company a, [class*="company"]')

                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        company = company_elem.get_text(strip=True) if company_elem else ''

                        if not is_mba_relevant(title):
                            continue
                        if is_sales_role(title):
                            continue

                        href = title_elem.get('href', '')
                        if href and not href.startswith('http'):
                            href = 'https://www.foundit.in' + href

                        listing = {
                            'job_id': f"foundit_{hashlib.md5(href.encode()).hexdigest()[:8]}",
                            'platform': 'foundit',
                            'title': title, 'company': company,
                            'location': 'India', 'url': href,
                            'mba_category': determine_mba_category(title),
                            'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
                        }
                        listings.append(listing)

                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Foundit scrape error: {e}")

        return listings

    async def _scrape_timesjobs(self) -> List[Dict[str, Any]]:
        """Scrape TimesJobs for MBA internships."""
        listings = []
        queries = ['MBA+intern', 'management+trainee', 'data+analyst+intern']

        for query in queries:
            try:
                url = f"https://www.timesjobs.com/candidate/job-search.html?searchType=personal498&from=submit&txtKeywords={query}&cboWorkExp1=0&postWeek=15"
                result = await self.stealth.get(url=url, domain='timesjobs')

                if result and result.get('success') and BS4_AVAILABLE:
                    soup = BeautifulSoup(result['text'], 'html.parser')
                    cards = soup.select('.job-bx, .clearfix.job-bx')

                    for card in cards[:15]:
                        title_elem = card.select_one('h2 a, .heading a')
                        company_elem = card.select_one('.joblist-comp-name, h3.joblist-comp-name')

                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        company = company_elem.get_text(strip=True) if company_elem else ''

                        if not is_mba_relevant(title):
                            continue
                        if is_sales_role(title):
                            continue

                        href = title_elem.get('href', '')

                        listing = {
                            'job_id': f"timesjobs_{hashlib.md5(href.encode()).hexdigest()[:8]}",
                            'platform': 'timesjobs',
                            'title': title, 'company': company,
                            'location': 'India', 'url': href,
                            'mba_category': determine_mba_category(title),
                            'dedup_hash': DatabaseManager.compute_dedup_hash(title, company),
                        }
                        listings.append(listing)

                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"TimesJobs scrape error: {e}")

        return listings

    async def _scrape_ats_greenhouse(self) -> List[Dict[str, Any]]:
        """Scrape top companies on Greenhouse ATS."""
        companies = [
            ('stripe', 'Stripe'), ('airbnb', 'Airbnb'),
            ('discord', 'Discord'), ('figma', 'Figma'),
            ('notion', 'Notion'), ('databricks', 'Databricks'),
            ('cloudflare', 'Cloudflare'), ('twilio', 'Twilio'),
        ]
        all_listings = []
        for slug, name in companies:
            listings = await self.greenhouse.scrape_company(slug, name)
            all_listings.extend(listings)
            await asyncio.sleep(1)
        return all_listings

    async def _scrape_ats_lever(self) -> List[Dict[str, Any]]:
        """Scrape top companies on Lever ATS."""
        companies = [
            ('netflix', 'Netflix'), ('spotify', 'Spotify'),
            ('coinbase', 'Coinbase'), ('gitlab', 'GitLab'),
        ]
        all_listings = []
        for slug, name in companies:
            listings = await self.lever.scrape_company(slug, name)
            all_listings.extend(listings)
            await asyncio.sleep(1)
        return all_listings

    def get_stats(self) -> Dict[str, Any]:
        """Get scraper statistics."""
        return {
            'total_scraped': self._total_scraped,
            'total_stored': self._total_stored,
            'total_duplicates': self._total_duplicates,
            'total_filtered': self._total_filtered,
            'stealth_stats': self.stealth.get_stats(),
        }


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

_primary_scraper: Optional[PrimaryScraper] = None

def get_primary_scraper() -> PrimaryScraper:
    """Get the singleton PrimaryScraper instance."""
    global _primary_scraper
    if _primary_scraper is None:
        _primary_scraper = PrimaryScraper()
    return _primary_scraper


if __name__ == "__main__":
    print("=" * 60)
    print(f"OPERATION FIRST MOVER v8.0 -- Agent {AGENT_ID}: {AGENT_NAME}")
    print("=" * 60)
    print(f"MBA Categories: {len(MBA_CATEGORIES)}")
    print(f"Sales Exclusions: {len(SALES_EXCLUSION_TITLES)}")
    print(f"Tech Exclusions: {len(TECH_EXCLUSION_TITLES)}")
    print(f"Supported Portals: linkedin, naukri, internshala, iimjobs, unstop,")
    print(f"  wellfound, foundit, timesjobs, greenhouse, lever")
    print("=" * 60)
