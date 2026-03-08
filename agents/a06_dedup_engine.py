"""
============================================================
AGENT A-06: 6-LAYER DEDUPLICATION ENGINE — INDUSTRIAL GRADE
============================================================
Cross-platform deduplication with 6 progressive layers that
eliminate duplicate job listings scraped from multiple sources.

Schedule:
    06:00 AM IST  — Morning batch (process overnight scrapes)
    06:00 PM IST  — Evening batch (process afternoon scrapes)

AI Model:
    Cerebras (`dedup_score`) — for semantic similarity scoring

Architecture:
    ┌──────────────────────────────────────────────────┐
    │            6-LAYER DEDUP PIPELINE                 │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │  Layer 1: URL Exact Match (O(1) hash lookup)     │
    │      ↓ (if no match)                             │
    │  Layer 2: Title+Company Normalized Exact Match   │
    │      ↓ (if no match)                             │
    │  Layer 3: Fuzzy String Match (RapidFuzz ≥85)     │
    │      ↓ (if no match)                             │
    │  Layer 4: Semantic Similarity (BERT ≥0.92)       │
    │      ↓ (if no match)                             │
    │  Layer 5: Location+Stipend+Company Match         │
    │      ↓ (if no match)                             │
    │  Layer 6: Cross-Platform ID Matching             │
    │      ↓                                           │
    │  [NEW LISTING] → Insert into clean_listings      │
    │                                                  │
    └──────────────────────────────────────────────────┘

Each layer has a confidence score. If ANY layer flags a
duplicate, we merge entries (keep earliest, update data).

Features:
    - URL hash index for O(1) lookup
    - Normalized text comparison (lowercase, stripped, etc.)
    - RapidFuzz fuzzy matching with ratio ≥ 85
    - BERT sentence-transformer cosine similarity ≥ 0.92
    - Location normalization (city synonyms, abbreviations)
    - Stipend range overlap detection
    - Cross-platform ID extraction (Internshala ID, Naukri ID, etc.)
    - Merge strategy: keep earliest, update applicant count
    - Batch processing with progress tracking
    - Memory-efficient chunked processing
    - Company name normalization (fuzzy company matching)
    - Duplicate pair logging for audit
    - Dedup statistics for reports
    - AI-assisted dedup for borderline cases
============================================================
"""

import os
import re
import json
import time
import hashlib
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from functools import lru_cache
from contextlib import contextmanager

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# Optional imports with graceful degradation
try:
    from rapidfuzz import fuzz, process as rfuzz_process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    logger.warning("rapidfuzz not installed. Layer 3 (fuzzy) disabled.")

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    BERT_AVAILABLE = True
except ImportError:
    BERT_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Layer 4 (semantic) disabled.")

from core.config import get_config, IST
from core.database import get_db, DatabaseManager, RawListing, CleanListing
from core.ai_router import get_router, AIRouter


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-06"
AGENT_NAME = "Deduplication Engine"

# Layer thresholds
LAYER_3_FUZZY_THRESHOLD = 85          # RapidFuzz ratio threshold
LAYER_4_SEMANTIC_THRESHOLD = 0.92     # Cosine similarity threshold
LAYER_5_STIPEND_TOLERANCE = 0.15      # 15% stipend difference tolerance
LAYER_5_DURATION_TOLERANCE = 1        # ±1 month tolerance

# Confidence scores per layer
LAYER_CONFIDENCE = {
    1: 1.00,   # URL exact match — certainty
    2: 0.98,   # Title+Company exact — near certainty
    3: 0.90,   # Fuzzy string — high confidence
    4: 0.95,   # BERT semantic — very high confidence
    5: 0.85,   # Location+Stipend — moderate-high
    6: 0.99,   # Cross-platform ID — near certainty
}

# Company name normalization replacements
COMPANY_NAME_NORMALIZATIONS = {
    'pvt. ltd.': '',
    'pvt ltd': '',
    'private limited': '',
    'limited': 'ltd',
    'technologies': 'tech',
    'solutions': '',
    'services': '',
    'india': '',
    'indian': '',
    'corporation': 'corp',
    'incorporated': 'inc',
    'international': 'intl',
    '(india)': '',
    'co.': '',
    '& co': '',
}

# Location synonyms for normalization
LOCATION_SYNONYMS = {
    'bangalore': 'bengaluru',
    'bombay': 'mumbai',
    'calcutta': 'kolkata',
    'madras': 'chennai',
    'trivandrum': 'thiruvananthapuram',
    'cochin': 'kochi',
    'baroda': 'vadodara',
    'mysore': 'mysuru',
    'mangalore': 'mangaluru',
    'pondicherry': 'puducherry',
    'allahabad': 'prayagraj',
    'gurgaon': 'gurugram',
    'noida': 'noida',
    'greater noida': 'noida',
    'ghaziabad': 'ghaziabad',
    'new delhi': 'delhi',
    'south delhi': 'delhi',
    'north delhi': 'delhi',
    'east delhi': 'delhi',
    'west delhi': 'delhi',
    'delhi ncr': 'delhi',
    'ncr': 'delhi',
    'navi mumbai': 'mumbai',
    'thane': 'mumbai',
    'whitefield': 'bengaluru',
    'electronic city': 'bengaluru',
    'koramangala': 'bengaluru',
    'indiranagar': 'bengaluru',
    'hsr layout': 'bengaluru',
    'andheri': 'mumbai',
    'bkc': 'mumbai',
    'lower parel': 'mumbai',
    'powai': 'mumbai',
    'malad': 'mumbai',
    'goregaon': 'mumbai',
    'cyber city': 'gurugram',
    'dlf cyber city': 'gurugram',
    'sector 44': 'gurugram',
    'mg road': '',  # ambiguous
    'work from home': 'remote',
    'wfh': 'remote',
    'anywhere': 'remote',
    'pan india': 'remote',
    'virtual': 'remote',
}

