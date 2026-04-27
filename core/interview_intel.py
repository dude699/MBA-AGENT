"""
NEXUS v0.2 — Layer 8: Interview Intelligence System
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

The moment an application converts to an interview request, NEXUS shifts modes.
Within 90 seconds of signal detection, a complete briefing package lands in
Telegram so Abuzar walks into every conversation prepped.

Signal sources
--------------
  • Gmail API           — keyword + applied-company watch
  • LinkedIn            — Camoufox background session for "Your application
                          was viewed" + "Recruiter sent you a message"
  • WhatsApp Web (NEW)  — Camoufox session for company-name mentions
  • Subject-line NLP    — Cerebras classifies subjects only (privacy-preserving)

Auto-briefing package (delivered to Telegram, target ≤ 90s)
-----------------------------------------------------------
  1. Company snapshot      — Crawl4AI of website + Crunchbase
  2. Recent news (3 items) — Crawl4AI + DuckDuckGo RSS
  3. Glassdoor interview intel
  4. 8 likely questions    — Cerebras, JD + company stage + profile
  5. Your own application  — exactly what you submitted (from Supabase)
  6. Suggested reply draft — for one-tap Telegram approve
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from core.crawl4ai_discovery import Crawl4AIDiscovery
from core.nexus_config import (
    INTERVIEW_INTEL,
    STACK,
    USER_HANDLE,
)

log = logging.getLogger("nexus.interview_intel")


# ────────────────────────────────────────────────────────────────────────────
# Signal taxonomy (matches DB constraint set)
# ────────────────────────────────────────────────────────────────────────────
class SignalType(str, Enum):
    INTERVIEW_INVITE = "INTERVIEW_INVITE"
    REJECTION        = "REJECTION"
    TEST_LINK        = "TEST_LINK"
    OFFER            = "OFFER"
    GENERIC          = "GENERIC"


class SignalSource(str, Enum):
    GMAIL    = "gmail"
    LINKEDIN = "linkedin"
    WHATSAPP = "whatsapp"


# ────────────────────────────────────────────────────────────────────────────
# Data
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class InterviewSignal:
    company:     str
    role:        str | None
    source:      SignalSource
    signal_type: SignalType
    raw_subject: str | None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload:     dict[str, Any] = field(default_factory=dict)


@dataclass
class BriefingPackage:
    id:                str
    company:           str
    role:              str | None
    snapshot:          str
    recent_news:       list[dict[str, str]]      # [{title, url, summary}]
    glassdoor_intel:   str | None
    likely_questions:  list[str]
    your_application:  dict | None               # what was actually submitted
    draft_reply:       str | None
    application_id:    int | None = None
    duration_ms:       int = 0
    created_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ────────────────────────────────────────────────────────────────────────────
# Subject-line classifier (privacy-preserving — uses subject only, never body)
# ────────────────────────────────────────────────────────────────────────────
_INVITE_KEYWORDS    = ("interview", "shortlisted", "next round", "schedule a call",
                       "screening", "discussion", "chat with our team")
_REJECT_KEYWORDS    = ("regret", "unsuccessful", "not moving forward", "not selected",
                       "decided to proceed with other")
_TEST_KEYWORDS      = ("assessment", "online test", "coding challenge", "case study",
                       "hackerrank", "hackerearth", "mettl")
_OFFER_KEYWORDS     = ("offer", "congratulations", "joining", "ctc", "package")


def classify_subject(subject: str) -> SignalType:
    s = (subject or "").lower()
    if not s:
        return SignalType.GENERIC
    if any(k in s for k in _OFFER_KEYWORDS):
        return SignalType.OFFER
    if any(k in s for k in _INVITE_KEYWORDS):
        return SignalType.INTERVIEW_INVITE
    if any(k in s for k in _TEST_KEYWORDS):
        return SignalType.TEST_LINK
    if any(k in s for k in _REJECT_KEYWORDS):
        return SignalType.REJECTION
    return SignalType.GENERIC


# ────────────────────────────────────────────────────────────────────────────
# Watcher protocols (concrete glue lives on the worker dyno)
# ────────────────────────────────────────────────────────────────────────────
class GmailWatcher:
    async def poll(self, applied_companies: set[str]) -> list[InterviewSignal]:
        """Return new INTERVIEW_INVITE/REJECTION/TEST_LINK signals since last poll."""
        return []


class LinkedInWatcher:
    async def poll(self) -> list[InterviewSignal]:
        """Camoufox background session — 'application viewed' + DM events."""
        return []


class WhatsAppWatcher:
    async def poll(self, applied_companies: set[str]) -> list[InterviewSignal]:
        """Camoufox WhatsApp Web session — company-name mentions."""
        return []


# ────────────────────────────────────────────────────────────────────────────
# Briefing builder — runs Crawl4AI in parallel, target wall-clock 90 s
# ────────────────────────────────────────────────────────────────────────────
class BriefingBuilder:
    """
    Required `db` methods:
        async def fetch_application_for(company, role) -> dict | None
        async def cache_briefing(pkg: BriefingPackage) -> None
    """

    def __init__(
        self,
        db,
        crawler: Crawl4AIDiscovery | None = None,
        cerebras_call: Callable[[str, str], Awaitable[str]] | None = None,
    ):
        self.db            = db
        self.crawler       = crawler or Crawl4AIDiscovery()
        self.cerebras_call = cerebras_call or _default_cerebras_call

    async def build(self, signal: InterviewSignal, profile: dict) -> BriefingPackage:
        t0 = time.monotonic()
        deadline = t0 + INTERVIEW_INTEL["briefing_target_seconds"]

        async def _bounded(coro, fallback):
            try:
                remaining = max(1.0, deadline - time.monotonic())
                return await asyncio.wait_for(coro, timeout=remaining)
            except (asyncio.TimeoutError, Exception) as e:               # noqa: BLE001
                log.debug("briefing.section_timeout/err err=%s", e)
                return fallback

        # Run all Crawl4AI fetches + Cerebras generations in parallel
        snapshot, news, glassdoor, application = await asyncio.gather(
            _bounded(self._company_snapshot(signal.company),      ""),
            _bounded(self._recent_news(signal.company),           []),
            _bounded(self._glassdoor_intel(signal.company),       None),
            _bounded(self._fetch_application(signal),             None),
            return_exceptions=False,
        )

        likely_questions = await _bounded(
            self._likely_questions(signal, profile, snapshot),
            [],
        )

        draft_reply = None
        if signal.signal_type == SignalType.INTERVIEW_INVITE:
            draft_reply = await _bounded(
                self._draft_reply(signal, profile),
                None,
            )

        pkg = BriefingPackage(
            id                = uuid.uuid4().hex[:12],
            company           = signal.company,
            role              = signal.role,
            snapshot          = snapshot,
            recent_news       = news,
            glassdoor_intel   = glassdoor,
            likely_questions  = likely_questions,
            your_application  = application,
            draft_reply       = draft_reply,
            application_id    = (application or {}).get("id") if application else None,
            duration_ms       = int((time.monotonic() - t0) * 1000),
        )
        try:
            await self.db.cache_briefing(pkg)
        except Exception as e:                                          # noqa: BLE001
            log.warning("briefing.cache_fail err=%s", e)

        log.info(
            "briefing.done company=%s ms=%s news=%s questions=%s reply=%s",
            signal.company, pkg.duration_ms, len(news),
            len(likely_questions), bool(draft_reply),
        )
        return pkg

    # ---- sections ---------------------------------------------------------
    async def _company_snapshot(self, company: str) -> str:
        """Quick Crawl4AI of the company's homepage → 1-paragraph summary."""
        try:
            from core.crawl4ai_discovery import CRAWL4AI_AVAILABLE, build_default_crawler
        except Exception:                                               # noqa: BLE001
            return ""
        if not CRAWL4AI_AVAILABLE:
            return ""
        # Best-effort homepage URL
        guess_urls = [
            f"https://www.{company.lower().replace(' ', '')}.com/about",
            f"https://www.{company.lower().replace(' ', '')}.com",
        ]
        crawler = build_default_crawler()
        try:
            for url in guess_urls:
                try:
                    res = await crawler.arun(url=url)                   # type: ignore[attr-defined]
                    md  = (getattr(res, "markdown", "") or "")[:1500]
                    if md:
                        return md
                except Exception:
                    continue
        finally:
            try:
                await crawler.close()                                   # type: ignore[attr-defined]
            except Exception:
                pass
        return ""

    async def _recent_news(self, company: str) -> list[dict[str, str]]:
        """DuckDuckGo RSS feed for `<company> news` — top 3 items."""
        try:
            import aiohttp                                              # type: ignore
            import feedparser                                           # type: ignore
        except Exception:                                               # noqa: BLE001
            return []
        url = f"https://duckduckgo.com/?q={company.replace(' ', '+')}+news&format=rss"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=15) as r:
                    body = await r.text()
            feed = feedparser.parse(body)
            return [
                {
                    "title":   getattr(e, "title", "")[:200],
                    "url":     getattr(e, "link", ""),
                    "summary": (getattr(e, "summary", "") or "")[:300],
                }
                for e in feed.entries[:3]
            ]
        except Exception as e:                                          # noqa: BLE001
            log.debug("briefing.news_err company=%s err=%s", company, e)
            return []

    async def _glassdoor_intel(self, company: str) -> str | None:
        """Crawl4AI of Glassdoor 'Interviews' section (best-effort)."""
        try:
            from core.crawl4ai_discovery import CRAWL4AI_AVAILABLE, build_default_crawler
        except Exception:                                               # noqa: BLE001
            return None
        if not CRAWL4AI_AVAILABLE:
            return None
        slug = company.lower().replace(" ", "-")
        url = f"https://www.glassdoor.co.in/Interview/{slug}-Interview-Questions.htm"
        crawler = build_default_crawler()
        try:
            res = await crawler.arun(url=url)                           # type: ignore[attr-defined]
            md  = (getattr(res, "markdown", "") or "")[:2000]
            return md or None
        except Exception:
            return None
        finally:
            try:
                await crawler.close()                                   # type: ignore[attr-defined]
            except Exception:
                pass

    async def _likely_questions(
        self, signal: InterviewSignal, profile: dict, snapshot: str,
    ) -> list[str]:
        n = INTERVIEW_INTEL["likely_questions_count"]
        system = (
            "You are an interview prep assistant. Given a candidate profile, "
            "company snapshot, and target role, output the most likely "
            f"{n} interview questions, ONE PER LINE, no numbering, no extra "
            "commentary. Mix behavioural, technical, and case-style as fits the role."
        )
        user = (
            f"Company: {signal.company}\n"
            f"Role: {signal.role or '(unknown)'}\n"
            f"Company snapshot:\n{snapshot[:800]}\n\n"
            f"Candidate profile (summary): {profile.get('summary', '')[:600]}"
        )
        try:
            text = await self.cerebras_call(system, user)
            qs = [q.strip(" -•\t") for q in text.splitlines() if q.strip()]
            return qs[:n]
        except Exception as e:                                          # noqa: BLE001
            log.warning("briefing.qgen_fail err=%s", e)
            return []

    async def _draft_reply(self, signal: InterviewSignal, profile: dict) -> str | None:
        system = (
            "You are MD Abuzar Salim drafting a polite, concise email confirming "
            "availability for an interview. 60-90 words. No emojis. Polite, "
            "professional, lightly enthusiastic. Sign off with name only."
        )
        user = (
            f"You received an interview invite from {signal.company} "
            f"for the role: {signal.role or '(unspecified)'}.\n"
            f"Subject of their email: {signal.raw_subject or '(unknown)'}\n"
            "Confirm availability for the next 5 business days, suggest two "
            "1-hour windows in IST: morning (10–11 AM) and afternoon (3–4 PM). "
            "Ask if they prefer Google Meet or Zoom. Keep it human."
        )
        try:
            return await self.cerebras_call(system, user)
        except Exception as e:                                          # noqa: BLE001
            log.warning("briefing.reply_fail err=%s", e)
            return None

    async def _fetch_application(self, signal: InterviewSignal) -> dict | None:
        try:
            return await self.db.fetch_application_for(signal.company, signal.role)
        except Exception as e:                                          # noqa: BLE001
            log.debug("briefing.app_fetch_err err=%s", e)
            return None


