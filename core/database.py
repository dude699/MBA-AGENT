"""
============================================================
OPERATION FIRST MOVER v5 — DATABASE MODULE
============================================================
Complete SQLite database management with all 12 tables,
migrations, indexes, CRUD operations, backup/restore,
maintenance, and query builders for all 12 agents.

Tables:
    1.  raw_listings         — Unprocessed scraped job listings
    2.  clean_listings       — Deduplicated, scored listings
    3.  companies            — 1080+ Indian company database
    4.  ghost_scores         — 5-signal ghost detection results
    5.  intent_signals       — Hiring intent signals
    6.  outcomes             — Application outcome tracking
    7.  dark_channel_listings — Telegram/X dark channel finds
    8.  alumni_contacts      — Alumni/network discovery
    9.  application_packages — Generated cover letters & ATS tweaks
    10. api_quotas           — API usage tracking per provider
    11. proxy_health         — Proxy pool health monitoring
    12. agent_heartbeats     — Agent status & heartbeat tracking

Architecture:
    - Thread-safe connection pooling via threading.local()
    - WAL journal mode for concurrent reads
    - Automatic schema migration system
    - Comprehensive CRUD for every table
    - Batch insert/update for scraping pipelines
    - Aggregation queries for reports
    - Backup/restore for Render ephemeral disk
    - Auto-maintenance (VACUUM, ANALYZE, checkpoint)
============================================================
"""

import os
import sys
import json
import time
import sqlite3
import hashlib
import threading
import shutil
import gzip
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import (
    Dict, List, Optional, Tuple, Any, Union, Set,
    Iterator, Callable, TypeVar, Generic
)
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager
from enum import Enum

# Local imports
try:
    from core.config import (
        get_config, DatabaseConfig, CompanyTier, TIER_PPO_SCORES,
        MBA_CATEGORIES, COMPANY_SECTORS, IST
    )
except ImportError:
    # Allow standalone testing
    pass

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

SCHEMA_VERSION = 1
MIGRATION_TABLE = "__schema_migrations"

# Listing statuses
class ListingStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    GHOST = "ghost"
    APPLIED = "applied"
    CLOSED = "closed"


