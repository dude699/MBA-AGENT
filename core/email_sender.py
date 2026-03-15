"""
============================================================
PRISM v0.1 — EMAIL SENDER ENGINE (BREVO / SENDINBLUE)
============================================================
Complete email outreach engine built on Brevo's free tier.

Free Tier Limits (2026):
    - 300 emails/day
    - Unlimited contacts
    - Open/click tracking via webhooks
    - Template support

Used By:
    A-15: Email Auto-Applier — Cold outreach to HR/Alumni
    A-19: Outcome Amplifier — Follow-up emails for silent applications

Architecture:
    - Brevo REST API v3 (POST /v3/smtp/email)
    - Thread-safe singleton with daily quota tracking
    - Template system for outreach, follow-up, and warm intro
    - Open/click webhook handler for tracking engagement
    - Rate limiting to stay within 300/day cap
    - Deduplication to prevent double-sending
    - Email queue with priority (alumni warm > HR cold > follow-up)
    - Personalization hooks from A-20 Deep Company Intel

Email Types:
    1. Alumni Warm Intro — Personalized MBA-to-MBA outreach
    2. HR Cold Outreach — Professional cold email to recruiters
    3. Direct Application — Application email with CV attachment
    4. Follow-up — Concise 7-day follow-up for silent applications
    5. Thank You — Post-interview thank you notes

Cost: $0 — 100% Brevo free tier
============================================================
"""

import os
import sys
import json
import time
import hashlib
import threading
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import (
    Dict, List, Optional, Tuple, Any, Union, Set
)
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS & ENUMS
# ============================================================

BREVO_API_BASE = "https://api.brevo.com/v3"
BREVO_SEND_ENDPOINT = f"{BREVO_API_BASE}/smtp/email"
BREVO_CONTACTS_ENDPOINT = f"{BREVO_API_BASE}/contacts"
BREVO_WEBHOOKS_ENDPOINT = f"{BREVO_API_BASE}/webhooks"

MAX_SUBJECT_LENGTH = 200
MAX_BODY_LENGTH = 50000
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5.0


class EmailType(Enum):
    """Types of emails the system sends."""
    ALUMNI_WARM = "alumni_warm"
    HR_COLD = "hr_cold"
    DIRECT_APPLICATION = "direct_application"
    FOLLOWUP = "followup"
    THANK_YOU = "thank_you"
    CUSTOM = "custom"


class EmailPriority(Enum):
    """Email priority for queue ordering."""
    CRITICAL = 1    # Alumni warm intro (highest conversion)
    HIGH = 2        # HR cold outreach (Tier 1-2 companies)
    MEDIUM = 3      # Direct application emails
    LOW = 4         # Follow-ups and thank-yous
    BATCH = 5       # Bulk/batch emails


class EmailStatus(Enum):
    """Tracking status for sent emails."""
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"
    BLOCKED = "blocked"  # Recipient already contacted


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class EmailRecipient:
    """Email recipient with metadata."""
    email: str
    name: str = ""
    company: str = ""
    role: str = ""
    connection_type: str = ""  # alumni, hr, recruiter, direct
    linkedin_url: str = ""
    source_agent: str = ""  # Which agent discovered this contact


@dataclass
class EmailMessage:
    """Complete email message ready for sending."""
    to: EmailRecipient
    subject: str
    html_body: str
    text_body: str = ""
    email_type: EmailType = EmailType.CUSTOM
    priority: EmailPriority = EmailPriority.MEDIUM
    # Metadata
    listing_id: Optional[int] = None
    company_name: str = ""
    personalization_hooks: Dict[str, str] = field(default_factory=dict)
    # Attachments (CV path)
    attachment_path: Optional[str] = None
    attachment_name: str = "Resume_Abuzar_Khan.pdf"
    # Tracking
    track_opens: bool = True
    track_clicks: bool = True
    # Tags for Brevo
    tags: List[str] = field(default_factory=list)
    # Reply-to
    reply_to_email: str = ""
    reply_to_name: str = ""


@dataclass
class EmailResult:
    """Result of an email send attempt."""
    success: bool
    message_id: str = ""
    recipient_email: str = ""
    email_type: str = ""
    error: Optional[str] = None
    status: EmailStatus = EmailStatus.QUEUED
    sent_at: Optional[str] = None
    latency_ms: float = 0.0
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'message_id': self.message_id,
            'recipient_email': self.recipient_email,
            'email_type': self.email_type,
            'error': self.error,
            'status': self.status.value,
            'sent_at': self.sent_at,
            'latency_ms': self.latency_ms,
        }


