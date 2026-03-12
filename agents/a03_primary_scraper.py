"""
============================================================
AGENT A-03: PRIMARY MULTI-SOURCE SCRAPER
============================================================
Scrapes all major Indian job boards with Internshala as
the primary source, followed by Naukri, IIMjobs, LinkedIn
(via DDG dorks), Glassdoor, Indeed, and Wellfound.

Schedule:
    05:30 AM IST — Internshala full scrape (10 categories)
    12:00 PM IST — Naukri + IIMjobs scrape

Sources & Methods:
    P1: Internshala    — Mobile Ajax API + curl_cffi
    P1: Naukri         — Mobile API + CF relay
    P2: IIMjobs        — Direct requests + rotating UA
    P2: LinkedIn       — DDG dorks ONLY (never direct)
    P2: Glassdoor      — chrome120 impersonation
    P3: Indeed         — RSS feeds + curl_cffi
    P3: Wellfound      — GraphQL API

Features:
    - 10 MBA categories per Internshala scrape
    - Full pagination with configurable depth
    - Automatic stipend normalization (text -> INR monthly)
    - PPO tag detection
    - WFH/Remote detection
    - Applicant count extraction
    - Duration normalization (text -> months)
    - Batch ID tracking for pipeline tracing
    - Auto-store to raw_listings table
    - Heartbeat reporting to A-12
    - Rate limit enforcement via stealth engine
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

# Internshala configuration
INTERNSHALA_BASE_URL = "https://internshala.com"
INTERNSHALA_LISTINGS_URL = "https://internshala.com/internships"
INTERNSHALA_AJAX_URL = "https://internshala.com/internships/ajax/search_ajax"

# Naukri configuration
NAUKRI_BASE_URL = "https://www.naukri.com"
NAUKRI_API_URL = "https://www.naukri.com/jobapi/v3/search"

# IIMjobs configuration
IIMJOBS_BASE_URL = "https://www.iimjobs.com"
IIMJOBS_SEARCH_URL = "https://www.iimjobs.com/search"

# Indeed RSS
INDEED_RSS_BASE = "https://www.indeed.co.in/rss"

# Wellfound
WELLFOUND_BASE_URL = "https://wellfound.com"

# LinkedIn DDG dork template — search for DIRECT job listings
LINKEDIN_DORK = 'site:linkedin.com/jobs/view "{query}" india intern'


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
        numbers = re.findall(r'[\d.]+', text)
        if numbers:
            return float(numbers[0]) * 1000

    # Extract all numbers
    numbers = re.findall(r'[\d.]+', text)

    if not numbers:
        return 0.0

    # If range (e.g., "10000 - 15000"), take average
    if len(numbers) >= 2:
        try:
            low = float(numbers[0])
            high = float(numbers[1])
            monthly = (low + high) / 2
        except (ValueError, IndexError):
            monthly = float(numbers[0])
    else:
        monthly = float(numbers[0])

    # Handle "lump sum" or "total" — estimate monthly
    if 'lump' in stipend_text.lower() or 'total' in stipend_text.lower():
        # Assume 3-month internship
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

    # Extract numbers
    numbers = re.findall(r'[\d.]+', text)
    if not numbers:
        return 0

    value = float(numbers[0])

    # Range: take the higher value
    if len(numbers) >= 2:
        value = float(numbers[1])

    # Convert weeks to months
    if 'week' in text:
        return max(1, int(value / 4.33))

    # Convert years to months
    if 'year' in text:
        return int(value * 12)

    # Default: assume months
    return max(1, int(value))


def extract_applicant_count(text: str) -> int:
    """Extract applicant count from text like '2.3K applicants' or '450 Applicants'."""
    if not text:
        return 0

    text = text.strip().lower()

    # Handle K suffix
    k_match = re.search(r'([\d.]+)\s*k', text)
    if k_match:
        return int(float(k_match.group(1)) * 1000)

    # Extract plain number
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
    # "X days ago"
    match = re.search(r'(\d+)\s*day', text_lower)
    if match:
        return int(match.group(1))
    # "X weeks ago"
    match = re.search(r'(\d+)\s*week', text_lower)
    if match:
        return int(match.group(1)) * 7
    # "X months ago"
    match = re.search(r'(\d+)\s*month', text_lower)
    if match:
        return int(match.group(1)) * 30
    return 0


def generate_batch_id(source: str) -> str:
    """Generate a unique batch ID for tracking."""
    timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{source}_{timestamp}_{short_uuid}"


# ============================================================
# INTERNSHALA SCRAPER
# ============================================================

class InternshalaHarvester:
    """
    Deep scraper for Internshala — the PRIMARY source.
    Uses the mobile Ajax API for lighter responses and
    curl_cffi for TLS fingerprinting.

    Targets 10 MBA categories with full pagination.
    Expected yield: 200-400 listings per full scrape.
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
        self.db = db or get_db()
        self.config = get_config()
        self.batch_id = ""

    def scrape_all_categories(self, pages_per_category: int = 5) -> List[RawListing]:
        """
        Scrape all 10 MBA categories from Internshala.

        Args:
            pages_per_category: Number of pages to scrape per category

        Returns:
            List of RawListing objects
        """
        self.batch_id = generate_batch_id("internshala")
        all_listings = []
        total_start = time.time()

        logger.info(f"[{AGENT_ID}] Starting Internshala full scrape (batch: {self.batch_id})")

        for category in MBA_CATEGORIES:
            try:
                category_listings = self.scrape_category(
                    category, max_pages=pages_per_category
                )
                all_listings.extend(category_listings)
                logger.info(
                    f"[{AGENT_ID}] {category}: {len(category_listings)} listings"
                )
            except Exception as e:
                logger.error(f"[{AGENT_ID}] Error scraping {category}: {e}")
                continue

        # Store in database
        if all_listings:
            inserted = self.db.insert_raw_listings_batch(all_listings)
            logger.info(
                f"[{AGENT_ID}] Internshala complete: "
                f"{len(all_listings)} scraped, {inserted} new "
                f"({time.time() - total_start:.1f}s)"
            )

        return all_listings

    def scrape_category(self, category: str,
                        max_pages: int = 5) -> List[RawListing]:
        """
        Scrape a single MBA category from Internshala.

        Args:
            category: Category slug (e.g., 'marketing', 'finance')
            max_pages: Maximum pages to paginate

        Returns:
            List of RawListing objects
        """
        listings = []
        seen_urls: Set[str] = set()

        for page in range(1, max_pages + 1):
            try:
                page_listings = self._scrape_page(category, page)

                if not page_listings:
                    logger.debug(f"No more listings for {category} page {page}")
                    break

                # Deduplicate within batch
                for listing in page_listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        listings.append(listing)

            except Exception as e:
                logger.error(f"Error on {category} page {page}: {e}")
                break

        return listings

    def _scrape_page(self, category: str, page: int) -> List[RawListing]:
        """Scrape a single page of Internshala results."""
        listings = []

        # Build URL
        category_url = f"{INTERNSHALA_LISTINGS_URL}/{category}-internship"
        if page > 1:
            category_url += f"/page-{page}"

        # Make request through stealth engine
        response = self.stealth.get(
            category_url,
            site='internshala',
            auto_delay=True,
        )

        if not response or response.get('status_code', 0) != 200:
            logger.warning(f"Internshala page failed: {category} p{page}")
            return listings

        html = response.get('text', '')
        if not html or not BeautifulSoup:
            return listings

        # Parse HTML
        soup = BeautifulSoup(html, 'html.parser')

        # Find internship cards
        cards = soup.select('.individual_internship, .internship_meta, [data-internship_id]')

        if not cards:
            # Try alternative selectors
            cards = soup.select('.container-fluid .individual_internship_header')
            if not cards:
                cards = soup.select('[class*="internship"]')

        for card in cards:
            try:
                listing = self._parse_card(card, category)
                if listing and listing.url:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Failed to parse card: {e}")
                continue

        return listings

    def _parse_card(self, card, category: str) -> Optional[RawListing]:
        """Parse an Internshala listing card HTML element."""
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
            '.stipend, [class*="stipend"], .salary, '
            '.desktop-text .item_body:nth-child(3), .stipend_container_desktop'
        )
        if stipend_elem:
            listing.stipend = stipend_elem.get_text(strip=True)
            listing.stipend_normalized = normalize_stipend(listing.stipend)

        # Duration
        duration_elem = card.select_one(
            '.desktop-text .item_body:nth-child(2), [class*="duration"], '
            '.other_detail_item .item_body'
        )
        if duration_elem:
            listing.duration = duration_elem.get_text(strip=True)
            listing.duration_months = normalize_duration(listing.duration)

        # Applicants
        applicant_elem = card.select_one(
            '[class*="applicant"], .applications_message, '
            '.no_of_applications'
        )
        if applicant_elem:
            listing.applicants = extract_applicant_count(
                applicant_elem.get_text(strip=True)
            )

        # PPO tag
        ppo_elem = card.select_one(
            '.ppo_tag, [class*="ppo"], .badge-ppo'
        )
        if ppo_elem:
            listing.is_ppo = True
        else:
            # Check in full text
            card_text = card.get_text()
            listing.is_ppo = detect_ppo(card_text)

        # WFH tag
        wfh_elem = card.select_one(
            '[class*="work_from_home"], [class*="wfh"], .badge-wfh'
        )
        if wfh_elem:
            listing.is_wfh = True
        else:
            card_text = card.get_text()
            listing.is_wfh = detect_wfh(card_text)
            if listing.location and detect_wfh(listing.location):
                listing.is_wfh = True

        # Posted days ago
        posted_elem = card.select_one(
            '[class*="status"], .posted_by_container, '
            '.days_since, [class*="posted"]'
        )
        if posted_elem:
            listing.posted_days_ago = parse_posted_days(
                posted_elem.get_text(strip=True)
            )

        # Description (if available in card)
        desc_elem = card.select_one(
            '.internship_details, [class*="description"], '
            '.detail_text'
        )
        if desc_elem:
            listing.description_text = desc_elem.get_text(strip=True)[:5000]

        return listing if listing.title and listing.url else None

    def scrape_on_demand(self, query: str,
                         max_pages: int = 2) -> List[RawListing]:
        """
        On-demand Internshala search triggered by /internshala command.

        Args:
            query: Search query (e.g., "digital marketing mumbai")
            max_pages: Pages to scrape

        Returns:
            List of RawListing objects
        """
        self.batch_id = generate_batch_id("internshala_demand")
        listings = []
        seen_urls: Set[str] = set()

        for page in range(1, max_pages + 1):
            try:
                search_url = f"{INTERNSHALA_LISTINGS_URL}/{quote_plus(query)}-internship"
                if page > 1:
                    search_url += f"/page-{page}"

                response = self.stealth.get(
                    search_url,
                    site='internshala',
                    auto_delay=True,
                )

                if not response or response.get('status_code') != 200:
                    break

                html = response.get('text', '')
                if not html or not BeautifulSoup:
                    break

                soup = BeautifulSoup(html, 'html.parser')
                cards = soup.select('.individual_internship, [data-internship_id]')

                for card in cards:
                    try:
                        listing = self._parse_card(card, query)
                        if listing and listing.url and listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            listings.append(listing)
                    except Exception:
                        continue

                if not cards:
                    break

            except Exception as e:
                logger.error(f"On-demand Internshala search error: {e}")
                break

        # Store
        if listings:
            self.db.insert_raw_listings_batch(listings)

        return listings


