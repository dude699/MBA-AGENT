"""
============================================================
PRISM v0.2 -- JOBSPY INTEGRATION MODULE
============================================================
Integrates the open-source python-jobspy library (speedyapply/JobSpy)
for robust, multi-portal job scraping.

JobSpy supports: LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Naukri, Bayt
License: MIT (safe for integration)
GitHub: https://github.com/speedyapply/JobSpy

Key advantages over custom scrapers:
  1. Maintained by active open-source community (1000+ stars)
  2. Built-in anti-detection (TLS fingerprinting, proxy rotation)
  3. Handles pagination, rate limits, and 403 errors internally
  4. Returns structured DataFrame with consistent schema
  5. Supports LinkedIn public guest API (no login required)
  6. Supports Naukri API (bypasses 403 with proper headers)
  7. AI-ready output (title, company, description, location, etc.)

Usage in PRISM:
  - Primary scraper for LinkedIn (replaces DDG dork approach)
  - Primary scraper for Naukri (replaces flaky API v2/v3)
  - Supplementary scraper for Indeed, Glassdoor
  - Feeds into existing dedup, ghost detection, AI relevance pipeline
  
Safety:
  - Only scrapes publicly available job listings
  - hiQ Labs v. LinkedIn (US Supreme Court): public data scraping is legal
  - No login credentials used (public guest APIs only)
  - Rate-limited: 3-5s delays between requests
  - Proxy support for IP rotation (optional)
============================================================
"""

import os
import time
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import IST, get_config

MODULE_ID = "JOBSPY"


# ============================================================
# MBA-FOCUSED SEARCH QUERIES (India-specific)
# ============================================================

MBA_SEARCH_QUERIES = [
    # Core MBA internship queries
    "MBA intern India",
    "management intern India",
    "business analyst intern India",
    "strategy intern India",
    "consulting intern India",
    # Functional area queries
    "marketing intern MBA India",
    "finance intern MBA India",
    "operations intern MBA India",
    "HR intern MBA India",
    "product management intern India",
    "data analytics intern India",
    "supply chain intern India",
    "brand management intern India",
    "digital marketing intern India",
    # High-value queries
    "investment banking intern India",
    "private equity intern India",
    "venture capital intern India",
    "management consulting intern India",
    "FMCG management trainee India",
    "corporate strategy intern India",
    # Additional high-volume queries for more coverage
    "business intern India",
    "summer intern MBA India",
    "management trainee India",
    "analyst intern India",
    "research intern India",
    "project management intern India",
    "e-commerce intern India",
    "growth intern India",
    "corporate finance intern India",
    "market research intern India",
]

# Location variations for India
INDIA_LOCATIONS = [
    "India",
    "Mumbai, India",
    "Bangalore, India",
    "Delhi, India",
    "Hyderabad, India",
    "Pune, India",
    "Gurgaon, India",
    "Chennai, India",
]

# ============================================================
# AI RELEVANCE FILTER (MBA-specific)
# ============================================================

POSITIVE_KEYWORDS = {
    'mba', 'management', 'business', 'strategy', 'consulting',
    'marketing', 'finance', 'operations', 'analytics', 'product',
    'intern', 'internship', 'trainee', 'associate', 'analyst',
    'brand', 'digital', 'supply chain', 'hr', 'human resources',
    'investment', 'banking', 'private equity', 'venture capital',
    'corporate', 'fmcg', 'e-commerce', 'startup',
    # Additional terms to catch more MBA-relevant listings
    'research', 'program', 'coordinator', 'planner', 'specialist',
    'growth', 'project', 'category', 'procurement', 'logistics',
    'ecommerce', 'commerce', 'advisory', 'risk', 'compliance',
    'transformation', 'innovation', 'insights', 'intelligence',
    'planning', 'manager', 'lead', 'head', 'director',
    'summer', 'fellow', 'apprentice', 'campus',
}

NEGATIVE_KEYWORDS = {
    'sales executive', 'telecaller', 'field sales', 'door to door',
    'insurance agent', 'commission only', 'mlm', 'network marketing',
    'data entry', 'typing', 'form filling', 'copy paste',
}

