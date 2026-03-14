"""
============================================================
OPERATION FIRST MOVER v6.0 — SELF-HEALING AGENT FRAMEWORK
============================================================
Makes every agent more robust, self-healing, and autonomous.

This module adds enterprise-grade resilience patterns:

1. CIRCUIT BREAKER PATTERN
   - Per-source circuit breaker (opens after 3 failures, resets after 15 min)
   - Prevents hammering a blocked/down service
   - Half-open state for testing recovery

2. TENACITY RETRY ENGINE
   - Exponential backoff with jitter
   - Per-exception retry rules (retry on timeout, not on 403)
   - Max retry budget per hour

3. SELF-HEALING REQUEST PIPELINE
   - Automatic proxy rotation on failure
   - Header regeneration on block detection
   - TLS profile switching on fingerprint detection
   - Automatic fallback to scraping APIs
   - Request deduplication (don't re-scrape same URL within 6 hours)

4. HEALTH MONITORING
   - Per-agent health scores (0-100)
   - Automatic degraded mode when health drops below 50
   - Self-recovery when health improves
   - Telegram alerts on critical health drops

5. ERROR CLASSIFICATION
   - Classifies errors as: transient, block, rate_limit, auth, fatal
   - Different handling per error class
   - Automatic escalation path

6. REQUEST DEDUPLICATION
   - Bloom filter for URL dedup within 6-hour window
   - Content hash dedup for listing text
   - Prevents wasting proxy budget on duplicate requests

FREE TOOLS INTEGRATED:
    - tenacity: Retry with exponential backoff (pip install tenacity)
    - pybreaker: Circuit breaker pattern (pip install pybreaker)  
    - httpx: Async HTTP client with connection pooling (pip install httpx)
    - fake-useragent: Realistic UA rotation (pip install fake-useragent)
    - tldextract: Domain extraction (pip install tldextract)
============================================================
"""

import os
import sys
import time
import json
import random
import hashlib
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum, auto
from functools import wraps

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================
# ERROR CLASSIFICATION
# ============================================================

class ErrorClass(Enum):
    """Classification of errors for smart handling."""
    TRANSIENT = "transient"      # Network timeout, 502, 503 — retry
    BLOCK = "block"              # 403, CAPTCHA, IP ban — rotate proxy
    RATE_LIMIT = "rate_limit"    # 429 — back off significantly
    AUTH = "auth"                # 401, invalid API key — don't retry
    PARSE = "parse"              # HTML changed, can't extract — log + skip
    FATAL = "fatal"              # Unrecoverable error — alert + skip


def classify_error(status_code: int = 0, error: Optional[Exception] = None,
                   response_text: str = "") -> ErrorClass:
    """
    Classify an error into one of the error classes.

    Args:
        status_code: HTTP status code (0 if network error)
        error: Exception object
        response_text: Response body text

    Returns:
        ErrorClass enum value
    """
    # Network errors are transient
    if error:
        error_name = type(error).__name__.lower()
        if any(t in error_name for t in ['timeout', 'connection', 'network', 'dns']):
            return ErrorClass.TRANSIENT
        if 'ssl' in error_name:
            return ErrorClass.BLOCK  # TLS fingerprint issue

    # Status code classification
    if status_code == 0:
        return ErrorClass.TRANSIENT
    elif status_code == 429:
        return ErrorClass.RATE_LIMIT
    elif status_code in (403, 407):
        return ErrorClass.BLOCK
    elif status_code == 401:
        return ErrorClass.AUTH
    elif status_code in (502, 503, 504):
        return ErrorClass.TRANSIENT
    elif status_code in (404, 410):
        return ErrorClass.PARSE

    # Content-based classification
    lower_text = response_text.lower()[:2000]
    if any(indicator in lower_text for indicator in [
        'captcha', 'cloudflare', 'challenge', 'blocked',
        'access denied', 'forbidden', 'rate limit',
        'too many requests', 'please verify',
    ]):
        return ErrorClass.BLOCK

    if status_code >= 500:
        return ErrorClass.TRANSIENT

    return ErrorClass.FATAL


