"""
============================================================
OPERATION FIRST MOVER v8.0 -- STEALTH ENGINE
============================================================
Anti-ban protection layer providing:
- Gaussian jitter delays (not uniform random)
- HTTP/2 via httpx with TLS fingerprint impersonation
- Sticky proxy rotation (Webshare 10 IPs + CF Worker + ScraperAPI)
- No night scraping (6 AM - 11 PM IST only)
- User-agent rotation with mobile/desktop profiles
- Cookie and session management
- Request throttling per-domain
- Human-like browsing patterns

v8.0 Anti-Ban Rules (from Blueprint Section 6):
    1. Gaussian jitter delays (not uniform)
    2. HTTP/2 via httpx
    3. Sticky proxies per portal session
    4. No scraping between 11 PM - 6 AM IST
    5. Max 50 requests/hour per portal
    6. TLS fingerprint rotation
    7. Session breaks after 5-10 pages
============================================================
"""

import os
import time
import random
import hashlib
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not installed. HTTP/2 support disabled.")

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    from curl_cffi.requests import Session as CurlSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    logger.warning("curl_cffi not installed. TLS impersonation disabled.")

try:
    import requests as sync_requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from core.config import (
    get_config, now_ist, IST,
    SITE_STEALTH_PROFILES, USER_AGENT_POOL,
    MOBILE_USER_AGENTS, DESKTOP_USER_AGENTS,
    TLS_IMPERSONATION_PROFILES,
    ProxyType, StealthTimingConfig,
)


# ============================================================
# SECTION 1: REQUEST TRACKER (Rate Limiting)
# ============================================================

class RequestTracker:
    """Tracks request rates per domain to enforce anti-ban limits."""

    def __init__(self):
        self._domain_requests: Dict[str, List[float]] = defaultdict(list)
        self._domain_cooldowns: Dict[str, float] = {}
        self._session_page_counts: Dict[str, int] = defaultdict(int)
        self._session_start_times: Dict[str, float] = {}
        self._total_requests_today: int = 0
        self._last_reset_date: Optional[str] = None

    def _cleanup_old_requests(self, domain: str, window_seconds: int = 3600):
        """Remove request timestamps older than the window."""
        cutoff = time.time() - window_seconds
        self._domain_requests[domain] = [
            t for t in self._domain_requests[domain] if t > cutoff
        ]

    def can_make_request(self, domain: str, max_per_hour: int = 50) -> bool:
        """Check if we can make a request to this domain."""
        now = time.time()

        # Check night scraping ban (11 PM - 6 AM IST)
        current_hour = now_ist().hour
        if current_hour >= 23 or current_hour < 6:
            logger.warning(f"Night scraping blocked for {domain} (hour={current_hour})")
            return False

        # Check domain cooldown
        if domain in self._domain_cooldowns:
            if now < self._domain_cooldowns[domain]:
                remaining = self._domain_cooldowns[domain] - now
                logger.debug(f"Domain {domain} in cooldown ({remaining:.0f}s remaining)")
                return False

        # Check hourly rate limit
        self._cleanup_old_requests(domain)
        if len(self._domain_requests[domain]) >= max_per_hour:
            logger.warning(f"Rate limit reached for {domain} ({max_per_hour}/hour)")
            return False

        return True

    def record_request(self, domain: str):
        """Record that a request was made to a domain."""
        self._domain_requests[domain].append(time.time())
        self._session_page_counts[domain] += 1
        self._total_requests_today += 1

    def set_cooldown(self, domain: str, seconds: int = 600):
        """Set a cooldown for a domain (no requests for N seconds)."""
        self._domain_cooldowns[domain] = time.time() + seconds
        logger.info(f"Domain {domain} cooldown set for {seconds}s")

    def should_take_session_break(self, domain: str,
                                   max_pages: int = 10) -> bool:
        """Check if we should take a break (simulates session end)."""
        count = self._session_page_counts.get(domain, 0)
        if count >= max_pages:
            return True
        return False

    def reset_session(self, domain: str):
        """Reset session counter for a domain."""
        self._session_page_counts[domain] = 0
        self._session_start_times[domain] = time.time()

    def get_hourly_count(self, domain: str) -> int:
        """Get number of requests in the last hour."""
        self._cleanup_old_requests(domain)
        return len(self._domain_requests[domain])

    def get_stats(self) -> Dict[str, Any]:
        """Get tracking statistics."""
        stats = {
            'total_requests_today': self._total_requests_today,
            'domains': {},
        }
        for domain, requests in self._domain_requests.items():
            self._cleanup_old_requests(domain)
            stats['domains'][domain] = {
                'requests_last_hour': len(requests),
                'session_pages': self._session_page_counts.get(domain, 0),
                'in_cooldown': domain in self._domain_cooldowns and
                               time.time() < self._domain_cooldowns.get(domain, 0),
            }
        return stats

    def reset_daily(self):
        """Reset daily counters."""
        self._total_requests_today = 0
        self._domain_requests.clear()
        self._domain_cooldowns.clear()
        self._session_page_counts.clear()
        self._session_start_times.clear()


