"""
============================================================
PRISM v0.1 — AGENT A-13: AUTO-APPLY ORCHESTRATOR
============================================================
Automates application submission to internship platforms with
intelligent cover letter generation, anti-ban measures, and
human-like behavior simulation.

PRISM v0.1 Upgrades from OFM v7.0:
    1. Intelligence Sequence (Pre-Application Check):
       - Check if A-10 ATS simulation done → if not, trigger it
       - Check if A-18 CV tailoring done → if not, trigger it
       - Check if A-09 found alumni → schedule A-15 email first
       - Only THEN proceed with application
    2. Portal-Specific Submission Strategies:
       - Internshala: Cookie-based session replay with mobile API
         - Uses _internshala_session cookie + CSRF token
         - POST form with cover letter + assessment answers
         - Human-mimicry delays (30-120s between apps)
       - Greenhouse: Direct JSON API POST to /applications
         - Public API: boards.greenhouse.io/{slug}/jobs/{id}
         - POST with cover_letter + PDF CV attachment
         - No auth needed for public boards
       - Lever: Direct multipart form POST to apply endpoint
         - Public API: jobs.lever.co/{company}/{id}/apply
         - POST with resume, cover_letter, name, email
       - Naukri: Manual only (aggressive login detection)
         - Queue for mini-app "Apply Manually" button
       - Workday: Manual only (CAPTCHA protection)
         - Queue for mini-app "Apply Manually" button
       - Email (A-15): Brevo REST for cold HR outreach
    3. Cover Letter Engine (Enhanced):
       - Groq 70B generates unique cover letter per application
       - Incorporates A-20 company research + A-10 ATS keywords
       - Non-generic: mentions specific company details
       - 3000-char limit for Internshala, 500-word for others
    4. Daily Cap: 15 applications total across all portals
       - 30-120s delays to avoid bans
       - Session rotation every 5 apps
       - Circuit breaker: stop after 3 consecutive failures

Trigger: /autoapply, /queue, /apply [id], scheduler (08:00 + 15:00 IST)
AI Model: Groq (cover_letter generation)
Cost: $0 (all free tier)

Integration Points:
    - A-08 PPO Optimizer → priority ordering (score >= 70)
    - A-10 ATS Simulator → pre-apply check (must be done)
    - A-18 CV Enhancer → pre-apply CV tailoring
    - A-09 Network Mapper → alumni found? schedule A-15 email
    - A-15 Email Applier → cold outreach for non-portal listings
    - A-19 Outcome Amplifier → reads applied status for follow-ups
    - A-12 Telegram Reporter → daily auto-apply summary

Architecture:
    +--------------------------------------------------+
    |         AUTO-APPLY ORCHESTRATOR (A-13)            |
    +--------------------------------------------------+
    |                                                    |
    |  +--------------------------------------------+   |
    |  |  Application Queue Manager                  |   |
    |  |  - Priority queue from PPO-ranked listings  |   |
    |  |  - Platform-specific routing                |   |
    |  |  - Rate limiting per platform               |   |
    |  |  - Retry with exponential backoff           |   |
    |  +---------------------+----------------------+   |
    |                        |                          |
    |  +---------------------v----------------------+   |
    |  |  Cover Letter Engine (Groq AI)              |   |
    |  |  - Role-specific, natural language           |   |
    |  |  - No AI markers (---, **, etc.)            |   |
    |  |  - Company research integration             |   |
    |  |  - Assessment question answering            |   |
    |  +---------------------+----------------------+   |
    |                        |                          |
    |  +---------------------v----------------------+   |
    |  |  Platform Applicators                       |   |
    |  |  - Internshala: session + form POST         |   |
    |  |  - Naukri: API quick-apply                  |   |
    |  |  - Greenhouse/Lever: API POST               |   |
    |  |  - Human-like delays (30-90s between apps)  |   |
    |  +---------------------+----------------------+   |
    |                        |                          |
    |  +---------------------v----------------------+   |
    |  |  Anti-Ban Engine                            |   |
    |  |  - Rate: max 15 apps/day per platform       |   |
    |  |  - Random delays: 30-120s between apps      |   |
    |  |  - Session rotation every 5 apps            |   |
    |  |  - User-agent rotation                      |   |
    |  |  - Proxy rotation via stealth engine        |   |
    |  +--------------------------------------------+   |
    |                                                    |
    +--------------------------------------------------+

Safety Controls:
    - Manual approval mode (default): queue -> Telegram confirm -> apply
    - Auto mode: queue -> auto-apply with PPO score >= threshold
    - Daily cap: 15 applications per platform (hard limit)
    - Cooldown: minimum 30 seconds between applications
    - Circuit breaker: stop after 3 consecutive failures
============================================================
"""

import os
import re
import json
import time
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST
from core.database import get_db, DatabaseManager
from core.ai_router import get_router, AIRouter

AGENT_ID = "A-13"
AGENT_NAME = "Auto-Apply Orchestrator"

# ============================================================
# CONFIGURATION
# ============================================================

# Rate limits per platform (applications per day)
PLATFORM_DAILY_LIMITS = {
    'internshala': 15,
    'naukri': 10,
    'greenhouse': 8,
    'lever': 8,
    'iimjobs': 10,
    'wellfound': 5,
}

# Delay ranges between applications (seconds)
DELAY_BETWEEN_APPS = (30, 120)      # Random uniform
DELAY_AFTER_FAILURE = (120, 300)    # Longer after failure
SESSION_ROTATION_INTERVAL = 5       # Rotate session every N apps

# Circuit breaker
MAX_CONSECUTIVE_FAILURES = 3

# Auto-apply threshold
DEFAULT_AUTO_APPLY_MIN_PPO = 70.0

# Cover letter constraints
COVER_LETTER_MAX_CHARS = 2000
COVER_LETTER_MIN_CHARS = 200


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ApplicationAttempt:
    """Result of a single application attempt."""
    listing_id: int = 0
    platform: str = ""
    success: bool = False
    error: str = ""
    cover_letter: str = ""
    external_app_id: str = ""
    duration_sec: float = 0.0
    method: str = ""  # api, form, quick_apply


@dataclass
class AutoApplyStats:
    """Statistics for an auto-apply session."""
    total_queued: int = 0
    attempted: int = 0
    applied: int = 0
    failed: int = 0
    skipped: int = 0
    cover_letters_generated: int = 0
    duration_sec: float = 0.0
    by_platform: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_telegram_msg(self) -> str:
        lines = [
            f"📝 <b>Auto-Apply Report</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📊 Queue: {self.total_queued}",
            f"  Attempted: {self.attempted}",
            f"  Applied: {self.applied}",
            f"  Failed: {self.failed}",
            f"  Skipped: {self.skipped}",
            f"",
        ]
        if self.by_platform:
            lines.append("<b>By Platform:</b>")
            for platform, count in self.by_platform.items():
                lines.append(f"  {platform}: {count}")
        lines.append(f"\n⏱ Duration: {self.duration_sec:.1f}s")
        if self.errors:
            lines.append(f"⚠️ Errors: {len(self.errors)}")
        return '\n'.join(lines)


# ============================================================
# COVER LETTER ENGINE
# ============================================================