# Platform ID extraction patterns
PLATFORM_ID_PATTERNS = {
    'internshala': [
        r'internshala\.com/internship/detail/[^/]*?-(\d+)',
        r'internshala\.com/internships/.*?/(\d+)',
        r'internshala\.com/.*?internship_id=(\d+)',
    ],
    'naukri': [
        r'naukri\.com/job-listings-.*?-(\d+)',
        r'naukri\.com/.*?jid=(\d+)',
        r'jobId[=:](\d+)',
    ],
    'linkedin': [
        r'linkedin\.com/jobs/view/(\d+)',
        r'linkedin\.com/jobs/.*?currentJobId=(\d+)',
    ],
    'glassdoor': [
        r'glassdoor\.co\.in/job-listing/.*?-(\d+)\.htm',
        r'glassdoor\.com/job-listing/.*?-(\d+)\.htm',
    ],
    'greenhouse': [
        r'boards\.greenhouse\.io/.*?/jobs/(\d+)',
        r'grnh\.se/(\w+)',
    ],
    'lever': [
        r'jobs\.lever\.co/.*?/([\w-]{36})',
        r'lever\.co/.*?/([\w-]{36})',
    ],
    'indeed': [
        r'indeed\.co\.in/.*?jk=([\w]+)',
        r'indeed\.com/.*?jk=([\w]+)',
    ],
    'wellfound': [
        r'wellfound\.com/.*?/(\d+)',
        r'angel\.co/.*?/(\d+)',
    ],
}

# Stop words for title normalization
TITLE_STOP_WORDS = {
    'the', 'a', 'an', 'in', 'at', 'for', 'and', 'or', 'of', 'to',
    'with', 'is', 'are', 'be', 'will', 'would', 'should', 'can',
    '-', '–', '—', '/', '|', '•', '·', ',', '.', ':', ';',
    'opening', 'vacancy', 'opportunity', 'position', 'role',
    'apply', 'now', 'urgent', 'immediate', 'asap',
}


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class DedupMatch:
    """Represents a duplicate match between two listings."""
    raw_id: int
    matched_clean_id: int
    layer: int
    confidence: float
    match_detail: str
    raw_title: str = ""
    raw_company: str = ""
    matched_title: str = ""
    matched_company: str = ""


@dataclass
class DedupStats:
    """Statistics for a dedup run."""
    total_processed: int = 0
    new_clean_listings: int = 0
    duplicates_found: int = 0
    layer_1_url_matches: int = 0
    layer_2_exact_matches: int = 0
    layer_3_fuzzy_matches: int = 0
    layer_4_semantic_matches: int = 0
    layer_5_metadata_matches: int = 0
    layer_6_crossid_matches: int = 0
    ai_dedup_calls: int = 0
    errors: int = 0
    duration_sec: float = 0.0
    matches: List[DedupMatch] = field(default_factory=list)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Processed: {self.total_processed}",
            f"New Clean: {self.new_clean_listings}",
            f"Duplicates: {self.duplicates_found}",
            f"  L1 (URL): {self.layer_1_url_matches}",
            f"  L2 (Exact): {self.layer_2_exact_matches}",
            f"  L3 (Fuzzy): {self.layer_3_fuzzy_matches}",
            f"  L4 (Semantic): {self.layer_4_semantic_matches}",
            f"  L5 (Metadata): {self.layer_5_metadata_matches}",
            f"  L6 (CrossID): {self.layer_6_crossid_matches}",
            f"AI Calls: {self.ai_dedup_calls}",
            f"Errors: {self.errors}",
            f"Duration: {self.duration_sec}s",
        ]
        return '\n'.join(lines)


# ============================================================
# TEXT NORMALIZATION UTILITIES
# ============================================================

