"""
============================================================
PRISM v0.1 — AI ROUTING ENGINE (5-PROVIDER ARCHITECTURE)
============================================================
5-provider AI routing system with PRISM task routing:

PROVIDERS (all free tier):
    1. Groq 70B        — PRIMARY DEEP (cover letters, JD analysis, reports)
    2. Cerebras 8B/70B — PRIMARY FAST (classification, extraction, parsing)
    3. OpenRouter      — PRIMARY LONG (1M context: ATS sim, CV tailoring)
    4. Groq Compound   — AGENTIC (live web search, company research)
    5. Mistral          — UNIVERSAL FALLBACK (when all else fails)

PRISM v0.1 Upgrades from OFM v7.0:
    - 3 NEW providers: OpenRouter, Groq Compound Beta, Mistral
    - 54-task PRISM routing table (was 2-provider binary)
    - Per-provider circuit breakers (5 independent circuits)
    - Per-provider rate limiters (5 independent limiters)
    - PRISM_FAILOVER_CHAIN: provider → [fallback1, fallback2]
    - 18 new PRISM task prompts (email, CV, follow-up, intel)
    - Groq Compound: built-in web_search + visit_url tools
    - OpenRouter: OpenAI-compatible API with custom base_url

Architecture:
    - Task-based routing with 2-level fallback chain
    - Quota tracking per-provider with aggressive utilization
    - Response caching with intelligent TTL
    - Structured JSON output parsing
    - Concurrent batch processing
============================================================
"""

import os
import sys
import json
import time
import hashlib
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import (
    Dict, List, Optional, Tuple, Any, Union, Callable, Set
)
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from functools import lru_cache

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# Local imports
from core.config import (
    get_config, TASK_TEMPERATURE_MAP, TASK_MAX_TOKENS_MAP,
    IST, GroqConfig, CerebrasConfig,
    # PRISM v0.1 new providers
    OpenRouterConfig, GroqCompoundConfig, MistralConfig,
    PRISM_TASK_ROUTING, PRISM_FAILOVER_CHAIN,
)
from core.database import get_db


# ============================================================
# ENUMS & CONSTANTS
# ============================================================

class AIProvider(Enum):
    """Available AI providers (PRISM v0.1: 5 providers)."""
    GROQ = "groq"
    CEREBRAS = "cerebras"
    OPENROUTER = "openrouter"
    GROQ_COMPOUND = "groq_compound"
    MISTRAL = "mistral"


class TaskCategory(Enum):
    """Task categories for routing decisions."""
    CLASSIFICATION = "classification"   # Binary/multi-class decisions
    EXTRACTION = "extraction"           # Entity/data extraction from text
    SCORING = "scoring"                 # Numeric scoring/ranking
    GENERATION = "generation"           # Creative text generation
    ANALYSIS = "analysis"               # Deep text analysis
    PARSING = "parsing"                 # HTML/JSON/text parsing


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocked — too many failures
    HALF_OPEN = "half_open" # Testing recovery


# Task to provider mapping (legacy — PRISM uses PRISM_TASK_ROUTING from config)
CEREBRAS_TASKS: Set[str] = {
    'ghost_classify', 'intent_classify', 'extract_basics',
    'dedup_score', 'internshala_parse', 'sector_tag',
    'naukri_parse', 'iimjobs_parse', 'ats_extract',
    'dark_classify', 'signal_score', 'quick_classify',
    # v7.0 Cerebras tasks
    'listing_quality_score', 'salary_benchmark',
    'duplicate_semantic', 'anomaly_detect',
    'enrichment_priority',
    # PRISM v0.1 NEW Cerebras tasks
    'followup_draft', 'tg_message_extract', 'schedule_health_check',
}

GROQ_TASKS: Set[str] = {
    'cover_letter', 'ats_simulation', 'resume_tweaks',
    'jd_analysis', 'outreach_draft', 'company_research',
    'report_compile', 'economic_analysis', 'package_generate',
    'network_outreach', 'deep_analysis',
    # v7.0 Groq tasks
    'deep_jd_parse', 'company_intent_predict',
    'schedule_optimize', 'proxy_strategy',
    # PRISM v0.1 NEW Groq tasks
    'email_personalize', 'alumni_outreach_draft', 'weekly_report_narrative',
}

# PRISM v0.1: OpenRouter tasks (1M context)
OPENROUTER_TASKS: Set[str] = {
    'ats_simulation_full', 'cv_tailor_full',
    'jd_comprehensive_analysis', 'resume_full_rewrite',
    'interview_prep_deep',
}

# PRISM v0.1: Groq Compound tasks (agentic web search)
GROQ_COMPOUND_TASKS: Set[str] = {
    'web_search', 'live_research', 'deep_company_intel',
    'intent_verify', 'funding_verify', 'career_page_scan',
    'news_aggregate', 'leadership_scan',
}

# PRISM v0.1: Mistral tasks (fallback)
MISTRAL_TASKS: Set[str] = {
    'fallback_classify', 'fallback_generate', 'fallback_analyze',
}

# Task to category mapping
TASK_CATEGORIES: Dict[str, TaskCategory] = {
    'ghost_classify': TaskCategory.CLASSIFICATION,
    'intent_classify': TaskCategory.CLASSIFICATION,
    'dark_classify': TaskCategory.CLASSIFICATION,
    'quick_classify': TaskCategory.CLASSIFICATION,
    'signal_score': TaskCategory.SCORING,
    'dedup_score': TaskCategory.SCORING,
    'extract_basics': TaskCategory.EXTRACTION,
    'ats_extract': TaskCategory.EXTRACTION,
    'internshala_parse': TaskCategory.PARSING,
    'naukri_parse': TaskCategory.PARSING,
    'iimjobs_parse': TaskCategory.PARSING,
    'sector_tag': TaskCategory.CLASSIFICATION,
    'cover_letter': TaskCategory.GENERATION,
    'outreach_draft': TaskCategory.GENERATION,
    'resume_tweaks': TaskCategory.GENERATION,
    'ats_simulation': TaskCategory.ANALYSIS,
    'jd_analysis': TaskCategory.ANALYSIS,
    'company_research': TaskCategory.ANALYSIS,
    'report_compile': TaskCategory.GENERATION,
    'economic_analysis': TaskCategory.ANALYSIS,
    'package_generate': TaskCategory.GENERATION,
    'network_outreach': TaskCategory.GENERATION,
    'deep_analysis': TaskCategory.ANALYSIS,
    # v7.0 NEW task categories
    'listing_quality_score': TaskCategory.SCORING,
    'salary_benchmark': TaskCategory.SCORING,
    'duplicate_semantic': TaskCategory.SCORING,
    'anomaly_detect': TaskCategory.ANALYSIS,
    'enrichment_priority': TaskCategory.SCORING,
    'deep_jd_parse': TaskCategory.EXTRACTION,
    'company_intent_predict': TaskCategory.ANALYSIS,
    'schedule_optimize': TaskCategory.ANALYSIS,
    'proxy_strategy': TaskCategory.ANALYSIS,
    # PRISM v0.1 NEW task categories
    'email_personalize': TaskCategory.GENERATION,
    'alumni_outreach_draft': TaskCategory.GENERATION,
    'weekly_report_narrative': TaskCategory.GENERATION,
    'followup_draft': TaskCategory.GENERATION,
    'tg_message_extract': TaskCategory.EXTRACTION,
    'schedule_health_check': TaskCategory.ANALYSIS,
    'ats_simulation_full': TaskCategory.ANALYSIS,
    'cv_tailor_full': TaskCategory.GENERATION,
    'jd_comprehensive_analysis': TaskCategory.ANALYSIS,
    'resume_full_rewrite': TaskCategory.GENERATION,
    'interview_prep_deep': TaskCategory.GENERATION,
    'web_search': TaskCategory.ANALYSIS,
    'live_research': TaskCategory.ANALYSIS,
    'deep_company_intel': TaskCategory.ANALYSIS,
    'intent_verify': TaskCategory.ANALYSIS,
    'funding_verify': TaskCategory.ANALYSIS,
    'career_page_scan': TaskCategory.EXTRACTION,
    'news_aggregate': TaskCategory.ANALYSIS,
    'leadership_scan': TaskCategory.EXTRACTION,
}


# ============================================================
# RESPONSE DATA MODEL
# ============================================================