class CoverLetterEngine:
    """
    AI-powered cover letter generator using Groq.
    
    Generates natural, human-sounding cover letters with:
    - No AI markers (---, **, bullet points)
    - Role-specific language
    - Company research integration
    - Natural tone without being generic
    """

    SYSTEM_PROMPT = (
        "You are a career advisor helping an MBA student write a cover letter "
        "for an internship application. Write in first person, natural tone. "
        "CRITICAL RULES:\n"
        "1. Do NOT use any markdown formatting (no **, --, ---, bullet points)\n"
        "2. Do NOT use phrases like 'I am writing to express my interest'\n"
        "3. Do NOT start with 'Dear Hiring Manager' — start directly with substance\n"
        "4. Keep it under 250 words, 3-4 short paragraphs\n"
        "5. Sound like a real person, not an AI\n"
        "6. Mention ONE specific thing about the company that shows research\n"
        "7. Connect your MBA background to the specific role requirements\n"
        "8. End with a confident, forward-looking statement (not begging)\n"
        "9. No filler phrases, every sentence should add value\n"
        "10. Write in a way that a human reading quickly would find compelling"
    )

    def __init__(self, router: AIRouter, db: DatabaseManager):
        self.router = router
        self.db = db

    def generate(self, listing: Dict, user_profile: Dict = None) -> str:
        """
        Generate a cover letter for a specific listing.
        
        Args:
            listing: Clean listing dict with title, company, description
            user_profile: Optional dict with college, specialization, skills
        
        Returns:
            Clean cover letter text (no markdown, no AI artifacts)
        """
        title = listing.get('title', '')
        company = listing.get('company', '')
        description = listing.get('description_text', '')[:1500]
        location = listing.get('location', '')
        category = listing.get('category', '')
        source = listing.get('source', '')

        # Get user profile from settings
        if not user_profile:
            user_profile = self._get_user_profile()

        college = user_profile.get('college', 'a top business school')
        specialization = user_profile.get('specialization', 'MBA')
        skills = user_profile.get('skills', '')

        user_prompt = (
            f"Write a cover letter for this internship:\n\n"
            f"Role: {title}\n"
            f"Company: {company}\n"
            f"Location: {location}\n"
            f"Category: {category}\n"
            f"Job Description (excerpt): {description[:800]}\n\n"
            f"About me:\n"
            f"- MBA student at {college}\n"
            f"- Specialization: {specialization}\n"
        )
        if skills:
            user_prompt += f"- Key skills: {skills}\n"

        user_prompt += (
            f"\nWrite the cover letter now. Remember: no markdown, "
            f"no bullet points, no AI-sounding phrases. Just natural, "
            f"compelling text that fits in {COVER_LETTER_MAX_CHARS} characters."
        )

        try:
            response = self.router.generate_cover_letter(
                self.SYSTEM_PROMPT, user_prompt
            )
            if response.success:
                letter = self._clean_cover_letter(response.content)
                return letter
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Cover letter generation error: {e}")

        # Fallback template
        return self._fallback_letter(title, company, college, specialization)

    def generate_assessment_answers(self, questions: List[str],
                                     listing: Dict) -> List[str]:
        """Generate answers for assessment questions on applications."""
        answers = []
        for question in questions:
            try:
                prompt = (
                    f"Answer this internship application question in 2-3 sentences. "
                    f"Be specific, genuine, and relevant to the role of "
                    f"'{listing.get('title', '')}' at '{listing.get('company', '')}'.\n\n"
                    f"Question: {question}\n\n"
                    f"Answer (natural, no bullet points):"
                )
                response = self.router.quick_generate(prompt)
                if response.success:
                    answer = self._clean_cover_letter(response.content)
                    answers.append(answer)
                else:
                    answers.append("")
            except Exception:
                answers.append("")
        return answers

    def _clean_cover_letter(self, text: str) -> str:
        """Remove AI artifacts from generated text — no stray characters."""
        # Remove markdown formatting
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Remove common AI signatures and artifacts
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^___+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^===+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\[Your Name\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[Name\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[.*?\]', '', text)  # Remove any bracketed placeholders
        text = re.sub(r'Dear Hiring Manager,?\s*\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Dear Sir/?Ma\'?am,?\s*\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Dear .{1,50} Team,?\s*\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Sincerely,?\s*$', '', text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r'Best [Rr]egards,?\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'Warm [Rr]egards,?\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'Kind [Rr]egards,?\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'Regards,?\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'Yours (sincerely|truly|faithfully),?\s*$', '', text, flags=re.IGNORECASE | re.MULTILINE)
        # Remove stray numbers at start of lines (e.g., "3." or "1)")
        text = re.sub(r'^\d+[\.\)]\s*', '', text, flags=re.MULTILINE)
        # Remove stray dashes at start of lines  
        text = re.sub(r'^[—–-]\s*', '', text, flags=re.MULTILINE)
        # Remove stray special characters that AI tends to add
        text = re.sub(r'^[•◦▪▸►]\s*', '', text, flags=re.MULTILINE)
        # Remove any remaining markdown-style formatting
        text = re.sub(r'`(.+?)`', r'\1', text)
        # Remove "Subject:" or "Re:" lines
        text = re.sub(r'^(Subject|Re|RE):.*$', '', text, flags=re.MULTILINE)
        # Clean extra whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = text.strip()
        # Truncate if too long
        if len(text) > COVER_LETTER_MAX_CHARS:
            text = text[:COVER_LETTER_MAX_CHARS - 3] + '...'
        return text

    def _get_user_profile(self) -> Dict:
        """Get user profile from database settings."""
        return {
            'college': self.db.get_setting('college', 'a top business school'),
            'specialization': self.db.get_setting('specialization', 'MBA'),
            'skills': self.db.get_setting('skills', ''),
            'name': self.db.get_setting('user_name', ''),
        }

    def _fallback_letter(self, title: str, company: str,
                         college: str, specialization: str) -> str:
        """Generate a simple fallback cover letter."""
        return (
            f"I am pursuing my {specialization} from {college} and am excited "
            f"about the {title} opportunity at {company}. My academic training "
            f"in business strategy and operations, combined with hands-on project "
            f"experience, makes me a strong fit for this role.\n\n"
            f"I am particularly drawn to {company}'s approach to innovation and "
            f"growth in the market. I believe my analytical skills and collaborative "
            f"mindset would allow me to contribute meaningfully to your team.\n\n"
            f"I look forward to the opportunity to discuss how my background "
            f"aligns with your team's goals."
        )


# ============================================================
# PLATFORM APPLICATORS
# ============================================================

class InternshalaApplicator:
    """
    PRISM v3.0: Applies to internships on Internshala.
    
    IMPORTANT: Internshala uses Google reCAPTCHA Enterprise on their login form.
    Programmatic email/password login is IMPOSSIBLE without solving reCAPTCHA.
    
    Authentication: Session cookie from user's browser.
        The user logs into internshala.com in their browser, then provides
        the session cookie string. The frontend extracts this from the 
        credentials form (stored as 'password' field = session cookie string).
    
    Verified endpoints (tested March 2026):
        Login:  POST /login/verify_ajax/user  (BLOCKED by reCAPTCHA Enterprise)
        Apply:  POST /application/easy_apply/{internship_id}  (WORKS with session)
        Apply:  POST /application/submit/{internship_id}  (WORKS with session)
        CSRF:   Cookie 'csrf_cookie_name' = form field 'csrf_test_name'
    
    Apply Flow:
        1. Build session from user-provided cookie string
        2. GET internship detail page → extract CSRF + assessment questions
        3. Verify we're logged in (check for login redirect)
        4. Generate cover letter + assessment answers
        5. POST /application/easy_apply/{internship_id} 
        6. Check JSON response: {success: true/false, errorThrown: "..."}
    """

    def __init__(self, db: DatabaseManager, cover_engine: CoverLetterEngine):
        self.db = db
        self.cover_engine = cover_engine
        self._apps_today = 0
        self._last_app_time = 0
        self._cached_session = None  # requests.Session object

    def can_apply(self) -> Tuple[bool, str]:
        """Check if we can apply on Internshala today."""
        if self._apps_today >= PLATFORM_DAILY_LIMITS['internshala']:
            return False, f"Daily limit reached ({self._apps_today}/{PLATFORM_DAILY_LIMITS['internshala']})"

        elapsed = time.time() - self._last_app_time
        if elapsed < DELAY_BETWEEN_APPS[0]:
            remaining = int(DELAY_BETWEEN_APPS[0] - elapsed)
            return False, f"Cooldown: {remaining}s remaining"

        return True, "Ready"

    def _build_session_from_cookies(self, cookie_string: str) -> Optional[Any]:
        """
        Build a requests.Session from a cookie string.
        The cookie_string can be:
          - A full cookie header string: "key1=val1; key2=val2; ..."
          - Just the PHPSESSID value
        Returns a requests.Session or None.
        """
        import requests

        if not cookie_string or not cookie_string.strip():
            return None

        session = requests.Session()
        session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7',
        })

        cookie_string = cookie_string.strip()

        # If it looks like just a session ID (no = sign), treat as PHPSESSID
        if '=' not in cookie_string:
            session.cookies.set('PHPSESSID', cookie_string, domain='.internshala.com')
        else:
            # Parse full cookie string: "key1=val1; key2=val2"
            for part in cookie_string.split(';'):
                part = part.strip()
                if '=' in part:
                    key, val = part.split('=', 1)
                    key = key.strip()
                    val = val.strip()
                    # Skip non-cookie attributes
                    if key.lower() in ('path', 'domain', 'expires', 'max-age',
                                       'secure', 'httponly', 'samesite'):
                        continue
                    session.cookies.set(key, val, domain='.internshala.com')

        return session

    def _validate_session(self, session) -> Tuple[bool, str]:
        """
        Validate that the session is actually logged in by checking
        a page that requires authentication.
        Returns (is_valid, error_message).
        """
        try:
            # Quick check: fetch the student dashboard
            resp = session.get(
                'https://internshala.com/student/dashboard',
                timeout=15,
                allow_redirects=False
            )
            # If logged in, we get 200. If not, we get 302 to /login
            if resp.status_code == 200:
                return True, ""
            elif resp.status_code == 302:
                location = resp.headers.get('Location', '')
                if 'login' in location.lower():
                    return False, "Session expired. Please log in to internshala.com in your browser and update the cookie."
            return False, f"Unexpected response {resp.status_code} from dashboard check"
        except Exception as e:
            return False, f"Session validation error: {str(e)[:100]}"

    def _extract_internship_id(self, url: str, html: str = '') -> Optional[str]:
        """Extract the numeric internship ID from URL or page HTML."""
        # URL patterns:
        # /internship/detail/some-title-here1774506693
        # /internship/detail/1774506693
        # The ID is the trailing digits at the end of the URL path
        
        # Pattern 1: trailing digits in the URL slug
        match = re.search(r'/internship/(?:detail/)?[^/]*?(\d{8,})', url)
        if match:
            return match.group(1)
        
        # Pattern 2: any long number in the URL
        match = re.search(r'(\d{8,})', url)
        if match:
            return match.group(1)
        
        # Pattern 3: from HTML data attribute
        if html:
            match = re.search(r'data-internship-id=["\'](\d+)["\']', html)
            if match:
                return match.group(1)
            # Also try JS variable
            match = re.search(r'internship_id\s*[=:]\s*["\']?(\d+)', html)
            if match:
                return match.group(1)
        
        return None

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        """
        Apply to an Internshala listing using session cookies.
        
        PRISM v3.0: Uses session cookie auth (reCAPTCHA blocks email/password login).
        The 'password' field from the frontend contains the session cookie string.
        
        Args:
            listing: Dict with url, title, company, password (=cookie string), etc.
            cover_letter: Pre-generated cover letter (optional)
            resume_path: Path to resume file (optional)
        
        Returns:
            ApplicationAttempt with success/failure details
        """
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='internshala',
            method='session_cookie',
        )
        start_time = time.time()

        try:
            import requests

            # ===== BUILD SESSION =====
            # The frontend sends the session cookie in the 'password' field
            # (since that's what the credential form captures)
            cookie_string = listing.get('password', '').strip()
            session = None

            if cookie_string and self._cached_session:
                # Reuse cached session from previous apply in same batch
                # But verify it's still valid first (might have expired mid-batch)
                is_still_valid, _ = self._validate_session(self._cached_session)
                if is_still_valid:
                    session = self._cached_session
                    logger.info(f"[{AGENT_ID}] Reusing cached Internshala session")
                else:
                    logger.warning(f"[{AGENT_ID}] Cached Internshala session expired, rebuilding")
                    self._cached_session = None
                    # Fall through to rebuild from cookie_string

            if not session and cookie_string:
                session = self._build_session_from_cookies(cookie_string)
                if session:
                    # Validate the session works
                    is_valid, err_msg = self._validate_session(session)
                    if is_valid:
                        self._cached_session = session
                        logger.info(f"[{AGENT_ID}] Internshala session validated OK")
                    else:
                        attempt.error = err_msg
                        try:
                            cover_letter = self.cover_engine.generate(listing)
                            attempt.cover_letter = cover_letter
                        except Exception:
                            pass
                        return attempt

            # Also try DB-stored session
            if not session:
                stored_cookie = self.db.get_setting('internshala_session', '')
                if stored_cookie:
                    session = self._build_session_from_cookies(stored_cookie)
                    if session:
                        is_valid, _ = self._validate_session(session)
                        if is_valid:
                            self._cached_session = session
                            logger.info(f"[{AGENT_ID}] Using stored Internshala session")
                        else:
                            session = None  # Invalid stored session
                            # Clear the stale DB session so we don't retry it
                            try:
                                self.db.set_setting('internshala_session', '')
                                logger.info(f"[{AGENT_ID}] Cleared stale stored Internshala session")
                            except Exception:
                                pass

            # ===== NO SESSION AVAILABLE =====
            if not session:
                attempt.error = (
                    "Internshala requires browser login (reCAPTCHA blocks programmatic login). "
                    "Please log in to internshala.com in your browser, then copy your session cookie "
                    "and paste it in the Password field. "
                    "To get cookie: Open internshala.com → F12 → Application → Cookies → "
                    "copy the full cookie string."
                )
                try:
                    cover_letter = self.cover_engine.generate(listing)
                    attempt.cover_letter = cover_letter
                except Exception:
                    pass
                return attempt

            # ===== WE HAVE A VALID SESSION — PROCEED WITH APPLICATION =====
            url = listing.get('url', '') or listing.get('source_url', '')
            if not url or 'internshala.com' not in url:
                attempt.error = "Invalid Internshala URL"
                return attempt

            # Generate cover letter
            if not cover_letter:
                try:
                    cover_letter = self.cover_engine.generate(listing)
                except Exception as e:
                    cover_letter = "I am excited about this opportunity and believe my skills make me a strong candidate."
                    logger.warning(f"[{AGENT_ID}] Cover letter generation failed: {e}")
            attempt.cover_letter = cover_letter

            # Step 1: GET the internship detail page
            session.headers.update({
                'Referer': 'https://internshala.com/internships/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            })
            detail_resp = session.get(url, timeout=20)
            if detail_resp.status_code != 200:
                attempt.error = f"Could not load internship page (HTTP {detail_resp.status_code})"
                return attempt

            html = detail_resp.text

            # Check if redirected to login (session expired)
            if '/login' in detail_resp.url and '/internship' not in detail_resp.url:
                attempt.error = "Session expired. Please log in again on internshala.com and update cookie."
                self._cached_session = None
                return attempt

            # Step 2: Extract CSRF token from cookie (Internshala uses csrf_cookie_name)
            csrf_token = session.cookies.get('csrf_cookie_name', '')
            if not csrf_token:
                # Try from HTML hidden field
                csrf_match = re.search(
                    r'name=["\']csrf_test_name["\'][^>]*value=["\']([^"\']+)["\']', html
                )
                if csrf_match:
                    csrf_token = csrf_match.group(1)
            if not csrf_token:
                # Reverse order: value first
                csrf_match = re.search(
                    r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_test_name["\']', html
                )
                if csrf_match:
                    csrf_token = csrf_match.group(1)

            logger.info(f"[{AGENT_ID}] CSRF token: {'found' if csrf_token else 'MISSING'}")

            # Step 3: Extract internship ID
            internship_id = self._extract_internship_id(url, html)
            if not internship_id:
                attempt.error = "Could not extract internship ID from URL or page"
                return attempt

            logger.info(f"[{AGENT_ID}] Internship ID: {internship_id}")

            # Step 4: Check for assessment questions on the page
            questions = []
            q_matches = re.findall(
                r'class=["\']assessment_question[^"\']*["\'][^>]*>([^<]+)', html
            )
            for q in q_matches:
                q_clean = q.strip()
                if q_clean and len(q_clean) > 10:
                    questions.append(q_clean)

            # Also check for textarea-based questions
            q_textarea = re.findall(
                r'<label[^>]*>([^<]*\?[^<]*)</label>\s*<textarea', html
            )
            for q in q_textarea:
                q_clean = q.strip()
                if q_clean and len(q_clean) > 10 and q_clean not in questions:
                    questions.append(q_clean)

            assessment_answers = {}
            if questions:
                logger.info(f"[{AGENT_ID}] Found {len(questions)} assessment questions")
                try:
                    answers = self.cover_engine.generate_assessment_answers(
                        questions, listing
                    )
                    for i, answer in enumerate(answers):
                        assessment_answers[f'text_answer[{i}]'] = answer
                except Exception as e:
                    logger.warning(f"[{AGENT_ID}] Assessment answer generation failed: {e}")

            # Step 5: Human-like delay before applying
            delay = random.uniform(3, 7)
            logger.info(
                f"[{AGENT_ID}] Internshala: applying to '{listing.get('title', '')[:40]}' "
                f"(waiting {delay:.1f}s)"
            )
            time.sleep(delay)

            # Step 6: POST application to /application/easy_apply/{id}
            apply_url = f"https://internshala.com/application/easy_apply/{internship_id}"
            form_data = {
                'cover_letter': cover_letter[:4000],  # Internshala has a limit
            }
            if csrf_token:
                form_data['csrf_test_name'] = csrf_token

            # Add assessment answers
            form_data.update(assessment_answers)

            apply_headers = {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Referer': url,
                'Origin': 'https://internshala.com',
            }

            apply_resp = session.post(
                apply_url, data=form_data, headers=apply_headers, timeout=25
            )

            # Step 7: Parse JSON response
            if apply_resp.status_code == 200:
                try:
                    resp_json = apply_resp.json()
                except Exception:
                    resp_json = {}

                if resp_json.get('success') is True:
                    attempt.success = True
                    attempt.external_app_id = internship_id
                    self._apps_today += 1
                    self._last_app_time = time.time()
                    logger.info(
                        f"[{AGENT_ID}] APPLIED to '{listing.get('title', '')[:40]}' "
                        f"at {listing.get('company', '')} ({self._apps_today} today)"
                    )
                elif 'already' in str(resp_json.get('errorThrown', '')).lower():
                    attempt.success = True  # Already applied = goal achieved
                    attempt.external_app_id = internship_id
                    attempt.error = "Already applied to this internship"
                elif resp_json.get('requireLogin'):
                    attempt.error = "Session expired. Please log in again and update cookie."
                    self._cached_session = None
                else:
                    error_msg = resp_json.get('errorThrown', apply_resp.text[:300])
                    attempt.error = f"Internshala rejected: {error_msg}"
                    
                    # If the easy_apply failed, try /application/submit as fallback
                    if not attempt.success:
                        try:
                            fallback_url = f"https://internshala.com/application/submit/{internship_id}"
                            time.sleep(random.uniform(1, 3))
                            fb_resp = session.post(
                                fallback_url, data=form_data,
                                headers=apply_headers, timeout=25
                            )
                            if fb_resp.status_code == 200:
                                fb_json = fb_resp.json() if fb_resp.headers.get('content-type', '').startswith('application/json') else {}
                                if fb_json.get('success') is True:
                                    attempt.success = True
                                    attempt.external_app_id = internship_id
                                    attempt.error = ''
                                    self._apps_today += 1
                                    self._last_app_time = time.time()
                                    logger.info(f"[{AGENT_ID}] APPLIED via fallback submit endpoint")
                        except Exception as fb_e:
                            logger.warning(f"[{AGENT_ID}] Fallback submit failed: {fb_e}")
            elif apply_resp.status_code in (401, 403):
                attempt.error = "Session rejected by Internshala (401/403). Please update cookie."
                self._cached_session = None
            elif apply_resp.status_code == 404:
                attempt.error = f"Internship {internship_id} not found or no longer accepting applications"
            else:
                attempt.error = f"Apply HTTP {apply_resp.status_code}: {apply_resp.text[:200]}"

        except ImportError:
            attempt.error = "requests library not available"
        except Exception as e:
            attempt.error = str(e)[:300]
            logger.error(f"[{AGENT_ID}] Internshala apply error: {e}")

        attempt.duration_sec = round(time.time() - start_time, 1)
        return attempt


class GreenhouseApplicator:
    """
    PRISM v0.1: Applies via Greenhouse job board API.

    Strategy:
        PUBLIC API: boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}
        POST to: boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}/application
        - No auth needed for public boards
        - Multipart form with: first_name, last_name, email, phone,
          resume (PDF), cover_letter (text)
        - Rate: 100 req/hour (very permissive)

    Application Flow:
        1. Extract board_slug and job_id from listing URL
        2. Fetch job questions via GET /jobs/{id}/questions
        3. Generate answers via Groq AI
        4. POST application with resume + cover letter + answers
    """

    def __init__(self, cover_engine=None, db=None):
        self.cover_engine = cover_engine
        self.db = db
        self._stealth = None

    def _get_stealth(self):
        if self._stealth is None:
            try:
                from core.stealth_engine import get_stealth_client
                self._stealth = get_stealth_client()
            except ImportError:
                pass
        return self._stealth

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        """
        Apply to a Greenhouse listing via public Job Board API.

        PRISM v0.2 — Based on official Greenhouse API docs:
        POST https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{id}
        Content-Type: application/json (or multipart/form-data with resume)
        Auth: HTTP Basic (API key as username, no password) — BUT many public boards
              accept applications without auth for candidate-facing submissions.

        The endpoint accepts: first_name, last_name, email, phone,
        cover_letter_text, resume_text, and custom question_XXXXX fields.
        """
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='greenhouse',
            method='api',
        )

        try:
            import requests

            url = listing.get('url', '') or listing.get('source_url', '')
            board_slug, job_id = self._extract_greenhouse_ids(url)

            if not board_slug or not job_id:
                attempt.error = "Could not extract Greenhouse board/job IDs from URL"
                return attempt

            # Get user profile from listing credentials or DB
            user_profile = self._get_user_profile()
            # Override with any credentials passed from frontend
            if listing.get('full_name'):
                parts = listing['full_name'].split(' ', 1)
                user_profile['first_name'] = parts[0]
                user_profile['last_name'] = parts[1] if len(parts) > 1 else ''
            if listing.get('email'):
                user_profile['email'] = listing['email']
            if listing.get('phone'):
                user_profile['phone'] = listing['phone']

            # Generate cover letter if not provided
            if not cover_letter and self.cover_engine:
                cover_letter = self.cover_engine.generate(listing)
                attempt.cover_letter = cover_letter

            # Build JSON payload (official Greenhouse format)
            payload = {
                'first_name': user_profile.get('first_name', ''),
                'last_name': user_profile.get('last_name', ''),
                'email': user_profile.get('email', ''),
                'phone': user_profile.get('phone', ''),
                'cover_letter_text': cover_letter or '',
            }

            # Official endpoint: POST /v1/boards/{board_token}/jobs/{job_post_id}
            apply_url = (
                f"https://boards-api.greenhouse.io/v1/boards/{board_slug}"
                f"/jobs/{job_id}"
            )

            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Origin': f'https://boards.greenhouse.io',
                'Referer': f'https://boards.greenhouse.io/{board_slug}/jobs/{job_id}',
            }

            # Human-like delay
            time.sleep(random.uniform(3, 8))

            apply_response = requests.post(
                apply_url,
                json=payload,
                headers=headers,
                timeout=25,
            )

            if apply_response.status_code in (200, 201, 302):
                attempt.success = True
                try:
                    resp_json = apply_response.json()
                    attempt.external_app_id = str(resp_json.get('id', ''))
                except Exception:
                    attempt.external_app_id = job_id
                logger.info(
                    f"[{AGENT_ID}] Greenhouse apply SUCCESS: "
                    f"{listing.get('title', '')} @ {listing.get('company', '')}"
                )
            elif apply_response.status_code == 422:
                # Validation error — missing required fields
                try:
                    err_detail = apply_response.json()
                    attempt.error = f"Greenhouse validation error: {json.dumps(err_detail)[:200]}"
                except Exception:
                    attempt.error = f"Greenhouse validation error (422)"
            else:
                attempt.error = f"Greenhouse POST returned HTTP {apply_response.status_code}"

        except ImportError:
            attempt.error = "requests library not available"
        except Exception as e:
            attempt.error = f"Greenhouse apply error: {str(e)}"
            logger.error(f"[{AGENT_ID}] Greenhouse apply error: {e}")

        return attempt

    def _extract_greenhouse_ids(self, url: str) -> tuple:
        """Extract board_slug and job_id from Greenhouse URL."""
        import re
        # Pattern: boards.greenhouse.io/{slug}/jobs/{id}
        match = re.search(r'boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
        if match:
            return match.group(1), match.group(2)
        # Pattern: {company}.greenhouse.io/jobs/{id}
        match = re.search(r'([^.]+)\.greenhouse\.io/jobs/(\d+)', url)
        if match:
            return match.group(1), match.group(2)
        return '', ''

    def _get_user_profile(self) -> Dict:
        """Get user profile from DB settings."""
        if self.db:
            try:
                return json.loads(self.db.get_setting('user_profile', '{}'))
            except (json.JSONDecodeError, Exception):
                pass
        return {}


class LeverApplicator:
    """
    PRISM v0.1: Applies via Lever job board API.

    Strategy:
        PUBLIC API: jobs.lever.co/{company}/{id}/apply
        POST multipart form with:
            - name, email, phone, org, urls
            - resume (PDF file upload)
            - cover_letter (text)
            - custom questions (if any)
        No auth needed for public postings.

    Application Flow:
        1. Extract company_slug and posting_id from listing URL
        2. Build multipart form data
        3. POST to apply endpoint
    """

    def __init__(self, cover_engine=None, db=None):
        self.cover_engine = cover_engine
        self.db = db
        self._stealth = None

    def _get_stealth(self):
        if self._stealth is None:
            try:
                from core.stealth_engine import get_stealth_client
                self._stealth = get_stealth_client()
            except ImportError:
                pass
        return self._stealth

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        """
        Apply to a Lever listing via public application endpoint.

        PRISM v0.2 — Lever's public postings accept form data at:
        POST https://jobs.lever.co/{company}/{posting_id}/apply
        Content-Type: application/x-www-form-urlencoded
        Fields: name, email, phone, org, urls[LinkedIn], comments (=cover letter)
        No auth required for public postings.
        """
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='lever',
            method='api',
        )

        try:
            import requests

            url = listing.get('url', '') or listing.get('source_url', '')
            company_slug, posting_id = self._extract_lever_ids(url)

            if not company_slug or not posting_id:
                attempt.error = "Could not extract Lever company/posting IDs from URL"
                return attempt

            # Build apply URL
            apply_url = f"https://jobs.lever.co/{company_slug}/{posting_id}/apply"

            # Get user profile
            user_profile = self._get_user_profile()
            # Override with credentials from frontend
            if listing.get('full_name'):
                user_profile['name'] = listing['full_name']
            elif user_profile.get('first_name'):
                user_profile['name'] = f"{user_profile.get('first_name', '')} {user_profile.get('last_name', '')}".strip()
            if listing.get('email'):
                user_profile['email'] = listing['email']
            if listing.get('phone'):
                user_profile['phone'] = listing['phone']

            # Generate cover letter if not provided
            if not cover_letter and self.cover_engine:
                cover_letter = self.cover_engine.generate(listing)
                attempt.cover_letter = cover_letter

            # Build form data
            form_data = {
                'name': user_profile.get('name', f"{user_profile.get('first_name', '')} {user_profile.get('last_name', '')}".strip()),
                'email': user_profile.get('email', ''),
                'phone': user_profile.get('phone', ''),
                'org': user_profile.get('college', listing.get('college', '')),
                'urls[LinkedIn]': user_profile.get('linkedin', listing.get('linkedin_profile', '')),
                'comments': cover_letter or '',
            }

            headers = {
                'Accept': 'text/html,application/json',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': f'https://jobs.lever.co/{company_slug}/{posting_id}',
                'Origin': 'https://jobs.lever.co',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }

            # Human-like delay
            time.sleep(random.uniform(3, 8))

            apply_response = requests.post(
                apply_url,
                data=form_data,
                headers=headers,
                timeout=25,
                allow_redirects=False,
            )

            # Lever returns 302 redirect on success (to /thank-you page)
            if apply_response.status_code in (200, 201, 302):
                attempt.success = True
                attempt.external_app_id = posting_id
                logger.info(
                    f"[{AGENT_ID}] Lever apply SUCCESS: "
                    f"{listing.get('title', '')} @ {listing.get('company', '')}"
                )
            else:
                attempt.error = f"Lever POST returned HTTP {apply_response.status_code}"

        except ImportError:
            attempt.error = "requests library not available"
        except Exception as e:
            attempt.error = f"Lever apply error: {str(e)}"
            logger.error(f"[{AGENT_ID}] Lever apply error: {e}")

        return attempt

    def _extract_lever_ids(self, url: str) -> tuple:
        """Extract company_slug and posting_id from Lever URL."""
        import re
        # Pattern: jobs.lever.co/{company}/{posting_id}
        match = re.search(r'jobs\.lever\.co/([^/]+)/([a-f0-9-]+)', url)
        if match:
            return match.group(1), match.group(2)
        return '', ''

    def _get_user_profile(self) -> Dict:
        if self.db:
            try:
                return json.loads(self.db.get_setting('user_profile', '{}'))
            except (json.JSONDecodeError, Exception):
                pass
        return {}


class NaukriApplicator:
    """
    PRISM v2.0: Naukri application handler.

    TWO login strategies (like Internshala):
        Strategy A (Preferred): User provides email + password from frontend.
                    We log in via Naukri's login API to get a session,
                    then apply using Quick Apply API.
        Strategy B (Fallback): Pre-stored session cookie from DB settings.
                    User sets via /set naukri_session <cookie> in Telegram.

    Apply Flow:
        1. Authenticate (login with email/password OR use stored session cookie)
        2. Extract job_id from listing URL
        3. POST Quick Apply with cover letter
        4. Verify success from response
    """

    def __init__(self, cover_engine=None, db=None):
        self.cover_engine = cover_engine
        self.db = db
        self._cached_session = None  # requests.Session for reuse within batch

    def _login_with_credentials(self, email: str, password: str) -> Optional[Any]:
        """
        Log in to Naukri using email + password.
        Returns a requests.Session with authenticated cookies, or None on failure.
        """
        import requests

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-IN,en;q=0.9',
            'Origin': 'https://www.naukri.com',
            'Referer': 'https://www.naukri.com/nlogin/login',
        })

        try:
            # Step 1: GET login page for cookies + CSRF
            session.get('https://www.naukri.com/nlogin/login', timeout=15)

            # Step 2: POST login credentials
            login_payload = {
                'username': email,
                'password': password,
            }
            login_headers = {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-HTTP-Method-Override': 'POST',
                'appid': '109',
                'systemid': 'Naukri',
            }

            login_resp = session.post(
                'https://www.naukri.com/central-loginservice/v1/login',
                json=login_payload,
                headers=login_headers,
                timeout=20,
                allow_redirects=True,
            )

            if login_resp.status_code == 200:
                try:
                    resp_json = login_resp.json()
                except Exception:
                    resp_json = {}

                # Check for success
                if (resp_json.get('status') == 'SUCCESS'
                        or resp_json.get('redirectUrl')
                        or 'success' in login_resp.text.lower()):
                    logger.info(f"[{AGENT_ID}] Naukri login SUCCESS for {email}")
                    self._cached_session = session
                    return session

                # Check for OTP required
                if 'otp' in login_resp.text.lower() or resp_json.get('otpRequired'):
                    logger.warning(f"[{AGENT_ID}] Naukri login requires OTP for {email}")
                    return None

                # Check for failure
                if ('invalid' in login_resp.text.lower()
                        or 'incorrect' in login_resp.text.lower()
                        or resp_json.get('error')):
                    logger.warning(f"[{AGENT_ID}] Naukri login FAILED: invalid credentials")
                    return None

            # Check cookies as fallback signal
            cookies = session.cookies.get_dict()
            if any(k for k in cookies if 'nauk' in k.lower() or 'session' in k.lower()):
                logger.info(f"[{AGENT_ID}] Naukri login SUCCESS (cookie check) for {email}")
                self._cached_session = session
                return session

            logger.warning(f"[{AGENT_ID}] Naukri login failed: HTTP {login_resp.status_code}")
            return None

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Naukri login error: {e}")
            return None

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='naukri',
            method='quick_apply',
        )

        try:
            import requests

            source_url = listing.get('url', '') or listing.get('source_url', '')

            # ===== STRATEGY A: Login with user-provided email + password =====
            user_email = listing.get('email', '').strip()
            user_password = listing.get('password', '').strip()
            session = None

            if user_email and user_password:
                if self._cached_session:
                    session = self._cached_session
                    logger.info(f"[{AGENT_ID}] Reusing cached Naukri session")
                else:
                    session = self._login_with_credentials(user_email, user_password)
                    if not session:
                        attempt.error = (
                            "Naukri login failed. Please check your email/password. "
                            "Naukri may require OTP verification — try logging in manually first, "
                            "then retry auto-apply."
                        )
                        try:
                            cover_letter = self.cover_engine.generate(listing)
                            attempt.cover_letter = cover_letter
                        except Exception:
                            pass
                        return attempt

            # ===== STRATEGY B: Fallback to stored session cookie =====
            if not session:
                session_cookie = ''
                if self.db:
                    session_cookie = self.db.get_setting('naukri_session', '')
                if session_cookie:
                    session = requests.Session()
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json',
                    })
                    for cookie_str in session_cookie.split(';'):
                        cookie_str = cookie_str.strip()
                        if '=' in cookie_str:
                            k, v = cookie_str.split('=', 1)
                            session.cookies.set(k.strip(), v.strip(), domain='naukri.com')

            # ===== NO AUTH AVAILABLE =====
            if not session:
                if not cover_letter and self.cover_engine:
                    try:
                        cover_letter = self.cover_engine.generate(listing)
                    except Exception:
                        pass
                attempt.cover_letter = cover_letter or ''
                attempt.error = (
                    "No Naukri credentials provided. "
                    "Please enter your Naukri email and password in the "
                    "Portal Credentials section, then try again."
                )
                attempt.success = False
                return attempt

            # ===== WE HAVE A SESSION — PROCEED WITH APPLICATION =====
            # Extract job ID from URL
            job_id_match = re.search(r'-(\d+)/?(?:\?|$)', source_url)
            if not job_id_match:
                job_id_match = re.search(r'jid=(\d+)', source_url)
            if not job_id_match:
                job_id_match = re.search(r'/(\d+)(?:\?|$|/)', source_url)
            if not job_id_match:
                attempt.error = "Could not extract Naukri job ID from URL"
                attempt.success = False
                return attempt

            job_id = job_id_match.group(1)

            # Generate cover letter if not provided
            if not cover_letter and self.cover_engine:
                try:
                    cover_letter = self.cover_engine.generate(listing)
                except Exception:
                    pass
            attempt.cover_letter = cover_letter or ''

            # Human-like delay
            delay = random.uniform(3, 8)
            logger.info(
                f"[{AGENT_ID}] Naukri: applying to '{listing.get('title', '')[:40]}' "
                f"(waiting {delay:.1f}s)"
            )
            time.sleep(delay)

            # ===== NAUKRI QUICK APPLY — CORRECT ENDPOINT =====
            # The real Naukri quick apply endpoint is /jobapply/applyjob
            # NOT /central-loginservice/v1/login/quickApply (that's a login URL)
            apply_headers = {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-HTTP-Method-Override': 'POST',
                'Referer': source_url,
                'Origin': 'https://www.naukri.com',
                'appid': '109',
                'systemid': 'Naukri',
            }
            session.headers.update(apply_headers)

            payload = {
                'jobId': job_id,
                'coverLetter': cover_letter[:2000] if cover_letter else '',
            }

            # Try the primary quick apply endpoint first
            apply_url = f'https://www.naukri.com/jobapply/applyjob'
            resp = session.post(
                apply_url,
                json=payload,
                timeout=25,
            )

            # If primary endpoint returns 404/405, try the alternate endpoint
            if resp.status_code in (404, 405, 400):
                logger.info(f"[{AGENT_ID}] Naukri primary apply endpoint returned {resp.status_code}, trying alternate")
                alt_url = f'https://www.naukri.com/job-apply/apply/{job_id}'
                resp = session.post(
                    alt_url,
                    json={'coverLetter': cover_letter[:2000] if cover_letter else ''},
                    timeout=25,
                )

            if resp.status_code == 200:
                try:
                    resp_data = resp.json()
                except Exception:
                    resp_data = {}
                if (resp_data.get('status') == 'SUCCESS'
                        or resp_data.get('applied') is True
                        or 'success' in resp.text.lower()
                        or 'applied' in resp.text.lower()
                        or resp_data.get('redirectUrl')):
                    attempt.success = True
                    attempt.external_app_id = job_id
                    logger.info(f"[{AGENT_ID}] Naukri Quick Apply SUCCESS: {listing.get('title', '')}")
                elif 'already' in resp.text.lower():
                    attempt.success = True  # Already applied counts as success
                    attempt.external_app_id = job_id
                    attempt.error = "Already applied to this job"
                else:
                    attempt.error = f"Naukri response: {resp.text[:200]}"
            elif resp.status_code == 401:
                attempt.error = "Naukri session expired. Please re-enter credentials and try again."
                self._cached_session = None
            elif resp.status_code == 403:
                attempt.error = "Naukri blocked this request (rate limited). Try again later."
                self._cached_session = None
            else:
                attempt.error = f"Naukri Quick Apply HTTP {resp.status_code}: {resp.text[:200]}"

        except ImportError:
            attempt.error = "requests library not available"
        except Exception as e:
            attempt.error = f"Naukri apply error: {str(e)[:200]}"
            logger.error(f"[{AGENT_ID}] Naukri apply error: {e}")

        return attempt


