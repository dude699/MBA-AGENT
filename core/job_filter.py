"""
============================================================
SMART JOB RELEVANCE FILTER
============================================================
ML-inspired scoring system that determines whether a job listing
is relevant for an MBA intern vs. a sales/cold-calling role.

Uses multi-signal scoring:
  1. Title keyword matching (positive + negative)
  2. Role type classification
  3. Description analysis
  4. Company context
  5. Stipend/duration reasonability check

NOT hardcoded — uses weighted scoring so borderline roles
(e.g. "Business Development Intern" at a T1 company) can
still pass if other signals are strong.
============================================================
"""

import re
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================
# NEGATIVE SIGNALS — Roles we DON'T want
# ============================================================

# Hard-reject: these titles are NEVER relevant
# ANY form of sales / business development is auto-rejected
HARD_REJECT_TITLES = [
    # ===== ALL SALES ROLES (zero tolerance) =====
    r'\bsales\b',                                   # ANY title with 'sales'
    r'\b(tele\s*sales|tele\s*caller|tele\s*marketing)\b',
    r'\b(cold\s*call|door[\s-]to[\s-]door)\b',
    r'\b(field\s*sales|direct\s*sales|channel\s*sales)\b',
    r'\b(inside\s*sales|outside\s*sales)\b',
    r'\b(area\s*sales|territory\s*sales)\b',
    r'\b(sales\s*executive|sales\s*officer|sales\s*associate)\b',
    r'\b(sales\s*representative|sales\s*rep|sales\s*manager)\b',
    r'\b(sales\s*intern|sales\s*trainee)\b',
    r'\b(b2b\s*sales|b2c\s*sales)\b',
    # ===== ALL BUSINESS DEVELOPMENT ROLES (zero tolerance) =====
    r'\bbusiness\s*development\b',                   # ANY title with 'business development'
    r'\b(bde|bdm|bda)\b',                           # BDE/BDM/BDA abbreviations
    r'\b(bd\s*intern|bd\s*executive|bd\s*manager|bd\s*associate)\b',
    # ===== INSURANCE / REAL ESTATE =====
    r'\b(insurance\s*(?:agent|advisor|consultant|sales|intern))\b',
    r'\b(real\s*estate\s*(?:agent|sales|broker|intern))\b',
    # ===== COMMISSION / TARGET BASED =====
    r'\b(commission[\s-]based|commission\s*only)\b',
    r'\b(target[\s-]based\s*sales|incentive[\s-]based)\b',
    # ===== WALK-IN / CALL CENTER =====
    r'\b(walk[\s-]in|walkin)\b',
    r'\b(call\s*center|bpo|kpo)\b',
    # ===== MLM / FREELANCE SALES =====
    r'\b(mlm|network\s*marketing|direct\s*selling)\b',
    r'\b(freelance\s*sales)\b',
    # ===== NON-MBA ROLES =====
    r'\b(data\s*entry|typing\s*job)\b',
    r'\b(content\s*writer|blog\s*writer|article\s*writer)\b',
    r'\b(graphic\s*design(?:er)?)\b',
    r'\b(web\s*develop(?:er|ment))\b',
    r'\b(software\s*(?:engineer|developer))\b',
    r'\b(full[\s-]stack|front[\s-]end|back[\s-]end)\b',
    # ===== LEAD GENERATION / CLIENT ACQUISITION =====
    r'\b(lead\s*generation\s*(?:intern|executive|manager))\b',
    r'\b(client\s*acquisition\s*(?:intern|executive|manager))\b',
    r'\b(customer\s*acquisition\s*(?:intern|executive|manager))\b',
    r'\b(revenue\s*generation)\b',
]

# Soft-negative: these reduce score but don't auto-reject
# NOTE: 'sales' and 'business development' are now HARD-REJECTED
# These handle subtler negative signals in descriptions
SOFT_NEGATIVE_KEYWORDS = {
    'selling': -20,
    'revenue target': -20,
    'cold calling': -30,
    'lead generation': -15,
    'client acquisition': -15,
    'outbound': -15,
    'inbound sales': -20,
    'field work': -12,
    'commission': -25,
    'incentive based': -20,
    'target based': -20,
    'customer acquisition': -15,
    'insurance': -15,
    'real estate': -15,
    'recruitment': -5,
    'placement': -3,
    'staffing': -8,
    'franchise': -10,
    'revenue generation': -15,
    'pitch': -8,
    'client meeting': -5,
    'prospect': -10,
    'quotation': -8,
}


# ============================================================
# POSITIVE SIGNALS — Roles we DO want
# ============================================================

