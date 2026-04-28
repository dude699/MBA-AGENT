"""
============================================================
PRISM v11.0 — CV MATCHING ENGINE
NEXUS v0.2 upgrade — pgvector semantic blend
============================================================
Scores job listings against the user's uploaded CV.

Two-layer engine (selected automatically per request):
    1. NEXUS pgvector path  (preferred when NEXUS_ENABLED=true and the
       runtime has stored a 1024-dim Groq embedding for this user)
       → cosine similarity with the cached JD embeddings (Layer 3a).
       → richer, learns dimension weights from user taps.
    2. Legacy keyword path  (always-available fallback)
       → rapidfuzz partial_ratio + token overlap, no network calls.
       → < 5MB RAM, < 50ms for 500 listings.

The legacy path remains for the mini-app's "For You" tab on the 512MB
Render dyno and for users who haven't uploaded a CV through the new
Telegram /cv flow yet. Plan A migration: same public API, internals
upgraded, callers in core/miniapp_api.py unchanged.

Public API (unchanged):
    get_cv_matcher() → singleton CVMatcher
    matcher.score_listing(listing) → {score, matched_keywords, reasons}
    matcher.score_listings_batch(listings) → list of annotated listings
    matcher.refresh_from_cv(telegram_id) → reload CV, invalidate cache
    matcher.get_cv_status(telegram_id) → {has_cv, keywords, ...}
============================================================
"""

from __future__ import annotations

import os
import re
import json
import time
import threading
from typing import Dict, List, Optional, Any, Tuple, Set

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


MODULE_ID = "CV-MATCHER"

# ============================================================
# TOKENIZATION + KEYWORD EXTRACTION
# ============================================================

# English stopwords — hand-curated for CVs/JDs (no nltk download on startup).
_STOPWORDS: Set[str] = {
    'a', 'an', 'the', 'and', 'or', 'but', 'if', 'of', 'at', 'by', 'for',
    'with', 'about', 'against', 'between', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'to', 'from', 'in', 'out', 'on',
    'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here',
    'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each',
    'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can',
    'will', 'just', 'don', 'should', 'now', 'i', 'me', 'my', 'myself',
    'we', 'our', 'ours', 'you', 'your', 'yours', 'he', 'she', 'it', 'its',
    'they', 'them', 'their', 'what', 'which', 'who', 'whom', 'this',
    'that', 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did',
    'doing', 'would', 'could', 'ought', 'would', 'as', 'until', 'while',
    'because', 'since', 'also', 'get', 'got', 'make', 'made', 'work',
    'works', 'working', 'worked', 'job', 'jobs', 'role', 'roles',
    'company', 'companies', 'team', 'teams', 'year', 'years', 'month',
    'months', 'internship', 'internships', 'experience', 'skills',
    'skill', 'candidate', 'candidates', 'responsibilities', 'requirement',
    'requirements', 'must', 'should', 'required', 'responsible', 'apply',
    'applying', 'opportunity', 'opportunities', 'looking', 'seek',
    'seeking', 'join', 'please', 'strong', 'good', 'great', 'excellent',
    'ability', 'abilities', 'knowledge', 'understanding', 'etc',
}

# High-value keyword categories — boost these matches in scoring.
_TECH_KEYWORDS: Set[str] = {
    'python', 'java', 'javascript', 'typescript', 'react', 'node', 'nodejs',
    'sql', 'nosql', 'mongodb', 'postgres', 'postgresql', 'mysql', 'redis',
    'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'k8s', 'ci', 'cd',
    'git', 'github', 'gitlab', 'linux', 'bash', 'shell', 'api', 'rest',
    'graphql', 'html', 'css', 'tailwind', 'bootstrap', 'vue', 'angular',
    'django', 'flask', 'fastapi', 'spring', 'express', 'rails',
    'pandas', 'numpy', 'tensorflow', 'pytorch', 'sklearn', 'ml', 'ai',
    'llm', 'nlp', 'cv', 'data', 'analytics', 'tableau', 'powerbi',
    'excel', 'vba', 'sap', 'salesforce', 'hubspot', 'jira', 'confluence',
    'agile', 'scrum', 'kanban', 'devops', 'sre', 'testing', 'qa',
    'selenium', 'pytest', 'junit', 'jest', 'cypress',
}