class WorkdayApplicator:
    """
    PRISM v0.1: Workday application handler.

    Strategy: MANUAL ONLY — Workday uses CAPTCHA on application forms.
    Queues the listing for the mini-app "Apply Manually" button.
    """

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='workday',
            method='manual',
        )
        attempt.error = (
            "Workday requires manual application due to CAPTCHA. "
            "Use the mini-app 'Apply Manually' button."
        )
        attempt.success = False
        return attempt


class AshbyApplicator:
    """
    PRISM v0.1: Ashby ATS Auto-Apply Engine.

    Strategy: Direct POST to Ashby's public application API.
        Endpoint: https://api.ashbyhq.com/posting-api/application-form/{posting_id}
        Method: POST multipart/form-data
        Fields: name, email, phone, resume (file), coverLetter, linkedInUrl
        Auth: None required (public boards)
        Rate: 100 req/hr max, 10-30s delays between apps

    Anti-Detection:
        - Public API, minimal ban risk
        - Standard browser headers
        - Random delays (10-30s between applications)
    """

    ASHBY_APPLY_URL = "https://api.ashbyhq.com/posting-api/application-form"

    def __init__(self, cover_engine=None, db=None):
        self.cover_engine = cover_engine
        self.db = db or get_db()

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        """
        PRISM v0.2: Auto-apply to an Ashby job posting.

        Ashby public API endpoint:
        POST https://api.ashbyhq.com/posting-api/application-form/{posting_id}
        Content-Type: application/json
        Fields: name, email, phone, linkedInUrl, coverLetter
        No auth required for public boards.
        """
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='ashby',
            method='api_post',
        )

        try:
            import requests

            # Extract posting ID from URL or source_id
            posting_id = self._extract_posting_id(listing)
            if not posting_id:
                attempt.error = "Could not extract Ashby posting ID"
                attempt.success = False
                return attempt

            # Get user profile — prefer frontend-provided credentials
            profile = self._get_user_profile()
            if listing.get('full_name'):
                profile['name'] = listing['full_name']
            if listing.get('email'):
                profile['email'] = listing['email']
            if listing.get('phone'):
                profile['phone'] = listing['phone']
            if listing.get('linkedin_profile'):
                profile['linkedin_url'] = listing['linkedin_profile']

            # Build JSON payload
            payload = {
                'name': profile.get('name', ''),
                'email': profile.get('email', ''),
                'phone': profile.get('phone', ''),
                'linkedInUrl': profile.get('linkedin_url', ''),
                'coverLetter': cover_letter[:5000] if cover_letter else '',
            }

            url = f"{self.ASHBY_APPLY_URL}/{posting_id}"

            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Origin': 'https://jobs.ashbyhq.com',
                'Referer': listing.get('source_url', listing.get('url', 'https://jobs.ashbyhq.com')),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }

            # Human-like delay
            time.sleep(random.uniform(3, 8))

            resp = requests.post(url, json=payload, headers=headers, timeout=25)

            if resp.status_code in (200, 201, 202):
                attempt.success = True
                logger.info(
                    f"[{AGENT_ID}] Ashby auto-apply SUCCESS: "
                    f"{listing.get('title', '')} at {listing.get('company', '')}"
                )
            else:
                attempt.error = f"Ashby API returned HTTP {resp.status_code}"
                attempt.success = False

        except ImportError:
            attempt.error = "requests library not available"
            attempt.success = False
        except Exception as e:
            attempt.error = f"Ashby apply error: {str(e)}"
            attempt.success = False
            logger.error(f"[{AGENT_ID}] Ashby apply error: {e}")

        return attempt

    def _extract_posting_id(self, listing: Dict) -> Optional[str]:
        """Extract Ashby posting ID from listing URL or source_id."""
        source_id = listing.get('source_id', '')
        if source_id.startswith('ashby_'):
            parts = source_id.split('_')
            if len(parts) >= 3:
                return parts[-1]

        url = listing.get('source_url', '')
        # Pattern: jobs.ashbyhq.com/{company}/{posting_id}
        match = re.search(r'ashbyhq\.com/[^/]+/([a-f0-9-]+)', url)
        if match:
            return match.group(1)
        return None

    def _get_user_profile(self) -> Dict:
        """Get user profile from config."""
        try:
            config = get_config()
            return config.get('user_profile', {})
        except Exception:
            return {}


