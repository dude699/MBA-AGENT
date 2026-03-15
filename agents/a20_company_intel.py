"""
============================================================
PRISM v0.1 — A-20: DEEP COMPANY INTEL (GROQ COMPOUND RESEARCH)
============================================================
Agent A-20: Pre-application deep research using Groq Compound Beta.
Generates 500-word intel briefs with personalization hooks for
cover letters and outreach emails.

Schedule: Triggered 1 hour before A-13 auto-apply
Trigger: PPO > 75 listings in auto_apply_queue

Pipeline:
    1. Receive company name from auto_apply_queue
    2. Groq Compound Beta: web_search (company + "news" + "hiring")
    3. Groq Compound Beta: web_search (company + "stipend" + "intern review")
    4. Groq Compound Beta: web_search (company + "leadership" + "CEO")
    5. Groq Compound Beta: visit_url (company career page)
    6. Synthesize into 500-word Intel Brief
    7. Extract personalization hooks for cover letters
    8. Store in company_intel table
    9. Feed to A-18 (CV Enhancer) and A-15 (Email Applier)

AI Provider: Groq Compound Beta (deep_company_intel task)
Tools: Groq Compound web_search + visit_url (built-in)
Cost: $0 (Groq free tier)

Integration Points:
    - A-13 Auto Applier → triggers research before application
    - A-18 CV Enhancer → uses company hooks for CV tailoring
    - A-15 Email Applier → uses intel for email personalization
    - A-12 Telegram Reporter → /research command
============================================================
"""

import os
import sys
import json
import time
import asyncio
import hashlib
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-20"
AGENT_NAME = "Deep Company Intel"

MAX_RESEARCH_PER_DAY = 20  # Groq Compound quota conservation
INTEL_CACHE_TTL_HOURS = 168  # 7 days cache
MAX_INTEL_BRIEF_WORDS = 500


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class CompanyIntelBrief:
    """A complete company intelligence brief."""
    company: str
    sector: str = ""
    # Research results
    overview: str = ""
    recent_news: List[str] = field(default_factory=list)
    leadership: List[str] = field(default_factory=list)
    culture_notes: str = ""
    intern_reviews: str = ""
    stipend_range: str = ""
    hiring_signals: List[str] = field(default_factory=list)
    career_page_url: str = ""
    # Personalization hooks (for cover letters & emails)
    personalization_hooks: List[str] = field(default_factory=list)
    talking_points: List[str] = field(default_factory=list)
    # Meta
    researched_at: str = ""
    confidence: float = 0.0
    word_count: int = 0
    sources_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'company': self.company,
            'sector': self.sector,
            'overview': self.overview,
            'recent_news': self.recent_news,
            'leadership': self.leadership,
            'culture_notes': self.culture_notes,
            'intern_reviews': self.intern_reviews,
            'stipend_range': self.stipend_range,
            'hiring_signals': self.hiring_signals,
            'career_page_url': self.career_page_url,
            'personalization_hooks': self.personalization_hooks,
            'talking_points': self.talking_points,
            'researched_at': self.researched_at,
            'confidence': self.confidence,
            'word_count': self.word_count,
        }

    def get_full_brief(self) -> str:
        """Get the full intel brief as formatted text."""
        sections = []
        if self.overview:
            sections.append(f"OVERVIEW: {self.overview}")
        if self.recent_news:
            sections.append(f"RECENT NEWS: {'; '.join(self.recent_news[:3])}")
        if self.leadership:
            sections.append(f"LEADERSHIP: {', '.join(self.leadership[:5])}")
        if self.culture_notes:
            sections.append(f"CULTURE: {self.culture_notes}")
        if self.intern_reviews:
            sections.append(f"INTERN REVIEWS: {self.intern_reviews}")
        if self.stipend_range:
            sections.append(f"STIPEND: {self.stipend_range}")
        if self.hiring_signals:
            sections.append(f"HIRING SIGNALS: {'; '.join(self.hiring_signals[:3])}")
        if self.personalization_hooks:
            sections.append(f"HOOKS: {'; '.join(self.personalization_hooks[:3])}")
        return '\n'.join(sections)