# ============================================================
# SECTION 2: PROXY MANAGER
# ============================================================

class ProxyManager:
    """
    Manages proxy rotation across multiple layers:
    L1: Webshare (10 free IPs)
    L2: Cloudflare Worker relay
    L3: ScraperAPI / Scrape.do / ScrapingBee
    L4: Free proxy lists (fallback)
    L5: Direct (no proxy - for safe APIs)
    """

    def __init__(self):
        self.config = get_config()
        self._webshare_proxies: List[str] = []
        self._free_proxies: List[str] = []
        self._proxy_health: Dict[str, bool] = {}
        self._proxy_assignments: Dict[str, str] = {}  # domain -> proxy
        self._last_refresh = None

    async def initialize(self) -> int:
        """Initialize proxy pools. Returns number of available proxies."""
        total = 0

        # Load Webshare proxies
        if self.config.webshare.api_key:
            proxies = await self._fetch_webshare_proxies()
            self._webshare_proxies = proxies
            total += len(proxies)
            logger.info(f"Loaded {len(proxies)} Webshare proxies")

        # Free proxy fallback (lightweight fetch)
        free_count = await self._fetch_free_proxies()
        total += free_count

        self._last_refresh = now_ist()
        logger.info(f"Proxy manager initialized: {total} total proxies")
        return total

    async def _fetch_webshare_proxies(self) -> List[str]:
        """Fetch proxy list from Webshare API."""
        if not self.config.webshare.api_key:
            return []

        try:
            url = self.config.webshare.api_url
            headers = {'Authorization': f'Token {self.config.webshare.api_key}'}

            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        proxies = []
                        for p in data.get('results', []):
                            proxy_str = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}"
                            proxies.append(proxy_str)
                        return proxies[:10]
            return []
        except Exception as e:
            logger.error(f"Failed to fetch Webshare proxies: {e}")
            return []

    async def _fetch_free_proxies(self) -> int:
        """Fetch free proxy list as fallback."""
        sources = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        ]
        proxies = []
        for source in sources:
            try:
                if HTTPX_AVAILABLE:
                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.get(source)
                        if resp.status_code == 200:
                            lines = resp.text.strip().split('\n')
                            proxies.extend([f"http://{l.strip()}" for l in lines[:50] if l.strip()])
                            break
            except Exception:
                continue

        self._free_proxies = proxies
        return len(proxies)

    def get_proxy_for_domain(self, domain: str,
                              proxy_type: ProxyType = ProxyType.WEBSHARE) -> Optional[str]:
        """Get a sticky proxy for a domain.
        Same domain always gets the same proxy (sticky sessions)."""
        if proxy_type == ProxyType.DIRECT:
            return None

        # Check existing assignment (sticky)
        if domain in self._proxy_assignments:
            proxy = self._proxy_assignments[domain]
            if self._proxy_health.get(proxy, True):
                return proxy

        # Assign new proxy based on type
        if proxy_type == ProxyType.WEBSHARE and self._webshare_proxies:
            # Hash-based assignment for consistency
            idx = hash(domain) % len(self._webshare_proxies)
            proxy = self._webshare_proxies[idx]
            self._proxy_assignments[domain] = proxy
            return proxy

        elif proxy_type == ProxyType.CLOUDFLARE:
            # Use CF Worker as proxy relay
            if self.config.cloudflare_relay.worker_url:
                return f"cf_relay:{self.config.cloudflare_relay.worker_url}"
            return None

        elif proxy_type in (ProxyType.SCRAPERAPI, ProxyType.SCRAPEDO, ProxyType.SCRAPINGBEE):
            # Return the API-based proxy URL
            return self._get_scraping_api_proxy(proxy_type)

        elif proxy_type == ProxyType.FREE_LIST and self._free_proxies:
            proxy = random.choice(self._free_proxies)
            return proxy

        return None

    def _get_scraping_api_proxy(self, proxy_type: ProxyType) -> Optional[str]:
        """Get scraping API proxy URL."""
        config = self.config.scraping_apis
        if proxy_type == ProxyType.SCRAPERAPI and config.scraperapi_key:
            return f"scraperapi:{config.scraperapi_key}"
        elif proxy_type == ProxyType.SCRAPEDO and config.scrapedo_token:
            return f"scrapedo:{config.scrapedo_token}"
        elif proxy_type == ProxyType.SCRAPINGBEE and config.scrapingbee_key:
            return f"scrapingbee:{config.scrapingbee_key}"
        return None

    def mark_proxy_failed(self, proxy: str):
        """Mark a proxy as failed."""
        self._proxy_health[proxy] = False
        logger.warning(f"Proxy marked as failed: {proxy[:30]}...")

    def mark_proxy_healthy(self, proxy: str):
        """Mark a proxy as healthy."""
        self._proxy_health[proxy] = True

    def get_stats(self) -> Dict[str, Any]:
        """Get proxy manager statistics."""
        return {
            'webshare_count': len(self._webshare_proxies),
            'free_count': len(self._free_proxies),
            'total_assignments': len(self._proxy_assignments),
            'failed_proxies': sum(1 for h in self._proxy_health.values() if not h),
            'last_refresh': self._last_refresh.isoformat() if self._last_refresh else None,
        }