# ============================================================
# NAUKRI SCRAPER — MULTI-STRATEGY
# ============================================================

class NaukriScraper:
    """
    Naukri job board scraper using multiple strategies:
      Strategy 1: DDG dorks (site:naukri.com) — most reliable
      Strategy 2: Naukri SEO-friendly URL scraping via Cloudflare /crawl
      Strategy 3: Naukri API v2 (fallback, often blocked)
    
    Naukri's API returns 406 without proper mobile app headers,
    so we primarily use DDG dorks to discover listings.
    Expected yield: 50-100 listings per scrape.
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

    def scrape_mba_internships(self, max_pages: int = 5) -> List[RawListing]:
        """Scrape MBA internship listings from Naukri via DDG dorks."""
        self.batch_id = generate_batch_id("naukri")
        all_listings = []

        # Naukri-specific DDG dork queries
        dork_queries = [
            'site:naukri.com "MBA intern" -jobs-{page}',
            'site:naukri.com "MBA internship" india',
            'site:naukri.com "management trainee" internship',
            'site:naukri.com "summer internship" MBA',
            'site:naukri.com "marketing intern" MBA stipend',
            'site:naukri.com "finance intern" MBA',
            'site:naukri.com "strategy intern" OR "consulting intern"',
            'site:naukri.com "operations intern" OR "supply chain intern"',
            'site:naukri.com "product management intern"',
            'site:naukri.com "analytics intern" MBA',
        ]

        # Also try Naukri SEO URLs via DDG
        seo_queries = [
            'site:naukri.com/job-listings mba intern 2026',
            'site:naukri.com/job-listings management trainee 2026',
            'site:naukri.com/job-listings summer internship mba',
        ]

        logger.info(f"[{AGENT_ID}] Starting Naukri scrape via DDG dorks (batch: {self.batch_id})")

        ddg = self._get_ddg()
        if not ddg:
            logger.warning(f"[{AGENT_ID}] DDG not available, trying API fallback")
            return self._api_fallback()

        queries_used = 0
        max_dorks = 8  # Rate limit DDG queries

        for query in dork_queries + seo_queries:
            if queries_used >= max_dorks:
                break
            try:
                results = ddg.text(query, region='in-en', max_results=15)
                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    # Only accept actual Naukri job listing URLs
                    if not url or 'naukri.com' not in url:
                        continue
                    # Filter for job listing URLs (not category pages)
                    if '/job-listings' in url or '/job-listings-' in url:
                        listing = self._parse_dork_result(url, title, body)
                        if listing:
                            all_listings.append(listing)

                queries_used += 1
                time.sleep(random.uniform(8, 15))

            except Exception as e:
                logger.error(f"[{AGENT_ID}] Naukri DDG dork error: {e}")
                continue

        # Deduplicate by URL
        seen = set()
        unique = []
        for l in all_listings:
            if l.url not in seen:
                seen.add(l.url)
                unique.append(l)

        if unique:
            inserted = self.db.insert_raw_listings_batch(unique)
            logger.info(
                f"[{AGENT_ID}] Naukri DDG complete: "
                f"{len(unique)} unique, {inserted} new ({queries_used} dorks)"
            )

        return unique

    def _parse_dork_result(self, url: str, title: str, body: str) -> Optional[RawListing]:
        """Parse a DDG search result for a Naukri listing."""
        listing = RawListing()
        listing.source = "naukri"
        listing.batch_id = self.batch_id
        listing.url = url.split('?')[0]  # Clean tracking params

        # Parse title: "Job Title - Company Name - Location - Naukri.com"
        title_parts = [p.strip() for p in title.split(' - ') if p.strip()]
        if title_parts:
            listing.title = title_parts[0]
            if len(title_parts) >= 2:
                # Last part is usually "Naukri.com", second-to-last is company or location
                company_part = title_parts[1] if len(title_parts) > 2 else ''
                if company_part and 'naukri' not in company_part.lower():
                    listing.company = company_part
            if len(title_parts) >= 3:
                loc_part = title_parts[2] if 'naukri' not in title_parts[2].lower() else ''
                if loc_part:
                    listing.location = loc_part

        # Parse body for more info
        listing.description_text = body[:3000] if body else ''

        # Detect category from title
        listing.category = self._detect_category(listing.title)

        # Detect PPO/WFH
        full_text = f"{listing.title} {body}"
        listing.is_ppo = detect_ppo(full_text)
        listing.is_wfh = detect_wfh(full_text)

        return listing if listing.title and listing.url else None

    def _api_fallback(self) -> List[RawListing]:
        """Fallback: try Naukri API v2 with updated headers."""
        self.batch_id = generate_batch_id("naukri_api")
        listings = []
        queries = ["MBA intern", "management trainee", "summer internship MBA"]

        for query in queries:
            try:
                # Use v2 API (v3 returns 406)
                params = {
                    'noOfResults': 20,
                    'urlType': 'search_by_keyword',
                    'searchType': 'adv',
                    'keyword': query,
                    'pageNo': 1,
                    'experience': 0,
                    'sort': 'r',
                    'jobAge': 7,
                }
                url = f"https://www.naukri.com/jobapi/v2/search?{urlencode(params)}"

                naukri_headers = {
                    'Accept': 'application/json',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'appid': '109',
                    'systemid': '109',
                    'Content-Type': 'application/json',
                    'gid': 'LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE',
                    'Referer': 'https://www.naukri.com/',
                    'Origin': 'https://www.naukri.com',
                    'X-Requested-With': 'XMLHttpRequest',
                }

                response = self.stealth.get(
                    url, site='naukri', headers=naukri_headers, auto_delay=True
                )

                if not response or response.get('status_code', 0) != 200:
                    continue

                text = response.get('text', '')
                try:
                    data = json.loads(text)
                    for job in data.get('jobDetails', []):
                        listing = self._parse_naukri_api_job(job)
                        if listing:
                            listings.append(listing)
                except (json.JSONDecodeError, KeyError):
                    continue

                time.sleep(random.uniform(5, 10))

            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Naukri API fallback error: {e}")
                continue

        if listings:
            self.db.insert_raw_listings_batch(listings)
            logger.info(f"[{AGENT_ID}] Naukri API fallback: {len(listings)} listings")

        return listings

    def _parse_naukri_api_job(self, job: Dict) -> Optional[RawListing]:
        """Parse a Naukri API v2 job response."""
        try:
            listing = RawListing()
            listing.source = "naukri"
            listing.batch_id = self.batch_id
            listing.title = job.get('title', '')
            listing.company = job.get('companyName', '')
            listing.url = job.get('jdURL', '') or job.get('jobId', '')
            if listing.url and not listing.url.startswith('http'):
                listing.url = f"https://www.naukri.com{listing.url}"

            for ph in job.get('placeholders', []):
                if ph.get('type') == 'location':
                    listing.location = ph.get('label', '')
                    break

            salary = job.get('salaryDetail', {})
            listing.stipend = salary.get('label', '')
            listing.stipend_normalized = normalize_stipend(listing.stipend)
            listing.description_text = job.get('jobDescription', '')[:5000]
            listing.category = self._detect_category(listing.title)

            full_text = f"{listing.title} {listing.description_text}"
            listing.is_ppo = detect_ppo(full_text)
            listing.is_wfh = detect_wfh(full_text)

            return listing if listing.title and listing.url else None
        except Exception:
            return None

    def _detect_category(self, title: str) -> str:
        """Detect MBA category from job title."""
        title_lower = title.lower()
        category_map = {
            'marketing': ['marketing', 'brand', 'digital', 'social media', 'content', 'seo'],
            'finance': ['finance', 'financial', 'accounting', 'investment', 'banking', 'audit'],
            'operations': ['operations', 'logistics', 'supply chain', 'procurement'],
            'strategy': ['strategy', 'strategic', 'planning'],
            'consulting': ['consulting', 'consultant', 'advisory'],
            'product-management': ['product', 'product manager'],
            'human-resources': ['hr', 'human resources', 'talent', 'recruitment'],
            'supply-chain': ['supply chain', 'scm', 'warehouse', 'inventory'],
            'analytics': ['analytics', 'data', 'business intelligence'],
        }
        for cat, keywords in category_map.items():
            if any(kw in title_lower for kw in keywords):
                return cat
        return 'general'


# ============================================================
# IIMJOBS SCRAPER
# ============================================================

class IIMJobsScraper:
    """
    IIMjobs scraper — DDG dork primary + direct HTML fallback.
    IIMjobs often blocks direct requests, so DDG dorks are more reliable.
    Expected yield: 20-50 listings per scrape.
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
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

    def scrape_internships(self, max_pages: int = 3) -> List[RawListing]:
        """Scrape MBA internship listings from IIMjobs."""
        self.batch_id = generate_batch_id("iimjobs")
        all_listings = []

        logger.info(f"[{AGENT_ID}] Starting IIMjobs scrape")

        # Strategy 1: DDG dorks (primary — most reliable)
        ddg = self._get_ddg()
        if ddg:
            dork_queries = [
                'site:iimjobs.com "internship" MBA india',
                'site:iimjobs.com "summer intern" OR "management trainee"',
                'site:iimjobs.com intern stipend 2026',
                'site:iimjobs.com marketing OR finance OR strategy intern',
            ]
            for query in dork_queries[:3]:
                try:
                    results = ddg.text(query, region='in-en', max_results=12)
                    for result in results:
                        url = result.get('href', '') or result.get('link', '')
                        title = result.get('title', '')
                        body = result.get('body', '')

                        if not url or 'iimjobs.com' not in url:
                            continue

                        listing = RawListing(
                            title=title.replace(' - IIMjobs', '').replace(' | IIMjobs', '').strip(),
                            company=self._extract_company(title, body),
                            url=url.split('?')[0],
                            source="iimjobs",
                            description_text=body[:2000],
                            batch_id=self.batch_id,
                            is_ppo=detect_ppo(f"{title} {body}"),
                            is_wfh=detect_wfh(f"{title} {body}"),
                        )
                        if listing.title and listing.url:
                            all_listings.append(listing)

                    time.sleep(random.uniform(8, 15))
                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] IIMjobs DDG error: {e}")
                    continue

        # Strategy 2: Direct HTML scrape (fallback)
        if len(all_listings) < 5:
            queries = ["MBA internship", "management trainee", "summer intern"]
            for query in queries:
                try:
                    listings = self._search_html(query, max_pages)
                    all_listings.extend(listings)
                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] IIMjobs HTML error for '{query}': {e}")
                    continue

        # Deduplicate
        seen = set()
        unique = []
        for l in all_listings:
            if l.url and l.url not in seen:
                seen.add(l.url)
                unique.append(l)

        if unique:
            inserted = self.db.insert_raw_listings_batch(unique)
            logger.info(f"[{AGENT_ID}] IIMjobs: {len(unique)} unique, {inserted} new")

        return unique

    def _extract_company(self, title: str, body: str) -> str:
        for sep in [' at ', ' - ', ' | ']:
            if sep in title:
                parts = title.split(sep)
                if len(parts) >= 2:
                    comp = parts[-1].replace('IIMjobs', '').strip()
                    if comp and len(comp) > 2:
                        return comp
        return ""

    def _search_html(self, query: str, max_pages: int) -> List[RawListing]:
        """Search IIMjobs."""
        listings = []

        for page in range(1, max_pages + 1):
            url = f"{IIMJOBS_SEARCH_URL}?search={quote_plus(query)}&page={page}"

            response = self.stealth.get(
                url,
                site='iimjobs',
                auto_delay=True,
            )

            if not response or response.get('status_code') != 200:
                break

            html = response.get('text', '')
            if not html or not BeautifulSoup:
                break

            soup = BeautifulSoup(html, 'html.parser')
            job_cards = soup.select('.job-listing, .job_listing, .job-card, article')

            for card in job_cards:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)

            if not job_cards:
                break

        return listings

    def _parse_card(self, card) -> Optional[RawListing]:
        """Parse an IIMjobs listing card."""
        listing = RawListing()
        listing.source = "iimjobs"
        listing.batch_id = self.batch_id

        # Title & URL
        title_elem = card.select_one('h2 a, h3 a, .job-title a, a[class*="title"]')
        if title_elem:
            listing.title = title_elem.get_text(strip=True)
            href = title_elem.get('href', '')
            listing.url = urljoin(IIMJOBS_BASE_URL, href) if href else ''

        # Company
        company_elem = card.select_one('.company, .company-name, [class*="company"]')
        if company_elem:
            listing.company = company_elem.get_text(strip=True)

        # Location
        location_elem = card.select_one('.location, [class*="location"]')
        if location_elem:
            listing.location = location_elem.get_text(strip=True)

        # Experience / Type
        card_text = card.get_text()
        listing.is_ppo = detect_ppo(card_text)
        listing.is_wfh = detect_wfh(card_text)

        return listing if listing.title and listing.url else None