@dataclass
class AIResponse:
    """Structured response from an AI call."""
    content: str = ""
    provider: str = ""
    model: str = ""
    task: str = ""
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False
    error: Optional[str] = None
    success: bool = True
    fallback_used: bool = False
    retry_count: int = 0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'content': self.content,
            'provider': self.provider,
            'model': self.model,
            'task': self.task,
            'tokens_used': self.tokens_used,
            'latency_ms': self.latency_ms,
            'cached': self.cached,
            'error': self.error,
            'success': self.success,
            'fallback_used': self.fallback_used,
        }

    def get_json(self) -> Optional[Dict]:
        """Try to parse the content as JSON."""
        if not self.content:
            return None
        try:
            # Try direct parse
            return json.loads(self.content)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code blocks
            content = self.content.strip()
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                if end > start:
                    try:
                        return json.loads(content[start:end].strip())
                    except json.JSONDecodeError:
                        pass
            elif '```' in content:
                start = content.find('```') + 3
                end = content.find('```', start)
                if end > start:
                    try:
                        return json.loads(content[start:end].strip())
                    except json.JSONDecodeError:
                        pass
            # Try finding JSON objects/arrays in text
            for start_char, end_char in [('{', '}'), ('[', ']')]:
                start_idx = content.find(start_char)
                end_idx = content.rfind(end_char)
                if start_idx >= 0 and end_idx > start_idx:
                    try:
                        return json.loads(content[start_idx:end_idx + 1])
                    except json.JSONDecodeError:
                        continue
            return None


# ============================================================
# RATE LIMITER
# ============================================================

class RateLimiter:
    """
    Token bucket rate limiter for API calls.
    Tracks usage per minute, per hour, and per day.
    """

    def __init__(self, per_minute: int = 30, per_hour: int = 500,
                 per_day: int = 14400):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day

        self._minute_calls: List[float] = []
        self._hour_calls: List[float] = []
        self._day_calls: List[float] = []
        self._lock = threading.Lock()

    def _cleanup(self, calls: List[float], window_seconds: float) -> List[float]:
        """Remove expired timestamps from the list."""
        cutoff = time.time() - window_seconds
        return [t for t in calls if t > cutoff]

    def can_call(self) -> bool:
        """Check if a call is allowed under current rate limits."""
        with self._lock:
            now = time.time()
            self._minute_calls = self._cleanup(self._minute_calls, 60)
            self._hour_calls = self._cleanup(self._hour_calls, 3600)
            self._day_calls = self._cleanup(self._day_calls, 86400)

            if len(self._minute_calls) >= self.per_minute:
                return False
            if len(self._hour_calls) >= self.per_hour:
                return False
            if len(self._day_calls) >= self.per_day:
                return False
            return True

    def record_call(self):
        """Record a successful API call."""
        with self._lock:
            now = time.time()
            self._minute_calls.append(now)
            self._hour_calls.append(now)
            self._day_calls.append(now)

    def wait_time(self) -> float:
        """Calculate how long to wait before next call is allowed."""
        with self._lock:
            now = time.time()
            self._minute_calls = self._cleanup(self._minute_calls, 60)

            if len(self._minute_calls) >= self.per_minute:
                oldest = min(self._minute_calls)
                return max(0, oldest + 60 - now + 0.1)
            return 0

    def get_usage(self) -> Dict[str, Any]:
        """Get current usage statistics."""
        with self._lock:
            now = time.time()
            self._minute_calls = self._cleanup(self._minute_calls, 60)
            self._hour_calls = self._cleanup(self._hour_calls, 3600)
            self._day_calls = self._cleanup(self._day_calls, 86400)
            return {
                'minute': len(self._minute_calls),
                'minute_limit': self.per_minute,
                'hour': len(self._hour_calls),
                'hour_limit': self.per_hour,
                'day': len(self._day_calls),
                'day_limit': self.per_day,
                'minute_pct': round(len(self._minute_calls) / self.per_minute * 100, 1),
                'hour_pct': round(len(self._hour_calls) / self.per_hour * 100, 1),
                'day_pct': round(len(self._day_calls) / self.per_day * 100, 1),
            }


# ============================================================
# CIRCUIT BREAKER
# ============================================================

class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    Opens after N consecutive failures, auto-resets after timeout.
    """

    def __init__(self, failure_threshold: int = 5,
                 reset_timeout_sec: float = 300.0,
                 half_open_max_calls: int = 2):
        self.failure_threshold = failure_threshold
        self.reset_timeout_sec = reset_timeout_sec
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (self._last_failure_time and
                    time.time() - self._last_failure_time > self.reset_timeout_sec):
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
            return self._state

    def can_call(self) -> bool:
        """Check if a call is allowed."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            with self._lock:
                return self._half_open_calls < self.half_open_max_calls
        return False  # OPEN

    def record_success(self):
        """Record a successful call — may close circuit."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info("Circuit breaker closed (recovered)")
            else:
                self._failure_count = 0

    def record_failure(self):
        """Record a failed call — may open circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker OPEN after {self._failure_count} failures. "
                    f"Will retry in {self.reset_timeout_sec}s"
                )
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker re-opened on half-open failure")

    def get_status(self) -> Dict[str, Any]:
        return {
            'state': self.state.value,
            'failure_count': self._failure_count,
            'threshold': self.failure_threshold,
        }


# ============================================================
# RESPONSE CACHE
# ============================================================

class ResponseCache:
    """
    LRU cache for AI responses to avoid redundant API calls.
    Keyed by (task, prompt_hash). TTL-based expiration.
    """

    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[AIResponse, float]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, task: str, prompt: str) -> str:
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        return f"{task}:{prompt_hash}"

    def get(self, task: str, prompt: str) -> Optional[AIResponse]:
        """Get a cached response if available and not expired."""
        key = self._make_key(task, prompt)
        with self._lock:
            if key in self._cache:
                response, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    self._hits += 1
                    cached_response = AIResponse(
                        content=response.content,
                        provider=response.provider,
                        model=response.model,
                        task=response.task,
                        tokens_used=0,
                        latency_ms=0,
                        cached=True,
                        success=True,
                    )
                    return cached_response
                else:
                    del self._cache[key]
            self._misses += 1
            return None

    def put(self, task: str, prompt: str, response: AIResponse):
        """Cache a response."""
        if not response.success or response.error:
            return
        key = self._make_key(task, prompt)
        with self._lock:
            if len(self._cache) >= self.max_size:
                # Evict oldest
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (response, time.time())

    def get_stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            'size': len(self._cache),
            'max_size': self.max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(self._hits / total * 100, 1) if total > 0 else 0,
        }

    def clear(self):
        with self._lock:
            self._cache.clear()


# ============================================================
# PROMPT TEMPLATES
# ============================================================