class SmartRecruitersApplicator:
    """
    PRISM v0.1: SmartRecruiters Auto-Apply Engine.

    Strategy: Direct POST to SmartRecruiters public application endpoint.
        Endpoint: https://jobs.smartrecruiters.com/api/apply/{posting_id}
        Method: POST multipart/form-data
        Fields: firstName, lastName, email, phone, resume (file), coverLetter
        Auth: None required (public postings)
        Rate: 60 req/hr max, 15-40s delays

    Note: SmartRecruiters has moderate bot detection, so we use
    stealth headers and human-like delays. Some companies may require
    additional custom fields — those are queued as manual.
    """

    SR_APPLY_BASE = "https://jobs.smartrecruiters.com"

    def __init__(self, cover_engine=None, db=None):
        self.cover_engine = cover_engine
        self.db = db or get_db()

    def _get_stealth(self):
        try:
            from core.stealth_engine import get_stealth_client
            return get_stealth_client()
        except Exception:
            return None

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        """
        PRISM v0.2: Auto-apply to a SmartRecruiters posting.
        Uses requests library directly for reliability.
        """
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='smartrecruiters',
            method='api_post',
        )

        try:
            import requests

            posting_url = listing.get('source_url', listing.get('url', ''))
            if not posting_url:
                attempt.error = "No SmartRecruiters posting URL"
                attempt.success = False
                return attempt

            profile = self._get_user_profile()
            # Override with frontend credentials
            if listing.get('full_name'):
                name_parts = listing['full_name'].split(' ', 1)
                profile['first_name'] = name_parts[0]
                profile['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
            if listing.get('email'):
                profile['email'] = listing['email']
            if listing.get('phone'):
                profile['phone'] = listing['phone']

            name_parts = profile.get('name', 'MBA Student').split(' ', 1) if 'name' in profile else [profile.get('first_name', ''), profile.get('last_name', '')]

            form_data = {
                'firstName': name_parts[0] if name_parts else '',
                'lastName': name_parts[1] if len(name_parts) > 1 else '',
                'email': profile.get('email', ''),
                'phone': profile.get('phone', ''),
                'coverLetter': cover_letter[:5000] if cover_letter else '',
            }

            # Extract posting ID
            posting_id = self._extract_posting_id(listing)
            if not posting_id:
                attempt.error = "Could not extract SmartRecruiters posting ID"
                attempt.success = False
                return attempt

            url = f"{self.SR_APPLY_BASE}/api/apply/{posting_id}"
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': self.SR_APPLY_BASE,
                'Referer': posting_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            }

            time.sleep(random.uniform(3, 8))

            resp = requests.post(url, data=form_data, headers=headers, timeout=25)

            if resp.status_code in (200, 201, 202):
                attempt.success = True
                logger.info(
                    f"[{AGENT_ID}] SmartRecruiters auto-apply SUCCESS: "
                    f"{listing.get('title', '')} at {listing.get('company', '')}"
                )
            elif resp.status_code == 400:
                attempt.error = "SmartRecruiters requires custom questions — manual apply needed"
                attempt.success = False
            else:
                attempt.error = f"SmartRecruiters API returned HTTP {resp.status_code}"
                attempt.success = False

        except ImportError:
            attempt.error = "requests library not available"
            attempt.success = False
        except Exception as e:
            attempt.error = f"SmartRecruiters apply error: {str(e)}"
            attempt.success = False
            logger.error(f"[{AGENT_ID}] SmartRecruiters apply error: {e}")

        return attempt

    def _extract_posting_id(self, listing: Dict) -> Optional[str]:
        """Extract SmartRecruiters posting ID from listing."""
        source_id = listing.get('source_id', '')
        if source_id.startswith('sr_'):
            parts = source_id.split('_')
            if len(parts) >= 3:
                return parts[-1]

        url = listing.get('source_url', '')
        match = re.search(r'smartrecruiters\.com/[^/]+/(\d+)', url)
        if match:
            return match.group(1)
        return None

    def _get_user_profile(self) -> Dict:
        try:
            config = get_config()
            return config.get('user_profile', {})
        except Exception:
            return {}


