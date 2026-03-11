"""
============================================================
OPERATION FIRST MOVER v5.1 — STEALTH ENGINE (INDUSTRIAL GRADE)
============================================================
4-layer zero-detection system that makes all scraping look
like normal human browser behavior.

Stealth Philosophy:
    You are mimicking normal human browser behavior.
    A human researcher visits 5-10 pages per session
    with 30-120 second gaps.

Layer Architecture:
    L1 — Webshare Free (10 rotating IPs) — Primary
    L2 — Cloudflare Worker Relay (global IPs) — Naukri/LinkedIn
    L3 — Tor via stem (unlimited exits) — Sensitive dorks
    L4 — Free Proxy Lists (50-200 IPs) — Fallback

Features:
    - TLS fingerprint impersonation via curl_cffi
    - 22+ User-Agent rotation (mobile + desktop)
    - Human-like timing with micro-pauses
    - Per-domain cooldown tracking
    - Session management (pages per session)
    - Proxy health checking and rotation
    - Cloudflare Worker relay for IP masking
    - Tor circuit renewal for anonymity
    - Request header randomization
    - Cookie jar management
    - Referer chain simulation
    - Accept-Language/Encoding randomization
============================================================
"""

import os
import sys
import json
import time
import random
import hashlib
import asyncio
import threading
from datetime import datetime, timedelta
from typing import (
    Dict, List, Optional, Tuple, Any, Union, Set
)
from dataclasses import dataclass, field
from collections import defaultdict
from urllib.parse import urlparse
import string

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# Local imports
from core.config import (
    get_config, ProxyType, SITE_STEALTH_PROFILES,
    USER_AGENT_POOL, MOBILE_USER_AGENTS, DESKTOP_USER_AGENTS,
    TLS_IMPERSONATION_PROFILES, TLS_PROFILE_WEIGHTS,
    StealthTimingConfig,
)
from core.database import get_db, ProxyHealth


# ============================================================
# CONSTANTS
# ============================================================

# Common browser accept headers
ACCEPT_HEADERS: List[str] = [
    'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
]

ACCEPT_LANGUAGE_HEADERS: List[str] = [
    'en-IN,en;q=0.9,hi;q=0.8',
    'en-US,en;q=0.9,en-IN;q=0.8',
    'en-GB,en;q=0.9,en-US;q=0.8',
    'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7',
    'en;q=0.9,hi;q=0.8',
]

ACCEPT_ENCODING_HEADERS: List[str] = [
    'gzip, deflate, br',
    'gzip, deflate',
    'gzip, deflate, br, zstd',
]

# Common referers for Indian job searches
REFERER_POOL: List[str] = [
    'https://www.google.com/',
    'https://www.google.co.in/',
    'https://www.google.co.in/search?q=internships+india',
    'https://www.google.co.in/search?q=mba+internship+2026',
    '',  # Direct visit (no referer)
]

# Sec-CH-UA headers for Chrome impersonation
SEC_CH_UA_HEADERS: List[str] = [
    '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    '"Not_A Brand";v="8", "Chromium";v="119", "Google Chrome";v="119"',
    '"Not_A Brand";v="8", "Chromium";v="121", "Google Chrome";v="121"',
    '"Not_A Brand";v="8", "Chromium";v="124", "Google Chrome";v="124"',
]


# ============================================================
# SESSION TRACKING
# ============================================================

@dataclass
class DomainSession:
    """Track session state per domain for human-like behavior."""
    domain: str
    pages_visited: int = 0
    session_start: float = 0.0
    last_request_time: float = 0.0
    current_proxy: Optional[str] = None
    current_ua: str = ""
    current_tls_profile: str = ""
    cookies: Dict[str, str] = field(default_factory=dict)
    total_requests: int = 0
    errors: int = 0
    is_blocked: bool = False
    blocked_at: Optional[float] = None

    def should_rotate_session(self, max_pages: int = 10) -> bool:
        """Check if we should start a new session (rotate IP, UA, etc)."""
        if self.pages_visited >= max_pages:
            return True
        if self.is_blocked:
            return True
        # Session timeout (30 minutes)
        if time.time() - self.session_start > 1800:
            return True
        return False

    def start_new_session(self):
        """Reset session state."""
        self.pages_visited = 0
        self.session_start = time.time()
        self.current_proxy = None
        self.current_ua = ""
        self.current_tls_profile = ""
        self.cookies.clear()
        self.is_blocked = False
        self.blocked_at = None

    def record_request(self):
        """Record a page visit."""
        self.pages_visited += 1
        self.total_requests += 1
        self.last_request_time = time.time()

    def record_error(self):
        """Record an error."""
        self.errors += 1

    def mark_blocked(self):
        """Mark this domain as blocked (need proxy rotation)."""
        self.is_blocked = True
        self.blocked_at = time.time()