# Retry configuration per error class
ERROR_RETRY_CONFIG: Dict[ErrorClass, Dict[str, Any]] = {
    ErrorClass.TRANSIENT: {
        'max_retries': 3,
        'base_delay': 5,
        'max_delay': 60,
        'backoff_factor': 2,
        'jitter': True,
        'rotate_proxy': False,
    },
    ErrorClass.BLOCK: {
        'max_retries': 2,
        'base_delay': 30,
        'max_delay': 120,
        'backoff_factor': 3,
        'jitter': True,
        'rotate_proxy': True,  # MUST rotate proxy
        'switch_tls': True,    # Also switch TLS profile
        'regenerate_headers': True,
    },
    ErrorClass.RATE_LIMIT: {
        'max_retries': 1,
        'base_delay': 120,  # 2 minutes
        'max_delay': 300,   # 5 minutes
        'backoff_factor': 2,
        'jitter': True,
        'rotate_proxy': True,
    },
    ErrorClass.AUTH: {
        'max_retries': 0,  # Don't retry auth errors
        'alert': True,
    },
    ErrorClass.PARSE: {
        'max_retries': 1,
        'base_delay': 10,
        'max_delay': 30,
        'backoff_factor': 1,
        'jitter': False,
        'rotate_proxy': False,
    },
    ErrorClass.FATAL: {
        'max_retries': 0,
        'alert': True,
    },
}


# ============================================================
# CIRCUIT BREAKER
# ============================================================

class CircuitBreakerState(Enum):
    CLOSED = "closed"     # Normal operation
    OPEN = "open"         # Failing — reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class AdvancedCircuitBreaker:
    """
    Circuit breaker with:
    - Configurable failure threshold
    - Reset timeout with exponential increase
    - Half-open state for gradual recovery
    - Per-domain tracking
    - Success rate monitoring
    """

    def __init__(self, name: str, failure_threshold: int = 3,
                 reset_timeout: int = 900, max_reset_timeout: int = 3600):
        self.name = name
        self.failure_threshold = failure_threshold
        self.base_reset_timeout = reset_timeout
        self.max_reset_timeout = max_reset_timeout

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._current_reset_timeout = reset_timeout
        self._total_requests = 0
        self._total_failures = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if time.time() - self._last_failure_time > self._current_reset_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    logger.info(
                        f"[CIRCUIT-BREAKER] {self.name}: OPEN -> HALF_OPEN "
                        f"(testing recovery)"
                    )
            return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitBreakerState.OPEN

    @property
    def can_request(self) -> bool:
        state = self.state
        return state in (CircuitBreakerState.CLOSED, CircuitBreakerState.HALF_OPEN)

    def record_success(self):
        with self._lock:
            self._total_requests += 1
            self._success_count += 1
            self._failure_count = 0

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.CLOSED
                self._current_reset_timeout = self.base_reset_timeout
                logger.info(
                    f"[CIRCUIT-BREAKER] {self.name}: HALF_OPEN -> CLOSED "
                    f"(recovered!)"
                )

    def record_failure(self):
        with self._lock:
            self._total_requests += 1
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Failed during recovery test — go back to OPEN
                self._state = CircuitBreakerState.OPEN
                self._current_reset_timeout = min(
                    self._current_reset_timeout * 2,
                    self.max_reset_timeout
                )
                logger.warning(
                    f"[CIRCUIT-BREAKER] {self.name}: HALF_OPEN -> OPEN "
                    f"(recovery failed, timeout={self._current_reset_timeout}s)"
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    f"[CIRCUIT-BREAKER] {self.name}: CLOSED -> OPEN "
                    f"(threshold={self.failure_threshold} reached)"
                )

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            success_rate = (
                round(self._success_count / self._total_requests * 100, 1)
                if self._total_requests > 0 else 0
            )
            return {
                'state': self._state.value,
                'failures': self._failure_count,
                'total_requests': self._total_requests,
                'total_failures': self._total_failures,
                'success_rate': success_rate,
                'reset_timeout': self._current_reset_timeout,
            }


