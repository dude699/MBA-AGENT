"""
============================================================
AGENT A-10: ATS KEYWORD SIMULATOR — INDUSTRIAL GRADE
============================================================
Simulates Applicant Tracking System keyword scanning on resume
vs Job Description. Identifies keyword gaps and generates
targeted resume tweaks for ATS optimization.

Trigger: On-demand via /ats [id] or /package [id]
AI Model: Groq (ats_simulation, resume_tweaks)

Architecture:
    ┌──────────────────────────────────────────────────┐
    │            ATS SIMULATOR (A-10)                  │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │  ┌───────────────────────────────────────────┐   │
    │  │  JD Keyword Extractor                      │   │
    │  │  - TF-IDF keyword extraction               │   │
    │  │  - AI-powered keyword identification       │   │
    │  │  - Skill/qualification clustering          │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Resume Keyword Scanner                    │   │
    │  │  - Exact keyword matching                  │   │
    │  │  - Synonym matching                        │   │
    │  │  - Partial/fuzzy matching                  │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Gap Analyzer                              │   │
    │  │  - Missing hard skills                     │   │
    │  │  - Missing soft skills                     │   │
    │  │  - Missing certifications                  │   │
    │  │  - Action verb suggestions                 │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Resume Tweak Generator (Groq)             │   │
    │  │  - 5 bullet-point resume tweaks            │   │
    │  │  - Exact phrases to add for ATS pass       │   │
    │  │  - Section-by-section optimization         │   │
    │  │  - Cover letter keyword integration        │   │
    │  └───────────────────────────────────────────┘   │
    │                                                  │
    └──────────────────────────────────────────────────┘
============================================================
"""

import os
import re
import json
import time
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from collections import Counter, defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

from core.config import get_config, IST
from core.database import get_db, DatabaseManager, ApplicationPackage
from core.ai_router import get_router, AIRouter

AGENT_ID = "A-10"
AGENT_NAME = "ATS Keyword Simulator"

# Common ATS keywords by category
ATS_KEYWORD_CATEGORIES = {
    'hard_skills': [
        'financial modeling', 'data analysis', 'market research',
        'business development', 'project management', 'stakeholder management',
        'strategic planning', 'competitive analysis', 'P&L management',
        'digital marketing', 'SEO', 'SEM', 'social media marketing',
        'supply chain management', 'inventory management', 'procurement',
        'SQL', 'Excel', 'PowerPoint', 'Tableau', 'Python', 'R',
        'Salesforce', 'SAP', 'CRM', 'ERP', 'JIRA', 'Confluence',
        'A/B testing', 'user research', 'product strategy',
        'pricing strategy', 'go-to-market', 'brand management',
        'operations management', 'process improvement', 'lean',
        'six sigma', 'agile', 'scrum', 'kanban',
        'valuation', 'DCF', 'M&A', 'due diligence',
        'revenue growth', 'cost optimization', 'budget management',
    ],
    'soft_skills': [
        'leadership', 'communication', 'teamwork', 'problem solving',
        'analytical thinking', 'critical thinking', 'creative thinking',
        'decision making', 'time management', 'adaptability',
        'collaboration', 'presentation skills', 'negotiation',
        'conflict resolution', 'mentoring', 'coaching',
        'cross-functional', 'stakeholder management', 'influence',
    ],
    'action_verbs': [
        'achieved', 'analyzed', 'built', 'created', 'delivered',
        'developed', 'drove', 'established', 'executed', 'generated',
        'implemented', 'improved', 'increased', 'launched', 'led',
        'managed', 'negotiated', 'optimized', 'organized', 'produced',
        'reduced', 'restructured', 'spearheaded', 'streamlined',
        'transformed', 'grew', 'exceeded', 'accelerated', 'pioneered',
    ],
    'certifications': [
        'CFA', 'FRM', 'PMP', 'PRINCE2', 'AWS', 'Azure',
        'Google Analytics', 'HubSpot', 'Salesforce',
        'Six Sigma Green Belt', 'Six Sigma Black Belt',
        'CBAP', 'CCBA', 'PMI-ACP', 'CSM', 'CSPO',
    ],
    'education': [
        'MBA', 'PGDM', 'BBA', 'B.Com', 'B.Tech', 'CA',
        'CMA', 'CS', 'IIM', 'ISB', 'XLRI', 'FMS',
        'IIFT', 'MDI', 'SPJIMR', 'JBIMS', 'NMIMS',
    ],
}