# ============================================================
# LINKEDIN DDG DORK SCRAPER
# ============================================================

class LinkedInDorkScraper:
    """
    LinkedIn job discovery via DuckDuckGo dorks.
    NEVER scrapes LinkedIn directly. Max 5 dorks/hour.

    Uses queries like:
        site:linkedin.com/jobs "marketing intern" india
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
                    logger.warning(f"[{AGENT_ID}] ddgs not installed (pip install ddgs)")
        return self._ddg

    def search_jobs(self, categories: Optional[List[str]] = None,
                    max_dorks: int = 5) -> List[RawListing]:
        """
        Search LinkedIn via DDG dorks for each category.
        Returns DIRECT job listing URLs (linkedin.com/jobs/view/...)
        NOT search result pages.

        Args:
            categories: MBA categories to search (default: all)
            max_dorks: Maximum dork queries (5/hour limit)
        """
        self.batch_id = generate_batch_id("linkedin_ddg")
        ddg = self._get_ddg()
        if not ddg:
            return []

        if categories is None:
            # Select 5 random categories
            categories = list(MBA_CATEGORIES)[:max_dorks]

        listings = []
        dork_count = 0

        # Multiple dork patterns for better coverage
        dork_patterns = [
            'site:linkedin.com/jobs/view "{query}" india intern',
            'site:linkedin.com/jobs/view "{query}" internship india 2026',
            'site:in.linkedin.com/jobs/view "{query}" intern',
        ]

        for category in categories:
            if dork_count >= max_dorks:
                break

            try:
                # Try different dork patterns
                pattern = dork_patterns[dork_count % len(dork_patterns)]
                dork_query = pattern.format(query=category.replace('-', ' '))
                results = ddg.text(
                    dork_query,
                    region='in-en',
                    max_results=15,
                )

                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    # ONLY accept direct job view URLs
                    # Accept: linkedin.com/jobs/view/1234
                    # Reject: linkedin.com/jobs/search, linkedin.com/jobs/collections
                    if not url:
                        continue

                    is_direct_job = (
                        'linkedin.com/jobs/view/' in url
                        or re.search(r'linkedin\.com/jobs/\d+', url)
                    )

                    if is_direct_job:
                        # Clean the URL — remove tracking params
                        clean_url = url.split('?')[0]

                        listing = RawListing(
                            title=self._clean_linkedin_title(title),
                            company=self._extract_company_from_title(title),
                            url=clean_url,
                            source="linkedin",
                            category=category,
                            description_text=body[:2000],
                            batch_id=self.batch_id,
                            is_ppo=detect_ppo(f"{title} {body}"),
                            is_wfh=detect_wfh(f"{title} {body}"),
                        )
                        listings.append(listing)

                dork_count += 1
                # Delay between dorks
                time.sleep(random.uniform(10, 20))

            except Exception as e:
                logger.error(f"LinkedIn DDG dork error: {e}")
                continue

        if listings:
            inserted = self.db.insert_raw_listings_batch(listings)
            logger.info(f"[{AGENT_ID}] LinkedIn DDG: {len(listings)} found, {inserted} new")

        return listings

    def _clean_linkedin_title(self, title: str) -> str:
        """Clean LinkedIn title from DDG result."""
        # Remove common LinkedIn suffixes
        for suffix in [' | LinkedIn', ' - LinkedIn', ' on LinkedIn']:
            if title.endswith(suffix):
                title = title[:-len(suffix)]
        return title.strip()

    def _extract_company_from_title(self, title: str) -> str:
        """Try to extract company name from LinkedIn title."""
        # Titles often look like: "Marketing Intern at Company Name"
        for separator in [' at ', ' - ', ' | ', ' @ ']:
            if separator in title:
                parts = title.split(separator)
                if len(parts) >= 2:
                    return parts[-1].strip()
        return ""


# ============================================================
# CAREER PAGE DDG DORK SCRAPER
# ============================================================

class CareerPageScraper:
    """
    Scrapes career pages of top companies via DDG dorks.
    For companies with 'custom' ATS (McKinsey, BCG, Goldman etc.),
    we use DDG to search their career sites for internship postings.
    
    Strategy:
      - DDG: 'site:<company-careers-url> intern OR internship'
      - DDG: '<company-name> india internship MBA 2026'
      - Parse results for direct job page URLs
    """

    def __init__(self, stealth: StealthHTTPClient = None,
                 db: DatabaseManager = None):
        self.stealth = stealth or get_stealth_client()
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
                    logger.warning(f"[{AGENT_ID}] ddgs not installed for career page scraper")
        return self._ddg

    def scrape_career_pages(self, max_companies: int = 20,
                             max_dorks_per_company: int = 2) -> List[RawListing]:
        """Scrape career pages of custom ATS companies via DDG dorks."""
        self.batch_id = generate_batch_id("careerpage")
        all_listings = []

        ddg = self._get_ddg()
        if not ddg:
            logger.warning(f"[{AGENT_ID}] DDG not available for career page scraping")
            return []

        # Load companies with 'custom' ATS platform
        custom_companies = self.db.get_companies_by_ats_platform('custom', limit=max_companies)
        if not custom_companies:
            logger.info(f"[{AGENT_ID}] No custom ATS companies to scrape")
            return []

        logger.info(
            f"[{AGENT_ID}] Career page scrape: {len(custom_companies)} companies "
            f"(batch: {self.batch_id})"
        )

        companies_scraped = 0
        for company in custom_companies:
            name = company.get('name', '')
            board_id = company.get('ats_board_id', '')
            tier = company.get('tier', 5)

            if not name:
                continue

            try:
                listings = self._scrape_single_company(ddg, name, board_id, tier)
                all_listings.extend(listings)
                companies_scraped += 1

                # If DDG found nothing, try Cloudflare /crawl for JS-heavy pages
                if not listings and board_id and '.' in board_id:
                    cf_listings = self._crawl_career_page_cf(name, board_id)
                    all_listings.extend(cf_listings)
                    if cf_listings:
                        logger.info(
                            f"[{AGENT_ID}] Career [{name}] CF /crawl: {len(cf_listings)} listings"
                        )

                if listings:
                    logger.info(
                        f"[{AGENT_ID}] Career [{name}]: {len(listings)} listings found"
                    )

                time.sleep(random.uniform(8, 15))
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Career [{name}] error: {e}")
                continue

        # Deduplicate and insert
        seen_urls = set()
        unique = []
        for listing in all_listings:
            if listing.url and listing.url not in seen_urls:
                seen_urls.add(listing.url)
                unique.append(listing)

        if unique:
            inserted = self.db.insert_raw_listings_batch(unique)
            logger.info(
                f"[{AGENT_ID}] Career page scrape complete: "
                f"{companies_scraped} companies, {len(unique)} unique, {inserted} new"
            )

        return unique

    def _scrape_single_company(self, ddg, company_name: str,
                                career_url: str, tier: int) -> List[RawListing]:
        """Scrape a single company's career page via DDG dorks."""
        listings = []

        queries = []
        if career_url and '.' in career_url:
            domain = career_url.split('/')[0] if '/' in career_url else career_url
            queries.append(f'site:{domain} intern OR internship india')
            queries.append(f'site:{domain} MBA intern OR "management trainee"')
        else:
            clean_name = company_name.replace(' India', '').replace(' Ltd', '').strip()
            queries.append(f'"{clean_name}" careers intern india 2026')
            queries.append(f'"{clean_name}" internship MBA india apply')

        for query in queries[:2]:
            try:
                results = ddg.text(query, region='in-en', max_results=10)

                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    if not url or not title:
                        continue

                    skip_domains = ['linkedin.com', 'glassdoor.com', 'indeed.com',
                                     'naukri.com', 'internshala.com', 'ambitionbox.com',
                                     'wikipedia.org', 'youtube.com']
                    if any(domain in url.lower() for domain in skip_domains):
                        continue

                    url_lower = url.lower()
                    title_lower = title.lower()
                    body_lower = body.lower()

                    is_career_page = any(kw in url_lower for kw in [
                        'career', 'job', 'intern', 'hiring', 'apply',
                        'position', 'openings', 'vacancy', 'recruit',
                    ]) or any(kw in title_lower for kw in [
                        'intern', 'trainee', 'associate', 'career',
                    ]) or any(kw in body_lower for kw in [
                        'intern', 'apply now', 'stipend', 'opening',
                    ])

                    if not is_career_page:
                        continue

                    listing = RawListing(
                        title=self._clean_title(title, company_name),
                        company=company_name,
                        url=url.split('?')[0],
                        source="career_page",
                        category=self._detect_category(title),
                        description_text=body[:3000],
                        location=self._extract_location(body),
                        batch_id=self.batch_id,
                        is_ppo=detect_ppo(f"{title} {body}"),
                        is_wfh=detect_wfh(f"{title} {body}"),
                    )
                    if listing.title and listing.url:
                        listings.append(listing)

                time.sleep(random.uniform(3, 6))
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Career dork error for {company_name}: {e}")
                continue

        return listings

    def _clean_title(self, title: str, company: str) -> str:
        for suffix in [f' - {company}', f' | {company}', f' at {company}',
                       ' - Careers', ' | Careers', ' - Jobs']:
            if title.endswith(suffix):
                title = title[:-len(suffix)]
        return title.strip()

    def _detect_category(self, title: str) -> str:
        title_lower = title.lower()
        category_map = {
            'marketing': ['marketing', 'brand', 'digital', 'social media', 'content'],
            'finance': ['finance', 'financial', 'accounting', 'investment', 'banking'],
            'operations': ['operations', 'logistics', 'supply chain', 'procurement'],
            'strategy': ['strategy', 'strategic', 'planning'],
            'consulting': ['consulting', 'consultant', 'advisory'],
            'product-management': ['product', 'product manager'],
            'human-resources': ['hr', 'human resources', 'talent'],
            'analytics': ['analytics', 'data', 'business intelligence'],
        }
        for cat, keywords in category_map.items():
            if any(kw in title_lower for kw in keywords):
                return cat
        return 'general'

    def _extract_location(self, body: str) -> str:
        india_cities = [
            'mumbai', 'bangalore', 'bengaluru', 'delhi', 'gurugram',
            'gurgaon', 'hyderabad', 'chennai', 'pune', 'noida',
            'kolkata', 'ahmedabad', 'jaipur', 'chandigarh',
        ]
        body_lower = body.lower()
        for city in india_cities:
            if city in body_lower:
                return city.capitalize()
        if 'india' in body_lower:
            return 'India'
        return ''

    def _crawl_career_page_cf(self, company_name: str,
                               career_url: str) -> List[RawListing]:
        """Crawl a career page using Cloudflare /crawl API (JS rendering)."""
        try:
            from core.cloudflare_crawl import crawl_career_page, is_configured
            if not is_configured():
                return []

            full_url = f"https://{career_url}" if not career_url.startswith('http') else career_url
            jobs = crawl_career_page(
                full_url,
                keywords=['intern', 'internship', 'mba', 'trainee', 'summer']
            )

            listings = []
            for job in jobs:
                listing = RawListing(
                    title=job.get('title', ''),
                    company=company_name,
                    url=job.get('url', ''),
                    source="career_page",
                    description_text=job.get('description', '')[:3000],
                    batch_id=self.batch_id,
                )
                if listing.title and listing.url:
                    listings.append(listing)

            return listings
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] CF crawl error for {company_name}: {e}")
            return []