@dataclass
class WebhookEvent:
    """Brevo webhook event for tracking."""
    event_type: str  # delivered, opened, clicked, bounced, spam
    email: str
    message_id: str
    timestamp: str
    ip: str = ""
    link: str = ""  # For click events
    reason: str = ""  # For bounce events


# ============================================================
# EMAIL TEMPLATES
# ============================================================

EMAIL_TEMPLATES: Dict[str, Dict[str, str]] = {
    'alumni_warm': {
        'subject': '{connection_hook} — {candidate_name} from {college} (MBA {year})',
        'html': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <p>Dear {recipient_name},</p>

    <p>I hope this message finds you well. I'm {candidate_name}, currently pursuing my MBA at
    {college} (Class of {year}), specializing in {specialization}.</p>

    <p>{personalization_paragraph}</p>

    <p>I came across your profile and noticed your incredible journey at {company}.
    {company_hook}</p>

    <p>I'm actively exploring internship opportunities in {target_domain} and would
    love to learn from your experience at {company}. Would you be open to a brief
    15-minute conversation at your convenience?</p>

    <p>{closing_hook}</p>

    <p>Warm regards,<br>
    <strong>{candidate_name}</strong><br>
    MBA {year} | {college}<br>
    {candidate_phone}<br>
    {candidate_linkedin}</p>
</div>""",
        'text': """Dear {recipient_name},

I hope this message finds you well. I'm {candidate_name}, currently pursuing my MBA at {college} (Class of {year}), specializing in {specialization}.

{personalization_paragraph}

I came across your profile and noticed your incredible journey at {company}. {company_hook}

I'm actively exploring internship opportunities in {target_domain} and would love to learn from your experience at {company}. Would you be open to a brief 15-minute conversation at your convenience?

{closing_hook}

Warm regards,
{candidate_name}
MBA {year} | {college}
{candidate_phone}
{candidate_linkedin}""",
    },

    'hr_cold': {
        'subject': 'MBA Intern Application — {target_role} at {company}',
        'html': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <p>Dear {recipient_name},</p>

    <p>I'm writing to express my interest in internship opportunities at {company},
    particularly in {target_domain}.</p>

    <p>{company_specific_paragraph}</p>

    <p>I'm {candidate_name}, an MBA candidate at {college} (Class of {year}), with
    prior experience in {experience_summary}. My key strengths include:</p>

    <ul>
        {skills_bullets}
    </ul>

    <p>{value_proposition}</p>

    <p>I've attached my resume for your reference. I would be grateful for the
    opportunity to discuss how I can contribute to {company}'s {department} team.</p>

    <p>Thank you for your time and consideration.</p>

    <p>Best regards,<br>
    <strong>{candidate_name}</strong><br>
    MBA {year} | {college}<br>
    {candidate_phone}<br>
    {candidate_linkedin}</p>
</div>""",
        'text': """Dear {recipient_name},

I'm writing to express my interest in internship opportunities at {company}, particularly in {target_domain}.

{company_specific_paragraph}

I'm {candidate_name}, an MBA candidate at {college} (Class of {year}), with prior experience in {experience_summary}. My key strengths include:
{skills_text}

{value_proposition}

I've attached my resume for your reference. I would be grateful for the opportunity to discuss how I can contribute to {company}'s {department} team.

Thank you for your time and consideration.

Best regards,
{candidate_name}
MBA {year} | {college}
{candidate_phone}
{candidate_linkedin}""",
    },

    'followup': {
        'subject': 'Following Up — {original_subject}',
        'html': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <p>Dear {recipient_name},</p>

    <p>I hope you're doing well. I wanted to follow up on my previous email
    regarding internship opportunities at {company}.</p>

    <p>{followup_hook}</p>

    <p>I understand you must be busy, and I truly appreciate any time you can
    spare. Even a brief pointer in the right direction would be incredibly helpful.</p>

    <p>Thank you again for your consideration.</p>

    <p>Best regards,<br>
    <strong>{candidate_name}</strong><br>
    MBA {year} | {college}</p>
</div>""",
        'text': """Dear {recipient_name},

I hope you're doing well. I wanted to follow up on my previous email regarding internship opportunities at {company}.

{followup_hook}

I understand you must be busy, and I truly appreciate any time you can spare. Even a brief pointer in the right direction would be incredibly helpful.

Thank you again for your consideration.

Best regards,
{candidate_name}
MBA {year} | {college}""",
    },

    'thank_you': {
        'subject': 'Thank You — {event_type} with {company}',
        'html': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
    <p>Dear {recipient_name},</p>

    <p>Thank you so much for {event_description}. I thoroughly enjoyed our
    conversation and learning more about {company}'s {department} team.</p>

    <p>{specific_reference}</p>

    <p>I'm even more excited about the possibility of contributing to {company}
    and remain eager to bring my {skills_mention} to the team.</p>

    <p>Please don't hesitate to reach out if you need any additional information
    from my end.</p>

    <p>Warm regards,<br>
    <strong>{candidate_name}</strong><br>
    MBA {year} | {college}</p>
</div>""",
        'text': """Dear {recipient_name},

Thank you so much for {event_description}. I thoroughly enjoyed our conversation and learning more about {company}'s {department} team.

{specific_reference}

I'm even more excited about the possibility of contributing to {company} and remain eager to bring my {skills_mention} to the team.

Please don't hesitate to reach out if you need any additional information from my end.

Warm regards,
{candidate_name}
MBA {year} | {college}""",
    },
}


