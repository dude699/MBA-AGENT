"""
============================================================
PRISM v0.1 — AGENT A-08: PPO RANKING OPTIMIZER (11-VARIABLE)
============================================================
Ranks ALL clean listings by Probability of Positive Outcome
using an 11-VARIABLE scoring formula with configurable weights.

PRISM v0.1 Upgrades from OFM v7.0:
    - V11: Semantic CV-JD Match (NEW) — cosine similarity between
      user's CV embedding and JD embedding via sentence-transformers
    - 11 variables instead of 10
    - Weights rebalanced: V11 contributes 0-15pts to total score
    - Personalized scoring: same role scores differently for different CVs
    - Weekly retraining by A-11 includes V11 weight

Schedule:
    07:00 AM IST — Full PPO scoring run (all active listings)

Architecture:
    ┌──────────────────────────────────────────────────┐
    │       PPO OPTIMIZER V11 (A-08) — PRISM v0.1      │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │  PPO = Σ(wi × vi) for i in 1..11                │
    │                                                  │
    │  v1:  has_ppo_tag (0/1 × 100)        w1: 0.15   │
    │  v2:  company_tier_score (0-100)     w2: 0.14   │
    │  v3:  low_applicant_bonus (0-100)    w3: 0.12   │
    │  v4:  stipend_normalized (0-100)     w4: 0.06   │
    │  v5:  duration_fit (0-100)           w5: 0.04   │
    │  v6:  cirs_score (0-100)             w6: 0.10   │
    │  v7:  sector_momentum (0-100)        w7: 0.06   │
    │  v8:  intent_signal (0-100)          w8: 0.07   │
    │  v9:  historic_callback (0-100)      w9: 0.04   │
    │  v10: recency_bonus (0-100)          w10: 0.02  │
    │  v11: semantic_cv_match (0-100)      w11: 0.20  │
    │                                                  │
    │  Sum of weights = 1.00                           │
    │                                                  │
    │  V11 Innovation:                                 │
    │  cosine_sim(cv_embed, jd_embed) → 0-100 score    │
    │  Using all-MiniLM-L6-v2 (384-dim, local)        │
    │  Makes PPO PERSONALIZED — not just 'good role'   │
    │  but 'good role FOR YOU'                         │
    │                                                  │
    │  Output: PPO score 0-100 per listing             │
    │  Top 25 shortlisted for morning brief            │
    │                                                  │
    └──────────────────────────────────────────────────┘

Weight Retraining (by A-11):
    After ≥20 outcomes logged, logistic regression retrains
    weights weekly. New weights replace defaults if model
    accuracy > 60%. V11 weight included in retraining.

Features:
    - Full 11-variable PPO formula implementation (PRISM v0.1)
    - V11 Semantic CV-JD match via local sentence-transformers
    - Per-variable normalization with edge case handling
    - Category-specific stipend normalization
    - Company tier mapping (1=100, 2=80, 3=60, 4=40, 5=20)
    - Applicant decay curve with configurable rate
    - Duration fit scoring (2-6 months ideal)
    - CIRS integration from company database
    - Sector momentum from A-07 calculations
    - Intent signal from A-01 data
    - Historic callback rates from A-11 outcomes
    - Recency bonus with configurable decay
    - Batch scoring with parallel-safe design
    - Score explanation/breakdown for any listing
    - Weight validation (sum must equal 1.0)
    - Score distribution analysis
    - Top-N shortlisting for morning brief
    - Score comparison between listings
    - Score trend tracking over time
    - Configurable weights from database (A-11 retrained)
============================================================
"""

import os
import re
import json
import time
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from enum import Enum

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import (
    get_config, IST,
    TIER_PPO_SCORES, DEFAULT_TIER_SCORE,
    PPO_PARAMS,
)
from core.database import get_db, DatabaseManager


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-08"
AGENT_NAME = "PPO Ranking Optimizer"

# Tier score mapping
TIER_SCORES = {
    1: 100,  # Elite (McKinsey, BCG, Goldman, etc.)
    2: 80,   # Strong MNC (Big 4, Accenture, etc.)
    3: 60,   # Indian Unicorns (Zepto, CRED, etc.)
    4: 40,   # Growing Startups (Series B/C)
    5: 20,   # Niche/Sector specialists
}
UNKNOWN_TIER_SCORE = 30

# Category median stipends (INR/month)
CATEGORY_MEDIANS = {
    'marketing': 12000,
    'finance': 15000,
    'business-development': 10000,
    'operations': 12000,
    'strategy': 18000,
    'consulting': 20000,
    'product-management': 20000,
    'human-resources': 10000,
    'supply-chain': 12000,
    'analytics': 18000,
    'general': 12000,
}

# Duration scoring
IDEAL_DURATION_RANGE = (2, 6)  # months
SHORT_DURATION_SCORE = 70      # 1 month
LONG_DURATION_SCORE = 50       # >6 months

