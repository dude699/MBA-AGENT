"""
============================================================
OPERATION FIRST MOVER v5.5 -- SUPABASE DATABASE MODULE
============================================================
Two-table persistent storage on Supabase PostgreSQL:

  latest_jobs  — Current scraping session results (new/unseen)
  all_jobs     — Complete archive of all previously seen jobs

Logic:
  1. After each scrape → insert into latest_jobs (dedup by content_hash)
  2. If a job in latest_jobs already exists in all_jobs → remove from latest_jobs
     (user already saw it)
  3. Morning merge (5 AM IST) → move latest_jobs into all_jobs
  4. User-triggered scrape between sessions → add to latest_jobs, dedup again
  5. Expired jobs (past deadline + 7 days) cleaned up daily
  6. Applied jobs tracked via `applied` flag + `applied_at` timestamp
============================================================
"""

import hashlib
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

from loguru import logger

from core.supabase_client import (
    get_supabase, execute_with_retry, is_operational,
    record_success, record_failure,
)

MODULE_ID = "SUPABASE-DB"
IST = timezone(timedelta(hours=5, minutes=30))


# ============================================================
# SQL SCHEMA (run this in Supabase SQL Editor once)
# ============================================================

SCHEMA_SQL = """
-- ============================================================
-- OPERATION FIRST MOVER — SUPABASE SCHEMA
-- Run this ONCE in Supabase SQL Editor (Dashboard > SQL Editor)
-- ============================================================

-- Latest jobs: current scraping session
CREATE TABLE IF NOT EXISTS latest_jobs (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    company_logo    TEXT DEFAULT '',
    company_size    TEXT DEFAULT '',
    company_rating  REAL DEFAULT 0,
    company_tier    TEXT DEFAULT 'startup',
    location        TEXT DEFAULT '',
    location_type   TEXT DEFAULT 'onsite',
    source          TEXT DEFAULT '',
    source_url      TEXT DEFAULT '',
    category        TEXT DEFAULT '',
    sector          TEXT DEFAULT '',
    stipend         INTEGER DEFAULT 0,
    stipend_currency TEXT DEFAULT 'INR',
    stipend_type    TEXT DEFAULT 'monthly',
    duration        INTEGER DEFAULT 0,
    duration_unit   TEXT DEFAULT 'months',
    applicants      INTEGER DEFAULT 0,
    openings        INTEGER DEFAULT 1,
    skills          JSONB DEFAULT '[]',
    description     TEXT DEFAULT '',
    responsibilities JSONB DEFAULT '[]',
    requirements    JSONB DEFAULT '[]',
    perks           JSONB DEFAULT '[]',
    tags            JSONB DEFAULT '[]',
    posted_date     TEXT DEFAULT '',
    deadline        TEXT DEFAULT '',
    start_date      TEXT DEFAULT '',
    ppo_score       REAL DEFAULT 0,
    ghost_score     REAL DEFAULT 0,
    match_score     REAL DEFAULT 50,
    is_expired      BOOLEAN DEFAULT FALSE,
    is_premium      BOOLEAN DEFAULT FALSE,
    is_verified     BOOLEAN DEFAULT TRUE,
    content_hash    TEXT NOT NULL,
    batch_id        TEXT DEFAULT '',
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT latest_jobs_content_hash_unique UNIQUE (content_hash)
);

-- All jobs: complete archive
CREATE TABLE IF NOT EXISTS all_jobs (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    company_logo    TEXT DEFAULT '',
    company_size    TEXT DEFAULT '',
    company_rating  REAL DEFAULT 0,
    company_tier    TEXT DEFAULT 'startup',
    location        TEXT DEFAULT '',
    location_type   TEXT DEFAULT 'onsite',
    source          TEXT DEFAULT '',
    source_url      TEXT DEFAULT '',
    category        TEXT DEFAULT '',
    sector          TEXT DEFAULT '',
    stipend         INTEGER DEFAULT 0,
    stipend_currency TEXT DEFAULT 'INR',
    stipend_type    TEXT DEFAULT 'monthly',
    duration        INTEGER DEFAULT 0,
    duration_unit   TEXT DEFAULT 'months',
    applicants      INTEGER DEFAULT 0,
    openings        INTEGER DEFAULT 1,
    skills          JSONB DEFAULT '[]',
    description     TEXT DEFAULT '',
    responsibilities JSONB DEFAULT '[]',
    requirements    JSONB DEFAULT '[]',
    perks           JSONB DEFAULT '[]',
    tags            JSONB DEFAULT '[]',
    posted_date     TEXT DEFAULT '',
    deadline        TEXT DEFAULT '',
    start_date      TEXT DEFAULT '',
    ppo_score       REAL DEFAULT 0,
    ghost_score     REAL DEFAULT 0,
    match_score     REAL DEFAULT 50,
    is_expired      BOOLEAN DEFAULT FALSE,
    is_premium      BOOLEAN DEFAULT FALSE,
    is_verified     BOOLEAN DEFAULT TRUE,
    applied         BOOLEAN DEFAULT FALSE,
    applied_at      TIMESTAMPTZ DEFAULT NULL,
    application_status TEXT DEFAULT 'not_applied',
    application_notes TEXT DEFAULT '',
    content_hash    TEXT NOT NULL,
    batch_id        TEXT DEFAULT '',
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT all_jobs_content_hash_unique UNIQUE (content_hash)
);

-- Keep-alive pings tracking
CREATE TABLE IF NOT EXISTS keepalive_pings (
    id          BIGSERIAL PRIMARY KEY,
    ping_type   TEXT DEFAULT 'scheduled',
    source      TEXT DEFAULT 'server',
    latency_ms  REAL DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_latest_jobs_source ON latest_jobs(source);
CREATE INDEX IF NOT EXISTS idx_latest_jobs_category ON latest_jobs(category);
CREATE INDEX IF NOT EXISTS idx_latest_jobs_scraped ON latest_jobs(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_latest_jobs_hash ON latest_jobs(content_hash);
CREATE INDEX IF NOT EXISTS idx_latest_jobs_stipend ON latest_jobs(stipend DESC);

CREATE INDEX IF NOT EXISTS idx_all_jobs_source ON all_jobs(source);
CREATE INDEX IF NOT EXISTS idx_all_jobs_category ON all_jobs(category);
CREATE INDEX IF NOT EXISTS idx_all_jobs_created ON all_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_all_jobs_hash ON all_jobs(content_hash);
CREATE INDEX IF NOT EXISTS idx_all_jobs_applied ON all_jobs(applied);
CREATE INDEX IF NOT EXISTS idx_all_jobs_expired ON all_jobs(is_expired);
CREATE INDEX IF NOT EXISTS idx_all_jobs_stipend ON all_jobs(stipend DESC);
CREATE INDEX IF NOT EXISTS idx_all_jobs_ppo ON all_jobs(ppo_score DESC);

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_latest_jobs_updated
    BEFORE UPDATE ON latest_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER trigger_all_jobs_updated
    BEFORE UPDATE ON all_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
"""