class OutcomeStatus(Enum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    PPO = "ppo"
    WITHDRAWN = "withdrawn"


class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    DISABLED = "disabled"
    COMPLETED = "completed"


class SignalType(Enum):
    NEWS = "news"
    HR_POST = "hr_post"
    FUNDING = "funding"
    EXPANSION = "expansion"
    EARNINGS = "earnings"
    LAYOFF = "layoff"
    ACQUISITION = "acquisition"


class ChannelType(Enum):
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    DISCORD = "discord"
    REDDIT = "reddit"


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class RawListing:
    """Unprocessed job listing from any source."""
    id: Optional[int] = None
    title: str = ""
    company: str = ""
    location: str = ""
    stipend: str = ""
    stipend_normalized: float = 0.0
    duration: str = ""
    duration_months: int = 0
    applicants: int = 0
    is_ppo: bool = False
    is_wfh: bool = False
    posted_days_ago: int = 0
    url: str = ""
    source: str = ""
    category: str = ""
    description_text: str = ""
    scraped_at: Optional[str] = None
    batch_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def content_hash(self) -> str:
        """Generate a content hash for dedup purposes."""
        content = f"{self.title}|{self.company}|{self.url}".lower().strip()
        return hashlib.md5(content.encode()).hexdigest()


@dataclass
class CleanListing:
    """Deduplicated and scored job listing."""
    id: Optional[int] = None
    raw_id: Optional[int] = None
    title: str = ""
    company: str = ""
    company_id: Optional[int] = None
    location: str = ""
    stipend_monthly: float = 0.0
    duration_months: int = 0
    applicants: int = 0
    is_ppo: bool = False
    is_wfh: bool = False
    ghost_score: float = 0.0
    is_ghost: bool = False
    ppo_score: float = 0.0
    is_blue_ocean: bool = False
    competition_ratio: float = 0.0
    source: str = ""
    url: str = ""
    description_text: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    status: str = ListingStatus.ACTIVE.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Company:
    """Company in the 1080+ Indian company database."""
    id: Optional[int] = None
    name: str = ""
    normalized_name: str = ""
    tier: int = 5
    sector: str = ""
    sub_sector: str = ""
    size_band: str = "mid"
    hq_city: str = ""
    careers_url: str = ""
    ats_platform: str = ""
    ats_board_id: str = ""
    cirs: float = 40.0
    glassdoor_rating: float = 0.0
    last_signal_scan: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def tier_score(self) -> int:
        return TIER_PPO_SCORES.get(self.tier, 30)


@dataclass
class GhostScore:
    """Ghost detection result for a listing."""
    id: Optional[int] = None
    listing_id: int = 0
    listing_age_score: float = 0.0
    applicant_overload_score: float = 0.0
    repetitive_posting_score: float = 0.0
    no_hr_signal_score: float = 0.0
    ats_mismatch_score: float = 0.0
    total_score: float = 0.0
    is_ghost: bool = False
    scored_at: Optional[str] = None

    def calculate_total(self) -> float:
        self.total_score = (
            self.listing_age_score +
            self.applicant_overload_score +
            self.repetitive_posting_score +
            self.no_hr_signal_score +
            self.ats_mismatch_score
        )
        self.is_ghost = self.total_score >= 60
        return self.total_score


@dataclass
class IntentSignal:
    """Hiring intent signal for a company."""
    id: Optional[int] = None
    company_id: int = 0
    signal_type: str = SignalType.NEWS.value
    signal_text: str = ""
    signal_score: float = 0.0
    source_url: str = ""
    detected_at: Optional[str] = None
    decay_applied: bool = False
    expires_at: Optional[str] = None


@dataclass
class Outcome:
    """Application outcome tracking."""
    id: Optional[int] = None
    listing_id: int = 0
    company_id: Optional[int] = None
    status: str = OutcomeStatus.APPLIED.value
    applied_at: Optional[str] = None
    outcome_at: Optional[str] = None
    notes: str = ""
    ppo_score_at_apply: float = 0.0
    created_at: Optional[str] = None


@dataclass
class DarkChannelListing:
    """Job listing found in dark channels."""
    id: Optional[int] = None
    channel_name: str = ""
    channel_type: str = ChannelType.TELEGRAM.value
    message_text: str = ""
    extracted_company: str = ""
    extracted_role: str = ""
    extracted_url: str = ""
    is_job: bool = False
    confidence: float = 0.0
    detected_at: Optional[str] = None


@dataclass
class AlumniContact:
    """Alumni/network contact for warm intros."""
    id: Optional[int] = None
    company_id: Optional[int] = None
    name: str = ""
    linkedin_url: str = ""
    college: str = ""
    batch_year: str = ""
    current_role: str = ""
    connection_degree: int = 3
    outreach_draft: str = ""
    outreach_status: str = "pending"
    discovered_at: Optional[str] = None


@dataclass
class ApplicationPackage:
    """Generated application materials."""
    id: Optional[int] = None
    listing_id: int = 0
    cover_letter: str = ""
    resume_tweaks: str = ""
    keyword_gaps: str = ""  # JSON string
    keyword_match_pct: float = 0.0
    warm_intro_draft: str = ""
    generated_at: Optional[str] = None


@dataclass
class APIQuota:
    """API usage tracking."""
    id: Optional[int] = None
    provider: str = ""
    date: str = ""
    hour: int = 0
    requests_made: int = 0
    tokens_used: int = 0
    errors: int = 0
    rate_limited: bool = False


@dataclass
class ProxyHealth:
    """Proxy health tracking."""
    id: Optional[int] = None
    proxy_url: str = ""
    proxy_type: str = ""
    is_alive: bool = True
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    last_check: Optional[str] = None
    last_used: Optional[str] = None
    fail_count: int = 0
    blocked_by: str = ""


@dataclass
class AgentHeartbeat:
    """Agent status and heartbeat tracking."""
    id: Optional[int] = None
    agent_id: str = ""
    agent_name: str = ""
    status: str = AgentStatus.IDLE.value
    last_run: Optional[str] = None
    last_success: Optional[str] = None
    items_processed: int = 0
    errors_last_run: int = 0
    total_runs: int = 0
    total_items: int = 0
    avg_duration_sec: float = 0.0
    updated_at: Optional[str] = None


# ============================================================
# SQL SCHEMA DEFINITIONS
# ============================================================

CREATE_TABLES_SQL: List[str] = [
    # ---- Table 1: raw_listings ----
    """
    CREATE TABLE IF NOT EXISTS raw_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        company TEXT NOT NULL DEFAULT '',
        location TEXT DEFAULT '',
        stipend TEXT DEFAULT '',
        stipend_normalized REAL DEFAULT 0.0,
        duration TEXT DEFAULT '',
        duration_months INTEGER DEFAULT 0,
        applicants INTEGER DEFAULT 0,
        is_ppo BOOLEAN DEFAULT 0,
        is_wfh BOOLEAN DEFAULT 0,
        posted_days_ago INTEGER DEFAULT 0,
        url TEXT UNIQUE,
        source TEXT DEFAULT '',
        category TEXT DEFAULT '',
        description_text TEXT DEFAULT '',
        scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        batch_id TEXT DEFAULT '',
        content_hash TEXT DEFAULT ''
    )
    """,

    # ---- Table 2: clean_listings ----
    """
    CREATE TABLE IF NOT EXISTS clean_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_id INTEGER REFERENCES raw_listings(id) ON DELETE SET NULL,
        title TEXT NOT NULL DEFAULT '',
        company TEXT NOT NULL DEFAULT '',
        company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        location TEXT DEFAULT '',
        stipend_monthly REAL DEFAULT 0.0,
        duration_months INTEGER DEFAULT 0,
        applicants INTEGER DEFAULT 0,
        is_ppo BOOLEAN DEFAULT 0,
        is_wfh BOOLEAN DEFAULT 0,
        ghost_score REAL DEFAULT 0.0,
        is_ghost BOOLEAN DEFAULT 0,
        ppo_score REAL DEFAULT 0.0,
        is_blue_ocean BOOLEAN DEFAULT 0,
        competition_ratio REAL DEFAULT 0.0,
        source TEXT DEFAULT '',
        url TEXT UNIQUE,
        description_text TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME,
        status TEXT DEFAULT 'active' CHECK(status IN ('active','expired','ghost','applied','closed'))
    )
    """,

    # ---- Table 3: companies ----
    """
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        normalized_name TEXT DEFAULT '',
        tier INTEGER DEFAULT 5 CHECK(tier BETWEEN 1 AND 5),
        sector TEXT DEFAULT '',
        sub_sector TEXT DEFAULT '',
        size_band TEXT DEFAULT 'mid' CHECK(size_band IN ('startup','small','mid','large','enterprise')),
        hq_city TEXT DEFAULT '',
        careers_url TEXT DEFAULT '',
        ats_platform TEXT DEFAULT '' CHECK(ats_platform IN ('','greenhouse','lever','workday','custom','smartrecruiters','icims','taleo','breezy','jobvite','ashby')),
        ats_board_id TEXT DEFAULT '',
        cirs REAL DEFAULT 40.0 CHECK(cirs BETWEEN 0 AND 100),
        glassdoor_rating REAL DEFAULT 0.0 CHECK(glassdoor_rating BETWEEN 0 AND 5),
        last_signal_scan DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )
    """,

    # ---- Table 4: ghost_scores ----
    """
    CREATE TABLE IF NOT EXISTS ghost_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER NOT NULL REFERENCES clean_listings(id) ON DELETE CASCADE,
        listing_age_score REAL DEFAULT 0.0,
        applicant_overload_score REAL DEFAULT 0.0,
        repetitive_posting_score REAL DEFAULT 0.0,
        no_hr_signal_score REAL DEFAULT 0.0,
        ats_mismatch_score REAL DEFAULT 0.0,
        total_score REAL DEFAULT 0.0,
        is_ghost BOOLEAN DEFAULT 0,
        scored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(listing_id)
    )
    """,

    # ---- Table 5: intent_signals ----
    """
    CREATE TABLE IF NOT EXISTS intent_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        signal_type TEXT DEFAULT 'news' CHECK(signal_type IN ('news','hr_post','funding','expansion','earnings','layoff','acquisition')),
        signal_text TEXT DEFAULT '',
        signal_score REAL DEFAULT 0.0 CHECK(signal_score BETWEEN 0 AND 100),
        source_url TEXT DEFAULT '',
        detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        decay_applied BOOLEAN DEFAULT 0,
        expires_at DATETIME
    )
    """,

    # ---- Table 6: outcomes ----
    """
    CREATE TABLE IF NOT EXISTS outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER REFERENCES clean_listings(id) ON DELETE SET NULL,
        company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        status TEXT DEFAULT 'applied' CHECK(status IN ('applied','shortlisted','interview','rejected','offer','ppo','withdrawn')),
        applied_at DATETIME,
        outcome_at DATETIME,
        notes TEXT DEFAULT '',
        ppo_score_at_apply REAL DEFAULT 0.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # ---- Table 7: dark_channel_listings ----
    """
    CREATE TABLE IF NOT EXISTS dark_channel_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_name TEXT DEFAULT '',
        channel_type TEXT DEFAULT 'telegram' CHECK(channel_type IN ('telegram','twitter','discord','reddit')),
        message_text TEXT DEFAULT '',
        extracted_company TEXT DEFAULT '',
        extracted_role TEXT DEFAULT '',
        extracted_url TEXT DEFAULT '',
        is_job BOOLEAN DEFAULT 0,
        confidence REAL DEFAULT 0.0,
        detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        message_hash TEXT DEFAULT '',
        UNIQUE(message_hash)
    )
    """,

    # ---- Table 8: alumni_contacts ----
    """
    CREATE TABLE IF NOT EXISTS alumni_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        name TEXT DEFAULT '',
        linkedin_url TEXT DEFAULT '',
        college TEXT DEFAULT '',
        batch_year TEXT DEFAULT '',
        current_role TEXT DEFAULT '',
        connection_degree INTEGER DEFAULT 3 CHECK(connection_degree BETWEEN 1 AND 3),
        outreach_draft TEXT DEFAULT '',
        outreach_status TEXT DEFAULT 'pending' CHECK(outreach_status IN ('pending','sent','replied','connected','declined')),
        discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(linkedin_url)
    )
    """,

    # ---- Table 9: application_packages ----
    """
    CREATE TABLE IF NOT EXISTS application_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER NOT NULL REFERENCES clean_listings(id) ON DELETE CASCADE,
        cover_letter TEXT DEFAULT '',
        resume_tweaks TEXT DEFAULT '',
        keyword_gaps TEXT DEFAULT '[]',
        keyword_match_pct REAL DEFAULT 0.0,
        warm_intro_draft TEXT DEFAULT '',
        generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(listing_id)
    )
    """,

    # ---- Table 10: api_quotas ----
    """
    CREATE TABLE IF NOT EXISTS api_quotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL DEFAULT '',
        date DATE NOT NULL,
        hour INTEGER DEFAULT 0 CHECK(hour BETWEEN 0 AND 23),
        requests_made INTEGER DEFAULT 0,
        tokens_used INTEGER DEFAULT 0,
        errors INTEGER DEFAULT 0,
        rate_limited BOOLEAN DEFAULT 0,
        UNIQUE(provider, date, hour)
    )
    """,

    # ---- Table 11: proxy_health ----
    """
    CREATE TABLE IF NOT EXISTS proxy_health (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proxy_url TEXT NOT NULL DEFAULT '',
        proxy_type TEXT DEFAULT '' CHECK(proxy_type IN ('','webshare','tor','free','cloudflare')),
        is_alive BOOLEAN DEFAULT 1,
        avg_latency_ms REAL DEFAULT 0.0,
        success_rate REAL DEFAULT 1.0 CHECK(success_rate BETWEEN 0 AND 1),
        last_check DATETIME,
        last_used DATETIME,
        fail_count INTEGER DEFAULT 0,
        blocked_by TEXT DEFAULT '',
        UNIQUE(proxy_url)
    )
    """,

    # ---- Table 12: agent_heartbeats ----
    """
    CREATE TABLE IF NOT EXISTS agent_heartbeats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL UNIQUE,
        agent_name TEXT DEFAULT '',
        status TEXT DEFAULT 'idle' CHECK(status IN ('idle','running','error','disabled','completed')),
        last_run DATETIME,
        last_success DATETIME,
        items_processed INTEGER DEFAULT 0,
        errors_last_run INTEGER DEFAULT 0,
        total_runs INTEGER DEFAULT 0,
        total_items INTEGER DEFAULT 0,
        avg_duration_sec REAL DEFAULT 0.0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # ---- Schema migrations tracking table ----
    """
    CREATE TABLE IF NOT EXISTS __schema_migrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL,
        description TEXT DEFAULT '',
        applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(version)
    )
    """,

    # ---- User settings table (bonus) ----
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT DEFAULT '',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

# ============================================================
# INDEX DEFINITIONS
# ============================================================

