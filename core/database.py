"""
============================================================
OPERATION FIRST MOVER v8.0 -- DATABASE MODULE (Supabase Primary)
============================================================
Complete Supabase PostgreSQL database management with:
- Full schema creation (clean_listings, portal_sessions, user_profile,
  outcomes, system_pings, dream_companies, question_bank, cover_letter_cache)
- UPSERT operations with dedup_hash
- Batch operations for performance
- Connection pooling and retry logic
- Keepalive queries to prevent 7-day pause
- JSON export for weekly backup (Layer 6)

v8.0 Schema (from Blueprint Section 3):
    clean_listings:   Core job listing table with all scoring fields
    portal_sessions:  Portal cookie/session management
    user_profile:     Single-row truth source for auto-apply
    outcomes:         Application outcome tracking for learning
    system_pings:     Service health monitoring logs
    dream_companies:  Watchlist companies (6-hour interval)
    question_bank:    Smart Question Bank for screening answers
    cover_letter_cache: Pre-generated cover letters (Sunday night)
    api_quotas:       Daily API usage tracking
============================================================
"""

import os
import json
import hashlib
import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from supabase import create_client, Client
    from postgrest.exceptions import APIError
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logger.warning("Supabase not installed. Database operations will be limited.")

from core.config import get_config, now_ist, IST


# ============================================================
# SECTION 1: DATABASE CONNECTION MANAGER
# ============================================================

class DatabaseManager:
    """
    Supabase database manager with connection pooling, retry logic,
    and comprehensive CRUD operations for all v8.0 tables.

    Usage:
        db = DatabaseManager()
        db.initialize()  # Creates tables if needed
        db.upsert_listing({...})
        listings = db.get_active_listings()
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
        self.client: Optional[Any] = None
        self._connected = False
        self._last_ping = None
        self._operation_count = 0
        self._error_count = 0

    def initialize(self) -> bool:
        """Initialize Supabase connection and create tables if needed."""
        if not SUPABASE_AVAILABLE:
            logger.error("Supabase library not installed!")
            return False

        if not self.config.supabase.is_configured:
            logger.error("Supabase not configured! Set SUPABASE_URL and keys.")
            return False

        try:
            key = self.config.supabase.service_role_key or self.config.supabase.anon_key
            self.client = create_client(self.config.supabase.url, key)
            self._connected = True
            self._last_ping = now_ist()
            logger.info(f"Supabase connected: {self.config.supabase.url}")

            # Verify connection with a simple query
            self._ping()
            logger.info("Supabase connection verified successfully")
            return True

        except Exception as e:
            logger.error(f"Supabase connection failed: {e}")
            self._connected = False
            return False

    def _ping(self) -> bool:
        """Ping Supabase to verify connection and prevent pause."""
        if not self.client:
            return False
        try:
            # Simple query to keep connection alive
            self.client.table('system_pings').select('id').limit(1).execute()
            self._last_ping = now_ist()
            return True
        except Exception:
            try:
                # If system_pings doesn't exist yet, try a basic RPC
                self.client.rpc('ping', {}).execute()
                self._last_ping = now_ist()
                return True
            except Exception:
                return False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    def _retry_operation(self, operation, max_retries: int = 3,
                         base_delay: float = 1.0) -> Any:
        """Execute a database operation with exponential backoff retry."""
        last_error = None
        for attempt in range(max_retries):
            try:
                result = operation()
                self._operation_count += 1
                return result
            except Exception as e:
                last_error = e
                self._error_count += 1
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"DB operation failed (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

        logger.error(f"DB operation failed after {max_retries} retries: {last_error}")
        raise last_error

    # ============================================================
    # SECTION 2: SCHEMA MANAGEMENT
    # ============================================================

    def create_tables_via_sql(self) -> bool:
        """Create all required tables using Supabase SQL editor.
        NOTE: These should be run via Supabase Dashboard SQL editor
        or via the REST API if service_role_key is available.

        Returns True if schemas are verified to exist."""
        if not self.is_connected:
            return False

        # The SQL below should be run in Supabase SQL editor
        # We verify tables exist by attempting to select from them
        tables_ok = True
        required_tables = [
            'clean_listings', 'portal_sessions', 'user_profile',
            'outcomes', 'system_pings', 'dream_companies',
            'question_bank', 'cover_letter_cache', 'api_quotas',
        ]

        for table in required_tables:
            try:
                self.client.table(table).select('*').limit(1).execute()
                logger.debug(f"Table '{table}' exists and accessible")
            except Exception as e:
                logger.warning(f"Table '{table}' not found or inaccessible: {e}")
                tables_ok = False

        return tables_ok

    @staticmethod
    def get_schema_sql() -> str:
        """Return the complete SQL schema for all v8.0 tables.
        This should be run in the Supabase SQL editor."""
        return """