# ============================================================
# PROXY POOL MANAGER
# ============================================================

class ProxyPoolManager:
    """
    Manages the 4-layer proxy pool with health checking,
    rotation, and automatic failover.
    """

    def __init__(self):
        self.config = get_config()
        self._webshare_proxies: List[str] = []
        self._free_proxies: List[str] = []
        self._proxy_health: Dict[str, Dict] = {}
        self._last_used: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        """Load proxy lists from configured sources."""
        if self._initialized:
            return
        self._initialized = True

        # Load Webshare proxies
        if self.config.webshare.api_key:
            self._load_webshare_proxies()

        # Load free proxy list
        self._load_free_proxies()

        logger.info(
            f"Proxy pool initialized: "
            f"{len(self._webshare_proxies)} Webshare, "
            f"{len(self._free_proxies)} Free"
        )

    def _load_webshare_proxies(self):
        """Load proxies from Webshare API."""
        try:
            import requests
            api_key = self.config.webshare.api_key
            if not api_key:
                logger.debug("Webshare API key not set, skipping")
                return

            headers = {"Authorization": f"Token {api_key}"}

            # Try v2 API list endpoint first
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
                        self._proxy_health[proxy_url] = {
                            'type': 'webshare',
                            'alive': True,
                            'latency': 0,
                            'failures': 0,
                        }
                if self._webshare_proxies:
                    logger.info(f"Loaded {len(self._webshare_proxies)} Webshare proxies")
                else:
                    logger.warning("Webshare API returned 200 but no proxies found")
            elif resp.status_code in (400, 401, 403):
                # Try download URL format as fallback
                try:
                    download_url = self.config.webshare.download_url.format(api_key=api_key)
                    resp2 = requests.get(download_url, timeout=15)
                    if resp2.status_code == 200 and resp2.text.strip():
                        for line in resp2.text.strip().split('\n'):
                            line = line.strip()
                            if line and ':' in line:
                                proxy_url = f"http://{line}"
                                self._webshare_proxies.append(proxy_url)
                                self._proxy_health[proxy_url] = {
                                    'type': 'webshare',
                                    'alive': True,
                                    'latency': 0,
                                    'failures': 0,
                                }
                        if self._webshare_proxies:
                            logger.info(f"Loaded {len(self._webshare_proxies)} Webshare proxies via download URL")
                        else:
                            logger.warning(f"Webshare download URL returned no proxies")
                    else:
                        logger.warning(f"Webshare API returned {resp.status_code}, download fallback also failed")
                except Exception as e2:
                    logger.warning(f"Webshare API returned {resp.status_code}, fallback failed: {e2}")
            else:
                logger.warning(f"Webshare API returned {resp.status_code}")
        except Exception as e:
            logger.error(f"Failed to load Webshare proxies: {e}")

    def _load_free_proxies(self):
        """Load free proxy list from public sources."""
        try:
            import requests
            for source_url in self.config.free_proxy.sources[:2]:
                try:
                    resp = requests.get(source_url, timeout=10)
                    if resp.status_code == 200:
                        for line in resp.text.strip().split('\n'):
                            line = line.strip()
                            if line and ':' in line:
                                proxy_url = f"http://{line}"
                                if len(self._free_proxies) < self.config.free_proxy.max_pool_size:
                                    self._free_proxies.append(proxy_url)
                                    self._proxy_health[proxy_url] = {
                                        'type': 'free',
                                        'alive': True,
                                        'latency': 0,
                                        'failures': 0,
                                    }
                except Exception:
                    continue
            logger.info(f"Loaded {len(self._free_proxies)} free proxies")
        except Exception as e:
            logger.error(f"Failed to load free proxies: {e}")

    def get_proxy(self, proxy_type: ProxyType = ProxyType.WEBSHARE,
                  excluded: Optional[Set[str]] = None) -> Optional[str]:
        """
        Get a healthy proxy of the specified type.

        Args:
            proxy_type: Which layer to use
            excluded: Set of proxy URLs to exclude (recently used)

        Returns:
            Proxy URL string or None
        """
        self.initialize()
        excluded = excluded or set()

        with self._lock:
            if proxy_type == ProxyType.WEBSHARE:
                pool = self._webshare_proxies
                # Auto-fallback to free proxies if webshare is empty
                if not pool:
                    pool = self._free_proxies
            elif proxy_type == ProxyType.FREE_LIST:
                pool = self._free_proxies
            elif proxy_type == ProxyType.CLOUDFLARE:
                return self._get_cloudflare_proxy()
            elif proxy_type == ProxyType.TOR:
                return self._get_tor_proxy()
            elif proxy_type == ProxyType.DIRECT:
                return None
            else:
                pool = self._webshare_proxies or self._free_proxies

            # Filter healthy, non-excluded proxies
            available = [
                p for p in pool
                if p not in excluded
                and self._proxy_health.get(p, {}).get('alive', True)
            ]

            if not available:
                # Fallback to any alive proxy
                available = [
                    p for p in pool
                    if self._proxy_health.get(p, {}).get('alive', True)
                ]

            if not available:
                logger.warning(f"No healthy proxies available for {proxy_type.value}")
                return None

            # Select least recently used
            proxy = min(available, key=lambda p: self._last_used.get(p, 0))
            self._last_used[proxy] = time.time()
            return proxy

    def _get_cloudflare_proxy(self) -> Optional[str]:
        """Get Cloudflare Worker relay URL as a 'proxy'."""
        if self.config.cloudflare_relay.worker_url:
            return f"cf_relay:{self.config.cloudflare_relay.worker_url}"
        return None

    def _get_tor_proxy(self) -> Optional[str]:
        """Get Tor SOCKS5 proxy."""
        if self.config.tor.enabled:
            return f"socks5://{self.config.tor.socks_host}:{self.config.tor.socks_port}"
        return None

    def mark_proxy_success(self, proxy_url: str, latency_ms: float = 0):
        """Record a successful proxy request."""
        with self._lock:
            if proxy_url in self._proxy_health:
                health = self._proxy_health[proxy_url]
                health['alive'] = True
                health['failures'] = 0
                if latency_ms > 0:
                    health['latency'] = latency_ms

    def mark_proxy_failure(self, proxy_url: str, site: str = ""):
        """Record a failed proxy request."""
        with self._lock:
            if proxy_url in self._proxy_health:
                health = self._proxy_health[proxy_url]
                health['failures'] += 1
                if health['failures'] >= 3:
                    health['alive'] = False
                    logger.warning(f"Proxy marked dead: {proxy_url}")

    def health_check_all(self) -> Dict[str, int]:
        """Run health check on all proxies. Returns counts."""
        alive = 0
        dead = 0
        try:
            import requests
            test_url = self.config.free_proxy.test_url
            timeout = self.config.free_proxy.test_timeout_seconds

            all_proxies = self._webshare_proxies + self._free_proxies[:50]
            for proxy_url in all_proxies:
                try:
                    start = time.time()
                    resp = requests.get(
                        test_url,
                        proxies={'http': proxy_url, 'https': proxy_url},
                        timeout=timeout
                    )
                    latency = (time.time() - start) * 1000
                    if resp.status_code == 200:
                        self.mark_proxy_success(proxy_url, latency)
                        alive += 1
                    else:
                        self.mark_proxy_failure(proxy_url)
                        dead += 1
                except Exception:
                    self.mark_proxy_failure(proxy_url)
                    dead += 1
        except ImportError:
            pass

        logger.info(f"Proxy health check: {alive} alive, {dead} dead")
        return {'alive': alive, 'dead': dead}

    def get_stats(self) -> Dict[str, Any]:
        """Get proxy pool statistics."""
        webshare_alive = sum(
            1 for p in self._webshare_proxies
            if self._proxy_health.get(p, {}).get('alive', False)
        )
        free_alive = sum(
            1 for p in self._free_proxies
            if self._proxy_health.get(p, {}).get('alive', False)
        )
        return {
            'webshare_total': len(self._webshare_proxies),
            'webshare_alive': webshare_alive,
            'free_total': len(self._free_proxies),
            'free_alive': free_alive,
            'tor_enabled': self.config.tor.enabled,
            'cf_relay_configured': bool(self.config.cloudflare_relay.worker_url),
        }