PROMPT_TEMPLATES: Dict[str, str] = {
    # ---- CEREBRAS TASKS (Fast Classification/Extraction) ----

    'ghost_classify': """Analyze this job listing and determine if it's likely a ghost/fake job posting.

Listing:
Title: {title}
Company: {company}
Posted: {posted_days_ago} days ago
Applicants: {applicants}
Stipend: {stipend}
Source: {source}

Consider these signals:
1. Listing age (>30 days is suspicious)
2. Applicant count overload (>500 still open is suspicious)
3. Repetitive posting pattern
4. Lack of specific requirements or vague JD
5. Unrealistic stipend for the role

Respond in JSON format:
{{
    "is_ghost": true/false,
    "confidence": 0.0-1.0,
    "ghost_score": 0-100,
    "signals": ["signal1", "signal2"],
    "reasoning": "brief explanation"
}}""",

    'intent_classify': """Classify this text as a hiring intent signal for Indian companies.

Text: {text}
Source: {source}

Classify the hiring intent:
- Is this about a company expanding/hiring in India?
- What company is mentioned?
- What type of signal is it? (news/hr_post/funding/expansion/earnings)
- How strong is the hiring signal? (0-100)

Respond in JSON format:
{{
    "is_hiring_signal": true/false,
    "company": "company name or null",
    "signal_type": "news/hr_post/funding/expansion/earnings",
    "signal_score": 0-100,
    "keywords": ["keyword1", "keyword2"],
    "summary": "one-line summary"
}}""",

    'extract_basics': """Extract structured job listing data from this HTML/text content.

Content:
{content}

Extract these fields (set null if not found):
- title: Job/internship title
- company: Company name
- location: City or "Remote"/"WFH"
- stipend: Monthly stipend amount in INR
- duration: Internship duration
- applicants: Number of applicants
- is_ppo: Does it mention PPO/Pre-Placement Offer?
- is_wfh: Is it work from home/remote?
- posted_date: When was it posted?
- skills: Required skills list
- url: Application URL

Respond in JSON format:
{{
    "title": "...",
    "company": "...",
    "location": "...",
    "stipend": "...",
    "stipend_normalized": 0,
    "duration": "...",
    "duration_months": 0,
    "applicants": 0,
    "is_ppo": false,
    "is_wfh": false,
    "posted_days_ago": 0,
    "skills": [],
    "url": "..."
}}""",

    'dedup_score': """Compare these two job listings and determine if they are duplicates.

Listing A:
Title: {title_a}
Company: {company_a}
Location: {location_a}
Stipend: {stipend_a}
Source: {source_a}
Description: {desc_a}

Listing B:
Title: {title_b}
Company: {company_b}
Location: {location_b}
Stipend: {stipend_b}
Source: {source_b}
Description: {desc_b}

Respond in JSON format:
{{
    "is_duplicate": true/false,
    "confidence": 0.0-1.0,
    "matching_fields": ["field1", "field2"],
    "differences": ["diff1", "diff2"],
    "recommendation": "merge/keep_both/keep_a/keep_b"
}}""",

    'internshala_parse': """Parse this Internshala listing card HTML into structured data.

HTML Content:
{html}

Extract ALL available fields:
{{
    "title": "internship title",
    "company": "company name",
    "location": "city or Remote",
    "stipend": "stipend text",
    "stipend_normalized": monthly_amount_in_inr,
    "duration": "duration text",
    "duration_months": number,
    "applicants": number_or_0,
    "is_ppo": true/false,
    "is_wfh": true/false,
    "posted_days_ago": number,
    "start_date": "start date text",
    "skills": ["skill1", "skill2"],
    "url": "/internship/..."
}}""",

    'sector_tag': """Classify this company into an industry sector and size band.

Company: {company_name}
Additional Info: {additional_info}

Classify into:
- sector: One of [Technology, FMCG, Banking & Finance, Consulting, E-Commerce, Healthcare, Manufacturing, Energy, Automotive, Telecom, Media & Entertainment, Education, Real Estate, Insurance, Fintech, Edtech, Healthtech, SaaS, D2C, AI/ML, PE/VC, Investment Banking, Boutique Consulting, Logistics, Retail, Pharma]
- sub_sector: More specific category
- size_band: One of [startup, small, mid, large, enterprise]
- tier: 1-5 (1=Elite like McKinsey/Google, 2=Strong MNC, 3=Indian Unicorn, 4=Growing Startup, 5=Niche)

Respond in JSON:
{{
    "sector": "...",
    "sub_sector": "...",
    "size_band": "...",
    "tier": 1-5,
    "reasoning": "brief explanation"
}}""",

    'dark_classify': """Analyze this message from a {channel_type} channel and determine if it contains a job/internship posting.

Message:
{message}

Channel: {channel_name}

Determine:
1. Is this a job/internship posting?
2. What company is mentioned?
3. What role/position?
4. Any application link?
5. Confidence level?

Respond in JSON:
{{
    "is_job": true/false,
    "confidence": 0.0-1.0,
    "company": "company name or null",
    "role": "role title or null",
    "url": "application url or null",
    "location": "location or null",
    "stipend": "stipend or null",
    "keywords": ["keyword1", "keyword2"]
}}""",

    'signal_score': """Score the strength of this hiring intent signal for the company.

Company: {company}
Signal Text: {signal_text}
Signal Type: {signal_type}
Source: {source}

Score from 0-100 based on:
- Directness: Is it explicitly about hiring? (0-40)
- Recency: How recent is this signal? (0-20)
- Relevance: Is it relevant to MBA internships? (0-20)
- Credibility: Is the source credible? (0-20)

Respond in JSON:
{{
    "signal_score": 0-100,
    "directness": 0-40,
    "recency": 0-20,
    "relevance": 0-20,
    "credibility": 0-20,
    "summary": "one-line summary"
}}""",

    # ---- GROQ TASKS (Heavy Analysis/Generation) ----

    'cover_letter': """Write a 200-word tailored cover letter for this internship.

Job Listing:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Candidate Profile:
- MBA student at {college}
- Specialization: {specialization}
- Key skills: {skills}
- Previous experience: {experience}

Requirements:
- Exactly 200 words
- Professional but not generic
- Reference specific company details
- Highlight relevant skills
- Show genuine interest and research
- Include a strong opening and closing
- Do NOT use cliches like "I am writing to express my interest"

Write the cover letter now:""",

    'ats_simulation': """Simulate an ATS (Applicant Tracking System) scan of a resume against this job description.

Job Description:
{jd_text}

Resume Content:
{resume_text}

Perform this analysis:
1. Extract top 20 keywords from the JD
2. Check which keywords appear in the resume
3. Calculate keyword match percentage
4. Identify critical missing keywords
5. Suggest 3 specific bullet-point resume tweaks
6. Identify sections that need strengthening
7. Rate ATS pass probability (0-100%)

Respond in JSON:
{{
    "jd_keywords": ["keyword1", "keyword2", ...],
    "matched_keywords": ["keyword1", "keyword2", ...],
    "missing_keywords": ["keyword1", "keyword2", ...],
    "match_percentage": 0-100,
    "ats_pass_probability": 0-100,
    "resume_tweaks": [
        "Tweak 1: ...",
        "Tweak 2: ...",
        "Tweak 3: ..."
    ],
    "weak_sections": ["section1", "section2"],
    "suggested_phrases": ["phrase1", "phrase2"],
    "overall_assessment": "brief assessment"
}}""",

    'resume_tweaks': """Suggest specific resume improvements for this job application.

Job Title: {title}
Company: {company}
Job Description: {jd_text}

Current Resume Bullets:
{resume_bullets}

Missing Keywords: {missing_keywords}

For each resume bullet, suggest an improved version that:
1. Incorporates missing keywords naturally
2. Uses strong action verbs
3. Includes quantifiable metrics where possible
4. Aligns with the job requirements
5. Maintains truthfulness

Respond in JSON:
{{
    "improved_bullets": [
        {{
            "original": "...",
            "improved": "...",
            "keywords_added": ["keyword1"],
            "reason": "..."
        }}
    ],
    "new_bullets_to_add": [
        "New bullet suggestion 1",
        "New bullet suggestion 2"
    ],
    "skills_to_highlight": ["skill1", "skill2"]
}}""",

    'jd_analysis': """Perform a comprehensive analysis of this job description.

Title: {title}
Company: {company}
Description:
{jd_text}

Analyze:
1. Core requirements (must-have skills/experience)
2. Nice-to-have qualifications
3. Company culture indicators
4. Red flags (if any)
5. Application strategy recommendations
6. Key phrases that indicate what they truly value
7. Estimated competition level
8. Fit assessment for an MBA student

Respond in JSON:
{{
    "core_requirements": ["req1", "req2"],
    "nice_to_haves": ["ntb1", "ntb2"],
    "culture_indicators": ["culture1"],
    "red_flags": ["flag1"],
    "strategy": "application strategy",
    "key_phrases": ["phrase1"],
    "competition_estimate": "low/medium/high",
    "mba_fit_score": 0-100,
    "summary": "2-3 sentence summary"
}}""",

    'outreach_draft': """Write a warm outreach message to a potential connection at this company.

Target Person:
Name: {person_name}
Role: {person_role}
Company: {company}
Connection: {connection_type}
College: {shared_college}

Candidate:
Name: {candidate_name}
College: {candidate_college}
Target Role: {target_role}

Write a concise, professional outreach message (100-150 words) that:
1. Establishes the connection (shared college, mutual contact, etc.)
2. Shows genuine interest in the company
3. Briefly mentions relevant background
4. Has a clear, non-pushy ask
5. Is warm and authentic, not templated

Write the message:""",

    'company_research': """Compile a comprehensive research brief on this company for an MBA internship candidate.

Company: {company}
Sector: {sector}
Recent News: {news_items}
Glassdoor Rating: {glassdoor_rating}
Intent Signals: {signals}

Generate a research brief covering:
1. Company Overview (50 words)
2. Recent Developments (key news, funding, expansion)
3. Culture & Work Environment
4. Internship/PPO History (if known)
5. Key People to Know (leadership team)
6. Interview Preparation Tips
7. Why This Company for MBA (strategic reasons)
8. CIRS Analysis (Company Intern Readiness Score breakdown)

Respond in JSON:
{{
    "overview": "...",
    "recent_developments": ["dev1", "dev2"],
    "culture": "...",
    "internship_history": "...",
    "key_people": ["person1", "person2"],
    "interview_tips": ["tip1", "tip2"],
    "why_apply": "...",
    "cirs_analysis": "...",
    "overall_recommendation": "strong_apply/apply/maybe/skip"
}}""",

    'report_compile': """Compile a structured Telegram report from this data.

Report Type: {report_type}
Date: {date}
Data:
{data}

Format the report as a clean, readable Telegram message with:
- Emoji headers for sections
- Key statistics prominently displayed
- Top items with brief descriptions
- Actionable insights
- Keep under 4000 characters

Generate the report:""",

    'economic_analysis': """Analyze these economic signals and their impact on MBA internship hiring.

Signals:
{signals}

Sectors to analyze: {sectors}

For each sector, determine:
1. Current hiring momentum (0-100)
2. Key drivers (positive and negative)
3. Top companies likely hiring
4. Recommended MBA specializations
5. 30-day outlook

Respond in JSON:
{{
    "sectors": [
        {{
            "name": "sector",
            "momentum_score": 0-100,
            "positive_drivers": ["driver1"],
            "negative_drivers": ["driver1"],
            "top_hiring_companies": ["company1"],
            "recommended_specs": ["spec1"],
            "outlook": "positive/neutral/negative",
            "summary": "..."
        }}
    ],
    "overall_market": "brief market summary"
}}""",

    'package_generate': """Generate a complete application package for this internship.

Listing:
Title: {title}
Company: {company}
Description: {jd_text}

Candidate Profile:
{profile}

Generate:
1. Cover Letter (200 words, tailored)
2. Resume Tweaks (top 3 bullet improvements)
3. Interview Prep (5 likely questions + answers)
4. Warm Intro Draft (if alumni connection exists: {alumni_info})

Respond in JSON:
{{
    "cover_letter": "...",
    "resume_tweaks": ["tweak1", "tweak2", "tweak3"],
    "interview_prep": [
        {{"question": "Q1", "suggested_answer": "A1"}},
        ...
    ],
    "warm_intro_draft": "..." or null,
    "key_talking_points": ["point1", "point2"]
}}""",

    # ============================================================
    # v7.0 NEW PROMPT TEMPLATES
    # ============================================================

    'listing_quality_score': """Rate this job listing's quality for an MBA intern on a scale of 0-100.

Title: {title}
Company: {company}
Location: {location}
Stipend: {stipend}
Duration: {duration}
Source: {source}
Applicants: {applicants}
PPO: {is_ppo}
Description snippet: {description}

Quality factors:
- Clarity of role and responsibilities (0-20)
- Company reputation/tier (0-20)
- Compensation fairness (0-15)
- Growth potential (0-15)
- Relevance to MBA (0-15)
- Freshness/recency (0-15)

Respond in JSON:
{{
    "quality_score": 0-100,
    "clarity": 0-20,
    "company_rep": 0-20,
    "compensation": 0-15,
    "growth": 0-15,
    "mba_relevance": 0-15,
    "freshness": 0-15,
    "highlights": ["highlight1"],
    "red_flags": ["flag1"],
    "recommendation": "apply/consider/skip"
}}""",

    'deep_jd_parse': """Extract comprehensive structured data from this job description.

Job Description:
{jd_text}

Extract ALL of these fields (null if not found):
{{
    "title": "exact job title",
    "company": "company name",
    "department": "department/team",
    "location": "city/remote",
    "is_remote": true/false,
    "is_hybrid": true/false,
    "stipend_min": number or null,
    "stipend_max": number or null,
    "stipend_currency": "INR",
    "duration_months": number,
    "start_date": "when",
    "application_deadline": "deadline",
    "required_skills": ["skill1", "skill2"],
    "preferred_skills": ["skill1"],
    "education_required": "MBA/any",
    "experience_required": "0-1 years",
    "key_responsibilities": ["resp1", "resp2"],
    "perks_benefits": ["perk1"],
    "has_ppo": true/false,
    "reporting_to": "role of manager",
    "team_size": "estimated",
    "tools_used": ["tool1"],
    "industry_sector": "sector",
    "job_function": "marketing/finance/etc",
    "seniority_level": "intern/entry/mid"
}}""",

    'company_intent_predict': """Predict this company's hiring intent for MBA interns based on available signals.

Company: {company}
Sector: {sector}
Recent Signals:
{signals}

News Context:
{news}

Predict:
1. Likelihood of active hiring (0-100)
2. Estimated timeline (immediate/1-3months/3-6months)
3. Likely departments hiring
4. Key decision makers to target
5. Best approach for outreach

Respond in JSON:
{{
    "hiring_probability": 0-100,
    "timeline": "immediate/1-3months/3-6months",
    "likely_departments": ["dept1", "dept2"],
    "key_people": ["title1", "title2"],
    "approach": "strategy recommendation",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}""",

    'salary_benchmark': """Benchmark this internship stipend against market rates.

Title: {title}
Company: {company}
Category: {category}
Location: {location}
Stipend: {stipend} per month
Company Tier: {tier}

Compare against typical Indian MBA internship stipends for:
- Same role category
- Same company tier
- Same city/location type

Respond in JSON:
{{
    "stipend_rating": "below_market/at_market/above_market",
    "market_median": estimated_median,
    "percentile": 0-100,
    "tier_median": estimated_tier_median,
    "location_factor": "premium/standard/discount",
    "overall_compensation_score": 0-100,
    "note": "brief context"
}}""",

    'anomaly_detect': """Analyze these scraping statistics for anomalies.

Day Statistics:
{stats}

Historical Averages:
{averages}

Check for:
1. Sudden drops in listing counts (>50% below average)
2. Unusual duplicate rates (>30%)
3. Portal-specific failures
4. Proxy block spikes
5. Response time degradation
6. Missing data fields

Respond in JSON:
{{
    "anomalies": ["anomaly1", "anomaly2"],
    "severity": "none/low/medium/high/critical",
    "healthy": true/false,
    "affected_portals": ["portal1"],
    "recommendations": ["action1", "action2"],
    "confidence": 0.0-1.0
}}""",

    'enrichment_priority': """Rank these job listings by enrichment priority.

Listings:
{listings}

Rank by which listings would benefit MOST from deeper research:
- High-tier companies with incomplete data → HIGH priority
- Fresh listings with missing details → HIGH priority  
- Already enriched listings → LOW priority
- Old/stale listings → LOW priority

Respond in JSON:
{{
    "ranked_ids": [id1, id2, id3],
    "high_priority": [id1],
    "medium_priority": [id2],
    "low_priority": [id3],
    "skip": [id4],
    "reasoning": "brief explanation"
}}""",

    # ============================================================
    # PRISM v0.1: NEW PROMPT TEMPLATES
    # ============================================================

    'email_personalize': """Write 2-3 personalization sentences for a cold outreach email.

Recipient: {recipient_name} ({recipient_role}) at {company}
Company Intel: {company_intel}
Listing: {listing_title}
Connection Type: {connection_type}
Candidate: MBA student specializing in {specialization}

Requirements:
- Reference specific company news/achievements from intel
- Show genuine knowledge of the company
- Be professional but warm
- Keep under 60 words total
- Do NOT use generic flattery

Respond in JSON:
{{
    "personalization_lines": ["line1", "line2"],
    "opening_hook": "attention-grabbing first sentence",
    "quality_score": 0-100
}}""",

    'alumni_outreach_draft': """Write a warm alumni outreach message.

Alumni: {alumni_name} (batch {batch_year}, {college})
Current Role: {current_role} at {company}
Connection: {connection_type}
Company Intel: {company_intel}
Target Role: {target_role}

Write a 100-word message that:
1. Establishes shared college bond
2. Shows genuine interest in their career path
3. Mentions specific company achievement
4. Has a soft, non-pushy ask for guidance
5. Is authentic, not templated

Write the message:""",

    'followup_draft': """Write a concise follow-up email for a silent application.

Original Application:
- Company: {company}
- Role: {role}
- Applied: {applied_date} ({days_ago} days ago)
- Application Method: {method}

Requirements:
- Under 80 words
- Professional, not desperate
- Reference the specific role
- Add one new value proposition
- Clear call to action

Respond in JSON:
{{
    "subject": "follow-up subject line",
    "body": "email body text",
    "tone": "professional/warm/assertive"
}}""",

    'tg_message_extract': """Extract job/internship details from this Telegram message.

Message:
{message}

Channel: {channel_name}

Extract if this is a job/internship posting:
{{
    "is_job": true/false,
    "confidence": 0.0-1.0,
    "company": "company name or null",
    "role": "job title or null",
    "location": "location or null",
    "stipend": "stipend or null",
    "url": "application link or null",
    "contact": "contact info or null",
    "deadline": "deadline or null",
    "keywords": ["keyword1", "keyword2"]
}}""",

    'cv_tailor_full': """Rewrite these resume bullet points to match the job description.

Job Description:
{jd_text}

Missing Keywords: {missing_keywords}
Keyword Match: {match_pct}%

Current Bullets:
{bullets}

Company Hooks: {company_hooks}

For each bullet, create an improved version that:
1. Naturally incorporates 1-2 missing keywords
2. Maintains truthfulness (don't fabricate experience)
3. Uses strong action verbs with quantified metrics
4. Aligns with the specific JD requirements
5. Keeps similar length to original

Respond in JSON:
{{
    "improved_bullets": [
        {{
            "original": "original bullet",
            "improved": "improved bullet with keywords",
            "keywords_injected": ["keyword1"],
            "change_type": "keyword_inject/metric_add/verb_strengthen"
        }}
    ],
    "skills_to_add": ["skill1", "skill2"],
    "summary_tweak": "optional 1-line resume summary adjustment"
}}""",

    'deep_company_intel': """Research this company for an MBA internship application.

Company: {company}
Sector: {sector}
Career Page: {careers_url}

Research the following (use web search):
1. Latest news (last 3 months)
2. Recent funding/expansion
3. Key leadership (CEO, CHRO, Head of HR)
4. Intern/fresher hiring history
5. Glassdoor sentiment
6. Competitor comparison

Generate a 500-word Intel Brief:
{{
    "company_name": "...",
    "intel_brief": "500-word research brief",
    "personalization_hooks": ["hook1 for cover letter", "hook2", "hook3"],
    "key_people": [{{"name": "...", "role": "..."}}, ...],
    "recent_news": ["news1", "news2"],
    "hiring_status": "active_hiring/passive/frozen",
    "intern_review_summary": "brief intern experience summary",
    "career_page_url": "url"
}}""",

    'schedule_health_check': """Analyze this portal/agent health data and suggest schedule adjustments.

Portal Health:
{portal_health}

Agent Heartbeats:
{agent_heartbeats}

AI Quota Usage:
{quota_usage}

Analyze and suggest:
{{
    "healthy_portals": ["portal1"],
    "degraded_portals": ["portal2"],
    "failed_portals": ["portal3"],
    "schedule_adjustments": [
        {{"agent": "A-03", "action": "delay_2h", "reason": "portal down"}}
    ],
    "quota_alert": true/false,
    "overall_health": "healthy/degraded/critical"
}}""",
}


