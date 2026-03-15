"""
============================================================
PRISM v0.1 — A-15: EMAIL AUTO-APPLIER (BREVO OUTREACH ENGINE)
============================================================
Agent A-15: Automated email outreach to HR contacts and alumni
discovered by A-09 (Network Mapper).

Schedule: Daily 09:30 IST
Trigger: outreach_queue populated by A-09

Pipeline:
    1. Load outreach_queue from database (contacts with verified emails)
    2. Prioritize: alumni warm > Tier 1-2 HR > Tier 3+ HR
    3. For each contact:
        a. Load company intel from A-20 (Deep Company Intel)
        b. Generate 2-3 personalization sentences via Groq 70B
        c. Render email template with personalization
        d. Send via Brevo API
        e. Record in alumni_contacts (sent_at, message_id)
    4. Respect daily quota (300/day Brevo free tier)
    5. Log results to Telegram

AI Provider: Groq 70B (email_personalize task)
Tools: Brevo REST API, db_read/write
Cost: $0 (Brevo free tier + Groq free tier)

Integration Points:
    - A-09 Network Mapper → populates outreach_queue
    - A-20 Deep Company Intel → provides company_hooks
    - A-19 Outcome Amplifier → reads sent status for follow-ups
    - A-12 Telegram Reporter → daily outreach summary
============================================================
"""

import os
import sys
import json
import time
import asyncio
import hashlib
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Set
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

AGENT_ID = "A-15"
AGENT_NAME = "Email Auto-Applier"
MAX_EMAILS_PER_RUN = 30  # Conserve quota across runs
MIN_COMPANY_TIER_FOR_PRIORITY = 2  # Tier 1-2 get priority
PERSONALIZATION_CACHE_TTL_HOURS = 48

# Email sending delays (human mimicry)
MIN_DELAY_BETWEEN_EMAILS = 3.0  # seconds
MAX_DELAY_BETWEEN_EMAILS = 8.0  # seconds


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class OutreachCandidate:
    """A candidate for email outreach."""
    contact_id: int
    email: str
    name: str
    company: str
    role: str = ""
    connection_type: str = ""  # alumni, hr, recruiter
    company_tier: int = 5
    linkedin_url: str = ""
    # Enrichment data
    company_intel: str = ""  # From A-20
    recent_news: str = ""
    # Personalization
    personalization_hooks: Dict[str, str] = field(default_factory=dict)
    # Status
    already_contacted: bool = False
    last_contact_date: Optional[str] = None
    priority_score: float = 0.0