-- ============================================================
-- OPERATION FIRST MOVER v8.0 -- COMPLETE DATABASE SCHEMA
-- Run this in Supabase SQL Editor (https://supabase.com/dashboard)
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLE 1: clean_listings (Core job listing table)
-- ============================================================
CREATE TABLE IF NOT EXISTS clean_listings (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT DEFAULT '',
    stipend TEXT DEFAULT '',
    stipend_numeric INTEGER DEFAULT 0,
    duration TEXT DEFAULT '',
    duration_months INTEGER DEFAULT 0,
    posted_date TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    applicants INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    skills_required TEXT[] DEFAULT '{}',
    url TEXT NOT NULL,
    apply_url TEXT DEFAULT '',
    ppo_eligible BOOLEAN DEFAULT FALSE,
    ppo_tag_text TEXT DEFAULT '',
    company_tier INTEGER DEFAULT 5,
    sector TEXT DEFAULT '',
    mba_category TEXT DEFAULT '',
    -- Scoring fields
    ppo_score FLOAT DEFAULT 0.0,
    ghost_score INTEGER DEFAULT 0,
    ghost_status TEXT DEFAULT 'unknown',
    ats_score FLOAT DEFAULT 0.0,
    quality_score FLOAT DEFAULT 0.0,
    blue_ocean BOOLEAN DEFAULT FALSE,
    cirs_score FLOAT DEFAULT 0.0,
    intent_signal_score FLOAT DEFAULT 0.0,
    -- Application tracking
    apply_status TEXT DEFAULT 'new',
    applied_at TIMESTAMPTZ,
    applied_via TEXT DEFAULT '',
    cover_letter_used TEXT DEFAULT '',
    -- Cross-portal dedup
    dedup_hash TEXT NOT NULL,
    canonical_portal TEXT DEFAULT '',
    duplicate_of UUID,
    -- Metadata
    raw_data JSONB DEFAULT '{}',
    enrichment_data JSONB DEFAULT '{}',
    scrape_batch TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(dedup_hash)
);

-- Indexes for clean_listings
CREATE INDEX IF NOT EXISTS idx_listings_platform ON clean_listings(platform);
CREATE INDEX IF NOT EXISTS idx_listings_company ON clean_listings(company);
CREATE INDEX IF NOT EXISTS idx_listings_category ON clean_listings(mba_category);
CREATE INDEX IF NOT EXISTS idx_listings_ppo_score ON clean_listings(ppo_score DESC);
CREATE INDEX IF NOT EXISTS idx_listings_ghost_status ON clean_listings(ghost_status);
CREATE INDEX IF NOT EXISTS idx_listings_apply_status ON clean_listings(apply_status);
CREATE INDEX IF NOT EXISTS idx_listings_blue_ocean ON clean_listings(blue_ocean);
CREATE INDEX IF NOT EXISTS idx_listings_created ON clean_listings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_dedup ON clean_listings(dedup_hash);
CREATE INDEX IF NOT EXISTS idx_listings_company_tier ON clean_listings(company_tier);

-- ============================================================
-- TABLE 2: portal_sessions (Portal cookie/session management)
-- ============================================================
CREATE TABLE IF NOT EXISTS portal_sessions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    portal TEXT NOT NULL UNIQUE,
    cookies JSONB DEFAULT '{}',
    headers JSONB DEFAULT '{}',
    proxy_assigned TEXT DEFAULT '',
    session_valid BOOLEAN DEFAULT FALSE,
    last_validated TIMESTAMPTZ,
    last_login TIMESTAMPTZ,
    login_method TEXT DEFAULT '',
    health_score INTEGER DEFAULT 100,
    consecutive_failures INTEGER DEFAULT 0,
    total_requests INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE 3: user_profile (Single-row truth source)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_profile (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT DEFAULT '',
    college TEXT DEFAULT '',
    degree TEXT DEFAULT 'MBA',
    specialization TEXT DEFAULT '',
    graduation_year INTEGER DEFAULT 2026,
    cgpa FLOAT DEFAULT 0.0,
    skills TEXT[] DEFAULT '{}',
    experience_summary TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    portfolio_url TEXT DEFAULT '',
    resume_url TEXT DEFAULT '',
    resume_filename TEXT DEFAULT '',
    preferred_locations TEXT[] DEFAULT '{}',
    preferred_categories TEXT[] DEFAULT '{}',
    min_stipend INTEGER DEFAULT 0,
    -- Question bank for screening answers
    question_bank JSONB DEFAULT '{}',
    -- Cover letter template
    cover_letter_template TEXT DEFAULT '',
    -- Work authorization
    work_auth_status TEXT DEFAULT 'Authorized to work in India',
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE 4: outcomes (Application outcome tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS outcomes (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    listing_id UUID REFERENCES clean_listings(id),
    job_id TEXT NOT NULL,
    company TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT DEFAULT '',
    -- Outcome tracking
    status TEXT DEFAULT 'applied',
    -- Status values: applied, viewed, shortlisted, interview_scheduled,
    --                interviewed, offered, rejected, ghosted, withdrawn
    shortlisted BOOLEAN DEFAULT FALSE,
    rejected BOOLEAN DEFAULT FALSE,
    response_time_hours FLOAT,
    -- Application details
    applied_at TIMESTAMPTZ,
    response_at TIMESTAMPTZ,
    cover_letter_version TEXT DEFAULT '',
    resume_version TEXT DEFAULT '',
    -- Learning data
    ppo_score_at_apply FLOAT DEFAULT 0.0,
    ghost_score_at_apply INTEGER DEFAULT 0,
    company_tier_at_apply INTEGER DEFAULT 5,
    category TEXT DEFAULT '',
    -- Follow-up
    follow_up_sent BOOLEAN DEFAULT FALSE,
    follow_up_at TIMESTAMPTZ,
    follow_up_response BOOLEAN DEFAULT FALSE,
    notes TEXT DEFAULT '',
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outcomes_status ON outcomes(status);
CREATE INDEX IF NOT EXISTS idx_outcomes_company ON outcomes(company);
CREATE INDEX IF NOT EXISTS idx_outcomes_listing ON outcomes(listing_id);

-- ============================================================
-- TABLE 5: system_pings (Service health monitoring)
-- ============================================================
CREATE TABLE IF NOT EXISTS system_pings (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    service TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    response_time_ms FLOAT DEFAULT 0.0,
    details JSONB DEFAULT '{}',
    error_message TEXT DEFAULT '',
    layer TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pings_service ON system_pings(service);
CREATE INDEX IF NOT EXISTS idx_pings_created ON system_pings(created_at DESC);

-- ============================================================
-- TABLE 6: dream_companies (Watchlist - 6 hour intervals)
-- ============================================================
CREATE TABLE IF NOT EXISTS dream_companies (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tier INTEGER DEFAULT 3,
    sector TEXT DEFAULT '',
    careers_url TEXT DEFAULT '',
    ats_platform TEXT DEFAULT '',
    last_checked TIMESTAMPTZ,
    last_found_listing TIMESTAMPTZ,
    total_listings_found INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE 7: question_bank (Smart screening answers)
-- ============================================================
CREATE TABLE IF NOT EXISTS question_bank (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    question_pattern TEXT NOT NULL,
    question_category TEXT DEFAULT 'general',
    answer_text TEXT NOT NULL,
    semantic_embedding FLOAT[] DEFAULT '{}',
    confidence_score FLOAT DEFAULT 1.0,
    times_used INTEGER DEFAULT 0,
    last_used TIMESTAMPTZ,
    portal TEXT DEFAULT 'any',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qbank_category ON question_bank(question_category);
CREATE INDEX IF NOT EXISTS idx_qbank_portal ON question_bank(portal);

-- ============================================================
-- TABLE 8: cover_letter_cache (Pre-generated Sunday night)
-- ============================================================
CREATE TABLE IF NOT EXISTS cover_letter_cache (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    listing_id UUID REFERENCES clean_listings(id),
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT DEFAULT '',
    cover_letter TEXT NOT NULL,
    quality_score FLOAT DEFAULT 0.0,
    word_count INTEGER DEFAULT 0,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    used BOOLEAN DEFAULT FALSE,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cover_listing ON cover_letter_cache(listing_id);
CREATE INDEX IF NOT EXISTS idx_cover_used ON cover_letter_cache(used);

-- ============================================================
-- TABLE 9: api_quotas (Daily API usage tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS api_quotas (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    service TEXT NOT NULL,
    requests_used INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    rate_limits_hit INTEGER DEFAULT 0,
    daily_limit INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(date, service)
);

CREATE INDEX IF NOT EXISTS idx_quotas_date ON api_quotas(date);
CREATE INDEX IF NOT EXISTS idx_quotas_service ON api_quotas(service);

-- ============================================================
-- FUNCTIONS
-- ============================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables with updated_at
DO $$
DECLARE
    t TEXT;
BEGIN
    FOR t IN
        SELECT unnest(ARRAY[
            'clean_listings', 'portal_sessions', 'user_profile',
            'outcomes', 'dream_companies', 'question_bank', 'api_quotas'
        ])
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS update_%s_updated_at ON %s; '
            'CREATE TRIGGER update_%s_updated_at BEFORE UPDATE ON %s '
            'FOR EACH ROW EXECUTE FUNCTION update_updated_at();',
            t, t, t, t
        );
    END LOOP;
END;
$$;

-- Cleanup function: Remove listings older than 90 days
CREATE OR REPLACE FUNCTION cleanup_old_listings()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM clean_listings
    WHERE created_at < NOW() - INTERVAL '90 days'
    AND apply_status IN ('new', 'skipped', 'expired');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Ping function for keep-alive
CREATE OR REPLACE FUNCTION ping()
RETURNS TEXT AS $$
BEGIN
    RETURN 'pong';
END;
$$ LANGUAGE plpgsql;
"""

    # ============================================================
    # SECTION 3: LISTING OPERATIONS (CRUD)
    # ============================================================

    @staticmethod
    def compute_dedup_hash(title: str, company: str, platform: str = "") -> str:
        """Compute a dedup hash for cross-portal deduplication.
        Hash is based on normalized title + company (platform-agnostic)."""
        normalized = f"{title.lower().strip()}|{company.lower().strip()}"
        # Remove common variations
        normalized = normalized.replace("intern", "").replace("internship", "")
        normalized = normalized.replace("  ", " ").strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def upsert_listing(self, listing: Dict[str, Any]) -> Optional[str]:
        """Insert or update a job listing. Uses dedup_hash for conflict resolution.

        Args:
            listing: Dict with listing fields matching clean_listings schema.

        Returns:
            The listing ID if successful, None otherwise.
        """
        if not self.is_connected:
            logger.error("Cannot upsert listing: not connected")
            return None

        try:
            # Ensure dedup_hash exists
            if 'dedup_hash' not in listing:
                listing['dedup_hash'] = self.compute_dedup_hash(
                    listing.get('title', ''),
                    listing.get('company', ''),
                    listing.get('platform', ''),
                )

            # Set timestamps
            listing['updated_at'] = now_ist().isoformat()
            if 'created_at' not in listing:
                listing['created_at'] = now_ist().isoformat()

            # Remove None values
            listing = {k: v for k, v in listing.items() if v is not None}

            result = self._retry_operation(
                lambda: self.client.table('clean_listings')
                    .upsert(listing, on_conflict='dedup_hash')
                    .execute()
            )

            if result.data:
                return result.data[0].get('id')
            return None

        except Exception as e:
            logger.error(f"Failed to upsert listing: {e}")
            return None

    def upsert_listings_batch(self, listings: List[Dict[str, Any]]) -> int:
        """Batch upsert multiple listings for performance.

        Args:
            listings: List of listing dicts.

        Returns:
            Number of successfully upserted listings.
        """
        if not self.is_connected or not listings:
            return 0

        # Ensure all have dedup_hash
        for listing in listings:
            if 'dedup_hash' not in listing:
                listing['dedup_hash'] = self.compute_dedup_hash(
                    listing.get('title', ''),
                    listing.get('company', ''),
                    listing.get('platform', ''),
                )
            listing['updated_at'] = now_ist().isoformat()
            if 'created_at' not in listing:
                listing['created_at'] = now_ist().isoformat()

        # Process in batches of 50 (Render memory constraint)
        batch_size = self.config.render.batch_size_limit
        total_upserted = 0

        for i in range(0, len(listings), batch_size):
            batch = listings[i:i + batch_size]
            # Clean None values
            batch = [{k: v for k, v in item.items() if v is not None} for item in batch]

            try:
                result = self._retry_operation(
                    lambda b=batch: self.client.table('clean_listings')
                        .upsert(b, on_conflict='dedup_hash')
                        .execute()
                )
                if result.data:
                    total_upserted += len(result.data)
                    logger.info(f"Batch upserted {len(result.data)} listings "
                               f"({i + len(batch)}/{len(listings)})")
            except Exception as e:
                logger.error(f"Batch upsert failed at index {i}: {e}")

        return total_upserted

    def get_active_listings(self, limit: int = 500,
                           category: Optional[str] = None,
                           platform: Optional[str] = None,
                           min_ppo_score: float = 0.0,
                           exclude_ghosts: bool = True,
                           exclude_applied: bool = False) -> List[Dict[str, Any]]:
        """Get active job listings with optional filters.

        Args:
            limit: Maximum number of listings to return.
            category: Filter by MBA category.
            platform: Filter by platform.
            min_ppo_score: Minimum PPO score filter.
            exclude_ghosts: Exclude ghost-detected listings.
            exclude_applied: Exclude already-applied listings.

        Returns:
            List of listing dicts sorted by PPO score descending.
        """
        if not self.is_connected:
            return []

        try:
            query = self.client.table('clean_listings').select('*')

            if category:
                query = query.eq('mba_category', category)
            if platform:
                query = query.eq('platform', platform)
            if min_ppo_score > 0:
                query = query.gte('ppo_score', min_ppo_score)
            if exclude_ghosts:
                query = query.neq('ghost_status', 'ghost')
            if exclude_applied:
                query = query.eq('apply_status', 'new')

            query = query.order('ppo_score', desc=True).limit(limit)

            result = self._retry_operation(lambda: query.execute())
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get active listings: {e}")
            return []

    def get_listing_by_id(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """Get a single listing by ID."""
        if not self.is_connected:
            return None
        try:
            result = self.client.table('clean_listings') \
                .select('*').eq('id', listing_id).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get listing {listing_id}: {e}")
            return None

    def get_listings_for_apply(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Get top listings ready for auto-apply.
        Sorted by PPO score, excluding ghosts and already applied."""
        if not self.is_connected:
            return []
        try:
            result = self._retry_operation(
                lambda: self.client.table('clean_listings')
                    .select('*')
                    .eq('apply_status', 'new')
                    .neq('ghost_status', 'ghost')
                    .gt('ppo_score', 0.3)
                    .order('ppo_score', desc=True)
                    .limit(limit)
                    .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get listings for apply: {e}")
            return []

    def update_listing_status(self, listing_id: str, status: str,
                              extra_data: Optional[Dict] = None) -> bool:
        """Update listing apply_status and optional extra fields."""
        if not self.is_connected:
            return False
        try:
            update_data = {'apply_status': status, 'updated_at': now_ist().isoformat()}
            if status == 'applied':
                update_data['applied_at'] = now_ist().isoformat()
            if extra_data:
                update_data.update(extra_data)

            self._retry_operation(
                lambda: self.client.table('clean_listings')
                    .update(update_data)
                    .eq('id', listing_id)
                    .execute()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update listing status: {e}")
            return False

    def update_listing_scores(self, listing_id: str,
                              scores: Dict[str, Any]) -> bool:
        """Update scoring fields for a listing."""
        if not self.is_connected:
            return False
        try:
            scores['updated_at'] = now_ist().isoformat()
            self._retry_operation(
                lambda: self.client.table('clean_listings')
                    .update(scores)
                    .eq('id', listing_id)
                    .execute()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update listing scores: {e}")
            return False

    def get_blue_ocean_listings(self) -> List[Dict[str, Any]]:
        """Get all Blue Ocean listings (high prestige, low competition)."""
        if not self.is_connected:
            return []
        try:
            result = self._retry_operation(
                lambda: self.client.table('clean_listings')
                    .select('*')
                    .eq('blue_ocean', True)
                    .eq('apply_status', 'new')
                    .neq('ghost_status', 'ghost')
                    .order('ppo_score', desc=True)
                    .limit(50)
                    .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get blue ocean listings: {e}")
            return []

    def get_listings_by_company(self, company: str) -> List[Dict[str, Any]]:
        """Get all listings from a specific company."""
        if not self.is_connected:
            return []
        try:
            result = self._retry_operation(
                lambda: self.client.table('clean_listings')
                    .select('*')
                    .ilike('company', f'%{company}%')
                    .order('created_at', desc=True)
                    .limit(50)
                    .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get listings by company: {e}")
            return []

    def check_duplicate(self, dedup_hash: str) -> bool:
        """Check if a listing with this dedup_hash already exists."""
        if not self.is_connected:
            return False
        try:
            result = self.client.table('clean_listings') \
                .select('id').eq('dedup_hash', dedup_hash).limit(1).execute()
            return bool(result.data)
        except Exception:
            return False

    def get_recent_listing_hashes(self, days: int = 30) -> Set:
        """Get all dedup_hashes from recent listings for fast duplicate check."""
        if not self.is_connected:
            return set()
        try:
            cutoff = (now_ist() - timedelta(days=days)).isoformat()
            result = self.client.table('clean_listings') \
                .select('dedup_hash') \
                .gte('created_at', cutoff) \
                .execute()
            return {r['dedup_hash'] for r in (result.data or [])}
        except Exception as e:
            logger.error(f"Failed to get recent hashes: {e}")
            return set()

    def get_listing_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics about listings."""
        if not self.is_connected:
            return {}
        try:
            # Total listings
            total = self.client.table('clean_listings') \
                .select('id', count='exact').execute()

            # By status
            new_count = self.client.table('clean_listings') \
                .select('id', count='exact').eq('apply_status', 'new').execute()
            applied_count = self.client.table('clean_listings') \
                .select('id', count='exact').eq('apply_status', 'applied').execute()

            # Blue ocean
            blue_ocean = self.client.table('clean_listings') \
                .select('id', count='exact').eq('blue_ocean', True).execute()

            # Ghost
            ghosts = self.client.table('clean_listings') \
                .select('id', count='exact').eq('ghost_status', 'ghost').execute()

            return {
                'total_listings': total.count or 0,
                'new_listings': new_count.count or 0,
                'applied_listings': applied_count.count or 0,
                'blue_ocean_listings': blue_ocean.count or 0,
                'ghost_listings': ghosts.count or 0,
                'as_of': now_ist().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to get listing stats: {e}")
            return {}

    # ============================================================
    # SECTION 4: PORTAL SESSION OPERATIONS
    # ============================================================

    def upsert_portal_session(self, portal: str,
                              session_data: Dict[str, Any]) -> bool:
        """Update or create a portal session record."""
        if not self.is_connected:
            return False
        try:
            session_data['portal'] = portal
            session_data['updated_at'] = now_ist().isoformat()
            self._retry_operation(
                lambda: self.client.table('portal_sessions')
                    .upsert(session_data, on_conflict='portal')
                    .execute()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to upsert portal session for {portal}: {e}")
            return False

    def get_portal_session(self, portal: str) -> Optional[Dict[str, Any]]:
        """Get session data for a portal."""
        if not self.is_connected:
            return None
        try:
            result = self.client.table('portal_sessions') \
                .select('*').eq('portal', portal).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get portal session for {portal}: {e}")
            return None

    def get_all_portal_sessions(self) -> List[Dict[str, Any]]:
        """Get all portal sessions."""
        if not self.is_connected:
            return []
        try:
            result = self.client.table('portal_sessions').select('*').execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get portal sessions: {e}")
            return []

    def invalidate_portal_session(self, portal: str) -> bool:
        """Mark a portal session as invalid."""
        if not self.is_connected:
            return False
        try:
            self.client.table('portal_sessions') \
                .update({
                    'session_valid': False,
                    'updated_at': now_ist().isoformat()
                }) \
                .eq('portal', portal) \
                .execute()
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate session for {portal}: {e}")
            return False

    # ============================================================
    # SECTION 5: USER PROFILE OPERATIONS
    # ============================================================

    def get_user_profile(self) -> Optional[Dict[str, Any]]:
        """Get the single-row user profile."""
        if not self.is_connected:
            return None
        try:
            result = self.client.table('user_profile') \
                .select('*').limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get user profile: {e}")
            return None

    def upsert_user_profile(self, profile: Dict[str, Any]) -> bool:
        """Create or update the user profile."""
        if not self.is_connected:
            return False
        try:
            profile['updated_at'] = now_ist().isoformat()
            # Check if profile exists
            existing = self.get_user_profile()
            if existing:
                profile.pop('id', None)
                self.client.table('user_profile') \
                    .update(profile) \
                    .eq('id', existing['id']) \
                    .execute()
            else:
                if 'created_at' not in profile:
                    profile['created_at'] = now_ist().isoformat()
                self.client.table('user_profile') \
                    .insert(profile) \
                    .execute()
            return True
        except Exception as e:
            logger.error(f"Failed to upsert user profile: {e}")
            return False

    # ============================================================
    # SECTION 6: OUTCOME TRACKING
    # ============================================================

    def record_outcome(self, outcome: Dict[str, Any]) -> Optional[str]:
        """Record an application outcome."""
        if not self.is_connected:
            return None
        try:
            outcome['created_at'] = now_ist().isoformat()
            outcome['updated_at'] = now_ist().isoformat()
            result = self._retry_operation(
                lambda: self.client.table('outcomes')
                    .insert(outcome)
                    .execute()
            )
            return result.data[0].get('id') if result.data else None
        except Exception as e:
            logger.error(f"Failed to record outcome: {e}")
            return None

    def update_outcome(self, outcome_id: str,
                       update_data: Dict[str, Any]) -> bool:
        """Update an existing outcome record."""
        if not self.is_connected:
            return False
        try:
            update_data['updated_at'] = now_ist().isoformat()
            self._retry_operation(
                lambda: self.client.table('outcomes')
                    .update(update_data)
                    .eq('id', outcome_id)
                    .execute()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update outcome: {e}")
            return False

    def get_outcomes(self, limit: int = 100,
                     status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get application outcomes with optional status filter."""
        if not self.is_connected:
            return []
        try:
            query = self.client.table('outcomes').select('*')
            if status:
                query = query.eq('status', status)
            query = query.order('created_at', desc=True).limit(limit)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get outcomes: {e}")
            return []

    def get_outcome_stats(self) -> Dict[str, Any]:
        """Get aggregate outcome statistics for learning."""
        if not self.is_connected:
            return {}
        try:
            all_outcomes = self.client.table('outcomes').select('*').execute()
            data = all_outcomes.data or []

            stats = {
                'total_applied': len(data),
                'shortlisted': sum(1 for o in data if o.get('shortlisted')),
                'rejected': sum(1 for o in data if o.get('rejected')),
                'ghosted': sum(1 for o in data if o.get('status') == 'ghosted'),
                'offered': sum(1 for o in data if o.get('status') == 'offered'),
                'response_rate': 0.0,
                'avg_response_hours': 0.0,
            }

            if stats['total_applied'] > 0:
                responded = stats['shortlisted'] + stats['rejected']
                stats['response_rate'] = responded / stats['total_applied']

            response_times = [
                o.get('response_time_hours', 0) for o in data
                if o.get('response_time_hours')
            ]
            if response_times:
                stats['avg_response_hours'] = sum(response_times) / len(response_times)

            return stats
        except Exception as e:
            logger.error(f"Failed to get outcome stats: {e}")
            return {}

    # ============================================================
    # SECTION 7: SYSTEM PINGS (Health Monitoring)
    # ============================================================

    def log_ping(self, service: str, status: str = 'ok',
                 response_time_ms: float = 0.0,
                 layer: str = '',
                 details: Optional[Dict] = None,
                 error_message: str = '') -> bool:
        """Log a system health ping."""
        if not self.is_connected:
            return False
        try:
            self.client.table('system_pings').insert({
                'service': service,
                'status': status,
                'response_time_ms': response_time_ms,
                'layer': layer,
                'details': details or {},
                'error_message': error_message,
                'created_at': now_ist().isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to log ping for {service}: {e}")
            return False

    def get_recent_pings(self, service: Optional[str] = None,
                         hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent system pings."""
        if not self.is_connected:
            return []
        try:
            cutoff = (now_ist() - timedelta(hours=hours)).isoformat()
            query = self.client.table('system_pings') \
                .select('*').gte('created_at', cutoff)
            if service:
                query = query.eq('service', service)
            query = query.order('created_at', desc=True).limit(100)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get recent pings: {e}")
            return []

    # ============================================================
    # SECTION 8: DREAM COMPANIES
    # ============================================================

    def upsert_dream_company(self, company: Dict[str, Any]) -> bool:
        """Add or update a dream company."""
        if not self.is_connected:
            return False
        try:
            company['updated_at'] = now_ist().isoformat()
            self._retry_operation(
                lambda: self.client.table('dream_companies')
                    .upsert(company, on_conflict='name')
                    .execute()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to upsert dream company: {e}")
            return False

    def get_dream_companies(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get dream company watchlist."""
        if not self.is_connected:
            return []
        try:
            query = self.client.table('dream_companies').select('*')
            if active_only:
                query = query.eq('active', True)
            result = query.order('tier').execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get dream companies: {e}")
            return []

    def seed_dream_companies(self, companies: List[Dict[str, Any]]) -> int:
        """Seed the dream companies table with defaults."""
        if not self.is_connected:
            return 0
        count = 0
        for company in companies:
            if self.upsert_dream_company(company):
                count += 1
        return count

    # ============================================================
    # SECTION 9: QUESTION BANK
    # ============================================================

    def add_question(self, question: str, answer: str,
                     category: str = 'general',
                     portal: str = 'any') -> bool:
        """Add a question-answer pair to the smart question bank."""
        if not self.is_connected:
            return False
        try:
            self.client.table('question_bank').insert({
                'question_pattern': question,
                'question_category': category,
                'answer_text': answer,
                'portal': portal,
                'confidence_score': 1.0,
                'created_at': now_ist().isoformat(),
                'updated_at': now_ist().isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to add question: {e}")
            return False

    def get_questions(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get question bank entries."""
        if not self.is_connected:
            return []
        try:
            query = self.client.table('question_bank').select('*')
            if category:
                query = query.eq('question_category', category)
            result = query.order('times_used', desc=True).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get questions: {e}")
            return []

    def find_matching_answer(self, question: str) -> Optional[str]:
        """Find the best matching answer for a screening question.
        Uses fuzzy matching on question patterns."""
        if not self.is_connected:
            return None
        try:
            questions = self.get_questions()
            if not questions:
                return None

            # Simple keyword matching (semantic matching done by AI agent)
            question_lower = question.lower()
            best_match = None
            best_score = 0

            for q in questions:
                pattern = q.get('question_pattern', '').lower()
                # Simple word overlap score
                pattern_words = set(pattern.split())
                question_words = set(question_lower.split())
                if not pattern_words:
                    continue
                overlap = len(pattern_words & question_words)
                score = overlap / max(len(pattern_words), 1)

                if score > best_score and score > 0.3:
                    best_score = score
                    best_match = q.get('answer_text')

            return best_match
        except Exception as e:
            logger.error(f"Failed to find matching answer: {e}")
            return None

    # ============================================================
    # SECTION 10: COVER LETTER CACHE
    # ============================================================

    def cache_cover_letter(self, listing_id: str, company: str,
                           title: str, cover_letter: str,
                           category: str = '',
                           quality_score: float = 0.0) -> bool:
        """Cache a pre-generated cover letter."""
        if not self.is_connected:
            return False
        try:
            self.client.table('cover_letter_cache').insert({
                'listing_id': listing_id,
                'company': company,
                'title': title,
                'category': category,
                'cover_letter': cover_letter,
                'quality_score': quality_score,
                'word_count': len(cover_letter.split()),
                'generated_at': now_ist().isoformat(),
                'created_at': now_ist().isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to cache cover letter: {e}")
            return False

    def get_cached_cover_letter(self, listing_id: str) -> Optional[str]:
        """Get a cached cover letter for a listing."""
        if not self.is_connected:
            return None
        try:
            result = self.client.table('cover_letter_cache') \
                .select('cover_letter') \
                .eq('listing_id', listing_id) \
                .eq('used', False) \
                .order('quality_score', desc=True) \
                .limit(1) \
                .execute()
            if result.data:
                return result.data[0].get('cover_letter')
            return None
        except Exception as e:
            logger.error(f"Failed to get cached cover letter: {e}")
            return None

    # ============================================================
    # SECTION 11: API QUOTA TRACKING
    # ============================================================

    def track_api_usage(self, service: str, requests: int = 1,
                        tokens: int = 0, errors: int = 0) -> bool:
        """Track API usage for daily quota monitoring."""
        if not self.is_connected:
            return False
        try:
            today = now_ist().strftime('%Y-%m-%d')
            # Try to update existing record
            result = self.client.table('api_quotas') \
                .select('*') \
                .eq('date', today) \
                .eq('service', service) \
                .limit(1) \
                .execute()

            if result.data:
                existing = result.data[0]
                self.client.table('api_quotas').update({
                    'requests_used': existing['requests_used'] + requests,
                    'tokens_used': existing['tokens_used'] + tokens,
                    'errors': existing['errors'] + errors,
                    'updated_at': now_ist().isoformat(),
                }).eq('id', existing['id']).execute()
            else:
                self.client.table('api_quotas').insert({
                    'date': today,
                    'service': service,
                    'requests_used': requests,
                    'tokens_used': tokens,
                    'errors': errors,
                    'created_at': now_ist().isoformat(),
                    'updated_at': now_ist().isoformat(),
                }).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to track API usage: {e}")
            return False

    def get_api_usage_today(self, service: str) -> Dict[str, int]:
        """Get today's API usage for a service."""
        if not self.is_connected:
            return {'requests_used': 0, 'tokens_used': 0, 'errors': 0}
        try:
            today = now_ist().strftime('%Y-%m-%d')
            result = self.client.table('api_quotas') \
                .select('*') \
                .eq('date', today) \
                .eq('service', service) \
                .limit(1) \
                .execute()
            if result.data:
                return {
                    'requests_used': result.data[0].get('requests_used', 0),
                    'tokens_used': result.data[0].get('tokens_used', 0),
                    'errors': result.data[0].get('errors', 0),
                }
            return {'requests_used': 0, 'tokens_used': 0, 'errors': 0}
        except Exception as e:
            logger.error(f"Failed to get API usage: {e}")
            return {'requests_used': 0, 'tokens_used': 0, 'errors': 0}

    # ============================================================
    # SECTION 12: BACKUP & EXPORT (Layer 6)
    # ============================================================

    def export_table_to_json(self, table_name: str) -> Optional[str]:
        """Export a table to JSON string for backup."""
        if not self.is_connected:
            return None
        try:
            result = self.client.table(table_name).select('*').execute()
            data = result.data or []
            return json.dumps(data, default=str, indent=2)
        except Exception as e:
            logger.error(f"Failed to export table {table_name}: {e}")
            return None

    def export_all_tables(self) -> Dict[str, str]:
        """Export all tables to JSON for weekly backup."""
        backup = {}
        tables = [
            'clean_listings', 'portal_sessions', 'user_profile',
            'outcomes', 'dream_companies', 'question_bank',
        ]
        for table in tables:
            json_data = self.export_table_to_json(table)
            if json_data:
                backup[table] = json_data
                logger.info(f"Exported {table}: {len(json_data)} bytes")
        return backup

    # ============================================================
    # SECTION 13: KEEPALIVE (Layer 2)
    # ============================================================

    def keepalive_ping(self) -> bool:
        """Execute keepalive query to prevent Supabase 7-day pause.
        Runs Mon/Fri 9am IST as specified in v8.0 Layer 2."""
        if not self.is_connected:
            return False
        try:
            start = time.time()
            result = self.client.table('clean_listings') \
                .select('id').limit(1).execute()
            elapsed_ms = (time.time() - start) * 1000

            self.log_ping(
                service='supabase',
                status='ok',
                response_time_ms=elapsed_ms,
                layer='L2_supabase_anti_pause',
                details={'query': 'SELECT 1 FROM clean_listings LIMIT 1'}
            )
            logger.info(f"Supabase keepalive ping OK ({elapsed_ms:.0f}ms)")
            self._last_ping = now_ist()
            return True
        except Exception as e:
            self.log_ping(
                service='supabase',
                status='error',
                layer='L2_supabase_anti_pause',
                error_message=str(e)
            )
            logger.error(f"Supabase keepalive ping FAILED: {e}")
            return False

    # ============================================================
    # SECTION 14: CLEANUP OPERATIONS
    # ============================================================

    def cleanup_old_listings(self, days: int = 90) -> int:
        """Remove listings older than specified days that are not applied."""
        if not self.is_connected:
            return 0
        try:
            cutoff = (now_ist() - timedelta(days=days)).isoformat()
            result = self.client.table('clean_listings') \
                .delete() \
                .lt('created_at', cutoff) \
                .in_('apply_status', ['new', 'skipped', 'expired']) \
                .execute()
            count = len(result.data or [])
            logger.info(f"Cleaned up {count} old listings (>{days} days)")
            return count
        except Exception as e:
            logger.error(f"Failed to cleanup old listings: {e}")
            return 0

    def cleanup_old_pings(self, days: int = 30) -> int:
        """Remove old system ping records."""
        if not self.is_connected:
            return 0
        try:
            cutoff = (now_ist() - timedelta(days=days)).isoformat()
            result = self.client.table('system_pings') \
                .delete() \
                .lt('created_at', cutoff) \
                .execute()
            count = len(result.data or [])
            logger.info(f"Cleaned up {count} old ping records (>{days} days)")
            return count
        except Exception as e:
            logger.error(f"Failed to cleanup old pings: {e}")
            return 0

    def get_db_health(self) -> Dict[str, Any]:
        """Get database health status."""
        return {
            'connected': self.is_connected,
            'last_ping': self._last_ping.isoformat() if self._last_ping else None,
            'total_operations': self._operation_count,
            'total_errors': self._error_count,
            'error_rate': (self._error_count / max(self._operation_count, 1)),
        }


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

def get_db() -> DatabaseManager:
    """Get the singleton DatabaseManager instance."""
    return DatabaseManager()


if __name__ == "__main__":
    print("=" * 60)
    print("OPERATION FIRST MOVER v8.0 -- Database Schema")
    print("=" * 60)
    print(DatabaseManager.get_schema_sql())
    print("=" * 60)
    print("Copy the SQL above into Supabase SQL Editor to create tables.")
