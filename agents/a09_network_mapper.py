"""
============================================================
AGENT A-09: NETWORK/ALUMNI MAPPER — INDUSTRIAL GRADE
============================================================
Discovers alumni connections and warm intro paths for target
companies using DuckDuckGo dorks and SerpAPI (reserved budget).
Generates outreach drafts for warm intros.

Trigger: On-demand via /network [company]
AI Model: Groq (outreach_draft) for email drafting

Architecture:
    ┌──────────────────────────────────────────────────┐
    │           NETWORK MAPPER (A-09)                  │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Alumni Discovery Engine                   │   │
    │  │  - DDG dorks for LinkedIn alumni profiles  │   │
    │  │  - SerpAPI for Tier 1 companies only       │   │
    │  │  - College-specific search patterns        │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Profile Parser                            │   │
    │  │  - Name extraction from LinkedIn titles    │   │
    │  │  - Role/department detection               │   │
    │  │  - Connection degree estimation            │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Outreach Draft Generator                  │   │
    │  │  - 200-word warm intro email (Groq)        │   │
    │  │  - Personalized by role/college/company    │   │
    │  │  - Follow-up message template              │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Connection Path Mapper                    │   │
    │  │  - 1st degree: direct alumni → priority    │   │
    │  │  - 2nd degree: alumni at partner firms     │   │
    │  │  - Cold outreach: HR/TA professionals      │   │
    │  └───────────────────────────────────────────┘   │
    │                                                  │
    └──────────────────────────────────────────────────┘

SerpAPI Budget Rules (CRITICAL — Only 100/month):
    - NEVER use for routine daily operations
    - USE ONLY for Tier 1 companies (McKinsey, BCG, Goldman, etc.)
    - Max 5 network lookups per day
    - Prefer DDG dorks for all other companies
============================================================
"""

import os
import re
import json
import time
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from urllib.parse import urlparse, quote_plus

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST, DDG_DORK_TEMPLATES
from core.database import get_db, DatabaseManager, AlumniContact
from core.ai_router import get_router, AIRouter

AGENT_ID = "A-09"
AGENT_NAME = "Network/Alumni Mapper"

# Daily SerpAPI budget
MAX_SERP_LOOKUPS_PER_DAY = 5
SERP_TIER_THRESHOLD = 2  # Only use SerpAPI for Tier 1 and 2

# DDG search templates
DDG_ALUMNI_DORK = 'site:linkedin.com/in "{college}" "{company}" {keywords}'
DDG_HR_DORK = 'site:linkedin.com/in "{company}" "talent acquisition" OR "recruiter" OR "HR" india'
DDG_ALUMNI_BATCH_DORK = 'site:linkedin.com/in "{college}" "{company}" alumni OR batch OR graduated'
DDG_MANAGER_DORK = 'site:linkedin.com/in "{company}" "hiring manager" OR "team lead" {department}'

# Search keyword variations
ALUMNI_KEYWORDS = ['alumni', 'batch', 'graduated', 'class of']
HR_KEYWORDS = ['talent acquisition', 'recruiter', 'HR', 'people operations']
MANAGER_KEYWORDS = ['hiring manager', 'team lead', 'head of', 'director']

# Outreach templates
OUTREACH_CONTEXT = {
    'alumni': (
        "You are writing a 200-word warm introduction email from an MBA student "
        "to an alumni at their target company. The email should be professional, "
        "personal (mention shared college), brief, and request a 15-minute coffee chat. "
        "Do NOT be overly formal or sycophantic."
    ),
    'hr': (
        "You are writing a 150-word professional inquiry email to an HR/TA professional "
        "at a target company. Inquire about internship opportunities, mention relevant "
        "MBA specialization, and request a brief informational call."
    ),
    'cold': (
        "You are writing a 150-word cold outreach email to a hiring manager "
        "at a target company. Express interest in their team, mention 1-2 relevant "
        "skills/experiences, and ask if they'd be open to a brief chat."
    ),
}