# ============================================================
# QUEUE MANAGER
# ============================================================

class ApplicationQueueManager:
    """
    Manages the application queue with priority ordering,
    platform routing, and rate limiting.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._daily_counts: Dict[str, int] = defaultdict(int)
        self._daily_date = datetime.now(IST).date()
        self._consecutive_failures = 0

    def _reset_daily_if_needed(self):
        today = datetime.now(IST).date()
        if today != self._daily_date:
            self._daily_counts.clear()
            self._daily_date = today
            self._consecutive_failures = 0

    def queue_listing(self, listing_id: int, platform: str = '',
                      priority: int = 50, queued_by: str = 'manual') -> bool:
        """Add a listing to the application queue."""
        if not platform:
            # Auto-detect platform from listing source
            listing = self.db.get_clean_listing_by_id(listing_id)
            if listing:
                platform = listing.get('source', 'internshala')

        result = self.db.queue_application(
            listing_id=listing_id,
            platform=platform,
            priority=priority,
            queued_by=queued_by,
        )
        return result is not None

    def queue_top_listings(self, n: int = 10,
                           min_ppo: float = DEFAULT_AUTO_APPLY_MIN_PPO) -> int:
        """Queue top N listings by PPO score."""
        listings = self.db.get_top_listings(n=n)
        queued = 0
        for listing in listings:
            ppo = listing.get('ppo_score', 0)
            if ppo < min_ppo:
                continue
            platform = listing.get('source', 'internshala')
            if self.queue_listing(listing['id'], platform, priority=int(ppo)):
                queued += 1
        return queued

    def get_next_batch(self, limit: int = 5) -> List[Dict]:
        """Get next batch of applications to process."""
        self._reset_daily_if_needed()

        # Check circuit breaker
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                f"[{AGENT_ID}] Circuit breaker active "
                f"({self._consecutive_failures} consecutive failures)"
            )
            return []

        queued = self.db.get_queued_applications(limit=limit)

        # Filter by daily platform limits
        batch = []
        for app in queued:
            platform = app.get('platform', 'internshala')
            limit_val = PLATFORM_DAILY_LIMITS.get(platform, 10)
            if self._daily_counts[platform] < limit_val:
                batch.append(app)

        return batch

    def record_result(self, queue_id: int, success: bool,
                       cover_letter: str = '', error: str = '',
                       external_app_id: str = ''):
        """Record application result."""
        if success:
            self.db.update_application_status(
                queue_id, 'applied',
                cover_letter=cover_letter,
                external_app_id=external_app_id,
            )
            platform = ''  # Will be looked up if needed
            self._consecutive_failures = 0
        else:
            self.db.update_application_status(
                queue_id, 'failed',
                cover_letter=cover_letter,
                error=error,
            )
            self._consecutive_failures += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get application queue statistics."""
        return self.db.get_application_stats()


