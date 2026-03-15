"""
============================================================
PRISM v0.1 — A-18: CV INTELLIGENCE ENHANCER (ATS TAILORING)
============================================================
Agent A-18: Personalizes CV bullet points per application using
ATS keyword gaps from A-10 and generates professional PDFs via
WeasyPrint.

Schedule: Triggered by A-13 pre-application check (PPO > 75)
Trigger: auto_apply_queue entries with high PPO

Pipeline:
    1. Receive listing + ATS simulation results from A-10
    2. Identify specific bullets to rewrite (keyword gaps)
    3. Use OpenRouter Gemini 2.0 Flash (1M context) for intelligent rewrites
    4. Inject missing JD keywords truthfully into existing experience
    5. Generate professional PDF via WeasyPrint (core/cv_generator.py)
    6. Store tailored CV path in application_packages.tailored_cv_url
    7. Return tailored CV for A-13 to attach to application

AI Provider: OpenRouter Gemini 2.0 Flash (cv_tailor_full task)
Tools: WeasyPrint PDF generator, db_read/write
Cost: $0 (OpenRouter free tier + local WeasyPrint)

Integration Points:
    - A-10 ATS Simulator → provides keyword gaps + match scores
    - A-13 Auto Applier → uses tailored CV for portal submission
    - A-20 Deep Company Intel → provides company personalization hooks
============================================================
"""

import os
import sys
import json
import time
import asyncio
from datetime import datetime, timezone
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

AGENT_ID = "A-18"
AGENT_NAME = "CV Intelligence Enhancer"

# Thresholds
MIN_PPO_FOR_TAILORING = 70  # Only tailor for PPO > 70
MIN_KEYWORD_GAPS = 2  # At least 2 missing keywords to justify tailoring
MAX_BULLETS_TO_REWRITE = 5  # Don't rewrite more than 5 bullets per CV
MAX_TAILORED_CVS_PER_DAY = 15  # OpenRouter quota conservation


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ATSGapAnalysis:
    """ATS keyword gap analysis from A-10."""
    listing_id: int
    company: str
    role: str
    jd_text: str = ""
    matched_keywords: List[str] = field(default_factory=list)
    missing_keywords: List[str] = field(default_factory=list)
    match_percentage: float = 0.0
    suggested_rewrites: List[Dict[str, str]] = field(default_factory=list)
    ats_pass_probability: float = 0.0