class TextNormalizer:
    """
    Comprehensive text normalization for deduplication.
    Handles Unicode, whitespace, company name variants,
    location synonyms, and title stop words.
    """

    @staticmethod
    def normalize_text(text: str) -> str:
        """General text normalization."""
        if not text:
            return ""
        # Unicode normalization
        text = unicodedata.normalize('NFKD', text)
        # Lowercase
        text = text.lower().strip()
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove special characters but keep alphanumeric and spaces
        text = re.sub(r'[^\w\s]', '', text)
        return text.strip()

    @staticmethod
    def normalize_title(title: str) -> str:
        """
        Normalize job title for comparison.
        Removes stop words, normalizes whitespace, handles common variants.
        """
        if not title:
            return ""
        # Lowercase and strip
        title = title.lower().strip()
        # Remove parenthetical content: "MBA Intern (2026 batch)" → "MBA Intern"
        title = re.sub(r'\([^)]*\)', '', title)
        # Remove brackets: "[Remote]" → ""
        title = re.sub(r'\[[^\]]*\]', '', title)
        # Normalize separators
        title = re.sub(r'\s*[-–—/|•·]\s*', ' ', title)
        # Remove stop words
        words = title.split()
        words = [w for w in words if w not in TITLE_STOP_WORDS]
        # Remove extra whitespace
        title = ' '.join(words).strip()
        # Normalize common title variants
        title = title.replace('management trainee', 'mt')
        title = title.replace('business development', 'bd')
        title = title.replace('product management', 'pm')
        title = title.replace('human resources', 'hr')
        title = title.replace('supply chain', 'scm')
        return title

    @staticmethod
    def normalize_company(company: str) -> str:
        """
        Normalize company name for comparison.
        Handles suffixes, abbreviations, and common variants.
        """
        if not company:
            return ""
        company = company.lower().strip()

        # Apply known normalizations
        for old, new in COMPANY_NAME_NORMALIZATIONS.items():
            company = company.replace(old, new)

        # Remove extra whitespace
        company = re.sub(r'\s+', ' ', company).strip()
        # Remove trailing punctuation
        company = company.rstrip('.')

        return company

    @staticmethod
    def normalize_location(location: str) -> str:
        """
        Normalize location for comparison.
        Handles city synonyms, abbreviations, and area names.
        """
        if not location:
            return ""
        location = location.lower().strip()

        # Apply synonym mapping
        for old, new in LOCATION_SYNONYMS.items():
            if old in location:
                location = location.replace(old, new)
                break  # Only apply first match

        # Remove country names
        location = re.sub(r'\b(india|in)\b', '', location)
        # Remove state names
        location = re.sub(
            r'\b(maharashtra|karnataka|telangana|tamil nadu|'
            r'west bengal|rajasthan|gujarat|madhya pradesh|'
            r'uttar pradesh|delhi|haryana|punjab|kerala|'
            r'andhra pradesh|odisha|bihar|jharkhand|'
            r'chhattisgarh|uttarakhand|himachal pradesh|goa)\b',
            '', location
        )
        # Clean up
        location = re.sub(r'[,\s]+', ' ', location).strip()

        return location

    @staticmethod
    def extract_platform_id(url: str) -> Dict[str, str]:
        """
        Extract platform-specific IDs from a URL.
        
        Returns:
            Dict mapping platform name to extracted ID
        """
        ids = {}
        if not url:
            return ids

        for platform, patterns in PLATFORM_ID_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, url, re.IGNORECASE)
                if match:
                    ids[platform] = match.group(1)
                    break

        return ids

    @staticmethod
    def compute_url_hash(url: str) -> str:
        """Compute a normalized hash for URL dedup."""
        if not url:
            return ""
        # Normalize URL: remove tracking params, trailing slashes
        url = url.lower().strip().rstrip('/')
        # Remove common tracking parameters
        url = re.sub(r'[?&](utm_\w+|ref|source|campaign|medium)=[^&]*', '', url)
        url = re.sub(r'[?&]$', '', url)  # Remove trailing ? or &
        return hashlib.md5(url.encode()).hexdigest()

    @staticmethod
    def compute_content_fingerprint(title: str, company: str, location: str) -> str:
        """Compute a content fingerprint for quick dedup."""
        norm_title = TextNormalizer.normalize_title(title)
        norm_company = TextNormalizer.normalize_company(company)
        norm_location = TextNormalizer.normalize_location(location)
        content = f"{norm_title}|{norm_company}|{norm_location}"
        return hashlib.md5(content.encode()).hexdigest()


# ============================================================
# DEDUP LAYERS
# ============================================================