# ============================================================
# STEALTH REQUEST BUILDER
# ============================================================

class StealthRequestBuilder:
    """
    Builds HTTP requests that look like real browser traffic.
    Handles header randomization, TLS fingerprinting, cookie
    management, and referer chain simulation.
    """

    def __init__(self):
        self.config = get_config()
        self._ua_index = 0
        self._tls_index = 0

    def get_random_ua(self, ua_type: str = "desktop") -> str:
        """Get a random User-Agent string."""
        if ua_type == "mobile":
            pool = MOBILE_USER_AGENTS
        elif ua_type == "desktop":
            pool = DESKTOP_USER_AGENTS
        else:
            pool = USER_AGENT_POOL
        return random.choice(pool) if pool else USER_AGENT_POOL[0]

    def get_random_tls_profile(self) -> str:
        """Get a weighted-random TLS impersonation profile."""
        profiles = list(TLS_PROFILE_WEIGHTS.keys())
        weights = list(TLS_PROFILE_WEIGHTS.values())
        return random.choices(profiles, weights=weights, k=1)[0]

    def build_headers(self, site: str = "",
                      ua_type: str = "desktop",
                      custom_headers: Optional[Dict[str, str]] = None,
                      include_referer: bool = True) -> Dict[str, str]:
        """
        Build a complete set of browser-like request headers.

        Args:
            site: Target site name for site-specific headers
            ua_type: 'desktop' or 'mobile'
            custom_headers: Additional headers to merge
            include_referer: Whether to include a referer

        Returns:
            Complete header dictionary
        """
        ua = self.get_random_ua(ua_type)
        headers = {
            'User-Agent': ua,
            'Accept': random.choice(ACCEPT_HEADERS),
            'Accept-Language': random.choice(ACCEPT_LANGUAGE_HEADERS),
            'Accept-Encoding': random.choice(ACCEPT_ENCODING_HEADERS),
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': random.choice(['max-age=0', 'no-cache', '']),
        }

        # Chrome-specific headers
        if 'Chrome' in ua:
            headers['Sec-CH-UA'] = random.choice(SEC_CH_UA_HEADERS)
            headers['Sec-CH-UA-Mobile'] = '?1' if 'Mobile' in ua else '?0'
            headers['Sec-CH-UA-Platform'] = (
                '"Android"' if 'Android' in ua
                else '"Windows"' if 'Windows' in ua
                else '"macOS"' if 'Mac' in ua
                else '"Linux"'
            )
            headers['Sec-Fetch-Dest'] = 'document'
            headers['Sec-Fetch-Mode'] = 'navigate'
            headers['Sec-Fetch-Site'] = 'none' if not include_referer else 'same-origin'
            headers['Sec-Fetch-User'] = '?1'

        # Referer
        if include_referer and random.random() > 0.3:
            headers['Referer'] = random.choice(REFERER_POOL)

        # Site-specific modifications
        profile = SITE_STEALTH_PROFILES.get(site, {})
        if site == 'internshala':
            headers['X-Requested-With'] = 'XMLHttpRequest'
            headers['Referer'] = 'https://internshala.com/internships'
        elif site == 'naukri':
            headers['appid'] = '109'
            headers['systemid'] = 'Jenga'
            headers['Accept'] = 'application/json'
            headers['Content-Type'] = 'application/json'
            headers['Referer'] = 'https://www.naukri.com/'
            headers['Origin'] = 'https://www.naukri.com'
        elif site == 'indeed':
            headers['Referer'] = 'https://www.indeed.co.in/'

        # Clean empty values
        headers = {k: v for k, v in headers.items() if v}

        # Merge custom headers
        if custom_headers:
            headers.update(custom_headers)

        return headers

    def build_mobile_headers(self, site: str = "") -> Dict[str, str]:
        """Build mobile-specific request headers."""
        return self.build_headers(site=site, ua_type="mobile")