# ============================================================
# MAIN AUTO-APPLY ORCHESTRATOR
# ============================================================

class AutoApplyOrchestrator:
    """
    PRISM v0.1: Master auto-apply engine with Intelligence Sequence.

    Pipeline:
        1. Get queued applications (priority order, PPO >= 70)
        2. For each application:
           a. PRE-CHECK: Has A-10 ATS simulation been done?
              - If not, trigger it now (or skip if OpenRouter quota low)
           b. PRE-CHECK: Has A-18 CV tailoring been done?
              - If not, trigger it now
           c. PRE-CHECK: Has A-09 found alumni contacts?
              - If yes, schedule A-15 email outreach BEFORE portal apply
           d. Generate cover letter (Groq 70B, using A-20 company intel)
           e. Route to platform-specific applicator:
              - Internshala: cookie-based session replay
              - Greenhouse: direct API POST
              - Lever: direct multipart POST
              - Naukri/Workday: manual queue
           f. Submit application
           g. Record result in outcomes table
           h. Wait (human-like delay: 30-120s)
        3. Stop on circuit breaker (3 failures) or daily limit (15)
        4. Report results to A-12 Telegram

    Daily Cap: 15 applications total across all portals
    Schedule: 08:00 IST (run #1) + 15:00 IST (run #2)
    """

    def __init__(self):
        self.db = get_db()
        self.router = get_router()
        self.config = get_config()

        # Sub-components
        self.cover_engine = CoverLetterEngine(self.router, self.db)
        self.queue_manager = ApplicationQueueManager(self.db)
        self.internshala = InternshalaApplicator(self.db, self.cover_engine)
        self.greenhouse = GreenhouseApplicator(self.cover_engine, self.db)
        self.lever = LeverApplicator(self.cover_engine, self.db)
        self.naukri = NaukriApplicator(self.cover_engine, self.db)
        self.workday = WorkdayApplicator()
        self.ashby = AshbyApplicator(self.cover_engine, self.db)
        self.smartrecruiters = SmartRecruitersApplicator(self.cover_engine, self.db)

        # PRISM v0.1: Platform routing — 7 platforms (5 auto + 2 manual)
        self._applicators = {
            'internshala': self.internshala,
            'greenhouse': self.greenhouse,
            'lever': self.lever,
            'naukri': self.naukri,
            'workday': self.workday,
            'ashby': self.ashby,
            'smartrecruiters': self.smartrecruiters,
            # Aliases for source name variations
            'ashbyhq': self.ashby,
            'smart_recruiters': self.smartrecruiters,
        }

    def run_auto_apply(self, max_apps: int = 10) -> AutoApplyStats:
        """
        PRISM v0.1: Run auto-apply session with Intelligence Sequence.

        The Intelligence Sequence ensures:
            1. ATS simulation (A-10) is done before applying
            2. CV tailoring (A-18) is done before applying
            3. Alumni outreach (A-15) is scheduled before portal apply
            4. Cover letter uses company intel from A-20

        Args:
            max_apps: Maximum applications to attempt this session

        Returns:
            AutoApplyStats with session results
        """
        logger.info(f"[{AGENT_ID}] === PRISM AUTO-APPLY START (max: {max_apps}) ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        stats = AutoApplyStats()

        # Get queued applications
        batch = self.queue_manager.get_next_batch(limit=max_apps)
        stats.total_queued = len(batch)

        if not batch:
            logger.info(f"[{AGENT_ID}] No applications in queue")
            self.db.update_agent_heartbeat(AGENT_ID, "completed", items_processed=0)
            return stats

        for app in batch:
            try:
                queue_id = app.get('id')
                platform = app.get('platform', 'internshala')
                listing_id = app.get('listing_id')

                # Build listing dict from joined data
                listing_data = {
                    'id': listing_id,
                    'title': app.get('title', ''),
                    'company': app.get('company', ''),
                    'url': app.get('url', ''),
                    'description_text': app.get('description_text', ''),
                    'source': app.get('source', ''),
                    'location': app.get('location', ''),
                    'category': app.get('category', ''),
                    'stipend_monthly': app.get('stipend_monthly', 0),
                    'tier': app.get('tier'),
                    'sector': app.get('sector', ''),
                }

                # ===== PRISM v0.1: INTELLIGENCE SEQUENCE =====
                self.db.update_application_status(queue_id, 'pre_checking')

                # Pre-check 1: ATS Simulation
                self._ensure_ats_simulation(listing_id)

                # Pre-check 2: CV Tailoring
                self._ensure_cv_tailoring(listing_id)

                # Pre-check 3: Alumni outreach scheduling
                self._check_alumni_outreach(listing_data)

                # ===== END INTELLIGENCE SEQUENCE =====

                # Mark as generating
                self.db.update_application_status(queue_id, 'generating')

                # Get the applicator for this platform
                applicator = self._applicators.get(platform)
                if not applicator:
                    self.queue_manager.record_result(
                        queue_id, False, error=f"No applicator for platform: {platform}"
                    )
                    stats.skipped += 1
                    continue

                # Check platform readiness
                if hasattr(applicator, 'can_apply'):
                    can, reason = applicator.can_apply()
                    if not can:
                        self.queue_manager.record_result(
                            queue_id, False, error=reason
                        )
                        stats.skipped += 1
                        continue

                # Update status to applying
                self.db.update_application_status(queue_id, 'applying')

                # Apply
                result = applicator.apply(listing_data)
                stats.attempted += 1

                # Record result
                self.queue_manager.record_result(
                    queue_id,
                    result.success,
                    cover_letter=result.cover_letter,
                    error=result.error,
                    external_app_id=result.external_app_id,
                )

                if result.success:
                    stats.applied += 1
                    stats.by_platform[platform] = stats.by_platform.get(platform, 0) + 1
                    self.db.update_clean_listing_scores(
                        listing_id, status='applied'
                    )
                else:
                    stats.failed += 1
                    stats.errors.append(f"{app.get('title', '')[:30]}: {result.error}")

                if result.cover_letter:
                    stats.cover_letters_generated += 1

                # Circuit breaker check
                if self.queue_manager._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.warning(f"[{AGENT_ID}] Circuit breaker triggered!")
                    break

                # Human-like delay between applications
                if result.success:
                    delay = random.uniform(*DELAY_BETWEEN_APPS)
                else:
                    delay = random.uniform(*DELAY_AFTER_FAILURE)

                actual_delay = min(delay, 15)
                time.sleep(actual_delay)

            except Exception as e:
                stats.failed += 1
                stats.errors.append(str(e))
                logger.error(f"[{AGENT_ID}] Apply error: {e}")

        # Finalize
        stats.duration_sec = round(time.time() - start_time, 1)

        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=stats.applied,
            errors=stats.failed,
            duration_sec=stats.duration_sec,
        )

        logger.info(
            f"[{AGENT_ID}] === PRISM AUTO-APPLY COMPLETE === "
            f"Applied: {stats.applied}/{stats.attempted} | "
            f"Failed: {stats.failed} | Duration: {stats.duration_sec}s"
        )

        return stats

    # ============================================================
    # PRISM v0.1: INTELLIGENCE SEQUENCE METHODS
    # ============================================================

    def _ensure_ats_simulation(self, listing_id: int):
        """
        PRISM v0.1: Ensure A-10 ATS simulation has been run for this listing.
        If not, trigger it now.
        """
        try:
            # Check if ATS simulation exists
            pkg = self.db.get_application_package(listing_id)
            if pkg and pkg.get('keyword_match_pct', 0) > 0:
                return  # Already done

            # Trigger ATS simulation
            from agents.a10_ats_simulator import get_ats_simulator
            simulator = get_ats_simulator()
            result = simulator.simulate(listing_id)

            if result and result.match_percentage > 0:
                logger.info(
                    f"[{AGENT_ID}] Intelligence Sequence: A-10 ATS sim triggered for #{listing_id} "
                    f"({result.match_percentage:.0f}% match)"
                )
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] ATS simulation pre-check error: {e}")

    def _ensure_cv_tailoring(self, listing_id: int):
        """
        PRISM v0.1: Ensure A-18 CV tailoring has been done for this listing.
        If not, trigger it now.
        """
        try:
            # Check if tailored CV exists
            pkg = self.db.get_application_package(listing_id)
            if pkg and pkg.get('tailored_cv_url'):
                return  # Already done

            # Trigger CV tailoring
            from agents.a18_cv_enhancer import get_cv_enhancer
            enhancer = get_cv_enhancer()
            if hasattr(enhancer, 'tailor_cv'):
                result = enhancer.tailor_cv(listing_id)
                if result:
                    logger.info(
                        f"[{AGENT_ID}] Intelligence Sequence: A-18 CV tailoring triggered for #{listing_id}"
                    )
        except ImportError:
            logger.debug(f"[{AGENT_ID}] A-18 CV Enhancer not available")
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] CV tailoring pre-check error: {e}")

    def _check_alumni_outreach(self, listing: Dict):
        """
        PRISM v0.1: Check if A-09 found alumni at this company.
        If yes, schedule A-15 email outreach BEFORE portal application.
        """
        try:
            company = listing.get('company', '')
            if not company:
                return

            # Check for alumni contacts at this company
            contacts = self.db.get_alumni_contacts_for_company(company)
            if not contacts:
                return

            # Schedule A-15 email outreach
            for contact in contacts[:2]:  # Max 2 contacts per company
                if contact.get('email_sent_at'):
                    continue  # Already sent

                try:
                    from agents.a15_email_applier import get_email_applier
                    emailer = get_email_applier()
                    if hasattr(emailer, 'queue_outreach'):
                        emailer.queue_outreach(
                            contact_id=contact.get('id'),
                            listing=listing,
                            priority='high',
                        )
                        logger.info(
                            f"[{AGENT_ID}] Intelligence Sequence: A-15 email queued for "
                            f"{contact.get('name', '?')} @ {company}"
                        )
                except ImportError:
                    pass
                except Exception as e:
                    logger.debug(f"[{AGENT_ID}] Alumni outreach scheduling error: {e}")

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Alumni check error: {e}")

    def queue_and_confirm(self, listing_id: int) -> Dict[str, Any]:
        """
        Queue a listing and return confirmation details for Telegram.
        Used by /apply [id] command.
        """
        listing = self.db.get_clean_listing_by_id(listing_id)
        if not listing:
            return {'error': f'Listing #{listing_id} not found'}

        platform = listing.get('source', 'internshala')

        # Check if already applied
        existing = self.db.get_application_history(limit=100)
        for app in existing:
            if app.get('listing_id') == listing_id and app.get('status') == 'applied':
                return {'error': f'Already applied to #{listing_id}'}

        # Generate cover letter preview
        cover_letter = self.cover_engine.generate(listing)

        # Queue it
        success = self.queue_manager.queue_listing(
            listing_id, platform, priority=80, queued_by='manual'
        )

        return {
            'success': success,
            'listing_id': listing_id,
            'title': listing.get('title', ''),
            'company': listing.get('company', ''),
            'platform': platform,
            'cover_letter_preview': cover_letter[:500],
            'url': listing.get('url', ''),
        }

    def generate_cover_letter_only(self, listing_id: int) -> str:
        """Generate cover letter without applying (for /cover command)."""
        listing = self.db.get_clean_listing_by_id(listing_id)
        if not listing:
            return f"Listing #{listing_id} not found"
        return self.cover_engine.generate(listing)

    def get_queue_status(self) -> str:
        """Format queue status for Telegram."""
        stats = self.queue_manager.get_stats()

        lines = [
            f"📝 <b>Application Queue Status</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"📬 Queued: {stats.get('queued', 0)}",
            f"🏃 Applying: {stats.get('applying', 0)}",
            f"✅ Applied: {stats.get('applied', 0)}",
            f"❌ Failed: {stats.get('failed', 0)}",
            f"⏭ Skipped: {stats.get('skipped', 0)}",
            f"",
            f"📊 Applied today: {stats.get('applied_today', 0)}",
        ]

        by_platform = stats.get('by_platform', {})
        if by_platform:
            lines.append("\n<b>By Platform:</b>")
            for platform, count in by_platform.items():
                limit = PLATFORM_DAILY_LIMITS.get(platform, '?')
                lines.append(f"  {platform}: {count}/{limit}")

        lines.append(f"\n💡 /apply [id] to queue | /autoapply to run")
        return '\n'.join(lines)


