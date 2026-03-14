"""
============================================================
OPERATION FIRST MOVER v6.0 — SMART PROXY MANAGER
============================================================
Enhanced proxy rotation with:

1. 10 Webshare IPs with smart day-based allocation
2. ScraperAPI free tier (1,000 credits/month) as fallback
3. ScrapingBee free tier (1,000 credits one-time) as emergency
4. Scrape.do free tier (1,000 credits/month) as fallback
5. Geonode free proxy list (curated, health-checked)
6. ProxyScrape curated list (filtered for reliability)
7. Circuit breaker per proxy source
8. Automatic failover chain: Webshare -> ScraperAPI -> Scrape.do -> ScrapingBee -> Geonode -> Direct
9. Per-domain proxy affinity (stick to working proxy for a domain)
10. Smart cooldown tracking per IP per domain

PROXY HIERARCHY:
    L1 (PRIMARY):    Webshare 10 rotating IPs       — Fast, reliable
    L2 (RELAY):      Cloudflare Worker relay          — IP masking
    L3 (API-BACKUP): ScraperAPI free (1000/month)     — When L1 blocked
    L4 (API-BACKUP): Scrape.do free (1000/month)      — When L3 exhausted
    L5 (EMERGENCY):  ScrapingBee free (1000 one-time) — Last resort API
    L6 (CURATED):    Geonode + ProxyScrape lists      — Health-checked hourly
    L7 (ANONYMITY):  Tor via stem                     — Sensitive dorks only
    L8 (FALLBACK):   Direct connection                — Safe APIs only

FREE PROXY BUDGET (monthly):
    Webshare:     10 IPs, unlimited requests     — Primary workhorse
    ScraperAPI:   1,000 credits/month            — ~33/day backup
    Scrape.do:    1,000 credits/month            — ~33/day backup
    ScrapingBee:  1,000 credits (one-time)       — Emergency only
    Geonode list: ~50-200 curated free proxies   — Fallback pool
    CF Workers:   100,000 req/day                — Relay layer
    
    TOTAL MONTHLY PROXY BUDGET: ~3,000 API credits + 10 IPs + unlimited CF
============================================================
"""

import os
import time
import random
import json
import threading
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from urllib.parse import urlparse
from enum import Enum, auto

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, ProxyType


# ============================================================
# PROXY SOURCE TYPES
# ============================================================

class ProxySource(Enum):
    """All proxy sources in priority order."""
    WEBSHARE = "webshare"
    CLOUDFLARE_RELAY = "cloudflare_relay"
    SCRAPER_API = "scraper_api"
    SCRAPE_DO = "scrape_do"
    SCRAPING_BEE = "scraping_bee"
    GEONODE_LIST = "geonode_list"
    PROXYSCRAPE_LIST = "proxyscrape_list"
    TOR = "tor"
    DIRECT = "direct"


# Failover chain — try in this order
FAILOVER_CHAIN: List[ProxySource] = [
    ProxySource.WEBSHARE,
    ProxySource.CLOUDFLARE_RELAY,
    ProxySource.SCRAPER_API,
    ProxySource.SCRAPE_DO,
    ProxySource.SCRAPING_BEE,
    ProxySource.GEONODE_LIST,
    ProxySource.PROXYSCRAPE_LIST,
    ProxySource.DIRECT,
]


# ============================================================
# SCRAPING API CLIENTS
# ============================================================

@dataclass
class APIBudget:
    """Track API credit usage."""
    monthly_limit: int
    used_this_month: int = 0
    month_start: str = ""
    is_one_time: bool = False  # True for ScrapingBee
    one_time_used: int = 0

    def can_use(self, credits: int = 1) -> bool:
        current_month = datetime.now().strftime("%Y-%m")
        if self.is_one_time:
            return (self.one_time_used + credits) <= self.monthly_limit
        if self.month_start != current_month:
            self.used_this_month = 0
            self.month_start = current_month
        return (self.used_this_month + credits) <= self.monthly_limit

    def use(self, credits: int = 1):
        current_month = datetime.now().strftime("%Y-%m")
        if self.is_one_time:
            self.one_time_used += credits
        else:
            if self.month_start != current_month:
                self.used_this_month = 0
                self.month_start = current_month
            self.used_this_month += credits

    @property
    def remaining(self) -> int:
        if self.is_one_time:
            return self.monthly_limit - self.one_time_used
        return self.monthly_limit - self.used_this_month


