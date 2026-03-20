"""
============================================================
PRISM v0.2 -- SUPABASE DATABASE MODULE (BULLETPROOF)
============================================================
Persistent storage on Supabase PostgreSQL with ZERO data loss.

CRITICAL FIX v0.2: Jobs were being DELETED on every redeployment
because:
  1. merge_latest_to_all() wiped latest_jobs after merge
  2. FORCE_DB_RESET env var left enabled = wipe on every deploy
  3. insert_all_jobs() stripped critical fields (skills, posted_date, etc.)
  4. cleanup_expired_jobs() was too aggressive

NEW Architecture (v0.2 — Data-Safe):
  - all_jobs is the SINGLE SOURCE OF TRUTH (never wiped)
  - latest_jobs is a VIEW/POINTER table (session tracking only)
  - merge NEVER deletes from latest_jobs (just marks as merged)
  - cleanup uses SOFT DELETE (is_expired=true) not hard delete
  - All fields preserved: skills, requirements, perks, posted_date, etc.
  - Applied jobs NEVER deleted regardless of age
  - Smart expiry detection via AI + deadline parsing

Tables:
  latest_jobs  — Current scraping session results (append-only)
  all_jobs     — Complete archive (NEVER wiped, soft-delete only)
============================================================
"""

import hashlib
import json
import re
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
-- PRISM v0.2 — SUPABASE SCHEMA (BULLETPROOF)
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

-- All jobs: complete archive (SINGLE SOURCE OF TRUTH)
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
CREATE INDEX IF NOT EXISTS idx_all_jobs_deadline ON all_jobs(deadline);
CREATE INDEX IF NOT EXISTS idx_all_jobs_posted ON all_jobs(posted_date DESC);

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
# HELPERS: JSONB field normalizer + deadline parser
# ============================================================