# Synonym map for matching
KEYWORD_SYNONYMS = {
    'financial modeling': ['financial modelling', 'fin modeling', 'financial models'],
    'data analysis': ['data analytics', 'analytical skills', 'data-driven'],
    'market research': ['market analysis', 'competitive intelligence', 'market study'],
    'project management': ['program management', 'project coordination', 'PM'],
    'business development': ['biz dev', 'BD', 'business growth'],
    'digital marketing': ['online marketing', 'internet marketing', 'digital strategy'],
    'supply chain': ['SCM', 'logistics', 'supply chain management'],
    'stakeholder management': ['stakeholder engagement', 'client management'],
    'P&L': ['profit and loss', 'P&L management', 'PnL', 'income statement'],
    'go-to-market': ['GTM', 'go to market strategy', 'launch strategy'],
    'cross-functional': ['cross functional', 'interdepartmental', 'multi-team'],
}


@dataclass
class ATSSimulationResult:
    """Complete ATS simulation result."""
    listing_id: int = 0
    title: str = ""
    company: str = ""
    match_percentage: float = 0.0
    total_jd_keywords: int = 0
    matched_keywords: int = 0
    missing_keywords: List[str] = field(default_factory=list)
    matched_keyword_list: List[str] = field(default_factory=list)
    partial_matches: List[Dict] = field(default_factory=list)
    category_scores: Dict[str, float] = field(default_factory=dict)
    resume_tweaks: List[str] = field(default_factory=list)
    phrases_to_add: List[str] = field(default_factory=list)
    section_suggestions: Dict[str, List[str]] = field(default_factory=dict)
    overall_assessment: str = ""
    error: Optional[str] = None

    def to_telegram_msg(self) -> str:
        """Format for Telegram display."""
        # Score emoji
        if self.match_percentage >= 80:
            emoji = "🟢"
        elif self.match_percentage >= 60:
            emoji = "🟡"
        else:
            emoji = "🔴"

        lines = [
            f"🔬 <b>ATS Simulation: {self.title}</b>",
            f"<i>@ {self.company}</i>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"{emoji} <b>Match Score: {self.match_percentage:.0f}%</b>",
            f"Keywords: {self.matched_keywords}/{self.total_jd_keywords} matched",
            f"",
        ]

        if self.category_scores:
            lines.append("<b>Category Breakdown:</b>")
            for cat, score in self.category_scores.items():
                filled = int(score / 10)
                bar = '█' * filled + '░' * (10 - filled)
                lines.append(f"  {cat}: [{bar}] {score:.0f}%")
            lines.append("")

        if self.missing_keywords:
            lines.append(f"<b>❌ Missing Keywords ({len(self.missing_keywords)}):</b>")
            for kw in self.missing_keywords[:10]:
                lines.append(f"  • {kw}")
            lines.append("")

        if self.resume_tweaks:
            lines.append("<b>📝 Resume Tweaks:</b>")
            for i, tweak in enumerate(self.resume_tweaks[:5], 1):
                lines.append(f"  {i}. {tweak}")
            lines.append("")

        if self.phrases_to_add:
            lines.append("<b>✏️ Exact Phrases to Add:</b>")
            for phrase in self.phrases_to_add[:5]:
                lines.append(f"  ✅ \"{phrase}\"")

        return '\n'.join(lines)