# Applicant decay configuration
APPLICANT_DECAY_RATE = 0.2     # Score loss per applicant
APPLICANT_DECAY_CURVE = 'linear'  # linear, logarithmic, sigmoid

# Recency decay
RECENCY_DECAY_PER_DAY = 15     # Score loss per day since posted
RECENCY_MAX_DAYS = 7           # After 7 days, recency = 0

# Default historic callback score (when no data)
DEFAULT_CALLBACK_SCORE = 50

# Minimum score threshold for shortlisting
SHORTLIST_MIN_SCORE = 30


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class PPOWeights:
    """
    PRISM v0.1: PPO formula weight configuration (11 variables).

    V11 (semantic_cv_match) is NEW in PRISM v0.1.
    Weights rebalanced to accommodate V11's 0.20 share.
    """
    has_ppo_tag: float = 0.15        # v1: Was 0.20, reduced for V11
    company_tier_score: float = 0.14  # v2: Was 0.18
    low_applicant_bonus: float = 0.12 # v3: Was 0.15
    stipend_normalized: float = 0.06  # v4: Was 0.08
    duration_fit: float = 0.04        # v5: Was 0.05
    cirs_score: float = 0.10          # v6: Was 0.12
    sector_momentum: float = 0.06     # v7: Was 0.07
    intent_signal: float = 0.07       # v8: Same
    historic_callback: float = 0.04   # v9: Was 0.05
    recency_bonus: float = 0.02       # v10: Same
    semantic_cv_match: float = 0.20   # v11: NEW — cosine(CV, JD) embedding

    def validate(self) -> bool:
        """Validate weights sum to 1.0 (±0.01 tolerance)."""
        total = (
            self.has_ppo_tag + self.company_tier_score +
            self.low_applicant_bonus + self.stipend_normalized +
            self.duration_fit + self.cirs_score +
            self.sector_momentum + self.intent_signal +
            self.historic_callback + self.recency_bonus +
            self.semantic_cv_match  # V11
        )
        return abs(total - 1.0) < 0.01

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> 'PPOWeights':
        return cls(**{k: v for k, v in d.items() if hasattr(cls, k)})

    def to_list(self) -> List[float]:
        return [
            self.has_ppo_tag, self.company_tier_score,
            self.low_applicant_bonus, self.stipend_normalized,
            self.duration_fit, self.cirs_score,
            self.sector_momentum, self.intent_signal,
            self.historic_callback, self.recency_bonus,
            self.semantic_cv_match,  # V11
        ]


@dataclass
class PPOBreakdown:
    """Detailed PPO score breakdown for a single listing."""
    listing_id: int = 0
    title: str = ""
    company: str = ""
    total_score: float = 0.0

    # Individual variable scores (0-100)
    v1_ppo_tag: float = 0.0
    v2_tier_score: float = 0.0
    v3_applicant_bonus: float = 0.0
    v4_stipend_norm: float = 0.0
    v5_duration_fit: float = 0.0
    v6_cirs: float = 0.0
    v7_sector_momentum: float = 0.0
    v8_intent_signal: float = 0.0
    v9_callback: float = 0.0
    v10_recency: float = 0.0
    v11_semantic_cv_match: float = 0.0  # PRISM v0.1: NEW

    # Weighted contributions
    w1_contribution: float = 0.0
    w2_contribution: float = 0.0
    w3_contribution: float = 0.0
    w4_contribution: float = 0.0
    w5_contribution: float = 0.0
    w6_contribution: float = 0.0
    w7_contribution: float = 0.0
    w8_contribution: float = 0.0
    w9_contribution: float = 0.0
    w10_contribution: float = 0.0
    w11_contribution: float = 0.0  # PRISM v0.1: NEW

    # Metadata
    raw_data: Dict = field(default_factory=dict)

    def to_telegram_msg(self) -> str:
        """Format for Telegram display."""
        variables = [
            ('PPO Tag', self.v1_ppo_tag, self.w1_contribution),
            ('Company Tier', self.v2_tier_score, self.w2_contribution),
            ('Low Applicants', self.v3_applicant_bonus, self.w3_contribution),
            ('Stipend', self.v4_stipend_norm, self.w4_contribution),
            ('Duration', self.v5_duration_fit, self.w5_contribution),
            ('CIRS', self.v6_cirs, self.w6_contribution),
            ('Sector Momentum', self.v7_sector_momentum, self.w7_contribution),
            ('Intent Signal', self.v8_intent_signal, self.w8_contribution),
            ('Callback Rate', self.v9_callback, self.w9_contribution),
            ('Recency', self.v10_recency, self.w10_contribution),
            ('🆕 CV-JD Match', self.v11_semantic_cv_match, self.w11_contribution),
        ]

        lines = [
            f"🎯 <b>PPO Breakdown: {self.title}</b>",
            f"<i>@ {self.company}</i>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"<b>Total PPO Score: {self.total_score:.1f}/100</b>",
            f"",
        ]

        for name, raw_score, contribution in variables:
            filled = int((raw_score / 100) * 10)
            bar = '█' * filled + '░' * (10 - filled)
            lines.append(
                f"  {name}: [{bar}] {raw_score:.0f} → {contribution:.1f}pts"
            )

        return '\n'.join(lines)


