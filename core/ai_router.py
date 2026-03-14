"""
============================================================
OPERATION FIRST MOVER v8.0 -- AI MULTI-MODEL ROUTER (A-14)
============================================================
The brain of the system. Routes AI requests to the optimal provider
with automatic fallback, health probing, and rate limit management.

Architecture (v8.0 Blueprint):
    - 5 AI Providers: Groq, Cerebras, Mistral, OpenRouter, HuggingFace
    - 2 Fallbacks per agent via Agent Fallback Matrix
    - Layer 4 Health Probe: 5-token test call before dispatch
    - Automatic failover on 429/500/timeout
    - Token budget tracking per provider
    - Task-specific temperature and max_tokens from config

Provider Summary (March 2026 verified):
    Groq:        llama-3.3-70b-versatile, 30 RPM, 14400 req/day
    Cerebras:    llama3.1-8b, 1M tokens/day, 60 RPM
    Mistral:     mistral-small-latest, Experiment plan
    OpenRouter:  google/gemini-2.0-flash-exp:free, 50 req/day
    HuggingFace: Mistral-7B-Instruct-v0.2, rate limited

Usage:
    router = AIRouter()
    response = await router.query(
        agent_id='A-07',
        task='jd_analysis',
        prompt='Analyze this JD...',
        system_prompt='You are an MBA career advisor...'
    )
============================================================
"""

import os
import json
import time
import asyncio
import logging
import traceback
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not installed. Using requests fallback.")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from core.config import (
    get_config, now_ist, IST,
    AGENT_FALLBACK_MATRIX,
    TASK_TEMPERATURE_MAP,
    TASK_MAX_TOKENS_MAP,
    AIProviderStatus,
)


# ============================================================
# SECTION 1: PROVIDER ADAPTERS
# ============================================================

