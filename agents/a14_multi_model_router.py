"""
============================================================
PRISM v0.1 — A-14: MULTI-MODEL ROUTER (AI TRAFFIC CONTROLLER)
============================================================
Agent A-14: The brain stem of PRISM. Every AI call in the
system goes through A-14. It knows which provider is healthy,
how much quota remains, which model gives best quality for
each task type, and how to fail over gracefully.

v0.1 adds 3 new providers to the existing Groq+Cerebras router:
    - OpenRouter (1M context, gemini-2.0-flash-exp:free)
    - Groq Compound Beta (agentic web_search + visit_url)
    - Mistral (pixtral-large-2411, universal fallback)

Schedule: Always-on middleware — every AI request passes through
Trigger: Every ai_router.route() call
AI Provider: N/A (this IS the provider layer)

Pipeline:
    1. Maintain real-time quota counters for all 5 providers in
       memory + DB (agent_heartbeats table)
    2. For each AI task request:
        a. Look up TASK_ROUTING_TABLE to find optimal provider
        b. Check provider health: is circuit breaker open?
           Is quota >90%? → skip to next in failover chain
        c. Execute request with retry (exponential backoff, max 3)
        d. On 429: mark provider as rate-limited, immediately
           route to next provider in PRISM_FAILOVER_CHAIN
        e. On success: update quota counter, log latency
    3. Nightly: reset daily counters, log efficiency report

TASK ROUTING TABLE (54 tasks across 5 providers):
    ┌─────────────────────────┬───────────────────────────────┐
    │ CEREBRAS (Primary Fast) │ ghost_classify, intent_classify│
    │ Cerebras 8B (24k RPD)   │ dark_classify, extract_basics │
    │                         │ dedup_score, listing_quality   │
    │                         │ sector_tag, anomaly_detect     │
    │                         │ tg_extract, schedule_optimize  │
    ├─────────────────────────┼───────────────────────────────┤
    │ GROQ 70B (Deep Tasks)   │ cover_letter, company_research│
    │ Llama-3.3-70B (14.4k)   │ outreach_draft, jd_analysis   │
    │                         │ report_compile, email_personal │
    │                         │ follow_up_draft, ats_keywords  │
    │                         │ cv_rewrite, ppo_explain        │
    ├─────────────────────────┼───────────────────────────────┤
    │ OPENROUTER (Long Ctx)   │ full_ats_simulation           │
    │ Gemini 2.0 Flash 1M     │ full_cv_tailoring             │
    │ 200 RPD free             │ long_jd_analysis              │
    ├─────────────────────────┼───────────────────────────────┤
    │ GROQ COMPOUND (Agentic) │ company_intel_live            │
    │ compound-beta (web)     │ funding_verify                │
    │                         │ leadership_changes            │
    │                         │ competitor_scan               │
    ├─────────────────────────┼───────────────────────────────┤
    │ MISTRAL (Fallback)      │ ALL tasks as final fallback   │
    │ pixtral-large-2411      │ 1B tokens/month free          │
    └─────────────────────────┴───────────────────────────────┘

FAILOVER CHAIN:
    Cerebras → Groq 70B → Mistral → queue_retry(60s)
    Groq 70B → Cerebras → Mistral → queue_retry(60s)
    OpenRouter → Groq 70B → Mistral → queue_retry(60s)
    Groq Compound → Groq 70B → Mistral → queue_retry(60s)
    Mistral → Groq 70B → Cerebras → queue_retry(60s)

CIRCUIT BREAKER (per provider):
    - 5 consecutive failures → OPEN (block for 120s)
    - After 120s → HALF_OPEN (allow 1 probe)
    - Probe success → CLOSED (resume normal)
    - Probe failure → OPEN (block for 240s)

QUOTA TRACKING:
    ┌──────────────┬──────────┬──────────┬───────────┐
    │ Provider     │ Daily RPD│ RPM Limit│ Monitor   │
    ├──────────────┼──────────┼──────────┼───────────┤
    │ Groq         │ 14,400   │ 30       │ Per-min   │
    │ Cerebras     │ 24,000   │ 60       │ Per-min   │
    │ OpenRouter   │ 200      │ 20       │ Per-req   │
    │ Groq Compound│ 14,400   │ 30       │ Per-min   │
    │ Mistral      │ ∞ (1B)   │ 2        │ Per-min   │
    └──────────────┴──────────┴──────────┴───────────┘

Integration Points:
    - core/ai_router.py → A-14 wraps and enhances the router
    - A-17 Adaptive Scheduler → reads quota health for scheduling
    - A-12 Telegram Reporter → nightly AI efficiency reports
    - All agents → every LLM call passes through A-14
============================================================
"""