@dataclass
class ResearchResult:
    """Result of a research operation."""
    success: bool
    company: str = ""
    brief: Optional[CompanyIntelBrief] = None
    cached: bool = False
    research_time_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'company': self.company,
            'cached': self.cached,
            'research_time_ms': round(self.research_time_ms, 1),
            'error': self.error,
            'word_count': self.brief.word_count if self.brief else 0,
        }


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class DeepCompanyIntel:
    """
    PRISM A-20: Deep Company Intel Agent.

    Uses Groq Compound Beta (agentic model with built-in web_search
    and visit_url) to generate comprehensive company research briefs
    with personalization hooks.

    Usage:
        intel = get_company_intel()
        result = await intel.research_company("McKinsey")
        brief = await intel.get_brief("McKinsey")
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
        self._agent_id = AGENT_ID
        self._agent_name = AGENT_NAME

        # Cache
        self._intel_cache: Dict[str, Tuple[CompanyIntelBrief, float]] = {}

        # Stats
        self._total_researched = 0
        self._total_cached_hits = 0
        self._total_failed = 0
        self._today_count = 0
        self._today_date = None

        logger.info(f"[{AGENT_ID}] {AGENT_NAME} initialized")

    # ----------------------------------------------------------
    # CACHE MANAGEMENT
    # ----------------------------------------------------------

    def _get_cached(self, company: str) -> Optional[CompanyIntelBrief]:
        """Get cached intel if available and not expired."""
        key = company.lower().strip()
        if key in self._intel_cache:
            brief, cached_time = self._intel_cache[key]
            age_hours = (time.time() - cached_time) / 3600
            if age_hours < INTEL_CACHE_TTL_HOURS:
                return brief
            else:
                del self._intel_cache[key]
        return None

    def _cache_intel(self, company: str, brief: CompanyIntelBrief):
        """Cache an intel brief."""
        key = company.lower().strip()
        self._intel_cache[key] = (brief, time.time())

    # ----------------------------------------------------------
    # GROQ COMPOUND RESEARCH
    # ----------------------------------------------------------

    async def _run_compound_research(self, company: str) -> Optional[Dict]:
        """
        Run Groq Compound Beta research with built-in web tools.
        The compound-beta model automatically uses web_search and
        visit_url tools when needed.
        """
        try:
            from core.ai_router import get_router
            router = get_router()

            prompt = f"""Research the company "{company}" for an MBA intern candidate in India.

Perform these research tasks:
1. Search for latest news about {company} (last 3 months)
2. Find {company}'s leadership team (CEO, HR Head, key executives)
3. Look for {company} intern reviews and stipend information
4. Check if {company} is currently hiring interns
5. Find {company}'s career page URL

Then synthesize a research brief with:
- Company overview (50 words)
- Recent developments (3 key items)
- Leadership team (top 5 names/titles)
- Culture & intern experience
- Stipend range for MBA interns
- Current hiring signals
- 3 personalization hooks for cover letter/email
- 3 talking points for interview

