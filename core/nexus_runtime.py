"""
NEXUS v0.2 — Runtime Wirer
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Single ignition point that assembles every NEXUS layer into a running system.

  Layer 0  · SessionVault        (encrypted sessions + health oracle)
  Layer 1  · StealthTriad        (Camoufox + Browser-Use + Skyvern)
  Layer 2  · Crawl4AI Discovery  (universal extraction + reactive RSS)
  Layer 3  · ScoringEngine v2    (9 dimensions + pgvector match)
  Layer 4  · Answer RAG          (top-3 + Cerebras + validator)
  Layer 5  · CAPTCHA Resolver    (T1..T4 cascade)
  Layer 6  · Orchestrator        (priority queue + Risk Governor)
  Layer 7  · Dedup Engine        (exact + semantic)
  Layer 8  · Interview Intel     (90s briefing)
  Layer 9  · Telegram Dashboard  (the cockpit)
  Layer M  · 15 Innovations      (trajectory, FOMO, warmup, …)

Design contract
---------------
* This module is **import-safe** even when the heavy NEXUS stack
  (`requirements-nexus.txt`) is not installed. Every heavy dependency is
  resolved lazily through the layer modules themselves, which all carry
  defensive guards.
* It is **opt-in**: nothing happens unless `NEXUS_ENABLED=true` is set in the
  environment. PRISM v0.1 keeps running unchanged.
* It exposes a single public class — `NexusRuntime` — with `start() / stop() /
  snapshot()`. The host application (`main.py`) launches it as a background
  asyncio task during Phase 10 and tears it down on graceful shutdown.

In-process stub DB
------------------
The orchestrator and risk governor expect a `db` object that fulfils a small
async protocol. On a fresh worker, the operator runs `scripts/nexus_bootstrap.sh
--step schema` to apply `data/nexus_v02_schema.sql`, then later swaps the stub
for the real Supabase-backed DAO. Until then, `_NullOrchestratorDB` keeps the
loops idling without crashes, so the dashboard can come online and show status.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

# Layer imports — every one of these is import-safe on the slim 512MB dyno.
from core.nexus_config import (
    NEXUS_VERSION,
    ORCHESTRATOR,
    SUPPORTED_PORTALS,
    STACK,
)
from core.session_vault import (
    InMemoryVaultDB,
    SessionOracle,
    SessionVault,
)
from core.stealth_triad import NullAdapter, StealthTriad, SkyvernCodeCacheRepo
from core.scoring_engine_v2 import ScoringEngine
from core.pgvector_matcher import InMemoryProfileDB, ProfileMatcher
from core.dedup_semantic import DedupEngine, InMemoryDedupDB
from core.orchestrator import Orchestrator, RiskGovernor
from core.telegram_dashboard import (
    DashboardConfig,
    TelegramDashboard,
)

log = logging.getLogger("nexus.runtime")


# ============================================================================
# Null / In-memory backends
# ----------------------------------------------------------------------------
# These keep the runtime alive without a Postgres backend so the operator can
# verify wiring + start the Telegram cockpit *before* applying the schema.
# ============================================================================

class _NullOrchestratorDB:
    """
    Async no-op DB. Returns neutral values for every signal so the Risk
    Governor reports `NORMALISE`, the queue is empty, and ticks complete in
    milliseconds. Replace by binding a real Supabase DAO in `NexusRuntime.bind_db`.
    """

    # ─────────── RiskGovernor signals ───────────
    async def apps_per_hour(self, portal: str) -> int: return 0
    async def captcha_rate(self, portal: str, lookback_hours: int = 24) -> float: return 0.0
    async def session_age_days(self, portal: str) -> int: return 0
    async def error_rate(self, portal: str, last_n: int = 20) -> float: return 0.0
    async def tod_variance(self, portal: str, days_back: int = 7) -> float: return 0.0

    async def log_risk(self, **kw: Any) -> None:                 # noqa: D401
        log.debug("nullDB.log_risk %s", kw)

    # ─────────── Orchestrator queue ──────────────
    async def upsert_queue_row(self, row: Any) -> None: pass
    async def fetch_dispatchable(self, now: datetime, max_n: int): return []
    async def fetch_for_rescore(self, now: datetime): return []
    async def update_state(self, job_id: str, state: Any, **kw: Any) -> None: pass
    async def fetch_job(self, job_id: str):                       # noqa: D401
        raise KeyError(f"NullDB has no job {job_id}")
    async def store_score(self, breakdown: Any) -> None: pass
    async def store_application_record(self, job_id: str, result: Any, breakdown: Any) -> None: pass
    async def set_orchestrator_state(self, **kw: Any) -> None: pass


class _NullInterviewIntel:
    """Stub for Layer 8 — used until Gmail/LinkedIn signal pipes are wired."""
    async def detect_signals(self) -> list[dict]:  return []
    async def briefing(self, signal_id: str) -> dict: return {}
    async def latest(self, n: int = 5) -> list[dict]: return []


# ============================================================================
# Runtime container
# ============================================================================

@dataclass
class NexusBootReport:
    started_at:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    layers_ok:    list[str] = field(default_factory=list)
    layers_fail:  dict[str, str] = field(default_factory=dict)
    dashboard_ok: bool = False
    triad_live:   bool = False        # True only when heavy stack installed
    db_backend:   str = "null"

    def summary(self) -> str:
        return (
            f"NEXUS v{NEXUS_VERSION} boot: "
            f"layers_ok={len(self.layers_ok)}, "
            f"layers_fail={len(self.layers_fail)}, "
            f"dashboard={'on' if self.dashboard_ok else 'off'}, "
            f"triad_live={self.triad_live}, "
            f"db={self.db_backend}"
        )


class NexusRuntime:
    """
    The orchestrator-of-orchestrators. Wires every NEXUS layer and runs the
    three background loops:

        • queue_tick        → every ORCHESTRATOR['queue_tick_minutes'] (15m default)
        • rescore_tick      → every ORCHESTRATOR['rescore_interval_hours'] (2h default)
        • dashboard_polling → run inside python-telegram-bot's own loop

    Public surface:
        runtime = NexusRuntime(profile=…)        # 1. construct, no I/O
        await runtime.start()                    # 2. ignite
        await runtime.snapshot()                 # 3. status (used by /health)
        await runtime.stop()                     # 4. graceful shutdown
    """

    def __init__(
        self,
        profile:        Optional[dict[str, Any]] = None,
        on_event:       Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> None:
        self.profile  = profile or self._default_profile()
        self.on_event = on_event or self._default_on_event
        self.report   = NexusBootReport()

        self._db          = _NullOrchestratorDB()
        self._vault_db    = InMemoryVaultDB()
        self._dedup_db    = InMemoryDedupDB()
        self._oracle      = SessionOracle(telegram_notifier=None)
        self._vault: Optional[SessionVault] = None
        self._scoring: Optional[ScoringEngine] = None
        self._dedup: Optional[DedupEngine] = None
        self._triad: Optional[StealthTriad] = None
        self._risk: Optional[RiskGovernor] = None
        self._orch: Optional[Orchestrator] = None
        self._dash: Optional[TelegramDashboard] = None

        self._tick_task:    Optional[asyncio.Task] = None
        self._rescore_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    # ─────────────────────────────────── lifecycle ──────────────────────

    async def start(self) -> NexusBootReport:
        log.info("nexus.runtime.start version=%s portals=%d",
                 NEXUS_VERSION, len(SUPPORTED_PORTALS))

        # Layer 0 — Vault
        try:
            self._vault = SessionVault(self._vault_db, oracle=self._oracle)
            self.report.layers_ok.append("L0_vault")
        except Exception as e:
            self.report.layers_fail["L0_vault"] = str(e)
            log.exception("L0 vault init failed")

        # Layer 1 — Stealth Triad (heavy stack guard via NullAdapter fallback)
        try:
            cache_repo = SkyvernCodeCacheRepo(db=self._db)
            adapter = NullAdapter()                       # sane default
            # Heavy adapters only loaded when requirements-nexus.txt installed.
            # The actual Skyvern/Browser-Use adapters live in agents/n0{1,2}_*.
            try:
                from agents.n01_skyvern_apply import SkyvernApplyAdapter  # type: ignore
                adapter = SkyvernApplyAdapter()                              # primary
                # Only flag triad as live when Playwright/Skyvern can actually run.
                try:
                    from agents.n01_skyvern_apply import PLAYWRIGHT_AVAILABLE  # type: ignore
                    self.report.triad_live = bool(PLAYWRIGHT_AVAILABLE)
                except Exception:
                    self.report.triad_live = False
            except Exception as inner:
                log.warning(
                    "nexus.triad.heavy_stack_missing — using NullAdapter (%s)",
                    inner,
                )

            self._triad = StealthTriad(
                vault=self._vault,            # type: ignore[arg-type]
                cache=cache_repo,
                adapter=adapter,
                on_event=self.on_event,
            )
            self.report.layers_ok.append("L1_stealth_triad")
        except Exception as e:
            self.report.layers_fail["L1_stealth_triad"] = str(e)
            log.exception("L1 triad init failed")

        # Layer 3 — Scoring  (no LLM bound yet → uses neutral InMemoryProfileDB)
        try:
            profile_db = InMemoryProfileDB()
            matcher = ProfileMatcher(profile_db)
            self._scoring = ScoringEngine(matcher=matcher)
            self.report.layers_ok.append("L3_scoring")
        except Exception as e:
            self.report.layers_fail["L3_scoring"] = str(e)
            log.exception("L3 scoring init failed")

        # Layer 7 — Dedup (in-memory until Postgres pgvector is bound)
        try:
            self._dedup = DedupEngine(db=self._dedup_db)
            self.report.layers_ok.append("L7_dedup")
        except Exception as e:
            self.report.layers_fail["L7_dedup"] = str(e)
            log.exception("L7 dedup init failed")

        # Layer 6 — Orchestrator (RiskGovernor → Orchestrator)
        try:
            self._risk = RiskGovernor(db=self._db, vault=self._vault)  # type: ignore[arg-type]
            self._orch = Orchestrator(
                db       = self._db,
                scoring  = self._scoring,    # type: ignore[arg-type]
                dedup    = self._dedup,      # type: ignore[arg-type]
                triad    = self._triad,      # type: ignore[arg-type]
                vault    = self._vault,      # type: ignore[arg-type]
                risk     = self._risk,
                profile  = self.profile,
                on_event = self.on_event,
            )
            self.report.layers_ok.append("L6_orchestrator")
        except Exception as e:
            self.report.layers_fail["L6_orchestrator"] = str(e)
            log.exception("L6 orchestrator init failed")

        # Layer 9 — Telegram Dashboard
        try:
            self._dash = TelegramDashboard(
                orch  = _OrchestratorAdapter(self._orch) if self._orch else _DashboardOrchStub(),
                vault = _VaultAdapter(self._vault) if self._vault else _DashboardVaultStub(),
                intel = _NullInterviewIntel(),
                cfg   = DashboardConfig(),
            )
            await self._dash.start()
            self.report.dashboard_ok = bool(self._dash._app)  # noqa: SLF001
            self.report.layers_ok.append("L9_dashboard")
        except Exception as e:
            self.report.layers_fail["L9_dashboard"] = str(e)
            log.exception("L9 dashboard init failed")

        # Background loops
        if self._orch:
            self._tick_task    = asyncio.create_task(self._loop_tick(),    name="nexus.tick")
            self._rescore_task = asyncio.create_task(self._loop_rescore(), name="nexus.rescore")

        log.info("nexus.runtime.started %s", self.report.summary())
        return self.report

    async def stop(self) -> None:
        log.info("nexus.runtime.stop")
        self._stopping.set()
        for t in (self._tick_task, self._rescore_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        if self._dash:
            try:
                await self._dash.stop()
            except Exception:
                log.exception("dashboard stop failed")

    # ─────────────────────────────────── snapshot ──────────────────────

    async def snapshot(self) -> dict[str, Any]:
        """Used by /health and /nexus telegram command."""
        return {
            "version":      NEXUS_VERSION,
            "started_at":   self.report.started_at.isoformat(),
            "layers_ok":    list(self.report.layers_ok),
            "layers_fail":  dict(self.report.layers_fail),
            "dashboard_ok": self.report.dashboard_ok,
            "triad_live":   self.report.triad_live,
            "db_backend":   self.report.db_backend,
            "portals":      list(SUPPORTED_PORTALS),
        }

    # ─────────────────────────────────── bind real DB ───────────────────

    def bind_db(self, real_db: Any) -> None:
        """Swap the in-process stub for a real Supabase-backed DAO."""
        self._db = real_db
        self.report.db_backend = type(real_db).__name__
        if self._risk:    self._risk.db    = real_db
        if self._orch:    self._orch.db    = real_db
        log.info("nexus.runtime.db_bound %s", type(real_db).__name__)

    # ─────────────────────────────────── loops ──────────────────────────

    async def _loop_tick(self) -> None:
        interval = ORCHESTRATOR["queue_tick_minutes"] * 60
        while not self._stopping.is_set():
            t0 = time.monotonic()
            try:
                if self._orch:
                    out = await self._orch.tick()
                    log.info("nexus.tick dispatched=%s", out.get("dispatched", 0))
            except Exception:
                log.exception("nexus.tick failed")
            elapsed = time.monotonic() - t0
            await self._sleep_or_stop(max(1.0, interval - elapsed))

    async def _loop_rescore(self) -> None:
        interval = ORCHESTRATOR["rescore_interval_hours"] * 3600
        while not self._stopping.is_set():
            t0 = time.monotonic()
            try:
                if self._orch:
                    n = await self._orch.rescore_tick()
                    log.info("nexus.rescore done=%s", n)
            except Exception:
                log.exception("nexus.rescore failed")
            elapsed = time.monotonic() - t0
            await self._sleep_or_stop(max(1.0, interval - elapsed))

    async def _sleep_or_stop(self, secs: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=secs)
        except asyncio.TimeoutError:
            pass

    # ─────────────────────────────────── helpers ────────────────────────

    @staticmethod
    def _default_profile() -> dict[str, Any]:
        return {
            "user_handle":     os.getenv("NEXUS_USER_HANDLE", "abuzar_salim"),
            "resume_variant":  "master",
            "resume_paths":    {"master": os.getenv("MASTER_RESUME_PATH", "")},
            "preloaded_answers": {},
        }

    async def _default_on_event(self, kind: str, payload: dict) -> None:
        log.info("nexus.event %s %s", kind, payload)


# ============================================================================
# Adapters: bridge our Orchestrator/Vault to the dashboard's Protocol surface
# ============================================================================

class _OrchestratorAdapter:
    def __init__(self, orch: Orchestrator):
        self.orch = orch
    async def status_snapshot(self) -> dict:
        return {
            "version":   NEXUS_VERSION,
            "portals":   list(SUPPORTED_PORTALS),
            "queue":     0,
            "dispatch":  ORCHESTRATOR["max_concurrent_applies"],
        }
    async def pending_review(self, n: int = 10) -> list:               return []
    async def daily_digest(self) -> list:                              return []
    async def pause_portal(self, portal: str, reason: str = "manual"):
        await self.orch.pause_portal(portal, reason)
    async def resume_portal(self, portal: str):
        await self.orch.resume_portal(portal)
    async def force_apply(self, url: str) -> dict:                     return {"ok": False, "reason": "no_db_bound"}
    async def force_score(self, url: str) -> dict:                     return {"ok": False, "reason": "no_db_bound"}
    async def risk_summary(self) -> dict:                              return {"governor": "idle"}


class _VaultAdapter:
    def __init__(self, vault: SessionVault):
        self.vault = vault
    async def health_summary(self) -> dict:
        return {"sessions": 0, "min_health": 100}
    async def refresh_session(self, portal: str) -> dict:              return {"queued": True, "portal": portal}


class _DashboardOrchStub:
    async def status_snapshot(self) -> dict:    return {"state": "boot_failed"}
    async def pending_review(self, n=10):       return []
    async def daily_digest(self):               return []
    async def pause_portal(self, *a, **kw):     return None
    async def resume_portal(self, *a, **kw):    return None
    async def force_apply(self, *a, **kw):      return {"ok": False}
    async def force_score(self, *a, **kw):      return {"ok": False}
    async def risk_summary(self):               return {}


class _DashboardVaultStub:
    async def health_summary(self):             return {}
    async def refresh_session(self, portal):    return {}


# ============================================================================
# Process-wide accessor (used by /nexus health endpoint in keepalive.py)
# ============================================================================
_active: Optional["NexusRuntime"] = None


def get_runtime() -> Optional["NexusRuntime"]:
    """Return the live NexusRuntime if Phase 10 has booted, else None."""
    return _active


def _set_active(rt: Optional["NexusRuntime"]) -> None:
    global _active
    _active = rt


# Re-bind start/stop to publish the singleton automatically
_orig_start = NexusRuntime.start
_orig_stop  = NexusRuntime.stop


async def _start_with_publish(self: "NexusRuntime") -> NexusBootReport:        # noqa: D401
    rep = await _orig_start(self)
    _set_active(self)
    return rep


async def _stop_with_publish(self: "NexusRuntime") -> None:                    # noqa: D401
    try:
        await _orig_stop(self)
    finally:
        if _active is self:
            _set_active(None)


NexusRuntime.start = _start_with_publish    # type: ignore[assignment]
NexusRuntime.stop  = _stop_with_publish     # type: ignore[assignment]


__all__ = ["NexusRuntime", "NexusBootReport", "get_runtime"]