import os
import sys
import json
import time
import asyncio
import threading
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Set, Union
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST

# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-14"
AGENT_NAME = "Multi-Model Router"

# ============================================================
# PROVIDER DEFINITIONS
# ============================================================

class ProviderID(Enum):
    """All 5 PRISM AI providers."""
    GROQ = "groq"
    CEREBRAS = "cerebras"
    OPENROUTER = "openrouter"
    GROQ_COMPOUND = "groq_compound"
    MISTRAL = "mistral"


class CircuitState(Enum):
    """Circuit breaker states per provider."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocked — too many consecutive failures
    HALF_OPEN = "half_open" # Testing recovery with a single probe request


class TaskPriority(Enum):
    """Task urgency levels for routing decisions."""
    CRITICAL = "critical"     # Auto-apply, cover letter — must succeed
    HIGH = "high"             # ATS simulation, company intel
    NORMAL = "normal"         # Classification, extraction
    LOW = "low"               # Logging, non-essential analysis
    BACKGROUND = "background" # Nightly batch tasks


# ============================================================
# PROVIDER QUOTA CONFIGURATION
# ============================================================

@dataclass
class ProviderQuota:
    """Real-time quota tracking per provider."""
    provider_id: ProviderID
    daily_limit: int           # Requests per day
    rpm_limit: int             # Requests per minute
    daily_used: int = 0
    minute_used: int = 0
    minute_window_start: float = 0.0
    day_window_start: str = ""  # ISO date string
    total_requests: int = 0
    total_failures: int = 0
    total_429s: int = 0
    avg_latency_ms: float = 0.0
    last_request_at: float = 0.0
    last_success_at: float = 0.0
    last_error_at: float = 0.0
    last_error_msg: str = ""

    def utilization_pct(self) -> float:
        """Current daily utilization percentage."""
        if self.daily_limit <= 0:
            return 0.0
        return (self.daily_used / self.daily_limit) * 100.0

    def is_quota_safe(self, threshold_pct: float = 90.0) -> bool:
        """True if provider still has quota headroom."""
        return self.utilization_pct() < threshold_pct

    def can_send_rpm(self) -> bool:
        """True if RPM limit not reached this minute."""
        now = time.time()
        if now - self.minute_window_start >= 60.0:
            self.minute_used = 0
            self.minute_window_start = now
        return self.minute_used < self.rpm_limit

    def record_request(self, latency_ms: float, success: bool, is_429: bool = False):
        """Record a request outcome for quota tracking."""
        now = time.time()
        today = datetime.now(timezone.utc).date().isoformat()

        # Reset daily counter on new day
        if self.day_window_start != today:
            self.daily_used = 0
            self.day_window_start = today

        # Reset minute counter
        if now - self.minute_window_start >= 60.0:
            self.minute_used = 0
            self.minute_window_start = now

        self.daily_used += 1
        self.minute_used += 1
        self.total_requests += 1
        self.last_request_at = now

        if success:
            self.last_success_at = now
            # Rolling average latency
            if self.avg_latency_ms == 0:
                self.avg_latency_ms = latency_ms
            else:
                self.avg_latency_ms = (self.avg_latency_ms * 0.9) + (latency_ms * 0.1)
        else:
            self.total_failures += 1
            self.last_error_at = now
            if is_429:
                self.total_429s += 1


@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker for fault isolation."""
    provider_id: ProviderID
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    failure_threshold: int = 5
    open_timeout_s: float = 120.0  # 2 minutes
    half_open_timeout_s: float = 240.0  # 4 minutes on repeated failure
    opened_at: float = 0.0
    last_probe_at: float = 0.0
    total_trips: int = 0

    def record_success(self):
        """Record successful request — reset or close circuit."""
        self.consecutive_failures = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info(f"[A-14] Circuit CLOSED for {self.provider_id.value} — probe succeeded")

    def record_failure(self):
        """Record failed request — may trip circuit open."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                self.state = CircuitState.OPEN
                self.opened_at = time.time()
                self.total_trips += 1
                logger.warning(
                    f"[A-14] Circuit OPENED for {self.provider_id.value} "
                    f"after {self.consecutive_failures} consecutive failures "
                    f"(trip #{self.total_trips})"
                )
            elif self.state == CircuitState.HALF_OPEN:
                # Probe failed — extend open period
                self.state = CircuitState.OPEN
                self.opened_at = time.time()
                self.open_timeout_s = self.half_open_timeout_s
                logger.warning(
                    f"[A-14] Circuit RE-OPENED for {self.provider_id.value} "
                    f"(half-open probe failed, timeout={self.half_open_timeout_s}s)"
                )

    def is_available(self) -> bool:
        """Check if provider is available for requests."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.opened_at
            if elapsed >= self.open_timeout_s:
                self.state = CircuitState.HALF_OPEN
                logger.info(
                    f"[A-14] Circuit HALF_OPEN for {self.provider_id.value} "
                    f"— allowing probe request"
                )
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True
        return False