@dataclass
class OutreachRunResult:
    """Result of a complete outreach run."""
    total_candidates: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    emails_skipped: int = 0
    quota_remaining: int = 0
    run_time_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_candidates': self.total_candidates,
            'emails_sent': self.emails_sent,
            'emails_failed': self.emails_failed,
            'emails_skipped': self.emails_skipped,
            'quota_remaining': self.quota_remaining,
            'run_time_seconds': round(self.run_time_seconds, 1),
            'errors': self.errors[:5],
        }


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class EmailAutoApplier:
    """
    PRISM A-15: Email Auto-Applier Agent.

    Sends personalized outreach emails to HR contacts and alumni
    discovered by A-09 (Network Mapper). Uses Brevo free tier
    (300 emails/day) with AI-powered personalization.

    Usage:
        agent = get_email_applier()
        result = await agent.run_outreach()
        result = await agent.send_single_outreach(contact_id)
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

        # Stats
        self._total_runs = 0
        self._total_emails_sent = 0
        self._total_emails_failed = 0
        self._last_run_time: Optional[str] = None

        logger.info(f"[{AGENT_ID}] {AGENT_NAME} initialized")

    # ----------------------------------------------------------
    # OUTREACH QUEUE LOADING
    # ----------------------------------------------------------

    def _load_outreach_queue(self) -> List[OutreachCandidate]:
        """
        Load the outreach queue from database.
        Filters out already-contacted recipients and prioritizes by company tier.
        """
        candidates = []
        try:
            from core.database import get_db
            db = get_db()

            with db.get_cursor() as cur:
                # Load contacts from alumni_contacts that haven't been emailed
                cur.execute("""
                    SELECT ac.id, ac.email, ac.name, ac.company, ac.current_role,
                           ac.connection_type, ac.linkedin_url, ac.email_sent_at,
                           COALESCE(c.tier, 5) as company_tier
                    FROM alumni_contacts ac
                    LEFT JOIN companies c ON LOWER(ac.company) = LOWER(c.name)
                    WHERE ac.email IS NOT NULL
                      AND ac.email != ''
                      AND (ac.email_sent_at IS NULL OR ac.email_sent_at = '')
                    ORDER BY COALESCE(c.tier, 5) ASC, ac.id DESC
                    LIMIT ?
                """, (MAX_EMAILS_PER_RUN * 2,))  # Load extra for filtering

                rows = cur.fetchall()
                columns = [d[0] for d in cur.description]

                for row in rows:
                    data = dict(zip(columns, row))
                    candidate = OutreachCandidate(
                        contact_id=data['id'],
                        email=data['email'],
                        name=data.get('name', ''),
                        company=data.get('company', ''),
                        role=data.get('current_role', ''),
                        connection_type=data.get('connection_type', 'hr'),
                        company_tier=data.get('company_tier', 5),
                        linkedin_url=data.get('linkedin_url', ''),
                        already_contacted=bool(data.get('email_sent_at')),
                    )

                    # Calculate priority score
                    candidate.priority_score = self._calculate_priority(candidate)
                    candidates.append(candidate)

            # Sort by priority (highest first)
            candidates.sort(key=lambda c: c.priority_score, reverse=True)

            logger.info(
                f"[{AGENT_ID}] Loaded {len(candidates)} outreach candidates"
            )

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Failed to load outreach queue: {e}")

        return candidates[:MAX_EMAILS_PER_RUN]

    def _calculate_priority(self, candidate: OutreachCandidate) -> float:
        """Calculate outreach priority score (0-100)."""
        score = 0.0

        # Connection type bonus
        if candidate.connection_type == 'alumni':
            score += 40.0  # Alumni are highest priority
        elif candidate.connection_type in ('hr', 'recruiter'):
            score += 25.0
        else:
            score += 10.0

        # Company tier bonus (Tier 1 = 30, Tier 5 = 6)
        tier_scores = {1: 30, 2: 24, 3: 18, 4: 12, 5: 6}
        score += tier_scores.get(candidate.company_tier, 6)

        # Has LinkedIn = +5 (more likely to respond)
        if candidate.linkedin_url:
            score += 5.0

        # Has role info = +5 (better personalization)
        if candidate.role:
            score += 5.0

        return min(100.0, score)

    # ----------------------------------------------------------
    # PERSONALIZATION
    # ----------------------------------------------------------

    async def _generate_personalization(
        self,
        candidate: OutreachCandidate,
    ) -> Dict[str, str]:
        """
        Generate AI-powered personalization for the email.
        Uses Groq 70B for natural, compelling sentences.
        """
        personalization = {
            'recipient_name': candidate.name or 'Hiring Manager',
            'company': candidate.company,
            'target_domain': 'marketing and strategy',
            'personalization_paragraph': '',
            'company_hook': '',
            'closing_hook': 'Looking forward to hearing from you.',
        }

        try:
            from core.ai_router import get_router
            router = get_router()

            # Generate personalized paragraph
            prompt = f"""Write 2-3 personalized sentences for an MBA student's outreach email to
{candidate.name or 'a professional'} at {candidate.company}.
Connection type: {candidate.connection_type}
Their role: {candidate.role or 'Unknown'}
Company Intel: {candidate.company_intel[:500] if candidate.company_intel else 'No intel available'}
Recent News: {candidate.recent_news[:300] if candidate.recent_news else 'None'}

Requirements:
- Be specific about the company (mention real details if available)
- Be warm and professional, not pushy
- Reference their role if known
- Keep it to 2-3 sentences total
- Do NOT include greetings or sign-offs

