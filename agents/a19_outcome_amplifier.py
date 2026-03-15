"""
============================================================
PRISM v0.1 — A-19: OUTCOME AMPLIFIER (FOLLOW-UP TRACKER)
============================================================
Agent A-19: Tracks application status and sends follow-up emails
for silent applications after 7 days.

Schedule: Daily 10:30 IST

Pipeline:
    1. Load outcomes table: applications > 7 days old with no response
    2. Check Internshala status tracker API (if applicable)
    3. For silent applications → generate concise follow-up email
    4. Send follow-up via Brevo (A-15's email_sender)
    5. Update outcome status (follow_up_sent_at)
    6. Track engagement (opens/clicks via webhooks)

AI Provider: Cerebras 8B (followup_draft task)
Tools: Brevo API, Internshala status API, db_read/write
Cost: $0

Integration Points:
    - A-13 Auto Applier → populates outcomes table
    - A-15 Email Applier → shared Brevo sender
    - A-11 Outcome Learner → uses follow-up response data
    - A-12 Telegram Reporter → daily follow-up summary
============================================================
"""

import os
import sys
import json
import time
import asyncio
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

AGENT_ID = "A-19"
AGENT_NAME = "Outcome Amplifier"

FOLLOWUP_WAIT_DAYS = 7  # Wait 7 days before first follow-up
MAX_FOLLOWUPS_PER_APPLICATION = 2  # Max 2 follow-ups
MAX_FOLLOWUPS_PER_DAY = 10  # Conserve email quota for A-15
SECOND_FOLLOWUP_WAIT_DAYS = 14  # Wait another 7 days for second follow-up


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class SilentApplication:
    """An application that hasn't received a response."""
    outcome_id: int
    listing_id: int
    company: str
    role: str
    applied_at: str
    days_since_applied: int
    source: str = ""  # internshala, greenhouse, lever, email
    contact_email: str = ""
    contact_name: str = ""
    followup_count: int = 0
    last_followup_at: str = ""
    current_status: str = "applied"
    # Internshala-specific
    internshala_status: str = ""  # seen, shortlisted, etc.


@dataclass
class FollowUpRunResult:
    """Result of a follow-up run."""
    total_silent: int = 0
    followups_sent: int = 0
    followups_skipped: int = 0
    status_updates: int = 0
    errors: List[str] = field(default_factory=list)
    run_time_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_silent': self.total_silent,
            'followups_sent': self.followups_sent,
            'followups_skipped': self.followups_skipped,
            'status_updates': self.status_updates,
            'run_time_seconds': round(self.run_time_seconds, 1),
        }


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class OutcomeAmplifier:
    """
    PRISM A-19: Outcome Amplifier Agent.

    Tracks application outcomes and sends strategic follow-up
    emails for silent applications.

    Usage:
        amplifier = get_outcome_amplifier()
        result = await amplifier.run_followup_check()
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
        self._total_followups_sent = 0
        self._total_status_updates = 0
        self._last_run_time: Optional[str] = None

        logger.info(f"[{AGENT_ID}] {AGENT_NAME} initialized")

    # ----------------------------------------------------------
    # LOAD SILENT APPLICATIONS
    # ----------------------------------------------------------

    def _load_silent_applications(self) -> List[SilentApplication]:
        """Load applications that need follow-up from outcomes table."""
        silent_apps = []
        try:
            from core.database import get_db
            db = get_db()

            cutoff_date = (
                datetime.now(IST) - timedelta(days=FOLLOWUP_WAIT_DAYS)
            ).isoformat()

            with db.get_cursor() as cur:
                cur.execute("""
                    SELECT o.id, o.listing_id, o.company, o.role,
                           o.applied_at, o.status, o.source,
                           o.followup_count, o.last_followup_at,
                           o.contact_email, o.contact_name
                    FROM outcomes o
                    WHERE o.status = 'applied'
                      AND o.applied_at < ?
                      AND COALESCE(o.followup_count, 0) < ?
                    ORDER BY o.applied_at ASC
                    LIMIT ?
                """, (cutoff_date, MAX_FOLLOWUPS_PER_APPLICATION, MAX_FOLLOWUPS_PER_DAY * 2))

                rows = cur.fetchall()
                columns = [d[0] for d in cur.description]

                for row in rows:
                    data = dict(zip(columns, row))

                    applied_dt = datetime.fromisoformat(
                        data['applied_at']
                    ) if data.get('applied_at') else datetime.now(IST)
                    days_since = (datetime.now(IST) - applied_dt.replace(
                        tzinfo=IST if applied_dt.tzinfo is None else applied_dt.tzinfo
                    )).days

                    # Check if enough time has passed since last follow-up
                    if data.get('last_followup_at'):
                        last_fu = datetime.fromisoformat(data['last_followup_at'])
                        days_since_fu = (datetime.now(IST) - last_fu.replace(
                            tzinfo=IST if last_fu.tzinfo is None else last_fu.tzinfo
                        )).days
                        if days_since_fu < FOLLOWUP_WAIT_DAYS:
                            continue

                    silent_apps.append(SilentApplication(
                        outcome_id=data['id'],
                        listing_id=data.get('listing_id', 0),
                        company=data.get('company', ''),
                        role=data.get('role', ''),
                        applied_at=data.get('applied_at', ''),
                        days_since_applied=days_since,
                        source=data.get('source', ''),
                        contact_email=data.get('contact_email', ''),
                        contact_name=data.get('contact_name', ''),
                        followup_count=data.get('followup_count', 0) or 0,
                        last_followup_at=data.get('last_followup_at', '') or '',
                    ))

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Load silent apps error: {e}")

        logger.info(f"[{AGENT_ID}] Found {len(silent_apps)} silent applications")
        return silent_apps[:MAX_FOLLOWUPS_PER_DAY]

    # ----------------------------------------------------------
    # FOLLOW-UP GENERATION
    # ----------------------------------------------------------

    async def _generate_followup(
        self,
        app: SilentApplication,
    ) -> Optional[str]:
        """Generate a concise follow-up email body."""
        try:
            from core.ai_router import get_router
            router = get_router()

            prompt = f"""Write a very concise follow-up email (max 80 words) for a silent job application.