# ============================================================
# INSTAHYRE SCRAPER
# ============================================================

class InstahyreScraper:
    """
    Instahyre job scraper via DDG dorks.
    Instahyre is a curated job platform popular with MBA grads.
    Direct API is locked down, so we use DDG site: search.
    """

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

    def scrape_jobs(self, max_dorks: int = 5) -> List[RawListing]:
        """Scrape Instahyre via DDG dorks."""
        self.batch_id = generate_batch_id("instahyre")
        ddg = self._get_ddg()
        if not ddg:
            return []

        queries = [
            'site:instahyre.com "intern" india MBA',
            'site:instahyre.com "internship" marketing OR finance OR strategy',
            'site:instahyre.com "management trainee" india',
            'site:instahyre.com "associate" MBA fresh graduate',
            'site:instahyre.com intern stipend india 2026',
        ]

        all_listings = []
        for query in queries[:max_dorks]:
            try:
                results = ddg.text(query, region='in-en', max_results=10)
                for result in results:
                    url = result.get('href', '') or result.get('link', '')
                    title = result.get('title', '')
                    body = result.get('body', '')

                    if not url or 'instahyre.com' not in url:
                        continue

                    listing = RawListing(
                        title=title.replace(' - Instahyre', '').strip(),
                        company=self._extract_company(title, body),
                        url=url.split('?')[0],
                        source="instahyre",
                        description_text=body[:2000],
                        batch_id=self.batch_id,
                        is_ppo=detect_ppo(f"{title} {body}"),
                        is_wfh=detect_wfh(f"{title} {body}"),
                    )
                    if listing.title and listing.url:
                        all_listings.append(listing)

                time.sleep(random.uniform(8, 15))
            except Exception as e:
                logger.debug(f"[{AGENT_ID}] Instahyre dork error: {e}")
                continue

        # Dedup and insert
        seen = set()
        unique = [l for l in all_listings if l.url not in seen and not seen.add(l.url)]

        if unique:
            inserted = self.db.insert_raw_listings_batch(unique)
            logger.info(f"[{AGENT_ID}] Instahyre: {len(unique)} unique, {inserted} new")

        return unique

    def _extract_company(self, title: str, body: str) -> str:
        for sep in [' at ', ' - ', ' | ']:
            if sep in title:
                parts = title.split(sep)
                if len(parts) >= 2:
                    comp = parts[-1].replace('Instahyre', '').strip()
                    if comp and len(comp) > 2:
                        return comp
        return ""


