"""
NEXUS v0.2 — Layer 1: Stealth Browser Triad
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

The Triad
---------
  Camoufox        → C++ fingerprint spoofing (Firefox 142, coryking fork).
                    ALWAYS the underlying browser context.
  Browser-Use 2.0 → Natural-language reasoning agent.  Used on NEW portals
                    or when the cached Skyvern code fails.
  Skyvern 2.0     → Generates + caches DETERMINISTIC Playwright code on the
                    first AI-mode run, replays the cache on subsequent runs
                    (3s, 0 LLM tokens).  Self-heals on portal layout changes.

Execution Decision Tree
-----------------------
   ┌─────────────────────────────────────────────────────────────┐
   │  start_apply(portal, job, profile)                           │
   ├─────────────────────────────────────────────────────────────┤
   │  1. ensure_camoufox_context(session, fingerprint)            │
   │  2. cached = skyvern.fetch_cache(portal, "apply")            │
   │  3. if cached and cached.fail_streak < N:                    │
   │        → SKYVERN_CODE     (~3s, 0 LLM)                       │
   │     elif portal_just_blocked:                                │
   │        → CAMOUFOX_VIRTUAL (entropy + CF Worker IP rotate)    │
   │     else:                                                    │
   │        → BROWSER_USE_AI   (~30s, Gemini call)                │
   │           ↳ Skyvern observes & crystallises code → cache     │
   │  4. if SKYVERN_CODE fails → fall back to BROWSER_USE_AI      │
   │     and re-cache the regenerated code.                       │
   └─────────────────────────────────────────────────────────────┘

The actual browser-use / skyvern / camoufox imports are guarded so the
module loads cleanly on the 512MB Render dyno where the heavy stack is
not installed.  All real automation runs on the worker dyno that has
`requirements-nexus.txt` installed.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.nexus_config import (
    SKYVERN_CODE_CACHE,
    STACK,
    portal_supported,
)
from core.session_vault import SessionRecord, SessionVault

log = logging.getLogger("nexus.stealth_triad")


# ────────────────────────────────────────────────────────────────────────────
# Strategies
# ────────────────────────────────────────────────────────────────────────────
class ApplyStrategy(str, enum.Enum):
    SKYVERN_CODE       = "skyvern_code"        # cached deterministic code
    BROWSER_USE_AI     = "browser_use_ai"      # NL reasoning agent
    CAMOUFOX_VIRTUAL   = "camoufox_virtual"    # virtual display + entropy + IP rotate


class ApplyOutcome(str, enum.Enum):
    SUCCESS         = "SUCCESS"
    FAILED          = "FAILED"
    CAPTCHA_NEEDED  = "CAPTCHA_NEEDED"
    PORTAL_BLOCKED  = "PORTAL_BLOCKED"


@dataclass
class ApplyResult:
    outcome:        ApplyOutcome
    strategy_used:  ApplyStrategy
    duration_ms:    int
    skyvern_cached: bool = False
    captcha_tier:   str | None = None
    error:          str | None = None
    artefacts:      dict[str, Any] = field(default_factory=dict)


@dataclass
class ApplyContext:
    portal:         str
    job_id:         str
    job_url:        str
    profile:        dict[str, Any]
    answers:        dict[str, str] = field(default_factory=dict)
    resume_path:    str | None = None
    portal_blocked: bool = False         # set by Risk Governor


# ────────────────────────────────────────────────────────────────────────────
# Skyvern code cache facade
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class CachedCode:
    code_blob:     str
    code_hash:     str
    success_count: int
    fail_count:    int
    fail_streak:   int


class SkyvernCodeCacheRepo:
    """Duck-typed wrapper around the Supabase `skyvern_code_cache` table."""

    def __init__(self, db):
        self.db = db

    async def fetch(self, portal: str, task_kind: str = "apply") -> CachedCode | None:
        return await self.db.fetch_skyvern_cache(portal, task_kind)

    async def store(
        self,
        portal: str,
        task_kind: str,
        code_blob: str,
        success: bool,
    ) -> None:
        await self.db.upsert_skyvern_cache(
            portal=portal, task_kind=task_kind,
            code_blob=code_blob, success=success,
        )

    async def record_outcome(
        self, portal: str, task_kind: str, success: bool
    ) -> None:
        await self.db.record_skyvern_outcome(portal, task_kind, success)


# ────────────────────────────────────────────────────────────────────────────
# Adapter protocol — keeps the heavy deps optional.
# ────────────────────────────────────────────────────────────────────────────
class StealthAdapter:
    """
    Concrete adapters live in agents/n01_skyvern_apply.py and
    agents/n02_browser_use_apply.py.  This module is the orchestrator.
    """

    async def run_skyvern_code(
        self, ctx: ApplyContext, session: SessionRecord, code_blob: str
    ) -> ApplyResult:
        raise NotImplementedError

    async def run_browser_use(
        self, ctx: ApplyContext, session: SessionRecord
    ) -> tuple[ApplyResult, str]:
        """Returns (result, generated_playwright_code) — second item cached on success."""
        raise NotImplementedError

    async def run_camoufox_virtual(
        self, ctx: ApplyContext, session: SessionRecord
    ) -> ApplyResult:
        raise NotImplementedError


# ────────────────────────────────────────────────────────────────────────────
# Stealth Triad — the orchestrator
# ────────────────────────────────────────────────────────────────────────────
class StealthTriad:
    def __init__(
        self,
        vault:    SessionVault,
        cache:    SkyvernCodeCacheRepo,
        adapter:  StealthAdapter,
        on_event: Callable[[str, dict], Awaitable[None]] | None = None,
    ):
        self.vault    = vault
        self.cache    = cache
        self.adapter  = adapter
        self.on_event = on_event or (lambda *_: asyncio.sleep(0))

    # ---- main entry --------------------------------------------------------
    async def execute(self, ctx: ApplyContext) -> ApplyResult:
        if not portal_supported(ctx.portal):
            return ApplyResult(
                outcome=ApplyOutcome.FAILED,
                strategy_used=ApplyStrategy.BROWSER_USE_AI,
                duration_ms=0,
                error=f"unsupported portal {ctx.portal!r}",
            )

        session = await self.vault.load(ctx.portal)
        strategy = await self._choose_strategy(ctx)
        log.info("triad.dispatch portal=%s job=%s strategy=%s",
                 ctx.portal, ctx.job_id, strategy.value)
        await self.on_event("apply_start", {
            "portal": ctx.portal, "job_id": ctx.job_id, "strategy": strategy.value,
        })

        t0 = time.monotonic()
        try:
            result = await self._run(strategy, ctx, session)
        except Exception as e:                                # noqa: BLE001
            log.exception("triad.exec_crash portal=%s err=%s", ctx.portal, e)
            result = ApplyResult(
                outcome=ApplyOutcome.FAILED,
                strategy_used=strategy,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error=f"crash:{type(e).__name__}:{e}",
            )

        # If cached code path failed → fall back to Browser-Use & re-cache.
        if (result.outcome == ApplyOutcome.FAILED
                and strategy == ApplyStrategy.SKYVERN_CODE):
            log.warning(
                "triad.cache_fallback portal=%s — Skyvern code failed, "
                "rerunning Browser-Use AI",
                ctx.portal,
            )
            await self.cache.record_outcome(ctx.portal, "apply", success=False)
            ctx.portal_blocked = False
            fallback_strategy = ApplyStrategy.BROWSER_USE_AI
            await self.on_event("apply_fallback", {
                "portal": ctx.portal, "from": strategy.value, "to": fallback_strategy.value,
            })
            result = await self._run(fallback_strategy, ctx, session)

        # Update session health based on outcome
        await self.vault.mark_used(
            session,
            success=(result.outcome == ApplyOutcome.SUCCESS),
            encountered_captcha=(result.outcome == ApplyOutcome.CAPTCHA_NEEDED),
        )
        await self.on_event("apply_done", {
            "portal":   ctx.portal,
            "job_id":   ctx.job_id,
            "outcome":  result.outcome.value,
            "duration": result.duration_ms,
            "strategy": result.strategy_used.value,
        })
        return result

    # ---- strategy selector -------------------------------------------------
    async def _choose_strategy(self, ctx: ApplyContext) -> ApplyStrategy:
        if ctx.portal_blocked:
            return ApplyStrategy.CAMOUFOX_VIRTUAL

        cached = await self.cache.fetch(ctx.portal, "apply")
        if cached is None:
            return ApplyStrategy.BROWSER_USE_AI

        cfg = SKYVERN_CODE_CACHE
        if cached.fail_streak >= cfg["fail_streak_invalidate"]:
            log.info("triad.cache_invalidated portal=%s fail_streak=%s",
                     ctx.portal, cached.fail_streak)
            return ApplyStrategy.BROWSER_USE_AI

        if cached.success_count < cfg["min_success_before_cache_use"]:
            return ApplyStrategy.BROWSER_USE_AI

        return ApplyStrategy.SKYVERN_CODE

    # ---- runners -----------------------------------------------------------
    async def _run(
        self,
        strategy: ApplyStrategy,
        ctx:      ApplyContext,
        session:  SessionRecord,
    ) -> ApplyResult:
        t0 = time.monotonic()

        if strategy == ApplyStrategy.SKYVERN_CODE:
            cached = await self.cache.fetch(ctx.portal, "apply")
            if cached is None:
                # Race condition — fall through to AI mode
                strategy = ApplyStrategy.BROWSER_USE_AI
            else:
                result = await self.adapter.run_skyvern_code(
                    ctx, session, cached.code_blob,
                )
                result.skyvern_cached = True
                result.duration_ms = int((time.monotonic() - t0) * 1000)
                if result.outcome == ApplyOutcome.SUCCESS:
                    await self.cache.record_outcome(ctx.portal, "apply", success=True)
                return result

        if strategy == ApplyStrategy.BROWSER_USE_AI:
            result, generated_code = await self.adapter.run_browser_use(ctx, session)
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            if result.outcome == ApplyOutcome.SUCCESS and generated_code:
                # Crystallise the AI reasoning into cached code (Innovation 2)
                await self.cache.store(
                    ctx.portal, "apply",
                    code_blob=generated_code, success=True,
                )
                log.info("triad.code_crystallised portal=%s bytes=%s",
                         ctx.portal, len(generated_code))
            return result

        # CAMOUFOX_VIRTUAL — heavy WAF bypass path
        result = await self.adapter.run_camoufox_virtual(ctx, session)
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        return result


# ────────────────────────────────────────────────────────────────────────────
# Null adapter — used in tests / dry-runs (no real browser opened)
# ────────────────────────────────────────────────────────────────────────────
class NullAdapter(StealthAdapter):
    """Deterministic stub.  Returns SUCCESS for every strategy."""

    async def run_skyvern_code(self, ctx, session, code_blob):
        await asyncio.sleep(0)
        return ApplyResult(
            outcome=ApplyOutcome.SUCCESS,
            strategy_used=ApplyStrategy.SKYVERN_CODE,
            duration_ms=0,
        )

    async def run_browser_use(self, ctx, session):
        await asyncio.sleep(0)
        result = ApplyResult(
            outcome=ApplyOutcome.SUCCESS,
            strategy_used=ApplyStrategy.BROWSER_USE_AI,
            duration_ms=0,
        )
        return result, "# generated playwright stub\nasync def apply(page): ..."

    async def run_camoufox_virtual(self, ctx, session):
        await asyncio.sleep(0)
        return ApplyResult(
            outcome=ApplyOutcome.SUCCESS,
            strategy_used=ApplyStrategy.CAMOUFOX_VIRTUAL,
            duration_ms=0,
        )


__all__ = [
    "ApplyStrategy", "ApplyOutcome", "ApplyResult", "ApplyContext",
    "StealthAdapter", "NullAdapter",
    "SkyvernCodeCacheRepo", "CachedCode",
    "StealthTriad",
]