# ============================================================
# SECTION 3: STEALTH HTTP CLIENT
# ============================================================

class StealthClient:
    """
    HTTP client with stealth capabilities:
    - TLS fingerprint impersonation (via curl_cffi)
    - HTTP/2 support (via httpx)
    - Automatic user-agent rotation
    - Gaussian delay injection
    - Proxy routing
    - Cookie persistence per domain
    """

    def __init__(self):
        self.config = get_config()
        self.proxy_manager = ProxyManager()
        self.request_tracker = RequestTracker()
        self.timing = self.config.stealth_timing
        self._cookies: Dict[str, Dict[str, str]] = {}
        self._domain_ua: Dict[str, str] = {}
        self._initialized = False

    async def initialize(self):
        """Initialize the stealth client."""
        await self.proxy_manager.initialize()
        self._initialized = True
        logger.info("Stealth client initialized")

    def _get_user_agent(self, domain: str,
                         mobile: bool = False) -> str:
        """Get a consistent user agent for a domain."""
        if domain in self._domain_ua:
            return self._domain_ua[domain]

        pool = MOBILE_USER_AGENTS if mobile else DESKTOP_USER_AGENTS
        if not pool:
            pool = USER_AGENT_POOL

        # Use hash for consistency (same domain = same UA)
        idx = hash(domain) % len(pool)
        ua = pool[idx]
        self._domain_ua[domain] = ua
        return ua

    def _get_stealth_headers(self, domain: str,
                              extra_headers: Optional[Dict] = None) -> Dict[str, str]:
        """Build stealth headers for a request."""
        profile = SITE_STEALTH_PROFILES.get(domain, {})
        mobile = profile.get('user_agent_type') == 'mobile'
        ua = self._get_user_agent(domain, mobile)

        headers = {
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        }

        # Add referrer for non-first requests
        if domain in self._cookies:
            base_url = profile.get('base_url', f'https://{domain}')
            headers['Referer'] = base_url

        if extra_headers:
            headers.update(extra_headers)

        return headers

    async def _apply_gaussian_delay(self, domain: str):
        """Apply Gaussian-distributed delay between requests."""
        profile = SITE_STEALTH_PROFILES.get(domain, {})
        min_delay = profile.get('delay_min', self.timing.min_delay)
        max_delay = profile.get('delay_max', self.timing.max_delay)

        mean = (min_delay + max_delay) / 2
        std = (max_delay - min_delay) / 4
        delay = random.gauss(mean, std)
        delay = max(min_delay, min(max_delay, delay))

        logger.debug(f"Stealth delay for {domain}: {delay:.1f}s")
        await asyncio.sleep(delay)

    async def get(self, url: str, domain: str,
                  extra_headers: Optional[Dict] = None,
                  use_proxy: bool = True,
                  max_retries: int = 3,
                  timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Make a stealth GET request with all anti-ban protections.

        Args:
            url: Target URL
            domain: Domain identifier (e.g., 'naukri', 'internshala')
            extra_headers: Additional headers to merge
            use_proxy: Whether to use proxy
            max_retries: Number of retry attempts
            timeout: Request timeout in seconds

        Returns:
            Dict with keys: status_code, text, headers, cookies, success
        """
        profile = SITE_STEALTH_PROFILES.get(domain, {})
        max_per_hour = profile.get('max_requests_per_hour', 50)

        # Check rate limits
        if not self.request_tracker.can_make_request(domain, max_per_hour):
            return {'status_code': 429, 'text': '', 'headers': {},
                    'cookies': {}, 'success': False,
                    'error': 'Rate limit - request blocked by stealth engine'}

        # Check session break
        max_pages = profile.get('max_pages_per_session', 10)
        if self.request_tracker.should_take_session_break(domain, max_pages):
            break_time = random.uniform(
                self.timing.session_break_min,
                self.timing.session_break_max,
            )
            logger.info(f"Session break for {domain}: {break_time:.0f}s")
            await asyncio.sleep(break_time)
            self.request_tracker.reset_session(domain)

        # Apply delay
        await self._apply_gaussian_delay(domain)

        # Build headers
        headers = self._get_stealth_headers(domain, extra_headers)

        # Get proxy
        proxy = None
        if use_proxy:
            proxy_type = profile.get('proxy_layer', ProxyType.DIRECT)
            if isinstance(proxy_type, str):
                proxy_type = ProxyType(proxy_type)
            proxy = self.proxy_manager.get_proxy_for_domain(domain, proxy_type)

        # Add cookies
        cookies = self._cookies.get(domain, {})

        # Make request with retries
        for attempt in range(max_retries):
            try:
                result = await self._make_request(
                    'GET', url, headers, proxy, cookies, timeout, domain
                )
                if result and result.get('success'):
                    self.request_tracker.record_request(domain)
                    # Store cookies
                    if result.get('cookies'):
                        self._cookies.setdefault(domain, {}).update(result['cookies'])
                    return result

                if result and result.get('status_code') == 429:
                    # Rate limited by server
                    wait = 30 * (attempt + 1)
                    logger.warning(f"Server rate limit on {domain}. Waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue

                if result and result.get('status_code', 0) >= 500:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue

                return result

            except Exception as e:
                logger.error(f"Stealth GET failed for {url}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5 * (attempt + 1))
                continue

        return {'status_code': 0, 'text': '', 'headers': {},
                'cookies': {}, 'success': False,
                'error': f'All {max_retries} retries failed'}

    async def post(self, url: str, domain: str,
                   data: Optional[Dict] = None,
                   json_data: Optional[Dict] = None,
                   extra_headers: Optional[Dict] = None,
                   use_proxy: bool = True,
                   timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Make a stealth POST request."""
        profile = SITE_STEALTH_PROFILES.get(domain, {})
        max_per_hour = profile.get('max_requests_per_hour', 50)

        if not self.request_tracker.can_make_request(domain, max_per_hour):
            return {'status_code': 429, 'text': '', 'success': False,
                    'error': 'Rate limit blocked'}

        await self._apply_gaussian_delay(domain)

        headers = self._get_stealth_headers(domain, extra_headers)
        if json_data:
            headers['Content-Type'] = 'application/json'

        proxy = None
        if use_proxy:
            proxy_type = profile.get('proxy_layer', ProxyType.DIRECT)
            if isinstance(proxy_type, str):
                proxy_type = ProxyType(proxy_type)
            proxy = self.proxy_manager.get_proxy_for_domain(domain, proxy_type)

        cookies = self._cookies.get(domain, {})

        try:
            result = await self._make_request(
                'POST', url, headers, proxy, cookies, timeout, domain,
                data=data, json_data=json_data
            )
            if result and result.get('success'):
                self.request_tracker.record_request(domain)
                if result.get('cookies'):
                    self._cookies.setdefault(domain, {}).update(result['cookies'])
            return result
        except Exception as e:
            logger.error(f"Stealth POST failed for {url}: {e}")
            return {'status_code': 0, 'text': '', 'success': False, 'error': str(e)}

    async def _make_request(self, method: str, url: str,
                            headers: Dict, proxy: Optional[str],
                            cookies: Dict, timeout: int, domain: str,
                            data: Optional[Dict] = None,
                            json_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute the actual HTTP request using best available client."""
        profile = SITE_STEALTH_PROFILES.get(domain, {})
        tls_profile = profile.get('tls_profile')

        # Handle ScraperAPI/Scrape.do/ScrapingBee proxy URLs
        actual_proxy = None
        actual_url = url
        if proxy and proxy.startswith('scraperapi:'):
            api_key = proxy.split(':', 1)[1]
            actual_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}"
            proxy = None
        elif proxy and proxy.startswith('scrapedo:'):
            token = proxy.split(':', 1)[1]
            actual_url = f"http://api.scrape.do?token={token}&url={url}"
            proxy = None
        elif proxy and proxy.startswith('scrapingbee:'):
            api_key = proxy.split(':', 1)[1]
            actual_url = f"https://app.scrapingbee.com/api/v1/?api_key={api_key}&url={url}"
            proxy = None
        elif proxy and proxy.startswith('cf_relay:'):
            # Use Cloudflare Worker relay
            worker_url = proxy.split(':', 1)[1]
            actual_url = worker_url
            headers['X-Target-URL'] = url
            headers['X-Relay-Secret'] = self.config.cloudflare_relay.relay_secret
            proxy = None
        else:
            actual_proxy = proxy

        # Try curl_cffi first (best TLS impersonation)
        if CURL_CFFI_AVAILABLE and tls_profile:
            return await self._request_curl_cffi(
                method, actual_url, headers, actual_proxy, cookies,
                timeout, tls_profile, data, json_data
            )

        # Fallback to httpx (HTTP/2 support)
        if HTTPX_AVAILABLE:
            return await self._request_httpx(
                method, actual_url, headers, actual_proxy, cookies,
                timeout, data, json_data
            )

        # Last resort: sync requests
        if REQUESTS_AVAILABLE:
            return await self._request_sync(
                method, actual_url, headers, actual_proxy, cookies,
                timeout, data, json_data
            )

        return {'status_code': 0, 'text': '', 'success': False,
                'error': 'No HTTP client available'}

    async def _request_curl_cffi(self, method: str, url: str,
                                  headers: Dict, proxy: Optional[str],
                                  cookies: Dict, timeout: int,
                                  tls_profile: str,
                                  data: Optional[Dict] = None,
                                  json_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make request using curl_cffi with TLS impersonation."""
        try:
            session = CurlSession(impersonate=tls_profile)
            kwargs = {
                'headers': headers,
                'timeout': timeout,
                'allow_redirects': True,
            }
            if proxy:
                kwargs['proxies'] = {'http': proxy, 'https': proxy}
            if cookies:
                kwargs['cookies'] = cookies
            if data:
                kwargs['data'] = data
            if json_data:
                kwargs['json'] = json_data

            # Run sync curl_cffi in executor
            loop = asyncio.get_event_loop()
            if method.upper() == 'GET':
                resp = await loop.run_in_executor(
                    None, lambda: session.get(url, **kwargs)
                )
            else:
                resp = await loop.run_in_executor(
                    None, lambda: session.post(url, **kwargs)
                )

            session.close()

            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'cookies': dict(resp.cookies) if hasattr(resp, 'cookies') else {},
                'success': 200 <= resp.status_code < 400,
                'client': 'curl_cffi',
            }
        except Exception as e:
            logger.error(f"curl_cffi request failed: {e}")
            return {'status_code': 0, 'text': '', 'success': False,
                    'error': str(e), 'client': 'curl_cffi'}

    async def _request_httpx(self, method: str, url: str,
                              headers: Dict, proxy: Optional[str],
                              cookies: Dict, timeout: int,
                              data: Optional[Dict] = None,
                              json_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make request using httpx (HTTP/2)."""
        try:
            client_kwargs = {
                'timeout': timeout,
                'http2': True,
                'follow_redirects': True,
            }
            if proxy:
                client_kwargs['proxies'] = proxy

            async with httpx.AsyncClient(**client_kwargs) as client:
                kwargs = {'headers': headers}
                if cookies:
                    kwargs['cookies'] = cookies
                if data:
                    kwargs['data'] = data
                if json_data:
                    kwargs['json'] = json_data

                if method.upper() == 'GET':
                    resp = await client.get(url, **kwargs)
                else:
                    resp = await client.post(url, **kwargs)

                return {
                    'status_code': resp.status_code,
                    'text': resp.text,
                    'headers': dict(resp.headers),
                    'cookies': dict(resp.cookies) if resp.cookies else {},
                    'success': 200 <= resp.status_code < 400,
                    'client': 'httpx',
                }
        except Exception as e:
            logger.error(f"httpx request failed: {e}")
            return {'status_code': 0, 'text': '', 'success': False,
                    'error': str(e), 'client': 'httpx'}

    async def _request_sync(self, method: str, url: str,
                             headers: Dict, proxy: Optional[str],
                             cookies: Dict, timeout: int,
                             data: Optional[Dict] = None,
                             json_data: Optional[Dict] = None) -> Dict[str, Any]:
        """Fallback: sync requests in executor."""
        try:
            loop = asyncio.get_event_loop()
            kwargs = {
                'headers': headers,
                'timeout': timeout,
                'allow_redirects': True,
            }
            if proxy:
                kwargs['proxies'] = {'http': proxy, 'https': proxy}
            if cookies:
                kwargs['cookies'] = cookies
            if data:
                kwargs['data'] = data
            if json_data:
                kwargs['json'] = json_data

            if method.upper() == 'GET':
                resp = await loop.run_in_executor(
                    None, lambda: sync_requests.get(url, **kwargs)
                )
            else:
                resp = await loop.run_in_executor(
                    None, lambda: sync_requests.post(url, **kwargs)
                )

            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'cookies': dict(resp.cookies) if resp.cookies else {},
                'success': 200 <= resp.status_code < 400,
                'client': 'requests',
            }
        except Exception as e:
            logger.error(f"Sync request failed: {e}")
            return {'status_code': 0, 'text': '', 'success': False,
                    'error': str(e), 'client': 'requests'}

    # ============================================================
    # SECTION 4: SCRAPING API HELPERS
    # ============================================================

    async def get_via_scraperapi(self, url: str, timeout: int = 30) -> Optional[str]:
        """Fetch a URL using ScraperAPI."""
        key = self.config.scraping_apis.scraperapi_key
        if not key:
            return None
        api_url = f"http://api.scraperapi.com?api_key={key}&url={url}"
        try:
            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(api_url)
                    if resp.status_code == 200:
                        return resp.text
            return None
        except Exception as e:
            logger.error(f"ScraperAPI request failed: {e}")
            return None

    async def get_via_scrapedo(self, url: str, timeout: int = 30) -> Optional[str]:
        """Fetch a URL using Scrape.do."""
        token = self.config.scraping_apis.scrapedo_token
        if not token:
            return None
        api_url = f"http://api.scrape.do?token={token}&url={url}"
        try:
            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(api_url)
                    if resp.status_code == 200:
                        return resp.text
            return None
        except Exception as e:
            logger.error(f"Scrape.do request failed: {e}")
            return None

    async def get_via_cf_relay(self, url: str, timeout: int = 30) -> Optional[str]:
        """Fetch a URL via Cloudflare Worker relay."""
        worker_url = self.config.cloudflare_relay.worker_url
        secret = self.config.cloudflare_relay.relay_secret
        if not worker_url or not secret:
            return None
        try:
            headers = {
                'X-Target-URL': url,
                'X-Relay-Secret': secret,
            }
            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(worker_url, headers=headers)
                    if resp.status_code == 200:
                        return resp.text
            return None
        except Exception as e:
            logger.error(f"CF relay request failed: {e}")
            return None

    # ============================================================
    # SECTION 5: COOKIE MANAGEMENT
    # ============================================================

    def set_cookies(self, domain: str, cookies: Dict[str, str]):
        """Set cookies for a domain."""
        self._cookies[domain] = cookies
        logger.debug(f"Set {len(cookies)} cookies for {domain}")

    def get_cookies(self, domain: str) -> Dict[str, str]:
        """Get cookies for a domain."""
        return self._cookies.get(domain, {})

    def clear_cookies(self, domain: str):
        """Clear cookies for a domain."""
        self._cookies.pop(domain, None)
        logger.debug(f"Cleared cookies for {domain}")

    # ============================================================
    # SECTION 6: STATUS & MONITORING
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive stealth engine stats."""
        return {
            'proxy_stats': self.proxy_manager.get_stats(),
            'request_stats': self.request_tracker.get_stats(),
            'cookies_domains': list(self._cookies.keys()),
            'ua_assignments': len(self._domain_ua),
            'initialized': self._initialized,
        }


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

_stealth_client: Optional[StealthClient] = None

def get_stealth_client() -> StealthClient:
    """Get the singleton StealthClient instance."""
    global _stealth_client
    if _stealth_client is None:
        _stealth_client = StealthClient()
    return _stealth_client


if __name__ == "__main__":
    print("=" * 60)
    print("OPERATION FIRST MOVER v8.0 -- Stealth Engine")
    print("=" * 60)
    client = get_stealth_client()
    print(f"HTTPX available: {HTTPX_AVAILABLE}")
    print(f"curl_cffi available: {CURL_CFFI_AVAILABLE}")
    print(f"requests available: {REQUESTS_AVAILABLE}")
    print(f"User agents: {len(USER_AGENT_POOL)}")
    print(f"TLS profiles: {len(TLS_IMPERSONATION_PROFILES)}")
    print(f"Site profiles: {len(SITE_STEALTH_PROFILES)}")
    print("=" * 60)