# ────────────────────────────────────────────────────────────────────────────
# Default Cerebras call wrapper (reused by Layer 8 + Innovations)
# ────────────────────────────────────────────────────────────────────────────
async def _default_cerebras_call(system: str, user: str) -> str:
    try:
        from cerebras.cloud.sdk import AsyncCerebras                    # type: ignore
    except Exception:                                                   # noqa: BLE001
        return ""
    import os
    client = AsyncCerebras(api_key=os.getenv("CEREBRAS_API_KEY", ""))
    try:
        resp = await client.chat.completions.create(
            model=STACK.cerebras_llm,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()                  # type: ignore[attr-defined]
    except Exception as e:                                              # noqa: BLE001
        log.warning("interview.cerebras_err err=%s", e)
        return ""


# ────────────────────────────────────────────────────────────────────────────
# InterviewIntel — orchestrates watchers + briefing dispatch
# ────────────────────────────────────────────────────────────────────────────
class InterviewIntel:
    """
    Tick loop:
        1. Pull applied companies set from DB.
        2. Poll each watcher in parallel.
        3. For each new signal: persist → if INTERVIEW_INVITE/TEST_LINK/OFFER,
           build briefing → dispatch to Telegram.
        4. Innovation 12: applied-but-not-viewed follow-up sweep
           (apps without recruiter_viewed older than 14 days).
    """

    def __init__(
        self,
        db,
        builder:           BriefingBuilder,
        gmail_watcher:     GmailWatcher    | None = None,
        linkedin_watcher:  LinkedInWatcher | None = None,
        whatsapp_watcher:  WhatsAppWatcher | None = None,
        on_briefing:       Callable[[BriefingPackage], Awaitable[None]] | None = None,
        on_followup_needed: Callable[[dict], Awaitable[None]]            | None = None,
        profile:           dict | None = None,
    ):
        self.db                  = db
        self.builder             = builder
        self.gmail_watcher       = gmail_watcher    or GmailWatcher()
        self.linkedin_watcher    = linkedin_watcher or LinkedInWatcher()
        self.whatsapp_watcher    = whatsapp_watcher or WhatsAppWatcher()
        self.on_briefing         = on_briefing or (lambda *_: asyncio.sleep(0))
        self.on_followup_needed  = on_followup_needed or (lambda *_: asyncio.sleep(0))
        self.profile             = profile or {}

    async def tick(self) -> dict[str, int]:
        applied_set = set(await self.db.applied_companies(USER_HANDLE))
        gmail, ln, wa = await asyncio.gather(
            self.gmail_watcher.poll(applied_set),
            self.linkedin_watcher.poll(),
            self.whatsapp_watcher.poll(applied_set),
            return_exceptions=False,
        )
        new_signals: list[InterviewSignal] = []
        for batch in (gmail, ln, wa):
            new_signals.extend(batch or [])

        briefings = 0
        for sig in new_signals:
            try:
                await self.db.persist_interview_signal(sig)
                if sig.signal_type in (
                    SignalType.INTERVIEW_INVITE,
                    SignalType.TEST_LINK,
                    SignalType.OFFER,
                ):
                    pkg = await self.builder.build(sig, self.profile)
                    await self.on_briefing(pkg)
                    briefings += 1
            except Exception as e:                                      # noqa: BLE001
                log.exception("interview.tick_err sig=%s err=%s", sig, e)

        # Innovation 12 — applied-but-not-viewed sweep
        followups = 0
        try:
            stale = await self.db.applied_not_viewed_older_than_days(
                INTERVIEW_INTEL["follow_up_unviewed_days"]
            )
            for app in stale:
                await self.on_followup_needed(app)
                followups += 1
        except Exception as e:                                          # noqa: BLE001
            log.debug("interview.followup_err err=%s", e)

        log.info("interview.tick signals=%s briefings=%s followups=%s",
                 len(new_signals), briefings, followups)
        return {
            "signals":   len(new_signals),
            "briefings": briefings,
            "followups": followups,
        }


__all__ = [
    "SignalType",
    "SignalSource",
    "InterviewSignal",
    "BriefingPackage",
    "BriefingBuilder",
    "InterviewIntel",
    "GmailWatcher",
    "LinkedInWatcher",
    "WhatsAppWatcher",
    "classify_subject",
]