class JDKeywordExtractor:
    """Extracts keywords from job descriptions using TF-IDF and AI."""

    def __init__(self, router: AIRouter):
        self.router = router

    def extract_keywords(self, jd_text: str) -> Dict[str, List[str]]:
        """
        Extract categorized keywords from JD.
        Returns dict with categories as keys and keyword lists as values.
        """
        keywords = {
            'hard_skills': [],
            'soft_skills': [],
            'tools': [],
            'qualifications': [],
            'experience': [],
        }

        jd_lower = jd_text.lower()

        # Rule-based extraction
        for category, kw_list in ATS_KEYWORD_CATEGORIES.items():
            for kw in kw_list:
                if kw.lower() in jd_lower:
                    target_cat = 'hard_skills' if category in ('hard_skills', 'action_verbs') else \
                                 'soft_skills' if category == 'soft_skills' else \
                                 'tools' if category == 'certifications' else 'qualifications'
                    if kw not in keywords[target_cat]:
                        keywords[target_cat].append(kw)

        # AI extraction for additional keywords
        try:
            response = self.router.simulate_ats(jd_text, '')
            if response.success:
                data = response.get_json()
                if data and isinstance(data.get('jd_keywords', []), list):
                    for kw in data['jd_keywords']:
                        if isinstance(kw, str) and kw not in keywords['hard_skills']:
                            keywords['hard_skills'].append(kw)
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] AI keyword extraction error: {e}")

        return keywords

    @staticmethod
    def extract_ngrams(text: str, n_range: Tuple[int, int] = (1, 3)) -> Counter:
        """Extract n-grams from text for TF-IDF style analysis."""
        words = re.findall(r'\b[a-z]{2,}\b', text.lower())
        ngrams = Counter()
        for n in range(n_range[0], n_range[1] + 1):
            for i in range(len(words) - n + 1):
                gram = ' '.join(words[i:i+n])
                ngrams[gram] += 1
        return ngrams