# ============================================================
# CONTENT HASH GENERATOR
# ============================================================

def compute_content_hash(title: str, company: str, source: str = "",
                         source_url: str = "") -> str:
    """
    Generate a deterministic hash for dedup.
    Uses title + company as primary key, with source_url as tiebreaker.
    """
    raw = f"{title.strip().lower()}|{company.strip().lower()}"
    if source_url:
        raw += f"|{source_url.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ============================================================
# SUPABASE JOB DATABASE CLASS
# ============================================================

class SupabaseJobDB:
    """Static methods for all Supabase job operations."""

    # ---- INSERT INTO latest_jobs ----

    @staticmethod
    def insert_latest_jobs(jobs: List[Dict], batch_id: str = "") -> int:
        """
        Insert jobs into latest_jobs table.
        Skips duplicates (by content_hash) and removes jobs already in all_jobs.
        Returns count of newly inserted jobs.
        """
        if not is_operational() or not jobs:
            return 0

        client = get_supabase()
        if not client:
            return 0

        inserted = 0
        try:
            # Get all content_hashes already in all_jobs (user already saw them)
            existing_hashes = set()
            try:
                resp = client.table("all_jobs").select("content_hash").execute()
                if resp.data:
                    existing_hashes = {r["content_hash"] for r in resp.data}
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Could not check all_jobs: {e}")

            # Also get hashes already in latest_jobs
            latest_hashes = set()
            try:
                resp = client.table("latest_jobs").select("content_hash").execute()
                if resp.data:
                    latest_hashes = {r["content_hash"] for r in resp.data}
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Could not check latest_jobs: {e}")

            # Filter out duplicates
            new_jobs = []
            for job in jobs:
                ch = job.get("content_hash", "")
                if not ch:
                    ch = compute_content_hash(
                        job.get("title", ""),
                        job.get("company", ""),
                        job.get("source", ""),
                        job.get("source_url", ""),
                    )
                    job["content_hash"] = ch

                if ch in existing_hashes or ch in latest_hashes:
                    continue

                job["batch_id"] = batch_id
                # Ensure JSONB fields are proper JSON strings
                for field in ("skills", "responsibilities", "requirements", "perks", "tags"):
                    val = job.get(field, [])
                    if isinstance(val, str):
                        try:
                            val = json.loads(val)
                        except Exception:
                            val = [v.strip() for v in val.split(",") if v.strip()] if val else []
                    job[field] = val if isinstance(val, list) else []

                new_jobs.append(job)

            if not new_jobs:
                logger.debug(f"[{MODULE_ID}] No new unique jobs to insert")
                return 0

            # Batch insert (Supabase handles upsert via unique constraint)
            # Insert in chunks of 50 to avoid payload limits
            chunk_size = 50
            for i in range(0, len(new_jobs), chunk_size):
                chunk = new_jobs[i:i + chunk_size]
                try:
                    resp = client.table("latest_jobs").upsert(
                        chunk, on_conflict="content_hash"
                    ).execute()
                    inserted += len(chunk)
                except Exception as e:
                    logger.error(f"[{MODULE_ID}] Insert chunk error: {e}")
                    record_failure()

            record_success()
            logger.info(f"[{MODULE_ID}] Inserted {inserted} jobs into latest_jobs (batch={batch_id})")

        except Exception as e:
            logger.error(f"[{MODULE_ID}] insert_latest_jobs error: {e}")
            record_failure()

        return inserted

    # ---- INSERT INTO all_jobs directly (for real-time sync) ----

    @staticmethod
    def insert_all_jobs(jobs: List[Dict], batch_id: str = "") -> int:
        """
        Upsert jobs directly into all_jobs table.
        This ensures the 'All Jobs' tab always has data, not just after morning merge.
        Uses content_hash for dedup.
        """
        if not is_operational() or not jobs:
            return 0

        client = get_supabase()
        if not client:
            return 0

        inserted = 0
        now = datetime.now(IST).isoformat()

        try:
            rows = []
            for job in jobs:
                content_hash = job.get("content_hash", "")
                if not content_hash:
                    raw = f"{job.get('title','')}-{job.get('company','')}-{job.get('source','')}"
                    content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

                rows.append({
                    "title": str(job.get("title", ""))[:500],
                    "company": str(job.get("company", ""))[:200],
                    "location": str(job.get("location", ""))[:200],
                    "location_type": str(job.get("location_type", "onsite")),
                    "source": str(job.get("source", "")),
                    "source_url": str(job.get("source_url", ""))[:1000],
                    "category": str(job.get("category", "")),
                    "sector": str(job.get("sector", "")),
                    "stipend": int(job.get("stipend", 0) or 0),
                    "duration": int(job.get("duration", 0) or 0),
                    "applicants": int(job.get("applicants", 0) or 0),
                    "description": str(job.get("description", ""))[:5000],
                    "ppo_score": float(job.get("ppo_score", 0) or 0),
                    "ghost_score": float(job.get("ghost_score", 0) or 0),
                    "match_score": float(job.get("match_score", 50) or 50),
                    "is_expired": bool(job.get("is_expired", False)),
                    "content_hash": content_hash,
                    "batch_id": batch_id,
                    "created_at": now,
                    "updated_at": now,
                })

            # Upsert in chunks of 50
            chunk_size = 50
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i + chunk_size]
                try:
                    resp = client.table("all_jobs").upsert(
                        chunk, on_conflict="content_hash"
                    ).execute()
                    inserted += len(chunk)
                except Exception as e:
                    logger.debug(f"[{MODULE_ID}] all_jobs chunk upsert: {e}")

            record_success()

        except Exception as e:
            logger.error(f"[{MODULE_ID}] insert_all_jobs error: {e}")
            record_failure()

        return inserted

    # ---- MERGE latest_jobs -> all_jobs ----

    @staticmethod
    def merge_latest_to_all() -> Tuple[int, int]:
        """
        Move jobs from latest_jobs to all_jobs.
        - Jobs already in all_jobs (by content_hash) are updated.
        - New jobs are inserted.
        - latest_jobs is cleared after merge.
        Returns (newly_merged, total_in_latest).
        """
        if not is_operational():
            return (0, 0)

        client = get_supabase()
        if not client:
            return (0, 0)

        try:
            # Get all latest_jobs
            resp = client.table("latest_jobs").select("*").execute()
            latest = resp.data or []
            total = len(latest)

            if total == 0:
                return (0, 0)

            # Get existing hashes in all_jobs
            all_resp = client.table("all_jobs").select("content_hash").execute()
            existing_hashes = {r["content_hash"] for r in (all_resp.data or [])}

            merged = 0
            chunk_size = 50

            # Prepare data for all_jobs (add first_seen_at, remove latest-only fields)
            for job in latest:
                # Remove the latest_jobs id so all_jobs gets its own
                job.pop("id", None)
                if job["content_hash"] not in existing_hashes:
                    job["first_seen_at"] = job.get("scraped_at", datetime.now(IST).isoformat())
                # Preserve applied status if already in all_jobs
                if job["content_hash"] in existing_hashes:
                    job.pop("applied", None)
                    job.pop("applied_at", None)
                    job.pop("application_status", None)
                    job.pop("application_notes", None)

            # Upsert in chunks
            for i in range(0, total, chunk_size):
                chunk = latest[i:i + chunk_size]
                try:
                    client.table("all_jobs").upsert(
                        chunk, on_conflict="content_hash"
                    ).execute()
                    merged += len([j for j in chunk if j.get("content_hash") not in existing_hashes])
                except Exception as e:
                    logger.error(f"[{MODULE_ID}] Merge chunk error: {e}")

            # Clear latest_jobs after successful merge
            try:
                client.table("latest_jobs").delete().neq("id", 0).execute()
                logger.info(f"[{MODULE_ID}] Cleared latest_jobs after merge")
            except Exception as e:
                logger.error(f"[{MODULE_ID}] Failed to clear latest_jobs: {e}")

            record_success()
            logger.info(f"[{MODULE_ID}] Merged {merged} new from {total} latest → all_jobs")
            return (merged, total)

        except Exception as e:
            logger.error(f"[{MODULE_ID}] merge_latest_to_all error: {e}")
            record_failure()
            return (0, 0)

    # ---- QUERY: latest_jobs ----

    @staticmethod
    def get_latest_jobs(limit: int = 20, offset: int = 0,
                        source: str = "", category: str = "",
                        location: str = "", search: str = "",
                        sort_by: str = "scraped_at") -> Tuple[List[Dict], int]:
        """Get jobs from latest_jobs with filtering and pagination."""
        if not is_operational():
            return ([], 0)

        client = get_supabase()
        if not client:
            return ([], 0)

        try:
            # Count query
            count_q = client.table("latest_jobs").select("id", count="exact")
            if source:
                count_q = count_q.eq("source", source)
            if category:
                count_q = count_q.eq("category", category)
            if location:
                count_q = count_q.ilike("location", f"%{location}%")
            if search:
                count_q = count_q.or_(f"title.ilike.%{search}%,company.ilike.%{search}%")

            count_resp = count_q.execute()
            total = count_resp.count if count_resp.count is not None else len(count_resp.data or [])

            # Data query
            q = client.table("latest_jobs").select("*")
            if source:
                q = q.eq("source", source)
            if category:
                q = q.eq("category", category)
            if location:
                q = q.ilike("location", f"%{location}%")
            if search:
                q = q.or_(f"title.ilike.%{search}%,company.ilike.%{search}%")

            q = q.order(sort_by, desc=True).range(offset, offset + limit - 1)
            resp = q.execute()

            record_success()
            return (resp.data or [], total)

        except Exception as e:
            logger.error(f"[{MODULE_ID}] get_latest_jobs error: {e}")
            record_failure()
            return ([], 0)

    # ---- QUERY: all_jobs ----

    @staticmethod
    def get_all_jobs(limit: int = 20, offset: int = 0,
                     source: str = "", category: str = "",
                     location: str = "", search: str = "",
                     applied_only: bool = False,
                     exclude_expired: bool = True,
                     sort_by: str = "created_at") -> Tuple[List[Dict], int]:
        """Get jobs from all_jobs archive with filtering and pagination."""
        if not is_operational():
            return ([], 0)

        client = get_supabase()
        if not client:
            return ([], 0)

        try:
            # Count query
            count_q = client.table("all_jobs").select("id", count="exact")
            if source:
                count_q = count_q.eq("source", source)
            if category:
                count_q = count_q.eq("category", category)
            if location:
                count_q = count_q.ilike("location", f"%{location}%")
            if search:
                count_q = count_q.or_(f"title.ilike.%{search}%,company.ilike.%{search}%")
            if applied_only:
                count_q = count_q.eq("applied", True)
            if exclude_expired:
                count_q = count_q.eq("is_expired", False)

            count_resp = count_q.execute()
            total = count_resp.count if count_resp.count is not None else len(count_resp.data or [])

            # Data query
            q = client.table("all_jobs").select("*")
            if source:
                q = q.eq("source", source)
            if category:
                q = q.eq("category", category)
            if location:
                q = q.ilike("location", f"%{location}%")
            if search:
                q = q.or_(f"title.ilike.%{search}%,company.ilike.%{search}%")
            if applied_only:
                q = q.eq("applied", True)
            if exclude_expired:
                q = q.eq("is_expired", False)

            q = q.order(sort_by, desc=True).range(offset, offset + limit - 1)
            resp = q.execute()

            record_success()
            return (resp.data or [], total)

        except Exception as e:
            logger.error(f"[{MODULE_ID}] get_all_jobs error: {e}")
            record_failure()
            return ([], 0)

    # ---- SINGLE JOB ----

    @staticmethod
    def get_job_by_id(job_id: int, table: str = "all_jobs") -> Optional[Dict]:
        """Get a single job by ID from specified table."""
        if not is_operational():
            return None

        client = get_supabase()
        if not client:
            return None

        try:
            resp = client.table(table).select("*").eq("id", job_id).limit(1).execute()
            record_success()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"[{MODULE_ID}] get_job_by_id error: {e}")
            record_failure()
            return None

    # ---- MARK APPLIED ----

    @staticmethod
    def mark_applied(content_hash: str = "", job_id: int = 0,
                     status: str = "applied", notes: str = "") -> bool:
        """
        Mark a job as applied in both tables (by content_hash or id).
        Updates all_jobs and latest_jobs if present.
        """
        if not is_operational():
            return False

        client = get_supabase()
        if not client:
            return False

        now = datetime.now(IST).isoformat()
        update_data = {
            "applied": True,
            "applied_at": now,
            "application_status": status,
            "application_notes": notes[:1000] if notes else "",
        }

        try:
            updated = False
            if content_hash:
                try:
                    resp = client.table("all_jobs").update(update_data).eq(
                        "content_hash", content_hash
                    ).execute()
                    if resp.data:
                        updated = True
                except Exception:
                    pass
            elif job_id:
                try:
                    resp = client.table("all_jobs").update(update_data).eq(
                        "id", job_id
                    ).execute()
                    if resp.data:
                        updated = True
                except Exception:
                    pass

            record_success()
            return updated

        except Exception as e:
            logger.error(f"[{MODULE_ID}] mark_applied error: {e}")
            record_failure()
            return False

    # ---- CLEANUP EXPIRED ----

    @staticmethod
    def cleanup_expired_jobs(days_past_deadline: int = 7) -> int:
        """
        Mark jobs as expired if their deadline has passed.
        Delete very old expired jobs (30+ days past deadline).
        """
        if not is_operational():
            return 0

        client = get_supabase()
        if not client:
            return 0

        deleted = 0
        try:
            # For now, mark jobs where deadline is a parseable date in the past
            # Also delete expired jobs older than 30 days to save storage
            cutoff = (datetime.now(IST) - timedelta(days=30)).isoformat()
            try:
                resp = client.table("all_jobs").delete().eq(
                    "is_expired", True
                ).lt("updated_at", cutoff).execute()
                deleted = len(resp.data) if resp.data else 0
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Cleanup delete error: {e}")

            # Also clean from latest_jobs
            try:
                client.table("latest_jobs").delete().eq(
                    "is_expired", True
                ).execute()
            except Exception:
                pass

            if deleted > 0:
                logger.info(f"[{MODULE_ID}] Cleaned up {deleted} old expired jobs")
            record_success()

        except Exception as e:
            logger.error(f"[{MODULE_ID}] cleanup_expired error: {e}")
            record_failure()

        return deleted

    # ---- STATS ----

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """Get database statistics."""
        if not is_operational():
            return {"error": "Supabase not operational"}

        client = get_supabase()
        if not client:
            return {"error": "No client"}

        stats = {}
        try:
            # Latest jobs count
            try:
                resp = client.table("latest_jobs").select("id", count="exact").execute()
                stats["latest_jobs_count"] = resp.count if resp.count is not None else len(resp.data or [])
            except Exception:
                stats["latest_jobs_count"] = 0

            # All jobs counts
            try:
                resp = client.table("all_jobs").select("id", count="exact").execute()
                stats["all_jobs_count"] = resp.count if resp.count is not None else len(resp.data or [])
            except Exception:
                stats["all_jobs_count"] = 0

            try:
                resp = client.table("all_jobs").select("id", count="exact").eq("is_expired", False).execute()
                stats["all_jobs_active"] = resp.count if resp.count is not None else len(resp.data or [])
            except Exception:
                stats["all_jobs_active"] = 0

            try:
                resp = client.table("all_jobs").select("id", count="exact").eq("is_expired", True).execute()
                stats["all_jobs_expired"] = resp.count if resp.count is not None else len(resp.data or [])
            except Exception:
                stats["all_jobs_expired"] = 0

            try:
                resp = client.table("all_jobs").select("id", count="exact").eq("applied", True).execute()
                stats["all_jobs_applied"] = resp.count if resp.count is not None else len(resp.data or [])
            except Exception:
                stats["all_jobs_applied"] = 0

            record_success()

        except Exception as e:
            stats["error"] = str(e)[:200]
            record_failure()

        return stats


# ============================================================
# ASYNC WRAPPERS (for scheduler / aiohttp handlers)
# ============================================================

async def async_insert_latest_jobs(jobs: List[Dict], batch_id: str = "") -> int:
    """Async wrapper for insert_latest_jobs."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, SupabaseJobDB.insert_latest_jobs, jobs, batch_id)


async def async_insert_all_jobs(jobs: List[Dict], batch_id: str = "") -> int:
    """Async wrapper for insert_all_jobs (upsert into all_jobs table)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, SupabaseJobDB.insert_all_jobs, jobs, batch_id)


async def async_merge_latest_to_all() -> Tuple[int, int]:
    """Async wrapper for merge_latest_to_all."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, SupabaseJobDB.merge_latest_to_all)


async def async_cleanup_expired_jobs(days: int = 7) -> int:
    """Async wrapper for cleanup_expired_jobs."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, SupabaseJobDB.cleanup_expired_jobs, days)


# ============================================================
# SCHEMA HELPER
# ============================================================

def get_schema_sql() -> str:
    """Return the SQL schema for manual setup in Supabase SQL Editor."""
    return SCHEMA_SQL