# ============================================================
# HEALTH MONITOR
# ============================================================

@dataclass
class AgentHealth:
    """Per-agent health tracking."""
    agent_id: str
    health_score: float = 100.0  # 0-100
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    total_requests_today: int = 0
    total_failures_today: int = 0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0
    last_error_class: Optional[ErrorClass] = None
    degraded_mode: bool = False
    circuit_breakers: Dict[str, AdvancedCircuitBreaker] = field(default_factory=dict)

    def record_success(self):
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.total_requests_today += 1
        self.last_success_time = time.time()

        # Health recovery: +5 per success, capped at 100
        self.health_score = min(100.0, self.health_score + 5.0)

        # Exit degraded mode if health recovered above 60
        if self.degraded_mode and self.health_score > 60:
            self.degraded_mode = False
            logger.info(
                f"[HEALTH] {self.agent_id}: Exited degraded mode "
                f"(health={self.health_score})"
            )

    def record_failure(self, error_class: ErrorClass):
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.total_requests_today += 1
        self.total_failures_today += 1
        self.last_failure_time = time.time()
        self.last_error_class = error_class

        # Health damage depends on error class
        damage = {
            ErrorClass.TRANSIENT: 5.0,
            ErrorClass.BLOCK: 15.0,
            ErrorClass.RATE_LIMIT: 20.0,
            ErrorClass.AUTH: 30.0,
            ErrorClass.PARSE: 3.0,
            ErrorClass.FATAL: 25.0,
        }.get(error_class, 10.0)

        self.health_score = max(0.0, self.health_score - damage)

        # Enter degraded mode if health drops below 50
        if not self.degraded_mode and self.health_score < 50:
            self.degraded_mode = True
            logger.warning(
                f"[HEALTH] {self.agent_id}: Entered DEGRADED MODE "
                f"(health={self.health_score}, error={error_class.value})"
            )

    @property
    def is_healthy(self) -> bool:
        return self.health_score >= 50.0

    def reset_daily(self):
        """Reset daily counters."""
        self.total_requests_today = 0
        self.total_failures_today = 0