# ============================================================
# PRISM TASK ROUTING TABLE
# ============================================================

# Maps task_type → (primary_provider, [fallback_chain])
PRISM_TASK_TABLE: Dict[str, Tuple[ProviderID, List[ProviderID]]] = {
    # --- CEREBRAS PRIMARY (Fast classification/extraction) ---
    "ghost_classify":       (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "intent_classify":      (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "dark_classify":        (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "extract_basics":       (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "dedup_score":          (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "listing_quality_score":(ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "sector_tag":           (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "anomaly_detect":       (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "tg_extract":           (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "schedule_optimize":    (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "internshala_parse":    (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "naukri_parse":         (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "iimjobs_parse":        (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "ats_extract":          (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "dark_extract":         (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "followup_classify":    (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "email_classify":       (ProviderID.CEREBRAS, [ProviderID.GROQ, ProviderID.MISTRAL]),

    # --- GROQ 70B PRIMARY (Deep generation/analysis) ---
    "cover_letter":         (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "company_research":     (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "outreach_draft":       (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "jd_analysis":          (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "report_compile":       (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "email_personalize":    (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "follow_up_draft":      (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "ats_keywords":         (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "cv_rewrite":           (ProviderID.GROQ, [ProviderID.OPENROUTER, ProviderID.MISTRAL]),
    "ppo_explain":          (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "alumni_research":      (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "morning_brief":        (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "evening_summary":      (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),
    "assessment_answer":    (ProviderID.GROQ, [ProviderID.OPENROUTER, ProviderID.MISTRAL]),
    "blue_ocean_analysis":  (ProviderID.GROQ, [ProviderID.CEREBRAS, ProviderID.MISTRAL]),

    # --- OPENROUTER PRIMARY (Long context 1M tokens) ---
    "full_ats_simulation":  (ProviderID.OPENROUTER, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "full_cv_tailoring":    (ProviderID.OPENROUTER, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "long_jd_analysis":     (ProviderID.OPENROUTER, [ProviderID.GROQ, ProviderID.MISTRAL]),

    # --- GROQ COMPOUND PRIMARY (Agentic web search) ---
    "company_intel_live":   (ProviderID.GROQ_COMPOUND, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "funding_verify":       (ProviderID.GROQ_COMPOUND, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "leadership_changes":   (ProviderID.GROQ_COMPOUND, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "competitor_scan":      (ProviderID.GROQ_COMPOUND, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "market_trend":         (ProviderID.GROQ_COMPOUND, [ProviderID.GROQ, ProviderID.MISTRAL]),
    "news_verify":          (ProviderID.GROQ_COMPOUND, [ProviderID.GROQ, ProviderID.MISTRAL]),

    # --- MISTRAL PRIMARY (edge cases) ---
    "general_fallback":     (ProviderID.MISTRAL, [ProviderID.GROQ, ProviderID.CEREBRAS]),
}


# ============================================================
# QUOTA DEFAULTS (PRISM v0.1 free tier limits)
# ============================================================

PROVIDER_QUOTA_DEFAULTS: Dict[ProviderID, Dict[str, int]] = {
    ProviderID.GROQ:          {"daily_limit": 14400, "rpm_limit": 30},
    ProviderID.CEREBRAS:      {"daily_limit": 24000, "rpm_limit": 60},
    ProviderID.OPENROUTER:    {"daily_limit": 200,   "rpm_limit": 20},
    ProviderID.GROQ_COMPOUND: {"daily_limit": 14400, "rpm_limit": 30},
    ProviderID.MISTRAL:       {"daily_limit": 999999, "rpm_limit": 2},
}


# ============================================================
# A-14 MULTI-MODEL ROUTER — MAIN CLASS
# ============================================================

class MultiModelRouter:
    """
    A-14: The AI Traffic Controller.

    Every LLM request in PRISM passes through this router.
    It maintains real-time quota counters, circuit breakers,
    and provider health metrics for all 5 providers.

    Usage:
        router = MultiModelRouter()
        result = await router.route_task("cover_letter", prompt, ...)
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Initialize quota trackers
        self.quotas: Dict[ProviderID, ProviderQuota] = {}
        for pid, defaults in PROVIDER_QUOTA_DEFAULTS.items():
            self.quotas[pid] = ProviderQuota(
                provider_id=pid,
                daily_limit=defaults["daily_limit"],
                rpm_limit=defaults["rpm_limit"],
                day_window_start=datetime.now(timezone.utc).date().isoformat(),
                minute_window_start=time.time(),
            )

        # Initialize circuit breakers
        self.circuits: Dict[ProviderID, CircuitBreaker] = {}
        for pid in ProviderID:
            threshold = 3 if pid == ProviderID.OPENROUTER else 5
            self.circuits[pid] = CircuitBreaker(
                provider_id=pid,
                failure_threshold=threshold,
            )

        # Request history for analytics
        self._request_log: List[Dict[str, Any]] = []
        self._max_log_size = 5000

        # Provider health scores (0-100, updated in real-time)
        self._health_scores: Dict[ProviderID, float] = {
            pid: 100.0 for pid in ProviderID
        }

        # Retry queue for failed tasks
        self._retry_queue: List[Dict[str, Any]] = []

        logger.info(f"[{AGENT_ID}] Multi-Model Router initialized — 5 providers, "
                     f"{len(PRISM_TASK_TABLE)} tasks in routing table")

    # ============================================================
    # CORE ROUTING LOGIC
    # ============================================================

    def get_provider_for_task(self, task_type: str,
                              priority: TaskPriority = TaskPriority.NORMAL
                              ) -> Optional[ProviderID]:
        """
        Determine the best available provider for a task.

        Steps:
            1. Look up PRISM_TASK_TABLE for primary + fallback chain
            2. Check circuit breaker (is provider healthy?)
            3. Check quota (has headroom?)
            4. Check RPM (not throttled this minute?)
            5. Return first available provider or None

        Args:
            task_type: The PRISM task identifier (e.g. 'cover_letter')
            priority: Task urgency level

        Returns:
            ProviderID of the best available provider, or None if all exhausted
        """
        if task_type not in PRISM_TASK_TABLE:
            logger.warning(f"[{AGENT_ID}] Unknown task '{task_type}' — using general_fallback")
            task_type = "general_fallback"

        primary, fallbacks = PRISM_TASK_TABLE[task_type]

        # Build ordered candidate list: primary first, then fallbacks
        candidates = [primary] + fallbacks

        for provider in candidates:
            if not self._is_provider_available(provider, priority):
                continue
            return provider

        # All providers exhausted
        logger.error(
            f"[{AGENT_ID}] ALL providers exhausted for task '{task_type}' "
            f"(priority={priority.value}). Adding to retry queue."
        )
        self._add_to_retry_queue(task_type, priority)
        return None

    def _is_provider_available(self, provider: ProviderID,
                                priority: TaskPriority) -> bool:
        """Check if a provider is healthy, has quota, and not rate-limited."""
        circuit = self.circuits.get(provider)
        quota = self.quotas.get(provider)

        if not circuit or not quota:
            return False

        # Circuit breaker check
        if not circuit.is_available():
            return False

        # Quota check (relaxed threshold for CRITICAL tasks)
        threshold = 98.0 if priority == TaskPriority.CRITICAL else 90.0
        if not quota.is_quota_safe(threshold):
            logger.debug(
                f"[{AGENT_ID}] {provider.value} quota at "
                f"{quota.utilization_pct():.1f}% — skipping"
            )
            return False

        # RPM check
        if not quota.can_send_rpm():
            logger.debug(
                f"[{AGENT_ID}] {provider.value} RPM limit reached "
                f"({quota.minute_used}/{quota.rpm_limit}) — skipping"
            )
            return False

        return True

    # ============================================================
    # REQUEST EXECUTION & TRACKING
    # ============================================================

    async def route_task(self, task_type: str, prompt: str,
                         system_prompt: str = "",
                         priority: TaskPriority = TaskPriority.NORMAL,
                         max_tokens: int = 2000,
                         temperature: float = 0.3,
                         json_mode: bool = False,
                         context: Optional[Dict[str, Any]] = None
                         ) -> Optional[Dict[str, Any]]:
        """
        Route an AI task to the optimal provider with full failover.

        This is the MAIN entry point for all AI requests in PRISM.

        Args:
            task_type: PRISM task identifier
            prompt: User/task prompt
            system_prompt: System instruction
            priority: Task urgency
            max_tokens: Response length limit
            temperature: Creativity parameter
            json_mode: Request JSON output
            context: Additional context (listing_id, agent_id, etc.)

        Returns:
            Dict with 'text', 'provider', 'latency_ms', 'tokens_used'
            or None if all providers failed
        """
        context = context or {}
        start_time = time.time()
        attempts = []

        # Get ordered provider list
        primary_provider = self.get_provider_for_task(task_type, priority)

        if primary_provider is None:
            return None

        # Build attempt chain
        if task_type in PRISM_TASK_TABLE:
            primary, fallbacks = PRISM_TASK_TABLE[task_type]
            provider_chain = [primary] + fallbacks
        else:
            provider_chain = [primary_provider, ProviderID.MISTRAL]

        # Try each provider in chain
        for provider in provider_chain:
            if not self._is_provider_available(provider, priority):
                attempts.append({"provider": provider.value, "status": "skipped"})
                continue

            try:
                result = await self._execute_on_provider(
                    provider=provider,
                    task_type=task_type,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=json_mode,
                )

                latency_ms = (time.time() - start_time) * 1000

                # Record success
                with self._lock:
                    self.quotas[provider].record_request(latency_ms, success=True)
                    self.circuits[provider].record_success()
                    self._update_health_score(provider)

                # Log request
                self._log_request(
                    task_type=task_type,
                    provider=provider,
                    success=True,
                    latency_ms=latency_ms,
                    attempts=attempts,
                    context=context,
                )

                return {
                    "text": result.get("text", ""),
                    "provider": provider.value,
                    "model": result.get("model", ""),
                    "latency_ms": round(latency_ms, 1),
                    "tokens_used": result.get("tokens_used", 0),
                    "task_type": task_type,
                    "attempts": len(attempts) + 1,
                }

            except RateLimitError as e:
                latency_ms = (time.time() - start_time) * 1000
                with self._lock:
                    self.quotas[provider].record_request(latency_ms, success=False, is_429=True)
                    self.circuits[provider].record_failure()
                    self._update_health_score(provider)

                attempts.append({
                    "provider": provider.value,
                    "status": "rate_limited",
                    "error": str(e),
                })
                logger.warning(
                    f"[{AGENT_ID}] 429 from {provider.value} on '{task_type}' — "
                    f"failover to next provider"
                )
                continue

            except ProviderError as e:
                latency_ms = (time.time() - start_time) * 1000
                with self._lock:
                    self.quotas[provider].record_request(latency_ms, success=False)
                    self.circuits[provider].record_failure()
                    self._update_health_score(provider)

                attempts.append({
                    "provider": provider.value,
                    "status": "error",
                    "error": str(e),
                })
                logger.error(
                    f"[{AGENT_ID}] Error from {provider.value} on '{task_type}': {e}"
                )
                continue

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                with self._lock:
                    self.quotas[provider].record_request(latency_ms, success=False)
                    self.circuits[provider].record_failure()

                attempts.append({
                    "provider": provider.value,
                    "status": "exception",
                    "error": str(e),
                })
                logger.exception(
                    f"[{AGENT_ID}] Unexpected error from {provider.value}: {e}"
                )
                continue

        # All providers failed
        logger.error(
            f"[{AGENT_ID}] ALL PROVIDERS FAILED for task '{task_type}' "
            f"after {len(attempts)} attempts: {attempts}"
        )
        return None

    async def _execute_on_provider(self, provider: ProviderID,
                                     task_type: str, prompt: str,
                                     system_prompt: str,
                                     max_tokens: int,
                                     temperature: float,
                                     json_mode: bool
                                     ) -> Dict[str, Any]:
        """
        Execute an AI request on a specific provider.

        Delegates to core/ai_router.py's provider-specific methods
        but wraps them with A-14's quota and circuit breaker logic.
        """
        try:
            from core.ai_router import get_router
            ai_router = get_router()
        except Exception as e:
            raise ProviderError(f"Failed to import ai_router: {e}")

        # Map provider to ai_router method
        provider_map = {
            ProviderID.GROQ: "groq",
            ProviderID.CEREBRAS: "cerebras",
            ProviderID.OPENROUTER: "openrouter",
            ProviderID.GROQ_COMPOUND: "groq_compound",
            ProviderID.MISTRAL: "mistral",
        }

        target_provider = provider_map.get(provider, "groq")

        try:
            # Use the ai_router's route method with provider override
            result = await self._call_ai_router(
                ai_router=ai_router,
                task_type=task_type,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                force_provider=target_provider,
            )
            return result

        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str or "limit" in error_str:
                raise RateLimitError(f"{provider.value}: {e}")
            raise ProviderError(f"{provider.value}: {e}")

    async def _call_ai_router(self, ai_router, task_type: str,
                                prompt: str, system_prompt: str,
                                max_tokens: int, temperature: float,
                                json_mode: bool,
                                force_provider: str) -> Dict[str, Any]:
        """
        Call the core ai_router with provider preference.

        The ai_router handles the actual API calls to Groq/Cerebras/etc.
        A-14 just wraps it with routing intelligence.
        """
        try:
            # Try to use the router's route method
            if hasattr(ai_router, 'route'):
                result = await ai_router.route(
                    task_type=task_type,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=json_mode,
                )
            elif hasattr(ai_router, 'generate'):
                result = await ai_router.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    task=task_type,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                raise ProviderError("ai_router has no route/generate method")

            # Normalize result
            if isinstance(result, str):
                return {"text": result, "model": force_provider, "tokens_used": 0}
            elif isinstance(result, dict):
                return {
                    "text": result.get("text", result.get("content", result.get("response", ""))),
                    "model": result.get("model", force_provider),
                    "tokens_used": result.get("tokens_used", result.get("usage", {}).get("total_tokens", 0)),
                }
            else:
                return {"text": str(result), "model": force_provider, "tokens_used": 0}

        except Exception as e:
            raise

    # ============================================================
    # HEALTH MONITORING
    # ============================================================

    def _update_health_score(self, provider: ProviderID):
        """Compute real-time health score (0-100) for a provider."""
        quota = self.quotas[provider]
        circuit = self.circuits[provider]

        score = 100.0

        # Deduct for circuit breaker state
        if circuit.state == CircuitState.OPEN:
            score -= 80
        elif circuit.state == CircuitState.HALF_OPEN:
            score -= 40

        # Deduct for high quota utilization
        util = quota.utilization_pct()
        if util > 90:
            score -= 50
        elif util > 75:
            score -= 25
        elif util > 50:
            score -= 10

        # Deduct for high failure rate
        if quota.total_requests > 10:
            failure_rate = quota.total_failures / quota.total_requests
            score -= failure_rate * 40

        # Deduct for high latency
        if quota.avg_latency_ms > 10000:
            score -= 20
        elif quota.avg_latency_ms > 5000:
            score -= 10

        # Deduct for recent errors
        if quota.last_error_at > 0:
            time_since_error = time.time() - quota.last_error_at
            if time_since_error < 60:
                score -= 15
            elif time_since_error < 300:
                score -= 5

        self._health_scores[provider] = max(0, min(100, score))

    def get_health_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive health report for all providers.

        Used by A-17 (Adaptive Scheduler) and A-12 (Telegram Reporter).
        """
        report = {
            "timestamp": datetime.now(IST).isoformat(),
            "agent": AGENT_ID,
            "providers": {},
            "summary": {},
        }

        total_requests = 0
        total_failures = 0

        for pid in ProviderID:
            quota = self.quotas[pid]
            circuit = self.circuits[pid]

            total_requests += quota.total_requests
            total_failures += quota.total_failures

            report["providers"][pid.value] = {
                "health_score": round(self._health_scores.get(pid, 100), 1),
                "circuit_state": circuit.state.value,
                "circuit_trips": circuit.total_trips,
                "daily_used": quota.daily_used,
                "daily_limit": quota.daily_limit,
                "utilization_pct": round(quota.utilization_pct(), 1),
                "rpm_current": quota.minute_used,
                "rpm_limit": quota.rpm_limit,
                "total_requests": quota.total_requests,
                "total_failures": quota.total_failures,
                "total_429s": quota.total_429s,
                "avg_latency_ms": round(quota.avg_latency_ms, 1),
                "failure_rate_pct": round(
                    (quota.total_failures / max(1, quota.total_requests)) * 100, 1
                ),
            }

        # Summary
        report["summary"] = {
            "total_requests": total_requests,
            "total_failures": total_failures,
            "overall_success_rate": round(
                ((total_requests - total_failures) / max(1, total_requests)) * 100, 1
            ),
            "providers_healthy": sum(
                1 for pid in ProviderID
                if self._health_scores.get(pid, 0) >= 50
            ),
            "providers_degraded": sum(
                1 for pid in ProviderID
                if 20 <= self._health_scores.get(pid, 0) < 50
            ),
            "providers_down": sum(
                1 for pid in ProviderID
                if self._health_scores.get(pid, 0) < 20
            ),
        }

        return report

    def get_quota_status(self) -> Dict[str, Dict[str, Any]]:
        """Quick quota snapshot for all providers."""
        status = {}
        for pid in ProviderID:
            q = self.quotas[pid]
            status[pid.value] = {
                "used": q.daily_used,
                "limit": q.daily_limit,
                "pct": round(q.utilization_pct(), 1),
                "remaining": max(0, q.daily_limit - q.daily_used),
                "healthy": self.circuits[pid].is_available(),
            }
        return status

    # ============================================================
    # RETRY QUEUE MANAGEMENT
    # ============================================================

    def _add_to_retry_queue(self, task_type: str, priority: TaskPriority):
        """Add a failed task to the retry queue."""
        self._retry_queue.append({
            "task_type": task_type,
            "priority": priority.value,
            "added_at": time.time(),
            "retry_after": time.time() + 60,  # Retry in 60 seconds
        })
        if len(self._retry_queue) > 500:
            self._retry_queue = self._retry_queue[-250:]

    async def process_retry_queue(self) -> Dict[str, int]:
        """
        Process pending retry items.

        Called periodically by A-17 Adaptive Scheduler or
        the main event loop.
        """
        now = time.time()
        processed = 0
        still_pending = 0

        new_queue = []
        for item in self._retry_queue:
            if now >= item.get("retry_after", 0):
                # Check if any provider is now available
                provider = self.get_provider_for_task(
                    item["task_type"],
                    TaskPriority(item["priority"]),
                )
                if provider:
                    processed += 1
                    # Item will be re-attempted by the calling agent
                else:
                    # Still no provider — keep in queue with extended delay
                    item["retry_after"] = now + 120
                    new_queue.append(item)
                    still_pending += 1
            else:
                new_queue.append(item)
                still_pending += 1

        self._retry_queue = new_queue
        return {"processed": processed, "still_pending": still_pending}

    # ============================================================
    # NIGHTLY OPERATIONS
    # ============================================================

    async def nightly_reset(self) -> Dict[str, Any]:
        """
        Nightly quota reset and efficiency report.

        Called at midnight IST by the scheduler.
        Resets daily counters and generates an efficiency report.
        """
        report = self.get_health_report()

        # Reset daily counters
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            for pid in ProviderID:
                q = self.quotas[pid]
                q.daily_used = 0
                q.day_window_start = today
                q.minute_used = 0
                q.minute_window_start = time.time()

                # Reset circuit breakers (fresh start)
                self.circuits[pid].consecutive_failures = 0
                if self.circuits[pid].state != CircuitState.CLOSED:
                    self.circuits[pid].state = CircuitState.CLOSED
                    logger.info(
                        f"[{AGENT_ID}] Circuit breaker reset to CLOSED "
                        f"for {pid.value} (nightly reset)"
                    )

                # Reset health scores
                self._health_scores[pid] = 100.0

        # Clear retry queue
        self._retry_queue.clear()

        # Trim request log
        if len(self._request_log) > self._max_log_size:
            self._request_log = self._request_log[-1000:]

        logger.info(
            f"[{AGENT_ID}] Nightly reset complete. "
            f"Previous day: {report['summary']['total_requests']} requests, "
            f"{report['summary']['overall_success_rate']}% success rate"
        )

        return report

    # ============================================================
    # REQUEST LOGGING & ANALYTICS
    # ============================================================

    def _log_request(self, task_type: str, provider: ProviderID,
                      success: bool, latency_ms: float,
                      attempts: List[Dict], context: Dict):
        """Log a request for analytics."""
        entry = {
            "ts": time.time(),
            "task": task_type,
            "provider": provider.value,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "attempts": len(attempts),
            "context": context.get("agent_id", ""),
        }
        self._request_log.append(entry)
        if len(self._request_log) > self._max_log_size:
            self._request_log = self._request_log[-2500:]

    def get_analytics(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get routing analytics for the last N hours.

        Returns per-provider stats, task distribution,
        and efficiency metrics.
        """
        cutoff = time.time() - (hours * 3600)
        recent = [r for r in self._request_log if r.get("ts", 0) >= cutoff]

        if not recent:
            return {"period_hours": hours, "total_requests": 0}

        # Per-provider breakdown
        by_provider = defaultdict(lambda: {"total": 0, "success": 0, "latency_sum": 0})
        for r in recent:
            p = r.get("provider", "unknown")
            by_provider[p]["total"] += 1
            if r.get("success"):
                by_provider[p]["success"] += 1
            by_provider[p]["latency_sum"] += r.get("latency_ms", 0)

        provider_stats = {}
        for p, stats in by_provider.items():
            provider_stats[p] = {
                "requests": stats["total"],
                "success_rate": round(
                    (stats["success"] / max(1, stats["total"])) * 100, 1
                ),
                "avg_latency_ms": round(
                    stats["latency_sum"] / max(1, stats["total"]), 1
                ),
            }

        # Per-task breakdown
        by_task = defaultdict(int)
        for r in recent:
            by_task[r.get("task", "unknown")] += 1

        return {
            "period_hours": hours,
            "total_requests": len(recent),
            "success_rate": round(
                sum(1 for r in recent if r.get("success")) / len(recent) * 100, 1
            ),
            "by_provider": dict(provider_stats),
            "by_task": dict(sorted(by_task.items(), key=lambda x: -x[1])[:20]),
        }

    # ============================================================
    # PROVIDER RECOMMENDATION ENGINE
    # ============================================================

    def recommend_provider(self, task_type: str) -> Dict[str, Any]:
        """
        Recommend the best provider for a task based on
        current health, quota, and historical performance.

        Used by A-17 for intelligent scheduling decisions.
        """
        if task_type not in PRISM_TASK_TABLE:
            return {
                "recommended": ProviderID.MISTRAL.value,
                "reason": "unknown task — using universal fallback",
                "confidence": 0.3,
            }

        primary, fallbacks = PRISM_TASK_TABLE[task_type]
        candidates = [primary] + fallbacks

        best_provider = None
        best_score = -1
        reasons = []

        for provider in candidates:
            health = self._health_scores.get(provider, 0)
            quota = self.quotas[provider]
            remaining_pct = 100 - quota.utilization_pct()

            # Composite score: health * remaining_quota_pct
            score = (health / 100) * (remaining_pct / 100) * 100

            # Bonus for being the primary provider (better quality)
            if provider == primary:
                score *= 1.2

            if score > best_score:
                best_score = score
                best_provider = provider
                reasons = [
                    f"health={health:.0f}",
                    f"quota_remaining={remaining_pct:.0f}%",
                    f"is_primary={provider == primary}",
                ]

        return {
            "recommended": best_provider.value if best_provider else ProviderID.MISTRAL.value,
            "score": round(best_score, 1),
            "reasons": reasons,
            "confidence": min(1.0, best_score / 100),
        }

    # ============================================================
    # TELEGRAM REPORT FORMATTING
    # ============================================================

    def format_telegram_report(self) -> str:
        """
        Format a Telegram-friendly AI efficiency report.

        Used by A-12 for the nightly AI summary.
        """
        report = self.get_health_report()
        analytics = self.get_analytics(hours=24)

        lines = [
            "🤖 *A-14 AI Router Report*",
            f"📊 Total Requests: {analytics.get('total_requests', 0)}",
            f"✅ Success Rate: {analytics.get('success_rate', 0)}%",
            "",
            "*Provider Status:*",
        ]

        for pid in ProviderID:
            info = report["providers"].get(pid.value, {})
            health = info.get("health_score", 0)
            state = info.get("circuit_state", "unknown")
            used = info.get("daily_used", 0)
            limit = info.get("daily_limit", 0)

            # Health emoji
            if health >= 80:
                emoji = "🟢"
            elif health >= 50:
                emoji = "🟡"
            else:
                emoji = "🔴"

            lines.append(
                f"{emoji} *{pid.value.upper()}*: "
                f"{used}/{limit} ({info.get('utilization_pct', 0)}%) "
                f"| {state} | {info.get('avg_latency_ms', 0)}ms"
            )

        summary = report.get("summary", {})
        lines.extend([
            "",
            f"💚 Healthy: {summary.get('providers_healthy', 0)} | "
            f"🟡 Degraded: {summary.get('providers_degraded', 0)} | "
            f"🔴 Down: {summary.get('providers_down', 0)}",
        ])

        retry_count = len(self._retry_queue)
        if retry_count > 0:
            lines.append(f"🔄 Retry Queue: {retry_count} pending")

        return "\n".join(lines)


# ============================================================
# CUSTOM EXCEPTIONS
# ============================================================

class RateLimitError(Exception):
    """Raised when a provider returns 429."""
    pass


class ProviderError(Exception):
    """Raised when a provider returns an error (non-429)."""
    pass


class AllProvidersExhaustedError(Exception):
    """Raised when no provider can handle the request."""
    pass


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_router_instance: Optional[MultiModelRouter] = None
_router_lock = threading.Lock()


def get_multi_model_router() -> MultiModelRouter:
    """Get or create the singleton MultiModelRouter instance."""
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = MultiModelRouter()
    return _router_instance


# ============================================================
# AGENT RUNNER INTERFACE (for main.py integration)
# ============================================================

async def run_agent(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    A-14 agent runner entry point.

    Called by the scheduler/main.py for health check reporting.
    A-14 is middleware — it runs continuously, not on a schedule.
    This function generates the periodic health report.
    """
    router = get_multi_model_router()

    # Generate health report
    health = router.get_health_report()
    analytics = router.get_analytics(hours=1)
    quota_status = router.get_quota_status()

    # Process retry queue
    retry_result = await router.process_retry_queue()

    result = {
        "agent_id": AGENT_ID,
        "agent_name": AGENT_NAME,
        "timestamp": datetime.now(IST).isoformat(),
        "health": health,
        "analytics_1h": analytics,
        "quota_status": quota_status,
        "retry_queue": retry_result,
        "status": "healthy" if health["summary"]["providers_healthy"] >= 3 else "degraded",
    }

    logger.info(
        f"[{AGENT_ID}] Health check: "
        f"{health['summary']['providers_healthy']}/5 providers healthy, "
        f"{analytics.get('total_requests', 0)} requests in last hour, "
        f"{retry_result.get('still_pending', 0)} in retry queue"
    )

    return result