# Connection degree estimation patterns
CONNECTION_DEGREE_PATTERNS = {
    1: ['alumni', 'batch mate', 'classmate', 'same college', 'same school'],
    2: ['friend of', 'referred by', 'mutual connection', 'knows'],
    3: [],  # Default for cold outreach
}


@dataclass
class AlumniProfile:
    """Parsed alumni/contact profile."""
    name: str = ""
    linkedin_url: str = ""
    current_role: str = ""
    current_company: str = ""
    college: str = ""
    batch_year: str = ""
    connection_degree: int = 3  # 1=direct alumni, 2=indirect, 3=cold
    department: str = ""
    location: str = ""
    contact_type: str = "alumni"  # alumni, hr, manager, cold
    source: str = "ddg"  # ddg, serpapi
    relevance_score: float = 0.0


@dataclass
class NetworkMapResult:
    """Result of a network mapping operation."""
    company_name: str = ""
    company_id: Optional[int] = None
    company_tier: int = 5
    college: str = ""
    alumni_found: int = 0
    hr_contacts: int = 0
    manager_contacts: int = 0
    outreach_drafts: int = 0
    profiles: List[AlumniProfile] = field(default_factory=list)
    outreach_messages: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_sec: float = 0.0
    search_method: str = "ddg"  # ddg or serpapi

    def to_telegram_msg(self) -> str:
        """Format for Telegram display."""
        lines = [
            f"🔗 <b>Network Map: {self.company_name}</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"👥 Alumni Found: {self.alumni_found}",
            f"🏢 HR Contacts: {self.hr_contacts}",
            f"👔 Managers: {self.manager_contacts}",
            f"✉️ Drafts Generated: {self.outreach_drafts}",
            f"",
        ]

        if self.profiles:
            lines.append("<b>Key Contacts:</b>")
            for i, p in enumerate(self.profiles[:10], 1):
                degree_emoji = {1: "🟢", 2: "🟡", 3: "🔴"}.get(p.connection_degree, "⚪")
                lines.append(
                    f"  {i}. {degree_emoji} <b>{p.name}</b>"
                )
                lines.append(
                    f"     {p.current_role} | {p.contact_type.upper()}"
                )
                if p.linkedin_url:
                    lines.append(f"     🔗 {p.linkedin_url[:50]}...")
            lines.append("")

        if self.outreach_messages:
            lines.append("<b>📧 Outreach Draft (1st contact):</b>")
            first = self.outreach_messages[0]
            lines.append(f"<i>{first.get('draft', '')[:500]}</i>")

        return '\n'.join(lines)