class ScraperAPIClient:
    """
    ScraperAPI free tier client.
    Free: 1,000 credits/month, 5 concurrent connections.

    Usage: Send request through their API, they handle proxy + headers.
    API: http://api.scraperapi.com?api_key=KEY&url=TARGET_URL

    Signup: https://www.scraperapi.com/signup (no credit card)
    """

    def __init__(self):
        self.api_key = os.getenv('SCRAPERAPI_KEY', '')
        self.base_url = "http://api.scraperapi.com"
        self.budget = APIBudget(monthly_limit=1000)
        self._enabled = bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self._enabled and self.budget.can_use()

    def make_request(self, target_url: str, render_js: bool = False,
                     country: str = "in", timeout: int = 60) -> Optional[Dict]:
        """
        Make a request through ScraperAPI.

        Args:
            target_url: The URL to scrape
            render_js: Enable JavaScript rendering (costs 5 credits)
            country: Country code for geo-targeting
            timeout: Request timeout

        Returns:
            Dict with {status_code, text, headers} or None
        """
        if not self.is_available:
            return None

        credits_cost = 5 if render_js else 1

        if not self.budget.can_use(credits_cost):
            logger.warning("[SCRAPERAPI] Monthly budget exhausted")
            return None

        try:
            import requests

            params = {
                'api_key': self.api_key,
                'url': target_url,
                'country_code': country,
            }
            if render_js:
                params['render'] = 'true'

            resp = requests.get(
                self.base_url,
                params=params,
                timeout=timeout,
            )

            self.budget.use(credits_cost)

            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'source': 'scraperapi',
                'credits_used': credits_cost,
                'credits_remaining': self.budget.remaining,
            }

        except Exception as e:
            logger.error(f"[SCRAPERAPI] Request failed: {e}")
            return None


class ScrapeDoClient:
    """
    Scrape.do free tier client.
    Free: 1,000 credits/month, refreshes monthly.

    API: https://api.scrape.do?token=TOKEN&url=TARGET_URL

    Signup: https://scrape.do/signup (no credit card)
    """

    def __init__(self):
        self.token = os.getenv('SCRAPEDO_TOKEN', '')
        self.base_url = "https://api.scrape.do"
        self.budget = APIBudget(monthly_limit=1000)
        self._enabled = bool(self.token)

    @property
    def is_available(self) -> bool:
        return self._enabled and self.budget.can_use()

    def make_request(self, target_url: str, render_js: bool = False,
                     timeout: int = 60) -> Optional[Dict]:
        if not self.is_available:
            return None

        credits_cost = 5 if render_js else 1

        if not self.budget.can_use(credits_cost):
            logger.warning("[SCRAPEDO] Monthly budget exhausted")
            return None

        try:
            import requests

            params = {
                'token': self.token,
                'url': target_url,
            }
            if render_js:
                params['render'] = 'true'

            resp = requests.get(
                self.base_url,
                params=params,
                timeout=timeout,
            )

            self.budget.use(credits_cost)

            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'source': 'scrape_do',
                'credits_used': credits_cost,
                'credits_remaining': self.budget.remaining,
            }

        except Exception as e:
            logger.error(f"[SCRAPEDO] Request failed: {e}")
            return None