# ============================================================
# INDEED RSS SCRAPER
# ============================================================

class IndeedRSSScraper:
    """
    Indeed India RSS feed scraper.
    No JavaScript rendering needed — pure RSS parsing.
    """

    def __init__(self, db: DatabaseManager = None):
        self.db = db or get_db()
        self.batch_id = ""

    def scrape_feeds(self) -> List[RawListing]:
        """Scrape Indeed India RSS feeds for MBA internships."""
        if not feedparser:
            logger.warning("feedparser not installed, skipping Indeed")
            return []

        self.batch_id = generate_batch_id("indeed")
        listings = []
        queries = [
            "MBA+intern", "management+intern", "marketing+intern",
            "finance+intern", "strategy+intern", "business+development+intern",
        ]

        for query in queries:
            try:
                feed_url = f"{INDEED_RSS_BASE}?q={query}&l=India&sort=date"
                feed = feedparser.parse(feed_url)

                for entry in feed.entries:
                    listing = RawListing(
                        title=entry.get('title', ''),
                        company=entry.get('source', {}).get('title', ''),
                        url=entry.get('link', ''),
                        source="indeed",
                        category=query.replace('+', ' '),
                        description_text=entry.get('summary', '')[:5000],
                        batch_id=self.batch_id,
                    )
                    # Parse description
                    if listing.description_text:
                        listing.is_ppo = detect_ppo(listing.description_text)
                        listing.is_wfh = detect_wfh(listing.description_text)

                    if listing.title and listing.url:
                        listings.append(listing)

                time.sleep(random.uniform(3, 8))

            except Exception as e:
                logger.error(f"Indeed RSS error for {query}: {e}")
                continue

        if listings:
            inserted = self.db.insert_raw_listings_batch(listings)
            logger.info(f"[{AGENT_ID}] Indeed: {len(listings)} found, {inserted} new")

        return listings