# ============================================================
# AI ROUTER CLASS
# ============================================================

class AIRouter:
    """
    PRISM v0.1: 5-provider AI routing engine that distributes tasks
    across Groq, Cerebras, OpenRouter, Groq Compound, and Mistral
    to maximize free-tier quota utilization.

    Usage:
        router = AIRouter()
        response = router.call("ghost_classify", prompt)         # → Cerebras
        response = router.call("cover_letter", prompt)           # → Groq
        response = router.call("ats_simulation_full", prompt)    # → OpenRouter
        response = router.call("deep_company_intel", prompt)     # → Groq Compound
        response = router.call("fallback_classify", prompt)      # → Mistral
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.config = get_config()

        # Initialize provider clients (lazy)
        self._groq_client = None
        self._cerebras_client = None
        self._openrouter_client = None
        self._mistral_client = None
        # Groq Compound uses same client as Groq (different model)

        # Rate limiters (all 5 providers)
        self._groq_limiter = RateLimiter(
            per_minute=self.config.groq.requests_per_minute,
            per_hour=self.config.groq.requests_per_hour,
            per_day=self.config.groq.daily_request_limit,
        )
        self._cerebras_limiter = RateLimiter(
            per_minute=self.config.cerebras.requests_per_minute,
            per_hour=self.config.cerebras.requests_per_hour,
            per_day=self.config.cerebras.daily_request_limit,
        )
        self._openrouter_limiter = RateLimiter(
            per_minute=self.config.openrouter.requests_per_minute,
            per_hour=self.config.openrouter.requests_per_hour,
            per_day=self.config.openrouter.daily_request_limit,
        )
        self._groq_compound_limiter = RateLimiter(
            per_minute=self.config.groq_compound.requests_per_minute,
            per_hour=self.config.groq_compound.requests_per_hour,
            per_day=self.config.groq_compound.daily_request_limit,
        )
        self._mistral_limiter = RateLimiter(
            per_minute=self.config.mistral.requests_per_minute,
            per_hour=self.config.mistral.requests_per_hour,
            per_day=self.config.mistral.daily_request_limit,
        )

        # Circuit breakers (all 5 providers)
        self._groq_circuit = CircuitBreaker(
            failure_threshold=5, reset_timeout_sec=300
        )
        self._cerebras_circuit = CircuitBreaker(
            failure_threshold=5, reset_timeout_sec=300
        )
        self._openrouter_circuit = CircuitBreaker(
            failure_threshold=3, reset_timeout_sec=600
        )
        self._groq_compound_circuit = CircuitBreaker(
            failure_threshold=3, reset_timeout_sec=600
        )
        self._mistral_circuit = CircuitBreaker(
            failure_threshold=3, reset_timeout_sec=600
        )

        # Response cache
        self._cache = ResponseCache(max_size=500, ttl_seconds=3600)

        # Stats
        self._total_calls = 0
        self._total_tokens = 0
        self._total_errors = 0
        self._provider_calls = defaultdict(int)
        self._task_calls = defaultdict(int)
        self._fallback_count = 0

        logger.info(
            "PRISM v0.1 AI Router initialized "
            "(Groq + Cerebras + OpenRouter + Groq Compound + Mistral)"
        )

    # ----------------------------------------------------------
    # LAZY CLIENT INITIALIZATION
    # ----------------------------------------------------------

    def _get_groq_client(self):
        """Lazily initialize Groq client."""
        if self._groq_client is None:
            try:
                from groq import Groq
                self._groq_client = Groq(
                    api_key=self.config.groq.api_key,
                    timeout=self.config.groq.timeout_seconds,
                )
                logger.info("Groq client initialized")
            except ImportError:
                logger.warning("Groq SDK not installed. Install with: pip install groq")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
                raise
        return self._groq_client

    def _get_cerebras_client(self):
        """Lazily initialize Cerebras client."""
        if self._cerebras_client is None:
            try:
                from cerebras.cloud.sdk import Cerebras
                self._cerebras_client = Cerebras(
                    api_key=self.config.cerebras.api_key,
                    timeout=self.config.cerebras.timeout_seconds,
                )
                logger.info("Cerebras client initialized")
            except ImportError:
                logger.warning("Cerebras SDK not installed. Install with: pip install cerebras-cloud-sdk")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Cerebras client: {e}")
                raise
        return self._cerebras_client

    def _get_openrouter_client(self):
        """Lazily initialize OpenRouter client (OpenAI-compatible)."""
        if self._openrouter_client is None:
            try:
                from openai import OpenAI
                self._openrouter_client = OpenAI(
                    api_key=self.config.openrouter.api_key,
                    base_url=self.config.openrouter.base_url,
                    timeout=self.config.openrouter.timeout_seconds,
                )
                logger.info(f"OpenRouter client initialized (model: {self.config.openrouter.model})")
            except ImportError:
                logger.warning("OpenAI SDK not installed. Install with: pip install openai")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize OpenRouter client: {e}")
                raise
        return self._openrouter_client

    def _get_mistral_client(self):
        """Lazily initialize Mistral client (OpenAI-compatible)."""
        if self._mistral_client is None:
            try:
                from openai import OpenAI
                self._mistral_client = OpenAI(
                    api_key=self.config.mistral.api_key,
                    base_url=self.config.mistral.base_url,
                    timeout=self.config.mistral.timeout_seconds,
                )
                logger.info(f"Mistral client initialized (model: {self.config.mistral.model})")
            except ImportError:
                logger.warning("OpenAI SDK not installed for Mistral. Install with: pip install openai")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Mistral client: {e}")
                raise
        return self._mistral_client

    # ----------------------------------------------------------
    # PROVIDER RESOLUTION
    # ----------------------------------------------------------

    def _resolve_provider(self, task: str) -> AIProvider:
        """Determine which provider should handle this task.
        PRISM v0.1: Uses PRISM_TASK_ROUTING table first, falls back to legacy."""
        # PRISM routing table has highest priority
        prism_provider = PRISM_TASK_ROUTING.get(task)
        if prism_provider:
            provider_map = {
                'cerebras': AIProvider.CEREBRAS,
                'groq': AIProvider.GROQ,
                'openrouter': AIProvider.OPENROUTER,
                'groq_compound': AIProvider.GROQ_COMPOUND,
                'mistral': AIProvider.MISTRAL,
            }
            return provider_map.get(prism_provider, AIProvider.CEREBRAS)

        # Legacy task sets as fallback
        if task in CEREBRAS_TASKS:
            return AIProvider.CEREBRAS
        elif task in GROQ_TASKS:
            return AIProvider.GROQ
        elif task in OPENROUTER_TASKS:
            return AIProvider.OPENROUTER
        elif task in GROQ_COMPOUND_TASKS:
            return AIProvider.GROQ_COMPOUND
        elif task in MISTRAL_TASKS:
            return AIProvider.MISTRAL
        else:
            # Default: classify/extract -> Cerebras, generate/analyze -> Groq
            category = TASK_CATEGORIES.get(task)
            if category in (TaskCategory.CLASSIFICATION, TaskCategory.EXTRACTION,
                            TaskCategory.SCORING, TaskCategory.PARSING):
                return AIProvider.CEREBRAS
            else:
                return AIProvider.GROQ

    def _get_fallback_providers(self, primary: AIProvider) -> List[AIProvider]:
        """Get the fallback provider chain using PRISM_FAILOVER_CHAIN.
        Returns ordered list of fallback providers."""
        chain = PRISM_FAILOVER_CHAIN.get(primary.value, [])
        provider_map = {
            'cerebras': AIProvider.CEREBRAS,
            'groq': AIProvider.GROQ,
            'openrouter': AIProvider.OPENROUTER,
            'groq_compound': AIProvider.GROQ_COMPOUND,
            'mistral': AIProvider.MISTRAL,
        }
        return [provider_map[p] for p in chain if p in provider_map]

    def _get_fallback_provider(self, primary: AIProvider) -> AIProvider:
        """Get the first fallback provider (legacy compat)."""
        fallbacks = self._get_fallback_providers(primary)
        return fallbacks[0] if fallbacks else AIProvider.MISTRAL

    def _get_limiter(self, provider: AIProvider) -> RateLimiter:
        limiter_map = {
            AIProvider.GROQ: self._groq_limiter,
            AIProvider.CEREBRAS: self._cerebras_limiter,
            AIProvider.OPENROUTER: self._openrouter_limiter,
            AIProvider.GROQ_COMPOUND: self._groq_compound_limiter,
            AIProvider.MISTRAL: self._mistral_limiter,
        }
        return limiter_map.get(provider, self._cerebras_limiter)

    def _get_circuit(self, provider: AIProvider) -> CircuitBreaker:
        circuit_map = {
            AIProvider.GROQ: self._groq_circuit,
            AIProvider.CEREBRAS: self._cerebras_circuit,
            AIProvider.OPENROUTER: self._openrouter_circuit,
            AIProvider.GROQ_COMPOUND: self._groq_compound_circuit,
            AIProvider.MISTRAL: self._mistral_circuit,
        }
        return circuit_map.get(provider, self._cerebras_circuit)

    # ----------------------------------------------------------
    # CORE API CALL
    # ----------------------------------------------------------

    def _call_provider(self, provider: AIProvider, prompt: str,
                       task: str, max_tokens: int,
                       temperature: float,
                       system_prompt: Optional[str] = None) -> AIResponse:
        """Make a synchronous API call to any of 5 providers."""
        start_time = time.time()

        # Resolve model for each provider
        model_map = {
            AIProvider.GROQ: self.config.groq.model,
            AIProvider.CEREBRAS: self.config.cerebras.model,
            AIProvider.OPENROUTER: self.config.openrouter.model,
            AIProvider.GROQ_COMPOUND: self.config.groq_compound.model,
            AIProvider.MISTRAL: self.config.mistral.model,
        }
        model = model_map.get(provider, self.config.cerebras.model)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            if provider == AIProvider.GROQ:
                client = self._get_groq_client()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            elif provider == AIProvider.CEREBRAS:
                client = self._get_cerebras_client()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            elif provider == AIProvider.OPENROUTER:
                client = self._get_openrouter_client()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            elif provider == AIProvider.GROQ_COMPOUND:
                # Groq Compound Beta uses same client as Groq, different model
                client = self._get_groq_client()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            elif provider == AIProvider.MISTRAL:
                client = self._get_mistral_client()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                raise ValueError(f"Unknown provider: {provider}")

            latency_ms = (time.time() - start_time) * 1000
            content = resp.choices[0].message.content if resp.choices else ""
            usage = getattr(resp, 'usage', None)
            prompt_tokens = getattr(usage, 'prompt_tokens', 0) if usage else 0
            completion_tokens = getattr(usage, 'completion_tokens', 0) if usage else 0
            total_tokens = prompt_tokens + completion_tokens

            return AIResponse(
                content=content,
                provider=provider.value,
                model=model,
                task=task,
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round(latency_ms, 1),
                success=True,
                timestamp=datetime.now(IST).isoformat(),
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            logger.error(f"AI call failed ({provider.value}/{task}): {error_msg}")

            return AIResponse(
                provider=provider.value,
                model=model,
                task=task,
                latency_ms=round(latency_ms, 1),
                error=error_msg,
                success=False,
                timestamp=datetime.now(IST).isoformat(),
            )

    # ----------------------------------------------------------
    # MAIN ROUTING METHOD
    # ----------------------------------------------------------

    def call(self, task: str, prompt: str,
             max_tokens: Optional[int] = None,
             temperature: Optional[float] = None,
             system_prompt: Optional[str] = None,
             use_cache: bool = True,
             force_provider: Optional[AIProvider] = None) -> AIResponse:
        """
        Route an AI task to the optimal provider.

        Args:
            task: Task name (e.g., 'ghost_classify', 'cover_letter')
            prompt: The prompt text
            max_tokens: Override max tokens (default from config)
            temperature: Override temperature (default from config)
            system_prompt: Optional system prompt
            use_cache: Whether to use response cache
            force_provider: Force a specific provider

        Returns:
            AIResponse with the result
        """
        # Check cache first
        if use_cache:
            cached = self._cache.get(task, prompt)
            if cached:
                logger.debug(f"Cache hit for task={task}")
                return cached

        # Resolve parameters
        if max_tokens is None:
            max_tokens = TASK_MAX_TOKENS_MAP.get(task, 500)
        if temperature is None:
            temperature = TASK_TEMPERATURE_MAP.get(task, 0.3)

        # Resolve provider
        primary = force_provider or self._resolve_provider(task)
        fallbacks = self._get_fallback_providers(primary)

        # Try primary provider
        response = self._try_provider(
            primary, task, prompt, max_tokens, temperature, system_prompt
        )

        if response.success:
            # Cache successful response
            if use_cache:
                self._cache.put(task, prompt, response)
            self._record_success(primary, task, response)
            return response

        # Primary failed — try fallback chain (PRISM: up to 2 fallbacks)
        for i, fallback in enumerate(fallbacks):
            logger.warning(
                f"Provider {primary.value} failed for {task}, "
                f"trying fallback #{i+1}: {fallback.value}"
            )
            self._fallback_count += 1

            response = self._try_provider(
                fallback, task, prompt, max_tokens, temperature, system_prompt
            )
            response.fallback_used = True

            if response.success:
                if use_cache:
                    self._cache.put(task, prompt, response)
                self._record_success(fallback, task, response)
                return response

        # All providers failed
        self._total_errors += 1
        logger.error(
            f"All providers failed for task={task} "
            f"(tried: {primary.value} + {[f.value for f in fallbacks]})"
        )

        return response

    def _is_provider_configured(self, provider: AIProvider) -> bool:
        """Check if a provider has valid API keys configured."""
        if provider == AIProvider.GROQ:
            return bool(self.config.groq.api_key)
        elif provider == AIProvider.CEREBRAS:
            return bool(self.config.cerebras.api_key)
        elif provider == AIProvider.OPENROUTER:
            return bool(self.config.openrouter.api_key)
        elif provider == AIProvider.GROQ_COMPOUND:
            # Uses Groq's API key
            return bool(self.config.groq.api_key)
        elif provider == AIProvider.MISTRAL:
            return bool(self.config.mistral.api_key)
        return False

    def _try_provider(self, provider: AIProvider, task: str,
                      prompt: str, max_tokens: int,
                      temperature: float,
                      system_prompt: Optional[str]) -> AIResponse:
        """Try to call a provider with rate limiting and circuit breaking."""
        # PRISM v0.1 FIX: Skip providers that have no API key configured
        if not self._is_provider_configured(provider):
            return AIResponse(
                provider=provider.value,
                task=task,
                error=f"Provider {provider.value} not configured (API key missing)",
                success=False,
            )

        limiter = self._get_limiter(provider)
        circuit = self._get_circuit(provider)

        # Check circuit breaker
        if not circuit.can_call():
            return AIResponse(
                provider=provider.value,
                task=task,
                error=f"Circuit breaker open for {provider.value}",
                success=False,
            )

        # Check rate limit
        if not limiter.can_call():
            wait = limiter.wait_time()
            if wait > 0 and wait < 5:
                time.sleep(wait)
            elif wait >= 5:
                return AIResponse(
                    provider=provider.value,
                    task=task,
                    error=f"Rate limited ({provider.value}), wait {wait:.1f}s",
                    success=False,
                )

        # Make the call with retries
        max_retries = (self.config.groq.retry_attempts if provider == AIProvider.GROQ
                       else self.config.cerebras.retry_attempts)
        base_delay = (self.config.groq.retry_base_delay if provider == AIProvider.GROQ
                      else self.config.cerebras.retry_base_delay)

        last_response = None
        for attempt in range(max_retries):
            limiter.record_call()
            response = self._call_provider(
                provider, prompt, task, max_tokens, temperature, system_prompt
            )
            response.retry_count = attempt

            if response.success:
                circuit.record_success()
                return response

            last_response = response
            circuit.record_failure()

            # Exponential backoff
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.debug(f"Retry {attempt + 1}/{max_retries} for {provider.value}/{task}, waiting {delay}s")
                time.sleep(delay)

        return last_response or AIResponse(
            provider=provider.value, task=task,
            error="Max retries exceeded", success=False
        )

    def _record_success(self, provider: AIProvider, task: str,
                        response: AIResponse):
        """Record successful call stats."""
        self._total_calls += 1
        self._total_tokens += response.tokens_used
        self._provider_calls[provider.value] += 1
        self._task_calls[task] += 1

        # Record to database
        try:
            db = get_db()
            db.record_api_usage(
                provider=provider.value,
                requests=1,
                tokens=response.tokens_used,
            )
        except Exception as e:
            logger.debug(f"Failed to record API usage to DB: {e}")

    # ----------------------------------------------------------
    # CONVENIENCE METHODS FOR SPECIFIC TASKS
    # ----------------------------------------------------------

    def classify_ghost(self, listing: Dict) -> AIResponse:
        """Classify a listing as ghost/not ghost."""
        prompt = PROMPT_TEMPLATES['ghost_classify'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            posted_days_ago=listing.get('posted_days_ago', 0),
            applicants=listing.get('applicants', 0),
            stipend=listing.get('stipend', ''),
            source=listing.get('source', ''),
        )
        return self.call('ghost_classify', prompt)

    def classify_intent(self, text: str, source: str = "") -> AIResponse:
        """Classify text as hiring intent signal."""
        prompt = PROMPT_TEMPLATES['intent_classify'].format(
            text=text,
            source=source,
        )
        return self.call('intent_classify', prompt)

    def extract_listing(self, content: str) -> AIResponse:
        """Extract structured listing data from HTML/text."""
        prompt = PROMPT_TEMPLATES['extract_basics'].format(content=content)
        return self.call('extract_basics', prompt)

    def score_dedup(self, listing_a: Dict, listing_b: Dict) -> AIResponse:
        """Score deduplication between two listings."""
        prompt = PROMPT_TEMPLATES['dedup_score'].format(
            title_a=listing_a.get('title', ''),
            company_a=listing_a.get('company', ''),
            location_a=listing_a.get('location', ''),
            stipend_a=listing_a.get('stipend', ''),
            source_a=listing_a.get('source', ''),
            desc_a=listing_a.get('description_text', '')[:500],
            title_b=listing_b.get('title', ''),
            company_b=listing_b.get('company', ''),
            location_b=listing_b.get('location', ''),
            stipend_b=listing_b.get('stipend', ''),
            source_b=listing_b.get('source', ''),
            desc_b=listing_b.get('description_text', '')[:500],
        )
        return self.call('dedup_score', prompt)

    def parse_internshala(self, html: str) -> AIResponse:
        """Parse Internshala listing HTML."""
        prompt = PROMPT_TEMPLATES['internshala_parse'].format(html=html[:3000])
        return self.call('internshala_parse', prompt)

    def tag_sector(self, company_name: str,
                   additional_info: str = "") -> AIResponse:
        """Classify company sector and tier."""
        prompt = PROMPT_TEMPLATES['sector_tag'].format(
            company_name=company_name,
            additional_info=additional_info,
        )
        return self.call('sector_tag', prompt)

    def classify_dark_message(self, message: str, channel_name: str,
                              channel_type: str = "telegram") -> AIResponse:
        """Classify a dark channel message as job/not job."""
        prompt = PROMPT_TEMPLATES['dark_classify'].format(
            message=message[:2000],
            channel_name=channel_name,
            channel_type=channel_type,
        )
        return self.call('dark_classify', prompt)

    def score_signal(self, company: str, signal_text: str,
                     signal_type: str, source: str) -> AIResponse:
        """Score a hiring intent signal."""
        prompt = PROMPT_TEMPLATES['signal_score'].format(
            company=company,
            signal_text=signal_text[:1000],
            signal_type=signal_type,
            source=source,
        )
        return self.call('signal_score', prompt)

    def generate_cover_letter(self, listing: Dict,
                              profile: Dict) -> AIResponse:
        """Generate a tailored cover letter."""
        prompt = PROMPT_TEMPLATES['cover_letter'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            location=listing.get('location', ''),
            description=listing.get('description_text', '')[:2000],
            college=profile.get('college', 'a top MBA program'),
            specialization=profile.get('specialization', 'Marketing & Strategy'),
            skills=', '.join(profile.get('skills', ['analytical skills', 'communication'])),
            experience=profile.get('experience', 'prior internship experience'),
        )
        return self.call('cover_letter', prompt, use_cache=False)

    def simulate_ats(self, jd_text: str, resume_text: str) -> AIResponse:
        """Run ATS simulation."""
        prompt = PROMPT_TEMPLATES['ats_simulation'].format(
            jd_text=jd_text[:3000],
            resume_text=resume_text[:3000],
        )
        return self.call('ats_simulation', prompt, use_cache=False)

    def tweak_resume(self, listing: Dict, resume_bullets: str,
                     missing_keywords: List[str]) -> AIResponse:
        """Generate resume tweaks."""
        prompt = PROMPT_TEMPLATES['resume_tweaks'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            jd_text=listing.get('description_text', '')[:2000],
            resume_bullets=resume_bullets[:2000],
            missing_keywords=', '.join(missing_keywords),
        )
        return self.call('resume_tweaks', prompt, use_cache=False)

    def analyze_jd(self, listing: Dict) -> AIResponse:
        """Analyze a job description."""
        prompt = PROMPT_TEMPLATES['jd_analysis'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            jd_text=listing.get('description_text', '')[:3000],
        )
        return self.call('jd_analysis', prompt)

    def draft_outreach(self, person: Dict, candidate: Dict,
                       company: str) -> AIResponse:
        """Generate an outreach message."""
        prompt = PROMPT_TEMPLATES['outreach_draft'].format(
            person_name=person.get('name', ''),
            person_role=person.get('current_role', ''),
            company=company,
            connection_type=person.get('connection_type', 'alumni'),
            shared_college=person.get('college', ''),
            candidate_name=candidate.get('name', ''),
            candidate_college=candidate.get('college', ''),
            target_role=candidate.get('target_role', 'MBA Intern'),
        )
        return self.call('outreach_draft', prompt, use_cache=False)

    def research_company(self, company: str, sector: str = "",
                         news_items: str = "", glassdoor_rating: float = 0,
                         signals: str = "") -> AIResponse:
        """Generate company research brief."""
        prompt = PROMPT_TEMPLATES['company_research'].format(
            company=company,
            sector=sector,
            news_items=news_items[:2000],
            glassdoor_rating=glassdoor_rating,
            signals=signals[:1000],
        )
        return self.call('company_research', prompt)

    def compile_report(self, report_type: str, data: str) -> AIResponse:
        """Compile a Telegram report."""
        prompt = PROMPT_TEMPLATES['report_compile'].format(
            report_type=report_type,
            date=datetime.now(IST).strftime("%Y-%m-%d"),
            data=data[:4000],
        )
        return self.call('report_compile', prompt, use_cache=False)

    def generate_package(self, listing: Dict, profile: Dict,
                         alumni_info: str = "") -> AIResponse:
        """Generate complete application package."""
        prompt = PROMPT_TEMPLATES['package_generate'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            jd_text=listing.get('description_text', '')[:2000],
            profile=json.dumps(profile, indent=2)[:1500],
            alumni_info=alumni_info[:500],
        )
        return self.call('package_generate', prompt, use_cache=False)

    # ----------------------------------------------------------
    # v7.0 NEW CONVENIENCE METHODS
    # ----------------------------------------------------------

    def score_listing_quality(self, listing: Dict) -> AIResponse:
        """v7.0: AI quality scoring for a listing."""
        prompt = PROMPT_TEMPLATES['listing_quality_score'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            location=listing.get('location', ''),
            stipend=listing.get('stipend', 'N/A'),
            duration=listing.get('duration', 'N/A'),
            source=listing.get('source', ''),
            applicants=listing.get('applicants', 0),
            is_ppo=listing.get('is_ppo', False),
            description=listing.get('description_text', '')[:500],
        )
        return self.call('listing_quality_score', prompt)

    def deep_parse_jd(self, jd_text: str) -> AIResponse:
        """v7.0: Deep JD parsing — extract 20+ fields."""
        prompt = PROMPT_TEMPLATES['deep_jd_parse'].format(
            jd_text=jd_text[:4000],
        )
        return self.call('deep_jd_parse', prompt, use_cache=False)

    def predict_company_intent(self, company: str, sector: str = "",
                                signals: str = "", news: str = "") -> AIResponse:
        """v7.0: Predict company hiring intent."""
        prompt = PROMPT_TEMPLATES['company_intent_predict'].format(
            company=company,
            sector=sector,
            signals=signals[:1500],
            news=news[:1500],
        )
        return self.call('company_intent_predict', prompt)

    def benchmark_salary(self, listing: Dict) -> AIResponse:
        """v7.0: Benchmark stipend against market."""
        prompt = PROMPT_TEMPLATES['salary_benchmark'].format(
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            category=listing.get('category', ''),
            location=listing.get('location', ''),
            stipend=listing.get('stipend_monthly', listing.get('stipend', 'N/A')),
            tier=listing.get('tier', 3),
        )
        return self.call('salary_benchmark', prompt)

    def detect_anomalies(self, stats: Dict, averages: Dict = None) -> AIResponse:
        """v7.0: Detect anomalies in scraping statistics."""
        prompt = PROMPT_TEMPLATES['anomaly_detect'].format(
            stats=json.dumps(stats, indent=2)[:2000],
            averages=json.dumps(averages or {}, indent=2)[:1000],
        )
        return self.call('anomaly_detect', prompt, use_cache=False)

    def rank_enrichment_priority(self, listings: List[Dict]) -> AIResponse:
        """v7.0: Rank listings by enrichment priority."""
        # Prepare compact listing summaries
        summaries = []
        for i, l in enumerate(listings[:20]):
            summaries.append({
                'id': i,
                'title': l.get('title', '')[:50],
                'company': l.get('company', ''),
                'tier': l.get('tier', 0),
                'enriched': l.get('enriched', False),
                'days_ago': l.get('posted_days_ago', 0),
            })
        prompt = PROMPT_TEMPLATES['enrichment_priority'].format(
            listings=json.dumps(summaries, indent=2),
        )
        return self.call('enrichment_priority', prompt)

    # ----------------------------------------------------------
    # BATCH PROCESSING
    # ----------------------------------------------------------

    def batch_call(self, task: str, prompts: List[str],
                   delay_between: float = 0.5,
                   max_concurrent: int = 1) -> List[AIResponse]:
        """
        Process multiple prompts for the same task sequentially.
        (Free tier doesn't support true concurrent calls well.)
        """
        results = []
        for i, prompt in enumerate(prompts):
            response = self.call(task, prompt)
            results.append(response)
            if i < len(prompts) - 1:
                time.sleep(delay_between)
        return results

    # ----------------------------------------------------------
    # HEALTH & MONITORING
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get comprehensive router health status (PRISM: 5 providers)."""
        return {
            'total_calls': self._total_calls,
            'total_tokens': self._total_tokens,
            'total_errors': self._total_errors,
            'fallback_count': self._fallback_count,
            'provider_calls': dict(self._provider_calls),
            'groq': {
                'rate_limiter': self._groq_limiter.get_usage(),
                'circuit_breaker': self._groq_circuit.get_status(),
                'api_key_set': bool(self.config.groq.api_key),
            },
            'cerebras': {
                'rate_limiter': self._cerebras_limiter.get_usage(),
                'circuit_breaker': self._cerebras_circuit.get_status(),
                'api_key_set': bool(self.config.cerebras.api_key),
            },
            'openrouter': {
                'rate_limiter': self._openrouter_limiter.get_usage(),
                'circuit_breaker': self._openrouter_circuit.get_status(),
                'api_key_set': bool(self.config.openrouter.api_key),
            },
            'groq_compound': {
                'rate_limiter': self._groq_compound_limiter.get_usage(),
                'circuit_breaker': self._groq_compound_circuit.get_status(),
                'api_key_set': bool(self.config.groq.api_key),  # uses same key
            },
            'mistral': {
                'rate_limiter': self._mistral_limiter.get_usage(),
                'circuit_breaker': self._mistral_circuit.get_status(),
                'api_key_set': bool(self.config.mistral.api_key),
            },
            'cache': self._cache.get_stats(),
            'top_tasks': dict(sorted(
                self._task_calls.items(),
                key=lambda x: x[1], reverse=True
            )[:10]),
        }

    def get_quota_report(self) -> str:
        """Generate a human-readable quota report for all 5 PRISM providers."""
        health = self.get_health()
        groq_usage = health['groq']['rate_limiter']
        cerebras_usage = health['cerebras']['rate_limiter']
        openrouter_usage = health['openrouter']['rate_limiter']
        groq_compound_usage = health['groq_compound']['rate_limiter']
        mistral_usage = health['mistral']['rate_limiter']

        # SerpAPI stats
        from core.config import get_config
        config = get_config()
        serp_key_set = bool(config.serpapi.api_key)

        report = (
            f"📊 <b>PRISM v0.1 API Quota Report</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🤖 <b>Groq 70B</b> (PRIMARY DEEP)\n"
            f"  Day: {groq_usage['day']}/{groq_usage['day_limit']} ({groq_usage['day_pct']}%)\n"
            f"  Circuit: {health['groq']['circuit_breaker']['state']}\n\n"
            f"⚡ <b>Cerebras 8B</b> (PRIMARY FAST)\n"
            f"  Day: {cerebras_usage['day']}/{cerebras_usage['day_limit']} ({cerebras_usage['day_pct']}%)\n"
            f"  Circuit: {health['cerebras']['circuit_breaker']['state']}\n\n"
            f"🌐 <b>OpenRouter</b> (PRIMARY LONG — 1M ctx)\n"
            f"  Day: {openrouter_usage['day']}/{openrouter_usage['day_limit']} ({openrouter_usage['day_pct']}%)\n"
            f"  Circuit: {health['openrouter']['circuit_breaker']['state']}\n"
            f"  Key: {'✅' if health['openrouter']['api_key_set'] else '❌'}\n\n"
            f"🔬 <b>Groq Compound</b> (AGENTIC — web search)\n"
            f"  Day: {groq_compound_usage['day']}/{groq_compound_usage['day_limit']} ({groq_compound_usage['day_pct']}%)\n"
            f"  Circuit: {health['groq_compound']['circuit_breaker']['state']}\n\n"
            f"🛡️ <b>Mistral</b> (FALLBACK)\n"
            f"  Day: {mistral_usage['day']}/{mistral_usage['day_limit']} ({mistral_usage['day_pct']}%)\n"
            f"  Circuit: {health['mistral']['circuit_breaker']['state']}\n"
            f"  Key: {'✅' if health['mistral']['api_key_set'] else '❌'}\n\n"
            f"🔍 <b>SerpAPI</b> {'✅' if serp_key_set else '❌ No Key'}\n\n"
            f"📈 <b>Session Stats</b>\n"
            f"  Total AI calls: {health['total_calls']}\n"
            f"  Total tokens: {health['total_tokens']}\n"
            f"  Errors: {health['total_errors']}\n"
            f"  Fallbacks: {health['fallback_count']}\n"
            f"  Cache hit rate: {health['cache']['hit_rate']}%\n"
        )
        return report


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

def get_router() -> AIRouter:
    """Get the singleton AIRouter instance."""
    return AIRouter()


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PRISM v0.1 — AI Router Test (5 Providers)")
    print("=" * 60)

    router = get_router()
    health = router.get_health()

    print(f"\nRouter Health:")
    for provider_name in ['groq', 'cerebras', 'openrouter', 'groq_compound', 'mistral']:
        prov = health.get(provider_name, {})
        key_set = '✅ Set' if prov.get('api_key_set') else '❌ Missing'
        circuit = prov.get('circuit_breaker', {}).get('state', 'N/A')
        print(f"  {provider_name}: Key={key_set}, Circuit={circuit}")

    print(f"\nCache: {health['cache']['size']}/{health['cache']['max_size']}")
    print(f"\nTask Routing (PRISM):")
    print(f"  PRISM routing table: {len(PRISM_TASK_ROUTING)} tasks")
    print(f"  Cerebras tasks: {len(CEREBRAS_TASKS)}")
    print(f"  Groq tasks: {len(GROQ_TASKS)}")
    print(f"  OpenRouter tasks: {len(OPENROUTER_TASKS)}")
    print(f"  Groq Compound tasks: {len(GROQ_COMPOUND_TASKS)}")
    print(f"  Mistral tasks: {len(MISTRAL_TASKS)}")
    print(f"  Prompt templates: {len(PROMPT_TEMPLATES)}")
    print(f"\n{router.get_quota_report()}")
    print("=" * 60)