class AlumniDiscovery:
    """
    Discovers alumni and professional contacts using
    DuckDuckGo dorks and SerpAPI.
    """

    def __init__(self, router: AIRouter, db: DatabaseManager):
        self.router = router
        self.db = db
        self._ddg = None
        self._serpapi_key = get_config().serp_api_key
        self._daily_serp_count = 0
        self._daily_serp_date = datetime.now(IST).date()

    def _get_ddg(self):
        if self._ddg is None:
            try:
                from duckduckgo_search import DDGS
                self._ddg = DDGS()
            except ImportError:
                logger.warning("duckduckgo_search not installed")
        return self._ddg

    def _can_use_serpapi(self, tier: int) -> bool:
        """Check if SerpAPI budget allows usage."""
        today = datetime.now(IST).date()
        if today != self._daily_serp_date:
            self._daily_serp_count = 0
            self._daily_serp_date = today

        return (
            self._serpapi_key and
            tier <= SERP_TIER_THRESHOLD and
            self._daily_serp_count < MAX_SERP_LOOKUPS_PER_DAY
        )

    def search_alumni(self, company: str, college: str, tier: int = 5) -> List[AlumniProfile]:
        """Search for alumni at a target company."""
        profiles = []
        seen_urls = set()

        # Strategy 1: DDG dorks (always available)
        ddg_profiles = self._ddg_alumni_search(company, college)
        for p in ddg_profiles:
            if p.linkedin_url not in seen_urls:
                seen_urls.add(p.linkedin_url)
                profiles.append(p)
        time.sleep(random.uniform(3, 8))

        # Strategy 2: SerpAPI (Tier 1-2 only, budget limited)
        if self._can_use_serpapi(tier) and len(profiles) < 5:
            serp_profiles = self._serpapi_alumni_search(company, college)
            for p in serp_profiles:
                if p.linkedin_url not in seen_urls:
                    seen_urls.add(p.linkedin_url)
                    p.source = 'serpapi'
                    profiles.append(p)
            self._daily_serp_count += 1

        return profiles

    def search_hr_contacts(self, company: str) -> List[AlumniProfile]:
        """Search for HR/TA contacts at a company."""
        ddg = self._get_ddg()
        if not ddg:
            return []

        profiles = []
        try:
            dork = DDG_HR_DORK.format(company=company)
            results = ddg.text(dork, region='in-en', max_results=10)

            for r in results:
                profile = self._parse_linkedin_result(r, 'hr')
                if profile:
                    profile.current_company = company
                    profile.connection_degree = 3
                    profiles.append(profile)

            time.sleep(random.uniform(5, 12))
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] HR search error: {e}")

        return profiles

    def search_managers(self, company: str, department: str = '') -> List[AlumniProfile]:
        """Search for hiring managers at a company."""
        ddg = self._get_ddg()
        if not ddg:
            return []

        profiles = []
        try:
            dork = DDG_MANAGER_DORK.format(company=company, department=department)
            results = ddg.text(dork, region='in-en', max_results=5)

            for r in results:
                profile = self._parse_linkedin_result(r, 'manager')
                if profile:
                    profile.current_company = company
                    profile.connection_degree = 3
                    profiles.append(profile)

            time.sleep(random.uniform(5, 12))
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Manager search error: {e}")

        return profiles

    def _ddg_alumni_search(self, company: str, college: str) -> List[AlumniProfile]:
        """Search DDG for alumni profiles."""
        ddg = self._get_ddg()
        if not ddg or not college:
            return []

        profiles = []
        try:
            dork = DDG_ALUMNI_DORK.format(
                college=college, company=company, keywords='alumni'
            )
            results = ddg.text(dork, region='in-en', max_results=10)

            for r in results:
                profile = self._parse_linkedin_result(r, 'alumni')
                if profile:
                    profile.college = college
                    profile.current_company = company
                    profile.connection_degree = 1
                    profiles.append(profile)

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] DDG alumni search error: {e}")

        return profiles

    def _serpapi_alumni_search(self, company: str, college: str) -> List[AlumniProfile]:
        """Search SerpAPI for alumni profiles (budget limited)."""
        if not self._serpapi_key:
            return []

        profiles = []
        try:
            import requests
            query = f'site:linkedin.com/in "{college}" "{company}" alumni india'
            resp = requests.get(
                'https://serpapi.com/search.json',
                params={
                    'q': query,
                    'api_key': self._serpapi_key,
                    'num': 10,
                },
                timeout=15,
            )

            if resp.status_code == 200:
                data = resp.json()
                for result in data.get('organic_results', []):
                    profile = AlumniProfile(
                        name=self._extract_name_from_title(result.get('title', '')),
                        linkedin_url=result.get('link', ''),
                        current_role=self._extract_role_from_snippet(result.get('snippet', '')),
                        college=college,
                        current_company=company,
                        connection_degree=1,
                        contact_type='alumni',
                        source='serpapi',
                    )
                    if profile.name and profile.linkedin_url:
                        profiles.append(profile)

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] SerpAPI error: {e}")

        return profiles

    def _parse_linkedin_result(self, result: Dict, contact_type: str) -> Optional[AlumniProfile]:
        """Parse a search result into an AlumniProfile."""
        title = result.get('title', '')
        url = result.get('href', '') or result.get('link', '')
        body = result.get('body', '') or result.get('snippet', '')

        if not url or 'linkedin.com/in' not in url:
            return None

        name = self._extract_name_from_title(title)
        role = self._extract_role_from_snippet(f"{title} {body}")

        if not name:
            return None

        return AlumniProfile(
            name=name,
            linkedin_url=url,
            current_role=role,
            contact_type=contact_type,
            source='ddg',
        )

    @staticmethod
    def _extract_name_from_title(title: str) -> str:
        """Extract person name from LinkedIn title."""
        if not title:
            return ""
        # LinkedIn titles: "First Last - Role at Company | LinkedIn"
        parts = title.split(' - ')
        if parts:
            name = parts[0].strip()
            # Remove "LinkedIn" suffix
            name = re.sub(r'\s*\|\s*LinkedIn\s*$', '', name, flags=re.IGNORECASE)
            # Remove emojis and special chars
            name = re.sub(r'[^\w\s.]', '', name).strip()
            if name and len(name.split()) >= 2:
                return name
        return ""

    @staticmethod
    def _extract_role_from_snippet(text: str) -> str:
        """Extract role from LinkedIn snippet."""
        if not text:
            return ""
        # Common patterns: "Title at Company"
        match = re.search(r'(?:^|\n)([^|]+?)(?:\s+at\s+|\s+@\s+)', text)
        if match:
            return match.group(1).strip()[:100]
        # Fallback: take text before first pipe or dash
        parts = re.split(r'[|–—]', text)
        if parts:
            return parts[0].strip()[:100]
        return text[:100]