# ============================================================
# DAILY QUOTA TRACKER
# ============================================================

class DailyQuotaTracker:
    """
    Thread-safe daily email quota tracker.
    Resets at midnight IST.
    """

    def __init__(self, daily_limit: int = 300):
        self.daily_limit = daily_limit
        self._count = 0
        self._date = date.today()
        self._lock = threading.Lock()
        self._sent_hashes: Set[str] = set()  # Dedup by recipient+type

    def _reset_if_new_day(self):
        """Reset counter if a new day has started."""
        today = date.today()
        if today != self._date:
            self._count = 0
            self._date = today
            self._sent_hashes.clear()

    def can_send(self) -> bool:
        """Check if we can send another email today."""
        with self._lock:
            self._reset_if_new_day()
            return self._count < self.daily_limit

    def record_send(self, recipient_email: str, email_type: str):
        """Record a sent email."""
        with self._lock:
            self._reset_if_new_day()
            self._count += 1
            dedup_key = f"{recipient_email}:{email_type}"
            self._sent_hashes.add(hashlib.md5(dedup_key.encode()).hexdigest())

    def already_sent(self, recipient_email: str, email_type: str) -> bool:
        """Check if we already sent this type of email to this recipient today."""
        with self._lock:
            self._reset_if_new_day()
            dedup_key = f"{recipient_email}:{email_type}"
            return hashlib.md5(dedup_key.encode()).hexdigest() in self._sent_hashes

    def remaining(self) -> int:
        """Get remaining email quota for today."""
        with self._lock:
            self._reset_if_new_day()
            return max(0, self.daily_limit - self._count)

    def get_stats(self) -> Dict[str, Any]:
        """Get quota statistics."""
        with self._lock:
            self._reset_if_new_day()
            return {
                'sent_today': self._count,
                'daily_limit': self.daily_limit,
                'remaining': max(0, self.daily_limit - self._count),
                'usage_pct': round(self._count / self.daily_limit * 100, 1),
                'date': str(self._date),
                'unique_recipients': len(self._sent_hashes),
            }


# ============================================================
# MAIN EMAIL SENDER ENGINE
# ============================================================