# ============================================================
# TIMING CONTROLLER
# ============================================================

class TimingController:
    """
    Human-like timing controller that manages inter-request
    delays, micro-pauses, session breaks, and domain cooldowns.
    """

    def __init__(self):
        self.config = get_config()
        self._domain_last_request: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get_delay(self, site: str = "", base_min: float = 8.0,
                  base_max: float = 25.0) -> float:
        """
        Calculate the appropriate delay before the next request.

        Args:
            site: Target site name for site-specific timing
            base_min: Minimum delay in seconds
            base_max: Maximum delay in seconds

        Returns:
            Delay in seconds (with human-like randomization)
        """
        # Site-specific timing overrides
        profile = SITE_STEALTH_PROFILES.get(site, {})
        if profile:
            base_min = profile.get('delay_min', base_min)
            base_max = profile.get('delay_max', base_max)

        # Random uniform delay
        delay = random.uniform(base_min, base_max)

        # Add micro-pause variation (human reading simulation)
        micro_pause = random.uniform(0.5, 2.0)
        delay += micro_pause

        # Slight randomization around whole numbers (humans don't click at exact intervals)
        jitter = random.gauss(0, 0.5)
        delay += jitter

        return max(1.0, delay)

    def get_session_break(self) -> float:
        """Get a session break duration (between 1-5 minutes)."""
        return random.uniform(
            self.config.stealth_timing.session_break_min,
            self.config.stealth_timing.session_break_max
        )

    def should_cooldown(self, domain: str,
                        cooldown_sec: int = 600) -> bool:
        """Check if a domain needs cooldown (same IP, 10 min gap)."""
        with self._lock:
            last = self._domain_last_request.get(domain, 0)
            return time.time() - last < cooldown_sec

    def record_request(self, domain: str):
        """Record a request to a domain."""
        with self._lock:
            self._domain_last_request[domain] = time.time()

    async def async_delay(self, site: str = "") -> float:
        """Async version of get_delay with actual sleep."""
        delay = self.get_delay(site)
        await asyncio.sleep(delay)
        return delay

    def sync_delay(self, site: str = "") -> float:
        """Sync version with actual sleep."""
        delay = self.get_delay(site)
        time.sleep(delay)
        return delay