class BaseProvider:
    """Base class for AI provider adapters."""

    def __init__(self, name: str, api_key: str, base_url: str,
                 model: str, fallback_model: str = "",
                 timeout: int = 60, max_retries: int = 3):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.fallback_model = fallback_model or model
        self.timeout = timeout
        self.max_retries = max_retries
        self.status = AIProviderStatus(provider=name)
        self._http_client = None

    @property
    def is_available(self) -> bool:
        """Check if provider has API key and is healthy."""
        return bool(self.api_key) and self.status.is_healthy

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers for this provider."""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    def _build_payload(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.3, max_tokens: int = 500,
                       model: Optional[str] = None) -> Dict[str, Any]:
        """Build the request payload in OpenAI-compatible format."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

    def _parse_response(self, response_data: Dict[str, Any]) -> Tuple[str, int]:
        """Parse the response and extract text and token count."""
        try:
            text = response_data['choices'][0]['message']['content']
            tokens = response_data.get('usage', {}).get('total_tokens', 0)
            return text.strip(), tokens
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse {self.name} response: {e}")
            return "", 0

    async def query_async(self, prompt: str, system_prompt: str = "",
                          temperature: float = 0.3, max_tokens: int = 500,
                          model: Optional[str] = None) -> Tuple[str, int, bool]:
        """Make an async API call to this provider.

        Returns:
            Tuple of (response_text, tokens_used, success)
        """
        if not self.is_available:
            return "", 0, False

        headers = self._get_headers()
        payload = self._build_payload(prompt, system_prompt, temperature,
                                      max_tokens, model)
        url = f"{self.base_url}/chat/completions"

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                if HTTPX_AVAILABLE:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.post(url, headers=headers,
                                                     json=payload)
                else:
                    # Sync fallback
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: requests.post(url, headers=headers,
                                              json=payload, timeout=self.timeout)
                    )

                elapsed = time.time() - start_time

                if response.status_code == 200:
                    data = response.json()
                    text, tokens = self._parse_response(data)
                    self.status.record_success()
                    self.status.total_tokens_today += tokens
                    logger.debug(
                        f"[{self.name}] OK ({elapsed:.1f}s, {tokens} tokens)"
                    )
                    return text, tokens, True

                elif response.status_code == 429:
                    # Rate limited
                    self.status.record_rate_limit()
                    retry_after = int(response.headers.get('retry-after', '5'))
                    logger.warning(
                        f"[{self.name}] Rate limited (429). "
                        f"Retry after {retry_after}s"
                    )
                    await asyncio.sleep(retry_after)
                    continue

                elif response.status_code >= 500:
                    self.status.record_error(f"Server error {response.status_code}")
                    logger.warning(
                        f"[{self.name}] Server error {response.status_code}. "
                        f"Attempt {attempt + 1}/{self.max_retries}"
                    )
                    await asyncio.sleep(2 ** attempt)
                    continue

                else:
                    error_text = response.text[:200]
                    self.status.record_error(f"HTTP {response.status_code}: {error_text}")
                    logger.error(
                        f"[{self.name}] HTTP {response.status_code}: {error_text}"
                    )
                    return "", 0, False

            except asyncio.TimeoutError:
                self.status.record_error("Timeout")
                logger.warning(
                    f"[{self.name}] Timeout ({self.timeout}s). "
                    f"Attempt {attempt + 1}/{self.max_retries}"
                )
                continue

            except Exception as e:
                self.status.record_error(str(e))
                logger.error(f"[{self.name}] Error: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

        return "", 0, False

    def query_sync(self, prompt: str, system_prompt: str = "",
                   temperature: float = 0.3, max_tokens: int = 500,
                   model: Optional[str] = None) -> Tuple[str, int, bool]:
        """Synchronous API call (for non-async contexts)."""
        if not self.is_available:
            return "", 0, False

        headers = self._get_headers()
        payload = self._build_payload(prompt, system_prompt, temperature,
                                      max_tokens, model)
        url = f"{self.base_url}/chat/completions"

        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                response = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout
                )
                elapsed = time.time() - start_time

                if response.status_code == 200:
                    data = response.json()
                    text, tokens = self._parse_response(data)
                    self.status.record_success()
                    self.status.total_tokens_today += tokens
                    logger.debug(
                        f"[{self.name}] OK ({elapsed:.1f}s, {tokens} tokens)"
                    )
                    return text, tokens, True

                elif response.status_code == 429:
                    self.status.record_rate_limit()
                    retry_after = int(response.headers.get('retry-after', '5'))
                    logger.warning(f"[{self.name}] Rate limited. Retry in {retry_after}s")
                    time.sleep(retry_after)
                    continue

                elif response.status_code >= 500:
                    self.status.record_error(f"Server error {response.status_code}")
                    time.sleep(2 ** attempt)
                    continue

                else:
                    error_text = response.text[:200]
                    self.status.record_error(f"HTTP {response.status_code}")
                    logger.error(f"[{self.name}] HTTP {response.status_code}: {error_text}")
                    return "", 0, False

            except requests.exceptions.Timeout:
                self.status.record_error("Timeout")
                logger.warning(f"[{self.name}] Timeout. Attempt {attempt + 1}/{self.max_retries}")
                continue
            except Exception as e:
                self.status.record_error(str(e))
                logger.error(f"[{self.name}] Error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

        return "", 0, False


class GroqProvider(BaseProvider):
    """Groq provider -- Primary for heavy reasoning."""
    def __init__(self, config):
        super().__init__(
            name='groq',
            api_key=config.groq.api_key,
            base_url=config.groq.base_url,
            model=config.groq.model,
            fallback_model=config.groq.fallback_model,
            timeout=config.groq.timeout_seconds,
            max_retries=config.groq.retry_attempts,
        )


class CerebrasProvider(BaseProvider):
    """Cerebras provider -- Primary for fast classification."""
    def __init__(self, config):
        super().__init__(
            name='cerebras',
            api_key=config.cerebras.api_key,
            base_url=config.cerebras.base_url,
            model=config.cerebras.model,
            fallback_model=config.cerebras.fallback_model,
            timeout=config.cerebras.timeout_seconds,
            max_retries=config.cerebras.retry_attempts,
        )


class MistralProvider(BaseProvider):
    """Mistral provider -- Fallback #1."""
    def __init__(self, config):
        super().__init__(
            name='mistral',
            api_key=config.mistral.api_key,
            base_url=config.mistral.base_url,
            model=config.mistral.model,
            timeout=config.mistral.timeout_seconds,
            max_retries=config.mistral.retry_attempts,
        )


class OpenRouterProvider(BaseProvider):
    """OpenRouter provider -- Fallback #2."""
    def __init__(self, config):
        super().__init__(
            name='openrouter',
            api_key=config.openrouter.api_key,
            base_url=config.openrouter.base_url,
            model=config.openrouter.model,
            timeout=config.openrouter.timeout_seconds,
            max_retries=config.openrouter.retry_attempts,
        )

    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        headers['HTTP-Referer'] = 'https://github.com/dude699/MBA-AGENT'
        headers['X-Title'] = 'Operation First Mover'
        return headers


class HuggingFaceProvider(BaseProvider):
    """HuggingFace Inference API -- Emergency fallback."""
    def __init__(self, config):
        super().__init__(
            name='huggingface',
            api_key=config.huggingface.api_key,
            base_url=config.huggingface.base_url,
            model=config.huggingface.model,
            timeout=config.huggingface.timeout_seconds,
            max_retries=config.huggingface.retry_attempts,
        )

    def _build_payload(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.3, max_tokens: int = 500,
                       model: Optional[str] = None) -> Dict[str, Any]:
        """HuggingFace uses a different payload format."""
        full_prompt = ""
        if system_prompt:
            full_prompt = f"[INST] {system_prompt}\n\n{prompt} [/INST]"
        else:
            full_prompt = f"[INST] {prompt} [/INST]"

        return {
            "inputs": full_prompt,
            "parameters": {
                "temperature": temperature,
                "max_new_tokens": max_tokens,
                "return_full_text": False,
            }
        }

    def _parse_response(self, response_data: Any) -> Tuple[str, int]:
        """Parse HuggingFace response format."""
        try:
            if isinstance(response_data, list) and response_data:
                text = response_data[0].get('generated_text', '')
                return text.strip(), len(text.split()) * 2  # Approximate tokens
            return "", 0
        except Exception as e:
            logger.error(f"Failed to parse HF response: {e}")
            return "", 0

    async def query_async(self, prompt: str, system_prompt: str = "",
                          temperature: float = 0.3, max_tokens: int = 500,
                          model: Optional[str] = None) -> Tuple[str, int, bool]:
        """Override for HuggingFace-specific endpoint."""
        if not self.is_available:
            return "", 0, False

        headers = self._get_headers()
        payload = self._build_payload(prompt, system_prompt, temperature, max_tokens)
        url = f"{self.base_url}/{model or self.model}"

        try:
            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, json=payload)
            else:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: requests.post(url, headers=headers, json=payload,
                                          timeout=self.timeout)
                )

            if response.status_code == 200:
                data = response.json()
                text, tokens = self._parse_response(data)
                self.status.record_success()
                return text, tokens, True
            else:
                self.status.record_error(f"HTTP {response.status_code}")
                return "", 0, False

        except Exception as e:
            self.status.record_error(str(e))
            return "", 0, False