_BUSINESS_KEYWORDS: Set[str] = {
    'marketing', 'finance', 'accounting', 'audit', 'tax', 'strategy',
    'consulting', 'operations', 'supply', 'logistics', 'procurement',
    'sales', 'business', 'development', 'analyst', 'manager', 'director',
    'mba', 'cfa', 'ca', 'cma', 'cpa', 'banking', 'investment', 'equity',
    'research', 'analysis', 'forecasting', 'modelling', 'valuation',
    'branding', 'digital', 'seo', 'sem', 'social', 'content', 'copy',
    'product', 'pm', 'project', 'hr', 'talent', 'recruiting', 'legal',
    'compliance', 'risk', 'treasury', 'crm', 'erp', 'startup',
}


def tokenize(text: str) -> List[str]:
    """Cheap, deterministic tokenizer — lowercase words ≥3 chars, no stopwords."""
    if not text:
        return []
    # Lowercase, keep letters/digits/+/#/-, split on anything else
    text = text.lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9+#\-\.]*", text)
    return [t.strip('-.').strip() for t in tokens
            if len(t) >= 3 and t not in _STOPWORDS]


def extract_keywords(text: str, top_n: int = 60) -> Dict[str, int]:
    """Return token → frequency map for top-N tokens."""
    tokens = tokenize(text)
    if not tokens:
        return {}
    freq: Dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    # Keep top N by frequency, but always keep tech/business keywords
    sorted_tokens = sorted(freq.items(), key=lambda x: -x[1])
    result: Dict[str, int] = {}
    for t, f in sorted_tokens[:top_n]:
        result[t] = f
    # Ensure all tech/business keywords present in CV are kept
    for t in _TECH_KEYWORDS | _BUSINESS_KEYWORDS:
        if t in freq and t not in result:
            result[t] = freq[t]
    return result


# ============================================================
# CV MATCHER — SINGLETON
# ============================================================