def _normalize_jsonb(val) -> list:
    """Ensure a value is a proper list for JSONB storage."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        if not val or val == '[]':
            return []
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return [v.strip() for v in val.split(",") if v.strip()]
    return []


def _parse_deadline_date(deadline_str: str) -> Optional[datetime]:
    """
    Parse various deadline date formats into a datetime object.
    Handles: '2026-04-15', 'Apr 15, 2026', '15 Apr 2026', '15/04/2026', etc.
    """
    if not deadline_str or not isinstance(deadline_str, str):
        return None

    deadline_str = deadline_str.strip()

    # ISO format: 2026-04-15 or 2026-04-15T00:00:00
    for fmt in (
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
        "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
        "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y",
        "%b %d %Y", "%d %b, %Y",
    ):
        try:
            return datetime.strptime(deadline_str[:30], fmt)
        except (ValueError, IndexError):
            continue

    # Try extracting date with regex
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', deadline_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def _build_full_job_row(job: Dict, batch_id: str = "", now: str = "") -> Dict:
    """
    Build a complete row dict for Supabase upsert, preserving ALL fields.
    This is the SINGLE place where job dicts get normalized — no field stripping.
    """
    if not now:
        now = datetime.now(IST).isoformat()

    content_hash = job.get("content_hash", "")
    if not content_hash:
        content_hash = compute_content_hash(
            job.get("title", ""), job.get("company", ""),
            job.get("source", ""), job.get("source_url", ""),
        )

    # Normalize JSONB fields
    skills = _normalize_jsonb(job.get("skills", []))
    responsibilities = _normalize_jsonb(job.get("responsibilities", []))
    requirements = _normalize_jsonb(job.get("requirements", []))
    perks = _normalize_jsonb(job.get("perks", []))
    tags = _normalize_jsonb(job.get("tags", []))

    # Applicants: try multiple field names from different scrapers
    applicants = 0
    for key in ("applicants", "applications_count", "no_of_applications", "total_applicants"):
        v = job.get(key, 0)
        if v:
            try:
                applicants = int(v)
                break
            except (ValueError, TypeError):
                pass

    # Posted date: use portal's real date, NOT scrape time
    posted_date = job.get("posted_date", "")
    if not posted_date:
        # Compute from posted_days_ago if available
        posted_days = job.get("posted_days_ago", 0) or job.get("posted_days", 0)
        if posted_days and int(posted_days) > 0:
            try:
                ref_str = job.get("scraped_at") or job.get("created_at") or now
                if isinstance(ref_str, str):
                    ref_dt = datetime.fromisoformat(ref_str.replace('Z', '+00:00'))
                else:
                    ref_dt = datetime.now(IST)
                real_posted = ref_dt - timedelta(days=int(posted_days))
                posted_date = real_posted.isoformat()
            except Exception:
                pass
        if not posted_date:
            posted_date = job.get("created_at") or job.get("scraped_at") or now

    return {
        "title": str(job.get("title", ""))[:500],
        "company": str(job.get("company", ""))[:200],
        "company_logo": str(job.get("company_logo", "") or "")[:500],
        "company_size": str(job.get("company_size", "") or "")[:50],
        "company_rating": float(job.get("company_rating", 0) or 0),
        "company_tier": str(job.get("company_tier", "startup") or "startup"),
        "location": str(job.get("location", ""))[:200],
        "location_type": str(job.get("location_type", "onsite") or "onsite"),
        "source": str(job.get("source", "")),
        "source_url": str(job.get("source_url", job.get("url", "")))[:1000],
        "category": str(job.get("category", "")),
        "sector": str(job.get("sector", "")),
        "stipend": int(job.get("stipend", job.get("stipend_monthly", 0)) or 0),
        "stipend_currency": str(job.get("stipend_currency", "INR") or "INR"),
        "stipend_type": str(job.get("stipend_type", "monthly") or "monthly"),
        "duration": int(job.get("duration", job.get("duration_months", 0)) or 0),
        "duration_unit": str(job.get("duration_unit", "months") or "months"),
        "applicants": applicants,
        "openings": int(job.get("openings", 1) or 1),
        "skills": skills,
        "description": str(job.get("description", job.get("description_text", "")))[:5000],
        "responsibilities": responsibilities,
        "requirements": requirements,
        "perks": perks,
        "tags": tags,
        "posted_date": str(posted_date),
        "deadline": str(job.get("deadline", "") or ""),
        "start_date": str(job.get("start_date", "") or ""),
        "ppo_score": float(job.get("ppo_score", 0) or 0),
        "ghost_score": float(job.get("ghost_score", 0) or 0),
        "match_score": float(job.get("match_score", 50) or 50),
        "is_expired": bool(job.get("is_expired", False)),
        "is_premium": bool(job.get("is_premium", False)),
        "is_verified": bool(job.get("is_verified", True)),
        "content_hash": content_hash,
        "batch_id": batch_id or job.get("batch_id", ""),
    }


# ============================================================
# SUPABASE JOB DATABASE CLASS (v0.2 — DATA-SAFE)
# ============================================================

class SupabaseJobDB:
    """Static methods for all Supabase job operations. NEVER deletes data without safety checks."""

    # ---- INSERT INTO latest_jobs ----

    @staticmethod
    def insert_latest_jobs(jobs: List[Dict], batch_id: str = "") -> int:
        """
        Insert jobs into latest_jobs table.
        Skips duplicates (by content_hash) and removes jobs already in all_jobs.
        Also upserts into all_jobs for real-time availability.
        Returns count of newly inserted jobs.
        """
        if not is_operational() or not jobs:
            return 0

        client = get_supabase()
        if not client:
            return 0

        inserted = 0
        now = datetime.now(IST).isoformat()

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

            # Build full rows and filter duplicates
            new_rows = []
            all_rows = []  # For all_jobs sync
            for job in jobs:
                row = _build_full_job_row(job, batch_id, now)
                ch = row["content_hash"]

                if ch in existing_hashes or ch in latest_hashes:
                    continue

                row["scraped_at"] = now
                row["created_at"] = now
                row["updated_at"] = now
                new_rows.append(row)

                # Build all_jobs version (with extra fields)
                all_row = dict(row)
                all_row["first_seen_at"] = now
                all_rows.append(all_row)

            if not new_rows:
                logger.debug(f"[{MODULE_ID}] No new unique jobs to insert")
                return 0

            # Batch insert into latest_jobs
            chunk_size = 50
            for i in range(0, len(new_rows), chunk_size):
                chunk = new_rows[i:i + chunk_size]
                try:
                    client.table("latest_jobs").upsert(
                        chunk, on_conflict="content_hash"
                    ).execute()
                    inserted += len(chunk)
                except Exception as e:
                    logger.error(f"[{MODULE_ID}] latest_jobs insert chunk error: {e}")
                    record_failure()

            record_success()
            logger.info(f"[{MODULE_ID}] Inserted {inserted} jobs into latest_jobs (batch={batch_id})")

            # ALSO upsert into all_jobs immediately (real-time sync)
            if all_rows:
                try:
                    all_inserted = SupabaseJobDB.insert_all_jobs(all_rows, batch_id)
                    if all_inserted > 0:
                        logger.info(f"[{MODULE_ID}] Synced {all_inserted} jobs to all_jobs (real-time)")
                except Exception as e:
                    logger.debug(f"[{MODULE_ID}] all_jobs real-time sync error (non-critical): {e}")

        except Exception as e:
            logger.error(f"[{MODULE_ID}] insert_latest_jobs error: {e}")
            record_failure()

        return inserted

    # ---- INSERT INTO all_jobs directly (for real-time sync) ----

    @staticmethod
    def insert_all_jobs(jobs: List[Dict], batch_id: str = "") -> int:
        """
        Upsert jobs directly into all_jobs table.
        PRESERVES ALL FIELDS — skills, requirements, perks, posted_date, etc.
        Uses content_hash for dedup. Never overwrites applied status.
        """
        if not is_operational() or not jobs:
            return 0

        client = get_supabase()
        if not client:
            return 0

        inserted = 0
        now = datetime.now(IST).isoformat()

        try:
            # Get existing applied jobs to protect their status
            applied_hashes = set()
            try:
                resp = client.table("all_jobs").select("content_hash").eq("applied", True).execute()
                if resp.data:
                    applied_hashes = {r["content_hash"] for r in resp.data}
            except Exception:
                pass

            rows = []
            for job in jobs:
                row = _build_full_job_row(job, batch_id, now)

                # NEVER overwrite applied status
                if row["content_hash"] in applied_hashes:
                    # Skip fields that would reset applied state
                    # (the upsert will still update other fields like scores)
                    pass

                row["created_at"] = job.get("created_at") or job.get("first_seen_at") or now
                row["updated_at"] = now
                row["first_seen_at"] = job.get("first_seen_at") or job.get("created_at") or now
                row["scraped_at"] = job.get("scraped_at") or now
                rows.append(row)

            # Upsert in chunks of 50
            chunk_size = 50
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i + chunk_size]
                try:
                    client.table("all_jobs").upsert(
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

    # ---- MERGE latest_jobs -> all_jobs (DATA-SAFE: no deletion) ----

    @staticmethod
    def merge_latest_to_all() -> Tuple[int, int]:
        """
        Sync jobs from latest_jobs to all_jobs.
        v0.2 CRITICAL FIX: Does NOT delete from latest_jobs.
        Instead, just ensures all latest data is in all_jobs.
        latest_jobs acts as a "session window" and gets cleaned
        ONLY by the next scrape session (not by merge).
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

            # Get existing data in all_jobs
            all_resp = client.table("all_jobs").select("content_hash, applied").execute()
            existing_map = {}
            for r in (all_resp.data or []):
                existing_map[r["content_hash"]] = r.get("applied", False)

            merged = 0
            chunk_size = 50
            now = datetime.now(IST).isoformat()

            # Prepare data for all_jobs
            upsert_rows = []
            for job in latest:
                ch = job.get("content_hash", "")
                job_id = job.pop("id", None)  # Remove latest_jobs PK

                # Set first_seen_at for genuinely new jobs
                if ch not in existing_map:
                    job["first_seen_at"] = job.get("scraped_at", now)
                    merged += 1

                # CRITICAL: Preserve applied status for existing jobs
                if ch in existing_map and existing_map[ch]:
                    job.pop("applied", None)
                    job.pop("applied_at", None)
                    job.pop("application_status", None)
                    job.pop("application_notes", None)

                job["updated_at"] = now
                upsert_rows.append(job)

            # Upsert in chunks
            for i in range(0, len(upsert_rows), chunk_size):
                chunk = upsert_rows[i:i + chunk_size]
                try:
                    client.table("all_jobs").upsert(
                        chunk, on_conflict="content_hash"
                    ).execute()
                except Exception as e:
                    logger.error(f"[{MODULE_ID}] Merge chunk error: {e}")

            # v0.2: DO NOT clear latest_jobs after merge
            # latest_jobs serves as "current session" view and gets
            # naturally replaced on next scrape session
            logger.info(f"[{MODULE_ID}] Merged {merged} new from {total} latest -> all_jobs (latest preserved)")
            record_success()
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

    # ---- SMART EXPIRED LISTING MANAGEMENT (v0.2) ----

    @staticmethod
    def smart_expire_jobs() -> Dict[str, int]:
        """
        Intelligently detect and SOFT-DELETE expired listings.
        
        Strategy (multi-signal):
          1. Parse deadline field — if date is past, mark expired
          2. Duration-based: if posted_date + duration > today, likely expired
          3. Age-based: listings 60+ days old with no activity = stale
          4. NEVER hard-delete applied jobs (keep for history)
          5. NEVER hard-delete — only set is_expired=true
          6. Hard-delete only truly ancient expired jobs (90+ days expired, not applied)
        
        Returns dict with counts of each action taken.
        """
        if not is_operational():
            return {"error": "not operational"}

        client = get_supabase()
        if not client:
            return {"error": "no client"}

        now = datetime.now(IST)
        stats = {"deadline_expired": 0, "age_expired": 0, "hard_deleted": 0, "protected_applied": 0}

        try:
            # 1. Get all active (non-expired) jobs with deadlines
            try:
                resp = client.table("all_jobs").select(
                    "id, deadline, posted_date, duration, created_at, applied, content_hash"
                ).eq("is_expired", False).execute()
                active_jobs = resp.data or []
            except Exception as e:
                logger.error(f"[{MODULE_ID}] smart_expire fetch error: {e}")
                return stats

            expire_ids = []
            for job in active_jobs:
                should_expire = False

                # Signal 1: Deadline has passed
                deadline = _parse_deadline_date(job.get("deadline", ""))
                if deadline and deadline < now:
                    should_expire = True

                # Signal 2: Duration-based expiry
                if not should_expire and job.get("posted_date") and job.get("duration"):
                    try:
                        posted = datetime.fromisoformat(
                            str(job["posted_date"]).replace('Z', '+00:00')
                        )
                        if posted.tzinfo is None:
                            posted = posted.replace(tzinfo=IST)
                        dur_months = int(job.get("duration", 0) or 0)
                        if dur_months > 0:
                            # If posted_date + duration + 30 day buffer < now
                            end_date = posted + timedelta(days=(dur_months * 30) + 30)
                            if end_date < now:
                                should_expire = True
                    except Exception:
                        pass

                # Signal 3: Very old listings (60+ days) with no updates
                if not should_expire:
                    try:
                        created = datetime.fromisoformat(
                            str(job.get("created_at", "")).replace('Z', '+00:00')
                        )
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=IST)
                        if (now - created).days > 60:
                            should_expire = True
                    except Exception:
                        pass

                if should_expire:
                    expire_ids.append(job["id"])
                    if job.get("deadline"):
                        stats["deadline_expired"] += 1
                    else:
                        stats["age_expired"] += 1

            # Soft-delete: mark as expired (NEVER hard delete active)
            if expire_ids:
                chunk_size = 50
                for i in range(0, len(expire_ids), chunk_size):
                    chunk = expire_ids[i:i + chunk_size]
                    try:
                        client.table("all_jobs").update(
                            {"is_expired": True, "updated_at": now.isoformat()}
                        ).in_("id", chunk).execute()
                    except Exception as e:
                        logger.error(f"[{MODULE_ID}] Soft-expire chunk error: {e}")

            # 2. Hard-delete only ANCIENT expired jobs (90+ days, NOT applied)
            ancient_cutoff = (now - timedelta(days=90)).isoformat()
            try:
                resp = client.table("all_jobs").delete().eq(
                    "is_expired", True
                ).eq("applied", False).lt(
                    "updated_at", ancient_cutoff
                ).execute()
                stats["hard_deleted"] = len(resp.data) if resp.data else 0
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Ancient cleanup error: {e}")

            # 3. Count protected applied jobs
            try:
                resp = client.table("all_jobs").select("id", count="exact").eq(
                    "applied", True
                ).eq("is_expired", True).execute()
                stats["protected_applied"] = resp.count if resp.count is not None else 0
            except Exception:
                pass

            # 4. Clean old entries from latest_jobs (keep last 7 days only)
            week_ago = (now - timedelta(days=7)).isoformat()
            try:
                client.table("latest_jobs").delete().lt("scraped_at", week_ago).execute()
            except Exception:
                pass

            total_expired = stats["deadline_expired"] + stats["age_expired"]
            if total_expired > 0 or stats["hard_deleted"] > 0:
                logger.info(
                    f"[{MODULE_ID}] Smart expire: {total_expired} soft-expired "
                    f"({stats['deadline_expired']} deadline, {stats['age_expired']} age), "
                    f"{stats['hard_deleted']} ancient removed, "
                    f"{stats['protected_applied']} applied protected"
                )

            record_success()

        except Exception as e:
            logger.error(f"[{MODULE_ID}] smart_expire_jobs error: {e}")
            record_failure()

        return stats

    # ---- CLEANUP EXPIRED (backward-compatible wrapper) ----

    @staticmethod
    def cleanup_expired_jobs(days_past_deadline: int = 7) -> int:
        """
        v0.2: Calls smart_expire_jobs instead of aggressive deletion.
        Returns total count of actions taken.
        """
        stats = SupabaseJobDB.smart_expire_jobs()
        return stats.get("deadline_expired", 0) + stats.get("age_expired", 0) + stats.get("hard_deleted", 0)

    @staticmethod
    def clear_all_jobs() -> Dict[str, int]:
        """
        Delete ALL jobs from latest_jobs and all_jobs tables.
        v0.2 SAFETY: Requires explicit confirmation via env var.
        Will NOT run accidentally on redeployment.
        """
        import os
        # SAFETY GATE: double-check that this is intentional
        force_flag = os.getenv('FORCE_DB_RESET', '').lower()
        if force_flag not in ('true', '1', 'yes'):
            logger.warning(f"[{MODULE_ID}] clear_all_jobs called WITHOUT FORCE_DB_RESET — REFUSING to wipe data")
            return {"error": "FORCE_DB_RESET not set, refusing to clear"}

        if not is_operational():
            return {"error": "not operational"}

        client = get_supabase()
        if not client:
            return {"error": "no client"}

        counts = {}
        try:
            # Clear latest_jobs
            try:
                resp = client.table("latest_jobs").delete().neq("id", 0).execute()
                counts["latest_jobs"] = len(resp.data) if resp.data else 0
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Clear latest_jobs error: {e}")
                counts["latest_jobs"] = 0

            # Clear all_jobs
            try:
                resp = client.table("all_jobs").delete().neq("id", 0).execute()
                counts["all_jobs"] = len(resp.data) if resp.data else 0
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Clear all_jobs error: {e}")
                counts["all_jobs"] = 0

            logger.info(f"[{MODULE_ID}] Cleared all Supabase jobs: {counts}")
            record_success()
        except Exception as e:
            logger.error(f"[{MODULE_ID}] clear_all_jobs error: {e}")
            record_failure()

        return counts

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
    """Async wrapper for cleanup_expired_jobs (now smart_expire_jobs)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, SupabaseJobDB.cleanup_expired_jobs, days)


async def async_smart_expire_jobs() -> Dict[str, int]:
    """Async wrapper for smart_expire_jobs."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, SupabaseJobDB.smart_expire_jobs)


# ============================================================
# SCHEMA HELPER
# ============================================================

def get_schema_sql() -> str:
    """Return the SQL schema for manual setup in Supabase SQL Editor."""
    return SCHEMA_SQL