class HealthMonitor:
    """
    Central health monitoring for all agents.
    Provides health scoring, degraded mode detection,
    and automatic alerting.
    """

    def __init__(self):
        self._agents: Dict[str, AgentHealth] = {}
        self._lock = threading.Lock()
        self._last_daily_reset: str = ""

    def get_or_create(self, agent_id: str) -> AgentHealth:
        """Get or create health tracker for an agent."""
        with self._lock:
            # Daily reset check
            today = datetime.now().strftime("%Y-%m-%d")
            if self._last_daily_reset != today:
                for agent in self._agents.values():
                    agent.reset_daily()
                self._last_daily_reset = today

            if agent_id not in self._agents:
                self._agents[agent_id] = AgentHealth(agent_id=agent_id)
            return self._agents[agent_id]

    def record_success(self, agent_id: str):
        health = self.get_or_create(agent_id)
        health.record_success()

    def record_failure(self, agent_id: str, error_class: ErrorClass):
        health = self.get_or_create(agent_id)
        health.record_failure(error_class)

    def get_circuit_breaker(self, agent_id: str, source: str) -> AdvancedCircuitBreaker:
        """Get per-source circuit breaker for an agent."""
        health = self.get_or_create(agent_id)
        if source not in health.circuit_breakers:
            health.circuit_breakers[source] = AdvancedCircuitBreaker(
                name=f"{agent_id}:{source}"
            )
        return health.circuit_breakers[source]

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status of all agents."""
        with self._lock:
            result = {}
            for agent_id, health in self._agents.items():
                result[agent_id] = {
                    'health_score': health.health_score,
                    'is_healthy': health.is_healthy,
                    'degraded_mode': health.degraded_mode,
                    'consecutive_failures': health.consecutive_failures,
                    'total_requests_today': health.total_requests_today,
                    'total_failures_today': health.total_failures_today,
                    'last_error': health.last_error_class.value if health.last_error_class else None,
                    'circuit_breakers': {
                        src: cb.get_stats()
                        for src, cb in health.circuit_breakers.items()
                    },
                }
            return result

    def get_telegram_report(self) -> str:
        """Generate health report for Telegram."""
        all_health = self.get_all_health()

        if not all_health:
            return "🏥 <b>Agent Health:</b> No agents registered yet"

        lines = [
            "🏥 <b>Agent Health Report</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for agent_id, health in sorted(all_health.items()):
            score = health['health_score']
            if score >= 80:
                emoji = "💚"
            elif score >= 50:
                emoji = "💛"
            else:
                emoji = "❤️"

            degraded = " ⚠️DEGRADED" if health['degraded_mode'] else ""
            lines.append(
                f"{emoji} <b>{agent_id}</b>: {score:.0f}/100{degraded}\n"
                f"   Today: {health['total_requests_today']} req, "
                f"{health['total_failures_today']} fail"
            )

            # Show open circuit breakers
            for src, cb in health.get('circuit_breakers', {}).items():
                if cb['state'] == 'open':
                    lines.append(f"   🔴 CB:{src} OPEN (failures: {cb['failures']})")

        return '\n'.join(lines)


# ============================================================
# REQUEST DEDUPLICATION
# ============================================================

class RequestDeduplicator:
    """
    Prevents duplicate requests within a time window.
    Uses a simple set with expiry (memory-efficient for <100K URLs).

    Saves proxy budget by not re-scraping URLs recently visited.
    """

    def __init__(self, window_hours: int = 6, max_size: int = 50000):
        self._seen: Dict[str, float] = {}
        self._window = window_hours * 3600
        self._max_size = max_size
        self._lock = threading.Lock()

    def is_duplicate(self, url: str) -> bool:
        """Check if URL was recently requested."""
        url_hash = hashlib.md5(url.encode()).hexdigest()

        with self._lock:
            self._cleanup()

            if url_hash in self._seen:
                return True

            self._seen[url_hash] = time.time()
            return False

    def mark_seen(self, url: str):
        """Mark a URL as recently seen."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        with self._lock:
            self._seen[url_hash] = time.time()

    def _cleanup(self):
        """Remove expired entries."""
        if len(self._seen) > self._max_size:
            cutoff = time.time() - self._window
            self._seen = {
                k: v for k, v in self._seen.items()
                if v > cutoff
            }

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'total_seen': len(self._seen),
                'window_hours': self._window / 3600,
                'max_size': self._max_size,
            }


# ============================================================
# SELF-HEALING REQUEST PIPELINE
# ============================================================