TITLE_BLOCKLIST = {
    'sales executive', 'business development executive',
    'telecaller', 'tele caller', 'insurance advisor',
    'field sales representative', 'door to door',
}


def is_mba_relevant(title: str, description: str = '') -> bool:
    """Check if a job listing is relevant for MBA internship seekers."""
    title_lower = title.lower().strip()
    desc_lower = (description or '').lower()
    
    # Block known irrelevant titles
    for blocked in TITLE_BLOCKLIST:
        if blocked in title_lower:
            return False
    
    # Check negative keywords
    combined = f"{title_lower} {desc_lower[:500]}"
    for neg in NEGATIVE_KEYWORDS:
        if neg in combined:
            return False
    
    # Check positive keywords (at least 1 must match)
    has_positive = any(kw in combined for kw in POSITIVE_KEYWORDS)
    return has_positive


def compute_content_hash(title: str, company: str, location: str = '') -> str:
    """Compute a deterministic content hash for deduplication."""
    normalized = f"{title.lower().strip()}|{company.lower().strip()}|{location.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ============================================================
# JOBSPY SCRAPER CLASS
# ============================================================

class JobSpyScraper:
    """
    Multi-portal job scraper using the python-jobspy library.
    
    Supports: LinkedIn, Indeed, Glassdoor, Google, Naukri
    All scraping uses public APIs / guest endpoints (no login required).
    """
    
    def __init__(self, db=None):
        self.db = db
        self._last_scrape_time = 0
        self._scrape_counts = defaultdict(int)
        self._daily_date = datetime.now(IST).date()
    
    def _reset_daily_if_needed(self):
        today = datetime.now(IST).date()
        if today != self._daily_date:
            self._scrape_counts.clear()
            self._daily_date = today
    
    def scrape_linkedin(self, queries: Optional[List[str]] = None,
                        max_results: int = 100,
                        hours_old: int = 72) -> List[Dict]:
        """
        Scrape LinkedIn job listings using JobSpy.
        
        Uses LinkedIn's public guest API (no login required).
        Rate limited internally by JobSpy.
        
        Args:
            queries: List of search terms (defaults to MBA_SEARCH_QUERIES)
            max_results: Maximum results per query
            hours_old: Only return jobs posted within N hours
            
        Returns:
            List of normalized listing dicts ready for database insertion
        """
        try:
            from jobspy import scrape_jobs
        except ImportError:
            logger.error(f"[{MODULE_ID}] python-jobspy not installed. Run: pip install python-jobspy")
            return []
        
        self._reset_daily_if_needed()
        queries = queries or MBA_SEARCH_QUERIES[:18]  # Use most queries for broad coverage
        all_listings = []
        seen_hashes = set()
        
        for query in queries:
            try:
                # Respect rate limits
                time.sleep(random.uniform(3, 8))
                
                location = random.choice(INDIA_LOCATIONS[:3])  # Top 3 locations
                
                logger.info(f"[{MODULE_ID}] LinkedIn scrape: '{query}' in {location}")
                
                jobs_df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=query,
                    location=location,
                    results_wanted=min(max_results, 50),  # Doubled from 25 for more results
                    hours_old=hours_old,
                    linkedin_fetch_description=True,
                    verbose=0,
                )
                
                if jobs_df is None or len(jobs_df) == 0:
                    continue
                
                for _, row in jobs_df.iterrows():
                    try:
                        listing = self._normalize_jobspy_row(row, 'linkedin')
                        if not listing:
                            continue
                        
                        # Dedup by content hash
                        content_hash = listing.get('content_hash', '')
                        if content_hash in seen_hashes:
                            continue
                        seen_hashes.add(content_hash)
                        
                        # MBA relevance filter
                        if not is_mba_relevant(listing['title'], listing.get('description_text', '')):
                            continue
                        
                        all_listings.append(listing)
                        
                    except Exception as row_err:
                        logger.debug(f"[{MODULE_ID}] Row parse error: {row_err}")
                        continue
                
                logger.info(f"[{MODULE_ID}] LinkedIn '{query}': {len(jobs_df)} raw -> {len(all_listings)} total filtered")
                
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] LinkedIn query '{query}' failed: {e}")
                continue
        
        self._scrape_counts['linkedin'] += len(all_listings)
        logger.info(f"[{MODULE_ID}] LinkedIn total: {len(all_listings)} MBA-relevant listings")
        return all_listings
    
    def scrape_naukri(self, queries: Optional[List[str]] = None,
                      max_results: int = 100,
                      hours_old: int = 168) -> List[Dict]:
        """
        Scrape Naukri job listings using JobSpy.
        
        JobSpy handles Naukri's API headers and pagination internally,
        bypassing the 403/406 errors that plague direct API calls.
        
        Args:
            queries: List of search terms
            max_results: Maximum results per query
            hours_old: Only return jobs posted within N hours (default 7 days)
            
        Returns:
            List of normalized listing dicts
        """
        try:
            from jobspy import scrape_jobs
        except ImportError:
            logger.error(f"[{MODULE_ID}] python-jobspy not installed")
            return []
        
        self._reset_daily_if_needed()
        queries = queries or MBA_SEARCH_QUERIES[:15]  # Use more queries
        all_listings = []
        seen_hashes = set()
        
        for query in queries:
            try:
                time.sleep(random.uniform(3, 8))
                
                logger.info(f"[{MODULE_ID}] Naukri scrape: '{query}'")
                
                jobs_df = scrape_jobs(
                    site_name=["naukri"],
                    search_term=query,
                    location="India",
                    results_wanted=min(max_results, 50),  # Doubled from 25 for more results
                    hours_old=hours_old,
                    verbose=0,
                )
                
                if jobs_df is None or len(jobs_df) == 0:
                    continue
                
                for _, row in jobs_df.iterrows():
                    try:
                        listing = self._normalize_jobspy_row(row, 'naukri')
                        if not listing:
                            continue
                        
                        content_hash = listing.get('content_hash', '')
                        if content_hash in seen_hashes:
                            continue
                        seen_hashes.add(content_hash)
                        
                        if not is_mba_relevant(listing['title'], listing.get('description_text', '')):
                            continue
                        
                        all_listings.append(listing)
                        
                    except Exception:
                        continue
                
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] Naukri query '{query}' failed: {e}")
                continue
        
        self._scrape_counts['naukri'] += len(all_listings)
        logger.info(f"[{MODULE_ID}] Naukri total: {len(all_listings)} MBA-relevant listings")
        return all_listings
    
    def scrape_indeed(self, queries: Optional[List[str]] = None,
                      max_results: int = 50) -> List[Dict]:
        """Scrape Indeed job listings using JobSpy."""
        try:
            from jobspy import scrape_jobs
        except ImportError:
            return []
        
        queries = queries or MBA_SEARCH_QUERIES[:6]
        all_listings = []
        seen_hashes = set()
        
        for query in queries:
            try:
                time.sleep(random.uniform(3, 8))
                
                jobs_df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=query,
                    location="India",
                    country_indeed="India",
                    results_wanted=min(max_results, 20),
                    hours_old=168,
                    verbose=0,
                )
                
                if jobs_df is None or len(jobs_df) == 0:
                    continue
                
                for _, row in jobs_df.iterrows():
                    try:
                        listing = self._normalize_jobspy_row(row, 'indeed')
                        if not listing:
                            continue
                        
                        content_hash = listing.get('content_hash', '')
                        if content_hash in seen_hashes:
                            continue
                        seen_hashes.add(content_hash)
                        
                        if not is_mba_relevant(listing['title'], listing.get('description_text', '')):
                            continue
                        
                        all_listings.append(listing)
                    except Exception:
                        continue
                        
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] Indeed query '{query}' failed: {e}")
                continue
        
        self._scrape_counts['indeed'] += len(all_listings)
        return all_listings
    
    def scrape_glassdoor(self, queries: Optional[List[str]] = None,
                         max_results: int = 30) -> List[Dict]:
        """Scrape Glassdoor job listings using JobSpy."""
        try:
            from jobspy import scrape_jobs
        except ImportError:
            return []
        
        queries = queries or MBA_SEARCH_QUERIES[:4]
        all_listings = []
        seen_hashes = set()
        
        for query in queries:
            try:
                time.sleep(random.uniform(5, 12))
                
                jobs_df = scrape_jobs(
                    site_name=["glassdoor"],
                    search_term=query,
                    location="India",
                    country_indeed="India",
                    results_wanted=min(max_results, 15),
                    verbose=0,
                )
                
                if jobs_df is None or len(jobs_df) == 0:
                    continue
                
                for _, row in jobs_df.iterrows():
                    try:
                        listing = self._normalize_jobspy_row(row, 'glassdoor')
                        if not listing:
                            continue
                        
                        content_hash = listing.get('content_hash', '')
                        if content_hash in seen_hashes:
                            continue
                        seen_hashes.add(content_hash)
                        
                        if not is_mba_relevant(listing['title'], listing.get('description_text', '')):
                            continue
                        
                        all_listings.append(listing)
                    except Exception:
                        continue
                        
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] Glassdoor query '{query}' failed: {e}")
                continue
        
        self._scrape_counts['glassdoor'] += len(all_listings)
        return all_listings
    
    def scrape_all(self, portals: Optional[List[str]] = None,
                   max_per_portal: int = 50) -> Dict[str, List[Dict]]:
        """
        Scrape ALL supported portals in one call.
        
        Args:
            portals: List of portal names (default: linkedin, naukri, indeed)
            max_per_portal: Max results per portal
            
        Returns:
            Dict mapping portal name -> list of listings
        """
        portals = portals or ['linkedin', 'naukri', 'indeed']
        results = {}
        
        portal_methods = {
            'linkedin': lambda: self.scrape_linkedin(max_results=max_per_portal),
            'naukri': lambda: self.scrape_naukri(max_results=max_per_portal),
            'indeed': lambda: self.scrape_indeed(max_results=max_per_portal),
            'glassdoor': lambda: self.scrape_glassdoor(max_results=max_per_portal),
        }
        
        for portal in portals:
            scraper_fn = portal_methods.get(portal)
            if scraper_fn:
                try:
                    listings = scraper_fn()
                    results[portal] = listings
                    logger.info(f"[{MODULE_ID}] {portal}: {len(listings)} listings")
                except Exception as e:
                    results[portal] = []
                    logger.error(f"[{MODULE_ID}] {portal} scrape failed: {e}")
        
        total = sum(len(v) for v in results.values())
        logger.info(f"[{MODULE_ID}] Total scraped across all portals: {total}")
        return results
    
    def scrape_and_sync(self, portals: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Scrape all portals and sync results to the database + Supabase.
        This is the main entry point for the scheduled scraper.
        
        Returns:
            Summary dict with counts per portal
        """
        results = self.scrape_all(portals=portals)
        summary = {'total': 0, 'synced_db': 0, 'synced_supabase': 0, 'by_portal': {}}
        
        for portal, listings in results.items():
            summary['by_portal'][portal] = len(listings)
            summary['total'] += len(listings)
            
            # Sync to SQLite database
            if self.db and listings:
                try:
                    synced = self._sync_to_database(listings)
                    summary['synced_db'] += synced
                except Exception as e:
                    logger.error(f"[{MODULE_ID}] DB sync failed for {portal}: {e}")
            
            # Sync to Supabase
            if listings:
                try:
                    synced = self._sync_to_supabase(listings)
                    summary['synced_supabase'] += synced
                except Exception as e:
                    logger.debug(f"[{MODULE_ID}] Supabase sync failed for {portal}: {e}")
        
        return summary
    
    # ============================================================
    # INTERNAL: Row normalization
    # ============================================================
    
    def _normalize_jobspy_row(self, row, source: str) -> Optional[Dict]:
        """
        Normalize a JobSpy DataFrame row to PRISM listing format.
        
        Maps JobSpy schema -> PRISM raw_listings schema.
        """
        title = str(row.get('title', '') or '').strip()
        company = str(row.get('company', '') or '').strip()
        
        if not title or not company:
            return None
        
        # Extract location
        city = str(row.get('city', '') or '')
        state = str(row.get('state', '') or '')
        location = f"{city}, {state}".strip(', ') if city or state else 'India'
        if not location or location == ',':
            location = str(row.get('location', '') or '') or 'India'
        
        # Extract salary/stipend
        min_amount = 0
        max_amount = 0
        try:
            min_amount = int(row.get('min_amount', 0) or 0)
            max_amount = int(row.get('max_amount', 0) or 0)
        except (ValueError, TypeError):
            pass
        
        # Convert to monthly stipend (assume annual if > 100K)
        stipend_monthly = 0
        if max_amount > 0:
            if max_amount > 100000:
                stipend_monthly = max_amount // 12
            else:
                stipend_monthly = max_amount
        elif min_amount > 0:
            if min_amount > 100000:
                stipend_monthly = min_amount // 12
            else:
                stipend_monthly = min_amount
        
        # Job URL
        job_url = str(row.get('job_url', '') or '')
        
        # Description
        description = str(row.get('description', '') or '')[:5000]
        
        # Job type
        job_type = str(row.get('job_type', '') or '').lower()
        is_internship = 'intern' in job_type or 'intern' in title.lower()
        
        # Remote detection
        is_remote = bool(row.get('is_remote', False))
        if not is_remote:
            is_remote = any(kw in (title + ' ' + location).lower() 
                          for kw in ['remote', 'work from home', 'wfh'])
        
        # Date posted
        date_posted = None
        try:
            dp = row.get('date_posted')
            if dp is not None:
                if hasattr(dp, 'isoformat'):
                    date_posted = dp.isoformat()
                else:
                    date_posted = str(dp)
        except Exception:
            pass
        
        # Content hash for dedup
        content_hash = compute_content_hash(title, company, location)
        
        # Category detection
        category = self._detect_category(title, description)
        
        # Build normalized listing
        listing = {
            'title': title,
            'company': company,
            'location': location,
            'description_text': description,
            'source': source,
            'source_url': job_url,
            'url': job_url,
            'stipend_monthly': stipend_monthly,
            'duration_months': 0,  # JobSpy doesn't always provide this
            'is_wfh': is_remote,
            'is_ppo': False,
            'applicants': 0,
            'openings': 1,
            'category': category,
            'content_hash': content_hash,
            'scraped_at': datetime.now(IST).isoformat(),
            'posted_date': date_posted,
            'source_id': f"jobspy_{source}_{content_hash}",
            'status': 'active',
            # Naukri-specific fields
            'skills': [],
            'company_rating': 0,
        }
        
        # Extract Naukri-specific fields if available
        if source == 'naukri':
            try:
                skills_raw = row.get('skills', [])
                if skills_raw and isinstance(skills_raw, (list, tuple)):
                    listing['skills'] = list(skills_raw)[:20]
                
                rating = row.get('company_rating', 0)
                if rating:
                    listing['company_rating'] = float(rating)
            except Exception:
                pass
        
        return listing
    
    def _detect_category(self, title: str, description: str) -> str:
        """Detect internship category from title and description."""
        combined = f"{title} {description[:500]}".lower()
        
        # NOTE: Order matters — more specific categories checked FIRST
        # to prevent 'strategy' from matching 'business development' keyword
        category_keywords = {
            'consulting': ['consulting', 'consultant', 'advisory', 'strategy consulting'],
            'investment_banking': ['investment banking', 'equity research', 'trading', 'ib analyst'],
            'product_management': ['product manager', 'product management', 'product owner'],
            'data_analytics': ['data analyst', 'data science', 'analytics', 'machine learning', 'ai', 'tableau', 'power bi'],
            'strategy': ['strategy', 'strategic', 'corporate development'],
            'marketing': ['marketing', 'brand', 'digital marketing', 'seo', 'social media', 'content marketing'],
            'finance': ['finance', 'financial', 'accounting', 'banking', 'equity'],
            'operations': ['operations', 'supply chain', 'logistics', 'procurement', 'manufacturing'],
            'human_resources': ['hr', 'human resource', 'talent', 'recruitment', 'people ops'],
            'sales': ['sales', 'business development', 'account management'],
            'technology': ['software', 'developer', 'engineer', 'programming', 'full stack', 'backend', 'frontend'],
        }
        
        for category, keywords in category_keywords.items():
            if any(kw in combined for kw in keywords):
                return category
        
        return 'general'
    
    # ============================================================
    # INTERNAL: Database sync
    # ============================================================
    
    def _sync_to_database(self, listings: List[Dict]) -> int:
        """Sync listings to SQLite database."""
        if not self.db:
            return 0
        
        synced = 0
        for listing in listings:
            try:
                # Use content_hash for dedup check
                existing = None
                try:
                    existing = self.db.get_raw_listing_by_hash(listing['content_hash'])
                except Exception:
                    pass
                
                if existing:
                    continue
                
                # Insert as raw listing
                self.db.insert_raw_listing(listing)
                synced += 1
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] DB insert error: {e}")
                continue
        
        return synced
    
    def _sync_to_supabase(self, listings: List[Dict]) -> int:
        """Sync listings to Supabase cloud database."""
        try:
            from core.supabase_client import is_operational
            if not is_operational():
                return 0
            
            from core.supabase_db import SupabaseJobDB
            synced = 0
            
            for listing in listings:
                try:
                    row = {
                        'title': listing['title'],
                        'company': listing['company'],
                        'location': listing.get('location', ''),
                        'description': listing.get('description_text', ''),
                        'source': listing['source'],
                        'source_url': listing.get('source_url', ''),
                        'stipend': listing.get('stipend_monthly', 0),
                        'duration': listing.get('duration_months', 0),
                        'category': listing.get('category', ''),
                        'content_hash': listing['content_hash'],
                        'is_expired': False,
                        'match_score': 50,
                        'ghost_score': 0,
                    }
                    
                    success = SupabaseJobDB.upsert_job(row)
                    if success:
                        synced += 1
                except Exception:
                    continue
            
            return synced
        except ImportError:
            return 0
        except Exception:
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        return {
            'daily_counts': dict(self._scrape_counts),
            'date': str(self._daily_date),
        }


# ============================================================
# SINGLETON
# ============================================================

_jobspy_instance: Optional[JobSpyScraper] = None


def get_jobspy_scraper() -> JobSpyScraper:
    """Get or create the singleton JobSpyScraper instance."""
    global _jobspy_instance
    if _jobspy_instance is None:
        try:
            from core.database import get_db
            _jobspy_instance = JobSpyScraper(db=get_db())
        except Exception:
            _jobspy_instance = JobSpyScraper()
    return _jobspy_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  PRISM JobSpy Integration — Self-Test")
    print("=" * 60)
    
    # Test import
    try:
        from jobspy import scrape_jobs
        print("  python-jobspy: INSTALLED")
    except ImportError:
        print("  python-jobspy: NOT INSTALLED")
        print("  Run: pip install python-jobspy")
    
    # Test relevance filter
    assert is_mba_relevant("MBA Marketing Intern", "Marketing internship at top FMCG")
    assert not is_mba_relevant("Sales Executive", "Door to door sales commission only")
    assert is_mba_relevant("Strategy Intern", "Consulting firm internship")
    print("  Relevance filter: OK")
    
    # Test hash
    h1 = compute_content_hash("MBA Intern", "Google", "Bangalore")
    h2 = compute_content_hash("mba intern", "google", "bangalore")
    assert h1 == h2, "Hash should be case-insensitive"
    print("  Content hash: OK")
    
    print(f"\n  {len(MBA_SEARCH_QUERIES)} search queries configured")
    print(f"  {len(INDIA_LOCATIONS)} India locations configured")
    print(f"\n  Ready for integration!")
    print("=" * 60)