Respond in JSON:
{{
    "overview": "50-word overview",
    "recent_news": ["news1", "news2", "news3"],
    "leadership": ["Name - Title", "Name - Title"],
    "culture_notes": "culture summary",
    "intern_reviews": "intern experience summary",
    "stipend_range": "INR X-Y/month",
    "hiring_signals": ["signal1", "signal2"],
    "career_page_url": "https://...",
    "personalization_hooks": ["hook1", "hook2", "hook3"],
    "talking_points": ["point1", "point2", "point3"],
    "sector": "Technology/FMCG/Finance/etc",
    "confidence": 0.0-1.0
}}"""

            # Use Groq Compound Beta (agentic model)
            response = router.call(
                'deep_company_intel',
                prompt,
                use_cache=True,
                max_tokens=3000,
            )

            if response.success:
                data = response.get_json()
                if data:
                    return data

            # Fallback: use regular Groq for basic research
            logger.warning(
                f"[{AGENT_ID}] Compound Beta failed, falling back to Groq 70B"
            )
            fallback_response = router.call(
                'company_research',
                prompt,
                use_cache=True,
            )
            if fallback_response.success:
                return fallback_response.get_json()

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Research error for {company}: {e}")

        return None

    # ----------------------------------------------------------
    # MAIN RESEARCH METHOD
    # ----------------------------------------------------------

    async def research_company(self, company: str) -> ResearchResult:
        """
        Research a company and generate an intel brief.

        Args:
            company: Company name to research

        Returns:
            ResearchResult with CompanyIntelBrief
        """
        start_time = time.time()

        # Check cache
        cached = self._get_cached(company)
        if cached:
            self._total_cached_hits += 1
            return ResearchResult(
                success=True,
                company=company,
                brief=cached,
                cached=True,
                research_time_ms=0,
            )

        # Daily limit
        today = datetime.now().date()
        if self._today_date != today:
            self._today_count = 0
            self._today_date = today

        if self._today_count >= MAX_RESEARCH_PER_DAY:
            return ResearchResult(
                success=False,
                company=company,
                error=f"Daily limit reached ({MAX_RESEARCH_PER_DAY})",
            )

        logger.info(f"[{AGENT_ID}] Researching {company}...")
        self._update_heartbeat('running')

        try:
            # Run Groq Compound research
            data = await self._run_compound_research(company)

            if not data:
                self._total_failed += 1
                self._update_heartbeat('idle')
                return ResearchResult(
                    success=False,
                    company=company,
                    error="No research data returned",
                )

            # Build intel brief
            brief = CompanyIntelBrief(
                company=company,
                sector=data.get('sector', ''),
                overview=data.get('overview', ''),
                recent_news=data.get('recent_news', [])[:5],
                leadership=data.get('leadership', [])[:5],
                culture_notes=data.get('culture_notes', ''),
                intern_reviews=data.get('intern_reviews', ''),
                stipend_range=data.get('stipend_range', ''),
                hiring_signals=data.get('hiring_signals', [])[:5],
                career_page_url=data.get('career_page_url', ''),
                personalization_hooks=data.get('personalization_hooks', [])[:5],
                talking_points=data.get('talking_points', [])[:5],
                researched_at=datetime.now(IST).isoformat(),
                confidence=data.get('confidence', 0.5),
                word_count=len(data.get('overview', '').split()),
                sources_used=len(data.get('recent_news', [])),
            )

            # Cache
            self._cache_intel(company, brief)

            # Save to database
            self._save_to_db(brief)

            research_time = (time.time() - start_time) * 1000
            self._total_researched += 1
            self._today_count += 1
            self._update_heartbeat('idle')

            logger.info(
                f"[{AGENT_ID}] Intel brief for {company}: "
                f"{brief.word_count} words, "
                f"{len(brief.personalization_hooks)} hooks, "
                f"confidence={brief.confidence:.0%}"
            )

            return ResearchResult(
                success=True,
                company=company,
                brief=brief,
                cached=False,
                research_time_ms=research_time,
            )

        except Exception as e:
            self._total_failed += 1
            self._update_heartbeat('error')
            logger.error(f"[{AGENT_ID}] Research failed for {company}: {e}")
            return ResearchResult(
                success=False,
                company=company,
                error=str(e),
            )

    async def get_brief(self, company: str) -> Optional[CompanyIntelBrief]:
        """Get intel brief (from cache or research)."""
        result = await self.research_company(company)
        return result.brief if result.success else None

    # ----------------------------------------------------------
    # DATABASE
    # ----------------------------------------------------------

    def _save_to_db(self, brief: CompanyIntelBrief):
        """Save intel brief to company_intel table."""
        try:
            from core.database import get_db
            db = get_db()

            with db.get_cursor() as cur:
                cur.execute("""
                    INSERT OR REPLACE INTO company_intel
                    (company, sector, overview, recent_news, leadership,
                     culture_notes, intern_reviews, stipend_range,
                     hiring_signals, career_page_url, personalization_hooks,
                     talking_points, confidence, researched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    brief.company,
                    brief.sector,
                    brief.overview,
                    json.dumps(brief.recent_news),
                    json.dumps(brief.leadership),
                    brief.culture_notes,
                    brief.intern_reviews,
                    brief.stipend_range,
                    json.dumps(brief.hiring_signals),
                    brief.career_page_url,
                    json.dumps(brief.personalization_hooks),
                    json.dumps(brief.talking_points),
                    brief.confidence,
                    brief.researched_at,
                ))

        except Exception as e:
            logger.error(f"[{AGENT_ID}] DB save error: {e}")

    def _update_heartbeat(self, status: str):
        try:
            from core.database import get_db
            get_db().update_agent_heartbeat(AGENT_ID, status)
        except Exception:
            pass

    # ----------------------------------------------------------
    # BATCH RESEARCH
    # ----------------------------------------------------------

    async def research_batch(
        self,
        companies: List[str],
        delay_between: float = 5.0,
    ) -> Dict[str, ResearchResult]:
        """Research multiple companies with delays."""
        results = {}
        for i, company in enumerate(companies):
            results[company] = await self.research_company(company)
            if i < len(companies) - 1:
                await asyncio.sleep(delay_between)
        return results

    # ----------------------------------------------------------
    # HEALTH
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        return {
            'agent_id': AGENT_ID,
            'agent_name': AGENT_NAME,
            'total_researched': self._total_researched,
            'total_cached_hits': self._total_cached_hits,
            'total_failed': self._total_failed,
            'today_count': self._today_count,
            'daily_limit': MAX_RESEARCH_PER_DAY,
            'cache_size': len(self._intel_cache),
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_instance: Optional[DeepCompanyIntel] = None

def get_company_intel() -> DeepCompanyIntel:
    global _instance
    if _instance is None:
        _instance = DeepCompanyIntel()
    return _instance


if __name__ == "__main__":
    print("=" * 60)
    print(f"PRISM v0.1 — {AGENT_ID}: {AGENT_NAME}")
    print("=" * 60)
    intel = get_company_intel()
    health = intel.get_health()
    for k, v in health.items():
        print(f"  {k}: {v}")