class OutreachDraftGenerator:
    """Generates personalized outreach drafts using AI."""

    def __init__(self, router: AIRouter, db: DatabaseManager):
        self.router = router
        self.db = db

    def generate_draft(self, profile: AlumniProfile, company: str,
                      college: str, specialization: str = '') -> str:
        """Generate an outreach email draft."""
        context_key = profile.contact_type
        if context_key not in OUTREACH_CONTEXT:
            context_key = 'cold'

        system_prompt = OUTREACH_CONTEXT[context_key]
        user_prompt = (
            f"Write a warm outreach email.\n"
            f"Sender: MBA student at {college or 'a top B-school'}"
            f"{' specializing in ' + specialization if specialization else ''}\n"
            f"Recipient: {profile.name}, {profile.current_role} at {company}\n"
            f"Contact type: {profile.contact_type}\n"
            f"Connection: {'Direct alumni from same college' if profile.connection_degree == 1 else 'Professional connection'}\n"
            f"Goal: 15-minute informational chat about internship opportunities\n"
        )

        try:
            response = self.router.generate_outreach_draft(
                system_prompt, user_prompt
            )
            if response.success:
                return response.content
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Draft generation error: {e}")

        # Fallback template
        return self._fallback_template(profile, company, college)

    def _fallback_template(self, profile: AlumniProfile, company: str, college: str) -> str:
        """Generate a simple fallback outreach template."""
        greeting = f"Dear {profile.name.split()[0] if profile.name else 'Sir/Madam'},"
        if profile.contact_type == 'alumni':
            body = (
                f"I am an MBA student at {college or 'a leading business school'}, "
                f"and I noticed that you are an alumnus currently at {company}. "
                f"I am very interested in exploring internship opportunities at {company} "
                f"and would love to hear about your experience. Would you have 15 minutes "
                f"for a quick call this week?"
            )
        else:
            body = (
                f"I am an MBA student exploring internship opportunities at {company}. "
                f"I was impressed by the work your team is doing and would love to learn more. "
                f"Would you be open to a brief 15-minute conversation about potential opportunities?"
            )

        return f"{greeting}\n\n{body}\n\nBest regards"