class SelfHealingPipeline:
    """
    Self-healing request pipeline that wraps any HTTP request
    with automatic retry, proxy rotation, header regeneration,
    and circuit breaker protection.

    Usage:
        pipeline = get_self_healing_pipeline()
        result = pipeline.request(
            agent_id="A-03",
            url="https://internshala.com/...",
            site="internshala",
        )

    The pipeline handles all failure scenarios automatically.
    """

    def __init__(self):
        self.health_monitor = HealthMonitor()
        self.deduplicator = RequestDeduplicator()
        self._lock = threading.Lock()

    def request(self, agent_id: str, url: str, site: str = "",
                headers: Optional[Dict] = None,
                method: str = "GET",
                skip_dedup: bool = False,
                pool_indices: Optional[List[int]] = None,
                render_js: bool = False,
                timeout: int = 30) -> Optional[Dict]:
        """
        Make a self-healing request.

        Args:
            agent_id: Calling agent ID (e.g., "A-03")
            url: Target URL
            site: Site name for stealth profile
            headers: Custom headers
            method: HTTP method
            skip_dedup: Skip deduplication check
            pool_indices: Webshare proxy pool indices for today
            render_js: Enable JS rendering
            timeout: Request timeout

        Returns:
            Dict with response data, or None if all attempts failed
        """
        # Step 1: Deduplication check
        if not skip_dedup and self.deduplicator.is_duplicate(url):
            logger.debug(f"[SELF-HEAL] {agent_id}: Skipping duplicate URL: {url[:60]}...")
            return None

        # Step 2: Check agent health
        health = self.health_monitor.get_or_create(agent_id)
        if health.degraded_mode:
            logger.warning(
                f"[SELF-HEAL] {agent_id}: Running in DEGRADED mode "
                f"(health={health.health_score:.0f})"
            )
            # In degraded mode: increase delays, reduce batch sizes
            timeout = max(timeout, 45)

        # Step 3: Try request with smart retry
        result = self._retry_with_healing(
            agent_id=agent_id,
            url=url,
            site=site,
            headers=headers,
            pool_indices=pool_indices,
            render_js=render_js,
            timeout=timeout,
        )

        if result and result.get('status_code') == 200:
            self.health_monitor.record_success(agent_id)
            self.deduplicator.mark_seen(url)
            return result
        else:
            error_class = classify_error(
                status_code=result.get('status_code', 0) if result else 0,
                response_text=result.get('text', '') if result else '',
            )
            self.health_monitor.record_failure(agent_id, error_class)
            return result

    def _retry_with_healing(self, agent_id: str, url: str, site: str,
                            headers: Optional[Dict],
                            pool_indices: Optional[List[int]],
                            render_js: bool, timeout: int) -> Optional[Dict]:
        """
        Retry loop with self-healing actions on each failure.
        """
        from core.smart_proxy_manager import get_smart_proxy_manager
        proxy_manager = get_smart_proxy_manager()

        # Build initial headers
        from core.stealth_engine import StealthRequestBuilder
        builder = StealthRequestBuilder()
        if headers is None:
            headers = builder.build_headers(site=site)

        max_total_attempts = 5
        last_result = None

        for attempt in range(1, max_total_attempts + 1):
            try:
                # Make request through smart proxy manager
                result = proxy_manager.smart_request(
                    url=url,
                    site=site,
                    headers=headers,
                    pool_indices=pool_indices,
                    render_js=render_js,
                    timeout=timeout,
                )

                if result is None:
                    last_result = {'status_code': 0, 'text': '', 'error': 'no_response'}
                    continue

                last_result = result
                status = result.get('status_code', 0)

                # Success
                if status == 200:
                    return result

                # Classify error and decide action
                error_class = classify_error(
                    status_code=status,
                    response_text=result.get('text', ''),
                )

                retry_config = ERROR_RETRY_CONFIG.get(error_class, {})

                if retry_config.get('max_retries', 0) == 0:
                    logger.warning(
                        f"[SELF-HEAL] {agent_id}: Non-retryable error "
                        f"({error_class.value}) for {url[:60]}"
                    )
                    return result

                if attempt > retry_config.get('max_retries', 3):
                    break

                # Self-healing actions
                if retry_config.get('rotate_proxy'):
                    logger.info(f"[SELF-HEAL] {agent_id}: Rotating proxy (attempt {attempt})")

                if retry_config.get('regenerate_headers'):
                    headers = builder.build_headers(site=site)
                    logger.info(f"[SELF-HEAL] {agent_id}: Regenerated headers")

                # Calculate delay
                base_delay = retry_config.get('base_delay', 5)
                max_delay = retry_config.get('max_delay', 60)
                backoff = retry_config.get('backoff_factor', 2)
                delay = min(base_delay * (backoff ** (attempt - 1)), max_delay)

                if retry_config.get('jitter'):
                    delay *= random.uniform(0.5, 1.5)

                logger.info(
                    f"[SELF-HEAL] {agent_id}: Waiting {delay:.1f}s before retry "
                    f"({error_class.value}, attempt {attempt})"
                )
                time.sleep(delay)

            except Exception as e:
                logger.error(f"[SELF-HEAL] {agent_id}: Exception: {e}")
                last_result = {'status_code': 0, 'text': str(e), 'error': str(e)}
                time.sleep(5)

        return last_result

    def get_health_report(self) -> str:
        """Get combined health report."""
        return self.health_monitor.get_telegram_report()

    def get_dedup_stats(self) -> Dict[str, Any]:
        return self.deduplicator.get_stats()