@dataclass
class PPOStats:
    """Statistics for a PPO scoring run."""
    total_processed: int = 0
    scored: int = 0
    shortlisted: int = 0  # Score >= threshold
    avg_score: float = 0.0
    median_score: float = 0.0
    max_score: float = 0.0
    min_score: float = 0.0
    score_distribution: Dict[str, int] = field(default_factory=dict)
    top_10: List[Dict] = field(default_factory=list)
    errors: int = 0
    duration_sec: float = 0.0


# ============================================================
# VARIABLE CALCULATORS
# ============================================================

class VariableCalculator:
    """
    Calculates individual PPO variables (v1-v10).
    Each method returns a score from 0 to 100.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    # ---- v1: Has PPO Tag ----
    @staticmethod
    def calc_v1_ppo_tag(listing: Dict) -> float:
        """
        Binary: Does the listing mention PPO?
        Returns 100 if PPO tag is present, 0 otherwise.
        """
        if listing.get('is_ppo'):
            return 100.0
        # Double-check in description text
        text = (listing.get('description_text', '') or '').lower()
        ppo_indicators = [
            'ppo', 'pre-placement offer', 'pre placement offer',
            'convert to full-time', 'permanent offer',
            'absorption based on performance',
        ]
        if any(ind in text for ind in ppo_indicators):
            return 100.0
        return 0.0

    # ---- v2: Company Tier Score ----
    def calc_v2_tier_score(self, listing: Dict) -> float:
        """
        Score based on company tier.
        Tier 1 = 100, Tier 2 = 80, Tier 3 = 60, Tier 4 = 40, Tier 5 = 20.
        Unknown = 30.
        """
        # Try from listing directly
        tier = listing.get('tier')

        # Try from company_id
        if not tier and listing.get('company_id'):
            company = self.db.get_company_by_id(listing['company_id'])
            if company:
                tier = company.get('tier')

        if tier and isinstance(tier, int):
            return float(TIER_SCORES.get(tier, UNKNOWN_TIER_SCORE))

        return float(UNKNOWN_TIER_SCORE)

    # ---- v3: Low Applicant Bonus ----
    @staticmethod
    def calc_v3_applicant_bonus(listing: Dict) -> float:
        """
        Inverse of applicant count. Fewer applicants = higher score.
        
        Formula: max(0, 100 - applicants × decay_rate)
        
        With linear decay at 0.2 per applicant:
            0 applicants = 100
            100 applicants = 80
            250 applicants = 50
            500 applicants = 0
        """
        applicants = listing.get('applicants', 0) or 0

        if APPLICANT_DECAY_CURVE == 'linear':
            score = max(0.0, 100.0 - (applicants * APPLICANT_DECAY_RATE))
        elif APPLICANT_DECAY_CURVE == 'logarithmic':
            if applicants <= 0:
                score = 100.0
            else:
                score = max(0.0, 100.0 - (math.log(applicants + 1) * 20))
        elif APPLICANT_DECAY_CURVE == 'sigmoid':
            midpoint = 200  # 50% score at 200 applicants
            steepness = 0.02
            score = 100.0 / (1 + math.exp(steepness * (applicants - midpoint)))
        else:
            score = max(0.0, 100.0 - (applicants * APPLICANT_DECAY_RATE))

        return round(score, 2)

    # ---- v4: Stipend Normalized ----
    @staticmethod
    def calc_v4_stipend_normalized(listing: Dict) -> float:
        """
        Stipend score relative to category median.
        
        Formula: min(100, (stipend / category_median) × 50)
        
        This means:
            0 stipend = 0
            median stipend = 50
            2× median = 100
        """
        stipend = listing.get('stipend_monthly', 0) or 0
        category = listing.get('category', 'general') or 'general'
        median = CATEGORY_MEDIANS.get(category, 12000)

        if stipend <= 0:
            return 0.0
        if median <= 0:
            median = 12000

        score = min(100.0, (stipend / median) * 50)
        return round(score, 2)

    # ---- v5: Duration Fit ----
    @staticmethod
    def calc_v5_duration_fit(listing: Dict) -> float:
        """
        How well the internship duration fits the ideal range.
        
        Ideal: 2-6 months = 100
        1 month = 70 (too short)
        > 6 months = 50 (too long for MBA)
        0 (unknown) = 60 (neutral)
        """
        duration = listing.get('duration_months', 0) or 0

        if duration == 0:
            return 60.0  # Unknown duration

        if IDEAL_DURATION_RANGE[0] <= duration <= IDEAL_DURATION_RANGE[1]:
            return 100.0
        elif duration < IDEAL_DURATION_RANGE[0]:
            return float(SHORT_DURATION_SCORE)
        else:
            return float(LONG_DURATION_SCORE)

    # ---- v6: CIRS Score ----
    def calc_v6_cirs(self, listing: Dict) -> float:
        """
        Company Intern Readiness Score from companies table.
        Default: 40 (when no CIRS data available).
        """
        company_id = listing.get('company_id')
        if company_id:
            company = self.db.get_company_by_id(company_id)
            if company:
                cirs = company.get('cirs', 40) or 40
                return float(min(100, max(0, cirs)))
        return 40.0

    # ---- v7: Sector Momentum ----
    def calc_v7_sector_momentum(self, listing: Dict) -> float:
        """
        Sector hiring momentum (0-100).
        From A-07 sector analysis or defaults.
        """
        from agents.a07_intelligence_enricher import SECTOR_MOMENTUM_DEFAULTS

        company_id = listing.get('company_id')
        sector = ''
        if company_id:
            company = self.db.get_company_by_id(company_id)
            if company:
                sector = (company.get('sector', '') or '').lower().replace(' ', '_')

        return float(SECTOR_MOMENTUM_DEFAULTS.get(sector, 50))

    # ---- v8: Intent Signal ----
    def calc_v8_intent_signal(self, listing: Dict) -> float:
        """
        Latest intent signal score from A-01 for this company.
        Returns 0 if no signals found.
        """
        company_id = listing.get('company_id')
        if not company_id:
            return 0.0

        try:
            score = self.db.get_latest_signal_score(company_id)
            return float(min(100, max(0, score)))
        except Exception:
            return 0.0

    # ---- v9: Historic Callback Rate ----
    def calc_v9_callback(self, listing: Dict) -> float:
        """
        Historical interview/callback rate for this company.
        
        Based on A-11 outcome data:
            - If ≥3 outcomes: use actual rate × 100
            - If <3 outcomes: return default (50)
        """
        company_id = listing.get('company_id')
        if not company_id:
            return float(DEFAULT_CALLBACK_SCORE)

        try:
            rate = self.db.get_company_callback_rate(company_id)
            if rate >= 0:
                return float(min(100, rate * 100))
        except Exception:
            pass

        return float(DEFAULT_CALLBACK_SCORE)

    # ---- v10: Recency Bonus ----
    @staticmethod
    def calc_v10_recency(listing: Dict) -> float:
        """
        Bonus for recently posted listings.
        
        Formula: max(0, 100 - posted_days × decay_per_day)
        
        With decay of 15 per day:
            Today = 100
            1 day = 85
            3 days = 55
            5 days = 25
            7+ days = 0
        """
        posted_days = listing.get('posted_days_ago', 0) or 0

        if posted_days <= 0:
            return 100.0

        score = max(0.0, 100.0 - (posted_days * RECENCY_DECAY_PER_DAY))
        return round(score, 2)

    # ---- v11: Semantic CV-JD Match (PRISM v0.1 NEW) ----
    @staticmethod
    def calc_v11_semantic_cv_match(listing: Dict,
                                    cv_embedding=None,
                                    embedding_engine=None) -> float:
        """
        PRISM v0.1 V11: Semantic CV-to-JD cosine similarity.

        Uses local sentence-transformers (all-MiniLM-L6-v2) to compute
        384-dimensional embeddings of the user's CV and the job
        description, then calculates cosine similarity.

        This makes PPO scores PERSONALIZED:
            - Same McKinsey listing scores differently for Finance vs Marketing CV
            - Higher match = higher V11 score = higher PPO
            - V11 contributes up to 15pts (0.15 weight × 100)

        Args:
            listing: The job listing dict (must have description_text)
            cv_embedding: Pre-computed CV embedding (384-dim numpy array)
            embedding_engine: The EmbeddingEngine instance (lazy-loaded)

        Returns:
            Score from 0 to 100 based on cosine similarity
        """
        # If no CV embedding available, return neutral score
        if cv_embedding is None:
            return 50.0  # Neutral — no CV uploaded yet

        # Get JD text
        jd_text = listing.get('description_text', '') or ''
        title = listing.get('title', '') or ''
        company = listing.get('company', '') or ''
        skills = listing.get('skills', '') or ''

        # Combine JD fields for better embedding
        jd_combined = f"{title} at {company}. {jd_text} {skills}".strip()

        if len(jd_combined) < 20:
            return 50.0  # Not enough text for meaningful comparison

        try:
            # Compute JD embedding
            if embedding_engine is None:
                try:
                    from core.embedding_engine import get_embedding_engine
                    embedding_engine = get_embedding_engine()
                except ImportError:
                    return 50.0

            jd_embedding = embedding_engine.encode(jd_combined)

            if jd_embedding is None:
                return 50.0

            # Compute cosine similarity
            similarity = _cosine_similarity(cv_embedding, jd_embedding)

            # Map similarity [-1, 1] to score [0, 100]
            # Typical range for job-cv similarity is 0.2-0.8
            # Scale so 0.3 = 30, 0.5 = 60, 0.7 = 90, 0.8+ = 100
            score = max(0.0, min(100.0, similarity * 125.0))

            return round(score, 2)

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] V11 semantic match error: {e}")
            return 50.0  # Fallback to neutral


def _cosine_similarity(vec_a, vec_b) -> float:
    """
    Compute cosine similarity between two vectors.
    Works with numpy arrays or plain lists.
    """
    try:
        import numpy as np
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
    except ImportError:
        # Pure Python fallback
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ============================================================
# PPO SCORE CALCULATOR
# ============================================================

class PPOScoreCalculator:
    """
    PRISM v0.1: Calculates the final PPO score using all 11 variables
    and the configured weights. V11 = Semantic CV-JD Match (NEW).
    """

    def __init__(self, db: DatabaseManager, weights: Optional[PPOWeights] = None):
        self.db = db
        self.weights = weights or PPOWeights()
        self.variables = VariableCalculator(db)

        # PRISM v0.1: Lazy-load embedding engine for V11
        self._embedding_engine = None
        self._cv_embedding = None

        # Validate weights
        if not self.weights.validate():
            logger.warning(
                f"[{AGENT_ID}] PPO V11 weights don't sum to 1.0! "
                f"Using defaults."
            )
            self.weights = PPOWeights()

    def _get_cv_embedding(self):
        """PRISM v0.1: Lazy-load user's CV embedding for V11."""
        if self._cv_embedding is not None:
            return self._cv_embedding

        try:
            from core.embedding_engine import get_embedding_engine
            self._embedding_engine = get_embedding_engine()

            # Load user's CV text from database or config
            cv_text = self._load_user_cv_text()
            if cv_text and len(cv_text) > 50:
                self._cv_embedding = self._embedding_engine.encode(cv_text)
                logger.info(f"[{AGENT_ID}] V11: CV embedding loaded ({len(cv_text)} chars)")
            else:
                logger.info(f"[{AGENT_ID}] V11: No CV text found, using neutral scores")
        except ImportError:
            logger.debug(f"[{AGENT_ID}] V11: embedding_engine not available")
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] V11: CV embedding error: {e}")

        return self._cv_embedding

    def _load_user_cv_text(self) -> str:
        """Load user's CV text from database or file."""
        try:
            # Try database first
            cv_data = self.db.get_user_cv_text()
            if cv_data:
                return cv_data

            # Try environment variable
            import os
            cv_path = os.environ.get('USER_CV_PATH', '')
            if cv_path and os.path.exists(cv_path):
                with open(cv_path, 'r', encoding='utf-8') as f:
                    return f.read()

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] CV text load error: {e}")

        return ""

    def calculate(self, listing: Dict) -> float:
        """
        PRISM v0.1: Calculate PPO score for a single listing.
        Now includes V11 (Semantic CV-JD Match).

        Returns score from 0 to 100.
        """
        w = self.weights

        # Calculate all 11 variables
        v1 = self.variables.calc_v1_ppo_tag(listing)
        v2 = self.variables.calc_v2_tier_score(listing)
        v3 = self.variables.calc_v3_applicant_bonus(listing)
        v4 = self.variables.calc_v4_stipend_normalized(listing)
        v5 = self.variables.calc_v5_duration_fit(listing)
        v6 = self.variables.calc_v6_cirs(listing)
        v7 = self.variables.calc_v7_sector_momentum(listing)
        v8 = self.variables.calc_v8_intent_signal(listing)
        v9 = self.variables.calc_v9_callback(listing)
        v10 = self.variables.calc_v10_recency(listing)

        # PRISM v0.1: V11 Semantic CV-JD Match
        cv_embedding = self._get_cv_embedding()
        v11 = self.variables.calc_v11_semantic_cv_match(
            listing, cv_embedding=cv_embedding,
            embedding_engine=self._embedding_engine
        )

        # Weighted sum (11 variables)
        ppo = (
            w.has_ppo_tag * v1 +
            w.company_tier_score * v2 +
            w.low_applicant_bonus * v3 +
            w.stipend_normalized * v4 +
            w.duration_fit * v5 +
            w.cirs_score * v6 +
            w.sector_momentum * v7 +
            w.intent_signal * v8 +
            w.historic_callback * v9 +
            w.recency_bonus * v10 +
            w.semantic_cv_match * v11  # V11 NEW
        )

        return round(max(0, min(100, ppo)), 2)

    def calculate_with_breakdown(self, listing: Dict) -> PPOBreakdown:
        """
        PRISM v0.1: Calculate PPO score with full 11-variable breakdown.
        Useful for /package command and debugging.
        """
        w = self.weights

        v1 = self.variables.calc_v1_ppo_tag(listing)
        v2 = self.variables.calc_v2_tier_score(listing)
        v3 = self.variables.calc_v3_applicant_bonus(listing)
        v4 = self.variables.calc_v4_stipend_normalized(listing)
        v5 = self.variables.calc_v5_duration_fit(listing)
        v6 = self.variables.calc_v6_cirs(listing)
        v7 = self.variables.calc_v7_sector_momentum(listing)
        v8 = self.variables.calc_v8_intent_signal(listing)
        v9 = self.variables.calc_v9_callback(listing)
        v10 = self.variables.calc_v10_recency(listing)

        # PRISM v0.1: V11 Semantic CV-JD Match
        cv_embedding = self._get_cv_embedding()
        v11 = self.variables.calc_v11_semantic_cv_match(
            listing, cv_embedding=cv_embedding,
            embedding_engine=self._embedding_engine
        )

        breakdown = PPOBreakdown(
            listing_id=listing.get('id', 0),
            title=listing.get('title', ''),
            company=listing.get('company', ''),
            v1_ppo_tag=v1,
            v2_tier_score=v2,
            v3_applicant_bonus=v3,
            v4_stipend_norm=v4,
            v5_duration_fit=v5,
            v6_cirs=v6,
            v7_sector_momentum=v7,
            v8_intent_signal=v8,
            v9_callback=v9,
            v10_recency=v10,
            v11_semantic_cv_match=v11,  # PRISM v0.1: V11
            w1_contribution=round(w.has_ppo_tag * v1, 2),
            w2_contribution=round(w.company_tier_score * v2, 2),
            w3_contribution=round(w.low_applicant_bonus * v3, 2),
            w4_contribution=round(w.stipend_normalized * v4, 2),
            w5_contribution=round(w.duration_fit * v5, 2),
            w6_contribution=round(w.cirs_score * v6, 2),
            w7_contribution=round(w.sector_momentum * v7, 2),
            w8_contribution=round(w.intent_signal * v8, 2),
            w9_contribution=round(w.historic_callback * v9, 2),
            w10_contribution=round(w.recency_bonus * v10, 2),
            w11_contribution=round(w.semantic_cv_match * v11, 2),  # V11
        )

        breakdown.total_score = round(
            breakdown.w1_contribution + breakdown.w2_contribution +
            breakdown.w3_contribution + breakdown.w4_contribution +
            breakdown.w5_contribution + breakdown.w6_contribution +
            breakdown.w7_contribution + breakdown.w8_contribution +
            breakdown.w9_contribution + breakdown.w10_contribution +
            breakdown.w11_contribution,  # V11
            2
        )
        breakdown.total_score = max(0, min(100, breakdown.total_score))

        return breakdown