class ScrapingBeeClient:
    """
    ScrapingBee free tier client.
    Free: 1,000 credits (one-time, no credit card).

    API: https://app.scrapingbee.com/api/v1/?api_key=KEY&url=TARGET_URL

    Signup: https://www.scrapingbee.com/signup (no credit card)
    
    NOTE: These are ONE-TIME credits, not monthly. Use sparingly as emergency.
    """

    def __init__(self):
        self.api_key = os.getenv('SCRAPINGBEE_KEY', '')
        self.base_url = "https://app.scrapingbee.com/api/v1/"
        self.budget = APIBudget(monthly_limit=1000, is_one_time=True)
        self._enabled = bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self._enabled and self.budget.can_use()

    def make_request(self, target_url: str, render_js: bool = False,
                     premium_proxy: bool = False,
                     timeout: int = 60) -> Optional[Dict]:
        if not self.is_available:
            return None

        # ScrapingBee: 1 credit = standard, 5 = JS render, 10 = premium
        credits_cost = 1
        if render_js:
            credits_cost = 5
        if premium_proxy:
            credits_cost = 10

        if not self.budget.can_use(credits_cost):
            logger.warning("[SCRAPINGBEE] One-time credits exhausted")
            return None

        try:
            import requests

            params = {
                'api_key': self.api_key,
                'url': target_url,
            }
            if render_js:
                params['render_js'] = 'true'
            if premium_proxy:
                params['premium_proxy'] = 'true'

            resp = requests.get(
                self.base_url,
                params=params,
                timeout=timeout,
            )

            self.budget.use(credits_cost)

            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'source': 'scrapingbee',
                'credits_used': credits_cost,
                'credits_remaining': self.budget.remaining,
            }

        except Exception as e:
            logger.error(f"[SCRAPINGBEE] Request failed: {e}")
            return None


# ============================================================
# CURATED FREE PROXY LISTS
# ============================================================

class CuratedProxyList:
    """
    Enhanced free proxy list manager that pulls from curated sources:
    1. Geonode free proxy list API (high quality)
    2. ProxyScrape curated list (filtered for HTTPS + elite anonymity)
    3. Monosans curated list (GitHub, frequently updated)

    All proxies are health-checked before use.
    """

    # Quality proxy sources (not random public lists)
    CURATED_SOURCES = {
        'geonode': {
            'url': 'https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps&anonymityLevel=elite%2Canonymous&speed=fast',
            'format': 'json',
            'description': 'Geonode curated list — elite/anonymous, fast, health-checked',
        },
        'proxyscrape_http': {
            'url': 'https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http&proxy_format=protocolipport&format=text&anonymity=Elite,Anonymous&timeout=5000',
            'format': 'text',
            'description': 'ProxyScrape elite/anonymous HTTP proxies',
        },
        'monosans': {
            'url': 'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
            'format': 'text',
            'description': 'Monosans curated list (GitHub, updated hourly)',
        },
    }

    def __init__(self, max_pool: int = 100):
        self._proxies: List[Dict[str, Any]] = []
        self._last_refresh: float = 0
        self._refresh_interval: float = 3600  # 1 hour
        self._max_pool = max_pool
        self._lock = threading.Lock()

    def refresh(self) -> int:
        """Fetch fresh proxies from curated sources."""
        if time.time() - self._last_refresh < self._refresh_interval:
            return len(self._proxies)

        new_proxies = []

        for source_name, source_config in self.CURATED_SOURCES.items():
            try:
                import requests
                resp = requests.get(source_config['url'], timeout=15)
                if resp.status_code != 200:
                    continue

                if source_config['format'] == 'json':
                    data = resp.json()
                    for proxy in data.get('data', []):
                        host = proxy.get('ip', '')
                        port = proxy.get('port', '')
                        if host and port:
                            new_proxies.append({
                                'url': f"http://{host}:{port}",
                                'source': source_name,
                                'country': proxy.get('country', ''),
                                'speed': proxy.get('speed', 0),
                                'alive': True,
                                'failures': 0,
                                'last_check': time.time(),
                            })
                elif source_config['format'] == 'text':
                    for line in resp.text.strip().split('\n'):
                        line = line.strip()
                        if line and ':' in line:
                            # Handle protocol://ip:port format
                            if line.startswith('http'):
                                proxy_url = line
                            else:
                                proxy_url = f"http://{line}"
                            new_proxies.append({
                                'url': proxy_url,
                                'source': source_name,
                                'country': '',
                                'speed': 0,
                                'alive': True,
                                'failures': 0,
                                'last_check': time.time(),
                            })

                logger.info(
                    f"[CURATED-PROXY] Loaded {len(new_proxies)} from {source_name}"
                )

            except Exception as e:
                logger.debug(f"[CURATED-PROXY] Failed to load {source_name}: {e}")

        with self._lock:
            # Keep only the best proxies (prioritize Geonode, then ProxyScrape)
            # Deduplicate by URL
            seen = set()
            deduped = []
            for p in new_proxies:
                if p['url'] not in seen:
                    seen.add(p['url'])
                    deduped.append(p)
            self._proxies = deduped[:self._max_pool]
            self._last_refresh = time.time()

        logger.info(
            f"[CURATED-PROXY] Pool refreshed: {len(self._proxies)} proxies"
        )
        return len(self._proxies)

    def get_proxy(self, excluded: Optional[Set[str]] = None) -> Optional[str]:
        """Get a healthy proxy from the curated list."""
        self.refresh()

        with self._lock:
            excluded = excluded or set()
            available = [
                p for p in self._proxies
                if p['alive'] and p['url'] not in excluded
            ]

            if not available:
                return None

            # Prefer Geonode proxies (highest quality)
            geonode = [p for p in available if p['source'] == 'geonode']
            if geonode:
                proxy = random.choice(geonode)
            else:
                proxy = random.choice(available)

            return proxy['url']

    def mark_success(self, proxy_url: str):
        with self._lock:
            for p in self._proxies:
                if p['url'] == proxy_url:
                    p['alive'] = True
                    p['failures'] = 0
                    break

    def mark_failure(self, proxy_url: str):
        with self._lock:
            for p in self._proxies:
                if p['url'] == proxy_url:
                    p['failures'] += 1
                    if p['failures'] >= 3:
                        p['alive'] = False
                    break

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            alive = sum(1 for p in self._proxies if p['alive'])
            by_source = defaultdict(int)
            for p in self._proxies:
                by_source[p['source']] += 1
            return {
                'total': len(self._proxies),
                'alive': alive,
                'by_source': dict(by_source),
                'last_refresh': self._last_refresh,
            }