# Strong MBA-relevant indicators
STRONG_POSITIVE_KEYWORDS = {
    # Core MBA functions
    'strategy': 20,
    'strategic': 18,
    'consulting': 20,
    'consultant': 18,
    'management consulting': 25,
    'financial analysis': 20,
    'financial modeling': 22,
    'investment banking': 25,
    'equity research': 22,
    'venture capital': 22,
    'private equity': 22,
    'corporate finance': 20,
    'brand management': 20,
    'product management': 22,
    'product manager': 20,
    'market research': 18,
    'consumer insights': 18,
    'category management': 18,
    'supply chain': 18,
    'operations management': 18,
    'process improvement': 15,
    'lean six sigma': 18,
    'digital marketing': 15,
    'growth marketing': 15,
    'performance marketing': 15,
    'marketing analytics': 18,
    'business analytics': 18,
    'data analytics': 15,
    'go-to-market': 18,
    'gtm': 15,
    'p&l': 20,
    'valuation': 20,
    'dcf': 18,
    'due diligence': 20,
    'market sizing': 18,
    'business case': 15,
    'competitive analysis': 15,
    'stakeholder management': 12,
}

# MBA role type indicators
MBA_ROLE_TYPES = {
    'intern': 15,
    'internship': 15,
    'trainee': 12,
    'management trainee': 20,
    'summer associate': 20,
    'summer analyst': 20,
    'fellow': 12,
    'associate': 8,
    'analyst': 8,
    'apprentice': 10,
    'graduate program': 18,
    'leadership program': 20,
    'rotational program': 20,
    'mba': 25,
    'fresher': 10,
    'campus': 12,
    'ppo': 15,
    'pre-placement': 15,
}

# Company tier boost (T1/T2 companies get benefit of doubt)
TIER_BOOST = {
    1: 25,  # Elite (McKinsey, Goldman, etc.)
    2: 15,  # Strong MNC
    3: 10,  # Indian Unicorn
    4: 5,   # Growing Startup
    5: 0,   # Niche
}


@dataclass
class FilterResult:
    """Result of the smart job filter."""
    is_relevant: bool
    score: float
    reason: str
    hard_rejected: bool = False
    signals: Dict[str, float] = None

    def __post_init__(self):
        if self.signals is None:
            self.signals = {}