class EmailSender:
    """
    PRISM v0.1 — Brevo Email Sending Engine (Singleton).

    Provides email sending via Brevo's free tier REST API with
    quota tracking, deduplication, template rendering, and
    webhook-based engagement tracking.

    Usage:
        sender = get_email_sender()
        result = await sender.send_email(message)
        result = await sender.send_alumni_outreach(recipient, personalization)
        stats = sender.get_health()
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Load config
        try:
            from core.config import get_config
            config = get_config()
            self._api_key = config.brevo.api_key
            self._sender_email = config.brevo.sender_email
            self._sender_name = config.brevo.sender_name
            self._daily_limit = config.brevo.daily_limit
            self._track_opens = config.brevo.track_opens
            self._track_clicks = config.brevo.track_clicks
            self._followup_wait_days = config.brevo.followup_wait_days
            self._max_followups = config.brevo.max_followups_per_contact
        except Exception as e:
            logger.warning(f"[EMAIL] Config fallback: {e}")
            self._api_key = os.getenv('BREVO_API_KEY', '')
            self._sender_email = os.getenv('BREVO_SENDER_EMAIL', '')
            self._sender_name = 'Abuzar Khan'
            self._daily_limit = 300
            self._track_opens = True
            self._track_clicks = True
            self._followup_wait_days = 7
            self._max_followups = 2

        # Quota tracker
        self._quota = DailyQuotaTracker(daily_limit=self._daily_limit)

        # Stats
        self._total_sent = 0
        self._total_failed = 0
        self._total_opened = 0
        self._total_clicked = 0
        self._total_bounced = 0

        # Engagement tracking (message_id -> events)
        self._engagement: Dict[str, List[WebhookEvent]] = defaultdict(list)
        self._engagement_lock = threading.Lock()

        # Contact history (email -> list of sent email types + dates)
        self._contact_history: Dict[str, List[Dict]] = defaultdict(list)

        self._configured = bool(self._api_key and self._sender_email)

        if self._configured:
            logger.info(
                f"[EMAIL] Brevo sender initialized "
                f"(sender={self._sender_email}, limit={self._daily_limit}/day)"
            )
        else:
            logger.warning(
                "[EMAIL] Brevo NOT configured (set BREVO_API_KEY + BREVO_SENDER_EMAIL)"
            )

    @property
    def is_configured(self) -> bool:
        """Check if Brevo is properly configured."""
        return self._configured

    # ----------------------------------------------------------
    # CORE SEND METHOD
    # ----------------------------------------------------------

    async def send_email(self, message: EmailMessage) -> EmailResult:
        """
        Send a single email via Brevo REST API.

        Args:
            message: Complete EmailMessage to send

        Returns:
            EmailResult with success/failure status
        """
        # Pre-flight checks
        if not self._configured:
            return EmailResult(
                success=False,
                recipient_email=message.to.email,
                email_type=message.email_type.value,
                error="Brevo not configured (missing API key or sender email)",
                status=EmailStatus.FAILED,
            )

        if not self._quota.can_send():
            return EmailResult(
                success=False,
                recipient_email=message.to.email,
                email_type=message.email_type.value,
                error=f"Daily quota exhausted ({self._daily_limit}/day)",
                status=EmailStatus.BLOCKED,
            )

        if self._quota.already_sent(message.to.email, message.email_type.value):
            return EmailResult(
                success=False,
                recipient_email=message.to.email,
                email_type=message.email_type.value,
                error="Already sent this email type to this recipient today",
                status=EmailStatus.BLOCKED,
            )

        # Validate
        if not message.to.email or '@' not in message.to.email:
            return EmailResult(
                success=False,
                recipient_email=message.to.email,
                email_type=message.email_type.value,
                error="Invalid recipient email address",
                status=EmailStatus.FAILED,
            )

        # Build Brevo API payload
        payload = {
            'sender': {
                'name': self._sender_name,
                'email': self._sender_email,
            },
            'to': [{
                'email': message.to.email,
                'name': message.to.name or message.to.email.split('@')[0],
            }],
            'subject': message.subject[:MAX_SUBJECT_LENGTH],
            'htmlContent': message.html_body[:MAX_BODY_LENGTH],
        }

        if message.text_body:
            payload['textContent'] = message.text_body[:MAX_BODY_LENGTH]

        if message.reply_to_email:
            payload['replyTo'] = {
                'email': message.reply_to_email,
                'name': message.reply_to_name or self._sender_name,
            }

        if message.tags:
            payload['tags'] = message.tags[:5]  # Brevo max 5 tags

        # Headers for tracking
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'api-key': self._api_key,
        }

        # Send with retries
        start_time = time.time()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                import aiohttp
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        BREVO_SEND_ENDPOINT,
                        json=payload,
                        headers=headers,
                    ) as resp:
                        latency_ms = (time.time() - start_time) * 1000
                        response_data = await resp.json()

                        if resp.status in (200, 201, 202):
                            message_id = response_data.get('messageId', '')

                            # Record success
                            self._quota.record_send(
                                message.to.email, message.email_type.value
                            )
                            self._total_sent += 1

                            # Record in contact history
                            self._contact_history[message.to.email].append({
                                'type': message.email_type.value,
                                'date': datetime.now(timezone.utc).isoformat(),
                                'message_id': message_id,
                                'company': message.company_name,
                            })

                            logger.info(
                                f"[EMAIL] Sent {message.email_type.value} to "
                                f"{message.to.email} (msgId={message_id}, "
                                f"{latency_ms:.0f}ms)"
                            )

                            return EmailResult(
                                success=True,
                                message_id=message_id,
                                recipient_email=message.to.email,
                                email_type=message.email_type.value,
                                status=EmailStatus.SENT,
                                sent_at=datetime.now(timezone.utc).isoformat(),
                                latency_ms=round(latency_ms, 1),
                                retry_count=attempt,
                            )
                        else:
                            error_msg = response_data.get(
                                'message',
                                f"HTTP {resp.status}"
                            )
                            last_error = error_msg
                            logger.warning(
                                f"[EMAIL] Send failed (attempt {attempt + 1}): "
                                f"{error_msg}"
                            )

            except asyncio.TimeoutError:
                last_error = "Request timed out (30s)"
                logger.warning(f"[EMAIL] Timeout (attempt {attempt + 1})")
            except ImportError:
                last_error = "aiohttp not installed"
                break
            except Exception as e:
                last_error = str(e)
                logger.error(f"[EMAIL] Send error (attempt {attempt + 1}): {e}")

            # Exponential backoff
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                await asyncio.sleep(delay)

        # All retries failed
        self._total_failed += 1
        return EmailResult(
            success=False,
            recipient_email=message.to.email,
            email_type=message.email_type.value,
            error=last_error or "All retries exhausted",
            status=EmailStatus.FAILED,
            latency_ms=round((time.time() - start_time) * 1000, 1),
            retry_count=MAX_RETRIES,
        )

    # ----------------------------------------------------------
    # CONVENIENCE METHODS
    # ----------------------------------------------------------

    async def send_alumni_outreach(
        self,
        recipient: EmailRecipient,
        personalization: Dict[str, str],
        listing_id: Optional[int] = None,
    ) -> EmailResult:
        """
        Send an alumni warm intro email.

        Args:
            recipient: Alumni contact details
            personalization: Dict with keys matching template variables
            listing_id: Optional linked job listing

        Returns:
            EmailResult
        """
        template = EMAIL_TEMPLATES['alumni_warm']

        # Fill template
        subject = template['subject']
        html_body = template['html']
        text_body = template['text']

        # Default personalization values
        defaults = {
            'recipient_name': recipient.name or 'there',
            'candidate_name': self._sender_name,
            'college': 'AMU',
            'year': '2025',
            'specialization': 'Marketing & Strategy',
            'company': recipient.company,
            'target_domain': 'marketing and strategy',
            'connection_hook': f'Fellow {personalization.get("college", "AMU")} Alumni',
            'personalization_paragraph': '',
            'company_hook': '',
            'closing_hook': 'Looking forward to hearing from you.',
            'candidate_phone': '',
            'candidate_linkedin': '',
        }
        defaults.update(personalization)

        for key, value in defaults.items():
            subject = subject.replace('{' + key + '}', str(value))
            html_body = html_body.replace('{' + key + '}', str(value))
            text_body = text_body.replace('{' + key + '}', str(value))

        message = EmailMessage(
            to=recipient,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            email_type=EmailType.ALUMNI_WARM,
            priority=EmailPriority.CRITICAL,
            listing_id=listing_id,
            company_name=recipient.company,
            tags=['alumni', 'outreach', recipient.company.lower().replace(' ', '_')[:20]],
        )

        return await self.send_email(message)

    async def send_hr_outreach(
        self,
        recipient: EmailRecipient,
        personalization: Dict[str, str],
        listing_id: Optional[int] = None,
        attach_cv: bool = True,
    ) -> EmailResult:
        """
        Send an HR cold outreach email.

        Args:
            recipient: HR/recruiter contact
            personalization: Template variables
            listing_id: Linked listing
            attach_cv: Whether to attach CV

        Returns:
            EmailResult
        """
        template = EMAIL_TEMPLATES['hr_cold']

        subject = template['subject']
        html_body = template['html']
        text_body = template['text']

        defaults = {
            'recipient_name': recipient.name or 'Hiring Manager',
            'candidate_name': self._sender_name,
            'college': 'AMU',
            'year': '2025',
            'company': recipient.company,
            'target_domain': 'marketing and strategy',
            'target_role': 'MBA Intern',
            'company_specific_paragraph': '',
            'experience_summary': 'business development and analytics',
            'skills_bullets': '<li>Data-driven decision making</li><li>Strategic thinking</li>',
            'skills_text': '- Data-driven decision making\n- Strategic thinking',
            'value_proposition': '',
            'department': personalization.get('target_domain', 'marketing'),
            'candidate_phone': '',
            'candidate_linkedin': '',
        }
        defaults.update(personalization)

        for key, value in defaults.items():
            subject = subject.replace('{' + key + '}', str(value))
            html_body = html_body.replace('{' + key + '}', str(value))
            text_body = text_body.replace('{' + key + '}', str(value))

        message = EmailMessage(
            to=recipient,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            email_type=EmailType.HR_COLD,
            priority=EmailPriority.HIGH,
            listing_id=listing_id,
            company_name=recipient.company,
            tags=['hr', 'cold_outreach', recipient.company.lower().replace(' ', '_')[:20]],
        )

        return await self.send_email(message)

    async def send_followup(
        self,
        recipient: EmailRecipient,
        original_subject: str,
        personalization: Dict[str, str],
    ) -> EmailResult:
        """
        Send a follow-up email for a silent application.

        Args:
            recipient: Original contact
            original_subject: Subject of the original email
            personalization: Additional personalization

        Returns:
            EmailResult
        """
        # Check if we've exceeded max follow-ups
        history = self._contact_history.get(recipient.email, [])
        followup_count = sum(
            1 for h in history if h['type'] == EmailType.FOLLOWUP.value
        )
        if followup_count >= self._max_followups:
            return EmailResult(
                success=False,
                recipient_email=recipient.email,
                email_type=EmailType.FOLLOWUP.value,
                error=f"Max follow-ups ({self._max_followups}) reached",
                status=EmailStatus.BLOCKED,
            )

        template = EMAIL_TEMPLATES['followup']

        subject = template['subject']
        html_body = template['html']
        text_body = template['text']

        defaults = {
            'recipient_name': recipient.name or 'there',
            'candidate_name': self._sender_name,
            'college': 'AMU',
            'year': '2025',
            'company': recipient.company,
            'original_subject': original_subject,
            'followup_hook': '',
        }
        defaults.update(personalization)

        for key, value in defaults.items():
            subject = subject.replace('{' + key + '}', str(value))
            html_body = html_body.replace('{' + key + '}', str(value))
            text_body = text_body.replace('{' + key + '}', str(value))

        message = EmailMessage(
            to=recipient,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            email_type=EmailType.FOLLOWUP,
            priority=EmailPriority.LOW,
            company_name=recipient.company,
            tags=['followup', recipient.company.lower().replace(' ', '_')[:20]],
        )

        return await self.send_email(message)

    # ----------------------------------------------------------
    # WEBHOOK HANDLER
    # ----------------------------------------------------------

    def handle_webhook(self, event_data: Dict[str, Any]) -> Optional[WebhookEvent]:
        """
        Process a Brevo webhook event for engagement tracking.

        Args:
            event_data: Raw webhook payload from Brevo

        Returns:
            Parsed WebhookEvent or None
        """
        try:
            event = WebhookEvent(
                event_type=event_data.get('event', ''),
                email=event_data.get('email', ''),
                message_id=event_data.get('message-id', ''),
                timestamp=event_data.get('date', ''),
                ip=event_data.get('ip', ''),
                link=event_data.get('link', ''),
                reason=event_data.get('reason', ''),
            )

            # Update tracking stats
            with self._engagement_lock:
                self._engagement[event.message_id].append(event)

            if event.event_type == 'opened':
                self._total_opened += 1
            elif event.event_type == 'click':
                self._total_clicked += 1
            elif event.event_type in ('hard_bounce', 'soft_bounce', 'blocked'):
                self._total_bounced += 1

            logger.info(
                f"[EMAIL] Webhook: {event.event_type} for {event.email} "
                f"(msgId={event.message_id})"
            )

            return event

        except Exception as e:
            logger.error(f"[EMAIL] Webhook parse error: {e}")
            return None

    def get_engagement_for_contact(
        self,
        email: str,
    ) -> Dict[str, Any]:
        """Get engagement history for a specific contact."""
        history = self._contact_history.get(email, [])
        events = []
        for h in history:
            msg_id = h.get('message_id', '')
            msg_events = self._engagement.get(msg_id, [])
            events.extend([{
                'type': e.event_type,
                'timestamp': e.timestamp,
            } for e in msg_events])

        return {
            'email': email,
            'total_emails_sent': len(history),
            'email_types': [h['type'] for h in history],
            'engagement_events': events,
            'has_opened': any(e['type'] == 'opened' for e in events),
            'has_clicked': any(e['type'] == 'click' for e in events),
        }

    # ----------------------------------------------------------
    # BATCH OPERATIONS
    # ----------------------------------------------------------

    async def send_batch(
        self,
        messages: List[EmailMessage],
        delay_between_seconds: float = 2.0,
    ) -> List[EmailResult]:
        """
        Send a batch of emails with delays between sends.

        Args:
            messages: List of emails to send
            delay_between_seconds: Delay between sends (human mimicry)

        Returns:
            List of EmailResults
        """
        results = []
        # Sort by priority
        sorted_msgs = sorted(messages, key=lambda m: m.priority.value)

        for i, msg in enumerate(sorted_msgs):
            if not self._quota.can_send():
                results.append(EmailResult(
                    success=False,
                    recipient_email=msg.to.email,
                    email_type=msg.email_type.value,
                    error="Daily quota exhausted",
                    status=EmailStatus.BLOCKED,
                ))
                continue

            result = await self.send_email(msg)
            results.append(result)

            # Delay between sends
            if i < len(sorted_msgs) - 1 and result.success:
                await asyncio.sleep(delay_between_seconds)

        sent = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        logger.info(
            f"[EMAIL] Batch complete: {sent} sent, {failed} failed "
            f"(quota remaining: {self._quota.remaining()})"
        )

        return results

    # ----------------------------------------------------------
    # HEALTH & MONITORING
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get email sender health and statistics."""
        return {
            'configured': self._configured,
            'sender': self._sender_email if self._configured else 'NOT SET',
            'quota': self._quota.get_stats(),
            'total_sent': self._total_sent,
            'total_failed': self._total_failed,
            'total_opened': self._total_opened,
            'total_clicked': self._total_clicked,
            'total_bounced': self._total_bounced,
            'open_rate': (
                round(self._total_opened / self._total_sent * 100, 1)
                if self._total_sent > 0 else 0
            ),
            'click_rate': (
                round(self._total_clicked / self._total_sent * 100, 1)
                if self._total_sent > 0 else 0
            ),
            'unique_contacts': len(self._contact_history),
            'tracked_messages': len(self._engagement),
        }

    def get_quota_report(self) -> str:
        """Generate a human-readable quota report for Telegram."""
        stats = self._quota.get_stats()
        health = self.get_health()

        return (
            f"📧 <b>Email Engine Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{'✅' if self._configured else '❌'} Configured: {self._configured}\n"
            f"📤 Sent today: {stats['sent_today']}/{stats['daily_limit']} "
            f"({stats['usage_pct']}%)\n"
            f"📬 Remaining: {stats['remaining']}\n"
            f"👥 Unique contacts: {health['unique_contacts']}\n"
            f"📖 Open rate: {health['open_rate']}%\n"
            f"🔗 Click rate: {health['click_rate']}%\n"
            f"🔴 Bounces: {health['total_bounced']}\n"
        )


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_sender_instance: Optional[EmailSender] = None
_sender_lock = threading.Lock()


def get_email_sender() -> EmailSender:
    """Get the singleton EmailSender instance."""
    global _sender_instance
    if _sender_instance is None:
        with _sender_lock:
            if _sender_instance is None:
                _sender_instance = EmailSender()
    return _sender_instance


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PRISM v0.1 — Email Sender Engine Test")
    print("=" * 60)

    sender = get_email_sender()
    health = sender.get_health()

    print(f"\nConfiguration:")
    print(f"  Configured: {health['configured']}")
    print(f"  Sender: {health['sender']}")
    print(f"\nQuota:")
    for k, v in health['quota'].items():
        print(f"  {k}: {v}")

    print(f"\nStats:")
    print(f"  Total sent: {health['total_sent']}")
    print(f"  Open rate: {health['open_rate']}%")

    print(f"\nTemplates available: {list(EMAIL_TEMPLATES.keys())}")
    print(f"Email types: {[e.value for e in EmailType]}")

    print("\n" + sender.get_quota_report())
    print("=" * 60)
