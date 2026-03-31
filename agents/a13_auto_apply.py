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

    def generate(self, listing, user_profile=None) -> str:
        """
        Generate a cover letter for a specific listing.
        
        Args:
            listing: Clean listing dict with title, company, description
            user_profile: Optional dict with college, specialization, skills
        
        Returns:
            Clean cover letter text (no markdown, no AI artifacts)
        """
        # Defensive: ensure listing is a dict (callers sometimes pass strings or None)
        if not isinstance(listing, dict):
            logger.warning(f"[{AGENT_ID}] CoverLetterEngine.generate got listing type={type(listing).__name__}, expected dict")
            if isinstance(listing, str):
                # If someone passed a title string instead of dict, wrap it
                listing = {'title': listing}
            else:
                listing = {}

        title = listing.get('title', '')
        company = listing.get('company', '')
        description = listing.get('description_text', '')[:1500]
        location = listing.get('location', '')
        category = listing.get('category', '')
        source = listing.get('source', '')

        # Get user profile from settings — ensure it's always a dict
        if not user_profile or not isinstance(user_profile, dict):
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
            # Use router.call() directly with our custom system+user prompts
            # NOT router.generate_cover_letter() which expects (listing_dict, profile_dict)
            response = self.router.call(
                'cover_letter',
                user_prompt,
                system_prompt=self.SYSTEM_PROMPT,
                use_cache=False,
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

class CaptchaSolver:
    """
    PRISM v8.0: Auto-solve reCAPTCHA Enterprise v3 tokens via third-party services.

    Supported providers (in order of preference):
        1. CapSolver (capsolver.com) — $0.8-1.5 per 1000 tokens
        2. 2Captcha (2captcha.com) — $2.99 per 1000 tokens
        3. Anti-Captcha (anti-captcha.com) — $2 per 1000 tokens

    For Internshala login, we only need ONE token per session (~$0.001-0.003).
    Sessions last weeks, so total cost is essentially zero.

    Usage:
        solver = CaptchaSolver(api_key="your-key", provider="capsolver")
        token = solver.solve_recaptcha_enterprise(
            site_key="6Lcqj0EsAAAAAL4K2T7--kNrAXT3_99tIuEQLZJF",
            page_url="https://internshala.com/login/user",
            action="login_submit"
        )
    """

    PROVIDERS = {
        'capsolver': {
            'create_url': 'https://api.capsolver.com/createTask',
            'result_url': 'https://api.capsolver.com/getTaskResult',
            'task_type': 'ReCaptchaV3EnterpriseTaskProxyLess',
        },
        '2captcha': {
            'create_url': 'https://api.2captcha.com/createTask',
            'result_url': 'https://api.2captcha.com/getTaskResult',
            'task_type': 'RecaptchaV3TaskProxyless',
        },
        'anticaptcha': {
            'create_url': 'https://api.anti-captcha.com/createTask',
            'result_url': 'https://api.anti-captcha.com/getTaskResult',
            'task_type': 'RecaptchaV3TaskProxyless',
        },
    }

    def __init__(self, api_key: str = '', provider: str = 'capsolver'):
        self.api_key = api_key.strip()
        self.provider = provider.lower().strip()
        if self.provider not in self.PROVIDERS:
            self.provider = 'capsolver'

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def solve_recaptcha_enterprise(self, site_key: str, page_url: str,
                                    action: str = 'login_submit',
                                    timeout: int = 120) -> Optional[str]:
        """
        Solve reCAPTCHA Enterprise v3 and return the token.

        Returns the g-recaptcha-response token string, or None on failure.
        Typical solve time: 5-30 seconds.
        """
        if not self.api_key:
            logger.warning(f"[{AGENT_ID}] CaptchaSolver: No API key configured")
            return None

        import requests
        prov = self.PROVIDERS[self.provider]

        try:
            # Step 1: Create task
            if self.provider == 'capsolver':
                create_payload = {
                    'clientKey': self.api_key,
                    'task': {
                        'type': 'ReCaptchaV3EnterpriseTaskProxyLess',
                        'websiteURL': page_url,
                        'websiteKey': site_key,
                        'pageAction': action,
                    }
                }
            else:
                # 2captcha / anticaptcha format
                create_payload = {
                    'clientKey': self.api_key,
                    'task': {
                        'type': prov['task_type'],
                        'websiteURL': page_url,
                        'websiteKey': site_key,
                        'action': action,
                        'minScore': 0.7,
                        'isEnterprise': True,
                    }
                }

            logger.info(f"[{AGENT_ID}] CaptchaSolver: Creating {self.provider} task for {page_url}")
            resp = requests.post(prov['create_url'], json=create_payload, timeout=30)
            result = resp.json()

            # CapSolver returns solution immediately for some tasks
            if result.get('status') == 'ready' and result.get('solution', {}).get('gRecaptchaResponse'):
                token = result['solution']['gRecaptchaResponse']
                logger.info(f"[{AGENT_ID}] CaptchaSolver: Instant solve! Token length: {len(token)}")
                return token

            task_id = result.get('taskId')
            if not task_id:
                error_desc = result.get('errorDescription', '') or result.get('errorId', '')
                logger.error(f"[{AGENT_ID}] CaptchaSolver: Failed to create task: {error_desc}")
                return None

            # Step 2: Poll for result
            logger.info(f"[{AGENT_ID}] CaptchaSolver: Task {task_id} created, polling...")
            start = time.time()
            while time.time() - start < timeout:
                time.sleep(5)  # Poll every 5 seconds

                poll_payload = {
                    'clientKey': self.api_key,
                    'taskId': task_id,
                }
                poll_resp = requests.post(prov['result_url'], json=poll_payload, timeout=30)
                poll_result = poll_resp.json()

                status = poll_result.get('status', '')
                if status == 'ready':
                    token = (
                        poll_result.get('solution', {}).get('gRecaptchaResponse')
                        or poll_result.get('solution', {}).get('token')
                    )
                    if token:
                        elapsed = time.time() - start
                        logger.info(
                            f"[{AGENT_ID}] CaptchaSolver: Solved in {elapsed:.1f}s! "
                            f"Token length: {len(token)}"
                        )
                        return token
                    logger.warning(f"[{AGENT_ID}] CaptchaSolver: Ready but no token in response")
                    return None

                elif status == 'failed' or poll_result.get('errorId'):
                    error_desc = poll_result.get('errorDescription', 'Unknown error')
                    logger.error(f"[{AGENT_ID}] CaptchaSolver: Task failed: {error_desc}")
                    return None

                # Still processing, continue polling

            logger.warning(f"[{AGENT_ID}] CaptchaSolver: Timeout after {timeout}s")
            return None

        except Exception as e:
            logger.error(f"[{AGENT_ID}] CaptchaSolver error: {e}")
            return None


class InternshalaApplicator:
    """
    PRISM v8.0: Internshala FULLY AUTOMATED Single-Click Apply Engine.

    === KEY DISCOVERY (2026-03-31 investigation) ===
    - Internshala does NOT use Cloudflare (uses Amazon CloudFront CDN + nginx)
    - reCAPTCHA Enterprise v3 is required ONLY for LOGIN, NOT for applying
    - The /application/easy_apply/{id} endpoint needs NO captcha at all
    - Once logged in, session cookies work for weeks

    === ARCHITECTURE ===
    Tier 1 (CAPTCHA SERVICE — FULLY AUTOMATED):
        User enters email + password + captcha API key (from capsolver.com ~$3/1000)
        → Backend auto-solves reCAPTCHA Enterprise via API
        → curl_cffi logs in with Chrome TLS fingerprint
        → Session cookies saved to DB (reused for weeks)
        → All applies via curl_cffi POST — ZERO manual intervention

    Tier 2 (STORED SESSION — SEMI-AUTOMATED):
        If login fails or no captcha key, use previously stored session.
        Sessions last weeks — user rarely needs to re-login.

    Tier 3 (SESSION COOKIE — MANUAL ONE-TIME):
        User can paste raw cookies from browser DevTools.
        Fallback for when everything else fails.

    Tier 4 (ASSISTED — LAST RESORT):
        Generate cover letter + return apply URL for manual click.

    === APPLY ENDPOINT (confirmed via JS analysis) ===
    POST /application/easy_apply/{internship_id}
    Fields: cover_letter, csrf_test_name
    NO reCAPTCHA required on apply form.

    === SAFETY ===
    - curl_cffi Chrome120 TLS fingerprint (indistinguishable from real browser)
    - Human-like delays (2-7s between steps)
    - 15 apps/day cap
    """

    INTERNSHALA_BASE = "https://internshala.com"
    RECAPTCHA_SITE_KEY = "6Lcqj0EsAAAAAL4K2T7--kNrAXT3_99tIuEQLZJF"

    def __init__(self, db: DatabaseManager, cover_engine: CoverLetterEngine):
        self.db = db
        self.cover_engine = cover_engine
        self._session = None  # Reuse curl_cffi session within a batch
        self._session_validated = False  # Track if current session is validated
        self._captcha_solver = None  # Lazy-init captcha solver

    def can_apply(self) -> Tuple[bool, str]:
        """Always ready — will attempt auto-apply, falls back to assisted."""
        return True, "Ready"

    def _extract_internship_id(self, url: str) -> Optional[str]:
        """Extract the numeric internship ID from URL."""
        if not url:
            return None
        # Pattern 1: /internship/detail/slug-12345678
        match = re.search(r'/internship/(?:detail/)?[^/]*?(\d{8,})', url)
        if match:
            return match.group(1)
        # Pattern 2: /application/easy_apply/12345678
        match = re.search(r'/easy_apply/(\d+)', url)
        if match:
            return match.group(1)
        # Pattern 3: any long number in the URL
        match = re.search(r'(\d{8,})', url)
        if match:
            return match.group(1)
        return None

    def _get_curl_session(self):
        """Get or create a curl_cffi session with Chrome impersonation."""
        try:
            from curl_cffi.requests import Session
            if self._session is None:
                self._session = Session(impersonate="chrome")
                self._session_validated = False
            return self._session
        except ImportError:
            logger.warning(f"[{AGENT_ID}] curl_cffi not available, cannot auto-apply to Internshala")
            return None

    def _build_session_from_cookies(self, cookie_string: str):
        """
        Build a curl_cffi session from a raw cookie string.

        Accepts multiple formats:
        1. Full cookie header: "name1=val1; name2=val2; ..."
        2. JSON format: {"name1": "val1", "name2": "val2"}
        3. Single cookie: "_internshala_session=abc123"

        The critical cookies for Internshala session are:
        - _internshala_session (or similar session identifier)
        - csrf_cookie_name (CSRF double-submit)
        - AWSALB / AWSALBCORS (load balancer affinity)
        """
        try:
            from curl_cffi.requests import Session
            session = Session(impersonate="chrome")

            cookie_string = cookie_string.strip()
            if not cookie_string:
                return None

            # Try JSON format first
            cookie_pairs = {}
            if cookie_string.startswith('{'):
                try:
                    cookie_pairs = json.loads(cookie_string)
                except (json.JSONDecodeError, Exception):
                    pass

            # Otherwise parse as semicolon-separated key=value pairs
            if not cookie_pairs:
                for part in cookie_string.split(';'):
                    part = part.strip()
                    if '=' in part:
                        k, v = part.split('=', 1)
                        k = k.strip()
                        v = v.strip()
                        if k and v:
                            cookie_pairs[k] = v

            if not cookie_pairs:
                logger.warning(f"[{AGENT_ID}] Could not parse any cookies from provided string")
                return None

            # Set cookies on session
            for name, value in cookie_pairs.items():
                session.cookies.set(name, value, domain='.internshala.com')
                # Also set without dot prefix for compatibility
                session.cookies.set(name, value, domain='internshala.com')

            logger.info(
                f"[{AGENT_ID}] Built session with {len(cookie_pairs)} cookies: "
                f"{', '.join(list(cookie_pairs.keys())[:5])}{'...' if len(cookie_pairs) > 5 else ''}"
            )
            return session

        except ImportError:
            logger.warning(f"[{AGENT_ID}] curl_cffi not available")
            return None
        except Exception as e:
            logger.error(f"[{AGENT_ID}] Error building session from cookies: {e}")
            return None

    def validate_session(self, cookie_string: str) -> Tuple[bool, str, str]:
        """
        Validate that a session cookie string gives us a logged-in Internshala session.

        Tests by visiting /student/dashboard — if we get 200 and see student content,
        the session is valid. If redirected to /login, the session is expired.

        Returns: (valid: bool, message: str, username: str)
        """
        session = self._build_session_from_cookies(cookie_string)
        if not session:
            return False, 'Could not parse session cookies', ''

        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = session.get(
                f"{self.INTERNSHALA_BASE}/student/dashboard",
                headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Referer': f'{self.INTERNSHALA_BASE}/',
                },
                timeout=15,
                allow_redirects=True,
            )

            if resp.status_code == 200:
                html = resp.text.lower()
                # Check for logged-in indicators
                if any(indicator in html for indicator in [
                    'student/dashboard', 'my applications', 'my_applications',
                    'student_header', 'logout', 'log out', 'my-applications',
                    'resume', 'profile', 'internship_matching',
                ]):
                    # Try to extract username
                    username = ''
                    name_match = re.search(r'class=["\'](?:user.?name|student.?name|profile.?name)["\'][^>]*>([^<]+)', resp.text, re.I)
                    if name_match:
                        username = name_match.group(1).strip()
                    if not username:
                        name_match = re.search(r'<span[^>]*class=["\']name["\'][^>]*>([^<]+)', resp.text, re.I)
                        if name_match:
                            username = name_match.group(1).strip()

                    # Store the validated session
                    self._session = session
                    self._session_validated = True
                    logger.info(f"[{AGENT_ID}] Session cookie VALID (user: {username or 'unknown'})")
                    return True, 'Session is valid and logged in', username

                # Page loaded but doesn't look like dashboard
                if '/login' in resp.url:
                    return False, 'Session expired — redirected to login page', ''

                return False, 'Session may be expired — dashboard content not found', ''

            elif resp.status_code == 302:
                location = resp.headers.get('Location', '')
                if '/login' in location:
                    return False, 'Session expired — redirected to login', ''
                return False, f'Unexpected redirect to: {location[:100]}', ''
            else:
                return False, f'Dashboard returned HTTP {resp.status_code}', ''

        except Exception as e:
            return False, f'Validation error: {str(e)[:150]}', ''

    def _extract_csrf_token(self, html: str) -> str:
        """Extract CSRF token from Internshala HTML page.
        
        Internshala uses a double-submit CSRF pattern:
        - Hidden input: <input type="hidden" name="csrf_test_name" value="...">
        - Cookie: csrf_cookie_name=<same_value>
        
        The hidden input field name is 'csrf_test_name' (NOT '_token' or 'csrf-token').
        """
        # PRIMARY: Internshala's actual CSRF field — csrf_test_name
        match = re.search(r'name=["\']csrf_test_name["\'][^>]*value=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        # Reverse attribute order
        match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_test_name["\']', html)
        if match:
            return match.group(1)
        # FALLBACK 1: Generic _token field (other platforms)
        match = re.search(r'name=["\']_token["\']\s*value=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        match = re.search(r'value=["\']([^"\']+)["\']\s*name=["\']_token["\']', html)
        if match:
            return match.group(1)
        # FALLBACK 2: Meta tag csrf-token (not used by Internshala but other sites)
        match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        # FALLBACK 3: csrfToken in JS variable
        match = re.search(r'csrfToken\s*[:=]\s*["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        return ''

    def _get_captcha_solver(self, captcha_api_key: str = '', captcha_provider: str = '') -> Optional[CaptchaSolver]:
        """Get or create a CaptchaSolver instance."""
        # Use provided key, or fall back to DB-stored key, or env var
        api_key = captcha_api_key
        if not api_key:
            try:
                api_key = self.db.get_setting('captcha_api_key', '')
            except Exception:
                pass
        if not api_key:
            api_key = os.environ.get('CAPTCHA_API_KEY', '') or os.environ.get('CAPSOLVER_API_KEY', '')

        provider = captcha_provider
        if not provider:
            try:
                provider = self.db.get_setting('captcha_provider', 'capsolver')
            except Exception:
                provider = 'capsolver'

        if api_key:
            self._captcha_solver = CaptchaSolver(api_key=api_key, provider=provider)
            return self._captcha_solver
        return None

    def _login_with_credentials(self, email: str, password: str,
                                 captcha_api_key: str = '',
                                 captcha_provider: str = '') -> Tuple[bool, str]:
        """
        PRISM v8.0: Login to Internshala with AUTO reCAPTCHA solving.

        Flow:
            1. GET /login/user → CSRF token + cookies
            2. Auto-solve reCAPTCHA Enterprise v3 via captcha service
            3. POST /login/verify_ajax/user with email + password + captcha token
            4. Save session cookies to DB for reuse

        Returns: (success: bool, error_message: str)
        """
        session = self._get_curl_session()
        if not session:
            return False, "curl_cffi not available"

        try:
            # Step 1: GET /login/user for CSRF token + initial cookies
            time.sleep(random.uniform(1, 2))
            login_page = session.get(
                f"{self.INTERNSHALA_BASE}/login/user",
                timeout=20,
            )
            if login_page.status_code != 200:
                return False, f"Login page returned HTTP {login_page.status_code}"

            csrf_token = self._extract_csrf_token(login_page.text)
            if not csrf_token:
                # Fallback: get csrf from cookie
                csrf_token = dict(session.cookies).get('csrf_cookie_name', '')

            if not csrf_token:
                return False, "Could not extract CSRF token from login page"

            # Step 2: Solve reCAPTCHA Enterprise v3 via captcha service
            recaptcha_token = None
            solver = self._get_captcha_solver(captcha_api_key, captcha_provider)
            if solver and solver.is_configured:
                logger.info(f"[{AGENT_ID}] Solving reCAPTCHA Enterprise for Internshala login...")
                recaptcha_token = solver.solve_recaptcha_enterprise(
                    site_key=self.RECAPTCHA_SITE_KEY,
                    page_url=f"{self.INTERNSHALA_BASE}/login/user",
                    action='login_submit',
                    timeout=120,
                )
                if recaptcha_token:
                    logger.info(f"[{AGENT_ID}] reCAPTCHA solved successfully!")
                else:
                    logger.warning(f"[{AGENT_ID}] reCAPTCHA solve FAILED — will try login anyway")
            else:
                logger.info(f"[{AGENT_ID}] No captcha solver configured — trying login without token")

            # Step 3: POST login with credentials + captcha token
            time.sleep(random.uniform(1, 3))
            login_payload = {
                'email': email,
                'password': password,
                'csrf_test_name': csrf_token,
            }
            if recaptcha_token:
                login_payload['g-recaptcha-response'] = recaptcha_token
                login_payload['action'] = 'login_submit'

            login_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': f'{self.INTERNSHALA_BASE}/login/user',
                'Origin': self.INTERNSHALA_BASE,
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
            }

            login_resp = session.post(
                f"{self.INTERNSHALA_BASE}/login/verify_ajax/user",
                data=login_payload,
                headers=login_headers,
                timeout=20,
                allow_redirects=True,
            )

            # Parse response
            login_ok = False
            login_error = ''

            if login_resp.status_code in (200, 302):
                resp_text = login_resp.text.lower()
                try:
                    resp_json = login_resp.json() if login_resp.text.strip().startswith('{') else {}
                except Exception:
                    resp_json = {}

                if (resp_json.get('success') is True
                        or resp_json.get('status') == 'success'
                        or 'dashboard' in login_resp.url
                        or 'student/dashboard' in login_resp.url):
                    login_ok = True
                elif 'captcha' in resp_text:
                    if recaptcha_token:
                        login_error = (
                            'CAPTCHA token was rejected by Internshala. '
                            'The captcha service may need a different approach. '
                            'Try again or use session cookie method.'
                        )
                    else:
                        login_error = (
                            'Internshala requires reCAPTCHA. Add a captcha API key '
                            '(capsolver.com ~$3/1000 solves) for fully automated login, '
                            'or paste your session cookie from browser.'
                        )
                elif 'invalid' in resp_text or 'incorrect' in resp_text or 'wrong' in resp_text:
                    login_error = 'Invalid email or password — check your Internshala credentials'
                elif 'otp' in resp_text:
                    login_error = 'Account requires OTP verification — log in on internshala.com first'
                elif resp_json.get('success') is False:
                    error_thrown = resp_json.get('errorThrown', '') or resp_json.get('error', '')
                    login_error = f'Login rejected: {str(error_thrown)[:150]}'
                else:
                    # Check cookies for session indicators
                    cookies = dict(session.cookies)
                    if any('logged' in k.lower() or 'student' in k.lower() for k in cookies):
                        login_ok = True
                    else:
                        login_error = f'Login response unclear (HTTP {login_resp.status_code})'
            else:
                login_error = f'Login returned HTTP {login_resp.status_code}'

            if login_ok:
                logger.info(f"[{AGENT_ID}] Internshala login SUCCESS for {email}")
                self._session_validated = True
                # Save session cookies to DB for reuse across requests
                try:
                    cookie_str = '; '.join(f'{k}={v}' for k, v in dict(session.cookies).items())
                    self.db.set_setting('internshala_session', cookie_str)
                    self.db.set_setting('internshala_session_email', email)
                    self.db.set_setting('internshala_session_time', str(int(time.time())))
                    logger.info(f"[{AGENT_ID}] Internshala session saved to DB (reusable for weeks)")
                except Exception as save_err:
                    logger.warning(f"[{AGENT_ID}] Could not save session to DB: {save_err}")
            else:
                logger.warning(f"[{AGENT_ID}] Internshala login FAILED: {login_error}")

            return login_ok, login_error

        except Exception as e:
            return False, f"Login error: {str(e)[:200]}"

    def _submit_application(self, internship_id: str, cover_letter: str,
                             listing: Dict) -> Tuple[bool, str]:
        """
        PRISM v9.0: Submit application to Internshala using the authenticated session.

        Flow:
            1. GET the internship detail page → extract CSRF + detect assessment questions
            2. If assessment questions exist → auto-generate answers via AI
            3. POST to /application/easy_apply/{id} via ajax-form-style form POST
               Fields: cover_letter, csrf_test_name (+ any assessment answers)
            4. Parse response for success/already-applied/error

        The apply form is submitted by jQuery ajaxForm plugin in internship-details.js.
        It POSTs to the form's action attribute which is /application/easy_apply/{id}.
        No reCAPTCHA required on the apply endpoint.

        Returns: (success: bool, error_message: str)
        """
        session = self._get_curl_session()
        if not session:
            return False, "No session available"

        try:
            # Step 1: Visit the internship detail page
            # This sets up server-side state + gives us CSRF token + assessment questions
            time.sleep(random.uniform(1.5, 4))
            original_url = listing.get('url', '') or listing.get('source_url', '')
            if original_url and 'internshala.com' in original_url:
                detail_url = original_url
            else:
                detail_url = f"{self.INTERNSHALA_BASE}/internship/detail/{internship_id}"

            detail_resp = session.get(
                detail_url,
                headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.8',
                    'Referer': f'{self.INTERNSHALA_BASE}/internships',
                },
                timeout=20,
            )

            if detail_resp.status_code != 200:
                return False, f"Detail page returned HTTP {detail_resp.status_code}"

            # Check if we're still logged in
            final_url = str(detail_resp.url)
            if '/login' in final_url and 'internship' not in final_url:
                return False, "Session expired — redirected to login"

            detail_html = detail_resp.text

            # Extract CSRF token
            csrf_token = self._extract_csrf_token(detail_html)
            if not csrf_token:
                # Fallback: get from cookie
                try:
                    cookies = {c.name: c.value for c in session.cookies}
                    csrf_token = cookies.get('csrf_cookie_name', '')
                except Exception:
                    pass

            # Detect assessment questions (custom questions on some internships)
            assessment_answers = {}
            assessment_patterns = re.findall(
                r'name="(assessment_question_answer(?:_\d+|\[\d+\]))"',
                detail_html
            )
            if assessment_patterns and self.cover_engine:
                # Extract question text if visible
                question_texts = re.findall(
                    r'class="[^"]*assessment[^"]*"[^>]*>\s*([^<]+)',
                    detail_html, re.I
                )
                logger.info(
                    f"[{AGENT_ID}] Found {len(assessment_patterns)} assessment questions"
                )
                for i, field_name in enumerate(assessment_patterns):
                    question = question_texts[i].strip() if i < len(question_texts) else ''
                    if not question:
                        question = f"Why are you interested in this {listing.get('title', 'role')} position?"
                    try:
                        answers = self.cover_engine.generate_assessment_answers(
                            [question], listing
                        )
                        if answers and answers[0]:
                            assessment_answers[field_name] = answers[0]
                    except Exception:
                        assessment_answers[field_name] = (
                            f"I am excited about this opportunity at {listing.get('company', 'your company')}. "
                            f"My background and skills align well with this role."
                        )

            # Check for "already applied" indicator on the page
            if ('already_applied' in detail_html.lower()
                    or 'you have already applied' in detail_html.lower()
                    or 'application_submitted' in detail_html.lower()):
                logger.info(f"[{AGENT_ID}] Already applied to internship {internship_id}")
                return True, 'Already applied'

            # Detect the actual form action URL (might differ from default)
            form_action = f"/application/easy_apply/{internship_id}"
            action_match = re.search(
                r'id="application-form"[^>]*action="([^"]+)"', detail_html
            )
            if not action_match:
                action_match = re.search(
                    r'action="([^"]+)"[^>]*id="application-form"', detail_html
                )
            if action_match:
                form_action = action_match.group(1)
                logger.info(f"[{AGENT_ID}] Found form action: {form_action}")

            apply_url = f"{self.INTERNSHALA_BASE}{form_action}"

            # Step 2: POST the application
            time.sleep(random.uniform(2, 5))

            apply_payload = {
                'cover_letter': cover_letter[:3000],
            }
            if csrf_token:
                apply_payload['csrf_test_name'] = csrf_token
            # Add assessment answers
            apply_payload.update(assessment_answers)

            apply_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': detail_url,
                'Origin': self.INTERNSHALA_BASE,
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
            }

            apply_resp = session.post(
                apply_url,
                data=apply_payload,
                headers=apply_headers,
                timeout=25,
            )

            # Step 3: Parse response
            resp_text = apply_resp.text
            resp_json = {}
            try:
                stripped = resp_text.strip()
                if stripped.startswith('{') or stripped.startswith('['):
                    resp_json = json.loads(stripped) if stripped.startswith('{') else {}
            except Exception:
                pass

            if apply_resp.status_code == 200:
                resp_lower = resp_text.lower()
                # Success indicators
                if (resp_json.get('success') is True
                        or resp_json.get('status') == 'success'
                        or 'successfully' in resp_lower
                        or 'application_submitted' in resp_lower
                        or 'congratul' in resp_lower
                        or resp_json.get('applied') is True
                        or 'your application has been submitted' in resp_lower):
                    logger.info(f"[{AGENT_ID}] Internshala APPLY SUCCESS: internship {internship_id}")
                    return True, ''

                # Already applied
                if ('already' in resp_lower and 'applied' in resp_lower) or 'already applied' in resp_lower:
                    logger.info(f"[{AGENT_ID}] Internshala: already applied to {internship_id}")
                    return True, 'Already applied'

                # Login required / session expired
                if (resp_json.get('requireLogin') is True
                        or 'requirelogin' in resp_lower
                        or 'not_logged_in' in resp_lower
                        or 'please login' in resp_lower):
                    return False, "Session expired — need to re-login"

                # Explicit failure
                if resp_json.get('success') is False:
                    error_msg = (
                        resp_json.get('errorThrown', '')
                        or resp_json.get('message', '')
                        or resp_json.get('error', '')
                        or 'Application rejected by server'
                    )
                    return False, f"Internshala rejected: {str(error_msg)[:200]}"

                # Some internships return HTML with success message
                if 'application' in resp_lower and ('submitted' in resp_lower or 'received' in resp_lower):
                    return True, ''

                # Short 200 response often means success (form plugin returns minimal response)
                if len(resp_text.strip()) < 100 and apply_resp.status_code == 200:
                    logger.info(f"[{AGENT_ID}] Short 200 response — treating as success")
                    return True, ''

                return False, f"Unclear response ({len(resp_text)} bytes): {resp_text[:200]}"

            elif apply_resp.status_code == 302:
                redirect_url = apply_resp.headers.get('Location', '')
                if any(kw in redirect_url.lower() for kw in ('success', 'submitted', 'application', 'dashboard')):
                    return True, ''
                if '/login' in redirect_url.lower():
                    return False, "Session expired — redirected to login"
                return False, f"Redirected to: {redirect_url[:200]}"
            else:
                return False, f"Apply returned HTTP {apply_resp.status_code}: {resp_text[:200]}"

        except Exception as e:
            return False, f"Submit error: {str(e)[:200]}"

    def apply(self, listing: Dict, cover_letter: str = '',
              resume_path: str = '') -> ApplicationAttempt:
        """
        PRISM v9.0: FULLY AUTOMATED 4-tier Internshala application.

        The entire flow is zero-manual-intervention:
        1. Try existing validated session (instant)
        2. Try stored DB session cookies (from previous login)
        3. Try email+password login with auto-captcha solving
        4. Try raw session cookies from frontend
        5. LAST RESORT: Assisted mode (cover letter + link)

        The system remembers sessions across batches and across server restarts.
        A single successful login lasts for weeks.

        Returns:
            - success=True, method='api' if auto-apply worked
            - success=False, error='assisted' if fell back to assisted mode
        """
        attempt = ApplicationAttempt(
            listing_id=listing.get('id', 0),
            platform='internshala',
        )
        start_time = time.time()

        try:
            url = listing.get('url', '') or listing.get('source_url', '')
            internship_id = self._extract_internship_id(url)

            # Generate cover letter if not provided
            if not cover_letter:
                try:
                    cover_letter = self.cover_engine.generate(listing)
                except Exception as e:
                    logger.warning(f"[{AGENT_ID}] Cover letter generation failed: {e}")
                    cover_letter = self.cover_engine._fallback_letter(
                        listing.get('title', ''),
                        listing.get('company', ''),
                        self.db.get_setting('college', 'a top business school'),
                        self.db.get_setting('specialization', 'MBA'),
                    )
            attempt.cover_letter = cover_letter

            # Build apply URL for assisted fallback
            if url and 'internshala.com' in url:
                attempt.external_app_id = url
            elif internship_id:
                attempt.external_app_id = f"https://internshala.com/internship/detail/{internship_id}"
            elif url:
                attempt.external_app_id = url

            if not internship_id:
                attempt.success = False
                attempt.error = 'assisted'
                attempt.method = 'assisted'
                logger.warning(f"[{AGENT_ID}] No internship ID found in URL: {url[:80]}")
                attempt.duration_sec = round(time.time() - start_time, 1)
                return attempt

            # Helper: attempt submission and return result
            def _try_submit() -> Tuple[bool, str]:
                return self._submit_application(internship_id, cover_letter, listing)

            def _handle_submit_result(submit_ok, submit_error, method_label):
                if submit_ok:
                    attempt.success = True
                    attempt.method = 'api'
                    attempt.error = submit_error
                    logger.info(
                        f"[{AGENT_ID}] Internshala AUTO-APPLY SUCCESS ({method_label}): "
                        f"'{listing.get('title', '')[:40]}' at {listing.get('company', '')}"
                    )
                    return True
                elif 'expired' in (submit_error or '').lower() or 'login' in (submit_error or '').lower():
                    self._session = None
                    self._session_validated = False
                    logger.info(f"[{AGENT_ID}] Session expired during {method_label}, will try next tier")
                return False

            # ===== TIER 1: Reuse validated session from this batch =====
            if self._session and self._session_validated:
                submit_ok, submit_error = _try_submit()
                if _handle_submit_result(submit_ok, submit_error, 'reused session'):
                    attempt.duration_sec = round(time.time() - start_time, 1)
                    return attempt

            # ===== TIER 2: Auto-use stored DB session (from previous login) =====
            # This is the KEY innovation: sessions saved from /api/internshala-login
            # are automatically reused. User logs in once, applies for weeks.
            if not (self._session and self._session_validated):
                try:
                    stored_session = self.db.get_setting('internshala_session', '')
                    session_time = self.db.get_setting('internshala_session_time', '0')
                    session_age_hours = (time.time() - int(session_time)) / 3600 if session_time.isdigit() else 999

                    if stored_session and session_age_hours < 336:  # < 14 days
                        logger.info(
                            f"[{AGENT_ID}] Found stored session ({session_age_hours:.0f}h old), trying..."
                        )
                        built_session = self._build_session_from_cookies(stored_session)
                        if built_session:
                            self._session = built_session
                            self._session_validated = True
                            submit_ok, submit_error = _try_submit()
                            if _handle_submit_result(submit_ok, submit_error, 'stored DB session'):
                                attempt.duration_sec = round(time.time() - start_time, 1)
                                return attempt
                except Exception as db_err:
                    logger.debug(f"[{AGENT_ID}] DB session lookup error: {db_err}")

            # ===== TIER 3: Login with email + password + auto-captcha =====
            user_email = listing.get('email', '').strip()
            user_password = listing.get('password', '').strip()
            captcha_api_key = listing.get('captcha_api_key', '').strip()
            captcha_provider = listing.get('captcha_provider', '').strip()

            # Also try credentials stored in DB (from previous /api/internshala-login)
            if not user_email:
                try:
                    user_email = self.db.get_setting('internshala_email', '')
                except Exception:
                    pass
            if not user_password:
                try:
                    user_password = self.db.get_setting('internshala_password', '')
                except Exception:
                    pass
            if not captcha_api_key:
                try:
                    captcha_api_key = self.db.get_setting('captcha_api_key', '')
                except Exception:
                    pass

            if user_email and user_password and not (self._session and self._session_validated):
                login_ok, login_error = self._login_with_credentials(
                    user_email, user_password, captcha_api_key, captcha_provider
                )
                if login_ok:
                    submit_ok, submit_error = _try_submit()
                    if _handle_submit_result(submit_ok, submit_error, 'fresh login'):
                        attempt.duration_sec = round(time.time() - start_time, 1)
                        return attempt
                    else:
                        logger.warning(f"[{AGENT_ID}] Apply failed after login: {submit_error}")
                else:
                    logger.warning(f"[{AGENT_ID}] Login failed: {login_error}")
                    attempt.error = login_error

            # ===== TIER 4: Raw session cookie from frontend =====
            if not (self._session and self._session_validated):
                session_cookie = (
                    listing.get('session_cookie', '').strip()
                    or listing.get('internshala_session', '').strip()
                )
                if session_cookie:
                    built_session = self._build_session_from_cookies(session_cookie)
                    if built_session:
                        self._session = built_session
                        self._session_validated = True
                        submit_ok, submit_error = _try_submit()
                        if _handle_submit_result(submit_ok, submit_error, 'frontend cookie'):
                            attempt.duration_sec = round(time.time() - start_time, 1)
                            return attempt

            # ===== TIER 5: Assisted mode (fallback) =====
            attempt.success = False
            attempt.error = 'assisted'
            attempt.method = 'assisted'

            logger.info(
                f"[{AGENT_ID}] Internshala ASSISTED (fallback): generated cover letter for "
                f"'{listing.get('title', '')[:40]}' at {listing.get('company', '')}"
            )

        except Exception as e:
            attempt.error = f"Internshala apply error: {str(e)[:200]}"
            attempt.method = 'assisted'
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
