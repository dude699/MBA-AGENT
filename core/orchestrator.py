"""
NEXUS v0.2 — Layer 6: Intelligent Application Orchestrator
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

The brain that coordinates every other layer.  Two big innovations vs PRISM:

  1. Priority Queue with dynamic re-scoring — every 2 hours queued jobs are
     re-scored as deadlines approach.  A 75-score job with 4-hour deadline
     becomes higher priority than a 90-score job with no deadline.

  2. Risk Governor — five continuous signals are monitored per portal and
     pre-emptive throttling kicks in BEFORE any portal hits a ban threshold.

Public surface
--------------
  Orchestrator(...)
      .ingest(jobs)               # Layer 2 → score → dedup → enqueue
      .tick()                     # one queue cycle (called every 15 min)
      .rescore_tick()             # one re-score cycle (called every 2 hr)
      .pause_portal(portal, ...)  # operator command from Telegram
      .resume_portal(portal)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from core.crawl4ai_discovery import NormalisedJob
from core.dedup_semantic import DedupEngine
from core.nexus_config import (
    APPLY_WINDOWS,
    DEADLINE_CLIFFS,
    ORCHESTRATOR,
    PORTAL_RISK,
    SUPPORTED_PORTALS,
    is_apply_window_open,
)
from core.scoring_engine_v2 import ScoreBreakdown, ScoringEngine
from core.session_vault import SessionVault
from core.stealth_triad import (
    ApplyContext,
    ApplyOutcome,
    ApplyResult,
    StealthTriad,
)

log = logging.getLogger("nexus.orchestrator")


# ────────────────────────────────────────────────────────────────────────────
# Queue state machine
# ────────────────────────────────────────────────────────────────────────────
class QueueState(str, Enum):
    QUEUED       = "QUEUED"
    HELD         = "HELD"            # outside apply window or paused
    DISPATCHING  = "DISPATCHING"
    RUNNING      = "RUNNING"
    DONE         = "DONE"
    FAILED       = "FAILED"


# ────────────────────────────────────────────────────────────────────────────
# Risk Governor — 5 signals + pre-emptive throttle
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class RiskSignal:
    name:      str
    value:     float
    threshold: float
    breach:    bool
    action:    str                 # THROTTLE | PAUSE | NORMALISE | NOTIFY


class RiskGovernor:
    """
    Required `db` methods:
        async def apps_per_hour(portal) -> int
        async def captcha_rate(portal, lookback_hours=24) -> float
        async def session_age_days(portal) -> int
        async def error_rate(portal, last_n=20) -> float
        async def tod_variance(portal, days_back=7) -> float       # 0..1
        async def log_risk(portal, signal, value, threshold, action, paused) -> None
    """

    def __init__(self, db, vault: SessionVault):
        self.db    = db
        self.vault = vault

    async def evaluate(self, portal: str) -> list[RiskSignal]:
        if portal not in PORTAL_RISK:
            return []
        cfg     = PORTAL_RISK[portal]
        out:    list[RiskSignal] = []

        # 1. Apps/hour
        v   = await self.db.apps_per_hour(portal)
        out.append(RiskSignal(
            name="apps_per_hour", value=v, threshold=cfg.max_apps_per_hour,
            breach=v >= cfg.max_apps_per_hour,
            action="THROTTLE" if v >= cfg.max_apps_per_hour else "NORMALISE",
        ))

        # 2. CAPTCHA rate
        v = await self.db.captcha_rate(portal)
        out.append(RiskSignal(
            name="captcha_rate", value=v, threshold=cfg.captcha_rate_throttle,
            breach=v > cfg.captcha_rate_throttle,
            action="THROTTLE" if v > cfg.captcha_rate_throttle else "NORMALISE",
        ))

        # 3. Session age (days)
        v = await self.db.session_age_days(portal)
        out.append(RiskSignal(
            name="session_age", value=v, threshold=cfg.session_age_warn_days,
            breach=v > cfg.session_age_warn_days,
            action="THROTTLE" if v > cfg.session_age_warn_days else "NORMALISE",
        ))

        # 4. Error rate (last 20 attempts)
        v = await self.db.error_rate(portal)
        out.append(RiskSignal(
            name="error_rate", value=v, threshold=cfg.error_rate_pause,
            breach=v > cfg.error_rate_pause,
            action="PAUSE" if v > cfg.error_rate_pause else "NORMALISE",
        ))

        # 5. Time-of-day variance
        v = await self.db.tod_variance(portal)
        out.append(RiskSignal(
            name="tod_variance", value=v, threshold=0.6,
            breach=v > 0.6,
            action="NORMALISE",
        ))
        return out

    async def apply(self, portal: str) -> tuple[float, bool]:
        """
        Returns (rate_multiplier, paused).
        Persists every signal evaluation to risk_governor_log.
        """
        signals = await self.evaluate(portal)
        rate    = 1.0
        paused  = False
        for s in signals:
            if s.action == "THROTTLE" and s.breach:
                rate *= 0.5
            if s.action == "PAUSE" and s.breach:
                paused = True
                rate   = 0.0
            await self.db.log_risk(
                portal=portal, signal=s.name,
                value=s.value, threshold=s.threshold,
                action=s.action, paused=paused,
            )
        if paused:
            log.warning("risk.pause portal=%s — error_rate breach", portal)
        elif rate < 1.0:
            log.info("risk.throttle portal=%s rate=%.2f", portal, rate)
        return rate, paused


# ────────────────────────────────────────────────────────────────────────────
# QueueRow
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class QueueRow:
    job_id:            str
    portal:            str
    score:             int
    deadline_urgency:  int
    apply_window_open: bool
    risk_level:        str             # LOW | MED | HIGH
    state:             QueueState
    attempts:          int
    queued_at:         datetime
    rescore_at:        datetime
    dispatch_at:       datetime | None = None
    last_error:        str | None      = None


# ────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ────────────────────────────────────────────────────────────────────────────
class Orchestrator:
    """
    Required `db` methods (in addition to those required by sub-engines):
        async def upsert_queue_row(row: QueueRow) -> None
        async def fetch_dispatchable(now, max_n) -> list[QueueRow]
        async def fetch_for_rescore(now) -> list[QueueRow]
        async def update_state(job_id, state, **kwargs) -> None
        async def fetch_job(job_id) -> NormalisedJob
        async def store_score(breakdown: ScoreBreakdown) -> None
        async def store_application_record(job_id, result, breakdown) -> None
        async def set_orchestrator_state(portal, paused, paused_reason,
                                        paused_until, rate_multiplier) -> None
    """

    def __init__(
        self,
        db,
        scoring:  ScoringEngine,
        dedup:    DedupEngine,
        triad:    StealthTriad,
        vault:    SessionVault,
        risk:     RiskGovernor,
        profile:  dict[str, Any],
        on_event: Callable[[str, dict], Awaitable[None]] | None = None,
    ):
        self.db       = db
        self.scoring  = scoring
        self.dedup    = dedup
        self.triad    = triad
        self.vault    = vault
        self.risk     = risk
        self.profile  = profile
        self.on_event = on_event or (lambda *_: asyncio.sleep(0))

    # ──────────────────────────── ingest ────────────────────────────────
    async def ingest(self, jobs: list[NormalisedJob]) -> dict[str, int]:
        """Layer 2 → score → dedup → enqueue.  Returns counts dict."""
        if not jobs:
            return {"received": 0, "enqueued": 0, "duplicates": 0, "rejected": 0}

        # Stage 1 — semantic + exact dedup (Layer 7)
        unique, dups = await self.dedup.filter_unique(jobs)

        # Stage 2 — score every unique job (Layer 3)
        enqueued = rejected = 0
        for job in unique:
            try:
                breakdown = await self.scoring.score(job, self.profile)
                await self.db.store_score(breakdown)

                if breakdown.routing == "REJECT":
                    rejected += 1
                    continue

                # Push into queue
                now = datetime.now(timezone.utc)
                deadline_urg = self._deadline_urgency(job)
                row = QueueRow(
                    job_id            = job.job_id,
                    portal            = job.portal,
                    score             = breakdown.final_score,
                    deadline_urgency  = deadline_urg,
                    apply_window_open = is_apply_window_open(job.portal, _now_hhmm()),
                    risk_level        = self._risk_level(breakdown.final_score, deadline_urg),
                    state             = QueueState.QUEUED,
                    attempts          = 0,
                    queued_at         = now,
                    rescore_at        = now + timedelta(hours=ORCHESTRATOR["rescore_interval_hours"]),
                )
                await self.db.upsert_queue_row(row)
                enqueued += 1
            except Exception as e:                                  # noqa: BLE001
                log.exception("orch.ingest_score_fail job=%s err=%s", job.job_id, e)

        log.info(
            "orch.ingest received=%s unique=%s enqueued=%s rejected=%s dups=%s",
            len(jobs), len(unique), enqueued, rejected, len(dups),
        )
        return {
            "received":   len(jobs),
            "enqueued":   enqueued,
            "duplicates": len(dups),
            "rejected":   rejected,
        }

    # ──────────────────────────── tick ──────────────────────────────────
    async def tick(self) -> dict[str, Any]:
        """One queue-processor cycle.  Called every 15 minutes."""
        now = datetime.now(timezone.utc)
        max_n = ORCHESTRATOR["max_concurrent_applies"]

        # Snapshot Risk Governor per portal
        portal_rates: dict[str, tuple[float, bool]] = {}
        for portal in SUPPORTED_PORTALS:
            try:
                portal_rates[portal] = await self.risk.apply(portal)
            except Exception as e:                                  # noqa: BLE001
                log.warning("orch.risk_eval_fail portal=%s err=%s", portal, e)
                portal_rates[portal] = (1.0, False)
            mult, paused = portal_rates[portal]
            try:
                await self.db.set_orchestrator_state(
                    portal=portal,
                    paused=paused,
                    paused_reason="risk_governor" if paused else None,
                    paused_until=(now + timedelta(hours=2)) if paused else None,
                    rate_multiplier=mult,
                )
            except Exception:
                pass

        rows = await self.db.fetch_dispatchable(now, max_n)
        outcomes: list[dict] = []
        for row in rows:
            mult, paused = portal_rates.get(row.portal, (1.0, False))
            if paused or mult <= 0.0:
                await self.db.update_state(row.job_id, QueueState.HELD,
                                           last_error="portal_paused")
                continue

            # Honour apply window — Innovation 6
            ignore_window = self._ignore_window_for_deadline(row)
            if not ignore_window and not is_apply_window_open(row.portal, _now_hhmm()):
                await self.db.update_state(row.job_id, QueueState.HELD,
                                           last_error="outside_apply_window")
                continue

            outcomes.append(await self._dispatch_one(row))
            # respect throttle multiplier with a delay between dispatches
            await asyncio.sleep(max(0.0, (1.0 - mult) * 60))

        return {"dispatched": len(outcomes), "outcomes": outcomes,
                "portal_rates": {p: r[0] for p, r in portal_rates.items()}}

    # ──────────────────────────── rescore_tick ─────────────────────────
    async def rescore_tick(self) -> int:
        """Re-score queued rows whose `rescore_at` has passed."""
        now  = datetime.now(timezone.utc)
        rows = await self.db.fetch_for_rescore(now)
        n = 0
        for row in rows:
            try:
                job  = await self.db.fetch_job(row.job_id)
                bd   = await self.scoring.score(job, self.profile)
                await self.db.store_score(bd)
                row.score             = bd.final_score
                row.deadline_urgency  = self._deadline_urgency(job)
                row.risk_level        = self._risk_level(bd.final_score, row.deadline_urgency)
                row.rescore_at        = now + timedelta(
                    hours=ORCHESTRATOR["rescore_interval_hours"]
                )
                row.apply_window_open = is_apply_window_open(row.portal, _now_hhmm())
                await self.db.upsert_queue_row(row)
                n += 1
            except Exception as e:                                  # noqa: BLE001
                log.warning("orch.rescore_fail job=%s err=%s", row.job_id, e)
        log.info("orch.rescore done=%d", n)
        return n

    # ──────────────────────────── operator API ─────────────────────────
    async def pause_portal(
        self, portal: str, reason: str, hours: int = 6,
    ) -> None:
        await self.db.set_orchestrator_state(
            portal=portal,
            paused=True,
            paused_reason=reason,
            paused_until=datetime.now(timezone.utc) + timedelta(hours=hours),
            rate_multiplier=0.0,
        )
        await self.on_event("portal_paused", {"portal": portal, "reason": reason})
        log.warning("orch.portal_paused portal=%s reason=%s hours=%s",
                    portal, reason, hours)

    async def resume_portal(self, portal: str) -> None:
        await self.db.set_orchestrator_state(
            portal=portal, paused=False, paused_reason=None,
            paused_until=None, rate_multiplier=1.0,
        )
        await self.on_event("portal_resumed", {"portal": portal})
        log.info("orch.portal_resumed portal=%s", portal)

    # ──────────────────────────── internals ────────────────────────────
    async def _dispatch_one(self, row: QueueRow) -> dict:
        """Execute one apply via the Stealth Triad."""
        await self.db.update_state(row.job_id, QueueState.DISPATCHING)
        await self.on_event("dispatch", {"job_id": row.job_id, "portal": row.portal})

        try:
            job = await self.db.fetch_job(row.job_id)
        except Exception as e:                                       # noqa: BLE001
            await self.db.update_state(row.job_id, QueueState.FAILED,
                                       last_error=f"fetch_job:{e}")
            return {"job_id": row.job_id, "outcome": "FETCH_FAILED"}

        # Build context — answers + resume variant come from Layer 4 / Innov.8
        ctx = ApplyContext(
            portal      = job.portal,
            job_id      = job.job_id,
            job_url     = job.raw_url,
            profile     = self.profile,
            answers     = self.profile.get("preloaded_answers", {}),
            resume_path = self.profile.get("resume_paths", {}).get(
                self.profile.get("resume_variant", "master"),
                self.profile.get("resume_paths", {}).get("master"),
            ),
            portal_blocked = (row.risk_level == "HIGH"),
        )

        await self.db.update_state(row.job_id, QueueState.RUNNING)
        result: ApplyResult = await self.triad.execute(ctx)

        # Persist
        breakdown = None  # the orchestrator stores the result; the score row
                          # was already persisted at ingest/rescore time.
        await self.db.store_application_record(row.job_id, result, breakdown)

        # Retry policy
        if result.outcome == ApplyOutcome.SUCCESS:
            await self.db.update_state(row.job_id, QueueState.DONE)
            await self.on_event("apply_success", {
                "job_id": row.job_id, "portal": row.portal,
                "duration_ms": result.duration_ms,
                "strategy": result.strategy_used.value,
            })
            return {"job_id": row.job_id, "outcome": "SUCCESS"}

        new_attempts = row.attempts + 1
        max_retry    = ORCHESTRATOR["retry_max"]
        if new_attempts >= max_retry:
            await self.db.update_state(row.job_id, QueueState.FAILED,
                                       last_error=result.error or result.outcome.value,
                                       attempts=new_attempts)
            await self.on_event("apply_failed_final", {
                "job_id": row.job_id, "portal": row.portal,
                "error": result.error,
            })
            return {"job_id": row.job_id, "outcome": "FAILED_FINAL"}

        # Re-queue with backoff
        backoffs = ORCHESTRATOR["retry_backoff_seconds"]
        delay    = backoffs[min(new_attempts - 1, len(backoffs) - 1)]
        await self.db.update_state(
            row.job_id, QueueState.QUEUED,
            last_error=result.error or result.outcome.value,
            attempts=new_attempts,
            dispatch_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
        )
        await self.on_event("apply_retry", {
            "job_id": row.job_id, "attempt": new_attempts, "delay_s": delay,
        })
        return {"job_id": row.job_id, "outcome": "RETRY", "attempt": new_attempts}

    @staticmethod
    def _deadline_urgency(job: NormalisedJob) -> int:
        """0..100 — bigger = more urgent."""
        if not job.deadline:
            return 0
        now = datetime.now(timezone.utc)
        dl  = job.deadline if job.deadline.tzinfo else job.deadline.replace(tzinfo=timezone.utc)
        hrs = (dl - now).total_seconds() / 3600
        if hrs <= 0:
            return 0
        if hrs <= 6:
            return 100
        if hrs <= 24:
            return 80
        if hrs <= 72:
            return 60
        if hrs <= 168:
            return 40
        return 20

    @staticmethod
    def _risk_level(score: int, deadline_urg: int) -> str:
        if score >= 80 or deadline_urg >= 80:
            return "HIGH"          # priority — fast track
        if score >= 60:
            return "MED"
        return "LOW"

    @staticmethod
    def _ignore_window_for_deadline(row: QueueRow) -> bool:
        """Innovation 11 — within 24-hour cliff, the apply window is ignored."""
        return row.deadline_urgency >= 80


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def _now_hhmm(tz_offset_hours: float = 5.5) -> str:
    """Local IST hh:mm string (default IST = UTC+5:30)."""
    now = datetime.now(timezone.utc) + timedelta(hours=tz_offset_hours)
    return now.strftime("%H:%M")


__all__ = [
    "Orchestrator",
    "QueueRow",
    "QueueState",
    "RiskGovernor",
    "RiskSignal",
]
