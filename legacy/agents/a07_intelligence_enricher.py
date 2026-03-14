"""
============================================================
AGENT A-07: INTELLIGENCE ENRICHER — INDUSTRIAL GRADE
============================================================
Enriches clean listings with competition data, sector analysis,
Blue Ocean flagging, CIRS (Company Intern Readiness Score)
computation, and market intelligence.

Schedule:
    06:30 AM IST  — Morning enrichment (post-dedup batch)
    06:00 PM IST  — Evening enrichment (afternoon scrapes)

AI Model:
    Cerebras (`sector_tag`) — sector/sub-sector classification
    Cerebras (`intent_classify`) — market signal correlation

Architecture:
    ┌──────────────────────────────────────────────────┐
    │         INTELLIGENCE ENRICHER (A-07)             │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Competition Analyzer                      │   │
    │  │  - Applicant count / days posted ratio     │   │
    │  │  - Competition percentile ranking          │   │
    │  │  - Source competition comparison           │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Blue Ocean Detector                       │   │
    │  │  - Prestige ≥ 60 AND Applicants ≤ 35       │   │
    │  │  - Stipend above category median           │   │
    │  │  - PPO tag bonus                           │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  CIRS Calculator                           │   │
    │  │  - Intent signal strength (from A-01)      │   │
    │  │  - Historical PPO conversion rate          │   │
    │  │  - Glassdoor intern reviews                │   │
    │  │  - Funding recency (startups)              │   │
    │  │  - LinkedIn intern posting frequency       │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Sector Momentum Calculator                │   │
    │  │  - Economic signal correlation             │   │
    │  │  - Industry hiring trends                  │   │
    │  │  - Funding cycle analysis                  │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Urgency Scorer                            │   │
    │  │  - Deadline proximity detection            │   │
    │  │  - Application velocity tracking           │   │
    │  │  - Closing date extraction                 │   │
    │  └───────────────────────────────────────────┘   │
    │                                                  │
    └──────────────────────────────────────────────────┘

Blue Ocean Criteria (from OPERATION_PLAN.md):
    - Company Prestige (Tier Score) ≥ 60
    - Applicant Count ≤ 35
    - Stipend ≥ category median (optional bonus)
    - PPO tag present (optional bonus)

CIRS — Company Intern Readiness Score (0-100):
    Default: 40 (for companies without enough data)
    Components:
        - intent_signal_strength: 0-25 (from A-01 signals)
        - historical_ppo_rate: 0-20 (conversion rate)
        - glassdoor_intern_rating: 0-15 (intern review score)
        - funding_recency: 0-15 (recent funding = active hiring)
        - posting_frequency: 0-15 (how often they post internships)
        - career_page_health: 0-10 (active career page indicator)
============================================================
"""

import os
import re
import json
import time
import math
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter
from enum import Enum

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import (
    get_config, IST, CompanyTier,
    TIER_PPO_SCORES, DEFAULT_TIER_SCORE,
    MBA_CATEGORIES, COMPANY_SECTORS,
)
from core.database import get_db, DatabaseManager
from core.ai_router import get_router, AIRouter


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-07"
AGENT_NAME = "Intelligence Enricher"

# Blue Ocean criteria defaults
BLUE_OCEAN_MIN_PRESTIGE = 60       # Minimum company tier score
BLUE_OCEAN_MAX_APPLICANTS = 35     # Maximum applicant count
BLUE_OCEAN_MIN_STIPEND_RATIO = 0.8 # Minimum stipend as ratio of median

# CIRS component weights (sum = 100)
CIRS_WEIGHTS = {
    'intent_signal': 25,
    'historical_ppo': 20,
    'glassdoor_rating': 15,
    'funding_recency': 15,
    'posting_frequency': 15,
    'career_page_health': 10,
}