CREATE_INDEXES_SQL: List[str] = [
    # raw_listings indexes
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_source ON raw_listings(source)",
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_company ON raw_listings(company)",
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_scraped_at ON raw_listings(scraped_at)",
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_batch ON raw_listings(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_category ON raw_listings(category)",
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_hash ON raw_listings(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_raw_listings_url ON raw_listings(url)",

    # clean_listings indexes
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_ppo_score ON clean_listings(ppo_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_ghost ON clean_listings(is_ghost)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_blue_ocean ON clean_listings(is_blue_ocean)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_company_id ON clean_listings(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_status ON clean_listings(status)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_source ON clean_listings(source)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_created ON clean_listings(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_company_name ON clean_listings(company)",
    "CREATE INDEX IF NOT EXISTS idx_clean_listings_url ON clean_listings(url)",

    # companies indexes
    "CREATE INDEX IF NOT EXISTS idx_companies_tier ON companies(tier)",
    "CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(normalized_name)",
    "CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector)",
    "CREATE INDEX IF NOT EXISTS idx_companies_ats ON companies(ats_platform)",
    "CREATE INDEX IF NOT EXISTS idx_companies_cirs ON companies(cirs DESC)",

    # intent_signals indexes
    "CREATE INDEX IF NOT EXISTS idx_intent_signals_company ON intent_signals(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_intent_signals_score ON intent_signals(signal_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intent_signals_type ON intent_signals(signal_type)",
    "CREATE INDEX IF NOT EXISTS idx_intent_signals_detected ON intent_signals(detected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_intent_signals_expires ON intent_signals(expires_at)",

    # outcomes indexes
    "CREATE INDEX IF NOT EXISTS idx_outcomes_listing ON outcomes(listing_id)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_company ON outcomes(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_status ON outcomes(status)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_applied ON outcomes(applied_at DESC)",

    # dark_channel_listings indexes
    "CREATE INDEX IF NOT EXISTS idx_dark_channel_detected ON dark_channel_listings(detected_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_dark_channel_type ON dark_channel_listings(channel_type)",
    "CREATE INDEX IF NOT EXISTS idx_dark_channel_is_job ON dark_channel_listings(is_job)",
    "CREATE INDEX IF NOT EXISTS idx_dark_channel_hash ON dark_channel_listings(message_hash)",

    # alumni_contacts indexes
    "CREATE INDEX IF NOT EXISTS idx_alumni_company ON alumni_contacts(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_alumni_college ON alumni_contacts(college)",
    "CREATE INDEX IF NOT EXISTS idx_alumni_status ON alumni_contacts(outreach_status)",

    # application_packages indexes
    "CREATE INDEX IF NOT EXISTS idx_packages_listing ON application_packages(listing_id)",

    # api_quotas indexes
    "CREATE INDEX IF NOT EXISTS idx_api_quotas_provider_date ON api_quotas(provider, date)",
    "CREATE INDEX IF NOT EXISTS idx_api_quotas_date ON api_quotas(date)",

    # proxy_health indexes
    "CREATE INDEX IF NOT EXISTS idx_proxy_health_alive ON proxy_health(is_alive)",
    "CREATE INDEX IF NOT EXISTS idx_proxy_health_type ON proxy_health(proxy_type)",

    # agent_heartbeats indexes
    "CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_agent ON agent_heartbeats(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_status ON agent_heartbeats(status)",
]


# ============================================================
# INITIAL AGENT HEARTBEAT SEEDS
# ============================================================

AGENT_SEEDS: List[Dict[str, str]] = [
    {"agent_id": "A-01", "agent_name": "Intent Signal Scanner"},
    {"agent_id": "A-02", "agent_name": "Dark Channel Listener"},
    {"agent_id": "A-03", "agent_name": "Primary Scraper"},
    {"agent_id": "A-04", "agent_name": "ATS Crawler"},
    {"agent_id": "A-05", "agent_name": "Ghost Detector"},
    {"agent_id": "A-06", "agent_name": "Dedup Engine"},
    {"agent_id": "A-07", "agent_name": "Intelligence Enricher"},
    {"agent_id": "A-08", "agent_name": "PPO Optimizer"},
    {"agent_id": "A-09", "agent_name": "Network Mapper"},
    {"agent_id": "A-10", "agent_name": "ATS Simulator"},
    {"agent_id": "A-11", "agent_name": "Outcome Learner"},
    {"agent_id": "A-12", "agent_name": "Telegram Reporter"},
]


# ============================================================
# DATABASE MANAGER CLASS
# ============================================================

class DatabaseManager:
    """
    Thread-safe SQLite database manager for Operation First Mover.

    Provides:
    - Connection pooling via threading.local()
    - WAL journal mode for concurrent reads
    - Schema creation and migration
    - CRUD operations for all 12 tables
    - Batch operations for scraping pipelines
    - Aggregation queries for reports
    - Backup/restore for ephemeral disk
    - Auto-maintenance (VACUUM, ANALYZE)
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the database manager.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to config value or 'data/firstmover.db'.
        """
        if db_path is None:
            try:
                cfg = get_config()
                db_path = cfg.database.path
            except Exception:
                db_path = "data/firstmover.db"

        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()

        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._initialize_database()

    # ----------------------------------------------------------
    # CONNECTION MANAGEMENT
    # ----------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=10.0,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            # Performance pragmas
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8000")  # 8MB
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB
            self._local.connection = conn
        return self._local.connection

    @contextmanager
    def get_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database cursor with auto-commit."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Explicit transaction context manager for batch operations."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction error: {e}")
            raise
        finally:
            cursor.close()

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    # ----------------------------------------------------------
    # SCHEMA INITIALIZATION
    # ----------------------------------------------------------

    def _initialize_database(self):
        """Create all tables, indexes, and seed data."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Create all 12 tables + migration table + settings
            for sql in CREATE_TABLES_SQL:
                cursor.execute(sql)

            # Create all indexes
            for sql in CREATE_INDEXES_SQL:
                cursor.execute(sql)

            # Seed agent heartbeats
            for agent in AGENT_SEEDS:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO agent_heartbeats (agent_id, agent_name)
                    VALUES (?, ?)
                    """,
                    (agent['agent_id'], agent['agent_name'])
                )

            # Record schema version
            cursor.execute(
                """
                INSERT OR IGNORE INTO __schema_migrations (version, description)
                VALUES (?, ?)
                """,
                (SCHEMA_VERSION, f"Initial schema v{SCHEMA_VERSION}")
            )

            conn.commit()
            logger.info(f"Database initialized at {self.db_path} (schema v{SCHEMA_VERSION})")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to initialize database: {e}")
            raise

    def get_schema_version(self) -> int:
        """Get the current schema version."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT MAX(version) FROM __schema_migrations"
            )
            row = cur.fetchone()
            return row[0] if row and row[0] else 0

    # ----------------------------------------------------------
    # RAW LISTINGS CRUD
    # ----------------------------------------------------------

    def insert_raw_listing(self, listing: RawListing) -> Optional[int]:
        """Insert a single raw listing. Returns the row ID or None if duplicate."""
        with self.get_cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO raw_listings
                    (title, company, location, stipend, stipend_normalized,
                     duration, duration_months, applicants, is_ppo, is_wfh,
                     posted_days_ago, url, source, category, description_text,
                     batch_id, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.title, listing.company, listing.location,
                        listing.stipend, listing.stipend_normalized,
                        listing.duration, listing.duration_months,
                        listing.applicants, int(listing.is_ppo), int(listing.is_wfh),
                        listing.posted_days_ago, listing.url, listing.source,
                        listing.category, listing.description_text,
                        listing.batch_id, listing.content_hash()
                    )
                )
                return cur.lastrowid if cur.rowcount > 0 else None
            except sqlite3.IntegrityError:
                return None

    def insert_raw_listings_batch(self, listings: List[RawListing]) -> int:
        """Batch insert raw listings. Returns count of new insertions."""
        inserted = 0
        with self.transaction() as cur:
            for listing in listings:
                try:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO raw_listings
                        (title, company, location, stipend, stipend_normalized,
                         duration, duration_months, applicants, is_ppo, is_wfh,
                         posted_days_ago, url, source, category, description_text,
                         batch_id, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            listing.title, listing.company, listing.location,
                            listing.stipend, listing.stipend_normalized,
                            listing.duration, listing.duration_months,
                            listing.applicants, int(listing.is_ppo), int(listing.is_wfh),
                            listing.posted_days_ago, listing.url, listing.source,
                            listing.category, listing.description_text,
                            listing.batch_id, listing.content_hash()
                        )
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                except sqlite3.IntegrityError:
                    continue
        logger.info(f"Batch inserted {inserted}/{len(listings)} raw listings")
        return inserted

    def get_raw_listings_by_batch(self, batch_id: str) -> List[Dict]:
        """Get all raw listings from a specific batch."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM raw_listings WHERE batch_id = ? ORDER BY id",
                (batch_id,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_raw_listings_since(self, hours: int = 24) -> List[Dict]:
        """Get raw listings from the last N hours."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM raw_listings
                WHERE scraped_at >= datetime('now', ?)
                ORDER BY scraped_at DESC
                """,
                (f"-{hours} hours",)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_unprocessed_raw_listings(self, limit: int = 500) -> List[Dict]:
        """Get raw listings not yet in clean_listings."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT r.* FROM raw_listings r
                LEFT JOIN clean_listings c ON c.raw_id = r.id
                WHERE c.id IS NULL
                ORDER BY r.scraped_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def count_raw_listings(self, source: Optional[str] = None,
                           hours: Optional[int] = None) -> int:
        """Count raw listings with optional filters."""
        query = "SELECT COUNT(*) FROM raw_listings WHERE 1=1"
        params = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if hours:
            query += " AND scraped_at >= datetime('now', ?)"
            params.append(f"-{hours} hours")
        with self.get_cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()[0]

    def count_unprocessed_raw_listings(self) -> int:
        """Count raw listings that haven't been processed into clean listings yet."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM raw_listings r
                LEFT JOIN clean_listings c ON c.raw_id = r.id
                WHERE c.id IS NULL
                """
            )
            return cur.fetchone()[0]

    # ----------------------------------------------------------
    # CLEAN LISTINGS CRUD
    # ----------------------------------------------------------

    def insert_clean_listing(self, listing: CleanListing) -> Optional[int]:
        """Insert a clean listing. Returns row ID or None."""
        with self.get_cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO clean_listings
                    (raw_id, title, company, company_id, location,
                     stipend_monthly, duration_months, applicants,
                     is_ppo, is_wfh, ghost_score, is_ghost,
                     ppo_score, is_blue_ocean, competition_ratio,
                     source, url, description_text, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.raw_id, listing.title, listing.company,
                        listing.company_id, listing.location,
                        listing.stipend_monthly, listing.duration_months,
                        listing.applicants, int(listing.is_ppo), int(listing.is_wfh),
                        listing.ghost_score, int(listing.is_ghost),
                        listing.ppo_score, int(listing.is_blue_ocean),
                        listing.competition_ratio, listing.source,
                        listing.url, listing.description_text, listing.status
                    )
                )
                return cur.lastrowid if cur.rowcount > 0 else None
            except sqlite3.IntegrityError:
                return None

    def insert_clean_listings_batch(self, listings: List[CleanListing]) -> int:
        """Batch insert clean listings."""
        inserted = 0
        with self.transaction() as cur:
            for listing in listings:
                try:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO clean_listings
                        (raw_id, title, company, company_id, location,
                         stipend_monthly, duration_months, applicants,
                         is_ppo, is_wfh, ghost_score, is_ghost,
                         ppo_score, is_blue_ocean, competition_ratio,
                         source, url, description_text, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            listing.raw_id, listing.title, listing.company,
                            listing.company_id, listing.location,
                            listing.stipend_monthly, listing.duration_months,
                            listing.applicants, int(listing.is_ppo), int(listing.is_wfh),
                            listing.ghost_score, int(listing.is_ghost),
                            listing.ppo_score, int(listing.is_blue_ocean),
                            listing.competition_ratio, listing.source,
                            listing.url, listing.description_text, listing.status
                        )
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                except sqlite3.IntegrityError:
                    continue
        return inserted

    def update_clean_listing_scores(self, listing_id: int,
                                      ghost_score: float = None,
                                      ppo_score: float = None,
                                      is_blue_ocean: bool = None,
                                      is_ghost: bool = None,
                                      status: str = None):
        """Update scoring fields on a clean listing."""
        updates = []
        params = []
        if ghost_score is not None:
            updates.append("ghost_score = ?")
            params.append(ghost_score)
        if ppo_score is not None:
            updates.append("ppo_score = ?")
            params.append(ppo_score)
        if is_blue_ocean is not None:
            updates.append("is_blue_ocean = ?")
            params.append(int(is_blue_ocean))
        if is_ghost is not None:
            updates.append("is_ghost = ?")
            params.append(int(is_ghost))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if not updates:
            return
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(listing_id)

        with self.get_cursor() as cur:
            cur.execute(
                f"UPDATE clean_listings SET {', '.join(updates)} WHERE id = ?",
                params
            )

    def get_clean_listing_by_id(self, listing_id: int) -> Optional[Dict]:
        """Get a single clean listing by ID."""
        with self.get_cursor() as cur:
            cur.execute("SELECT * FROM clean_listings WHERE id = ?", (listing_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_top_listings(self, n: int = 25, exclude_ghost: bool = True,
                          status: str = "active") -> List[Dict]:
        """Get top N listings by PPO score."""
        with self.get_cursor() as cur:
            query = """
                SELECT cl.*, c.tier, c.sector, c.cirs
                FROM clean_listings cl
                LEFT JOIN companies c ON cl.company_id = c.id
                WHERE cl.status = ?
            """
            params = [status]
            if exclude_ghost:
                query += " AND cl.is_ghost = 0"
            query += " ORDER BY cl.ppo_score DESC LIMIT ?"
            params.append(n)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_blue_ocean_listings(self, limit: int = 20) -> List[Dict]:
        """Get Blue Ocean listings (high prestige, low competition)."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT cl.*, c.tier, c.sector, c.cirs, c.name as company_name
                FROM clean_listings cl
                LEFT JOIN companies c ON cl.company_id = c.id
                WHERE cl.is_blue_ocean = 1
                  AND cl.is_ghost = 0
                  AND cl.status = 'active'
                ORDER BY cl.ppo_score DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_listings_for_ghost_scoring(self, limit: int = 500) -> List[Dict]:
        """Get listings that need ghost scoring."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT cl.* FROM clean_listings cl
                LEFT JOIN ghost_scores gs ON gs.listing_id = cl.id
                WHERE gs.id IS NULL AND cl.status = 'active'
                ORDER BY cl.created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_listings_needing_ppo_score(self, limit: int = 500) -> List[Dict]:
        """Get active listings that haven't been PPO scored."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT cl.*, c.tier, c.cirs, c.sector
                FROM clean_listings cl
                LEFT JOIN companies c ON cl.company_id = c.id
                WHERE cl.status = 'active'
                  AND cl.is_ghost = 0
                  AND cl.ppo_score = 0.0
                ORDER BY cl.created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def search_listings(self, query: str, limit: int = 50) -> List[Dict]:
        """Full-text search across title, company, location, description."""
        pattern = f"%{query}%"
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT cl.*, c.tier, c.sector
                FROM clean_listings cl
                LEFT JOIN companies c ON cl.company_id = c.id
                WHERE cl.status = 'active'
                  AND cl.is_ghost = 0
                  AND (
                    cl.title LIKE ? OR
                    cl.company LIKE ? OR
                    cl.location LIKE ? OR
                    cl.description_text LIKE ?
                  )
                ORDER BY cl.ppo_score DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, pattern, limit)
            )
            return [dict(row) for row in cur.fetchall()]

    def count_clean_listings(self, status: Optional[str] = None,
                              is_ghost: Optional[bool] = None,
                              hours: Optional[int] = None) -> int:
        """Count clean listings with optional filters."""
        query = "SELECT COUNT(*) FROM clean_listings WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if is_ghost is not None:
            query += " AND is_ghost = ?"
            params.append(int(is_ghost))
        if hours:
            query += " AND created_at >= datetime('now', ?)"
            params.append(f"-{hours} hours")
        with self.get_cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()[0]

    def get_listings_by_company(self, company_name: str,
                                 limit: int = 20) -> List[Dict]:
        """Get listings for a specific company."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM clean_listings
                WHERE company LIKE ? AND status = 'active'
                ORDER BY ppo_score DESC LIMIT ?
                """,
                (f"%{company_name}%", limit)
            )
            return [dict(row) for row in cur.fetchall()]

    def check_url_exists(self, url: str) -> bool:
        """Check if a URL already exists in raw or clean listings."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM raw_listings WHERE url = ? UNION SELECT 1 FROM clean_listings WHERE url = ? LIMIT 1",
                (url, url)
            )
            return cur.fetchone() is not None

    # ----------------------------------------------------------
    # COMPANIES CRUD
    # ----------------------------------------------------------

    def insert_company(self, company: Company) -> Optional[int]:
        """Insert a company. Returns row ID or None if duplicate."""
        with self.get_cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO companies
                    (name, normalized_name, tier, sector, sub_sector,
                     size_band, hq_city, careers_url, ats_platform,
                     ats_board_id, cirs, glassdoor_rating)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        company.name, company.normalized_name or company.name.lower().strip(),
                        company.tier, company.sector, company.sub_sector,
                        company.size_band, company.hq_city, company.careers_url,
                        company.ats_platform, company.ats_board_id,
                        company.cirs, company.glassdoor_rating
                    )
                )
                return cur.lastrowid if cur.rowcount > 0 else None
            except sqlite3.IntegrityError:
                return None

    def insert_companies_batch(self, companies: List[Company]) -> int:
        """Batch insert companies."""
        inserted = 0
        with self.transaction() as cur:
            for co in companies:
                try:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO companies
                        (name, normalized_name, tier, sector, sub_sector,
                         size_band, hq_city, careers_url, ats_platform,
                         ats_board_id, cirs, glassdoor_rating)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            co.name, co.normalized_name or co.name.lower().strip(),
                            co.tier, co.sector, co.sub_sector,
                            co.size_band, co.hq_city, co.careers_url,
                            co.ats_platform, co.ats_board_id,
                            co.cirs, co.glassdoor_rating
                        )
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                except sqlite3.IntegrityError:
                    continue
        logger.info(f"Batch inserted {inserted}/{len(companies)} companies")
        return inserted

    def get_company_by_name(self, name: str) -> Optional[Dict]:
        """Find a company by exact or normalized name."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM companies
                WHERE name = ? OR normalized_name = ?
                LIMIT 1
                """,
                (name, name.lower().strip())
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_company_by_id(self, company_id: int) -> Optional[Dict]:
        """Get company by ID."""
        with self.get_cursor() as cur:
            cur.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_companies_by_tier(self, tier: int, limit: int = 100) -> List[Dict]:
        """Get companies of a specific tier."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM companies WHERE tier = ? ORDER BY cirs DESC LIMIT ?",
                (tier, limit)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_companies_with_ats(self, ats_platform: str = None) -> List[Dict]:
        """Get companies that have ATS configured."""
        with self.get_cursor() as cur:
            if ats_platform:
                cur.execute(
                    "SELECT * FROM companies WHERE ats_platform = ? AND ats_board_id != ''",
                    (ats_platform,)
                )
            else:
                cur.execute(
                    "SELECT * FROM companies WHERE ats_platform != '' AND ats_board_id != ''"
                )
            return [dict(row) for row in cur.fetchall()]

    def update_company_cirs(self, company_id: int, cirs: float):
        """Update a company's CIRS score."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                UPDATE companies
                SET cirs = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (max(0, min(100, cirs)), company_id)
            )

    def fuzzy_match_company(self, name: str) -> Optional[Dict]:
        """Fuzzy match a company name using LIKE patterns."""
        normalized = name.lower().strip()
        with self.get_cursor() as cur:
            # Try exact match first
            cur.execute(
                "SELECT * FROM companies WHERE normalized_name = ? LIMIT 1",
                (normalized,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            # Try LIKE match
            cur.execute(
                "SELECT * FROM companies WHERE normalized_name LIKE ? LIMIT 1",
                (f"%{normalized}%",)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def count_companies(self, tier: Optional[int] = None) -> int:
        """Count companies with optional tier filter."""
        if tier:
            with self.get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM companies WHERE tier = ?", (tier,))
                return cur.fetchone()[0]
        with self.get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM companies")
            return cur.fetchone()[0]

    def get_all_company_names(self) -> Set[str]:
        """Get all normalized company names for fast lookup."""
        with self.get_cursor() as cur:
            cur.execute("SELECT normalized_name FROM companies")
            return {row[0] for row in cur.fetchall()}

    # ----------------------------------------------------------
    # GHOST SCORES CRUD
    # ----------------------------------------------------------

    def insert_ghost_score(self, score: GhostScore) -> Optional[int]:
        """Insert or update a ghost score for a listing."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO ghost_scores
                (listing_id, listing_age_score, applicant_overload_score,
                 repetitive_posting_score, no_hr_signal_score,
                 ats_mismatch_score, total_score, is_ghost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score.listing_id, score.listing_age_score,
                    score.applicant_overload_score, score.repetitive_posting_score,
                    score.no_hr_signal_score, score.ats_mismatch_score,
                    score.total_score, int(score.is_ghost)
                )
            )
            return cur.lastrowid

    def insert_ghost_scores_batch(self, scores: List[GhostScore]) -> int:
        """Batch insert ghost scores."""
        inserted = 0
        with self.transaction() as cur:
            for score in scores:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO ghost_scores
                    (listing_id, listing_age_score, applicant_overload_score,
                     repetitive_posting_score, no_hr_signal_score,
                     ats_mismatch_score, total_score, is_ghost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        score.listing_id, score.listing_age_score,
                        score.applicant_overload_score, score.repetitive_posting_score,
                        score.no_hr_signal_score, score.ats_mismatch_score,
                        score.total_score, int(score.is_ghost)
                    )
                )
                inserted += 1
        return inserted

    def get_ghost_score(self, listing_id: int) -> Optional[Dict]:
        """Get ghost score for a listing."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM ghost_scores WHERE listing_id = ?",
                (listing_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    # ----------------------------------------------------------
    # INTENT SIGNALS CRUD
    # ----------------------------------------------------------

    def insert_intent_signal(self, signal: IntentSignal) -> Optional[int]:
        """Insert an intent signal."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO intent_signals
                (company_id, signal_type, signal_text, signal_score,
                 source_url, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.company_id, signal.signal_type,
                    signal.signal_text, signal.signal_score,
                    signal.source_url, signal.expires_at
                )
            )
            return cur.lastrowid

    def get_active_signals(self, min_score: float = 0,
                            days: int = 7) -> List[Dict]:
        """Get active intent signals from the last N days."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT s.*, c.name as company_name, c.tier
                FROM intent_signals s
                JOIN companies c ON s.company_id = c.id
                WHERE s.detected_at >= datetime('now', ?)
                  AND s.signal_score >= ?
                ORDER BY s.signal_score DESC
                """,
                (f"-{days} days", min_score)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_company_signals(self, company_id: int,
                             days: int = 30) -> List[Dict]:
        """Get intent signals for a specific company."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM intent_signals
                WHERE company_id = ?
                  AND detected_at >= datetime('now', ?)
                ORDER BY detected_at DESC
                """,
                (company_id, f"-{days} days")
            )
            return [dict(row) for row in cur.fetchall()]

    def get_latest_signal_score(self, company_id: int) -> float:
        """Get the latest signal score for a company."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT signal_score FROM intent_signals
                WHERE company_id = ?
                ORDER BY detected_at DESC LIMIT 1
                """,
                (company_id,)
            )
            row = cur.fetchone()
            return row[0] if row else 0.0

    def apply_signal_decay(self, decay_per_day: float = 10.0):
        """Apply signal decay to all signals (called daily)."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                UPDATE intent_signals
                SET signal_score = MAX(0, signal_score - ?),
                    decay_applied = 1
                WHERE detected_at < datetime('now', '-1 day')
                  AND signal_score > 0
                """,
                (decay_per_day,)
            )
            logger.info(f"Applied signal decay to {cur.rowcount} signals")

    # ----------------------------------------------------------
    # OUTCOMES CRUD
    # ----------------------------------------------------------

    def insert_outcome(self, outcome: Outcome) -> Optional[int]:
        """Record an application outcome."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO outcomes
                (listing_id, company_id, status, applied_at,
                 notes, ppo_score_at_apply)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                """,
                (
                    outcome.listing_id, outcome.company_id,
                    outcome.status, outcome.notes,
                    outcome.ppo_score_at_apply
                )
            )
            return cur.lastrowid

    def update_outcome(self, outcome_id: int, status: str,
                        notes: str = ""):
        """Update an outcome status."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                UPDATE outcomes
                SET status = ?, outcome_at = CURRENT_TIMESTAMP, notes = ?
                WHERE id = ?
                """,
                (status, notes, outcome_id)
            )

    def get_outcomes_for_learning(self, min_count: int = 20) -> List[Dict]:
        """Get outcomes with enough data for learning (A-11)."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT o.*, cl.title, cl.company, cl.stipend_monthly,
                       cl.duration_months, cl.applicants, cl.is_ppo,
                       cl.ppo_score, c.tier, c.sector, c.cirs
                FROM outcomes o
                JOIN clean_listings cl ON o.listing_id = cl.id
                LEFT JOIN companies c ON o.company_id = c.id
                WHERE o.status IN ('interview', 'rejected', 'offer', 'ppo')
                ORDER BY o.created_at DESC
                """
            )
            results = [dict(row) for row in cur.fetchall()]
            return results if len(results) >= min_count else []

    def get_outcome_stats(self) -> Dict[str, Any]:
        """Get outcome funnel statistics."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM outcomes
                GROUP BY status
                ORDER BY
                    CASE status
                        WHEN 'applied' THEN 1
                        WHEN 'shortlisted' THEN 2
                        WHEN 'interview' THEN 3
                        WHEN 'rejected' THEN 4
                        WHEN 'offer' THEN 5
                        WHEN 'ppo' THEN 6
                    END
                """
            )
            return {row['status']: row['count'] for row in cur.fetchall()}

    def get_company_callback_rate(self, company_id: int) -> float:
        """Calculate interview callback rate for a company."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status IN ('interview', 'offer', 'ppo') THEN 1 ELSE 0 END) as positive
                FROM outcomes
                WHERE company_id = ?
                """,
                (company_id,)
            )
            row = cur.fetchone()
            if row and row['total'] > 0:
                return row['positive'] / row['total']
            return 0.0

    # ----------------------------------------------------------
    # DARK CHANNEL LISTINGS CRUD
    # ----------------------------------------------------------

    def insert_dark_channel_listing(self, listing: DarkChannelListing) -> Optional[int]:
        """Insert a dark channel listing."""
        msg_hash = hashlib.md5(listing.message_text.encode()).hexdigest()
        with self.get_cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO dark_channel_listings
                    (channel_name, channel_type, message_text,
                     extracted_company, extracted_role, extracted_url,
                     is_job, confidence, message_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.channel_name, listing.channel_type,
                        listing.message_text, listing.extracted_company,
                        listing.extracted_role, listing.extracted_url,
                        int(listing.is_job), listing.confidence, msg_hash
                    )
                )
                return cur.lastrowid if cur.rowcount > 0 else None
            except sqlite3.IntegrityError:
                return None

    def get_recent_dark_listings(self, days: int = 3,
                                  limit: int = 30) -> List[Dict]:
        """Get recent dark channel job listings."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM dark_channel_listings
                WHERE is_job = 1
                  AND detected_at >= datetime('now', ?)
                ORDER BY detected_at DESC
                LIMIT ?
                """,
                (f"-{days} days", limit)
            )
            return [dict(row) for row in cur.fetchall()]

    # ----------------------------------------------------------
    # ALUMNI CONTACTS CRUD
    # ----------------------------------------------------------

    def insert_alumni_contact(self, contact: AlumniContact) -> Optional[int]:
        """Insert an alumni contact."""
        with self.get_cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO alumni_contacts
                    (company_id, name, linkedin_url, college, batch_year,
                     current_role, connection_degree, outreach_draft,
                     outreach_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        contact.company_id, contact.name, contact.linkedin_url,
                        contact.college, contact.batch_year, contact.current_role,
                        contact.connection_degree, contact.outreach_draft,
                        contact.outreach_status
                    )
                )
                return cur.lastrowid if cur.rowcount > 0 else None
            except sqlite3.IntegrityError:
                return None

    def get_alumni_for_company(self, company_id: int) -> List[Dict]:
        """Get all alumni contacts for a company."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM alumni_contacts
                WHERE company_id = ?
                ORDER BY connection_degree ASC
                """,
                (company_id,)
            )
            return [dict(row) for row in cur.fetchall()]

    # ----------------------------------------------------------
    # APPLICATION PACKAGES CRUD
    # ----------------------------------------------------------

    def insert_application_package(self, pkg: ApplicationPackage) -> Optional[int]:
        """Insert or update an application package."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO application_packages
                (listing_id, cover_letter, resume_tweaks,
                 keyword_gaps, keyword_match_pct, warm_intro_draft)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    pkg.listing_id, pkg.cover_letter, pkg.resume_tweaks,
                    pkg.keyword_gaps, pkg.keyword_match_pct,
                    pkg.warm_intro_draft
                )
            )
            return cur.lastrowid

    def get_application_package(self, listing_id: int) -> Optional[Dict]:
        """Get application package for a listing."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM application_packages WHERE listing_id = ?",
                (listing_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    # ----------------------------------------------------------
    # API QUOTAS CRUD
    # ----------------------------------------------------------

    def record_api_usage(self, provider: str, requests: int = 1,
                          tokens: int = 0, is_error: bool = False,
                          is_rate_limited: bool = False):
        """Record API usage for quota tracking."""
        now = datetime.now(IST)
        date_str = now.strftime("%Y-%m-%d")
        hour = now.hour

        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_quotas (provider, date, hour, requests_made, tokens_used, errors, rate_limited)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, date, hour)
                DO UPDATE SET
                    requests_made = requests_made + ?,
                    tokens_used = tokens_used + ?,
                    errors = errors + ?,
                    rate_limited = CASE WHEN ? THEN 1 ELSE rate_limited END
                """,
                (
                    provider, date_str, hour, requests, tokens,
                    int(is_error), int(is_rate_limited),
                    requests, tokens, int(is_error), int(is_rate_limited)
                )
            )

    def get_daily_usage(self, provider: str,
                         date_str: Optional[str] = None) -> Dict[str, int]:
        """Get daily API usage for a provider."""
        if date_str is None:
            date_str = datetime.now(IST).strftime("%Y-%m-%d")
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(requests_made), 0) as total_requests,
                    COALESCE(SUM(tokens_used), 0) as total_tokens,
                    COALESCE(SUM(errors), 0) as total_errors,
                    MAX(rate_limited) as was_rate_limited
                FROM api_quotas
                WHERE provider = ? AND date = ?
                """,
                (provider, date_str)
            )
            row = cur.fetchone()
            return dict(row) if row else {
                'total_requests': 0, 'total_tokens': 0,
                'total_errors': 0, 'was_rate_limited': 0
            }

    def get_all_daily_usage(self, date_str: Optional[str] = None) -> Dict[str, Dict]:
        """Get daily API usage for all providers."""
        if date_str is None:
            date_str = datetime.now(IST).strftime("%Y-%m-%d")
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT provider,
                    COALESCE(SUM(requests_made), 0) as total_requests,
                    COALESCE(SUM(tokens_used), 0) as total_tokens,
                    COALESCE(SUM(errors), 0) as total_errors
                FROM api_quotas
                WHERE date = ?
                GROUP BY provider
                """,
                (date_str,)
            )
            return {row['provider']: dict(row) for row in cur.fetchall()}

    # ----------------------------------------------------------
    # PROXY HEALTH CRUD
    # ----------------------------------------------------------

    def upsert_proxy(self, proxy: ProxyHealth):
        """Insert or update proxy health."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO proxy_health
                (proxy_url, proxy_type, is_alive, avg_latency_ms,
                 success_rate, last_check, fail_count, blocked_by)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(proxy_url)
                DO UPDATE SET
                    is_alive = ?, avg_latency_ms = ?,
                    success_rate = ?, last_check = CURRENT_TIMESTAMP,
                    fail_count = ?, blocked_by = ?
                """,
                (
                    proxy.proxy_url, proxy.proxy_type,
                    int(proxy.is_alive), proxy.avg_latency_ms,
                    proxy.success_rate, proxy.fail_count, proxy.blocked_by,
                    int(proxy.is_alive), proxy.avg_latency_ms,
                    proxy.success_rate, proxy.fail_count, proxy.blocked_by
                )
            )

    def get_healthy_proxies(self, proxy_type: Optional[str] = None,
                             limit: int = 10) -> List[Dict]:
        """Get healthy proxies sorted by latency."""
        query = """
            SELECT * FROM proxy_health
            WHERE is_alive = 1
        """
        params = []
        if proxy_type:
            query += " AND proxy_type = ?"
            params.append(proxy_type)
        query += " ORDER BY avg_latency_ms ASC LIMIT ?"
        params.append(limit)
        with self.get_cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def mark_proxy_used(self, proxy_url: str):
        """Mark a proxy as recently used."""
        with self.get_cursor() as cur:
            cur.execute(
                "UPDATE proxy_health SET last_used = CURRENT_TIMESTAMP WHERE proxy_url = ?",
                (proxy_url,)
            )

    def mark_proxy_failed(self, proxy_url: str, blocked_by: str = ""):
        """Increment failure count for a proxy."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                UPDATE proxy_health
                SET fail_count = fail_count + 1,
                    is_alive = CASE WHEN fail_count >= 3 THEN 0 ELSE is_alive END,
                    blocked_by = CASE WHEN ? != '' THEN
                        CASE WHEN blocked_by = '' THEN ? ELSE blocked_by || ',' || ? END
                    ELSE blocked_by END
                WHERE proxy_url = ?
                """,
                (blocked_by, blocked_by, blocked_by, proxy_url)
            )

    # ----------------------------------------------------------
    # AGENT HEARTBEATS CRUD
    # ----------------------------------------------------------

    def update_agent_heartbeat(self, agent_id: str, status: str,
                                 items_processed: int = 0,
                                 errors: int = 0,
                                 duration_sec: float = 0.0):
        """Update an agent's heartbeat status."""
        with self.get_cursor() as cur:
            if status == AgentStatus.RUNNING.value:
                cur.execute(
                    """
                    UPDATE agent_heartbeats
                    SET status = ?, last_run = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE agent_id = ?
                    """,
                    (status, agent_id)
                )
            elif status in (AgentStatus.COMPLETED.value, AgentStatus.IDLE.value):
                cur.execute(
                    """
                    UPDATE agent_heartbeats
                    SET status = 'idle',
                        last_success = CASE WHEN ? = 0 THEN CURRENT_TIMESTAMP ELSE last_success END,
                        items_processed = ?,
                        errors_last_run = ?,
                        total_runs = total_runs + 1,
                        total_items = total_items + ?,
                        avg_duration_sec = CASE
                            WHEN total_runs = 0 THEN ?
                            ELSE (avg_duration_sec * total_runs + ?) / (total_runs + 1)
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE agent_id = ?
                    """,
                    (errors, items_processed, errors, items_processed,
                     duration_sec, duration_sec, agent_id)
                )
            else:
                cur.execute(
                    """
                    UPDATE agent_heartbeats
                    SET status = ?, errors_last_run = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE agent_id = ?
                    """,
                    (status, errors, agent_id)
                )

    def get_all_heartbeats(self) -> List[Dict]:
        """Get all agent heartbeats."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM agent_heartbeats ORDER BY agent_id"
            )
            return [dict(row) for row in cur.fetchall()]

    def get_agent_heartbeat(self, agent_id: str) -> Optional[Dict]:
        """Get a single agent's heartbeat."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM agent_heartbeats WHERE agent_id = ?",
                (agent_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    # ----------------------------------------------------------
    # USER SETTINGS CRUD
    # ----------------------------------------------------------

    def set_setting(self, key: str, value: str):
        """Set a user setting."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = ?, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value, value)
            )

    def get_setting(self, key: str, default: str = "") -> str:
        """Get a user setting."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT value FROM user_settings WHERE key = ?",
                (key,)
            )
            row = cur.fetchone()
            return row[0] if row else default

    # ----------------------------------------------------------
    # AGGREGATION & REPORTING QUERIES
    # ----------------------------------------------------------

    def get_morning_brief_data(self) -> Dict[str, Any]:
        """Get all data needed for the morning Telegram brief."""
        with self.get_cursor() as cur:
            # New listings in last 24h
            cur.execute(
                """SELECT COUNT(*) FROM clean_listings
                   WHERE created_at >= datetime('now', '-24 hours')"""
            )
            total_new = cur.fetchone()[0]

            # After ghost filter
            cur.execute(
                """SELECT COUNT(*) FROM clean_listings
                   WHERE created_at >= datetime('now', '-24 hours')
                     AND is_ghost = 0"""
            )
            after_ghost = cur.fetchone()[0]

            # Blue ocean count
            cur.execute(
                """SELECT COUNT(*) FROM clean_listings
                   WHERE created_at >= datetime('now', '-24 hours')
                     AND is_blue_ocean = 1 AND is_ghost = 0"""
            )
            blue_ocean_count = cur.fetchone()[0]

            # Intent signals this week
            cur.execute(
                """SELECT COUNT(*) FROM intent_signals
                   WHERE detected_at >= datetime('now', '-7 days')
                     AND signal_score >= 50"""
            )
            signals_count = cur.fetchone()[0]

            # Top 10 by PPO
            top_10 = self.get_top_listings(n=10)

            # Dark channel finds
            dark_finds = self.get_recent_dark_listings(days=1, limit=5)

            # Urgent deadlines (listings created >5 days ago with high PPO — may be closing soon)
            cur.execute(
                """SELECT cl.*, r.posted_days_ago FROM clean_listings cl
                   LEFT JOIN raw_listings r ON cl.raw_id = r.id
                   WHERE cl.status = 'active' AND cl.is_ghost = 0
                     AND (
                       (r.posted_days_ago IS NOT NULL AND (7 - COALESCE(r.posted_days_ago, 0)) <= 2)
                       OR (cl.created_at <= datetime('now', '-5 days'))
                     )
                   ORDER BY cl.ppo_score DESC LIMIT 5"""
            )
            urgent = [dict(row) for row in cur.fetchall()]

            return {
                'total_new': total_new,
                'after_ghost_filter': after_ghost,
                'blue_ocean_count': blue_ocean_count,
                'signals_fired': signals_count,
                'top_10': top_10,
                'dark_finds': dark_finds,
                'urgent_deadlines': urgent,
            }

    def get_weekly_stats(self) -> Dict[str, Any]:
        """Get weekly statistics for A-11 and /stats command."""
        with self.get_cursor() as cur:
            # Outcome funnel
            funnel = self.get_outcome_stats()

            # Listings by source
            cur.execute(
                """SELECT source, COUNT(*) as count
                   FROM clean_listings
                   WHERE created_at >= datetime('now', '-7 days')
                   GROUP BY source ORDER BY count DESC"""
            )
            by_source = {row['source']: row['count'] for row in cur.fetchall()}

            # Top sectors
            cur.execute(
                """SELECT c.sector, COUNT(*) as count,
                          AVG(cl.ppo_score) as avg_ppo
                   FROM clean_listings cl
                   JOIN companies c ON cl.company_id = c.id
                   WHERE cl.created_at >= datetime('now', '-7 days')
                     AND cl.is_ghost = 0
                   GROUP BY c.sector
                   ORDER BY avg_ppo DESC
                   LIMIT 10"""
            )
            top_sectors = [dict(row) for row in cur.fetchall()]

            # Agent performance
            agents = self.get_all_heartbeats()

            return {
                'funnel': funnel,
                'by_source': by_source,
                'top_sectors': top_sectors,
                'agents': agents,
                'period': '7 days',
            }

    # ----------------------------------------------------------
    # MAINTENANCE & BACKUP
    # ----------------------------------------------------------

    def vacuum(self):
        """Run VACUUM to reclaim space."""
        conn = self._get_connection()
        conn.execute("VACUUM")
        logger.info("Database VACUUM completed")

    def analyze(self):
        """Run ANALYZE to update query planner statistics."""
        conn = self._get_connection()
        conn.execute("ANALYZE")
        logger.info("Database ANALYZE completed")

    def checkpoint(self):
        """Force WAL checkpoint."""
        conn = self._get_connection()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        logger.info("WAL checkpoint completed")

    def get_db_size(self) -> int:
        """Get database file size in bytes."""
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0

    def get_table_counts(self) -> Dict[str, int]:
        """Get row counts for all tables."""
        tables = [
            'raw_listings', 'clean_listings', 'companies',
            'ghost_scores', 'intent_signals', 'outcomes',
            'dark_channel_listings', 'alumni_contacts',
            'application_packages', 'api_quotas',
            'proxy_health', 'agent_heartbeats'
        ]
        counts = {}
        with self.get_cursor() as cur:
            for table in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = cur.fetchone()[0]
                except Exception:
                    counts[table] = -1
        return counts

    def backup(self, backup_path: Optional[str] = None) -> str:
        """Create a backup of the database."""
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = Path(self.db_path).parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup_path = str(backup_dir / f"firstmover_backup_{timestamp}.db")

        # Use SQLite online backup API
        conn = self._get_connection()
        backup_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(backup_conn)
            logger.info(f"Database backed up to {backup_path}")
        finally:
            backup_conn.close()

        # Compress
        compressed_path = backup_path + ".gz"
        with open(backup_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(backup_path)
        logger.info(f"Backup compressed to {compressed_path}")
        return compressed_path

    def restore(self, backup_path: str):
        """Restore database from a backup."""
        # Close current connection
        self.close()

        # Decompress if needed
        if backup_path.endswith('.gz'):
            decompressed = backup_path[:-3]
            with gzip.open(backup_path, 'rb') as f_in:
                with open(decompressed, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_path = decompressed

        # Replace current database
        shutil.copy2(backup_path, self.db_path)
        logger.info(f"Database restored from {backup_path}")

    def cleanup_old_data(self, days: int = 30):
        """Remove data older than N days to keep DB small."""
        with self.get_cursor() as cur:
            # Old raw listings
            cur.execute(
                "DELETE FROM raw_listings WHERE scraped_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            raw_deleted = cur.rowcount

            # Expired intent signals
            cur.execute(
                "DELETE FROM intent_signals WHERE expires_at < datetime('now')"
            )
            signals_deleted = cur.rowcount

            # Old API quota records
            cur.execute(
                "DELETE FROM api_quotas WHERE date < date('now', ?)",
                (f"-{days} days",)
            )
            quota_deleted = cur.rowcount

            logger.info(
                f"Cleanup: removed {raw_deleted} raw listings, "
                f"{signals_deleted} expired signals, "
                f"{quota_deleted} old quota records"
            )

    def seed_agent_heartbeats(self):
        """Seed agent heartbeats (called from main.py startup)."""
        with self.get_cursor() as cur:
            for agent in AGENT_SEEDS:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO agent_heartbeats (agent_id, agent_name)
                    VALUES (?, ?)
                    """,
                    (agent['agent_id'], agent['agent_name'])
                )
        logger.info("Agent heartbeats seeded (A-01 to A-12)")

    # ----------------------------------------------------------
    # MISSING METHODS REQUIRED BY AGENTS
    # ----------------------------------------------------------

    def get_all_companies_basic(self) -> List[Dict]:
        """Get all companies with basic fields (id, name, tier, sector).
        Used by A-01 Intent Scanner for company matching."""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT id, name, normalized_name, tier, sector, hq_city, "
                "ats_platform, ats_board_id, cirs FROM companies ORDER BY tier, name"
            )
            return [dict(row) for row in cur.fetchall()]

    def get_all_listing_urls(self) -> List[Dict]:
        """Get all listing URLs from both raw and clean tables.
        Used by A-06 Dedup Engine for URL-based dedup (L1, L6)."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT id, url FROM clean_listings WHERE url IS NOT NULL AND url != ''
                UNION ALL
                SELECT id, url FROM raw_listings WHERE url IS NOT NULL AND url != ''
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def get_all_clean_listing_basics(self) -> List[Dict]:
        """Get basic fields from all clean listings for dedup fingerprinting.
        Used by A-06 Dedup Engine (L2, L3)."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT id, title, company, location, url, stipend_monthly,
                       duration_months, source, description_text
                FROM clean_listings
                WHERE status = 'active'
                ORDER BY created_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def get_recent_clean_listings(self, days: int = 14,
                                    limit: int = 1000) -> List[Dict]:
        """Get recent clean listings within N days.
        Used by A-06 Dedup Engine (L4 semantic, L5 metadata),
        and A-07 Intelligence Enricher."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT cl.*, c.tier, c.sector, c.cirs
                FROM clean_listings cl
                LEFT JOIN companies c ON cl.company_id = c.id
                WHERE cl.created_at >= datetime('now', ?)
                  AND cl.status = 'active'
                ORDER BY cl.created_at DESC
                LIMIT ?
                """,
                (f"-{days} days", limit)
            )
            return [dict(row) for row in cur.fetchall()]

    def cleanup_expired_signals(self) -> int:
        """Remove expired or zero-score intent signals.
        Used by A-01 Intent Scanner."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                DELETE FROM intent_signals
                WHERE signal_score <= 0
                   OR (expires_at IS NOT NULL AND expires_at < datetime('now'))
                """
            )
            count = cur.rowcount
            logger.info(f"Cleaned up {count} expired signals")
            return count

    def get_listings_needing_enrichment(self, hours: int = 48,
                                          limit: int = 200) -> List[Dict]:
        """Get clean listings that need enrichment (no competition_ratio set).
        Used by A-07 Intelligence Enricher."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT cl.*, c.tier, c.sector, c.cirs, c.name as company_name
                FROM clean_listings cl
                LEFT JOIN companies c ON cl.company_id = c.id
                WHERE cl.status = 'active'
                  AND cl.is_ghost = 0
                  AND cl.competition_ratio = 0.0
                  AND cl.created_at >= datetime('now', ?)
                ORDER BY cl.created_at DESC
                LIMIT ?
                """,
                (f"-{hours} hours", limit)
            )
            return [dict(row) for row in cur.fetchall()]

    def update_clean_listing_enrichment(self, listing_id: int,
                                          competition_ratio: float = None,
                                          is_blue_ocean: bool = None,
                                          sector_momentum: float = None):
        """Update enrichment fields on a clean listing.
        Used by A-07 Intelligence Enricher."""
        updates = []
        params = []
        if competition_ratio is not None:
            updates.append("competition_ratio = ?")
            params.append(competition_ratio)
        if is_blue_ocean is not None:
            updates.append("is_blue_ocean = ?")
            params.append(int(is_blue_ocean))
        # sector_momentum is not a column; store in description or ignore
        if not updates:
            return
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(listing_id)
        with self.get_cursor() as cur:
            cur.execute(
                f"UPDATE clean_listings SET {', '.join(updates)} WHERE id = ?",
                params
            )

    def count_outcomes_today(self) -> int:
        """Count outcomes recorded today.
        Used by A-12 Telegram Reporter evening summary."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM outcomes
                WHERE date(created_at) = date('now')
                """
            )
            return cur.fetchone()[0]

    def count_dark_listings_today(self) -> int:
        """Count dark channel job listings found today.
        Used by A-12 Telegram Reporter evening summary."""
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM dark_channel_listings
                WHERE is_job = 1
                  AND date(detected_at) = date('now')
                """
            )
            return cur.fetchone()[0]

    def get_hourly_usage(self, provider: str,
                          date_str: Optional[str] = None,
                          hour: Optional[int] = None) -> Dict[str, int]:
        """Get hourly API usage for a provider."""
        if date_str is None:
            date_str = datetime.now(IST).strftime("%Y-%m-%d")
        if hour is None:
            hour = datetime.now(IST).hour
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(requests_made, 0) as requests,
                    COALESCE(tokens_used, 0) as tokens,
                    COALESCE(errors, 0) as errors
                FROM api_quotas
                WHERE provider = ? AND date = ? AND hour = ?
                """,
                (provider, date_str, hour)
            )
            row = cur.fetchone()
            return dict(row) if row else {'requests': 0, 'tokens': 0, 'errors': 0}

    def get_health_report(self) -> Dict[str, Any]:
        """Generate a comprehensive database health report."""
        return {
            'db_path': self.db_path,
            'db_size_mb': round(self.get_db_size() / (1024 * 1024), 2),
            'schema_version': self.get_schema_version(),
            'table_counts': self.get_table_counts(),
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_db_instance: Optional[DatabaseManager] = None
_db_lock = threading.Lock()


def get_db(db_path: Optional[str] = None) -> DatabaseManager:
    """Get the singleton DatabaseManager instance."""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = DatabaseManager(db_path)
    return _db_instance


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    """Test database initialization and basic operations."""
    print("=" * 60)
    print("OPERATION FIRST MOVER v5 — Database Test")
    print("=" * 60)

    db = DatabaseManager("data/test_firstmover.db")

    # Test health report
    health = db.get_health_report()
    print(f"\nDatabase: {health['db_path']}")
    print(f"Size: {health['db_size_mb']} MB")
    print(f"Schema: v{health['schema_version']}")
    print(f"\nTable counts:")
    for table, count in health['table_counts'].items():
        print(f"  {table}: {count}")

    # Test company insert
    test_company = Company(
        name="Test Company",
        tier=3,
        sector="Technology",
        hq_city="Mumbai"
    )
    cid = db.insert_company(test_company)
    print(f"\nInserted company: id={cid}")

    # Test raw listing insert
    test_listing = RawListing(
        title="Marketing Intern",
        company="Test Company",
        location="Mumbai",
        stipend="₹15,000/month",
        stipend_normalized=15000.0,
        url="https://example.com/job/1",
        source="internshala",
        category="marketing"
    )
    lid = db.insert_raw_listing(test_listing)
    print(f"Inserted raw listing: id={lid}")

    # Test agent heartbeat
    hb = db.get_all_heartbeats()
    print(f"\nAgent heartbeats: {len(hb)}")
    for h in hb:
        print(f"  {h['agent_id']}: {h['agent_name']} ({h['status']})")

    print("\n✅ All database tests passed!")
    print("=" * 60)

    # Cleanup test DB
    db.close()
    os.remove("data/test_firstmover.db")
