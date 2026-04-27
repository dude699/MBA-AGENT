"""
============================================================
JOB RETENTION — Score-tiered TTL purge of stale listings
============================================================

Per the operator request (2026-04-27):

    "jobs posting with low score will be deleted after 15 days
     from listing in database and jobs with good scores will be
     deleted after 25 days of listing"

Rationale
---------
Old low-scoring listings clutter the "For You" tab and waste
Supabase storage on a 500MB free tier. Higher-scoring jobs are
worth holding onto longer because the user is more likely to
actually apply to them — but even high-score jobs become stale
after a month.

Tiers (configurable via env)
----------------------------
- LOW_SCORE_TTL_DAYS  (default 15) — match_score < 60
- HIGH_SCORE_TTL_DAYS (default 25) — match_score >= 60
- APPLIED_PROTECTED   — never auto-purged regardless of age
                       (kept for outcome amplification & history)

Tables affected
---------------
- Supabase  `latest_jobs`     (current scrape window — all rows)
- Supabase  `all_jobs`         (long-term archive — protected if applied=true)
- SQLite    `clean_listings`   (local cache — applied jobs are protected via status='applied')
- SQLite    `raw_listings`     (only orphaned rows ie. clean_listings row gone)

Run cadence
-----------
The scheduler calls `purge_stale_jobs()` once per day (04:30 IST,
just after the existing `smart_expire_jobs` cleanup). It is also
exposed via `/api/admin/trigger-purge` so the super-admin can
trigger an on-demand sweep from the mini-app.

Public API
----------
    from core.job_retention import purge_stale_jobs, RetentionStats
    stats = purge_stale_jobs()           # sync
    stats = await async_purge_stale_jobs()
============================================================
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    from loguru import logger
except ImportError:                                           # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

try:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
except ImportError:                                           # pragma: no cover
    IST = timezone(timedelta(hours=5, minutes=30))            # type: ignore

MODULE_ID = "JOB-RETENTION"

# ============================================================
# CONFIGURATION
# ============================================================

def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


LOW_SCORE_TTL_DAYS:  int = _int_env("JOB_LOW_TTL_DAYS",  15)
HIGH_SCORE_TTL_DAYS: int = _int_env("JOB_HIGH_TTL_DAYS", 25)
SCORE_THRESHOLD:     int = _int_env("JOB_SCORE_TIER_CUTOFF", 60)

# Hard-cap absolute age for any job that has NO match_score signal
# (legacy rows). Anything older than this is purged regardless of
# tier — keeps the table from growing unbounded.
ABSOLUTE_MAX_AGE_DAYS: int = _int_env("JOB_ABSOLUTE_MAX_AGE_DAYS", 25)


# ============================================================
# TYPES
# ============================================================

@dataclass
class RetentionStats:
    """Per-table tally of what was deleted vs protected."""
    low_score_purged_supabase:  int = 0
    high_score_purged_supabase: int = 0
    legacy_purged_supabase:     int = 0
    applied_protected:          int = 0
    latest_jobs_purged:         int = 0
    sqlite_purged:              int = 0
    errors:                     list = field(default_factory=list)
    started_at:                 str = ""
    finished_at:                str = ""
    config: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def total_purged(self) -> int:
        return (
            self.low_score_purged_supabase
            + self.high_score_purged_supabase
            + self.legacy_purged_supabase
            + self.latest_jobs_purged
            + self.sqlite_purged
        )


# ============================================================
# CORE PURGE
# ============================================================

def _now() -> datetime:
    return datetime.now(IST)


def _cutoff_iso(days: int) -> str:
    """Return the ISO-8601 cutoff for "anything created before this date"."""
    return (_now() - timedelta(days=days)).isoformat()


def _purge_supabase_tier(
    score_lt: Optional[float],
    score_gte: Optional[float],
    cutoff_iso: str,
    bucket_name: str,
) -> int:
    """
    Delete rows from Supabase `all_jobs` matching:
      - created_at < cutoff
      - applied  = false   (never delete applied rows)
      - match_score in [score_gte, score_lt)  (open on top, closed on bottom)
    """
    try:
        from core.supabase_client import get_supabase, is_operational
    except Exception as e:
        logger.warning(f"[{MODULE_ID}] supabase client unavailable: {e}")
        return 0

    if not is_operational():
        return 0
    sb = get_supabase()
    if sb is None:
        return 0

    try:
        q = sb.table("all_jobs").delete().eq("applied", False).lt("created_at", cutoff_iso)
        if score_gte is not None:
            q = q.gte("match_score", score_gte)
        if score_lt is not None:
            q = q.lt("match_score", score_lt)
        resp = q.execute()
        deleted = len(resp.data) if resp.data else 0
        if deleted:
            logger.info(
                f"[{MODULE_ID}] {bucket_name}: removed {deleted} rows "
                f"(cutoff={cutoff_iso}, applied=false)"
            )
        return deleted
    except Exception as e:
        logger.error(f"[{MODULE_ID}] {bucket_name} purge failed: {e}")
        return 0


def _purge_supabase_latest_jobs(stats: RetentionStats) -> None:
    """
    `latest_jobs` is a session view — apply the SHORTER of the two TTLs
    (low-score TTL) blanket. The morning merge already promotes
    keepers into `all_jobs`, so this is safe.
    """
    try:
        from core.supabase_client import get_supabase, is_operational
        if not is_operational():
            return
        sb = get_supabase()
        if sb is None:
            return
        cutoff = _cutoff_iso(LOW_SCORE_TTL_DAYS)
        resp = sb.table("latest_jobs").delete().lt("scraped_at", cutoff).execute()
        n = len(resp.data) if resp.data else 0
        stats.latest_jobs_purged = n
        if n:
            logger.info(f"[{MODULE_ID}] latest_jobs: pruned {n} rows older than {LOW_SCORE_TTL_DAYS}d")
    except Exception as e:
        logger.warning(f"[{MODULE_ID}] latest_jobs cleanup error: {e}")
        stats.errors.append(f"latest_jobs: {e}")


def _count_supabase_protected_applied(stats: RetentionStats) -> None:
    """How many applied rows were protected from purge (informational only)."""
    try:
        from core.supabase_client import get_supabase, is_operational
        if not is_operational():
            return
        sb = get_supabase()
        if sb is None:
            return
        resp = sb.table("all_jobs").select("id", count="exact").eq(
            "applied", True
        ).execute()
        stats.applied_protected = int(resp.count or 0)
    except Exception:
        pass


def _purge_sqlite_local(stats: RetentionStats) -> None:
    """
    Purge stale rows from the local SQLite `clean_listings` cache.
    The local cache backs the "Live" tab. Applied rows are tagged
    `status='applied'` and protected.
    """
    try:
        from core.database import get_db
        db = get_db()
        conn = db._get_conn() if hasattr(db, "_get_conn") else None
        if conn is None:
            # Fallback path — older code uses direct sqlite3.connect
            import sqlite3
            db_path = os.getenv("DATABASE_PATH", "data/firstmover.db")
            conn = sqlite3.connect(db_path)
            close_after = True
        else:
            close_after = False

        low_cut  = (_now() - timedelta(days=LOW_SCORE_TTL_DAYS)).isoformat()
        high_cut = (_now() - timedelta(days=HIGH_SCORE_TTL_DAYS)).isoformat()

        cur = conn.cursor()
        # Low-tier (< threshold OR no score) — 15-day TTL
        cur.execute(
            """
            DELETE FROM clean_listings
             WHERE status != 'applied'
               AND (ppo_score IS NULL OR ppo_score < ?)
               AND created_at < ?
            """,
            (SCORE_THRESHOLD, low_cut),
        )
        n_low = cur.rowcount

        # High-tier (>= threshold) — 25-day TTL
        cur.execute(
            """
            DELETE FROM clean_listings
             WHERE status != 'applied'
               AND ppo_score >= ?
               AND created_at < ?
            """,
            (SCORE_THRESHOLD, high_cut),
        )
        n_high = cur.rowcount

        # Orphan raw_listings whose clean row is gone
        cur.execute(
            """
            DELETE FROM raw_listings
             WHERE id NOT IN (SELECT raw_id FROM clean_listings WHERE raw_id IS NOT NULL)
               AND scraped_at < ?
            """,
            (low_cut,),
        )

        conn.commit()
        if close_after:
            conn.close()

        stats.sqlite_purged = (n_low or 0) + (n_high or 0)
        if stats.sqlite_purged:
            logger.info(
                f"[{MODULE_ID}] sqlite clean_listings: {n_low} low-score "
                f"+ {n_high} high-score = {stats.sqlite_purged} purged"
            )
    except Exception as e:
        logger.warning(f"[{MODULE_ID}] sqlite purge error: {e}")
        stats.errors.append(f"sqlite: {e}")


# ============================================================
# PUBLIC API
# ============================================================

def purge_stale_jobs() -> RetentionStats:
    """
    Score-tiered retention sweep. Safe to run repeatedly. Idempotent.

    Returns
    -------
    RetentionStats : per-bucket tally of deletions.
    """
    stats = RetentionStats(
        started_at=_now().isoformat(),
        config={
            "low_ttl_days":          LOW_SCORE_TTL_DAYS,
            "high_ttl_days":         HIGH_SCORE_TTL_DAYS,
            "score_threshold":       SCORE_THRESHOLD,
            "absolute_max_age_days": ABSOLUTE_MAX_AGE_DAYS,
        },
    )

    logger.info(
        f"[{MODULE_ID}] Starting score-tiered retention sweep "
        f"(low<{SCORE_THRESHOLD}: {LOW_SCORE_TTL_DAYS}d, "
        f"high>={SCORE_THRESHOLD}: {HIGH_SCORE_TTL_DAYS}d)"
    )

    # ---- Supabase all_jobs tiered purge ----
    low_cutoff_iso  = _cutoff_iso(LOW_SCORE_TTL_DAYS)
    high_cutoff_iso = _cutoff_iso(HIGH_SCORE_TTL_DAYS)

    # Tier 1: low-score (match_score < 60) older than 15 days
    stats.low_score_purged_supabase = _purge_supabase_tier(
        score_lt=float(SCORE_THRESHOLD),
        score_gte=None,
        cutoff_iso=low_cutoff_iso,
        bucket_name=f"all_jobs<{SCORE_THRESHOLD}",
    )

    # Tier 2: high-score (match_score >= 60) older than 25 days
    stats.high_score_purged_supabase = _purge_supabase_tier(
        score_lt=None,
        score_gte=float(SCORE_THRESHOLD),
        cutoff_iso=high_cutoff_iso,
        bucket_name=f"all_jobs>={SCORE_THRESHOLD}",
    )

    # Tier 3: ABSOLUTE max-age guard (catches rows where match_score
    # is NULL/0 because they never got scored). Cutoff = HIGH ttl.
    try:
        from core.supabase_client import get_supabase, is_operational
        if is_operational():
            sb = get_supabase()
            if sb is not None:
                resp = sb.table("all_jobs").delete().eq(
                    "applied", False
                ).lt(
                    "created_at", _cutoff_iso(ABSOLUTE_MAX_AGE_DAYS)
                ).is_("match_score", "null").execute()
                stats.legacy_purged_supabase = len(resp.data) if resp.data else 0
                if stats.legacy_purged_supabase:
                    logger.info(
                        f"[{MODULE_ID}] legacy unscored rows purged: "
                        f"{stats.legacy_purged_supabase}"
                    )
    except Exception as e:
        logger.debug(f"[{MODULE_ID}] legacy purge skipped: {e}")

    # ---- latest_jobs (session view) ----
    _purge_supabase_latest_jobs(stats)

    # ---- SQLite local cache ----
    _purge_sqlite_local(stats)

    # ---- Informational: count protected rows ----
    _count_supabase_protected_applied(stats)

    stats.finished_at = _now().isoformat()
    logger.info(
        f"[{MODULE_ID}] Sweep complete — {stats.total_purged} rows purged "
        f"(applied-protected: {stats.applied_protected}, errors: {len(stats.errors)})"
    )
    return stats


async def async_purge_stale_jobs() -> RetentionStats:
    """Async wrapper for use inside the apscheduler/aiohttp event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, purge_stale_jobs)