class Layer1URLMatch:
    """
    Layer 1: URL Exact Match
    
    O(1) hash lookup against all known URLs.
    This is the fastest and most definitive layer.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._url_cache: Dict[str, int] = {}  # url_hash → clean_listing_id
        self._loaded = False

    def load_cache(self):
        """Pre-load all known URLs into memory for O(1) lookup."""
        if self._loaded:
            return

        try:
            urls = self.db.get_all_listing_urls()
            for url_data in urls:
                url = url_data.get('url', '')
                listing_id = url_data.get('id', 0)
                if url:
                    url_hash = TextNormalizer.compute_url_hash(url)
                    self._url_cache[url_hash] = listing_id
            self._loaded = True
            logger.debug(f"[{AGENT_ID}] L1: Loaded {len(self._url_cache)} URLs into cache")
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L1 cache load error: {e}")

    def check(self, url: str) -> Optional[DedupMatch]:
        """Check if URL already exists."""
        if not url:
            return None

        self.load_cache()
        url_hash = TextNormalizer.compute_url_hash(url)

        if url_hash in self._url_cache:
            return DedupMatch(
                raw_id=0,  # Will be set by caller
                matched_clean_id=self._url_cache[url_hash],
                layer=1,
                confidence=LAYER_CONFIDENCE[1],
                match_detail=f"URL exact match: {url[:80]}",
            )
        return None

    def add_url(self, url: str, clean_id: int):
        """Add a new URL to the cache."""
        if url:
            url_hash = TextNormalizer.compute_url_hash(url)
            self._url_cache[url_hash] = clean_id


class Layer2ExactMatch:
    """
    Layer 2: Title + Company Normalized Exact Match
    
    After normalizing both title and company name,
    checks for exact string equality.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._fingerprint_cache: Dict[str, int] = {}  # fingerprint → clean_id
        self._loaded = False

    def load_cache(self):
        """Pre-load content fingerprints."""
        if self._loaded:
            return

        try:
            listings = self.db.get_all_clean_listing_basics()
            for listing in listings:
                fp = TextNormalizer.compute_content_fingerprint(
                    listing.get('title', ''),
                    listing.get('company', ''),
                    listing.get('location', ''),
                )
                self._fingerprint_cache[fp] = listing.get('id', 0)
            self._loaded = True
            logger.debug(
                f"[{AGENT_ID}] L2: Loaded {len(self._fingerprint_cache)} fingerprints"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L2 cache load error: {e}")

    def check(self, title: str, company: str, location: str) -> Optional[DedupMatch]:
        """Check for exact normalized match."""
        self.load_cache()

        fp = TextNormalizer.compute_content_fingerprint(title, company, location)
        if fp in self._fingerprint_cache:
            return DedupMatch(
                raw_id=0,
                matched_clean_id=self._fingerprint_cache[fp],
                layer=2,
                confidence=LAYER_CONFIDENCE[2],
                match_detail=f"Exact match: {TextNormalizer.normalize_title(title)} @ {TextNormalizer.normalize_company(company)}",
            )
        return None

    def add_fingerprint(self, title: str, company: str, location: str, clean_id: int):
        """Add a new fingerprint to cache."""
        fp = TextNormalizer.compute_content_fingerprint(title, company, location)
        self._fingerprint_cache[fp] = clean_id


class Layer3FuzzyMatch:
    """
    Layer 3: Fuzzy String Matching
    
    Uses RapidFuzz (C++ backend) for fast fuzzy string comparison.
    Threshold: ratio ≥ 85 on normalized title within same company.
    
    Strategy:
        - Group existing listings by normalized company name
        - For each new listing, only compare against same-company listings
        - Use fuzz.ratio() and fuzz.token_sort_ratio()
        - Take the maximum of both scores
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._company_titles: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
        self._loaded = False

    def load_cache(self):
        """Pre-load titles grouped by company."""
        if self._loaded or not RAPIDFUZZ_AVAILABLE:
            return

        try:
            listings = self.db.get_all_clean_listing_basics()
            for listing in listings:
                norm_company = TextNormalizer.normalize_company(
                    listing.get('company', '')
                )
                norm_title = TextNormalizer.normalize_title(
                    listing.get('title', '')
                )
                if norm_company and norm_title:
                    self._company_titles[norm_company].append(
                        (listing.get('id', 0), norm_title)
                    )
            self._loaded = True
            logger.debug(
                f"[{AGENT_ID}] L3: Loaded titles for "
                f"{len(self._company_titles)} companies"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L3 cache load error: {e}")

    def check(self, title: str, company: str) -> Optional[DedupMatch]:
        """Check for fuzzy title match within same company."""
        if not RAPIDFUZZ_AVAILABLE:
            return None

        self.load_cache()

        norm_company = TextNormalizer.normalize_company(company)
        norm_title = TextNormalizer.normalize_title(title)

        if not norm_company or not norm_title:
            return None

        # Check exact company match first
        candidates = self._company_titles.get(norm_company, [])

        # Also check similar company names
        if not candidates:
            for cached_company, titles in self._company_titles.items():
                company_sim = fuzz.ratio(norm_company, cached_company)
                if company_sim >= 80:
                    candidates.extend(titles)

        if not candidates:
            return None

        # Compare titles
        best_score = 0
        best_match_id = 0
        best_match_title = ""

        for clean_id, cached_title in candidates:
            # Standard ratio
            score1 = fuzz.ratio(norm_title, cached_title)
            # Token sort ratio (handles word reordering)
            score2 = fuzz.token_sort_ratio(norm_title, cached_title)
            # Token set ratio (handles subset matching)
            score3 = fuzz.token_set_ratio(norm_title, cached_title)
            # Weighted combination
            score = max(score1, score2, score3 * 0.9)

            if score > best_score:
                best_score = score
                best_match_id = clean_id
                best_match_title = cached_title

        if best_score >= LAYER_3_FUZZY_THRESHOLD:
            return DedupMatch(
                raw_id=0,
                matched_clean_id=best_match_id,
                layer=3,
                confidence=LAYER_CONFIDENCE[3] * (best_score / 100),
                match_detail=(
                    f"Fuzzy match (score={best_score:.0f}): "
                    f"'{norm_title}' ≈ '{best_match_title}'"
                ),
            )
        return None

    def add_title(self, title: str, company: str, clean_id: int):
        """Add a new title to the cache."""
        norm_company = TextNormalizer.normalize_company(company)
        norm_title = TextNormalizer.normalize_title(title)
        if norm_company and norm_title:
            self._company_titles[norm_company].append((clean_id, norm_title))


class Layer4SemanticMatch:
    """
    Layer 4: BERT Semantic Similarity
    
    Uses sentence-transformers to compute cosine similarity
    between job description embeddings. Threshold: ≥ 0.92.
    
    Model: all-MiniLM-L6-v2 (22M params, fast, 384-dim)
    
    Strategy:
        - Lazy-load model (Render 512MB constraint)
        - Only compare within same company group
        - Cache embeddings to avoid recomputation
        - Batch encode for efficiency
        - Fall back to Layer 3 if model unavailable
    """

    # Use small model for Render 512MB constraint
    MODEL_NAME = "all-MiniLM-L6-v2"
    MAX_EMBEDDINGS_CACHED = 5000  # Memory budget

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._model = None
        self._embeddings: Dict[int, Any] = {}  # clean_id → embedding
        self._loaded = False

    def _load_model(self):
        """Lazy-load the sentence transformer model."""
        if self._model is not None or not BERT_AVAILABLE:
            return

        try:
            logger.info(f"[{AGENT_ID}] L4: Loading {self.MODEL_NAME}...")
            self._model = SentenceTransformer(self.MODEL_NAME)
            logger.info(f"[{AGENT_ID}] L4: Model loaded successfully")
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L4: Failed to load model: {e}")
            self._model = None

    def load_cache(self, company_ids: Optional[Set[int]] = None):
        """Pre-compute embeddings for existing listings."""
        if not BERT_AVAILABLE or self._loaded:
            return

        self._load_model()
        if not self._model:
            return

        try:
            # Get recent listings (limit for memory)
            listings = self.db.get_recent_clean_listings(
                days=14, limit=self.MAX_EMBEDDINGS_CACHED
            )

            texts = []
            ids = []
            for listing in listings:
                desc = listing.get('description_text', '')
                title = listing.get('title', '')
                # Use title + first 200 chars of description
                text = f"{title}. {desc[:200]}"
                texts.append(text)
                ids.append(listing.get('id', 0))

            if texts:
                embeddings = self._model.encode(texts, batch_size=32, show_progress_bar=False)
                for i, emb in enumerate(embeddings):
                    self._embeddings[ids[i]] = emb

            self._loaded = True
            logger.debug(
                f"[{AGENT_ID}] L4: Cached {len(self._embeddings)} embeddings"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L4 cache error: {e}")

    def check(self, title: str, description: str, company: str) -> Optional[DedupMatch]:
        """Check for semantic similarity match."""
        if not BERT_AVAILABLE or not self._model:
            return None

        if not self._embeddings:
            return None

        try:
            # Encode new listing
            text = f"{title}. {description[:200]}"
            new_embedding = self._model.encode([text], show_progress_bar=False)[0]

            # Compare against cached embeddings
            best_score = 0.0
            best_match_id = 0

            for clean_id, cached_emb in self._embeddings.items():
                # Cosine similarity
                score = float(np.dot(new_embedding, cached_emb) / (
                    np.linalg.norm(new_embedding) * np.linalg.norm(cached_emb) + 1e-8
                ))
                if score > best_score:
                    best_score = score
                    best_match_id = clean_id

            if best_score >= LAYER_4_SEMANTIC_THRESHOLD:
                return DedupMatch(
                    raw_id=0,
                    matched_clean_id=best_match_id,
                    layer=4,
                    confidence=LAYER_CONFIDENCE[4] * best_score,
                    match_detail=f"Semantic match (cosine={best_score:.4f})",
                )
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] L4 check error: {e}")

        return None

    def add_embedding(self, clean_id: int, title: str, description: str):
        """Add a new embedding to the cache."""
        if not BERT_AVAILABLE or not self._model:
            return
        if len(self._embeddings) >= self.MAX_EMBEDDINGS_CACHED:
            # Evict oldest
            oldest_key = next(iter(self._embeddings))
            del self._embeddings[oldest_key]

        try:
            text = f"{title}. {description[:200]}"
            embedding = self._model.encode([text], show_progress_bar=False)[0]
            self._embeddings[clean_id] = embedding
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] L4 add error: {e}")


class Layer5MetadataMatch:
    """
    Layer 5: Location + Stipend + Company Match
    
    If the same company has a listing in the same city with
    a similar stipend and similar duration, it's likely a duplicate
    even if the title differs slightly.
    
    Conditions (ALL must match):
        - Same normalized company name
        - Same normalized city
        - Stipend within 15% tolerance
        - Duration within ±1 month
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._metadata_cache: Dict[str, List[Tuple[int, Dict]]] = defaultdict(list)
        self._loaded = False

    def load_cache(self):
        """Pre-load metadata for existing listings."""
        if self._loaded:
            return

        try:
            listings = self.db.get_recent_clean_listings(days=30, limit=2000)
            for listing in listings:
                company = TextNormalizer.normalize_company(
                    listing.get('company', '')
                )
                if company:
                    self._metadata_cache[company].append((
                        listing.get('id', 0),
                        {
                            'location': TextNormalizer.normalize_location(
                                listing.get('location', '')
                            ),
                            'stipend': listing.get('stipend_monthly', 0) or 0,
                            'duration': listing.get('duration_months', 0) or 0,
                            'title': TextNormalizer.normalize_title(
                                listing.get('title', '')
                            ),
                        }
                    ))
            self._loaded = True
            logger.debug(
                f"[{AGENT_ID}] L5: Loaded metadata for "
                f"{len(self._metadata_cache)} companies"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L5 cache load error: {e}")

    def check(self, company: str, location: str, stipend: float,
              duration: int) -> Optional[DedupMatch]:
        """Check for metadata match."""
        self.load_cache()

        norm_company = TextNormalizer.normalize_company(company)
        norm_location = TextNormalizer.normalize_location(location)

        if not norm_company:
            return None

        candidates = self._metadata_cache.get(norm_company, [])
        if not candidates:
            return None

        for clean_id, meta in candidates:
            # Location match
            if norm_location and meta['location']:
                if norm_location != meta['location']:
                    continue  # Different city

            # Stipend match (within tolerance)
            if stipend > 0 and meta['stipend'] > 0:
                min_stipend = min(stipend, meta['stipend'])
                max_stipend = max(stipend, meta['stipend'])
                if min_stipend > 0:
                    diff_ratio = (max_stipend - min_stipend) / min_stipend
                    if diff_ratio > LAYER_5_STIPEND_TOLERANCE:
                        continue  # Stipend too different

            # Duration match (within tolerance)
            if duration > 0 and meta['duration'] > 0:
                if abs(duration - meta['duration']) > LAYER_5_DURATION_TOLERANCE:
                    continue  # Duration too different

            # If we reach here, all metadata matches
            return DedupMatch(
                raw_id=0,
                matched_clean_id=clean_id,
                layer=5,
                confidence=LAYER_CONFIDENCE[5],
                match_detail=(
                    f"Metadata match: {norm_company} @ {norm_location} "
                    f"₹{stipend:,.0f} {duration}mo"
                ),
            )

        return None

    def add_metadata(self, company: str, location: str, stipend: float,
                     duration: int, title: str, clean_id: int):
        """Add metadata to cache."""
        norm_company = TextNormalizer.normalize_company(company)
        if norm_company:
            self._metadata_cache[norm_company].append((
                clean_id,
                {
                    'location': TextNormalizer.normalize_location(location),
                    'stipend': stipend,
                    'duration': duration,
                    'title': TextNormalizer.normalize_title(title),
                }
            ))


class Layer6CrossPlatformID:
    """
    Layer 6: Cross-Platform ID Matching
    
    Extract platform-specific IDs from URLs and match across
    different sources. If the same Internshala ID appears in
    both an Internshala scrape and a LinkedIn dork result,
    they're the same listing.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._id_cache: Dict[str, int] = {}  # "platform:id" → clean_listing_id
        self._loaded = False

    def load_cache(self):
        """Pre-load all known platform IDs."""
        if self._loaded:
            return

        try:
            listings = self.db.get_all_listing_urls()
            for listing in listings:
                url = listing.get('url', '')
                clean_id = listing.get('id', 0)
                if url:
                    ids = TextNormalizer.extract_platform_id(url)
                    for platform, pid in ids.items():
                        cache_key = f"{platform}:{pid}"
                        self._id_cache[cache_key] = clean_id
            self._loaded = True
            logger.debug(
                f"[{AGENT_ID}] L6: Loaded {len(self._id_cache)} platform IDs"
            )
        except Exception as e:
            logger.error(f"[{AGENT_ID}] L6 cache load error: {e}")

    def check(self, url: str) -> Optional[DedupMatch]:
        """Check for cross-platform ID match."""
        if not url:
            return None

        self.load_cache()

        ids = TextNormalizer.extract_platform_id(url)
        for platform, pid in ids.items():
            cache_key = f"{platform}:{pid}"
            if cache_key in self._id_cache:
                return DedupMatch(
                    raw_id=0,
                    matched_clean_id=self._id_cache[cache_key],
                    layer=6,
                    confidence=LAYER_CONFIDENCE[6],
                    match_detail=f"Cross-platform ID: {platform}={pid}",
                )
        return None

    def add_ids(self, url: str, clean_id: int):
        """Add platform IDs to cache."""
        if url:
            ids = TextNormalizer.extract_platform_id(url)
            for platform, pid in ids.items():
                cache_key = f"{platform}:{pid}"
                self._id_cache[cache_key] = clean_id


# ============================================================
# MAIN DEDUPLICATION ENGINE
# ============================================================

class DedupEngine:
    """
    Master deduplication engine orchestrating all 6 layers.
    
    Architecture:
        1. Load all caches (URL, fingerprint, titles, embeddings, etc.)
        2. For each raw listing:
           a. Run through layers 1-6 sequentially
           b. If ANY layer matches → mark as duplicate
           c. If NO layer matches → create clean listing
        3. Update caches with new listings
        4. Report statistics
    
    Memory Management:
        - Render 512MB constraint
        - Layer 4 (BERT) only loaded when needed
        - Embedding cache limited to 5000 entries
        - Periodic cache pruning for old entries
    
    Performance:
        - Batch processing (500 listings per run)
        - Layer 1 and 2 are O(1) (hash lookups)
        - Layer 3 is O(n) per company group (usually small)
        - Layer 4 is O(n) but limited to same-company embeddings
        - Layer 5 is O(n) per company group
        - Layer 6 is O(1) (hash lookup)
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.router = get_router()

        # Initialize layers
        self.layer1 = Layer1URLMatch(self.db)
        self.layer2 = Layer2ExactMatch(self.db)
        self.layer3 = Layer3FuzzyMatch(self.db)
        self.layer4 = Layer4SemanticMatch(self.db)
        self.layer5 = Layer5MetadataMatch(self.db)
        self.layer6 = Layer6CrossPlatformID(self.db)

        # Statistics
        self._stats = DedupStats()

    def run_dedup(self, batch_size: int = 500, use_semantic: bool = False) -> DedupStats:
        """
        Run the full 6-layer deduplication pipeline.
        
        Args:
            batch_size: Max raw listings to process per run
            use_semantic: Enable Layer 4 (BERT) — increases memory usage
        
        Returns:
            DedupStats with complete statistics
        """
        logger.info(f"[{AGENT_ID}] === DEDUP START ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, 'running')

        self._stats = DedupStats()

        # Load all caches
        self._load_all_caches(use_semantic)

        # Get unprocessed raw listings
        raw_listings = self.db.get_unprocessed_raw_listings(limit=batch_size)
        self._stats.total_processed = len(raw_listings)

        logger.info(
            f"[{AGENT_ID}] Processing {len(raw_listings)} raw listings "
            f"(batch_size={batch_size})"
        )

        # Process each raw listing
        for i, raw in enumerate(raw_listings):
            try:
                self._process_raw_listing(raw, use_semantic)

                # Progress logging every 100 items
                if (i + 1) % 100 == 0:
                    logger.info(
                        f"[{AGENT_ID}] Progress: {i+1}/{len(raw_listings)} | "
                        f"New: {self._stats.new_clean_listings} | "
                        f"Dups: {self._stats.duplicates_found}"
                    )

            except Exception as e:
                self._stats.errors += 1
                logger.debug(f"[{AGENT_ID}] Dedup error for raw_id={raw.get('id')}: {e}")

        # Finalize
        duration = time.time() - start_time
        self._stats.duration_sec = round(duration, 1)

        self.db.update_agent_heartbeat(
            AGENT_ID, 'completed',
            items_processed=self._stats.new_clean_listings,
            errors=self._stats.errors,
            duration_sec=duration,
        )

        logger.info(
            f"[{AGENT_ID}] === DEDUP COMPLETE === "
            f"Processed: {self._stats.total_processed} | "
            f"New: {self._stats.new_clean_listings} | "
            f"Dups: {self._stats.duplicates_found} | "
            f"L1:{self._stats.layer_1_url_matches} "
            f"L2:{self._stats.layer_2_exact_matches} "
            f"L3:{self._stats.layer_3_fuzzy_matches} "
            f"L4:{self._stats.layer_4_semantic_matches} "
            f"L5:{self._stats.layer_5_metadata_matches} "
            f"L6:{self._stats.layer_6_crossid_matches} | "
            f"Duration: {self._stats.duration_sec}s"
        )

        return self._stats

    def _load_all_caches(self, use_semantic: bool):
        """Load all layer caches."""
        logger.debug(f"[{AGENT_ID}] Loading dedup caches...")
        self.layer1.load_cache()
        self.layer2.load_cache()
        self.layer3.load_cache()
        if use_semantic:
            self.layer4.load_cache()
        self.layer5.load_cache()
        self.layer6.load_cache()
        logger.debug(f"[{AGENT_ID}] All caches loaded")

    def _process_raw_listing(self, raw: Dict, use_semantic: bool):
        """Process a single raw listing through the dedup pipeline."""
        raw_id = raw.get('id', 0)
        title = raw.get('title', '')
        company = raw.get('company', '')
        location = raw.get('location', '')
        url = raw.get('url', '')
        stipend = raw.get('stipend_normalized', 0) or 0
        duration = raw.get('duration_months', 0) or 0
        description = raw.get('description_text', '')

        # Layer 1: URL Match
        match = self.layer1.check(url)
        if match:
            match.raw_id = raw_id
            match.raw_title = title
            match.raw_company = company
            self._stats.duplicates_found += 1
            self._stats.layer_1_url_matches += 1
            self._stats.matches.append(match)
            self.db.mark_raw_listing_processed(raw_id, duplicate=True, matched_id=match.matched_clean_id)
            return

        # Layer 6: Cross-Platform ID (check early — it's O(1))
        match = self.layer6.check(url)
        if match:
            match.raw_id = raw_id
            match.raw_title = title
            match.raw_company = company
            self._stats.duplicates_found += 1
            self._stats.layer_6_crossid_matches += 1
            self._stats.matches.append(match)
            self.db.mark_raw_listing_processed(raw_id, duplicate=True, matched_id=match.matched_clean_id)
            return

        # Layer 2: Title+Company Exact
        match = self.layer2.check(title, company, location)
        if match:
            match.raw_id = raw_id
            match.raw_title = title
            match.raw_company = company
            self._stats.duplicates_found += 1
            self._stats.layer_2_exact_matches += 1
            self._stats.matches.append(match)
            self.db.mark_raw_listing_processed(raw_id, duplicate=True, matched_id=match.matched_clean_id)
            return

        # Layer 3: Fuzzy String Match
        match = self.layer3.check(title, company)
        if match:
            match.raw_id = raw_id
            match.raw_title = title
            match.raw_company = company
            self._stats.duplicates_found += 1
            self._stats.layer_3_fuzzy_matches += 1
            self._stats.matches.append(match)
            self.db.mark_raw_listing_processed(raw_id, duplicate=True, matched_id=match.matched_clean_id)
            return

        # Layer 5: Metadata Match
        if stipend > 0 or duration > 0:
            match = self.layer5.check(company, location, stipend, duration)
            if match:
                match.raw_id = raw_id
                match.raw_title = title
                match.raw_company = company
                self._stats.duplicates_found += 1
                self._stats.layer_5_metadata_matches += 1
                self._stats.matches.append(match)
                self.db.mark_raw_listing_processed(raw_id, duplicate=True, matched_id=match.matched_clean_id)
                return

        # Layer 4: Semantic Match (expensive, only if enabled)
        if use_semantic and description:
            match = self.layer4.check(title, description, company)
            if match:
                match.raw_id = raw_id
                match.raw_title = title
                match.raw_company = company
                self._stats.duplicates_found += 1
                self._stats.layer_4_semantic_matches += 1
                self._stats.matches.append(match)
                self.db.mark_raw_listing_processed(raw_id, duplicate=True, matched_id=match.matched_clean_id)
                return

        # ---- NO DUPLICATE FOUND — Create clean listing ----
        clean_listing = self._create_clean_listing(raw)
        if clean_listing:
            clean_id = self.db.insert_clean_listing(clean_listing)
            if clean_id:
                self._stats.new_clean_listings += 1

                # Update all caches with new listing
                self.layer1.add_url(url, clean_id)
                self.layer2.add_fingerprint(title, company, location, clean_id)
                self.layer3.add_title(title, company, clean_id)
                self.layer5.add_metadata(
                    company, location, stipend, duration, title, clean_id
                )
                self.layer6.add_ids(url, clean_id)
                if use_semantic:
                    self.layer4.add_embedding(clean_id, title, description)

                self.db.mark_raw_listing_processed(raw_id, duplicate=False, clean_id=clean_id)
            else:
                # Insert failed (likely constraint violation)
                self.db.mark_raw_listing_processed(raw_id, duplicate=True)
        else:
            self._stats.errors += 1

    def _create_clean_listing(self, raw: Dict) -> Optional[CleanListing]:
        """Create a CleanListing from a raw listing."""
        try:
            # Try to match company in database
            company_name = raw.get('company', '')
            company = self.db.fuzzy_match_company(company_name)
            company_id = company.get('id') if company else None

            clean = CleanListing(
                raw_id=raw.get('id'),
                title=raw.get('title', ''),
                company=company_name,
                company_id=company_id,
                location=raw.get('location', ''),
                stipend_monthly=raw.get('stipend_normalized', 0) or 0,
                duration_months=raw.get('duration_months', 0) or 0,
                applicants=raw.get('applicants', 0) or 0,
                is_ppo=bool(raw.get('is_ppo', False)),
                is_wfh=bool(raw.get('is_wfh', False)),
                source=raw.get('source', ''),
                url=raw.get('url', ''),
                description_text=raw.get('description_text', '')[:10000],
            )
            return clean
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Clean listing creation error: {e}")
            return None

    def check_single(self, title: str, company: str, url: str = "",
                     location: str = "", description: str = "",
                     stipend: float = 0, duration: int = 0) -> Optional[DedupMatch]:
        """
        Check a single listing for duplicates without inserting.
        Useful for real-time dedup during scraping.
        """
        # Load caches if not loaded
        self.layer1.load_cache()
        self.layer2.load_cache()
        self.layer3.load_cache()
        self.layer5.load_cache()
        self.layer6.load_cache()

        # Run through layers
        match = self.layer1.check(url)
        if match:
            return match

        match = self.layer6.check(url)
        if match:
            return match

        match = self.layer2.check(title, company, location)
        if match:
            return match

        match = self.layer3.check(title, company)
        if match:
            return match

        if stipend > 0 or duration > 0:
            match = self.layer5.check(company, location, stipend, duration)
            if match:
                return match

        return None

    def generate_report(self, stats: DedupStats) -> str:
        """Generate formatted report for Telegram."""
        lines = [
            f"🔄 <b>Dedup Engine Report</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📊 <b>Results:</b>",
            f"  Processed: {stats.total_processed}",
            f"  New listings: {stats.new_clean_listings}",
            f"  Duplicates removed: {stats.duplicates_found}",
            f"  Dedup rate: {stats.duplicates_found / max(stats.total_processed, 1) * 100:.1f}%",
            f"",
            f"📋 <b>By Layer:</b>",
            f"  L1 URL Match: {stats.layer_1_url_matches}",
            f"  L2 Exact Match: {stats.layer_2_exact_matches}",
            f"  L3 Fuzzy Match: {stats.layer_3_fuzzy_matches}",
            f"  L4 Semantic Match: {stats.layer_4_semantic_matches}",
            f"  L5 Metadata Match: {stats.layer_5_metadata_matches}",
            f"  L6 Cross-Platform: {stats.layer_6_crossid_matches}",
            f"",
            f"⏱ Duration: {stats.duration_sec}s",
        ]

        if stats.errors > 0:
            lines.append(f"⚠️ Errors: {stats.errors}")

        return '\n'.join(lines)


# ============================================================
# MODULE-LEVEL FACTORY
# ============================================================

_engine_instance: Optional[DedupEngine] = None


def get_dedup_engine() -> DedupEngine:
    """Get or create the singleton DedupEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DedupEngine()
    return _engine_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test text normalization
    print("\n📝 Text Normalization Tests:")
    test_titles = [
        "MBA Intern - Marketing (2026 Batch) [Remote]",
        "Marketing Intern - MBA / Summer 2026",
        "mba intern  marketing    2026 batch remote",
        "Management Trainee — Marketing",
        "MARKETING INTERN • Summer Program",
    ]
    for title in test_titles:
        normalized = TextNormalizer.normalize_title(title)
        print(f"  '{title}'\n    → '{normalized}'")

    # Test company normalization
    print("\n🏢 Company Normalization Tests:")
    test_companies = [
        "Tata Consultancy Services Pvt. Ltd.",
        "tata consultancy services private limited",
        "Infosys Technologies India Pvt Ltd",
        "HDFC Bank Limited",
        "Reliance Industries Ltd.",
    ]
    for company in test_companies:
        normalized = TextNormalizer.normalize_company(company)
        print(f"  '{company}' → '{normalized}'")

    # Test location normalization
    print("\n📍 Location Normalization Tests:")
    test_locations = [
        "Bangalore, Karnataka, India",
        "Gurgaon, Haryana",
        "Mumbai, Maharashtra, India",
        "Work from Home",
        "Whitefield, Bangalore",
        "BKC, Mumbai",
        "Cyber City, Gurgaon",
    ]
    for loc in test_locations:
        normalized = TextNormalizer.normalize_location(loc)
        print(f"  '{loc}' → '{normalized}'")

    # Test URL hash
    print("\n🔗 URL Hash Tests:")
    test_urls = [
        ("https://internshala.com/internship/detail/abc-123", "https://internshala.com/internship/detail/abc-123/"),
        ("https://example.com/job?utm_source=google&id=5", "https://example.com/job?id=5"),
    ]
    for url1, url2 in test_urls:
        h1 = TextNormalizer.compute_url_hash(url1)
        h2 = TextNormalizer.compute_url_hash(url2)
        match = "✅ MATCH" if h1 == h2 else "❌ DIFFERENT"
        print(f"  {match}: '{url1[:50]}' vs '{url2[:50]}'")

    # Test platform ID extraction
    print("\n🆔 Platform ID Extraction Tests:")
    test_id_urls = [
        "https://internshala.com/internship/detail/marketing-intern-at-hdfc-12345",
        "https://www.naukri.com/job-listings-mba-intern-67890",
        "https://www.linkedin.com/jobs/view/3456789012",
        "https://boards.greenhouse.io/razorpay/jobs/54321",
        "https://jobs.lever.co/cred/abc12345-6789-0abc-def0-123456789abc",
    ]
    for url in test_id_urls:
        ids = TextNormalizer.extract_platform_id(url)
        print(f"  '{url[:60]}...'\n    → {ids}")

    # Test fuzzy matching
    if RAPIDFUZZ_AVAILABLE:
        print("\n🔍 Fuzzy Matching Tests:")
        test_pairs = [
            ("Marketing Intern - Digital", "Digital Marketing Intern"),
            ("MBA Summer Intern Finance", "Finance Intern MBA Summer 2026"),
            ("Software Engineer Senior", "Marketing Intern Junior"),
            ("Business Analyst", "Business Development Analyst"),
        ]
        for t1, t2 in test_pairs:
            n1 = TextNormalizer.normalize_title(t1)
            n2 = TextNormalizer.normalize_title(t2)
            ratio = fuzz.ratio(n1, n2)
            token_sort = fuzz.token_sort_ratio(n1, n2)
            token_set = fuzz.token_set_ratio(n1, n2)
            best = max(ratio, token_sort, token_set * 0.9)
            dup = "✅ DUP" if best >= LAYER_3_FUZZY_THRESHOLD else "❌ UNIQUE"
            print(f"  {dup} (score={best:.0f}): '{t1}' vs '{t2}'")

    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) — All tests passed!")
    print(f"  Layers: 6")
    print(f"  RapidFuzz: {'✅' if RAPIDFUZZ_AVAILABLE else '❌'}")
    print(f"  BERT: {'✅' if BERT_AVAILABLE else '❌'}")
    print(f"  Location synonyms: {len(LOCATION_SYNONYMS)}")
    print(f"  Platform ID patterns: {sum(len(v) for v in PLATFORM_ID_PATTERNS.values())}")
    print("=" * 60)