class ResumeKeywordScanner:
    """Scans resume text for JD keyword matches."""

    @staticmethod
    def scan(resume_text: str, jd_keywords: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Scan resume for JD keywords.
        Returns match details.
        """
        resume_lower = resume_text.lower()
        matched = []
        missing = []
        partial = []
        category_matches = {}

        all_keywords = []
        for cat, kws in jd_keywords.items():
            cat_matched = 0
            cat_total = len(kws)

            for kw in kws:
                all_keywords.append((kw, cat))
                kw_lower = kw.lower()

                # Exact match
                if kw_lower in resume_lower:
                    matched.append(kw)
                    cat_matched += 1
                    continue

                # Synonym match
                synonyms = KEYWORD_SYNONYMS.get(kw_lower, [])
                found_synonym = False
                for syn in synonyms:
                    if syn.lower() in resume_lower:
                        matched.append(kw)
                        partial.append({'keyword': kw, 'matched_as': syn, 'type': 'synonym'})
                        cat_matched += 1
                        found_synonym = True
                        break

                if found_synonym:
                    continue

                # Fuzzy match (if available)
                if FUZZY_AVAILABLE:
                    best_fuzzy = 0
                    best_match_word = ""
                    resume_words = resume_lower.split()
                    for rw in resume_words:
                        score = fuzz.ratio(kw_lower, rw)
                        if score > best_fuzzy:
                            best_fuzzy = score
                            best_match_word = rw

                    if best_fuzzy >= 85:
                        matched.append(kw)
                        partial.append({'keyword': kw, 'matched_as': best_match_word, 'type': 'fuzzy', 'score': best_fuzzy})
                        cat_matched += 1
                        continue

                missing.append(kw)

            if cat_total > 0:
                category_matches[cat] = round((cat_matched / cat_total) * 100, 1)

        total = len(all_keywords)
        match_pct = (len(matched) / max(total, 1)) * 100

        return {
            'matched': matched,
            'missing': missing,
            'partial': partial,
            'category_scores': category_matches,
            'match_percentage': round(match_pct, 1),
            'total_keywords': total,
        }


class ATSSimulator:
    """
    Master ATS simulation engine.
    
    Pipeline:
        1. Load listing JD from database
        2. Load user resume from settings
        3. Extract JD keywords (rule-based + AI)
        4. Scan resume for keyword matches
        5. Identify gaps
        6. Generate resume tweaks (Groq)
        7. Store result as ApplicationPackage
        8. Return formatted result
    """

    def __init__(self):
        self.db = get_db()
        self.router = get_router()
        self.jd_extractor = JDKeywordExtractor(self.router)
        self.scanner = ResumeKeywordScanner()

    def simulate(self, listing_id: int, resume_text: str = '') -> ATSSimulationResult:
        """Run full ATS simulation for a listing."""
        logger.info(f"[{AGENT_ID}] ATS simulation for listing {listing_id}")
        self.db.update_agent_heartbeat(AGENT_ID, 'running')

        result = ATSSimulationResult(listing_id=listing_id)

        # Get listing
        listing = self.db.get_clean_listing_by_id(listing_id)
        if not listing:
            result.error = "Listing not found"
            return result

        result.title = listing.get('title', '')
        result.company = listing.get('company', '')
        jd_text = listing.get('description_text', '')

        if not jd_text:
            result.error = "No job description available"
            return result

        # Get resume
        if not resume_text:
            resume_text = self.db.get_setting('user_resume', '')
        if not resume_text:
            result.error = "No resume text. Use /settings to set your resume."
            return result

        # Extract JD keywords
        jd_keywords = self.jd_extractor.extract_keywords(jd_text)

        # Scan resume
        scan_result = self.scanner.scan(resume_text, jd_keywords)

        result.match_percentage = scan_result['match_percentage']
        result.total_jd_keywords = scan_result['total_keywords']
        result.matched_keywords = len(scan_result['matched'])
        result.matched_keyword_list = scan_result['matched']
        result.missing_keywords = scan_result['missing']
        result.partial_matches = scan_result['partial']
        result.category_scores = scan_result['category_scores']

        # Generate resume tweaks using AI
        try:
            response = self.router.simulate_ats(jd_text, resume_text)
            if response.success:
                data = response.get_json()
                if data:
                    result.resume_tweaks = data.get('resume_tweaks', [])[:5]
                    result.phrases_to_add = data.get('phrases_to_add', result.missing_keywords[:5])
                    result.section_suggestions = data.get('section_suggestions', {})
                    result.overall_assessment = data.get('assessment', '')
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] AI tweak generation error: {e}")

        # Fallback tweaks if AI failed
        if not result.resume_tweaks and result.missing_keywords:
            result.resume_tweaks = [
                f"Add '{kw}' to your skills or experience section"
                for kw in result.missing_keywords[:5]
            ]
            result.phrases_to_add = result.missing_keywords[:5]

        # Store as ApplicationPackage
        try:
            pkg = ApplicationPackage(
                listing_id=listing_id,
                resume_tweaks=json.dumps(result.resume_tweaks, indent=2),
                keyword_gaps=json.dumps(result.missing_keywords, indent=2),
                keyword_match_pct=result.match_percentage,
            )
            self.db.insert_application_package(pkg)
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Package save error: {e}")

        self.db.update_agent_heartbeat(AGENT_ID, 'completed', items_processed=1)
        return result


_simulator_instance: Optional[ATSSimulator] = None

def get_ats_simulator() -> ATSSimulator:
    global _simulator_instance
    if _simulator_instance is None:
        _simulator_instance = ATSSimulator()
    return _simulator_instance


if __name__ == "__main__":
    print(f"✅ {AGENT_NAME} ({AGENT_ID}) ready")
    print(f"  ATS keyword categories: {len(ATS_KEYWORD_CATEGORIES)}")
    print(f"  Hard skills tracked: {len(ATS_KEYWORD_CATEGORIES['hard_skills'])}")
    print(f"  Synonym mappings: {len(KEYWORD_SYNONYMS)}")