# ============================================================
# MASTER SCRAPER ORCHESTRATOR
# ============================================================

class PrimaryScraper:
    """
    Master orchestrator for Agent A-03.
    Coordinates all scrapers and manages the scraping pipeline.
    """

    def __init__(self):
        self.db = get_db()
        self.stealth = get_stealth_client()
        self.internshala = InternshalaHarvester(self.stealth, self.db)
        self.naukri = NaukriScraper(self.stealth, self.db)
        self.iimjobs = IIMJobsScraper(self.stealth, self.db)
        self.linkedin = LinkedInDorkScraper(self.db)
        self.indeed = IndeedRSSScraper(self.db)
        self.career_page = CareerPageScraper(self.stealth, self.db)
        self.instahyre = InstahyreScraper(self.db)

    def run_morning_scrape(self) -> Dict[str, Any]:
        """
        Morning scrape (05:30 AM IST).
        Primary: Internshala full (10 categories)
        """
        logger.info(f"[{AGENT_ID}] === MORNING SCRAPE START ===")
        start_time = time.time()
        results = {'source': {}, 'total': 0, 'new': 0, 'errors': []}

        # Count DB state before scraping so we can calculate net new
        pre_count = self.db.count_raw_listings()

        # Update heartbeat
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        try:
            # Internshala — PRIMARY
            try:
                internshala_listings = self.internshala.scrape_all_categories(
                    pages_per_category=5
                )
                results['source']['internshala'] = len(internshala_listings)
                results['total'] += len(internshala_listings)
            except Exception as e:
                results['errors'].append(f"Internshala: {str(e)}")
                logger.error(f"Internshala scrape failed: {e}")

            # LinkedIn DDG dorks
            try:
                linkedin_listings = self.linkedin.search_jobs(max_dorks=5)
                results['source']['linkedin'] = len(linkedin_listings)
                results['total'] += len(linkedin_listings)
            except Exception as e:
                results['errors'].append(f"LinkedIn: {str(e)}")

            # Indeed RSS
            try:
                indeed_listings = self.indeed.scrape_feeds()
                results['source']['indeed'] = len(indeed_listings)
                results['total'] += len(indeed_listings)
            except Exception as e:
                results['errors'].append(f"Indeed: {str(e)}")

            # Career Pages (custom ATS: McKinsey, BCG, Goldman etc.)
            try:
                career_listings = self.career_page.scrape_career_pages(
                    max_companies=15, max_dorks_per_company=2
                )
                results['source']['career_page'] = len(career_listings)
                results['total'] += len(career_listings)
            except Exception as e:
                results['errors'].append(f"CareerPage: {str(e)}")

            # Instahyre (curated MBA job platform)
            try:
                instahyre_listings = self.instahyre.scrape_jobs(max_dorks=4)
                results['source']['instahyre'] = len(instahyre_listings)
                results['total'] += len(instahyre_listings)
            except Exception as e:
                results['errors'].append(f"Instahyre: {str(e)}")

        except Exception as e:
            results['errors'].append(f"General: {str(e)}")

        # Calculate net new insertions
        post_count = self.db.count_raw_listings()
        results['new'] = max(0, post_count - pre_count)

        duration = time.time() - start_time
        results['duration_sec'] = round(duration, 1)

        # Update heartbeat
        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=results['new'],
            errors=len(results['errors']),
            duration_sec=duration
        )

        logger.info(
            f"[{AGENT_ID}] === MORNING SCRAPE COMPLETE === "
            f"Total: {results['total']} | New: {results['new']} | "
            f"Duration: {duration:.1f}s"
        )
        return results

    def run_afternoon_scrape(self) -> Dict[str, Any]:
        """
        Afternoon scrape (12:00 PM IST).
        Naukri + IIMjobs
        """
        logger.info(f"[{AGENT_ID}] === AFTERNOON SCRAPE START ===")
        start_time = time.time()
        results = {'source': {}, 'total': 0, 'new': 0, 'errors': []}

        # Count DB state before scraping
        pre_count = self.db.count_raw_listings()

        self.db.update_agent_heartbeat(AGENT_ID, "running")

        try:
            # Naukri — PRIMARY for afternoon (now DDG-based)
            try:
                naukri_listings = self.naukri.scrape_mba_internships(max_pages=3)
                results['source']['naukri'] = len(naukri_listings)
                results['total'] += len(naukri_listings)
            except Exception as e:
                results['errors'].append(f"Naukri: {str(e)}")

            # IIMjobs
            try:
                iimjobs_listings = self.iimjobs.scrape_internships(max_pages=3)
                results['source']['iimjobs'] = len(iimjobs_listings)
                results['total'] += len(iimjobs_listings)
            except Exception as e:
                results['errors'].append(f"IIMjobs: {str(e)}")

            # Indeed RSS (also in afternoon for broader coverage)
            try:
                indeed_listings = self.indeed.scrape_feeds()
                results['source']['indeed'] = len(indeed_listings)
                results['total'] += len(indeed_listings)
            except Exception as e:
                results['errors'].append(f"Indeed: {str(e)}")

        except Exception as e:
            results['errors'].append(f"General: {str(e)}")

        # Calculate net new insertions
        post_count = self.db.count_raw_listings()
        results['new'] = max(0, post_count - pre_count)

        duration = time.time() - start_time
        results['duration_sec'] = round(duration, 1)

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=results['new'],
            errors=len(results['errors']),
            duration_sec=duration
        )

        logger.info(
            f"[{AGENT_ID}] === AFTERNOON SCRAPE COMPLETE === "
            f"Total: {results['total']} | New: {results['new']} | "
            f"Duration: {duration:.1f}s"
        )
        return results

    def search_on_demand(self, query: str) -> List[RawListing]:
        """On-demand search triggered by /internshala command."""
        return self.internshala.scrape_on_demand(query)