class CVMatcher:
    """
    Keeps tokenized CV + user profile in memory for fast scoring.
    Thread-safe; cheap to initialize (< 1ms if CV is cached).
    """

    def __init__(self):
        self._lock = threading.RLock()
        # Per-user CV cache: telegram_id -> {'tokens': set, 'keywords': dict, 'cv_mtime': float, 'cv_text_preview': str}
        self._cache: Dict[str, Dict[str, Any]] = {}
        # Default profile when no user-specific profile is found
        self._default_profile: Dict[str, Any] = {}

    # --------------------------------------------------------
    # CV LOADING
    # --------------------------------------------------------

    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF — tries pdftotext (fast) then PyPDF2 fallback."""
        try:
            import subprocess
            result = subprocess.run(
                ['pdftotext', '-layout', pdf_path, '-'],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, Exception):
            pass

        # Try pypdf first (modern, maintained), fall back to PyPDF2 (old name)
        for module_name in ('pypdf', 'PyPDF2'):
            try:
                mod = __import__(module_name)
                with open(pdf_path, 'rb') as f:
                    reader = mod.PdfReader(f)
                    pages = []
                    for page in reader.pages[:5]:
                        try:
                            pages.append(page.extract_text() or "")
                        except Exception:
                            continue
                    text = "\n".join(pages).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    def _load_profile(self, telegram_id: str) -> Dict[str, Any]:
        """Read user profile JSON from disk."""
        try:
            safe_id = str(telegram_id).replace('/', '').replace('..', '')[:20]
            profile_path = os.path.join('data', 'user_profiles', f'{safe_id}.json')
            if os.path.isfile(profile_path):
                with open(profile_path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def refresh_from_cv(self, telegram_id: str) -> bool:
        """
        Re-read the user's CV and tokenize. Call this after /api/user/upload-cv.
        Returns True if CV was loaded, False if no CV available.

        NEXUS v0.2 fix: if the local PDF is missing (Render's free tier
        wipes `data/` on every redeploy), transparently restore it from
        the Supabase `user_cvs` mirror before tokenising. This keeps the
        "For You" tab personalised across restarts.
        """
        with self._lock:
            safe_id = str(telegram_id or 'anonymous').replace('/', '').replace('..', '')[:20]
            cv_path = os.path.join('data', 'user_cvs', f'{safe_id}.pdf')

            profile = self._load_profile(safe_id)

            if not os.path.isfile(cv_path):
                # NEXUS v0.2 — try restoring from Supabase before giving up.
                restored = False
                try:
                    from core.cv_storage import restore_local_cv
                    restored = restore_local_cv(safe_id, cv_path)
                except Exception as restore_err:
                    logger.debug(
                        f"[{MODULE_ID}] cv_storage restore unavailable: {restore_err}"
                    )

                if not restored:
                    # Still cache profile so profile-only matching works
                    self._cache[safe_id] = {
                        'tokens': set(),
                        'keywords': {},
                        'cv_mtime': 0,
                        'cv_text_preview': '',
                        'profile': profile,
                        'has_cv': False,
                        'loaded_at': time.time(),
                    }
                    return False
                # Else: file is now on disk, fall through to the regular
                # extraction path below.

            try:
                mtime = os.path.getmtime(cv_path)
            except OSError:
                mtime = 0

            # Cache hit — don't re-extract if mtime unchanged
            cached = self._cache.get(safe_id)
            if cached and cached.get('cv_mtime') == mtime and cached.get('has_cv'):
                # Just refresh profile in case it changed
                cached['profile'] = profile
                return True

            text = self._extract_pdf_text(cv_path)
            if not text:
                logger.warning(f"[{MODULE_ID}] CV extraction returned empty for {safe_id}")
                self._cache[safe_id] = {
                    'tokens': set(),
                    'keywords': {},
                    'cv_mtime': mtime,
                    'cv_text_preview': '',
                    'profile': profile,
                    'has_cv': False,
                    'loaded_at': time.time(),
                }
                return False

            keywords = extract_keywords(text, top_n=80)
            tokens = set(keywords.keys())

            # Enrich from profile skills too
            profile_skills = profile.get('skills', '') or ''
            if profile_skills:
                for t in tokenize(profile_skills):
                    tokens.add(t)
                    keywords[t] = keywords.get(t, 0) + 2  # profile skills weighted higher

            self._cache[safe_id] = {
                'tokens': tokens,
                'keywords': keywords,
                'cv_mtime': mtime,
                'cv_text_preview': text[:500],
                'profile': profile,
                'has_cv': True,
                'loaded_at': time.time(),
            }

            logger.info(
                f"[{MODULE_ID}] CV loaded for {safe_id}: "
                f"{len(tokens)} tokens, {len(keywords)} keywords, "
                f"{len(text)} chars text"
            )
            return True

    def get_cv_status(self, telegram_id: str) -> Dict[str, Any]:
        """Return whether we have a CV + keyword preview for UI display."""
        safe_id = str(telegram_id or 'anonymous').replace('/', '').replace('..', '')[:20]
        with self._lock:
            cached = self._cache.get(safe_id)
            if not cached:
                self.refresh_from_cv(safe_id)
                cached = self._cache.get(safe_id, {})

            return {
                'has_cv': cached.get('has_cv', False),
                'keyword_count': len(cached.get('keywords', {})),
                'top_keywords': [
                    k for k, _ in sorted(
                        cached.get('keywords', {}).items(),
                        key=lambda x: -x[1]
                    )[:15]
                ],
                'has_profile': bool(cached.get('profile')),
                'text_preview': cached.get('cv_text_preview', '')[:200],
            }

    # --------------------------------------------------------
    # SCORING
    # --------------------------------------------------------

    def score_listing(self, listing: Dict[str, Any],
                      telegram_id: str = 'anonymous') -> Dict[str, Any]:
        """
        Score a single listing against the cached CV.

        NEXUS v0.2: When NEXUS_ENABLED=true, blends the legacy keyword score
        (60% weight) with the pgvector cosine score from the user's stored
        embedding (40% weight). Falls back to pure keyword scoring otherwise.

        Returns:
            {
                'match_score': 0-100 float,
                'matched_keywords': [...],
                'reasons': [...],
                'has_cv': bool,
            }
        """
        safe_id = str(telegram_id or 'anonymous').replace('/', '').replace('..', '')[:20]

        with self._lock:
            cached = self._cache.get(safe_id)
            if not cached:
                # First call for this user — try to load
                self.refresh_from_cv(safe_id)
                cached = self._cache.get(safe_id, {})

            cv_tokens: Set[str] = cached.get('tokens', set())
            cv_keywords: Dict[str, int] = cached.get('keywords', {})
            profile: Dict[str, Any] = cached.get('profile', {})
            has_cv: bool = cached.get('has_cv', False)

        # If no CV and no profile, return neutral score
        if not cv_tokens and not profile:
            return {
                'match_score': 50.0,
                'matched_keywords': [],
                'reasons': ['Upload your CV to get personalized match scores'],
                'has_cv': False,
            }

        # ===== Extract listing signal =====
        title = (listing.get('title', '') or '').lower()
        company = (listing.get('company', '') or '').lower()
        description = (listing.get('description_text', '') or listing.get('description', '') or '')[:3000].lower()
        category = (listing.get('category', '') or '').lower()
        location = (listing.get('location', '') or '').lower()

        listing_text = f"{title} {title} {category} {description}"  # title weighted 2x
        listing_tokens = set(tokenize(listing_text))

        if not listing_tokens:
            return {
                'match_score': 30.0,
                'matched_keywords': [],
                'reasons': ['Listing has no description'],
                'has_cv': has_cv,
            }

        # ===== NEXUS v0.2 — NO HARD CAPS =====
        # Per the architecture doc (Layer 3, 9-dim Intelligence Scoring):
        # the AI decides relevance via Groq/Gemini semantic classification
        # against the candidate's full CV+profile. Hard regex blocklists are
        # WRONG because they reject valid roles like "Customer Experience
        # Associate Manager" (a customer-ops MBA role) just because they
        # contain a keyword. Removed.
        #
        # The proper signal is _nexus_pgvector_score() at the bottom of
        # this method, which compares the JD embedding to the user's
        # 1024-dim CV embedding via cosine similarity. AI does the work.
        # ===== 1. Raw keyword overlap (0-50 points) =====
        overlap = cv_tokens & listing_tokens
        overlap_weighted = sum(
            cv_keywords.get(t, 1) * (2 if t in _TECH_KEYWORDS or t in _BUSINESS_KEYWORDS else 1)
            for t in overlap
        )
        # Normalize: 10 weighted matches = full 50 points
        overlap_score = min(50.0, overlap_weighted * 5.0)

        # ===== 2. Title/role keyword match (0-25 points) =====
        title_tokens = set(tokenize(title + ' ' + category))
        title_overlap = cv_tokens & title_tokens
        title_score = min(25.0, len(title_overlap) * 8.0)

        # ===== 3. Fuzzy top-keyword match (0-15 points) =====
        # Even if exact match fails, rapidfuzz catches "frontend" vs "front-end"
        fuzzy_score = 0.0
        try:
            from rapidfuzz import fuzz
            top_cv_kws = list(sorted(cv_keywords.items(), key=lambda x: -x[1]))[:20]
            for kw, _ in top_cv_kws:
                if kw in listing_tokens:
                    continue  # already counted in overlap
                # Cheap substring check first to avoid full scoring
                if kw in listing_text:
                    fuzzy_score += 1.5
                elif len(kw) >= 5:
                    ratio = fuzz.partial_ratio(kw, listing_text)
                    if ratio >= 92:
                        fuzzy_score += 1.0
                if fuzzy_score >= 15.0:
                    break
            fuzzy_score = min(15.0, fuzzy_score)
        except ImportError:
            # rapidfuzz not available — fall back to exact substring
            for kw in list(cv_keywords.keys())[:20]:
                if kw in listing_text and kw not in listing_tokens:
                    fuzzy_score += 1.0
            fuzzy_score = min(15.0, fuzzy_score)

        # ===== 4. Profile fit (location, specialization) (0-10 points) =====
        profile_score = 0.0
        profile_loc = (profile.get('location', '') or '').lower().strip()
        if profile_loc and location:
            if profile_loc in location or location in profile_loc:
                profile_score += 5.0
            elif location in ('remote', 'work from home'):
                profile_score += 3.0

        specialization = (profile.get('specialization', '') or '').lower().strip()
        if specialization:
            spec_tokens = tokenize(specialization)
            if any(st in title or st in category for st in spec_tokens):
                profile_score += 5.0

        # Remote bonus
        if 'remote' in location or 'work from home' in location:
            profile_score += 2.0

        profile_score = min(10.0, profile_score)

        # ===== Combine =====
        total = overlap_score + title_score + fuzzy_score + profile_score
        total = round(min(100.0, max(0.0, total)), 1)

        # Build reasons for UI tooltip
        reasons = []
        if overlap:
            reasons.append(f"{len(overlap)} CV keywords match")
        if title_overlap:
            top3 = list(title_overlap)[:3]
            reasons.append(f"Title matches: {', '.join(top3)}")
        if profile_score >= 5:
            reasons.append("Fits your location/specialization")
        if not reasons:
            reasons.append("Low CV alignment")

        matched_keywords = sorted(overlap, key=lambda k: -cv_keywords.get(k, 0))[:8]

        # ────────────────────────────────────────────────────────────────
        # NEXUS v0.2 — pgvector blend (60% keyword / 40% cosine)
        # Only kicks in when NEXUS_ENABLED=true AND a runtime is bound AND
        # the user has a stored embedding. ANY error → silent fallback to
        # the legacy keyword score (never break the mini-app).
        # ────────────────────────────────────────────────────────────────
        nexus_score = self._nexus_pgvector_score(safe_id, listing)
        if nexus_score is not None:
            blended = round(min(100.0, max(0.0, total * 0.6 + nexus_score * 0.4)), 1)
            reasons.insert(0, f"Semantic match: {nexus_score:.0f}/100 (NEXUS pgvector)")
            total = blended

        # NEXUS v0.2 — NO HARD CAPS. Final score is the AI-blended value.
        # If the user genuinely has "python" on their CV and a listing is
        # for an SWE role, that's a high match. The user can filter by
        # category in the UI; we don't second-guess the AI here.

        return {
            'match_score': total,
            'matched_keywords': matched_keywords,
            'reasons': reasons,
            'has_cv': has_cv,
        }

    # ────────────────────────────────────────────────────────────────────
    # NEXUS v0.2 helper — pgvector cosine on the user's stored embedding
    # ────────────────────────────────────────────────────────────────────
    def _nexus_pgvector_score(self, safe_id: str, listing: Dict[str, Any]) -> Optional[float]:
        """
        Returns 0..100 cosine score against the user's stored 1024-dim Groq
        embedding, or None when unavailable. Synchronous wrapper — refuses
        to run inside a running event loop to avoid re-entry."""
        if os.getenv("NEXUS_ENABLED", "").lower() not in ("1", "true", "yes", "on"):
            return None
        try:
            from core.nexus_runtime import get_runtime               # type: ignore
        except Exception:
            return None
        runtime = None
        try:
            runtime = get_runtime()
        except Exception:
            return None
        if runtime is None:
            return None

        # Build the JD text once; cheap fields only
        jd = (
            (listing.get("description_text") or listing.get("jd_text") or "")
            + " " + (listing.get("title") or "")
            + " " + (listing.get("company") or "")
        ).strip()
        if len(jd) < 30:
            return None

        # Resolve user_id from telegram handle via the access DAO.
        # If the runtime has no DAO bound yet (light-mode boot), bail.
        db = getattr(runtime, "_db", None) or getattr(runtime, "db", None)
        if db is None:
            return None

        try:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    return None     # re-entry guard (we're inside web handler)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            async def _go() -> Optional[float]:
                # 1. Resolve user_id from telegram handle
                getter = getattr(db, "get_user_id_by_telegram_handle", None)
                if getter is None:
                    return None
                uid = await getter(safe_id)
                if uid is None:
                    return None
                # 2. Compute cosine via pgvector_matcher.match_with_jd_embedding
                from core.pgvector_matcher import (
                    embed_text as _embed,
                    cosine as _cos,
                    cosine_to_score as _to_score,
                )
                # 3. Fetch user embedding
                user_emb_getter = getattr(db, "get_user_cv_embedding", None)
                if user_emb_getter is None:
                    return None
                user_emb = await user_emb_getter(uid)
                if not user_emb or all(v == 0.0 for v in user_emb):
                    return None
                # 4. Compute JD embedding (cached if already in jobs table)
                jd_emb = await _embed(jd[:6000])
                if not jd_emb or all(v == 0.0 for v in jd_emb):
                    return None
                sim = _cos(user_emb, jd_emb)
                return float(_to_score(sim))

            return loop.run_until_complete(_go())
        except Exception as e:                                          # noqa: BLE001
            logger.debug(f"[{MODULE_ID}] NEXUS pgvector blend skipped: {e}")
            return None

    def score_listings_batch(self, listings: List[Dict[str, Any]],
                             telegram_id: str = 'anonymous') -> List[Dict[str, Any]]:
        """
        Score a batch of listings and return them sorted by score desc.
        Each listing gets 'cv_match_score' and 'cv_matched_keywords' injected.
        """
        if not listings:
            return []

        safe_id = str(telegram_id or 'anonymous').replace('/', '').replace('..', '')[:20]
        # Ensure CV is loaded once (not per-listing)
        with self._lock:
            if safe_id not in self._cache:
                self.refresh_from_cv(safe_id)

        annotated = []
        for listing in listings:
            score_result = self.score_listing(listing, safe_id)
            # Shallow copy to avoid mutating caller's dict
            enriched = dict(listing)
            enriched['cv_match_score'] = score_result['match_score']
            enriched['cv_matched_keywords'] = score_result['matched_keywords']
            enriched['cv_match_reasons'] = score_result['reasons']
            annotated.append(enriched)

        # Sort by CV match score descending
        annotated.sort(key=lambda x: -x.get('cv_match_score', 0))
        return annotated


# ============================================================
# SINGLETON ACCESS
# ============================================================

_matcher_instance: Optional[CVMatcher] = None
_matcher_lock = threading.Lock()


def get_cv_matcher() -> CVMatcher:
    """Thread-safe singleton accessor."""
    global _matcher_instance
    if _matcher_instance is None:
        with _matcher_lock:
            if _matcher_instance is None:
                _matcher_instance = CVMatcher()
    return _matcher_instance