Company: {app.company}
Role: {app.role}
Applied: {app.days_since_applied} days ago
Follow-up #: {app.followup_count + 1}

Requirements:
- Be polite and professional
- Reference the original application
- Add ONE new value point
- Have a clear but gentle ask
- Keep under 80 words
- NO subject line, just the body

Write the follow-up body:"""

            response = router.call('followup_draft', prompt, use_cache=False)
            if response.success and response.content:
                return response.content.strip()

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Follow-up generation error: {e}")

        return None

    # ----------------------------------------------------------
    # MAIN RUN
    # ----------------------------------------------------------

    async def run_followup_check(self) -> FollowUpRunResult:
        """
        Execute a complete follow-up check.
        Loads silent applications, generates follow-ups, sends emails.
        """
        start_time = time.time()
        result = FollowUpRunResult()

        logger.info(f"[{AGENT_ID}] Starting follow-up check...")
        self._update_heartbeat('running')

        try:
            # Load silent applications
            silent_apps = self._load_silent_applications()
            result.total_silent = len(silent_apps)

            if not silent_apps:
                logger.info(f"[{AGENT_ID}] No applications need follow-up")
                self._update_heartbeat('idle')
                return result

            # Process each silent application
            from core.email_sender import get_email_sender, EmailRecipient
            sender = get_email_sender()

            # PRISM v0.1 FIX: Skip if Brevo email sender is not configured
            if not sender.is_configured:
                logger.warning(
                    f"[{AGENT_ID}] Brevo not configured, skipping follow-up run "
                    f"(set BREVO_API_KEY + BREVO_SENDER_EMAIL)"
                )
                result.errors.append("Brevo not configured")
                self._update_heartbeat('idle')
                return result

            for app in silent_apps:
                try:
                    # Skip if no contact email
                    if not app.contact_email:
                        result.followups_skipped += 1
                        continue

                    # Generate follow-up text
                    followup_text = await self._generate_followup(app)
                    if not followup_text:
                        result.followups_skipped += 1
                        continue

                    # Send via Brevo
                    recipient = EmailRecipient(
                        email=app.contact_email,
                        name=app.contact_name or 'Hiring Manager',
                        company=app.company,
                    )

                    email_result = await sender.send_followup(
                        recipient=recipient,
                        original_subject=f"Application for {app.role} at {app.company}",
                        personalization={
                            'company': app.company,
                            'followup_hook': followup_text,
                        },
                    )

                    if email_result.success:
                        result.followups_sent += 1
                        self._total_followups_sent += 1

                        # Update database
                        self._record_followup(app.outcome_id)
                    else:
                        result.followups_skipped += 1

                except Exception as e:
                    result.errors.append(f"{app.company}: {str(e)}")

                # Delay between follow-ups
                await asyncio.sleep(5.0)

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Follow-up run error: {e}")
            result.errors.append(str(e))

        result.run_time_seconds = time.time() - start_time
        self._last_run_time = datetime.now(IST).isoformat()
        self._update_heartbeat('idle')

        logger.info(
            f"[{AGENT_ID}] Follow-up check complete: "
            f"{result.followups_sent} sent, "
            f"{result.followups_skipped} skipped"
        )

        return result

    # ----------------------------------------------------------
    # DATABASE
    # ----------------------------------------------------------

    def _record_followup(self, outcome_id: int):
        """Record a follow-up in the outcomes table."""
        try:
            from core.database import get_db
            db = get_db()

            with db.get_cursor() as cur:
                cur.execute("""
                    UPDATE outcomes
                    SET followup_count = COALESCE(followup_count, 0) + 1,
                        last_followup_at = ?
                    WHERE id = ?
                """, (datetime.now(IST).isoformat(), outcome_id))

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Record follow-up error: {e}")

    def _update_heartbeat(self, status: str):
        try:
            from core.database import get_db
            get_db().update_agent_heartbeat(AGENT_ID, status)
        except Exception:
            pass

    def get_health(self) -> Dict[str, Any]:
        return {
            'agent_id': AGENT_ID,
            'agent_name': AGENT_NAME,
            'total_followups_sent': self._total_followups_sent,
            'total_status_updates': self._total_status_updates,
            'last_run_time': self._last_run_time,
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_instance: Optional[OutcomeAmplifier] = None

def get_outcome_amplifier() -> OutcomeAmplifier:
    global _instance
    if _instance is None:
        _instance = OutcomeAmplifier()
    return _instance