class NetworkMapper:
    """
    Master network mapping engine.
    
    Pipeline:
        1. Validate company exists in database
        2. Search for alumni (DDG + SerpAPI if Tier 1-2)
        3. Search for HR/TA contacts
        4. Search for hiring managers
        5. Generate outreach drafts for top contacts
        6. Store results in alumni_contacts table
        7. Return formatted result
    """

    def __init__(self):
        self.db = get_db()
        self.router = get_router()
        self.config = get_config()
        self.discovery = AlumniDiscovery(self.router, self.db)
        self.drafts = OutreachDraftGenerator(self.router, self.db)

    def map_network(self, company_name: str, college: str = '',
                    specialization: str = '') -> NetworkMapResult:
        """
        Full network mapping for a company.
        
        Args:
            company_name: Target company
            college: User's college name
            specialization: MBA specialization
        
        Returns:
            NetworkMapResult with all discovered contacts
        """
        logger.info(f"[{AGENT_ID}] Mapping network for {company_name}")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, 'running')

        result = NetworkMapResult(company_name=company_name)

        # Get college from settings if not provided
        if not college:
            college = self.db.get_setting('college', '')
        if not specialization:
            specialization = self.db.get_setting('specialization', '')
        result.college = college

        # Resolve company
        company = self.db.fuzzy_match_company(company_name)
        if company:
            result.company_id = company.get('id')
            result.company_tier = company.get('tier', 5)
            result.company_name = company.get('name', company_name)

        # 1. Alumni search
        try:
            alumni = self.discovery.search_alumni(
                result.company_name, college, result.company_tier
            )
            for p in alumni:
                result.profiles.append(p)
                result.alumni_found += 1
        except Exception as e:
            result.errors.append(f"Alumni search: {e}")

        # 2. HR contacts
        try:
            hr = self.discovery.search_hr_contacts(result.company_name)
            for p in hr:
                result.profiles.append(p)
                result.hr_contacts += 1
        except Exception as e:
            result.errors.append(f"HR search: {e}")

        # 3. Managers (if we have department info)
        try:
            managers = self.discovery.search_managers(
                result.company_name, specialization
            )
            for p in managers:
                result.profiles.append(p)
                result.manager_contacts += 1
        except Exception as e:
            result.errors.append(f"Manager search: {e}")

        # 4. Sort profiles by priority (alumni first, then HR, then cold)
        result.profiles.sort(key=lambda p: p.connection_degree)

        # 5. Generate outreach drafts for top 3 contacts
        for profile in result.profiles[:3]:
            try:
                draft = self.drafts.generate_draft(
                    profile, result.company_name, college, specialization
                )
                if draft:
                    result.outreach_messages.append({
                        'name': profile.name,
                        'type': profile.contact_type,
                        'draft': draft,
                    })
                    result.outreach_drafts += 1
            except Exception as e:
                result.errors.append(f"Draft generation: {e}")

        # 6. Store in database
        for profile in result.profiles:
            try:
                contact = AlumniContact(
                    company_id=result.company_id,
                    name=profile.name,
                    linkedin_url=profile.linkedin_url,
                    college=profile.college or college,
                    batch_year=profile.batch_year,
                    current_role=profile.current_role,
                    connection_degree=profile.connection_degree,
                )
                self.db.insert_alumni_contact(contact)
            except Exception:
                pass

        result.duration_sec = round(time.time() - start_time, 1)
        self.db.update_agent_heartbeat(
            AGENT_ID, 'completed',
            items_processed=len(result.profiles),
            errors=len(result.errors),
            duration_sec=result.duration_sec,
        )

        logger.info(
            f"[{AGENT_ID}] Network map complete: "
            f"{result.alumni_found} alumni, "
            f"{result.hr_contacts} HR, "
            f"{result.manager_contacts} managers"
        )

        return result

    def get_existing_contacts(self, company_name: str) -> List[Dict]:
        """Get previously discovered contacts from database."""
        company = self.db.fuzzy_match_company(company_name)
        if not company:
            return []
        return self.db.get_alumni_by_company(company['id'])


_mapper_instance: Optional[NetworkMapper] = None

def get_network_mapper() -> NetworkMapper:
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = NetworkMapper()
    return _mapper_instance


if __name__ == "__main__":
    print(f"✅ {AGENT_NAME} ({AGENT_ID}) ready")
    print(f"  SerpAPI daily budget: {MAX_SERP_LOOKUPS_PER_DAY}")
    print(f"  SerpAPI tier threshold: Tier ≤ {SERP_TIER_THRESHOLD}")
    print(f"  Outreach templates: {len(OUTREACH_CONTEXT)}")