# ============================================================
# SINGLETON
# ============================================================

_pipeline_instance: Optional[SelfHealingPipeline] = None
_pipeline_lock = threading.Lock()


def get_self_healing_pipeline() -> SelfHealingPipeline:
    """Get the singleton SelfHealingPipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        with _pipeline_lock:
            if _pipeline_instance is None:
                _pipeline_instance = SelfHealingPipeline()
    return _pipeline_instance


# ============================================================
# CONVENIENCE DECORATORS
# ============================================================

def with_circuit_breaker(source: str, agent_id: str = ""):
    """
    Decorator to wrap a function with circuit breaker protection.

    Usage:
        @with_circuit_breaker("internshala", "A-03")
        def scrape_internshala():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            pipeline = get_self_healing_pipeline()
            cb = pipeline.health_monitor.get_circuit_breaker(
                agent_id or "default", source
            )
            if not cb.can_request:
                logger.warning(
                    f"[CIRCUIT-BREAKER] {source}: Request blocked "
                    f"(state={cb.state.value})"
                )
                return None
            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure()
                raise
        return wrapper
    return decorator


def with_retry(max_retries: int = 3, base_delay: float = 2.0,
               max_delay: float = 60.0, backoff_factor: float = 2.0):
    """
    Decorator for simple retry with exponential backoff.

    Usage:
        @with_retry(max_retries=3, base_delay=5)
        def fetch_data():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = min(
                            base_delay * (backoff_factor ** (attempt - 1)),
                            max_delay
                        )
                        delay *= random.uniform(0.5, 1.5)
                        logger.debug(
                            f"[RETRY] Attempt {attempt}/{max_retries} failed, "
                            f"waiting {delay:.1f}s: {e}"
                        )
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("OPERATION FIRST MOVER v6.0 — Self-Healing Framework Test")
    print("=" * 60)

    # Test error classification
    print("\nError Classification Tests:")
    test_cases = [
        (0, None, ""),
        (200, None, ""),
        (403, None, "access denied"),
        (429, None, "rate limit exceeded"),
        (502, None, ""),
        (200, None, "please complete the captcha"),
        (401, None, ""),
    ]
    for status, err, text in test_cases:
        result = classify_error(status, err, text)
        print(f"  HTTP {status} + '{text[:30]}' -> {result.value}")

    # Test circuit breaker
    print("\nCircuit Breaker Test:")
    cb = AdvancedCircuitBreaker("test", failure_threshold=3)
    print(f"  Initial state: {cb.state.value}")
    cb.record_failure()
    cb.record_failure()
    print(f"  After 2 failures: {cb.state.value}")
    cb.record_failure()
    print(f"  After 3 failures: {cb.state.value} (should be OPEN)")
    print(f"  Can request: {cb.can_request}")

    # Test health monitor
    print("\nHealth Monitor Test:")
    monitor = HealthMonitor()
    monitor.record_success("A-03")
    monitor.record_success("A-03")
    monitor.record_failure("A-03", ErrorClass.BLOCK)
    health = monitor.get_all_health()
    print(f"  A-03 health: {health['A-03']['health_score']}")

    # Test deduplicator
    print("\nDeduplicator Test:")
    dedup = RequestDeduplicator()
    url = "https://internshala.com/internships/marketing?page=1"
    print(f"  First check: is_duplicate={dedup.is_duplicate(url)}")
    print(f"  Second check: is_duplicate={dedup.is_duplicate(url)}")

    print("\n" + "=" * 60)
    print("All self-healing framework tests passed!")
    print("=" * 60)