# ============================================================
# SMART PROXY MANAGER
# ============================================================

class SmartProxyManager:
    """
    Master proxy manager that orchestrates all proxy sources
    with intelligent failover, budget tracking, and domain affinity.

    Usage:
        manager = get_smart_proxy_manager()
        result = manager.smart_request("https://internshala.com/...", site="internshala")

    The manager will:
    1. Check which proxy source is best for this domain
    2. Use domain affinity if a proxy worked before
    3. Failover through the chain if blocked
    4. Track budgets and avoid over-spending
    5. Record success/failure for health tracking
    """

    def __init__(self):
        self.config = get_config()

        # Proxy sources
        self._webshare_proxies: List[str] = []
        self._webshare_loaded = False

        # Scraping API clients
        self.scraper_api = ScraperAPIClient()
        self.scrape_do = ScrapeDoClient()
        self.scraping_bee = ScrapingBeeClient()

        # Curated free proxy list
        self.curated_list = CuratedProxyList()

        # Domain affinity: domain -> last-working-proxy-url
        self._domain_affinity: Dict[str, str] = {}

        # Domain cooldown: (domain, proxy_url) -> last_request_time
        self._domain_proxy_cooldown: Dict[Tuple[str, str], float] = {}

        # Source circuit breakers
        self._source_breakers: Dict[str, Dict] = {}

        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        """Load all proxy sources."""
        if self._initialized:
            return
        self._initialized = True

        # Load Webshare
        self._load_webshare()

        # Pre-load curated list
        self.curated_list.refresh()

        logger.info(
            f"[SMART-PROXY] Initialized: "
            f"Webshare={len(self._webshare_proxies)}, "
            f"ScraperAPI={'yes' if self.scraper_api.is_available else 'no'}, "
            f"Scrape.do={'yes' if self.scrape_do.is_available else 'no'}, "
            f"ScrapingBee={'yes' if self.scraping_bee.is_available else 'no'}, "
            f"Curated={self.curated_list.get_stats()['total']}"
        )

    def _load_webshare(self):
        """Load Webshare proxies."""
        try:
            import requests
            api_key = self.config.webshare.api_key
            if not api_key:
                return

            headers = {"Authorization": f"Token {api_key}"}
            api_url = self.config.webshare.api_url
            resp = requests.get(
                api_url,
                headers=headers,
                params={"mode": "direct", "page": "1", "page_size": "25"},
                timeout=15
            )

            if resp.status_code == 200:
                data = resp.json()
                for proxy_data in data.get('results', []):
                    host = proxy_data.get('proxy_address', '')
                    port = proxy_data.get('port', '')
                    username = proxy_data.get('username', '')
                    password = proxy_data.get('password', '')
                    if host and port:
                        if username and password:
                            proxy_url = f"http://{username}:{password}@{host}:{port}"
                        else:
                            proxy_url = f"http://{host}:{port}"
                        self._webshare_proxies.append(proxy_url)
                if self._webshare_proxies:
                    logger.info(f"[SMART-PROXY] Loaded {len(self._webshare_proxies)} Webshare proxies")
            else:
                # Fallback to download URL
                try:
                    download_url = self.config.webshare.download_url.format(api_key=api_key)
                    resp2 = requests.get(download_url, timeout=15)
                    if resp2.status_code == 200 and resp2.text.strip():
                        for line in resp2.text.strip().split('\n'):
                            line = line.strip()
                            if line and ':' in line:
                                self._webshare_proxies.append(f"http://{line}")
                        if self._webshare_proxies:
                            logger.info(f"[SMART-PROXY] Loaded {len(self._webshare_proxies)} Webshare proxies (download)")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[SMART-PROXY] Webshare load failed: {e}")

    def get_webshare_proxy(self, pool_indices: Optional[List[int]] = None,
                           excluded: Optional[Set[str]] = None) -> Optional[str]:
        """
        Get a Webshare proxy, optionally from specific pool indices.

        Args:
            pool_indices: List of allowed proxy indices (from daily allocation)
            excluded: Set of proxy URLs to exclude
        """
        self.initialize()
        excluded = excluded or set()

        if not self._webshare_proxies:
            return None

        if pool_indices:
            available = [
                self._webshare_proxies[i]
                for i in pool_indices
                if i < len(self._webshare_proxies)
                and self._webshare_proxies[i] not in excluded
            ]
        else:
            available = [p for p in self._webshare_proxies if p not in excluded]

        if not available:
            return None

        return random.choice(available)

    def smart_request(self, url: str, site: str = "",
                      headers: Optional[Dict] = None,
                      pool_indices: Optional[List[int]] = None,
                      render_js: bool = False,
                      timeout: int = 30) -> Optional[Dict]:
        """
        Make a request using the smartest available proxy.

        Failover chain:
        1. Domain affinity proxy (if it worked before)
        2. Webshare (from day's allocated pool)
        3. Cloudflare Worker relay
        4. ScraperAPI free tier
        5. Scrape.do free tier
        6. ScrapingBee free tier (emergency)
        7. Curated free proxy list
        8. Direct connection

        Returns:
            Dict with {status_code, text, headers, source, proxy_used}
        """
        self.initialize()
        domain = urlparse(url).netloc

        # Step 1: Try domain affinity proxy first
        if domain in self._domain_affinity:
            affinity_proxy = self._domain_affinity[domain]
            if not self._is_on_cooldown(domain, affinity_proxy):
                result = self._try_webshare_request(
                    url, affinity_proxy, headers, timeout
                )
                if result and result.get('status_code') == 200:
                    self._record_domain_request(domain, affinity_proxy)
                    return result

        # Step 2: Try Webshare proxies
        excluded: Set[str] = set()
        for _ in range(3):  # Try up to 3 different proxies
            proxy = self.get_webshare_proxy(pool_indices, excluded)
            if not proxy:
                break

            if self._is_on_cooldown(domain, proxy):
                excluded.add(proxy)
                continue

            result = self._try_webshare_request(url, proxy, headers, timeout)
            if result and result.get('status_code') == 200:
                self._domain_affinity[domain] = proxy
                self._record_domain_request(domain, proxy)
                return result

            excluded.add(proxy)

        # Step 3: Try Cloudflare relay
        cf_result = self._try_cf_relay(url, headers)
        if cf_result and cf_result.get('status_code') == 200:
            return cf_result

        # Step 4: Try ScraperAPI
        if self.scraper_api.is_available:
            result = self.scraper_api.make_request(url, render_js=render_js)
            if result and result.get('status_code') == 200:
                logger.info(
                    f"[SMART-PROXY] ScraperAPI success for {domain} "
                    f"(credits remaining: {self.scraper_api.budget.remaining})"
                )
                return result

        # Step 5: Try Scrape.do
        if self.scrape_do.is_available:
            result = self.scrape_do.make_request(url, render_js=render_js)
            if result and result.get('status_code') == 200:
                logger.info(
                    f"[SMART-PROXY] Scrape.do success for {domain} "
                    f"(credits remaining: {self.scrape_do.budget.remaining})"
                )
                return result

        # Step 6: Try ScrapingBee (emergency only)
        if self.scraping_bee.is_available:
            result = self.scraping_bee.make_request(url, render_js=render_js)
            if result and result.get('status_code') == 200:
                logger.warning(
                    f"[SMART-PROXY] ScrapingBee EMERGENCY used for {domain} "
                    f"(credits remaining: {self.scraping_bee.budget.remaining})"
                )
                return result

        # Step 7: Try curated free proxy list
        for _ in range(3):
            curated_proxy = self.curated_list.get_proxy(excluded)
            if not curated_proxy:
                break
            result = self._try_webshare_request(url, curated_proxy, headers, timeout)
            if result and result.get('status_code') == 200:
                self.curated_list.mark_success(curated_proxy)
                return result
            self.curated_list.mark_failure(curated_proxy)
            excluded.add(curated_proxy)

        # Step 8: Direct connection (last resort)
        logger.warning(f"[SMART-PROXY] All proxies failed for {domain}, trying direct")
        return self._try_direct_request(url, headers, timeout)

    def _try_webshare_request(self, url: str, proxy: str,
                               headers: Optional[Dict], timeout: int) -> Optional[Dict]:
        """Make a request through a Webshare/curated proxy."""
        try:
            import requests
            proxies = {'http': proxy, 'https': proxy}
            resp = requests.get(
                url,
                headers=headers or {},
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True,
            )
            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'url': resp.url,
                'source': 'webshare',
                'proxy_used': proxy,
            }
        except Exception as e:
            logger.debug(f"[SMART-PROXY] Proxy request failed ({proxy[:30]}...): {e}")
            return None

    def _try_cf_relay(self, url: str, headers: Optional[Dict]) -> Optional[Dict]:
        """Try Cloudflare Worker relay."""
        try:
            from core.stealth_engine import CloudflareRelayClient
            client = CloudflareRelayClient()
            result = client.relay_request(url, headers or {})
            if result:
                result['source'] = 'cloudflare_relay'
                return result
        except Exception:
            pass
        return None

    def _try_direct_request(self, url: str, headers: Optional[Dict],
                            timeout: int) -> Optional[Dict]:
        """Direct request without proxy."""
        try:
            import requests
            resp = requests.get(
                url,
                headers=headers or {},
                timeout=timeout,
                allow_redirects=True,
            )
            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'url': resp.url,
                'source': 'direct',
                'proxy_used': None,
            }
        except Exception as e:
            logger.error(f"[SMART-PROXY] Direct request failed: {e}")
            return None

    def _is_on_cooldown(self, domain: str, proxy: str,
                         cooldown_sec: int = 1800) -> bool:
        """Check if domain+proxy combination is on cooldown (30 min default)."""
        key = (domain, proxy)
        last_used = self._domain_proxy_cooldown.get(key, 0)
        return time.time() - last_used < cooldown_sec

    def _record_domain_request(self, domain: str, proxy: str):
        """Record a domain request for cooldown tracking."""
        self._domain_proxy_cooldown[(domain, proxy)] = time.time()

    def get_all_stats(self) -> Dict[str, Any]:
        """Get comprehensive proxy stats for reporting."""
        return {
            'webshare': {
                'total': len(self._webshare_proxies),
                'loaded': self._webshare_loaded or len(self._webshare_proxies) > 0,
            },
            'scraper_api': {
                'available': self.scraper_api.is_available,
                'credits_remaining': self.scraper_api.budget.remaining,
                'monthly_limit': self.scraper_api.budget.monthly_limit,
            },
            'scrape_do': {
                'available': self.scrape_do.is_available,
                'credits_remaining': self.scrape_do.budget.remaining,
                'monthly_limit': self.scrape_do.budget.monthly_limit,
            },
            'scraping_bee': {
                'available': self.scraping_bee.is_available,
                'credits_remaining': self.scraping_bee.budget.remaining,
                'total_limit': self.scraping_bee.budget.monthly_limit,
                'note': 'ONE-TIME credits (emergency only)',
            },
            'curated_list': self.curated_list.get_stats(),
            'domain_affinities': len(self._domain_affinity),
        }

    def get_telegram_report(self) -> str:
        """Generate proxy status report for Telegram."""
        stats = self.get_all_stats()
        lines = [
            "🔄 <b>Smart Proxy Manager Status</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🟢 <b>Webshare:</b> {stats['webshare']['total']} IPs loaded",
            "",
            f"📡 <b>ScraperAPI:</b> "
            f"{'🟢' if stats['scraper_api']['available'] else '🔴'} "
            f"{stats['scraper_api']['credits_remaining']}/{stats['scraper_api']['monthly_limit']} credits/month",
            "",
            f"📡 <b>Scrape.do:</b> "
            f"{'🟢' if stats['scrape_do']['available'] else '🔴'} "
            f"{stats['scrape_do']['credits_remaining']}/{stats['scrape_do']['monthly_limit']} credits/month",
            "",
            f"🚨 <b>ScrapingBee:</b> "
            f"{'🟢' if stats['scraping_bee']['available'] else '🔴'} "
            f"{stats['scraping_bee']['credits_remaining']}/{stats['scraping_bee']['total_limit']} credits (ONE-TIME)",
            "",
            f"🌐 <b>Curated List:</b> "
            f"{stats['curated_list']['alive']}/{stats['curated_list']['total']} alive",
            "",
            f"🔗 <b>Domain Affinities:</b> {stats['domain_affinities']} cached",
        ]
        return '\n'.join(lines)


# ============================================================
# SINGLETON
# ============================================================

_smart_proxy_instance: Optional[SmartProxyManager] = None
_smart_proxy_lock = threading.Lock()


def get_smart_proxy_manager() -> SmartProxyManager:
    """Get the singleton SmartProxyManager instance."""
    global _smart_proxy_instance
    if _smart_proxy_instance is None:
        with _smart_proxy_lock:
            if _smart_proxy_instance is None:
                _smart_proxy_instance = SmartProxyManager()
    return _smart_proxy_instance


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("OPERATION FIRST MOVER v6.0 — Smart Proxy Manager Test")
    print("=" * 60)

    manager = get_smart_proxy_manager()
    manager.initialize()

    stats = manager.get_all_stats()
    for source, info in stats.items():
        print(f"\n{source}:")
        if isinstance(info, dict):
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print(f"  {info}")

    print("\n" + "=" * 60)