# ============================================================
# CLOUDFLARE RELAY CLIENT
# ============================================================

class CloudflareRelayClient:
    """
    Client for the Cloudflare Worker relay (L2 proxy layer).
    Sends requests through CF's global edge network to mask
    the origin server's IP address.
    """

    def __init__(self):
        self.config = get_config()
        self._session = None

    def _get_session(self):
        """Get or create a requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                raise ImportError("requests library required for CF relay")
        return self._session

    def relay_request(self, url: str,
                      headers: Optional[Dict[str, str]] = None,
                      method: str = "GET",
                      body: Optional[str] = None) -> Optional[Dict]:
        """
        Send a request through the Cloudflare Worker relay.

        Args:
            url: Target URL to fetch
            headers: Custom headers for the target request
            method: HTTP method (GET, POST)
            body: Request body for POST

        Returns:
            Dict with {status_code, text, headers} or None on failure.
            Response format matches stealth engine's expected format.
        """
        worker_url = self.config.cloudflare_relay.worker_url
        relay_secret = self.config.cloudflare_relay.relay_secret

        if not worker_url or not relay_secret:
            # Only warn once per session to avoid log spam
            if not hasattr(self, '_warned_no_config'):
                logger.warning(
                    "Cloudflare relay not configured. "
                    "Set CF_WORKER_URL and CF_RELAY_SECRET env vars. "
                    "Falling back to direct/Webshare proxies."
                )
                self._warned_no_config = True
            return None

        try:
            session = self._get_session()
            payload = {
                'url': url,
                'headers': headers or {},
                'method': method,
            }
            if body:
                payload['body'] = body

            # Send to worker's /relay endpoint (or root for backwards compat)
            relay_endpoint = worker_url.rstrip('/')
            if not relay_endpoint.endswith('/relay'):
                relay_endpoint += '/relay'

            resp = session.post(
                relay_endpoint,
                json=payload,
                headers={
                    'Content-Type': 'application/json',
                    'X-Relay-Secret': relay_secret,
                },
                timeout=self.config.cloudflare_relay.timeout_seconds,
            )

            if resp.status_code == 200:
                data = resp.json()
                # Normalize response to match stealth engine format
                # Worker returns {status, statusText, body, headers}
                result = {
                    'status_code': data.get('status', 0),
                    'text': data.get('body', ''),
                    'headers': data.get('headers', {}),
                    'method': 'cf_relay',
                }
                logger.debug(
                    f"CF Relay: {url} -> HTTP {result['status_code']}"
                )
                return result
            elif resp.status_code == 429:
                logger.warning("CF Relay rate limited (100/min). Backing off.")
                return None
            elif resp.status_code == 403:
                logger.error(
                    "CF Relay auth failed (403). Check CF_RELAY_SECRET matches."
                )
                return None
            elif resp.status_code == 504:
                logger.warning(f"CF Relay timeout for {url}")
                return None
            else:
                logger.warning(
                    f"CF Relay error: HTTP {resp.status_code} "
                    f"for {url}: {resp.text[:200]}"
                )
                return None

        except Exception as e:
            logger.error(f"CF Relay request failed for {url}: {e}")
            return None


# ============================================================
# TOR CLIENT
# ============================================================

class TorClient:
    """
    Tor proxy client using the stem library for circuit control.
    Used for sensitive alumni dorks and high-anonymity requests.
    """

    def __init__(self):
        self.config = get_config()
        self._controller = None

    def is_available(self) -> bool:
        """Check if Tor is available and enabled."""
        if not self.config.tor.enabled:
            return False
        try:
            import stem
            return True
        except ImportError:
            return False

    def renew_circuit(self) -> bool:
        """Request a new Tor circuit (new exit node = new IP)."""
        if not self.is_available():
            return False
        try:
            from stem import Signal
            from stem.control import Controller

            if self._controller is None:
                self._controller = Controller.from_port(
                    port=self.config.tor.control_port
                )
                if self.config.tor.control_password:
                    self._controller.authenticate(
                        password=self.config.tor.control_password
                    )
                else:
                    self._controller.authenticate()

            self._controller.signal(Signal.NEWNYM)
            time.sleep(5)  # Wait for new circuit
            logger.info("Tor circuit renewed")
            return True

        except Exception as e:
            logger.error(f"Tor circuit renewal failed: {e}")
            return False

    def get_proxy_dict(self) -> Dict[str, str]:
        """Get proxy dict for requests library."""
        socks_url = f"socks5://{self.config.tor.socks_host}:{self.config.tor.socks_port}"
        return {
            'http': socks_url,
            'https': socks_url,
        }


# ============================================================
# STEALTH HTTP CLIENT
# ============================================================

class StealthHTTPClient:
    """
    Main HTTP client that combines all stealth layers into
    a single, easy-to-use interface for making requests.

    Usage:
        client = StealthHTTPClient()
        response = client.get("https://internshala.com/internships/marketing", site="internshala")
    """

    def __init__(self):
        self.config = get_config()
        self.proxy_pool = ProxyPoolManager()
        self.request_builder = StealthRequestBuilder()
        self.timing = TimingController()
        self.cf_relay = CloudflareRelayClient()
        self.tor_client = TorClient()

        # Domain sessions
        self._sessions: Dict[str, DomainSession] = {}
        self._lock = threading.Lock()

        # Request counters per site per hour
        self._hourly_counts: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

        # curl_cffi session (lazy loaded)
        self._curl_session = None

    def _get_curl_session(self, impersonate: str = "chrome120"):
        """Get or create a curl_cffi session with TLS impersonation."""
        try:
            from curl_cffi.requests import Session
            return Session(impersonate=impersonate)
        except ImportError:
            logger.warning("curl_cffi not available, falling back to requests")
            return None

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.hostname or ""

    def _get_session(self, domain: str) -> DomainSession:
        """Get or create a domain session."""
        with self._lock:
            if domain not in self._sessions:
                self._sessions[domain] = DomainSession(
                    domain=domain,
                    session_start=time.time()
                )
            return self._sessions[domain]

    def _check_hourly_limit(self, site: str) -> bool:
        """Check if we're under the hourly request limit for a site."""
        profile = SITE_STEALTH_PROFILES.get(site, {})
        max_per_hour = profile.get('max_requests_per_hour', 50)
        current_hour = datetime.now().hour

        count = self._hourly_counts[site][current_hour]
        return count < max_per_hour

    def _record_hourly_request(self, site: str):
        """Record a request in the hourly counter."""
        current_hour = datetime.now().hour
        self._hourly_counts[site][current_hour] += 1

    # ----------------------------------------------------------
    # MAIN REQUEST METHODS
    # ----------------------------------------------------------

    def get(self, url: str, site: str = "",
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, str]] = None,
            proxy_type: Optional[ProxyType] = None,
            use_curl_cffi: bool = True,
            impersonate: Optional[str] = None,
            timeout: int = 30,
            auto_delay: bool = True,
            allow_redirects: bool = True) -> Optional[Dict[str, Any]]:
        """
        Make a stealth GET request.

        Args:
            url: Target URL
            site: Site name for profile lookup
            headers: Custom headers (merged with generated ones)
            params: URL query parameters to append
            proxy_type: Override proxy layer
            use_curl_cffi: Use curl_cffi for TLS fingerprinting
            impersonate: TLS impersonation profile
            timeout: Request timeout in seconds
            auto_delay: Apply human-like delay before request
            allow_redirects: Follow redirects

        Returns:
            Dict with {status_code, text, headers, url, latency_ms} or None
        """
        # Append query params to URL if provided
        if params:
            from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
            parsed = urlparse(url)
            existing_params = parse_qs(parsed.query)
            # Merge existing and new params (new params take priority)
            for k, v in params.items():
                existing_params[k] = [v] if isinstance(v, str) else v
            new_query = urlencode(
                {k: v[0] if isinstance(v, list) and len(v) == 1 else v
                 for k, v in existing_params.items()},
                doseq=True
            )
            url = urlunparse(parsed._replace(query=new_query))
        # Check hourly limit
        if site and not self._check_hourly_limit(site):
            logger.warning(f"Hourly limit reached for {site}")
            return None

        # Get site profile
        profile = SITE_STEALTH_PROFILES.get(site, {})

        # Resolve proxy
        if proxy_type is None:
            proxy_type = profile.get('proxy_layer', ProxyType.DIRECT)
            if isinstance(proxy_type, str):
                proxy_type = ProxyType(proxy_type)

        # Auto delay
        if auto_delay:
            self.timing.sync_delay(site)

        # Build headers
        ua_type = profile.get('user_agent_type', 'desktop')
        built_headers = self.request_builder.build_headers(
            site=site, ua_type=ua_type
        )
        if headers:
            built_headers.update(headers)

        # Resolve impersonation profile
        if impersonate is None:
            impersonate = profile.get('tls_profile', None)
        if impersonate is None and use_curl_cffi:
            impersonate = self.request_builder.get_random_tls_profile()

        # Handle Cloudflare relay
        if proxy_type == ProxyType.CLOUDFLARE:
            result = self._request_via_cf_relay(url, built_headers, "GET")
            if result is not None:
                return result
            # CF relay not configured or failed — fall back to Webshare proxies
            logger.debug(
                f"CF relay unavailable for {site}, falling back to Webshare proxy"
            )
            proxy_type = ProxyType.WEBSHARE

        # Get proxy
        proxy_url = self.proxy_pool.get_proxy(proxy_type) if proxy_type != ProxyType.DIRECT else None

        # Make the request
        start_time = time.time()

        try:
            result = None

            if use_curl_cffi and impersonate:
                result = self._curl_cffi_get(
                    url, built_headers, proxy_url,
                    impersonate, timeout, allow_redirects
                )

            if result is None:
                result = self._requests_get(
                    url, built_headers, proxy_url,
                    timeout, allow_redirects
                )

            if result:
                latency_ms = (time.time() - start_time) * 1000
                result['latency_ms'] = round(latency_ms, 1)

                # Track session
                domain = self._get_domain(url)
                session = self._get_session(domain)
                session.record_request()
                self.timing.record_request(domain)
                self._record_hourly_request(site)

                # Track proxy success
                if proxy_url:
                    self.proxy_pool.mark_proxy_success(proxy_url, latency_ms)

                # Check for block indicators
                if result.get('status_code', 0) in (403, 429, 503):
                    if proxy_url:
                        self.proxy_pool.mark_proxy_failure(proxy_url, site)
                    session.mark_blocked()
                    logger.warning(f"Possible block on {site}: HTTP {result['status_code']}")

                return result

        except Exception as e:
            logger.error(f"Stealth GET failed for {url}: {e}")
            if proxy_url:
                self.proxy_pool.mark_proxy_failure(proxy_url, site)

        return None

    def _curl_cffi_get(self, url: str, headers: Dict[str, str],
                       proxy: Optional[str], impersonate: str,
                       timeout: int, allow_redirects: bool) -> Optional[Dict]:
        """Make a request using curl_cffi for TLS fingerprinting."""
        try:
            from curl_cffi.requests import Session as CurlSession

            with CurlSession(impersonate=impersonate) as session:
                proxies = {'http': proxy, 'https': proxy} if proxy else None
                resp = session.get(
                    url,
                    headers=headers,
                    proxies=proxies,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                )
                return {
                    'status_code': resp.status_code,
                    'text': resp.text,
                    'headers': dict(resp.headers),
                    'url': str(resp.url),
                    'method': 'curl_cffi',
                    'impersonate': impersonate,
                }
        except ImportError:
            return None
        except Exception as e:
            logger.debug(f"curl_cffi GET failed: {e}")
            return None

    def _requests_get(self, url: str, headers: Dict[str, str],
                      proxy: Optional[str], timeout: int,
                      allow_redirects: bool) -> Optional[Dict]:
        """Fallback: Make a request using standard requests library."""
        try:
            import requests as req
            proxies = {'http': proxy, 'https': proxy} if proxy else None
            resp = req.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=timeout,
                allow_redirects=allow_redirects,
            )
            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'url': resp.url,
                'method': 'requests',
            }
        except Exception as e:
            logger.debug(f"requests GET failed: {e}")
            return None

    def _request_via_cf_relay(self, url: str, headers: Dict[str, str],
                              method: str = "GET") -> Optional[Dict]:
        """Route request through Cloudflare Worker relay."""
        result = self.cf_relay.relay_request(url, headers, method)
        if result:
            # relay_request already returns normalized format
            # {status_code, text, headers, method}
            result['url'] = url
            return result
        return None

    def post(self, url: str, site: str = "",
             headers: Optional[Dict[str, str]] = None,
             data: Optional[Union[str, Dict]] = None,
             json_data: Optional[Dict] = None,
             proxy_type: Optional[ProxyType] = None,
             timeout: int = 30,
             auto_delay: bool = True) -> Optional[Dict[str, Any]]:
        """Make a stealth POST request."""
        # Check hourly limit
        if site and not self._check_hourly_limit(site):
            logger.warning(f"Hourly limit reached for {site}")
            return None

        profile = SITE_STEALTH_PROFILES.get(site, {})

        if proxy_type is None:
            proxy_type = profile.get('proxy_layer', ProxyType.DIRECT)
            if isinstance(proxy_type, str):
                proxy_type = ProxyType(proxy_type)

        if auto_delay:
            self.timing.sync_delay(site)

        ua_type = profile.get('user_agent_type', 'desktop')
        built_headers = self.request_builder.build_headers(
            site=site, ua_type=ua_type
        )
        if headers:
            built_headers.update(headers)

        proxy_url = self.proxy_pool.get_proxy(proxy_type) if proxy_type != ProxyType.DIRECT else None

        start_time = time.time()

        try:
            import requests as req
            proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

            if json_data:
                built_headers['Content-Type'] = 'application/json'
                resp = req.post(
                    url, headers=built_headers, json=json_data,
                    proxies=proxies, timeout=timeout
                )
            elif data:
                resp = req.post(
                    url, headers=built_headers, data=data,
                    proxies=proxies, timeout=timeout
                )
            else:
                resp = req.post(
                    url, headers=built_headers,
                    proxies=proxies, timeout=timeout
                )

            latency_ms = (time.time() - start_time) * 1000

            self._record_hourly_request(site)

            return {
                'status_code': resp.status_code,
                'text': resp.text,
                'headers': dict(resp.headers),
                'url': resp.url,
                'latency_ms': round(latency_ms, 1),
                'method': 'requests_post',
            }
        except Exception as e:
            logger.error(f"Stealth POST failed for {url}: {e}")
            return None

    # ----------------------------------------------------------
    # CONVENIENCE METHODS
    # ----------------------------------------------------------

    def get_json(self, url: str, site: str = "",
                 **kwargs) -> Optional[Dict]:
        """GET request expecting JSON response."""
        result = self.get(url, site=site, **kwargs)
        if result and result.get('text'):
            try:
                return json.loads(result['text'])
            except json.JSONDecodeError:
                return None
        return None

    def get_with_retry(self, url: str, site: str = "",
                       max_retries: int = 3,
                       **kwargs) -> Optional[Dict]:
        """GET with automatic retry on failure."""
        for attempt in range(max_retries):
            result = self.get(url, site=site, **kwargs)
            if result and result.get('status_code', 0) == 200:
                return result
            if attempt < max_retries - 1:
                delay = random.uniform(5, 15) * (attempt + 1)
                time.sleep(delay)
        return None

    # ----------------------------------------------------------
    # HEALTH & STATS
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get comprehensive stealth engine health report."""
        proxy_stats = self.proxy_pool.get_stats()
        session_count = len(self._sessions)
        blocked_domains = [
            d for d, s in self._sessions.items() if s.is_blocked
        ]
        hourly_stats = {}
        current_hour = datetime.now().hour
        for site, hours in self._hourly_counts.items():
            hourly_stats[site] = hours.get(current_hour, 0)

        return {
            'proxy_pool': proxy_stats,
            'active_sessions': session_count,
            'blocked_domains': blocked_domains,
            'hourly_requests': hourly_stats,
            'tor_available': self.tor_client.is_available(),
            'cf_relay_configured': bool(self.config.cloudflare_relay.worker_url),
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_stealth_instance: Optional[StealthHTTPClient] = None
_stealth_lock = threading.Lock()


def get_stealth_client() -> StealthHTTPClient:
    """Get the singleton StealthHTTPClient instance."""
    global _stealth_instance
    if _stealth_instance is None:
        with _stealth_lock:
            if _stealth_instance is None:
                _stealth_instance = StealthHTTPClient()
    return _stealth_instance


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("OPERATION FIRST MOVER v5 — Stealth Engine Test")
    print("=" * 60)

    client = get_stealth_client()
    health = client.get_health()

    print(f"\nProxy Pool:")
    for k, v in health['proxy_pool'].items():
        print(f"  {k}: {v}")

    print(f"\nActive Sessions: {health['active_sessions']}")
    print(f"Blocked Domains: {health['blocked_domains']}")
    print(f"Tor Available: {health['tor_available']}")
    print(f"CF Relay: {health['cf_relay_configured']}")

    # Test header generation
    builder = StealthRequestBuilder()
    headers = builder.build_headers(site='internshala', ua_type='mobile')
    print(f"\nSample Internshala headers:")
    for k, v in headers.items():
        print(f"  {k}: {v[:80]}...")

    # Test timing
    timing = TimingController()
    delays = [timing.get_delay(site='internshala') for _ in range(5)]
    print(f"\nInternshala delays: {[round(d, 1) for d in delays]}")
    print(f"Average delay: {sum(delays)/len(delays):.1f}s")

    print("\n✅ Stealth engine test passed!")
    print("=" * 60)