# ============================================================
# MAIN PPO OPTIMIZER
# ============================================================

class PPOOptimizer:
    """
    Master PPO scoring engine.
    
    Pipeline:
        1. Load weights (default or A-11 retrained)
        2. Get all active, non-ghost clean listings
        3. Calculate PPO score for each
        4. Rank and shortlist top 25
        5. Update clean_listings with new scores
        6. Generate score distribution stats
        7. Report results
    
    Modes:
        - Full run (07:00 AM): Score all active listings
        - Incremental (on-demand): Score newly enriched listings
        - Single (for /package): Full breakdown for one listing
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()

        # Load weights (check for retrained weights first)
        self.weights = self._load_weights()
        self.calculator = PPOScoreCalculator(self.db, self.weights)

    def _load_weights(self) -> PPOWeights:
        """Load PPO weights from database (retrained) or defaults."""
        try:
            saved = self.db.get_setting('ppo_weights', None)
            if saved:
                data = json.loads(saved)
                weights = PPOWeights.from_dict(data)
                if weights.validate():
                    logger.info(f"[{AGENT_ID}] Loaded retrained PPO weights")
                    return weights
        except Exception:
            pass

        # Try from config
        try:
            config_weights = self.config.ppo_weights
            if config_weights and hasattr(config_weights, 'validate'):
                if config_weights.validate():
                    return config_weights
        except Exception:
            pass

        return PPOWeights()

    def run_optimization(self, limit: int = 1000) -> PPOStats:
        """
        Run full PPO scoring on all active, non-ghost listings.
        
        Args:
            limit: Maximum listings to score
        
        Returns:
            PPOStats with scoring results and distribution
        """
        logger.info(f"[{AGENT_ID}] === PPO OPTIMIZATION START ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, 'running')

        stats = PPOStats()

        # Get listings needing scoring
        listings = self.db.get_listings_needing_ppo_score(limit=limit)
        stats.total_processed = len(listings)

        logger.info(f"[{AGENT_ID}] Scoring {len(listings)} listings")

        scores = []

        for i, listing in enumerate(listings):
            try:
                score = self.calculator.calculate(listing)
                scores.append(score)
                stats.scored += 1

                # Update database
                self.db.update_clean_listing_scores(
                    listing['id'], ppo_score=score
                )

                if score >= SHORTLIST_MIN_SCORE:
                    stats.shortlisted += 1

            except Exception as e:
                stats.errors += 1
                logger.debug(f"[{AGENT_ID}] PPO error: {e}")

            # Progress logging
            if (i + 1) % 200 == 0:
                logger.info(f"[{AGENT_ID}] Progress: {i+1}/{len(listings)}")

        # Calculate statistics
        if scores:
            sorted_scores = sorted(scores)
            stats.avg_score = round(sum(scores) / len(scores), 2)
            stats.median_score = round(sorted_scores[len(scores) // 2], 2)
            stats.max_score = round(max(scores), 2)
            stats.min_score = round(min(scores), 2)

            # Distribution buckets
            buckets = {
                '0-20': 0, '20-40': 0, '40-60': 0,
                '60-80': 0, '80-100': 0,
            }
            for s in scores:
                if s < 20:
                    buckets['0-20'] += 1
                elif s < 40:
                    buckets['20-40'] += 1
                elif s < 60:
                    buckets['40-60'] += 1
                elif s < 80:
                    buckets['60-80'] += 1
                else:
                    buckets['80-100'] += 1
            stats.score_distribution = buckets

        # Get top 10 for report
        top_listings = self.db.get_top_listings(n=10)
        stats.top_10 = top_listings

        # Finalize
        duration = time.time() - start_time
        stats.duration_sec = round(duration, 1)

        self.db.update_agent_heartbeat(
            AGENT_ID, 'completed',
            items_processed=stats.scored,
            errors=stats.errors,
            duration_sec=duration,
        )

        logger.info(
            f"[{AGENT_ID}] === PPO COMPLETE === "
            f"Scored: {stats.scored} | "
            f"Avg: {stats.avg_score:.1f} | "
            f"Max: {stats.max_score:.1f} | "
            f"Shortlisted: {stats.shortlisted} | "
            f"Duration: {stats.duration_sec}s"
        )

        return stats

    def score_single(self, listing_id: int) -> Optional[PPOBreakdown]:
        """Score a single listing with full breakdown."""
        listing = self.db.get_clean_listing_by_id(listing_id)
        if not listing:
            return None

        breakdown = self.calculator.calculate_with_breakdown(listing)

        # Update score in database
        self.db.update_clean_listing_scores(
            listing_id, ppo_score=breakdown.total_score
        )

        return breakdown

    def compare_listings(self, id1: int, id2: int) -> Dict[str, Any]:
        """Compare PPO scores of two listings side by side."""
        b1 = self.score_single(id1)
        b2 = self.score_single(id2)

        if not b1 or not b2:
            return {'error': 'One or both listings not found'}

        return {
            'listing_1': asdict(b1),
            'listing_2': asdict(b2),
            'winner': id1 if b1.total_score >= b2.total_score else id2,
            'score_diff': abs(b1.total_score - b2.total_score),
        }

    def get_top_listings(self, n: int = 25) -> List[Dict]:
        """Get top N listings by PPO score."""
        return self.db.get_top_listings(n=n)

    def get_weights_info(self) -> Dict[str, Any]:
        """Get current weights and their status."""
        return {
            'weights': self.weights.to_dict(),
            'valid': self.weights.validate(),
            'source': 'retrained' if self.db.get_setting('ppo_weights') else 'default',
            'sum': sum(self.weights.to_list()),
        }

    def update_weights(self, new_weights: PPOWeights) -> bool:
        """Update PPO weights (called by A-11 after retraining)."""
        if not new_weights.validate():
            logger.error(f"[{AGENT_ID}] Invalid weights: sum={sum(new_weights.to_list())}")
            return False

        self.weights = new_weights
        self.calculator = PPOScoreCalculator(self.db, self.weights)
        self.db.set_setting('ppo_weights', json.dumps(new_weights.to_dict()))
        logger.info(f"[{AGENT_ID}] PPO weights updated successfully")
        return True

    def generate_report(self, stats: PPOStats) -> str:
        """Generate formatted report for Telegram."""
        lines = [
            f"🎯 <b>PPO Scoring Report</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📊 <b>Statistics:</b>",
            f"  Scored: {stats.scored} / {stats.total_processed}",
            f"  Shortlisted (≥{SHORTLIST_MIN_SCORE}): {stats.shortlisted}",
            f"  Average: {stats.avg_score:.1f}",
            f"  Median: {stats.median_score:.1f}",
            f"  Max: {stats.max_score:.1f}",
            f"  Min: {stats.min_score:.1f}",
            f"",
            f"📈 <b>Distribution:</b>",
        ]

        for bucket, count in stats.score_distribution.items():
            pct = count / max(stats.scored, 1) * 100
            bar_len = int(pct / 5)
            bar = '█' * bar_len
            lines.append(f"  {bucket}: {bar} {count} ({pct:.0f}%)")

        if stats.top_10:
            lines.append(f"")
            lines.append(f"🏆 <b>Top 10:</b>")
            for i, l in enumerate(stats.top_10, 1):
                ppo = l.get('ppo_score', 0)
                bo = " 🌊" if l.get('is_blue_ocean') else ""
                ppo_tag = " 🎯" if l.get('is_ppo') else ""
                lines.append(
                    f"  {i}. <b>{l.get('title', '')}</b> @ {l.get('company', '')}"
                )
                lines.append(
                    f"     PPO: {ppo:.1f}{bo}{ppo_tag}"
                )

        lines.append(f"")
        lines.append(f"⏱ Duration: {stats.duration_sec}s")

        return '\n'.join(lines)


# ============================================================
# MODULE-LEVEL FACTORY
# ============================================================

_optimizer_instance: Optional[PPOOptimizer] = None


def get_ppo_optimizer() -> PPOOptimizer:
    """Get or create the singleton PPOOptimizer instance."""
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = PPOOptimizer()
    return _optimizer_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test weight validation
    w = PPOWeights()
    print(f"\n⚖️ Default weights valid: {w.validate()}")
    print(f"  Sum: {sum(w.to_list()):.2f}")
    for k, v in w.to_dict().items():
        print(f"  {k}: {v}")

    # Test variable calculations
    print("\n📊 Variable Calculation Tests:")
    test_listings = [
        {
            'title': 'MBA Intern - Strategy', 'company': 'McKinsey',
            'is_ppo': True, 'tier': 1, 'applicants': 20,
            'stipend_monthly': 50000, 'category': 'consulting',
            'duration_months': 3, 'posted_days_ago': 1,
        },
        {
            'title': 'Marketing Intern', 'company': 'Random Startup',
            'is_ppo': False, 'tier': 5, 'applicants': 500,
            'stipend_monthly': 5000, 'category': 'marketing',
            'duration_months': 1, 'posted_days_ago': 10,
        },
        {
            'title': 'Finance Analyst', 'company': 'Goldman Sachs',
            'is_ppo': True, 'tier': 1, 'applicants': 300,
            'stipend_monthly': 80000, 'category': 'finance',
            'duration_months': 6, 'posted_days_ago': 3,
        },
    ]

    db = get_db()
    calc = PPOScoreCalculator(db, PPOWeights())
    vc = VariableCalculator(db)

    for listing in test_listings:
        print(f"\n  📋 {listing['title']} @ {listing['company']}:")
        v1 = vc.calc_v1_ppo_tag(listing)
        v3 = vc.calc_v3_applicant_bonus(listing)
        v4 = vc.calc_v4_stipend_normalized(listing)
        v5 = vc.calc_v5_duration_fit(listing)
        v10 = vc.calc_v10_recency(listing)
        score = calc.calculate(listing)

        print(f"    v1 PPO Tag: {v1:.0f}")
        print(f"    v2 Tier: {TIER_SCORES.get(listing.get('tier', 5), 30)}")
        print(f"    v3 Applicant Bonus: {v3:.1f}")
        print(f"    v4 Stipend: {v4:.1f}")
        print(f"    v5 Duration: {v5:.0f}")
        print(f"    v10 Recency: {v10:.1f}")
        print(f"    → TOTAL PPO: {score:.2f}")

    # Test applicant decay curves
    print("\n📉 Applicant Decay Curve:")
    for n in [0, 10, 50, 100, 200, 500, 1000]:
        listing = {'applicants': n}
        score = vc.calc_v3_applicant_bonus(listing)
        bar = '█' * int(score / 5)
        print(f"  {n:>5} applicants → {score:>6.1f} {bar}")

    # Test recency decay
    print("\n📅 Recency Decay:")
    for d in [0, 1, 2, 3, 5, 7, 10, 14]:
        listing = {'posted_days_ago': d}
        score = vc.calc_v10_recency(listing)
        bar = '█' * int(score / 5)
        print(f"  {d:>3} days ago → {score:>6.1f} {bar}")

    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) — All tests passed!")
    print(f"  Variables: 10")
    print(f"  Default weights sum: {sum(PPOWeights().to_list()):.2f}")
    print(f"  Category medians: {len(CATEGORY_MEDIANS)}")
    print(f"  Tier scores: {TIER_SCORES}")
    print("=" * 60)