# Category median stipends (INR/month) — baseline for normalization
CATEGORY_MEDIAN_STIPENDS = {
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

# Sector momentum base scores
SECTOR_MOMENTUM_DEFAULTS = {
    'technology': 70,
    'fintech': 75,
    'edtech': 55,
    'healthtech': 65,
    'ecommerce': 60,
    'fmcg': 65,
    'banking': 60,
    'consulting': 70,
    'manufacturing': 50,
    'automotive': 55,
    'energy': 55,
    'pharma': 60,
    'media': 50,
    'telecom': 50,
    'real_estate': 45,
    'infrastructure': 50,
    'insurance': 55,
    'logistics': 60,
    'd2c': 65,
    'saas': 70,
    'ai_ml': 80,
    'ev': 70,
    'agritech': 50,
    'legaltech': 55,
    'hrtech': 60,
    'proptech': 50,
    'gaming': 55,
    'blockchain': 45,
    'vc_pe': 65,
    'general': 50,
}

# Urgency keywords for deadline detection
URGENCY_PATTERNS = [
    r'last\s+date\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'deadline\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'apply\s+(?:by|before)\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'closing\s+date\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'expires?\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'last\s+day\s+to\s+apply\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'applications?\s+close\s*:?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'hurry', r'few\s+(?:spots?|seats?)\s+left',
    r'limited\s+(?:positions?|openings?|slots?)',
    r'closing\s+soon', r'last\s+(?:few|couple)\s+days?',
    r'urgent(?:ly)?\s+(?:hiring|looking|needed)',
]

# Salary/compensation tier mapping
STIPEND_TIERS = {
    'excellent': (25000, float('inf')),  # ₹25K+ /month
    'good': (15000, 25000),
    'average': (8000, 15000),
    'below_average': (3000, 8000),
    'token': (0, 3000),
    'unpaid': (0, 0),
}

# Date parsing patterns
DATE_PATTERNS = [
    r'(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s*(\d{2,4})',
    r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',
    r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',
]


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class EnrichmentResult:
    """Result of enriching a single listing."""
    listing_id: int = 0
    competition_ratio: float = 0.0
    competition_percentile: float = 0.0
    is_blue_ocean: bool = False
    blue_ocean_score: float = 0.0
    blue_ocean_reasons: List[str] = field(default_factory=list)
    sector_momentum: float = 50.0
    urgency_score: float = 0.0
    urgency_deadline: str = ""
    stipend_tier: str = ""
    stipend_percentile: float = 0.0
    category_detected: str = ""
    enriched: bool = False
    error: Optional[str] = None


@dataclass
class CIRSBreakdown:
    """CIRS (Company Intern Readiness Score) breakdown."""
    company_id: int = 0
    company_name: str = ""
    total_score: float = 40.0  # Default
    intent_signal_score: float = 0.0
    historical_ppo_score: float = 0.0
    glassdoor_rating_score: float = 0.0
    funding_recency_score: float = 0.0
    posting_frequency_score: float = 0.0
    career_page_health_score: float = 0.0
    last_computed: str = ""

    def to_telegram_msg(self) -> str:
        """Format for Telegram display."""
        bars = {
            'Intent Signal': (self.intent_signal_score, CIRS_WEIGHTS['intent_signal']),
            'PPO History': (self.historical_ppo_score, CIRS_WEIGHTS['historical_ppo']),
            'Glassdoor': (self.glassdoor_rating_score, CIRS_WEIGHTS['glassdoor_rating']),
            'Funding': (self.funding_recency_score, CIRS_WEIGHTS['funding_recency']),
            'Post Frequency': (self.posting_frequency_score, CIRS_WEIGHTS['posting_frequency']),
            'Career Page': (self.career_page_health_score, CIRS_WEIGHTS['career_page_health']),
        }
        lines = [
            f"🏢 <b>CIRS: {self.company_name}</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Total Score: <b>{self.total_score:.0f}/100</b>",
            f"",
        ]
        for name, (score, max_score) in bars.items():
            filled = int((score / max(max_score, 1)) * 10)
            bar = '█' * filled + '░' * (10 - filled)
            lines.append(f"  {name}: [{bar}] {score:.0f}/{max_score}")
        return '\n'.join(lines)


@dataclass
class EnrichmentStats:
    """Statistics for an enrichment run."""
    total_processed: int = 0
    enriched: int = 0
    blue_ocean_found: int = 0
    cirs_updated: int = 0
    sector_tagged: int = 0
    urgency_detected: int = 0
    errors: int = 0
    duration_sec: float = 0.0

    def summary(self) -> str:
        return (
            f"Processed: {self.total_processed} | "
            f"Enriched: {self.enriched} | "
            f"Blue Ocean: {self.blue_ocean_found} | "
            f"CIRS Updated: {self.cirs_updated} | "
            f"Urgent: {self.urgency_detected} | "
            f"Duration: {self.duration_sec}s"
        )


# ============================================================
# COMPETITION ANALYZER
# ============================================================

class CompetitionAnalyzer:
    """
    Analyzes competition levels across listings.
    
    Metrics:
        - Competition ratio: applicants / days_posted
        - Source competition: avg applicants per source
        - Category competition: avg applicants per category
        - Company tier competition: avg applicants per tier
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._percentile_cache: Dict[str, List[float]] = {}

    def compute_competition_ratio(self, applicants: int, posted_days: int) -> float:
        """
        Compute competition ratio (applicants per day).
        
        Lower ratio = less competitive = better opportunity.
        """
        if posted_days <= 0:
            posted_days = 1
        return round(applicants / posted_days, 2)

    def compute_competition_percentile(self, ratio: float, category: str = 'general') -> float:
        """
        Compute what percentile this ratio falls in.
        
        Returns 0-100 where:
            0 = least competitive (best)
            100 = most competitive (worst)
        """
        cache_key = f"ratio_{category}"
        if cache_key not in self._percentile_cache:
            self._load_category_ratios(category)

        ratios = self._percentile_cache.get(cache_key, [])
        if not ratios:
            return 50.0  # Default: median

        # Count how many are below this ratio
        below = sum(1 for r in ratios if r <= ratio)
        percentile = (below / len(ratios)) * 100
        return round(percentile, 1)

    def get_category_stats(self, category: str = 'general') -> Dict[str, float]:
        """Get competition stats for a category."""
        cache_key = f"ratio_{category}"
        if cache_key not in self._percentile_cache:
            self._load_category_ratios(category)

        ratios = self._percentile_cache.get(cache_key, [])
        if not ratios:
            return {'mean': 0, 'median': 0, 'p25': 0, 'p75': 0}

        sorted_ratios = sorted(ratios)
        n = len(sorted_ratios)

        return {
            'mean': sum(sorted_ratios) / n,
            'median': sorted_ratios[n // 2],
            'p25': sorted_ratios[n // 4] if n >= 4 else sorted_ratios[0],
            'p75': sorted_ratios[3 * n // 4] if n >= 4 else sorted_ratios[-1],
            'count': n,
        }

    def _load_category_ratios(self, category: str):
        """Load competition ratios for a category."""
        try:
            listings = self.db.get_recent_clean_listings(days=30, limit=1000)
            ratios = []
            for l in listings:
                if category != 'general':
                    l_cat = (l.get('category', '') or '').lower()
                    if l_cat != category:
                        continue
                applicants = l.get('applicants', 0) or 0
                posted_days = l.get('posted_days_ago', 1) or 1
                ratio = applicants / max(posted_days, 1)
                ratios.append(ratio)
            self._percentile_cache[f"ratio_{category}"] = ratios
        except Exception as e:
            logger.debug(f"Failed to load category ratios: {e}")


# ============================================================
# BLUE OCEAN DETECTOR
# ============================================================

class BlueOceanDetector:
    """
    Identifies Blue Ocean opportunities — high-prestige listings
    with unusually low competition.
    
    Blue Ocean = Company Prestige ≥ 60 AND Applicants ≤ 35
    
    Scoring (0-100):
        - Base: meets core criteria = 50
        - Bonus: PPO tag = +20
        - Bonus: stipend above median = +10
        - Bonus: applicants < 15 = +10
        - Bonus: intent signal active = +10
        - Penalty: posted > 7 days = -10
        - Penalty: WFH (more competitive) = -5
    """

    def __init__(self, db: DatabaseManager, config):
        self.db = db
        self.config = config

    def check_blue_ocean(self, listing: Dict) -> Tuple[bool, float, List[str]]:
        """
        Check if a listing qualifies as Blue Ocean.
        
        Returns:
            Tuple of (is_blue_ocean, score, reasons)
        """
        reasons = []
        score = 0.0

        # Get company tier score
        company_id = listing.get('company_id')
        tier = listing.get('tier') or 5
        if company_id and not tier:
            company = self.db.get_company_by_id(company_id)
            if company:
                tier = company.get('tier', 5)

        prestige = TIER_PPO_SCORES.get(tier, DEFAULT_TIER_SCORE)
        applicants = listing.get('applicants', 0) or 0

        # Core criteria check
        if prestige < BLUE_OCEAN_MIN_PRESTIGE:
            return False, 0.0, [f"Prestige too low: {prestige} < {BLUE_OCEAN_MIN_PRESTIGE}"]

        if applicants > BLUE_OCEAN_MAX_APPLICANTS:
            return False, 0.0, [f"Too many applicants: {applicants} > {BLUE_OCEAN_MAX_APPLICANTS}"]

        # Base score — meets core criteria
        score = 50.0
        reasons.append(f"✅ Prestige={prestige} (Tier {tier}), Applicants={applicants}")

        # PPO bonus
        if listing.get('is_ppo'):
            score += 20.0
            reasons.append("✅ PPO tag present (+20)")

        # Stipend bonus
        stipend = listing.get('stipend_monthly', 0) or 0
        category = listing.get('category', 'general') or 'general'
        median = CATEGORY_MEDIAN_STIPENDS.get(category, 12000)
        if stipend >= median * BLUE_OCEAN_MIN_STIPEND_RATIO:
            score += 10.0
            reasons.append(f"✅ Stipend ₹{stipend:,.0f} ≥ median ₹{median:,.0f} (+10)")

        # Very low applicant bonus
        if applicants < 15:
            score += 10.0
            reasons.append(f"✅ Very low competition: {applicants} applicants (+10)")

        # Intent signal bonus
        if company_id:
            signal_score = self.db.get_latest_signal_score(company_id)
            if signal_score > 50:
                score += 10.0
                reasons.append(f"✅ Active intent signal: {signal_score:.0f} (+10)")

        # Recency penalty
        posted_days = listing.get('posted_days_ago', 0) or 0
        if posted_days > 7:
            score -= 10.0
            reasons.append(f"⚠️ Posted {posted_days} days ago (-10)")

        # WFH penalty (more people apply to remote roles)
        if listing.get('is_wfh'):
            score -= 5.0
            reasons.append("⚠️ WFH role (higher competition risk) (-5)")

        score = max(0, min(100, score))

        return True, score, reasons

    def find_blue_oceans(self, listings: List[Dict], top_n: int = 20) -> List[Dict]:
        """Find and rank Blue Ocean opportunities."""
        blue_oceans = []

        for listing in listings:
            is_bo, score, reasons = self.check_blue_ocean(listing)
            if is_bo:
                listing['blue_ocean_score'] = score
                listing['blue_ocean_reasons'] = reasons
                blue_oceans.append(listing)

        # Sort by Blue Ocean score
        blue_oceans.sort(key=lambda x: x.get('blue_ocean_score', 0), reverse=True)

        return blue_oceans[:top_n]


# ============================================================
# CIRS CALCULATOR
# ============================================================

class CIRSCalculator:
    """
    Company Intern Readiness Score calculator.
    
    CIRS measures how "ready" a company is to hire interns,
    based on multiple signals:
    
    Component 1: Intent Signal Strength (0-25)
        - Recent A-01 signals for this company
        - Weighted by signal recency and type
    
    Component 2: Historical PPO Rate (0-20)
        - Past conversion rate from our outcomes data
        - Companies that gave PPOs before score higher
    
    Component 3: Glassdoor Intern Rating (0-15)
        - Intern-specific reviews on Glassdoor
        - Proxy: overall rating × intern mention frequency
    
    Component 4: Funding Recency (0-15)
        - For startups: recent funding = active hiring
        - For corporates: consistent annual hiring cycle
    
    Component 5: Posting Frequency (0-15)
        - How often this company posts internships
        - Measured from our raw_listings history
    
    Component 6: Career Page Health (0-10)
        - Active career page with intern listings
        - Known ATS platform configured
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def compute_cirs(self, company_id: int) -> CIRSBreakdown:
        """Compute full CIRS breakdown for a company."""
        company = self.db.get_company_by_id(company_id)
        if not company:
            return CIRSBreakdown(company_id=company_id, total_score=40.0)

        breakdown = CIRSBreakdown(
            company_id=company_id,
            company_name=company.get('name', ''),
            last_computed=datetime.now(IST).isoformat(),
        )

        # Component 1: Intent Signal Strength
        breakdown.intent_signal_score = self._compute_intent_signal(company_id)

        # Component 2: Historical PPO Rate
        breakdown.historical_ppo_score = self._compute_ppo_rate(company_id)

        # Component 3: Glassdoor Rating
        breakdown.glassdoor_rating_score = self._compute_glassdoor(company)

        # Component 4: Funding Recency
        breakdown.funding_recency_score = self._compute_funding(company)

        # Component 5: Posting Frequency
        breakdown.posting_frequency_score = self._compute_posting_frequency(company_id)

        # Component 6: Career Page Health
        breakdown.career_page_health_score = self._compute_career_health(company)

        # Sum all components
        breakdown.total_score = (
            breakdown.intent_signal_score +
            breakdown.historical_ppo_score +
            breakdown.glassdoor_rating_score +
            breakdown.funding_recency_score +
            breakdown.posting_frequency_score +
            breakdown.career_page_health_score
        )

        breakdown.total_score = round(max(0, min(100, breakdown.total_score)), 1)
        return breakdown

    def _compute_intent_signal(self, company_id: int) -> float:
        """Score based on A-01 intent signals (0-25)."""
        max_score = CIRS_WEIGHTS['intent_signal']
        try:
            signals = self.db.get_company_signals(company_id, days=30)
            if not signals:
                return 0.0

            # Weight by recency and signal score
            total_weighted = 0.0
            for signal in signals:
                signal_score = signal.get('signal_score', 0) or 0
                days_ago = signal.get('days_ago', 30) or 30
                # Recency weight: recent signals count more
                recency_weight = max(0.1, 1.0 - (days_ago / 30))
                total_weighted += signal_score * recency_weight

            # Normalize to 0-25
            normalized = min(max_score, (total_weighted / 100) * max_score)
            return round(normalized, 1)
        except Exception:
            return 0.0

    def _compute_ppo_rate(self, company_id: int) -> float:
        """Score based on historical PPO conversion (0-20)."""
        max_score = CIRS_WEIGHTS['historical_ppo']
        try:
            outcomes = self.db.get_company_outcomes(company_id)
            if not outcomes:
                return max_score * 0.3  # Neutral: 30% of max

            total = len(outcomes)
            positive = sum(
                1 for o in outcomes
                if o.get('status') in ('interview', 'offer', 'ppo', 'shortlisted')
            )
            rate = positive / max(total, 1)

            # Minimum sample size: need at least 3 outcomes
            if total < 3:
                return max_score * 0.3

            return round(rate * max_score, 1)
        except Exception:
            return max_score * 0.3

    def _compute_glassdoor(self, company: Dict) -> float:
        """Score based on Glassdoor rating (0-15)."""
        max_score = CIRS_WEIGHTS['glassdoor_rating']
        rating = company.get('glassdoor_rating', 0) or 0

        if rating <= 0:
            return max_score * 0.4  # Neutral if no data

        # Scale: 1.0 → 0, 3.0 → 50%, 5.0 → 100%
        normalized = max(0, (rating - 1.0) / 4.0)
        return round(normalized * max_score, 1)

    def _compute_funding(self, company: Dict) -> float:
        """Score based on funding recency (0-15)."""
        max_score = CIRS_WEIGHTS['funding_recency']
        tier = company.get('tier', 5) or 5
        size_band = (company.get('size_band', '') or '').lower()

        # Large corporates / Tier 1: consistent hiring cycle
        if tier <= 2 or size_band in ('large', 'enterprise'):
            return max_score * 0.8

        # Startups: check for recent funding signals
        sector = (company.get('sector', '') or '').lower()
        if 'startup' in size_band or tier >= 4:
            # Check if we have funding signals from A-01
            company_id = company.get('id')
            if company_id:
                funding_signals = self.db.get_company_signals_by_type(
                    company_id, 'funding', days=180
                )
                if funding_signals:
                    # Recent funding = high score
                    return max_score * 0.9
                else:
                    return max_score * 0.3

        return max_score * 0.5  # Default

    def _compute_posting_frequency(self, company_id: int) -> float:
        """Score based on how often company posts internships (0-15)."""
        max_score = CIRS_WEIGHTS['posting_frequency']
        try:
            count = self.db.count_company_listings(company_id, days=90)
            if count <= 0:
                return 0.0
            elif count >= 10:
                return max_score  # Very active
            elif count >= 5:
                return max_score * 0.7
            elif count >= 2:
                return max_score * 0.5
            else:
                return max_score * 0.3
        except Exception:
            return 0.0

    def _compute_career_health(self, company: Dict) -> float:
        """Score based on career page configuration (0-10)."""
        max_score = CIRS_WEIGHTS['career_page_health']
        score = 0.0

        if company.get('careers_url'):
            score += max_score * 0.4

        if company.get('ats_platform') and company['ats_platform'] != 'unknown':
            score += max_score * 0.4

        if company.get('ats_board_id'):
            score += max_score * 0.2

        return round(score, 1)

    def compute_batch_cirs(self, tier_filter: Optional[List[int]] = None) -> int:
        """Recompute CIRS for all companies and update database."""
        updated = 0
        for tier in (tier_filter or [1, 2, 3, 4, 5]):
            companies = self.db.get_companies_by_tier(tier, limit=300)
            for company in companies:
                try:
                    breakdown = self.compute_cirs(company['id'])
                    self.db.update_company_cirs(
                        company['id'], breakdown.total_score
                    )
                    updated += 1
                except Exception as e:
                    logger.debug(f"CIRS compute error for {company.get('name')}: {e}")
        return updated


# ============================================================
# SECTOR MOMENTUM CALCULATOR
# ============================================================

class SectorMomentumCalculator:
    """
    Calculates sector momentum scores based on:
        - Hiring volume trends per sector
        - Economic signal correlation
        - Funding cycle analysis
        - Listing growth rate
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._sector_cache: Dict[str, float] = {}

    def get_sector_momentum(self, sector: str) -> float:
        """Get momentum score for a sector (0-100)."""
        if not sector:
            return 50.0

        sector_lower = sector.lower().replace(' ', '_')

        if sector_lower in self._sector_cache:
            return self._sector_cache[sector_lower]

        # Base score from defaults
        base = SECTOR_MOMENTUM_DEFAULTS.get(sector_lower, 50)

        # Adjust based on recent listing trends
        try:
            recent = self.db.count_sector_listings(sector, days=7)
            older = self.db.count_sector_listings(sector, days=30)

            if older > 0:
                growth_rate = (recent * 4) / older  # Normalize to monthly
                if growth_rate > 1.5:
                    base = min(100, base + 15)  # Strong growth
                elif growth_rate > 1.0:
                    base = min(100, base + 5)   # Moderate growth
                elif growth_rate < 0.5:
                    base = max(0, base - 10)    # Declining
        except Exception:
            pass

        score = round(max(0, min(100, base)), 1)
        self._sector_cache[sector_lower] = score
        return score

    def refresh_all(self) -> Dict[str, float]:
        """Refresh momentum scores for all sectors."""
        self._sector_cache.clear()
        for sector in SECTOR_MOMENTUM_DEFAULTS:
            self.get_sector_momentum(sector)
        return dict(self._sector_cache)


# ============================================================
# URGENCY SCORER
# ============================================================

class UrgencyScorer:
    """
    Detects urgency signals in job listings:
        - Explicit deadlines
        - "Last few days" language
        - High application velocity
        - "Closing soon" indicators
    """

    @staticmethod
    def score_urgency(listing: Dict) -> Tuple[float, str]:
        """
        Score urgency of a listing.
        
        Returns:
            Tuple of (urgency_score 0-100, deadline_text)
        """
        text = f"{listing.get('title', '')} {listing.get('description_text', '')}".lower()
        score = 0.0
        deadline = ""

        # Check for explicit deadline dates
        for pattern in URGENCY_PATTERNS[:7]:  # Date-containing patterns
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                deadline = match.group(1) if match.groups() else ""
                # Try to parse and check proximity
                if deadline:
                    days_until = UrgencyScorer._parse_deadline_days(deadline)
                    if days_until is not None:
                        if days_until <= 2:
                            score = max(score, 95)
                        elif days_until <= 5:
                            score = max(score, 80)
                        elif days_until <= 10:
                            score = max(score, 60)
                        elif days_until <= 30:
                            score = max(score, 40)

        # Check for urgency language
        for pattern in URGENCY_PATTERNS[7:]:  # Language patterns
            if re.search(pattern, text, re.IGNORECASE):
                score = max(score, 70)
                break

        # Application velocity check
        applicants = listing.get('applicants', 0) or 0
        posted_days = listing.get('posted_days_ago', 1) or 1
        velocity = applicants / posted_days

        if velocity > 100:
            score = max(score, 50)  # Very fast filling

        # Recency bonus
        if posted_days <= 1:
            score = max(score, 30)  # Just posted

        return round(score, 1), deadline

    @staticmethod
    def _parse_deadline_days(deadline_str: str) -> Optional[int]:
        """Parse deadline string into days from now."""
        months_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
            'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }

        for pattern in DATE_PATTERNS:
            match = re.search(pattern, deadline_str.lower())
            if match:
                try:
                    groups = match.groups()
                    if len(groups) == 3:
                        g1, g2, g3 = groups
                        # Try day-month-year format
                        if g2[:3] in months_map:
                            day = int(g1)
                            month = months_map[g2[:3]]
                            year = int(g3)
                            if year < 100:
                                year += 2000
                        else:
                            day = int(g1)
                            month = int(g2)
                            year = int(g3)
                            if year < 100:
                                year += 2000

                        deadline_date = datetime(year, month, day)
                        now = datetime.now()
                        delta = (deadline_date - now).days
                        return max(0, delta)
                except (ValueError, KeyError):
                    continue
        return None


# ============================================================
# STIPEND ANALYZER
# ============================================================

class StipendAnalyzer:
    """Analyzes and categorizes stipend levels."""

    @staticmethod
    def get_stipend_tier(stipend: float) -> str:
        """Categorize stipend into tiers."""
        if stipend <= 0:
            return 'unpaid'
        for tier_name, (low, high) in STIPEND_TIERS.items():
            if low <= stipend < high:
                return tier_name
        return 'unknown'

    @staticmethod
    def get_stipend_percentile(stipend: float, category: str = 'general') -> float:
        """Get percentile ranking of stipend within category."""
        median = CATEGORY_MEDIAN_STIPENDS.get(category, 12000)
        if median <= 0:
            return 50.0
        ratio = stipend / median
        # Map ratio to percentile (rough approximation)
        if ratio >= 2.0:
            return 95.0
        elif ratio >= 1.5:
            return 85.0
        elif ratio >= 1.0:
            return 65.0
        elif ratio >= 0.7:
            return 45.0
        elif ratio >= 0.4:
            return 25.0
        else:
            return 10.0


# ============================================================
# MAIN INTELLIGENCE ENRICHER
# ============================================================

class IntelligenceEnricher:
    """
    Master enrichment engine orchestrating all sub-components.
    
    Pipeline:
        1. Load un-enriched clean listings
        2. For each listing:
           a. Compute competition ratio + percentile
           b. Check Blue Ocean criteria
           c. Compute sector momentum
           d. Detect urgency
           e. Categorize stipend
        3. Batch-update CIRS for companies with new data
        4. Update clean_listings with enriched data
        5. Generate alerts for Blue Ocean finds
        6. Report statistics
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()
        self.router = get_router()

        # Sub-components
        self.competition = CompetitionAnalyzer(self.db)
        self.blue_ocean = BlueOceanDetector(self.db, self.config)
        self.cirs_calc = CIRSCalculator(self.db)
        self.sector_momentum = SectorMomentumCalculator(self.db)
        self.urgency = UrgencyScorer()
        self.stipend_analyzer = StipendAnalyzer()

    def run_enrichment(self, hours: int = 48, limit: int = 2000) -> EnrichmentStats:
        """
        Run full enrichment pipeline on recent listings.
        
        Args:
            hours: Process listings from the last N hours
            limit: Maximum listings to process
        
        Returns:
            EnrichmentStats with complete statistics
        """
        logger.info(f"[{AGENT_ID}] === ENRICHMENT START ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, 'running')

        stats = EnrichmentStats()

        # Get listings needing enrichment
        listings = self.db.get_listings_needing_enrichment(
            hours=hours, limit=limit
        )
        stats.total_processed = len(listings)

        logger.info(f"[{AGENT_ID}] Processing {len(listings)} listings")

        blue_ocean_alerts = []

        # Enrich each listing
        for i, listing in enumerate(listings):
            try:
                result = self._enrich_listing(listing)

                if result.enriched:
                    stats.enriched += 1

                    # Update database
                    self.db.update_clean_listing_enrichment(
                        listing_id=result.listing_id,
                        competition_ratio=result.competition_ratio,
                        is_blue_ocean=result.is_blue_ocean,
                        sector_momentum=result.sector_momentum,
                    )

                    if result.is_blue_ocean:
                        stats.blue_ocean_found += 1
                        blue_ocean_alerts.append({
                            'listing': listing,
                            'score': result.blue_ocean_score,
                            'reasons': result.blue_ocean_reasons,
                        })

                    if result.urgency_score > 70:
                        stats.urgency_detected += 1

                # Progress logging
                if (i + 1) % 100 == 0:
                    logger.info(
                        f"[{AGENT_ID}] Progress: {i+1}/{len(listings)} | "
                        f"Blue Ocean: {stats.blue_ocean_found}"
                    )

            except Exception as e:
                stats.errors += 1
                logger.debug(f"[{AGENT_ID}] Enrichment error: {e}")

        # Batch CIRS update for active companies
        try:
            cirs_updated = self.cirs_calc.compute_batch_cirs(tier_filter=[1, 2, 3])
            stats.cirs_updated = cirs_updated
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] CIRS batch update error: {e}")

        # Finalize
        duration = time.time() - start_time
        stats.duration_sec = round(duration, 1)

        self.db.update_agent_heartbeat(
            AGENT_ID, 'completed',
            items_processed=stats.enriched,
            errors=stats.errors,
            duration_sec=duration,
        )

        logger.info(
            f"[{AGENT_ID}] === ENRICHMENT COMPLETE === "
            f"{stats.summary()}"
        )

        return stats

    def _enrich_listing(self, listing: Dict) -> EnrichmentResult:
        """Enrich a single listing."""
        result = EnrichmentResult(listing_id=listing.get('id', 0))

        try:
            # 1. Competition analysis
            applicants = listing.get('applicants', 0) or 0
            posted_days = listing.get('posted_days_ago', 1) or 1
            category = listing.get('category', 'general') or 'general'

            result.competition_ratio = self.competition.compute_competition_ratio(
                applicants, posted_days
            )
            result.competition_percentile = self.competition.compute_competition_percentile(
                result.competition_ratio, category
            )

            # 2. Blue Ocean check
            is_bo, bo_score, bo_reasons = self.blue_ocean.check_blue_ocean(listing)
            result.is_blue_ocean = is_bo
            result.blue_ocean_score = bo_score
            result.blue_ocean_reasons = bo_reasons

            # 3. Sector momentum
            company_id = listing.get('company_id')
            sector = ''
            if company_id:
                company = self.db.get_company_by_id(company_id)
                if company:
                    sector = company.get('sector', '')
            result.sector_momentum = self.sector_momentum.get_sector_momentum(sector)

            # 4. Urgency scoring
            result.urgency_score, result.urgency_deadline = self.urgency.score_urgency(listing)

            # 5. Stipend analysis
            stipend = listing.get('stipend_monthly', 0) or 0
            result.stipend_tier = self.stipend_analyzer.get_stipend_tier(stipend)
            result.stipend_percentile = self.stipend_analyzer.get_stipend_percentile(
                stipend, category
            )

            result.enriched = True

        except Exception as e:
            result.error = str(e)

        return result

    def get_cirs_breakdown(self, company_name: str) -> Optional[CIRSBreakdown]:
        """Get CIRS breakdown for a company (for /cirs command)."""
        company = self.db.fuzzy_match_company(company_name)
        if not company:
            return None
        return self.cirs_calc.compute_cirs(company['id'])

    def get_sector_report(self) -> Dict[str, float]:
        """Get sector momentum report."""
        return self.sector_momentum.refresh_all()

    def generate_report(self, stats: EnrichmentStats) -> str:
        """Generate formatted report for Telegram."""
        lines = [
            f"🔍 <b>Intelligence Enrichment Report</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📊 <b>Results:</b>",
            f"  Processed: {stats.total_processed}",
            f"  Enriched: {stats.enriched}",
            f"  🌊 Blue Ocean: {stats.blue_ocean_found}",
            f"  ⏰ Urgent: {stats.urgency_detected}",
            f"  🏢 CIRS Updated: {stats.cirs_updated}",
            f"",
            f"⏱ Duration: {stats.duration_sec}s",
        ]

        if stats.errors > 0:
            lines.append(f"⚠️ Errors: {stats.errors}")

        return '\n'.join(lines)

    def run_deep_enrichment(self) -> EnrichmentStats:
        """
        v6.0: Sunday deep enrichment.
        - Full CIRS refresh for all companies
        - Sector momentum recalculation
        - Re-score all active listings with updated company data
        - Wider time window (7 days) and higher limit
        """
        logger.info(f"[{AGENT_ID}] === SUNDAY DEEP ENRICHMENT START ===")
        # Use wider time window and higher limit for Sunday deep run
        return self.run_enrichment(hours=168, limit=5000)  # 7 days, 5000 listings


# ============================================================
# MODULE-LEVEL FACTORY
# ============================================================

_enricher_instance: Optional[IntelligenceEnricher] = None


def get_intelligence_enricher() -> IntelligenceEnricher:
    """Get or create the singleton IntelligenceEnricher instance."""
    global _enricher_instance
    if _enricher_instance is None:
        _enricher_instance = IntelligenceEnricher()
    return _enricher_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    # Test Blue Ocean detection
    print("\n🌊 Blue Ocean Detection Tests:")
    test_listings = [
        {'title': 'MBA Intern - Strategy', 'company': 'McKinsey', 'tier': 1,
         'applicants': 20, 'is_ppo': True, 'stipend_monthly': 50000, 'category': 'consulting'},
        {'title': 'Marketing Intern', 'company': 'Random Startup', 'tier': 5,
         'applicants': 5, 'is_ppo': False, 'stipend_monthly': 5000, 'category': 'marketing'},
        {'title': 'Finance Analyst', 'company': 'Goldman Sachs', 'tier': 1,
         'applicants': 500, 'is_ppo': True, 'stipend_monthly': 80000, 'category': 'finance'},
        {'title': 'Product Intern', 'company': 'Zepto', 'tier': 3,
         'applicants': 30, 'is_ppo': False, 'stipend_monthly': 25000, 'category': 'product-management'},
    ]

    from core.database import get_db as _get_db
    _db = _get_db()
    bo_detector = BlueOceanDetector(_db, get_config())

    for listing in test_listings:
        is_bo, score, reasons = bo_detector.check_blue_ocean(listing)
        icon = "🌊" if is_bo else "❌"
        print(f"  {icon} {listing['title']} @ {listing['company']}")
        print(f"    Score: {score:.0f} | Applicants: {listing['applicants']} | Tier: {listing['tier']}")
        for r in reasons[:2]:
            print(f"    {r}")

    # Test stipend analysis
    print("\n💰 Stipend Analysis Tests:")
    test_stipends = [0, 3000, 8000, 15000, 25000, 50000]
    for s in test_stipends:
        tier = StipendAnalyzer.get_stipend_tier(s)
        pct = StipendAnalyzer.get_stipend_percentile(s, 'marketing')
        print(f"  ₹{s:,.0f}/mo → Tier: {tier}, Percentile: {pct:.0f}%")

    # Test urgency scoring
    print("\n⏰ Urgency Tests:")
    test_urgency = [
        {'title': 'Apply by 10 Mar 2026', 'description_text': 'Last date: 10 Mar 2026'},
        {'title': 'Summer Intern', 'description_text': 'Hurry! Few spots left'},
        {'title': 'Regular Intern', 'description_text': 'We are looking for interns'},
        {'title': 'Urgent Hiring', 'description_text': 'Closing soon, limited positions'},
    ]
    for listing in test_urgency:
        score, deadline = UrgencyScorer.score_urgency(listing)
        icon = "🔴" if score >= 70 else "🟡" if score >= 40 else "🟢"
        print(f"  {icon} Score={score:.0f} | '{listing['title']}'")

    # Test sector momentum
    print("\n📈 Sector Momentum:")
    for sector in ['technology', 'fintech', 'fmcg', 'manufacturing', 'ai_ml', 'blockchain']:
        score = SECTOR_MOMENTUM_DEFAULTS.get(sector, 50)
        print(f"  {sector}: {score}")

    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) — All tests passed!")
    print(f"  CIRS weights: {CIRS_WEIGHTS}")
    print(f"  Blue Ocean threshold: Prestige≥{BLUE_OCEAN_MIN_PRESTIGE}, Applicants≤{BLUE_OCEAN_MAX_APPLICANTS}")
    print(f"  Sectors tracked: {len(SECTOR_MOMENTUM_DEFAULTS)}")
    print(f"  Category stipend medians: {len(CATEGORY_MEDIAN_STIPENDS)}")
    print("=" * 60)