# ============================================================
# SECTION 2: MULTI-MODEL ROUTER (A-14)
# ============================================================

class AIRouter:
    """
    The Multi-Model AI Router (A-14).
    Routes requests to the optimal provider with automatic fallback.

    Features:
        - 5 provider support with automatic failover
        - Agent Fallback Matrix (2 fallbacks per agent)
        - Layer 4 health probing before dispatch
        - Task-specific temperature and token limits
        - Rate limit tracking and budget management
        - Daily counter resets

    Usage:
        router = AIRouter()
        router.initialize()

        # Async
        response = await router.query(
            agent_id='A-07',
            task='jd_analysis',
            prompt='Analyze this JD...',
        )

        # Sync
        response = router.query_sync(
            agent_id='A-07',
            task='jd_analysis',
            prompt='Analyze this JD...',
        )
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
        self.providers: Dict[str, BaseProvider] = {}
        self._total_requests = 0
        self._total_tokens = 0
        self._total_errors = 0
        self._last_daily_reset = None

    def initialize(self) -> Dict[str, bool]:
        """Initialize all AI providers and return their availability status."""
        self.providers = {
            'groq': GroqProvider(self.config),
            'cerebras': CerebrasProvider(self.config),
            'mistral': MistralProvider(self.config),
            'openrouter': OpenRouterProvider(self.config),
            'huggingface': HuggingFaceProvider(self.config),
        }

        status = {}
        for name, provider in self.providers.items():
            available = provider.is_available
            status[name] = available
            if available:
                logger.info(f"AI Provider [{name}] initialized: {provider.model}")
            else:
                logger.warning(f"AI Provider [{name}] NOT available (no API key)")

        active_count = sum(1 for v in status.values() if v)
        logger.info(f"AI Router initialized: {active_count}/{len(status)} providers active")

        return status

    async def health_probe(self, provider_name: str) -> bool:
        """Layer 4: Health probe with 5-token test call.
        Called before every dispatch to ensure provider is alive."""
        provider = self.providers.get(provider_name)
        if not provider or not provider.is_available:
            return False

        try:
            text, tokens, success = await provider.query_async(
                prompt="Say OK",
                temperature=0.0,
                max_tokens=5,
            )
            if success and text:
                logger.debug(f"Health probe [{provider_name}]: OK")
                return True
            else:
                logger.warning(f"Health probe [{provider_name}]: FAILED (empty response)")
                return False
        except Exception as e:
            logger.warning(f"Health probe [{provider_name}]: FAILED ({e})")
            return False

    def health_probe_sync(self, provider_name: str) -> bool:
        """Synchronous health probe."""
        provider = self.providers.get(provider_name)
        if not provider or not provider.is_available:
            return False
        try:
            text, tokens, success = provider.query_sync(
                prompt="Say OK",
                temperature=0.0,
                max_tokens=5,
            )
            return success and bool(text)
        except Exception:
            return False

    def _get_task_params(self, task: str) -> Tuple[float, int]:
        """Get temperature and max_tokens for a specific task."""
        temperature = TASK_TEMPERATURE_MAP.get(task, 0.3)
        max_tokens = TASK_MAX_TOKENS_MAP.get(task, 500)
        return temperature, max_tokens

    def _get_provider_chain(self, agent_id: str) -> List[str]:
        """Get the ordered provider chain for an agent (primary + fallbacks)."""
        chain = AGENT_FALLBACK_MATRIX.get(
            agent_id,
            ['groq', 'cerebras', 'mistral']  # Default
        )
        # Filter to only available providers
        return [p for p in chain if p in self.providers and self.providers[p].is_available]

    def _check_daily_reset(self):
        """Reset daily counters if new day (IST)."""
        today = now_ist().date()
        if self._last_daily_reset != today:
            for provider in self.providers.values():
                provider.status.reset_daily()
            self._last_daily_reset = today
            logger.info("Daily AI provider counters reset")

    async def query(self, agent_id: str, task: str, prompt: str,
                    system_prompt: str = "",
                    temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None,
                    force_provider: Optional[str] = None,
                    skip_health_probe: bool = False) -> Dict[str, Any]:
        """
        Route an AI query through the provider chain with automatic fallback.

        Args:
            agent_id: The requesting agent (e.g., 'A-07')
            task: The task type (e.g., 'jd_analysis')
            prompt: The user prompt
            system_prompt: Optional system prompt
            temperature: Override task default temperature
            max_tokens: Override task default max_tokens
            force_provider: Force a specific provider (skip chain)
            skip_health_probe: Skip Layer 4 health probe

        Returns:
            Dict with keys: text, provider, tokens, success, error
        """
        self._check_daily_reset()

        # Get task-specific parameters
        task_temp, task_max_tokens = self._get_task_params(task)
        if temperature is None:
            temperature = task_temp
        if max_tokens is None:
            max_tokens = task_max_tokens

        # Get provider chain
        if force_provider:
            chain = [force_provider] if force_provider in self.providers else []
        else:
            chain = self._get_provider_chain(agent_id)

        if not chain:
            logger.error(f"No available providers for {agent_id}/{task}")
            return {
                'text': '',
                'provider': None,
                'tokens': 0,
                'success': False,
                'error': 'No available AI providers',
            }

        # Try each provider in the chain
        last_error = ""
        for provider_name in chain:
            provider = self.providers[provider_name]

            # Layer 4: Health probe (skip for speed-critical tasks)
            if not skip_health_probe and task not in ('quick_classify', 'extract_basics'):
                healthy = await self.health_probe(provider_name)
                if not healthy:
                    logger.warning(
                        f"[{agent_id}] Skipping {provider_name} (health probe failed)"
                    )
                    continue

            # Make the actual query
            logger.debug(
                f"[{agent_id}] Querying {provider_name} for {task} "
                f"(temp={temperature}, max_tokens={max_tokens})"
            )

            text, tokens, success = await provider.query_async(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if success and text:
                self._total_requests += 1
                self._total_tokens += tokens
                return {
                    'text': text,
                    'provider': provider_name,
                    'tokens': tokens,
                    'success': True,
                    'error': '',
                }
            else:
                last_error = f"{provider_name} failed"
                logger.warning(
                    f"[{agent_id}] {provider_name} failed for {task}. "
                    f"Trying next fallback..."
                )
                continue

        # All providers failed
        self._total_errors += 1
        logger.error(f"[{agent_id}] ALL providers failed for {task}")
        return {
            'text': '',
            'provider': None,
            'tokens': 0,
            'success': False,
            'error': f'All providers failed: {last_error}',
        }

    def query_sync(self, agent_id: str, task: str, prompt: str,
                   system_prompt: str = "",
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None,
                   force_provider: Optional[str] = None) -> Dict[str, Any]:
        """
        Synchronous version of query() for non-async contexts.
        Same parameters and return format as query().
        """
        self._check_daily_reset()

        task_temp, task_max_tokens = self._get_task_params(task)
        if temperature is None:
            temperature = task_temp
        if max_tokens is None:
            max_tokens = task_max_tokens

        if force_provider:
            chain = [force_provider] if force_provider in self.providers else []
        else:
            chain = self._get_provider_chain(agent_id)

        if not chain:
            return {
                'text': '', 'provider': None, 'tokens': 0,
                'success': False, 'error': 'No available AI providers',
            }

        last_error = ""
        for provider_name in chain:
            provider = self.providers[provider_name]

            # Sync health probe
            if not self.health_probe_sync(provider_name):
                logger.warning(f"[{agent_id}] Skipping {provider_name} (health probe failed)")
                continue

            text, tokens, success = provider.query_sync(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if success and text:
                self._total_requests += 1
                self._total_tokens += tokens
                return {
                    'text': text, 'provider': provider_name,
                    'tokens': tokens, 'success': True, 'error': '',
                }
            else:
                last_error = f"{provider_name} failed"
                continue

        self._total_errors += 1
        return {
            'text': '', 'provider': None, 'tokens': 0,
            'success': False, 'error': f'All providers failed: {last_error}',
        }

    # ============================================================
    # SECTION 3: SPECIALIZED QUERY METHODS
    # ============================================================

    async def classify(self, agent_id: str, text: str,
                       categories: List[str],
                       task: str = 'quick_classify') -> str:
        """Quick classification of text into categories.
        Optimized for Cerebras (fast, low-cost)."""
        prompt = (
            f"Classify the following text into exactly ONE of these categories: "
            f"{', '.join(categories)}\n\n"
            f"Text: {text}\n\n"
            f"Reply with ONLY the category name, nothing else."
        )
        result = await self.query(
            agent_id=agent_id,
            task=task,
            prompt=prompt,
            temperature=0.0,
            max_tokens=50,
            skip_health_probe=True,
        )
        return result['text'].strip().lower() if result['success'] else ''

    async def score(self, agent_id: str, text: str,
                    criteria: str, task: str = 'dedup_score') -> float:
        """Score text on a 0-100 scale based on criteria.
        Optimized for Cerebras."""
        prompt = (
            f"Score the following on a scale of 0-100 based on: {criteria}\n\n"
            f"Text: {text}\n\n"
            f"Reply with ONLY a number between 0 and 100."
        )
        result = await self.query(
            agent_id=agent_id,
            task=task,
            prompt=prompt,
            temperature=0.0,
            max_tokens=10,
            skip_health_probe=True,
        )
        try:
            return float(result['text'].strip())
        except (ValueError, TypeError):
            return 0.0

    async def analyze(self, agent_id: str, text: str,
                      instruction: str, task: str = 'deep_analysis') -> str:
        """Deep analysis of text. Optimized for Groq (heavy reasoning)."""
        result = await self.query(
            agent_id=agent_id,
            task=task,
            prompt=f"{instruction}\n\n{text}",
            system_prompt="You are an expert MBA career advisor and internship analyst.",
        )
        return result['text'] if result['success'] else ''

    async def generate_cover_letter(self, agent_id: str, job_title: str,
                                    company: str, jd: str,
                                    user_profile: str,
                                    max_words: int = 200) -> str:
        """Generate a tailored cover letter."""
        prompt = (
            f"Write a {max_words}-word cover letter for:\n"
            f"Position: {job_title}\n"
            f"Company: {company}\n"
            f"Job Description: {jd[:1000]}\n\n"
            f"Candidate Profile: {user_profile}\n\n"
            f"Requirements:\n"
            f"- Professional but genuine tone\n"
            f"- Highlight specific skills matching the JD\n"
            f"- Show knowledge of the company\n"
            f"- Keep under {max_words} words\n"
            f"- No generic templates - make it specific"
        )
        result = await self.query(
            agent_id=agent_id,
            task='cover_letter',
            prompt=prompt,
            system_prompt=(
                "You are an expert cover letter writer for MBA students "
                "applying to top companies in India."
            ),
        )
        return result['text'] if result['success'] else ''

    async def answer_screening_question(self, agent_id: str,
                                        question: str,
                                        user_profile: str,
                                        context: str = "") -> str:
        """Answer a screening question using the user's profile."""
        prompt = (
            f"Answer this screening question based on the candidate's profile:\n\n"
            f"Question: {question}\n"
            f"Candidate Profile: {user_profile}\n"
            f"{'Context: ' + context if context else ''}\n\n"
            f"Reply with a natural, concise answer (2-3 sentences max)."
        )
        result = await self.query(
            agent_id=agent_id,
            task='question_answer',
            prompt=prompt,
            system_prompt="You are helping an MBA student answer internship screening questions.",
        )
        return result['text'] if result['success'] else ''

    async def check_mba_relevance(self, title: str, description: str) -> Dict[str, Any]:
        """Check if a listing is MBA-relevant and not a disguised sales role.
        Returns: {is_mba: bool, is_sales: bool, category: str, confidence: float}"""
        prompt = (
            f"Analyze this internship listing:\n"
            f"Title: {title}\n"
            f"Description: {description[:800]}\n\n"
            f"Determine:\n"
            f"1. Is this an MBA-relevant internship? (marketing, finance, strategy, "
            f"consulting, operations, product management, HR, supply chain, analytics, "
            f"data science, AI/ML)\n"
            f"2. Is this actually a SALES role disguised as something else? "
            f"(business development, BDE, SDR, lead generation, cold calling, telecalling)\n"
            f"3. Is this a pure TECH role? (software engineering, web development, devops)\n"
            f"4. Best MBA category if relevant\n\n"
            f"Reply in JSON format:\n"
            f'{{"is_mba": true/false, "is_sales": true/false, "is_tech": true/false, '
            f'"category": "category_name", "confidence": 0.0-1.0, '
            f'"reason": "brief reason"}}'
        )
        result = await self.query(
            agent_id='A-06',
            task='mba_relevance_filter',
            prompt=prompt,
            temperature=0.0,
            max_tokens=200,
            skip_health_probe=True,
        )
        try:
            if result['success']:
                # Try to parse JSON from response
                text = result['text']
                # Find JSON in response
                start = text.find('{')
                end = text.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
            return {'is_mba': False, 'is_sales': False, 'is_tech': False,
                    'category': '', 'confidence': 0.0, 'reason': 'AI analysis failed'}
        except json.JSONDecodeError:
            return {'is_mba': False, 'is_sales': False, 'is_tech': False,
                    'category': '', 'confidence': 0.0, 'reason': 'JSON parse failed'}

    # ============================================================
    # SECTION 4: STATUS & MONITORING
    # ============================================================

    def get_provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all AI providers."""
        status = {}
        for name, provider in self.providers.items():
            s = provider.status
            status[name] = {
                'available': provider.is_available,
                'healthy': s.is_healthy,
                'model': provider.model,
                'requests_today': s.total_requests_today,
                'tokens_today': s.total_tokens_today,
                'errors_today': s.errors_today,
                'rate_limits_today': s.rate_limited_count,
                'consecutive_errors': s.consecutive_errors,
                'last_request': s.last_request_time.isoformat() if s.last_request_time else None,
                'last_error': s.last_error_message,
            }
        return status

    def get_router_stats(self) -> Dict[str, Any]:
        """Get aggregate router statistics."""
        return {
            'total_requests': self._total_requests,
            'total_tokens': self._total_tokens,
            'total_errors': self._total_errors,
            'error_rate': self._total_errors / max(self._total_requests, 1),
            'providers': self.get_provider_status(),
            'active_providers': sum(
                1 for p in self.providers.values() if p.is_available
            ),
            'total_providers': len(self.providers),
        }

    def get_health_summary(self) -> str:
        """Get a human-readable health summary for Telegram reports."""
        lines = ["<b>AI Router Health Report</b>"]
        lines.append(f"Requests today: {self._total_requests}")
        lines.append(f"Tokens used: {self._total_tokens:,}")
        lines.append(f"Errors: {self._total_errors}")
        lines.append("")

        for name, provider in self.providers.items():
            s = provider.status
            emoji = "✅" if provider.is_available and s.is_healthy else "❌"
            lines.append(
                f"{emoji} <b>{name}</b>: "
                f"{s.total_requests_today} req, "
                f"{s.total_tokens_today:,} tok, "
                f"{s.errors_today} err"
            )

        return "\n".join(lines)


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

def get_router() -> AIRouter:
    """Get the singleton AIRouter instance."""
    return AIRouter()


if __name__ == "__main__":
    router = get_router()
    status = router.initialize()
    print("=" * 60)
    print("OPERATION FIRST MOVER v8.0 -- AI Router Status")
    print("=" * 60)
    for provider, available in status.items():
        mark = "OK" if available else "MISSING"
        print(f"  [{mark}] {provider}")
    print("=" * 60)