@dataclass
class TailoringResult:
    """Result of CV tailoring."""
    success: bool
    listing_id: int = 0
    company: str = ""
    role: str = ""
    pdf_path: str = ""
    original_ats_score: float = 0.0
    estimated_new_score: float = 0.0
    keywords_injected: List[str] = field(default_factory=list)
    bullets_rewritten: int = 0
    generation_time_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'company': self.company,
            'role': self.role,
            'pdf_path': self.pdf_path,
            'original_ats_score': self.original_ats_score,
            'estimated_new_score': self.estimated_new_score,
            'keywords_injected': self.keywords_injected,
            'bullets_rewritten': self.bullets_rewritten,
            'generation_time_ms': round(self.generation_time_ms, 1),
            'error': self.error,
        }


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class CVIntelligenceEnhancer:
    """
    PRISM A-18: CV Intelligence Enhancer Agent.

    Takes ATS keyword gaps from A-10, generates intelligent bullet
    rewrites via OpenRouter Gemini (1M context), and produces
    tailored PDF CVs via WeasyPrint.

    Usage:
        enhancer = get_cv_enhancer()
        result = await enhancer.tailor_cv(gap_analysis)
        result = await enhancer.tailor_for_listing(listing_id)
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

        # User CV profile (loaded from DB or config)
        self._user_profile = None

        # Stats
        self._total_tailored = 0
        self._total_failed = 0
        self._today_count = 0
        self._today_date = None

        logger.info(f"[{AGENT_ID}] {AGENT_NAME} initialized")

    # ----------------------------------------------------------
    # PROFILE LOADING
    # ----------------------------------------------------------

    def _get_user_profile(self):
        """Load the user's CV profile."""
        if self._user_profile is not None:
            return self._user_profile

        try:
            from core.cv_generator import CVProfile, CVEducationEntry, CVExperienceEntry

            # Try loading from database
            from core.database import get_db
            db = get_db()

            # Default profile (can be overridden from DB/settings)
            self._user_profile = CVProfile(
                name="Abuzar Khan",
                email="",
                phone="",
                linkedin="",
                location="India",
                summary=(
                    "Results-driven MBA candidate at AMU with expertise in "
                    "marketing analytics, business development, and data-driven "
                    "strategy. Skilled in Python, SQL, financial modeling, and "
                    "cross-functional team leadership."
                ),
                education=[
                    CVEducationEntry(
                        institution="Aligarh Muslim University",
                        degree="MBA",
                        field_of_study="Marketing & Strategy",
                        start_year="2024",
                        end_year="2026",
                    ),
                ],
                experience=[],
                skills={
                    'Technical': ['Python', 'SQL', 'Tableau', 'Excel', 'Power BI'],
                    'Domain': ['Marketing Analytics', 'Financial Modeling', 'Strategy'],
                    'Soft Skills': ['Leadership', 'Communication', 'Analytical Thinking'],
                },
            )

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Profile load error: {e}")

        return self._user_profile

    # ----------------------------------------------------------
    # AI-POWERED REWRITING
    # ----------------------------------------------------------

    async def _generate_bullet_rewrites(
        self,
        gap_analysis: ATSGapAnalysis,
        current_bullets: List[str],
    ) -> List[Dict[str, str]]:
        """
        Use OpenRouter Gemini to generate intelligent bullet rewrites
        that inject missing keywords naturally.
        """
        rewrites = []

        if not gap_analysis.missing_keywords:
            return rewrites

        try:
            from core.ai_router import get_router
            router = get_router()

            missing_kws = ', '.join(gap_analysis.missing_keywords[:10])
            bullets_text = '\n'.join(
                f"  {i+1}. {b}" for i, b in enumerate(current_bullets[:MAX_BULLETS_TO_REWRITE])
            )

            prompt = f"""You are an expert ATS resume optimizer for MBA students in India.

TARGET JOB:
Company: {gap_analysis.company}
Role: {gap_analysis.role}
JD: {gap_analysis.jd_text[:3000]}

MISSING KEYWORDS (not in current resume): {missing_kws}

CURRENT RESUME BULLETS:
{bullets_text}

TASK: Rewrite the bullets above to naturally incorporate the missing keywords.

RULES:
1. Only modify bullets where keywords fit naturally
2. MUST be truthful — don't add skills/experience the candidate doesn't have
3. Use strong action verbs and quantifiable metrics
4. Keep each bullet under 200 characters
5. Incorporate keywords as naturally as possible
6. Focus on the top 3-5 most impactful missing keywords

Respond in JSON:
{{
    "rewrites": [
        {{
            "original": "original bullet text",
            "improved": "improved bullet with keywords",
            "keywords_added": ["keyword1", "keyword2"],
            "change_reason": "brief explanation"
        }}
    ],
    "skills_to_add": ["skill1", "skill2"],
    "estimated_ats_improvement": 0-30
}}"""

            response = router.call(
                'cv_tailor_full', prompt, use_cache=False
            )

            if response.success:
                data = response.get_json()
                if data and 'rewrites' in data:
                    rewrites = data['rewrites']

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Rewrite generation error: {e}")

        return rewrites

    # ----------------------------------------------------------
    # MAIN TAILORING METHOD
    # ----------------------------------------------------------

    async def tailor_cv(self, gap_analysis: ATSGapAnalysis) -> TailoringResult:
        """
        Tailor the user's CV for a specific application.

        Args:
            gap_analysis: ATS keyword gap analysis from A-10

        Returns:
            TailoringResult with path to tailored PDF
        """
        start_time = time.time()

        # Daily limit check
        today = datetime.now().date()
        if self._today_date != today:
            self._today_count = 0
            self._today_date = today

        if self._today_count >= MAX_TAILORED_CVS_PER_DAY:
            return TailoringResult(
                success=False,
                listing_id=gap_analysis.listing_id,
                company=gap_analysis.company,
                error=f"Daily limit reached ({MAX_TAILORED_CVS_PER_DAY})",
            )

        logger.info(
            f"[{AGENT_ID}] Tailoring CV for {gap_analysis.company} — "
            f"{gap_analysis.role} ({len(gap_analysis.missing_keywords)} gaps)"
        )
        self._update_heartbeat('running')

        try:
            # Get user profile
            profile = self._get_user_profile()
            if not profile:
                return TailoringResult(
                    success=False,
                    listing_id=gap_analysis.listing_id,
                    error="User profile not loaded",
                )

            # Get current bullets
            current_bullets = []
            for exp in profile.experience:
                current_bullets.extend(exp.bullets)

            # Generate AI rewrites
            rewrites = await self._generate_bullet_rewrites(
                gap_analysis, current_bullets
            )

            # Use existing suggested rewrites from A-10 as fallback
            if not rewrites and gap_analysis.suggested_rewrites:
                rewrites = gap_analysis.suggested_rewrites

            # Generate PDF
            from core.cv_generator import (
                get_cv_generator, CVTailoringRequest
            )
            generator = get_cv_generator()

            request = CVTailoringRequest(
                profile=profile,
                target_company=gap_analysis.company,
                target_role=gap_analysis.role,
                target_jd=gap_analysis.jd_text,
                keyword_gaps=gap_analysis.missing_keywords,
                bullet_rewrites=rewrites,
                skills_to_highlight=gap_analysis.matched_keywords[:5],
            )

            cv_result = generator.generate_tailored_cv(request)

            if not cv_result.success:
                self._total_failed += 1
                return TailoringResult(
                    success=False,
                    listing_id=gap_analysis.listing_id,
                    company=gap_analysis.company,
                    error=cv_result.error,
                )

            # Save to application_packages in DB
            self._save_tailored_cv(
                gap_analysis.listing_id,
                cv_result.pdf_path,
                rewrites,
            )

            generation_time_ms = (time.time() - start_time) * 1000
            self._total_tailored += 1
            self._today_count += 1

            estimated_improvement = min(30, len(cv_result.keywords_injected) * 3)

            logger.info(
                f"[{AGENT_ID}] CV tailored for {gap_analysis.company}: "
                f"{cv_result.bullets_rewritten} rewrites, "
                f"{len(cv_result.keywords_injected)} keywords, "
                f"+{estimated_improvement}% estimated ATS boost"
            )

            self._update_heartbeat('idle')

            return TailoringResult(
                success=True,
                listing_id=gap_analysis.listing_id,
                company=gap_analysis.company,
                role=gap_analysis.role,
                pdf_path=cv_result.pdf_path,
                original_ats_score=gap_analysis.ats_pass_probability,
                estimated_new_score=min(
                    100, gap_analysis.ats_pass_probability + estimated_improvement
                ),
                keywords_injected=cv_result.keywords_injected,
                bullets_rewritten=cv_result.bullets_rewritten,
                generation_time_ms=generation_time_ms,
            )

        except Exception as e:
            self._total_failed += 1
            self._update_heartbeat('error')
            logger.error(f"[{AGENT_ID}] Tailoring error: {e}")
            return TailoringResult(
                success=False,
                listing_id=gap_analysis.listing_id,
                company=gap_analysis.company,
                error=str(e),
            )

    # ----------------------------------------------------------
    # DATABASE
    # ----------------------------------------------------------

    def _save_tailored_cv(
        self,
        listing_id: int,
        pdf_path: str,
        rewrites: List[Dict],
    ):
        """Save tailored CV info to application_packages."""
        try:
            from core.database import get_db
            db = get_db()

            with db.get_cursor() as cur:
                cur.execute("""
                    UPDATE application_packages
                    SET tailored_cv_url = ?,
                        cv_rewrites = ?,
                        cv_tailored_at = ?
                    WHERE listing_id = ?
                """, (
                    pdf_path,
                    json.dumps(rewrites[:10]),
                    datetime.now(IST).isoformat(),
                    listing_id,
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
    # HEALTH
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        return {
            'agent_id': AGENT_ID,
            'agent_name': AGENT_NAME,
            'total_tailored': self._total_tailored,
            'total_failed': self._total_failed,
            'today_count': self._today_count,
            'daily_limit': MAX_TAILORED_CVS_PER_DAY,
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_instance: Optional[CVIntelligenceEnhancer] = None

def get_cv_enhancer() -> CVIntelligenceEnhancer:
    global _instance
    if _instance is None:
        _instance = CVIntelligenceEnhancer()
    return _instance