Write only the personalization sentences:"""

            response = router.call('email_personalize', prompt, use_cache=True)
            if response.success and response.content:
                personalization['personalization_paragraph'] = response.content.strip()

                # Also generate a company hook
                if candidate.company_intel:
                    personalization['company_hook'] = (
                        candidate.company_intel[:200].split('.')[0] + '.'
                    )

        except Exception as e:
            logger.warning(
                f"[{AGENT_ID}] Personalization generation failed for "
                f"{candidate.company}: {e}"
            )

        return personalization

    # ----------------------------------------------------------
    # MAIN OUTREACH RUN
    # ----------------------------------------------------------

    async def run_outreach(self) -> OutreachRunResult:
        """
        Execute a complete outreach run.
        Loads queue, generates personalization, sends emails.

        Returns:
            OutreachRunResult with summary
        """
        start_time = time.time()
        result = OutreachRunResult()

        logger.info(f"[{AGENT_ID}] Starting outreach run...")

        # Update heartbeat
        self._update_heartbeat('running')

        try:
            # Load outreach queue
            candidates = self._load_outreach_queue()
            result.total_candidates = len(candidates)

            if not candidates:
                logger.info(f"[{AGENT_ID}] No candidates in outreach queue")
                self._update_heartbeat('idle')
                return result

            # Get email sender
            from core.email_sender import (
                get_email_sender, EmailRecipient, EmailType
            )
            sender = get_email_sender()

            if not sender.is_configured:
                logger.warning(f"[{AGENT_ID}] Brevo not configured, skipping run")
                result.errors.append("Brevo not configured")
                self._update_heartbeat('idle')
                return result

            # Process each candidate
            import random
            for i, candidate in enumerate(candidates):
                # Check quota
                health = sender.get_health()
                if health['quota']['remaining'] <= 10:
                    logger.warning(
                        f"[{AGENT_ID}] Quota nearly exhausted "
                        f"(remaining: {health['quota']['remaining']})"
                    )
                    break

                try:
                    # Generate personalization
                    personalization = await self._generate_personalization(candidate)

                    # Create recipient
                    recipient = EmailRecipient(
                        email=candidate.email,
                        name=candidate.name,
                        company=candidate.company,
                        role=candidate.role,
                        connection_type=candidate.connection_type,
                        linkedin_url=candidate.linkedin_url,
                        source_agent=AGENT_ID,
                    )

                    # Send email based on connection type
                    if candidate.connection_type == 'alumni':
                        email_result = await sender.send_alumni_outreach(
                            recipient=recipient,
                            personalization=personalization,
                        )
                    else:
                        email_result = await sender.send_hr_outreach(
                            recipient=recipient,
                            personalization=personalization,
                        )

                    if email_result.success:
                        result.emails_sent += 1
                        self._total_emails_sent += 1

                        # Update database
                        self._mark_email_sent(
                            candidate.contact_id,
                            email_result.message_id,
                        )
                    else:
                        if email_result.status.value == 'blocked':
                            result.emails_skipped += 1
                        else:
                            result.emails_failed += 1
                            self._total_emails_failed += 1
                            result.errors.append(
                                f"{candidate.company}: {email_result.error}"
                            )

                except Exception as e:
                    result.emails_failed += 1
                    result.errors.append(f"{candidate.company}: {str(e)}")
                    logger.error(
                        f"[{AGENT_ID}] Error processing {candidate.email}: {e}"
                    )

                # Human-mimicry delay between emails
                if i < len(candidates) - 1:
                    delay = random.uniform(
                        MIN_DELAY_BETWEEN_EMAILS, MAX_DELAY_BETWEEN_EMAILS
                    )
                    await asyncio.sleep(delay)

            # Get final quota status
            health = sender.get_health()
            result.quota_remaining = health['quota']['remaining']

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Outreach run failed: {e}")
            result.errors.append(str(e))

        result.run_time_seconds = time.time() - start_time
        self._total_runs += 1
        self._last_run_time = datetime.now(IST).isoformat()

        # Update heartbeat
        self._update_heartbeat('idle')

        # Log summary
        logger.info(
            f"[{AGENT_ID}] Outreach complete: "
            f"{result.emails_sent} sent, {result.emails_failed} failed, "
            f"{result.emails_skipped} skipped "
            f"(quota: {result.quota_remaining} remaining)"
        )

        return result

    # ----------------------------------------------------------
    # DATABASE HELPERS
    # ----------------------------------------------------------

    def _mark_email_sent(self, contact_id: int, message_id: str):
        """Mark a contact as emailed in the database."""
        try:
            from core.database import get_db
            db = get_db()
            now = datetime.now(IST).isoformat()

            with db.get_cursor() as cur:
                cur.execute("""
                    UPDATE alumni_contacts
                    SET email_sent_at = ?, brevo_message_id = ?
                    WHERE id = ?
                """, (now, message_id, contact_id))

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Failed to mark email sent: {e}")

    def _update_heartbeat(self, status: str):
        """Update agent heartbeat in the database."""
        try:
            from core.database import get_db
            db = get_db()
            db.update_agent_heartbeat(AGENT_ID, status)
        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Heartbeat update failed: {e}")

    # ----------------------------------------------------------
    # HEALTH & MONITORING
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get agent health status."""
        return {
            'agent_id': AGENT_ID,
            'agent_name': AGENT_NAME,
            'total_runs': self._total_runs,
            'total_emails_sent': self._total_emails_sent,
            'total_emails_failed': self._total_emails_failed,
            'last_run_time': self._last_run_time,
            'max_per_run': MAX_EMAILS_PER_RUN,
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_instance: Optional[EmailAutoApplier] = None

def get_email_applier() -> EmailAutoApplier:
    """Get the singleton EmailAutoApplier instance."""
    global _instance
    if _instance is None:
        _instance = EmailAutoApplier()
    return _instance


if __name__ == "__main__":
    print("=" * 60)
    print(f"PRISM v0.1 — {AGENT_ID}: {AGENT_NAME}")
    print("=" * 60)
    agent = get_email_applier()
    health = agent.get_health()
    for k, v in health.items():
        print(f"  {k}: {v}")
    print("=" * 60)
