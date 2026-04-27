"""
NEXUS v0.2 — Scoring Loop (off-hours per-user CV-match scorer + usage learner)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Continuously scores every (user, job) pair in the background. Designed to run
during *off-hours* — defined as either:

  • Time window: 02:00–06:00 IST (configurable via NEXUS_SCORING_WINDOW_IST)
  • Idle gap:    the orchestrator queue has been quiet for > 30 min
  • Trigger:     a user just uploaded a new CV (full backfill for that user)

What it does
------------
  1. For each active user (ADMIN/POWER/STANDARD with a CV embedding):
     a. Fetch all jobs they have NOT yet been scored against (job_scores miss).
     b. Score each job → (user_id, job_id, breakdown) row in job_scores.
     c. Apply per-user dimension-weight deltas (learned from past taps).
     d. Route per-user according to role:
          ADMIN/POWER + auto_apply_on:
            score ≥ 80 → enqueue priority_score = role_boost + score + urgency
          STANDARD or auto_apply_on=False:
            score ≥ 80 → digest [Apply] [Skip]
          40 ≤ score < 80 → digest [Apply] [Skip] [Snooze]
          < 40 → silent (already saved to job_scores)

Usage-pattern learning (Bayesian dimension reweighter)
------------------------------------------------------
After a user accumulates ≥ 30 actions (APPLIED / SKIPPED), we compute:

   delta_d = (mean(dim_d on APPLIED) - mean(dim_d on SKIPPED)) / 200

Clipped to ±0.08, written to user_dimension_weights. Next scoring run uses
SCORING_WEIGHTS[d] + delta_d for that user. This makes the system smarter
about what THIS user actually wants — not the global average.

Public surface
--------------
  ScoringLoop(db, scoring_engine, orchestrator, access).
      start()                — launches the asyncio task
      stop()                 — cancels gracefully
      enqueue_user(user_id)  — force a backfill for a single user (CV upload)
      status()               — dict: last_run_at, scored_24h, learning_users
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.access_control import Role, ROLE_BOOST
from core.crawl4ai_discovery import NormalisedJob
from core.nexus_config import (
    ROUTING_THRESHOLDS,
    SCORING_WEIGHTS,
)

log = logging.getLogger("nexus.scoring_loop")


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class ScoringWindowConfig:
    """When the loop is allowed to chew CPU + LLM tokens."""
    start_hour_ist: int = 2          # 02:00 IST
    end_hour_ist:   int = 6          # 06:00 IST
    idle_minutes_before_run: int = 30
    tick_seconds: int = 90           # poll cadence outside window

    @classmethod
    def from_env(cls) -> "ScoringWindowConfig":
        spec = os.getenv("NEXUS_SCORING_WINDOW_IST", "").strip()
        if spec and "-" in spec:
            try:
                a, b = spec.split("-", 1)
                return cls(int(a), int(b))
            except Exception:
                log.warning("Bad NEXUS_SCORING_WINDOW_IST=%r — using default", spec)
        return cls()


@dataclass
class ScoringLoopStatus:
    started_at:      datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at:     Optional[datetime] = None
    last_run_ms:     int       = 0
    scored_total:    int       = 0
    scored_24h:      int       = 0
    queued_total:    int       = 0
    learning_users:  int       = 0
    in_window:       bool      = False
    idle_triggered:  bool      = False


# ============================================================================
# Helpers — IST time gates
# ============================================================================

def _now_ist_hour() -> int:
    """Return the IST hour (0-23) regardless of host timezone."""
    return ((datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).hour)


def _in_window(cfg: ScoringWindowConfig) -> bool:
    h = _now_ist_hour()
    if cfg.start_hour_ist <= cfg.end_hour_ist:
        return cfg.start_hour_ist <= h < cfg.end_hour_ist
    # wrap (e.g. 23..6)
    return h >= cfg.start_hour_ist or h < cfg.end_hour_ist


# ============================================================================
# Bayesian dimension-weight learner
# ============================================================================

DIMENSIONS = list(SCORING_WEIGHTS.keys())   # ordered, 9 items
LEARN_MIN_SAMPLES = 30
LEARN_DELTA_CLIP  = 0.08


def _compute_dimension_deltas(
    history: list[dict],
) -> dict[str, float]:
    """
    Given the user's scored+actioned history, return a delta-weight dict.

    delta_d = (mean(dim_d | APPLIED) - mean(dim_d | SKIPPED)) / 200

    `200` is a conservative scaler so a 50-point swing per dimension only
    shifts that dimension by 0.25 — combined with the LEARN_DELTA_CLIP this
    keeps total weights near the global mean.
    """
    applied = [r for r in history if r.get("user_action") == "APPLIED"]
    skipped = [r for r in history if r.get("user_action") == "SKIPPED"]
    if len(applied) < LEARN_MIN_SAMPLES // 3 or len(skipped) < LEARN_MIN_SAMPLES // 3:
        return {}
    deltas: dict[str, float] = {}
    for d in DIMENSIONS:
        a_vals = [int(r.get(d) or 0) for r in applied]
        s_vals = [int(r.get(d) or 0) for r in skipped]
        if not a_vals or not s_vals:
            continue
        diff = (sum(a_vals) / len(a_vals)) - (sum(s_vals) / len(s_vals))
        delta = diff / 200.0
        delta = max(-LEARN_DELTA_CLIP, min(LEARN_DELTA_CLIP, delta))
        if abs(delta) >= 0.005:
            deltas[d] = round(delta, 4)
    return deltas


# ============================================================================
# ScoringLoop
# ============================================================================

class ScoringLoop:
    """
    Background task that fans out the scoring engine across users.

    The loop is *cooperative* — it yields between users and between
    batches so other parts of the runtime (orchestrator, dashboard) keep
    responsive. It also breaks out of the work loop when the window
    closes mid-run, picking up where it left off the next tick.
    """

    BATCH_SIZE = 25                       # jobs per user per batch
    USERS_PER_TICK = 5                    # how many users to advance per pass
    MAX_QUEUE_PER_RUN = 200               # cap so a giant backlog can't lock the dyno

    def __init__(
        self,
        db: Any,
        scoring_engine: Any,
        orchestrator: Any,
        access: Optional[Any] = None,
        cfg: Optional[ScoringWindowConfig] = None,
    ) -> None:
        self.db        = db
        self.scoring   = scoring_engine
        self.orch      = orchestrator
        self.access    = access
        self.cfg       = cfg or ScoringWindowConfig.from_env()
        self.status    = ScoringLoopStatus()
        self._task:        Optional[asyncio.Task] = None
        self._stop:        asyncio.Event = asyncio.Event()
        self._priority_q:  asyncio.Queue = asyncio.Queue()      # user_ids needing immediate rescoring
        self._last_orch_idle_check: float = 0.0

    # ─────────────────────────── lifecycle ──────────────────────────────

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="nexus.scoring_loop")
        log.info("scoring_loop.started window=%02d:00-%02d:00 IST",
                 self.cfg.start_hour_ist, self.cfg.end_hour_ist)

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def enqueue_user(self, user_id: int) -> None:
        """Trigger an immediate full re-score for one user (e.g. new CV)."""
        await self._priority_q.put(user_id)
        log.info("scoring_loop.user_enqueued user_id=%s", user_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "started_at":     self.status.started_at.isoformat(),
            "last_run_at":    self.status.last_run_at.isoformat() if self.status.last_run_at else None,
            "last_run_ms":    self.status.last_run_ms,
            "scored_total":   self.status.scored_total,
            "scored_24h":     self.status.scored_24h,
            "queued_total":   self.status.queued_total,
            "learning_users": self.status.learning_users,
            "in_window":      self.status.in_window,
            "idle_triggered": self.status.idle_triggered,
            "window_ist":     f"{self.cfg.start_hour_ist:02d}:00-{self.cfg.end_hour_ist:02d}:00",
        }

    # ─────────────────────────── main loop ──────────────────────────────

    async def _run(self) -> None:
        """The async loop — wakes every tick_seconds, runs work when allowed."""
        while not self._stop.is_set():
            try:
                # Priority users first (CV upload trigger) — always ok to run
                if not self._priority_q.empty():
                    uid = await self._priority_q.get()
                    await self._score_user(uid, full_backfill=True)

                # Then the regular gating: in-window OR orchestrator idle
                in_win = _in_window(self.cfg)
                idle   = await self._orchestrator_idle()
                self.status.in_window = in_win
                self.status.idle_triggered = idle and not in_win

                if in_win or idle:
                    t0 = time.monotonic()
                    n = await self._run_one_pass()
                    self.status.last_run_at = datetime.now(timezone.utc)
                    self.status.last_run_ms = int((time.monotonic() - t0) * 1000)
                    log.info(
                        "scoring_loop.pass scored=%d ms=%d in_win=%s idle=%s",
                        n, self.status.last_run_ms, in_win, idle,
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("scoring_loop.pass_failed (continuing)")

            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.cfg.tick_seconds,
                )
            except asyncio.TimeoutError:
                pass

    # ─────────────────────────── one pass ───────────────────────────────

    async def _run_one_pass(self) -> int:
        users = await self._list_active_users()
        if not users:
            return 0

        scored_this_pass = 0
        # round-robin a small slice of users this tick — keeps memory low
        slice_users = users[: self.USERS_PER_TICK]
        for u in slice_users:
            try:
                n = await self._score_user(u.user_id, full_backfill=False)
                scored_this_pass += n
                if scored_this_pass >= self.MAX_QUEUE_PER_RUN:
                    break
            except Exception:
                log.exception("scoring_loop.user_pass_failed user_id=%s", u.user_id)
            await asyncio.sleep(0)               # cooperative yield
        # rotate users so next tick gets different ones
        users.append(users.pop(0))               # pure local; DAO returns same order each time
        return scored_this_pass

    async def _list_active_users(self) -> list[Any]:
        getter = getattr(self.db, "list_active_users_with_cv", None)
        if getter is None:
            log.debug("scoring_loop.no_user_lister — using single admin fallback")
            return []
        try:
            return await getter()
        except Exception:
            log.exception("scoring_loop.list_users_failed")
            return []

    # ─────────────────────────── per-user score ─────────────────────────

    async def _score_user(self, user_id: int, *, full_backfill: bool) -> int:
        """
        Score a batch of unscored jobs for this user. If full_backfill, repeat
        until empty (used by CV-upload trigger). Returns count scored.
        """
        # Pull learned dimension weights for this user (Bayesian deltas)
        try:
            deltas = await self.db.get_dimension_weight_deltas(user_id)
        except Exception:
            deltas = {}
        weights = self._weights_for_user(deltas)

        # Resolve the user's profile — minimal dict so the scoring engine
        # gets stipend floor, location preference, etc.
        profile = await self._build_user_profile(user_id)

        scored = 0
        while True:
            try:
                rows = await self.db.fetch_unscored_jobs_for_user(
                    user_id, limit=self.BATCH_SIZE,
                )
            except Exception:
                log.exception("scoring_loop.fetch_unscored_failed user_id=%s", user_id)
                return scored
            if not rows:
                break

            for r in rows:
                try:
                    job = self._row_to_normalised_job(r)
                    bd  = await self.scoring.score(job, profile)

                    # Apply per-user weight deltas without re-running LLM dims:
                    # nudge the final_score by Σ delta_d × dim_d, capped ±10
                    if deltas:
                        nudge = sum(
                            deltas.get(d, 0.0) * int(getattr(bd, d, 0))
                            for d in DIMENSIONS
                        )
                        nudge = max(-10.0, min(10.0, nudge))
                        bd.final_score = max(0, min(100, bd.final_score + int(round(nudge))))
                        # Re-route after nudge so digest decisions reflect the new score
                        from core.scoring_engine_v2 import route as _route
                        bd.routing = _route(bd.final_score)

                    await self.db.store_user_score(user_id, bd)
                    scored += 1
                    self.status.scored_total += 1
                    self.status.scored_24h += 1

                    # Routing
                    await self._route_after_score(user_id, job, bd)
                except Exception:
                    log.exception(
                        "scoring_loop.score_failed user_id=%s job_id=%s",
                        user_id, r.get("job_id"),
                    )
                await asyncio.sleep(0)

            if not full_backfill:
                break                            # one batch per tick in normal mode

        # Refresh learner stats for this user (cheap)
        try:
            await self._update_learner(user_id)
        except Exception:
            log.exception("scoring_loop.learner_failed user_id=%s", user_id)
        return scored

    # ─────────────────────────── routing per role ───────────────────────

    async def _route_after_score(
        self, user_id: int, job: NormalisedJob, bd: Any,
    ) -> None:
        """
        Decide what to do with a freshly-scored (user, job) pair:
          • ADMIN/POWER + auto_apply_on + score ≥ 80 → enqueue HIGH priority
          • Anyone with TAP_APPLY_MID + score 40-79  → digest pending review
          • Anyone with score ≥ 80 but no auto       → digest pending review
          • score < 40 → already saved, no-op
        """
        if bd.final_score < ROUTING_THRESHOLDS["MANUAL_REVIEW"]:
            return                                # silent save (REJECT)

        # Resolve the user's role + auto_apply preference
        role, auto_on, role_boost = await self._resolve_user_role(user_id)

        urgency = int(getattr(bd, "bonuses", {}).get("deadline_meta", {}).get("cliff", 0) or 0)
        priority_score = role_boost + int(bd.final_score) + urgency

        auto_high = (
            bd.final_score >= ROUTING_THRESHOLDS["AUTO_APPLY_PRIORITY"]
            and auto_on
            and role in (Role.ADMIN, Role.POWER_USER)
        )

        if auto_high:
            # Push into the orchestrator queue with role boost
            try:
                await self._enqueue_for_user(
                    user_id=user_id, job=job, bd=bd,
                    role_boost=role_boost,
                    priority_score=priority_score,
                    source="auto",
                )
                self.status.queued_total += 1
            except Exception:
                log.exception("scoring_loop.enqueue_failed user_id=%s job_id=%s",
                              user_id, job.job_id)
        # else: MID/HIGH-not-auto stays in job_scores with user_action=NULL — the
        # dashboard will surface it via /pending and the daily digest, where the
        # one-tap Apply button hits orchestrator.force_apply(user_id, job_id).

    async def _enqueue_for_user(
        self, *, user_id: int, job: NormalisedJob, bd: Any,
        role_boost: int, priority_score: int, source: str,
    ) -> None:
        from core.orchestrator import QueueRow, QueueState
        from core.nexus_config import is_apply_window_open

        now = datetime.now(timezone.utc)
        urg = int(getattr(bd, "bonuses", {}).get("deadline_meta", {}).get("cliff", 0) or 0)
        row = QueueRow(
            job_id            = job.job_id,
            portal            = job.portal,
            score             = int(bd.final_score),
            deadline_urgency  = urg,
            apply_window_open = is_apply_window_open(
                job.portal,
                ((now + timedelta(hours=5, minutes=30)).strftime("%H:%M")),
            ),
            risk_level        = "HIGH" if bd.final_score >= 80 else "MED",
            state             = QueueState.QUEUED,
            attempts          = 0,
            queued_at         = now,
            rescore_at        = now + timedelta(hours=2),
        )
        # Stamp multi-tenant attrs so the DAO upsert can persist them
        row.user_id        = user_id              # type: ignore[attr-defined]
        row.role_boost     = role_boost           # type: ignore[attr-defined]
        row.priority_score = priority_score       # type: ignore[attr-defined]
        row.source         = source               # type: ignore[attr-defined]
        await self.db.upsert_queue_row(row)

    # ─────────────────────────── learner ────────────────────────────────

    async def _update_learner(self, user_id: int) -> None:
        getter = getattr(self.db, "get_user_action_history", None)
        upsert = getattr(self.db, "upsert_dimension_weight", None)
        if getter is None or upsert is None:
            return
        history = await getter(user_id, last_n=200)
        if len(history) < LEARN_MIN_SAMPLES:
            return
        deltas = _compute_dimension_deltas(history)
        if not deltas:
            return
        for dim, delta in deltas.items():
            try:
                await upsert(user_id, dim, float(delta), len(history))
            except Exception:
                log.exception("scoring_loop.learner_upsert_failed user_id=%s dim=%s",
                              user_id, dim)
        self.status.learning_users = max(self.status.learning_users, 1)
        log.info("scoring_loop.learner user_id=%s deltas=%s", user_id, deltas)

    # ─────────────────────────── helpers ────────────────────────────────

    async def _resolve_user_role(self, user_id: int) -> tuple[Role, bool, int]:
        """Return (role, auto_apply_on, role_boost). Defaults to STANDARD/0."""
        # Try DAO direct
        pool = getattr(self.db, "_pool", None)
        if pool is None:
            return Role.STANDARD_USER, False, 0
        try:
            async with pool.acquire() as c:
                row = await c.fetchrow(
                    "SELECT role, auto_apply_on FROM nexus_users WHERE user_id = $1",
                    user_id,
                )
            if not row:
                return Role.STANDARD_USER, False, 0
            role = Role(row["role"])
            return role, bool(row["auto_apply_on"]), ROLE_BOOST.get(role, 0)
        except Exception:
            return Role.STANDARD_USER, False, 0

    async def _build_user_profile(self, user_id: int) -> dict[str, Any]:
        """
        Build the small profile dict the scoring engine expects.
        We don't pass the raw CV text — the embedding is already what
        ProfileMatcher uses. We do pass min_stipend / preferred_cities from
        the user's stored profile JSON.
        """
        pool = getattr(self.db, "_pool", None)
        prof: dict[str, Any] = {"min_stipend": 20000, "preferred_cities": []}
        if pool is None:
            return prof
        try:
            async with pool.acquire() as c:
                row = await c.fetchrow(
                    "SELECT profile FROM nexus_users WHERE user_id = $1", user_id,
                )
            if row and row["profile"]:
                p = row["profile"]
                if isinstance(p, dict):
                    prof.update(p)
        except Exception:
            pass
        return prof

    @staticmethod
    def _row_to_normalised_job(r: dict) -> NormalisedJob:
        return NormalisedJob(
            job_id   = r["job_id"],
            portal   = r["portal"],
            company  = r["company"],
            title    = r["title"],
            jd_text  = r.get("jd_text") or "",
            location = r.get("location"),
            stipend  = r.get("stipend_raw"),
            deadline = r.get("deadline"),
            posted_at= r["posted_at"],
            raw_url  = r.get("raw_url", ""),
        )

    # ─────────────────────────── orchestrator-idle gate ─────────────────

    async def _orchestrator_idle(self) -> bool:
        """
        Treats the orchestrator as 'idle' when its queue is empty and no
        applies have happened in the last `idle_minutes_before_run` minutes.
        """
        # Light cache so we don't hit the DB every tick
        now = time.monotonic()
        if now - self._last_orch_idle_check < 60:
            return False
        self._last_orch_idle_check = now

        pool = getattr(self.db, "_pool", None)
        if pool is None:
            return False
        try:
            async with pool.acquire() as c:
                queued = await c.fetchval(
                    "SELECT count(*) FROM job_queue WHERE state IN ('QUEUED','RUNNING','DISPATCHING')"
                )
                last_apply = await c.fetchval(
                    "SELECT max(applied_at) FROM applied_jobs"
                )
        except Exception:
            return False

        if int(queued or 0) > 0:
            return False
        if last_apply is None:
            return True
        gap_min = (datetime.now(timezone.utc) - last_apply).total_seconds() / 60
        return gap_min >= self.cfg.idle_minutes_before_run

    # ─────────────────────────── weights helper ─────────────────────────

    @staticmethod
    def _weights_for_user(deltas: dict[str, float]) -> dict[str, float]:
        """Combine global SCORING_WEIGHTS with per-user deltas (renormalised)."""
        if not deltas:
            return dict(SCORING_WEIGHTS)
        out = {d: SCORING_WEIGHTS[d] + deltas.get(d, 0.0) for d in DIMENSIONS}
        # Renormalise to sum=1 (paranoia — clip already prevents large sway)
        s = sum(out.values())
        if s <= 0:
            return dict(SCORING_WEIGHTS)
        return {k: v / s for k, v in out.items()}


__all__ = [
    "ScoringLoop",
    "ScoringWindowConfig",
    "ScoringLoopStatus",
    "DIMENSIONS",
    "LEARN_MIN_SAMPLES",
    "LEARN_DELTA_CLIP",
]