def score_job_relevance(
    title: str,
    company: str = '',
    description: str = '',
    category: str = '',
    location: str = '',
    stipend: float = 0.0,
    company_tier: int = 5,
    source: str = '',
) -> FilterResult:
    """
    Score a job listing for MBA intern relevance.
    
    Returns FilterResult with:
      - is_relevant: True if score >= threshold
      - score: 0-100 composite relevance score
      - reason: Human-readable explanation
      - hard_rejected: True if auto-rejected by blocklist
    
    Scoring breakdown:
      - Title keywords: -30 to +25
      - Role type: 0 to +25
      - Description signals: -20 to +20
      - Company tier: 0 to +25
      - Category alignment: 0 to +10
      - Stipend reasonability: -5 to +5
    
    Threshold: 25 (on 0-100 scale)
    """
    title_lower = title.lower().strip()
    desc_lower = description.lower().strip() if description else ''
    full_text = f"{title_lower} {desc_lower}"
    signals = {}
    
    # ============================================================
    # STEP 1: Hard reject check
    # ============================================================
    for pattern in HARD_REJECT_TITLES:
        if re.search(pattern, title_lower):
            return FilterResult(
                is_relevant=False,
                score=0.0,
                reason=f"Hard-rejected: title matches '{pattern}'",
                hard_rejected=True,
                signals={'hard_reject': -100}
            )
    
    score = 50.0  # Start at neutral
    
    # ============================================================
    # STEP 2: Title keyword scoring
    # ============================================================
    title_score = 0.0
    
    # Check negative keywords in title
    for keyword, penalty in SOFT_NEGATIVE_KEYWORDS.items():
        if keyword in title_lower:
            title_score += penalty
            signals[f'title_neg:{keyword}'] = penalty
    
    # Check positive keywords in title
    for keyword, boost in STRONG_POSITIVE_KEYWORDS.items():
        if keyword in title_lower:
            title_score += boost
            signals[f'title_pos:{keyword}'] = boost
    
    score += max(-30, min(25, title_score))
    
    # ============================================================
    # STEP 3: Role type scoring
    # ============================================================
    role_score = 0.0
    for keyword, boost in MBA_ROLE_TYPES.items():
        if keyword in title_lower:
            role_score = max(role_score, boost)
            signals[f'role:{keyword}'] = boost
    
    score += min(25, role_score)
    
    # ============================================================
    # STEP 4: Description analysis (if available)
    # ============================================================
    if desc_lower:
        desc_score = 0.0
        
        # MBA-relevant description signals
        mba_desc_keywords = [
            'mba', 'business school', 'management program', 'pgdm',
            'case study', 'market research', 'competitive landscape',
            'financial model', 'valuation', 'strategy', 'consulting',
            'stakeholder', 'cross-functional', 'go-to-market',
            'brand', 'product launch', 'p&l', 'roi analysis',
        ]
        desc_positive_count = sum(1 for kw in mba_desc_keywords if kw in desc_lower)
        desc_score += min(15, desc_positive_count * 3)
        
        # Sales-heavy description signals
        sales_desc_keywords = [
            'cold call', 'door to door', 'field visit', 'lead generation target',
            'daily target', 'monthly target', 'revenue target',
            'commission structure', 'incentive structure',
            'customer walk-in', 'showroom',
        ]
        desc_negative_count = sum(1 for kw in sales_desc_keywords if kw in desc_lower)
        desc_score -= min(20, desc_negative_count * 5)
        
        score += max(-20, min(20, desc_score))
        signals['description_analysis'] = desc_score
    
    # ============================================================
    # STEP 5: Company tier boost
    # ============================================================
    tier_boost = TIER_BOOST.get(company_tier, 0)
    score += tier_boost
    if tier_boost > 0:
        signals[f'company_tier:{company_tier}'] = tier_boost
    
    # ============================================================
    # STEP 6: Category alignment
    # ============================================================
    good_categories = {
        'marketing', 'finance', 'strategy', 'consulting',
        'operations', 'product-management', 'analytics',
        'human-resources', 'supply-chain',
    }
    bad_categories = {
        'sales', 'telesales', 'insurance', 'real-estate',
        'business-development', 'business development',
    }
    
    if category:
        cat_lower = category.lower()
        if cat_lower in good_categories:
            score += 10
            signals['category_good'] = 10
        elif cat_lower in bad_categories:
            score -= 10
            signals['category_bad'] = -10
    
    # ============================================================
    # STEP 7: Stipend reasonability
    # ============================================================
    if stipend > 0:
        if stipend < 1000:  # Likely unpaid or suspiciously low
            score -= 3
            signals['stipend_low'] = -3
        elif 5000 <= stipend <= 100000:  # Reasonable intern stipend
            score += 5
            signals['stipend_reasonable'] = 5
    
    # ============================================================
    # STEP 8: REMOVED — "Business Development Intern" special case
    # ============================================================
    # ALL business development roles are now HARD-REJECTED at Step 1.
    # No exceptions, regardless of company tier or stipend.
    # This eliminates sales-disguised roles from ever appearing.
    
    # Clamp to 0-100
    final_score = max(0.0, min(100.0, score))
    
    # Threshold: 25 means we accept anything that's even somewhat MBA-relevant
    RELEVANCE_THRESHOLD = 25.0
    is_relevant = final_score >= RELEVANCE_THRESHOLD
    
    # Build reason
    top_signals = sorted(signals.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    reason_parts = [f"{k}={v:+.0f}" for k, v in top_signals]
    reason = f"Score {final_score:.1f}/100 ({'PASS' if is_relevant else 'FAIL'}): {', '.join(reason_parts)}"
    
    return FilterResult(
        is_relevant=is_relevant,
        score=final_score,
        reason=reason,
        hard_rejected=False,
        signals=signals,
    )


def batch_filter_listings(listings: list, company_tier_map: Dict[str, int] = None) -> Tuple[list, list]:
    """
    Filter a batch of raw listings.
    
    Args:
        listings: List of raw listing dicts
        company_tier_map: Optional map of company name -> tier
    
    Returns:
        (relevant, filtered) tuple of lists
    """
    if company_tier_map is None:
        company_tier_map = {}
    
    relevant = []
    filtered = []
    
    for listing in listings:
        company = listing.get('company', '')
        tier = company_tier_map.get(company.lower(), 5)
        
        result = score_job_relevance(
            title=listing.get('title', ''),
            company=company,
            description=listing.get('description_text', ''),
            category=listing.get('category', ''),
            location=listing.get('location', ''),
            stipend=listing.get('stipend_normalized', 0) or 0,
            company_tier=tier,
            source=listing.get('source', ''),
        )
        
        listing['_filter_result'] = result
        
        if result.is_relevant:
            relevant.append(listing)
        else:
            filtered.append(listing)
    
    return relevant, filtered