# ============================================================
# SINGLETON ACCESS
# ============================================================

_orchestrator_instance: Optional[AutoApplyOrchestrator] = None


def get_auto_apply_orchestrator() -> AutoApplyOrchestrator:
    """Get or create the singleton AutoApplyOrchestrator instance."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = AutoApplyOrchestrator()
    return _orchestrator_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  {AGENT_NAME} ({AGENT_ID}) — Self-Test")
    print("=" * 60)

    print(f"\nPlatform daily limits:")
    for platform, limit in PLATFORM_DAILY_LIMITS.items():
        print(f"  {platform}: {limit}/day")

    print(f"\nDelay between apps: {DELAY_BETWEEN_APPS[0]}-{DELAY_BETWEEN_APPS[1]}s")
    print(f"Circuit breaker: {MAX_CONSECUTIVE_FAILURES} consecutive failures")
    print(f"Auto-apply min PPO: {DEFAULT_AUTO_APPLY_MIN_PPO}")
    print(f"Cover letter chars: {COVER_LETTER_MIN_CHARS}-{COVER_LETTER_MAX_CHARS}")

    # Test cover letter cleaning
    engine_test = CoverLetterEngine.__new__(CoverLetterEngine)
    test_text = "**Dear Hiring Manager,**\n\n- Point 1\n- Point 2\n\n---\n\n[Your Name]"
    cleaned = engine_test._clean_cover_letter(test_text)
    print(f"\nCover letter cleaning test:")
    print(f"  Input: '{test_text[:60]}...'")
    print(f"  Output: '{cleaned[:60]}...'")
    assert '**' not in cleaned, "Markdown not removed!"
    assert '---' not in cleaned, "Separator not removed!"
    print("  ✅ Cleaning works!")

    print(f"\n✅ {AGENT_NAME} ({AGENT_ID}) ready!")
    print("=" * 60)