# ============================================================
# MODULE-LEVEL ACCESS
# ============================================================

def get_primary_scraper() -> PrimaryScraper:
    """Get the primary scraper instance."""
    return PrimaryScraper()


if __name__ == "__main__":
    print("=" * 60)
    print(f"OPERATION FIRST MOVER v5.1 — {AGENT_NAME} Test")
    print("=" * 60)
    print(f"Agent ID: {AGENT_ID}")
    print(f"MBA Categories: {len(MBA_CATEGORIES)}")
    print(f"Utility functions ready:")
    print(f"  normalize_stipend('₹15,000/month') = {normalize_stipend('₹15,000/month')}")
    print(f"  normalize_stipend('10K /month') = {normalize_stipend('10K /month')}")
    print(f"  normalize_duration('3 Months') = {normalize_duration('3 Months')}")
    print(f"  normalize_duration('6 weeks') = {normalize_duration('6 weeks')}")
    print(f"  detect_ppo('PPO available') = {detect_ppo('PPO available')}")
    print(f"  detect_wfh('Work from home') = {detect_wfh('Work from home')}")
    print(f"  extract_applicant_count('2.3K applicants') = {extract_applicant_count('2.3K applicants')}")
    print("✅ A-03 Primary Scraper ready!")
    print("=" * 60)
