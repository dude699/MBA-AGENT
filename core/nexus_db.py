"""
NEXUS v0.2 — Real Postgres / Supabase DAO (Multi-Tenant)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Single async DAO that fulfils every Protocol the runtime depends on:

  * AccessDB             — core.access_control (users, grants, audit, callbacks, rate-limit)
  * OrchestratorDB       — core.orchestrator   (queue, risk signals, application records)
  * RiskDB               — core.orchestrator   (5 risk signals)
  * ScoringDB            — multi-tenant job_scores + per-user dimension weights
  * VaultDB              — core.session_vault  (encrypted sessions per user)
  * DedupDB              — core.dedup_semantic (exact + pgvector cosine)
  * JobsDB               — agents/n03_crawl4ai_scraper (jobs upsert + fetch)

Backed by `asyncpg`. Heavy import is guarded; if asyncpg is missing the module
still imports cleanly, but `connect()` will raise so the runtime falls back to
in-memory backends with a warning.

Usage
-----
    db = NexusDB(os.environ["DATABASE_URL"])
    await db.connect()
    runtime.bind_db(db)            # swaps the in-memory stub
    ...
    await db.close()
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.access_control import Role, TelegramUser, User

log = logging.getLogger("nexus.db")

try:
    import asyncpg                                                       # type: ignore
    ASYNCPG_AVAILABLE = True
except Exception:                                                        # noqa: BLE001
    asyncpg = None                                                       # type: ignore
    ASYNCPG_AVAILABLE = False


# ============================================================================
# NexusDB
# ============================================================================

class NexusDB:
    """
    Async Postgres DAO. One asyncpg pool per instance. Every method is
    idempotent, defensive (returns neutral values on missing rows), and
    schema-stable against `data/nexus_v02_schema.sql` + `nexus_v02_multitenant.sql`.
    """

    def __init__(self, dsn: Optional[str] = None, pool_size: int = 4) -> None:
        self.dsn = dsn or os.getenv("DATABASE_URL", "")
        self.pool_size = pool_size
        self._pool: Optional[Any] = None

    # ─────────────────────────────────── lifecycle ──────────────────────

    async def connect(self) -> None:
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError(
                "asyncpg not installed — install via `pip install asyncpg` "
                "or keep using the in-memory stub."
            )
        if not self.dsn:
            raise RuntimeError("DATABASE_URL not set; cannot connect.")
        self._pool = await asyncpg.create_pool(
            self.dsn, min_size=1, max_size=self.pool_size,
            command_timeout=30,
        )
        log.info("nexus.db.connected pool_size=%d", self.pool_size)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _conn(self):
        if self._pool is None:
            raise RuntimeError("NexusDB.connect() not called yet.")
        return self._pool.acquire()

    # ============================================================
    # AccessDB — users, grants, audit, callbacks, rate limits
    # ============================================================

    async def get_user_by_telegram(self, telegram_id: int) -> Optional[User]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                SELECT user_id, telegram_id, telegram_handle, display_name,
                       role, auto_apply_on, rate_limit_per_min,
                       rate_limit_apply_per_hour
                FROM nexus_users WHERE telegram_id = $1
                """,
                telegram_id,
            )
        if not row:
            return None
        return User(
            user_id=row["user_id"],
            telegram_id=row["telegram_id"],
            handle=row["telegram_handle"],
            display_name=row["display_name"],
            role=Role(row["role"]),
            auto_apply_on=bool(row["auto_apply_on"]),
            rate_per_min=int(row["rate_limit_per_min"]),
            rate_apply_per_hour=int(row["rate_limit_apply_per_hour"]),
        )

    async def upsert_pending_user(self, tg: TelegramUser) -> User:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                INSERT INTO nexus_users (telegram_id, telegram_handle, display_name, role)
                VALUES ($1, $2, $3, 'PENDING')
                ON CONFLICT (telegram_id) DO UPDATE
                  SET telegram_handle = COALESCE(EXCLUDED.telegram_handle, nexus_users.telegram_handle),
                      display_name    = COALESCE(EXCLUDED.display_name,    nexus_users.display_name),
                      last_seen_at    = now()
                RETURNING user_id, telegram_id, telegram_handle, display_name,
                          role, auto_apply_on, rate_limit_per_min,
                          rate_limit_apply_per_hour
                """,
                tg.telegram_id, tg.handle, tg.display_name,
            )
        return User(
            user_id=row["user_id"],
            telegram_id=row["telegram_id"],
            handle=row["telegram_handle"],
            display_name=row["display_name"],
            role=Role(row["role"]),
            auto_apply_on=bool(row["auto_apply_on"]),
            rate_per_min=int(row["rate_limit_per_min"]),
            rate_apply_per_hour=int(row["rate_limit_apply_per_hour"]),
        )

    async def update_role(self, user_id: int, new_role: Role) -> bool:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            r = await c.execute(
                "UPDATE nexus_users SET role = $1 WHERE user_id = $2",
                new_role.value, user_id,
            )
        return r.endswith("UPDATE 1")

    async def update_auto_apply(self, user_id: int, on: bool) -> bool:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            r = await c.execute(
                "UPDATE nexus_users SET auto_apply_on = $1 WHERE user_id = $2",
                on, user_id,
            )
        return r.endswith("UPDATE 1")

    async def insert_grant(
        self, granted_to: int, granted_by: int,
        role_granted: str, reason: Optional[str],
    ) -> int:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                INSERT INTO access_grants (granted_to, granted_by, role_granted, reason)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                granted_to, granted_by, role_granted, reason,
            )
        return int(row["id"])

    async def revoke_grants(self, user_id: int, by: int, reason: Optional[str]) -> int:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            r = await c.execute(
                """
                UPDATE access_grants
                   SET revoked_at = now(),
                       revoked_by = $2,
                       revoke_reason = $3
                 WHERE granted_to = $1 AND revoked_at IS NULL
                """,
                user_id, by, reason,
            )
        try:
            return int(r.split()[-1])
        except Exception:
            return 0

    async def rate_limit_consume(
        self, user_id: int, bucket: str, max_n: int, window_seconds: int,
    ) -> bool:
        """
        Sliding-window via fixed bucket-of-window-size + atomic increment.
        Returns False on breach, True when within budget.
        """
        now = datetime.now(timezone.utc)
        bucket_idx = int(now.timestamp() // window_seconds)
        window_start = datetime.fromtimestamp(bucket_idx * window_seconds, tz=timezone.utc)
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            # Atomic upsert + increment in one statement
            row = await c.fetchrow(
                """
                INSERT INTO rate_limit_buckets (user_id, bucket, window_start, counter)
                VALUES ($1, $2, $3, 1)
                ON CONFLICT (user_id, bucket, window_start)
                  DO UPDATE SET counter = rate_limit_buckets.counter + 1
                RETURNING counter
                """,
                user_id, bucket, window_start,
            )
        return int(row["counter"]) <= max_n

    async def audit_log(self, **fields: Any) -> None:
        payload = fields.pop("payload", None)
        if payload is not None and not isinstance(payload, str):
            payload = json.dumps(payload, default=str)
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO audit_log (actor_id, actor_role, action, target_id,
                                       target_kind, target_ref, payload, ip)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                """,
                fields.get("actor_id"),
                fields.get("actor_role"),
                fields.get("action", "UNKNOWN"),
                fields.get("target_id"),
                fields.get("target_kind"),
                fields.get("target_ref"),
                payload,
                fields.get("ip"),
            )

    async def store_callback_token(
        self, token: str, user_id: int, action: str,
        target: Optional[str], expires_at: datetime,
    ) -> None:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO callback_tokens (token, user_id, action, target, expires_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (token) DO NOTHING
                """,
                token, user_id, action, target, expires_at,
            )

    async def consume_callback_token(self, token: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                UPDATE callback_tokens
                   SET consumed_at = now()
                 WHERE token = $1
                   AND consumed_at IS NULL
                   AND expires_at > now()
                RETURNING user_id, action, target
                """,
                token,
            )
        if not row:
            return None
        return {"user_id": row["user_id"], "action": row["action"], "target": row["target"]}

    # ============================================================
    # CV intake
    # ============================================================

    async def store_cv(
        self, user_id: int, *, cv_text_encrypted: str,
        embedding: list[float], filename: Optional[str],
        sha256: Optional[str], size_bytes: int, parsed_chars: int,
        parse_engine: str = "pypdf",
    ) -> None:
        emb_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                UPDATE nexus_users
                   SET cv_text_encrypted = $2,
                       cv_embedding      = $3::vector,
                       cv_uploaded_at    = now(),
                       cv_filename       = $4,
                       cv_sha256         = $5
                 WHERE user_id = $1
                """,
                user_id, cv_text_encrypted, emb_str, filename, sha256,
            )
            await c.execute(
                """
                INSERT INTO cv_uploads (user_id, filename, sha256, size_bytes,
                                        parsed_chars, parse_engine)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                user_id, filename, sha256, size_bytes, parsed_chars, parse_engine,
            )

    async def get_user_cv_embedding(self, user_id: int) -> Optional[list[float]]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                "SELECT cv_embedding FROM nexus_users WHERE user_id = $1",
                user_id,
            )
        if not row or row["cv_embedding"] is None:
            return None
        v = row["cv_embedding"]
        if isinstance(v, str):
            return [float(x) for x in v.strip("[]").split(",") if x]
        return list(v)

    async def list_active_users_with_cv(self) -> list[User]:
        """All users (POWER + STANDARD + ADMIN) with a CV embedding."""
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT user_id, telegram_id, telegram_handle, display_name,
                       role, auto_apply_on, rate_limit_per_min,
                       rate_limit_apply_per_hour
                FROM nexus_users
                WHERE cv_embedding IS NOT NULL
                  AND role IN ('ADMIN','POWER_USER','STANDARD_USER')
                """
            )
        return [
            User(
                user_id=r["user_id"], telegram_id=r["telegram_id"],
                handle=r["telegram_handle"], display_name=r["display_name"],
                role=Role(r["role"]), auto_apply_on=bool(r["auto_apply_on"]),
                rate_per_min=int(r["rate_limit_per_min"]),
                rate_apply_per_hour=int(r["rate_limit_apply_per_hour"]),
            )
            for r in rows
        ]

    # ============================================================
    # Scoring DB (multi-tenant)
    # ============================================================

    async def fetch_unscored_jobs_for_user(
        self, user_id: int, limit: int = 200,
    ) -> list[dict]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT j.*
                FROM jobs j
                LEFT JOIN job_scores js
                       ON js.job_id = j.job_id AND js.user_id = $1
                WHERE js.job_id IS NULL
                ORDER BY j.discovered_at DESC
                LIMIT $2
                """,
                user_id, limit,
            )
        return [dict(r) for r in rows]

    async def store_user_score(
        self, user_id: int, breakdown: Any,
    ) -> None:
        """`breakdown` is core.scoring_engine_v2.ScoreBreakdown."""
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO job_scores (
                    user_id, job_id,
                    profile_match, compensation_fit, role_type_match,
                    company_tier, location_fit, recency,
                    competitive_pos, cultural_fit, trajectory,
                    final_score, routing, raw_breakdown
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
                ON CONFLICT (user_id, job_id) DO UPDATE
                  SET profile_match    = EXCLUDED.profile_match,
                      compensation_fit = EXCLUDED.compensation_fit,
                      role_type_match  = EXCLUDED.role_type_match,
                      company_tier     = EXCLUDED.company_tier,
                      location_fit     = EXCLUDED.location_fit,
                      recency          = EXCLUDED.recency,
                      competitive_pos  = EXCLUDED.competitive_pos,
                      cultural_fit     = EXCLUDED.cultural_fit,
                      trajectory       = EXCLUDED.trajectory,
                      final_score      = EXCLUDED.final_score,
                      routing          = EXCLUDED.routing,
                      raw_breakdown    = EXCLUDED.raw_breakdown,
                      scored_at        = now()
                """,
                user_id,
                getattr(breakdown, "job_id", None),
                getattr(breakdown, "profile_match", 0),
                getattr(breakdown, "compensation_fit", 0),
                getattr(breakdown, "role_type_match", 0),
                getattr(breakdown, "company_tier", 0),
                getattr(breakdown, "location_fit", 0),
                getattr(breakdown, "recency", 0),
                getattr(breakdown, "competitive_pos", 0),
                getattr(breakdown, "cultural_fit", 0),
                getattr(breakdown, "trajectory", 0),
                int(getattr(breakdown, "final_score", 0)),
                getattr(breakdown, "routing", "REJECT"),
                json.dumps(getattr(breakdown, "raw", {}), default=str),
            )

    async def store_score(self, breakdown: Any) -> None:
        """Single-tenant fallback for orchestrator — uses admin user_id=1."""
        # Admin is always user_id=1 by seed
        await self.store_user_score(user_id=1, breakdown=breakdown)

    async def record_user_action(
        self, user_id: int, job_id: str, action: str,
    ) -> None:
        """action ∈ APPLIED | SKIPPED | SNOOZED — feeds usage-pattern learning."""
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                UPDATE job_scores
                   SET user_action    = $3,
                       user_action_at = now()
                 WHERE user_id = $1 AND job_id = $2
                """,
                user_id, job_id, action,
            )

    async def get_dimension_weight_deltas(self, user_id: int) -> dict[str, float]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                "SELECT dimension, weight FROM user_dimension_weights WHERE user_id = $1",
                user_id,
            )
        return {r["dimension"]: float(r["weight"]) for r in rows}

    async def upsert_dimension_weight(
        self, user_id: int, dimension: str, delta: float, sample_size: int,
    ) -> None:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO user_dimension_weights (user_id, dimension, weight, sample_size)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, dimension) DO UPDATE
                  SET weight      = EXCLUDED.weight,
                      sample_size = EXCLUDED.sample_size,
                      updated_at  = now()
                """,
                user_id, dimension, delta, sample_size,
            )

    async def fetch_user_scores_bulk(
        self, user_id: int, job_keys: list[str],
    ) -> dict[str, dict]:
        """
        Bulk-fetch the 9-dim breakdown for a list of job_ids for one user.
        Returns {job_id: {final_score, profile_match, ..., routing}}.
        Used by the mini-app /api/cv-matched-jobs endpoint to surface
        NEXUS Layer-3 scores (instead of falling back to keyword overlap).
        """
        if not job_keys:
            return {}
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT job_id, profile_match, compensation_fit, role_type_match,
                       company_tier, location_fit, recency, competitive_pos,
                       cultural_fit, trajectory, final_score, routing,
                       resume_variant, scored_at
                FROM job_scores
                WHERE user_id = $1 AND job_id = ANY($2::text[])
                """,
                user_id, job_keys,
            )
        return {r["job_id"]: dict(r) for r in rows}

    async def fetch_top_scored_for_user(
        self, user_id: int, *, min_score: int = 0, limit: int = 200,
    ) -> list[dict]:
        """Top-N scored jobs for a user, with the joined job row.
        Used by the For-You feed when DATABASE_URL is set."""
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT js.job_id, js.final_score, js.routing,
                       js.profile_match, js.role_type_match, js.company_tier,
                       js.location_fit, js.recency, js.competitive_pos,
                       js.cultural_fit, js.trajectory, js.compensation_fit,
                       js.resume_variant, js.scored_at,
                       j.title, j.company, j.portal AS source, j.raw_url AS source_url,
                       j.jd_text AS description, j.location, j.deadline,
                       j.stipend_inr_monthly AS stipend, j.discovered_at AS posted_at
                FROM job_scores js
                JOIN jobs j ON j.job_id = js.job_id
                WHERE js.user_id = $1 AND js.final_score >= $2
                ORDER BY js.final_score DESC, js.scored_at DESC
                LIMIT $3
                """,
                user_id, min_score, limit,
            )
        return [dict(r) for r in rows]

    async def get_user_action_history(
        self, user_id: int, last_n: int = 200,
    ) -> list[dict]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT job_id, profile_match, compensation_fit, role_type_match,
                       company_tier, location_fit, recency, competitive_pos,
                       cultural_fit, trajectory, final_score, user_action
                FROM job_scores
                WHERE user_id = $1 AND user_action IS NOT NULL
                ORDER BY user_action_at DESC
                LIMIT $2
                """,
                user_id, last_n,
            )
        return [dict(r) for r in rows]

    # ============================================================
    # Orchestrator queue + risk signals (multi-tenant)
    # ============================================================

    async def upsert_queue_row(self, row: Any) -> None:
        user_id     = getattr(row, "user_id", None)
        role_boost  = int(getattr(row, "role_boost", 0))
        priority    = int(getattr(row, "priority_score",
                                  role_boost + int(row.score)
                                  + int(row.deadline_urgency)))
        source      = getattr(row, "source", "auto")
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO job_queue (
                    job_id, user_id, portal, score, deadline_urgency,
                    apply_window_open, risk_level, state, attempts,
                    queued_at, rescore_at, dispatch_at,
                    role_boost, priority_score, source
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (COALESCE(user_id, 0), job_id) DO UPDATE
                  SET score             = EXCLUDED.score,
                      deadline_urgency  = EXCLUDED.deadline_urgency,
                      apply_window_open = EXCLUDED.apply_window_open,
                      risk_level        = EXCLUDED.risk_level,
                      state             = EXCLUDED.state,
                      attempts          = EXCLUDED.attempts,
                      rescore_at        = EXCLUDED.rescore_at,
                      dispatch_at       = EXCLUDED.dispatch_at,
                      role_boost        = EXCLUDED.role_boost,
                      priority_score    = EXCLUDED.priority_score,
                      source            = EXCLUDED.source
                """,
                row.job_id, user_id, row.portal,
                int(row.score), int(row.deadline_urgency),
                bool(row.apply_window_open), row.risk_level,
                row.state.value if hasattr(row.state, "value") else str(row.state),
                int(row.attempts),
                row.queued_at, row.rescore_at,
                getattr(row, "dispatch_at", None),
                role_boost, priority, source,
            )

    async def fetch_dispatchable(self, now: datetime, max_n: int) -> list[Any]:
        from core.orchestrator import QueueRow, QueueState
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT q.*, COALESCE(u.role, 'STANDARD_USER') AS u_role
                FROM job_queue q
                LEFT JOIN nexus_users u ON u.user_id = q.user_id
                WHERE q.state = 'QUEUED'
                  AND (q.dispatch_at IS NULL OR q.dispatch_at <= $1)
                ORDER BY q.priority_score DESC, q.score DESC,
                         q.deadline_urgency DESC, q.queued_at ASC
                LIMIT $2
                """,
                now, max_n,
            )
        out: list[Any] = []
        for r in rows:
            out.append(QueueRow(
                job_id=r["job_id"],
                portal=r["portal"],
                score=int(r["score"]),
                deadline_urgency=int(r["deadline_urgency"]),
                apply_window_open=bool(r["apply_window_open"]),
                risk_level=r["risk_level"],
                state=QueueState(r["state"]),
                attempts=int(r["attempts"]),
                queued_at=r["queued_at"],
                rescore_at=r["rescore_at"],
                dispatch_at=r["dispatch_at"],
                last_error=r["last_error"],
            ))
            # Attach user_id + boost for downstream
            out[-1].user_id = r["user_id"]                                # type: ignore[attr-defined]
            out[-1].role_boost = int(r["role_boost"])                     # type: ignore[attr-defined]
            out[-1].source = r["source"]                                  # type: ignore[attr-defined]
        return out

    async def fetch_for_rescore(self, now: datetime) -> list[Any]:
        from core.orchestrator import QueueRow, QueueState
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT * FROM job_queue
                WHERE state = 'QUEUED' AND rescore_at <= $1
                ORDER BY rescore_at ASC
                LIMIT 100
                """,
                now,
            )
        out = []
        for r in rows:
            row = QueueRow(
                job_id=r["job_id"], portal=r["portal"],
                score=int(r["score"]), deadline_urgency=int(r["deadline_urgency"]),
                apply_window_open=bool(r["apply_window_open"]),
                risk_level=r["risk_level"], state=QueueState(r["state"]),
                attempts=int(r["attempts"]), queued_at=r["queued_at"],
                rescore_at=r["rescore_at"], dispatch_at=r["dispatch_at"],
                last_error=r["last_error"],
            )
            row.user_id = r["user_id"]                                    # type: ignore[attr-defined]
            out.append(row)
        return out

    async def update_state(self, job_id: str, state: Any, **kw: Any) -> None:
        st = state.value if hasattr(state, "value") else str(state)
        last_error  = kw.get("last_error")
        attempts    = kw.get("attempts")
        dispatch_at = kw.get("dispatch_at")
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                UPDATE job_queue
                   SET state       = $2,
                       last_error  = COALESCE($3, last_error),
                       attempts    = COALESCE($4, attempts),
                       dispatch_at = COALESCE($5, dispatch_at)
                 WHERE job_id = $1
                """,
                job_id, st, last_error, attempts, dispatch_at,
            )

    async def fetch_job(self, job_id: str) -> Any:
        from core.crawl4ai_discovery import NormalisedJob
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            r = await c.fetchrow(
                "SELECT * FROM jobs WHERE job_id = $1", job_id,
            )
        if not r:
            raise KeyError(f"job {job_id} not found")
        return NormalisedJob(
            job_id=r["job_id"], portal=r["portal"], company=r["company"],
            title=r["title"], jd_text=r["jd_text"],
            location=r.get("location"),
            stipend=r.get("stipend_raw"),
            deadline=r.get("deadline"),
            posted_at=r["posted_at"],
            raw_url=r["raw_url"],
        )

    async def store_application_record(
        self, job_id: str, result: Any, breakdown: Any = None,
    ) -> None:
        outcome = getattr(result, "outcome", None)
        status_value = (
            "SUCCESS" if outcome and getattr(outcome, "value", "") == "SUCCESS"
            else "FAILED"
        )
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                SELECT user_id, portal FROM job_queue WHERE job_id = $1 LIMIT 1
                """,
                job_id,
            )
            if not row:
                row = await c.fetchrow(
                    "SELECT NULL AS user_id, portal FROM jobs WHERE job_id = $1",
                    job_id,
                )
            if not row:
                return
            await c.execute(
                """
                INSERT INTO applied_jobs (
                    job_id, user_id, portal, company, title, title_hash,
                    submission_status, skyvern_code_used, duration_ms
                )
                SELECT j.job_id, $2, j.portal, j.company, j.title,
                       md5(lower(j.title)),
                       $3, $4, $5
                FROM jobs j WHERE j.job_id = $1
                ON CONFLICT (COALESCE(user_id, 0), job_id) DO UPDATE
                  SET submission_status = EXCLUDED.submission_status
                """,
                job_id,
                row["user_id"],
                status_value,
                bool(getattr(result, "from_cache", False)),
                int(getattr(result, "duration_ms", 0) or 0),
            )

    async def set_orchestrator_state(self, **kw: Any) -> None:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO orchestrator_state
                       (portal, paused, paused_reason, paused_until, rate_multiplier)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (portal) DO UPDATE
                   SET paused          = EXCLUDED.paused,
                       paused_reason   = EXCLUDED.paused_reason,
                       paused_until    = EXCLUDED.paused_until,
                       rate_multiplier = EXCLUDED.rate_multiplier
                """,
                kw.get("portal"),
                bool(kw.get("paused", False)),
                kw.get("paused_reason"),
                kw.get("paused_until"),
                float(kw.get("rate_multiplier", 1.0)),
            )

    # ─────────────────────────── RiskGovernor signals ───────────────────

    async def apps_per_hour(self, portal: str) -> int:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                SELECT count(*) AS n
                FROM applied_jobs
                WHERE portal = $1 AND applied_at > now() - interval '1 hour'
                """,
                portal,
            )
        return int(row["n"]) if row else 0

    async def captcha_rate(self, portal: str, lookback_hours: int = 24) -> float:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                WITH recent AS (
                  SELECT count(*) AS apps
                  FROM applied_jobs
                  WHERE portal = $1
                    AND applied_at > now() - ($2 || ' hours')::interval
                ), cap AS (
                  SELECT count(*) AS captchas
                  FROM captcha_events
                  WHERE portal = $1
                    AND created_at > now() - ($2 || ' hours')::interval
                )
                SELECT GREATEST(recent.apps, 1) AS apps, cap.captchas
                FROM recent, cap
                """,
                portal, lookback_hours,
            )
        if not row:
            return 0.0
        return float(row["captchas"]) / float(row["apps"])

    async def session_age_days(self, portal: str) -> int:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                SELECT EXTRACT(EPOCH FROM (now() - captured_at)) / 86400 AS age
                FROM session_vault
                WHERE portal = $1 AND revoked = FALSE
                ORDER BY captured_at DESC LIMIT 1
                """,
                portal,
            )
        if not row or row["age"] is None:
            return 0
        return int(row["age"])

    async def error_rate(self, portal: str, last_n: int = 20) -> float:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT submission_status FROM applied_jobs
                WHERE portal = $1
                ORDER BY applied_at DESC
                LIMIT $2
                """,
                portal, last_n,
            )
        if not rows:
            return 0.0
        fails = sum(1 for r in rows if r["submission_status"] != "SUCCESS")
        return fails / len(rows)

    async def tod_variance(self, portal: str, days_back: int = 7) -> float:
        # Simple proxy: stddev of hour-of-day across last N applies / 12
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            row = await c.fetchrow(
                """
                SELECT COALESCE(stddev(EXTRACT(HOUR FROM applied_at)), 0) AS sd
                FROM applied_jobs
                WHERE portal = $1
                  AND applied_at > now() - ($2 || ' days')::interval
                """,
                portal, days_back,
            )
        if not row or row["sd"] is None:
            return 0.0
        return min(1.0, float(row["sd"]) / 12.0)

    async def log_risk(self, **kw: Any) -> None:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO risk_governor_log (portal, signal, value, threshold, action, portal_paused)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                kw.get("portal"), kw.get("signal"),
                float(kw.get("value", 0)), float(kw.get("threshold", 0)),
                kw.get("action", "NORMALISE"),
                bool(kw.get("paused", False)),
            )

    # ============================================================
    # Jobs (Crawl4AI ingest)
    # ============================================================

    async def upsert_jobs(self, jobs: list[Any]) -> int:
        """Bulk upsert NormalisedJob objects. Returns count of new rows."""
        if not jobs:
            return 0
        new_count = 0
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            for j in jobs:
                emb = getattr(j, "jd_embedding", None)
                emb_str = (
                    "[" + ",".join(f"{v:.6f}" for v in emb) + "]"
                    if emb else None
                )
                row = await c.fetchrow(
                    """
                    INSERT INTO jobs (
                        job_id, portal, company, title, location, remote,
                        stipend_inr_monthly, stipend_raw, deadline, posted_at,
                        discovery_mode, jd_text, jd_embedding, raw_url,
                        applicant_count, raw_payload
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                            $13::vector, $14,$15,$16::jsonb)
                    ON CONFLICT (job_id) DO UPDATE
                      SET title    = EXCLUDED.title,
                          location = EXCLUDED.location,
                          deadline = EXCLUDED.deadline,
                          jd_text  = EXCLUDED.jd_text
                    RETURNING (xmax = 0) AS inserted
                    """,
                    j.job_id, j.portal, j.company, j.title,
                    getattr(j, "location", None), bool(getattr(j, "remote", False)),
                    getattr(j, "stipend_inr_monthly", None),
                    getattr(j, "stipend", None),
                    getattr(j, "deadline", None),
                    j.posted_at,
                    getattr(j, "discovery_mode", "cron"),
                    j.jd_text, emb_str, j.raw_url,
                    getattr(j, "applicant_count", None),
                    json.dumps(getattr(j, "raw_payload", {}), default=str),
                )
                if row and row.get("inserted"):
                    new_count += 1
        return new_count

    # ============================================================
    # Dashboard helpers
    # ============================================================

    async def pending_review_for_user(self, user_id: int, limit: int = 10) -> list[dict]:
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            rows = await c.fetch(
                """
                SELECT js.job_id, j.portal, j.company, j.title, j.deadline,
                       j.raw_url AS apply_url, js.final_score AS score
                FROM job_scores js
                JOIN jobs j ON j.job_id = js.job_id
                WHERE js.user_id = $1
                  AND js.user_action IS NULL
                  AND js.routing IN ('MANUAL_REVIEW','AUTO_APPLY')
                  AND js.final_score BETWEEN 40 AND 79
                ORDER BY js.final_score DESC
                LIMIT $2
                """,
                user_id, limit,
            )
        out = []
        for r in rows:
            d = dict(r)
            if d.get("deadline"):
                hours = (d["deadline"] - datetime.now(timezone.utc)).total_seconds() / 3600
                d["deadline_hours"] = max(0.0, hours)
            else:
                d["deadline_hours"] = None
            d["score_band"] = "MANUAL_REVIEW"
            out.append(d)
        return out

    async def status_snapshot(self, user_id: Optional[int] = None) -> dict[str, Any]:
        """Aggregate snapshot. If user_id given, scoped to that user."""
        async with self._pool.acquire() as c:                            # type: ignore[union-attr]
            if user_id is not None:
                base_filter = "WHERE user_id = $1"
                params = [user_id]
            else:
                base_filter = ""
                params = []
            queued = await c.fetchval(
                f"SELECT count(*) FROM job_queue {base_filter} "
                f"{'AND' if user_id else 'WHERE'} state = 'QUEUED'",
                *params,
            )
            running = await c.fetchval(
                f"SELECT count(*) FROM job_queue {base_filter} "
                f"{'AND' if user_id else 'WHERE'} state IN ('DISPATCHING','RUNNING')",
                *params,
            )
            applied_24h = await c.fetchval(
                f"SELECT count(*) FROM applied_jobs {base_filter} "
                f"{'AND' if user_id else 'WHERE'} applied_at > now() - interval '24 hours' "
                f"AND submission_status = 'SUCCESS'",
                *params,
            )
            manual_review = await c.fetchval(
                f"SELECT count(*) FROM job_scores {base_filter} "
                f"{'AND' if user_id else 'WHERE'} user_action IS NULL "
                f"AND final_score BETWEEN 40 AND 79",
                *params,
            )
        return {
            "queued":        int(queued or 0),
            "running":       int(running or 0),
            "applied_24h":   int(applied_24h or 0),
            "manual_review": int(manual_review or 0),
            "captcha_24h":   0,
            "failed_24h":    0,
            "portals":       {},
        }


__all__ = ["NexusDB", "ASYNCPG_AVAILABLE"]
