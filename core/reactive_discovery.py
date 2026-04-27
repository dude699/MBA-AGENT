"""
NEXUS v0.2 — Layer 2b: Reactive Discovery (Event-Driven, Not Just Cron)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

The cron problem
----------------
A job posted at 9:01 AM is not discovered by cron-based scrapers until ~11:00 AM.
Competitors who get there first win the recruiter's attention. NEXUS v0.2 closes
this gap with a reactive layer.

Reactive sources
----------------
  • LinkedIn     — RSS subscription on company pages + job-alert feeds (free, no API).
  • Internshala  — public RSS, refreshed every ~15 minutes.
  • Naukri       — Camoufox background watcher session that polls the recommended-
                   jobs page and emits new items as soon as they appear.
  • Webhooks     — public Render endpoint that any external trigger can POST to.

Outcome: application lands within 5–15 minutes of posting — before 99% of
competitors. Other portals stay on enhanced cron with a 2-hour ceiling.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from core.crawl4ai_discovery import (
    Crawl4AIDiscovery,
    NormalisedJob,
)
from core.nexus_config import (
    REACTIVE_SOURCES,
    SUPPORTED_PORTALS,
    portal_supported,
)

log = logging.getLogger("nexus.reactive")


# ─── Optional deps ───────────────────────────────────────────────────────
try:
    import aiohttp                                                   # type: ignore
    AIOHTTP_AVAILABLE = True
except Exception:                                                    # noqa: BLE001
    aiohttp = None                                                   # type: ignore
    AIOHTTP_AVAILABLE = False

try:
    import feedparser                                                # type: ignore
    FEEDPARSER_AVAILABLE = True
except Exception:                                                    # noqa: BLE001
    feedparser = None                                                # type: ignore
    FEEDPARSER_AVAILABLE = False


# ────────────────────────────────────────────────────────────────────────────
# Public types
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class ReactiveSignal:
    portal:    str
    raw_url:   str
    title:     str | None
    company:   str | None
    received_at: datetime
    source:    str                # rss | webhook | browser_watch
    payload:   dict


# Callback signature: receives the freshly-discovered NormalisedJob list.
# In production this is wired to the orchestrator's "ingest_jobs" coroutine.
JobSink = Callable[[list[NormalisedJob]], Awaitable[None]]


# ────────────────────────────────────────────────────────────────────────────
# In-memory dedup ring buffer — keeps last 4096 url hashes per portal so a
# noisy RSS feed re-publishing the same item doesn't spam the orchestrator.
# Real persistent dedup happens in Layer 7 (semantic).
# ────────────────────────────────────────────────────────────────────────────
class _SeenRing:
    def __init__(self, capacity: int = 4096):
        self.capacity = capacity
        self._buf: dict[str, list[str]] = {}

    @staticmethod
    def _h(url: str) -> str:
        return hashlib.sha1(url.encode()).hexdigest()[:16]

    def has(self, portal: str, url: str) -> bool:
        return self._h(url) in self._buf.get(portal, [])

    def add(self, portal: str, url: str) -> None:
        ring = self._buf.setdefault(portal, [])
        ring.append(self._h(url))
        if len(ring) > self.capacity:
            del ring[: len(ring) - self.capacity]


# ────────────────────────────────────────────────────────────────────────────
# Reactive Discovery — main facade
# ────────────────────────────────────────────────────────────────────────────
class ReactiveDiscovery:
    """
    Owns one task per reactive source and a single shared Crawl4AIDiscovery
    instance for "drill-down" (when an RSS item arrives, we Crawl4AI the
    detail page to enrich it into a full NormalisedJob).
    """

    def __init__(
        self,
        sink:        JobSink,
        crawler:     Crawl4AIDiscovery | None = None,
        poll_seconds: int = 300,                # default RSS poll cadence
    ):
        self.sink         = sink
        self.crawler      = crawler or Crawl4AIDiscovery()
        self.poll_seconds = poll_seconds
        self._seen        = _SeenRing()
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    # ---- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        for portal, spec in REACTIVE_SOURCES.items():
            mode = spec.get("mode")
            if mode == "rss":
                self._tasks.append(asyncio.create_task(
                    self._rss_loop(portal, spec["url_template"]),
                    name=f"rx_rss_{portal}",
                ))
            elif mode == "browser_watch":
                self._tasks.append(asyncio.create_task(
                    self._browser_watch_loop(portal, spec["url_template"]),
                    name=f"rx_watch_{portal}",
                ))
        log.info("reactive.started tasks=%d", len(self._tasks))

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        log.info("reactive.stopped")

    # ---- public webhook ingest --------------------------------------------
    async def ingest_webhook(self, portal: str, payload: dict) -> int:
        """
        Public POST endpoint handler — let any external service push a job
        signal. Returns count of jobs forwarded to the sink.
        """
        if not portal_supported(portal):
            log.warning("reactive.webhook_bad_portal portal=%s", portal)
            return 0

        signal = ReactiveSignal(
            portal=portal,
            raw_url=str(payload.get("url") or payload.get("raw_url") or ""),
            title=payload.get("title"),
            company=payload.get("company"),
            received_at=datetime.now(timezone.utc),
            source="webhook",
            payload=payload,
        )
        return await self._handle_signal(signal)

    # ---- RSS poll loop ----------------------------------------------------
    async def _rss_loop(self, portal: str, url_template: str) -> None:
        if not (AIOHTTP_AVAILABLE and FEEDPARSER_AVAILABLE):
            log.warning(
                "reactive.rss_unavailable portal=%s — aiohttp/feedparser missing",
                portal,
            )
            return

        feed_url = url_template.format(kw="mba+intern+india")
        log.info("reactive.rss_start portal=%s url=%s", portal, feed_url)
        backoff = self.poll_seconds

        while not self._stop.is_set():
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(feed_url, timeout=20) as r:
                        body = await r.text()
                feed = feedparser.parse(body)
                fresh = 0
                for entry in feed.entries:
                    url = getattr(entry, "link", None)
                    if not url or self._seen.has(portal, url):
                        continue
                    self._seen.add(portal, url)
                    sig = ReactiveSignal(
                        portal=portal,
                        raw_url=url,
                        title=getattr(entry, "title", None),
                        company=getattr(entry, "author", None),
                        received_at=datetime.now(timezone.utc),
                        source="rss",
                        payload={k: getattr(entry, k, None) for k in
                                 ("title", "link", "summary", "published")},
                    )
                    fresh += await self._handle_signal(sig)
                if fresh:
                    log.info("reactive.rss_fresh portal=%s n=%s", portal, fresh)
                backoff = self.poll_seconds
            except Exception as e:                                   # noqa: BLE001
                log.exception("reactive.rss_err portal=%s err=%s", portal, e)
                backoff = min(backoff * 2, 1800)                     # cap 30 min

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass

    # ---- browser-watch loop (Naukri etc.) ---------------------------------
    async def _browser_watch_loop(self, portal: str, watch_url: str) -> None:
        """
        Camoufox session sits on the page and looks for new cards every
        couple of minutes. The actual browser glue lives on the worker
        dyno; here we provide the loop scaffold.
        """
        log.info("reactive.watch_start portal=%s url=%s", portal, watch_url)
        # Conservative cadence to avoid Risk Governor signals
        cadence = max(self.poll_seconds, 120)

        # Worker-side: agents/n03_crawl4ai_scraper.py exposes
        #   await snapshot_page(portal, watch_url) -> list[dict]
        # This module imports lazily so the slim dyno does not pull
        # heavy deps at import time.
        try:
            from agents.n03_crawl4ai_scraper import snapshot_page    # type: ignore
        except Exception:                                            # noqa: BLE001
            log.warning("reactive.watch_unavailable portal=%s — agent N03 missing",
                        portal)
            return

        while not self._stop.is_set():
            try:
                snapshot = await snapshot_page(portal, watch_url)
                fresh = 0
                for raw in snapshot:
                    url = raw.get("raw_url") or raw.get("link") or ""
                    if not url or self._seen.has(portal, url):
                        continue
                    self._seen.add(portal, url)
                    sig = ReactiveSignal(
                        portal=portal,
                        raw_url=url,
                        title=raw.get("title"),
                        company=raw.get("company"),
                        received_at=datetime.now(timezone.utc),
                        source="browser_watch",
                        payload=raw,
                    )
                    fresh += await self._handle_signal(sig)
                if fresh:
                    log.info("reactive.watch_fresh portal=%s n=%s", portal, fresh)
            except Exception as e:                                   # noqa: BLE001
                log.exception("reactive.watch_err portal=%s err=%s", portal, e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=cadence)
            except asyncio.TimeoutError:
                pass

    # ---- enrich + ship ----------------------------------------------------
    async def _handle_signal(self, sig: ReactiveSignal) -> int:
        """
        Drill down into the detail page via Crawl4AI, materialise into a
        NormalisedJob with discovery_mode set, hand off to the sink.
        Returns 1 on success, 0 on failure (so caller can sum).
        """
        try:
            jobs = await self._enrich(sig)
            if jobs:
                await self.sink(jobs)
                return 1
        except Exception as e:                                       # noqa: BLE001
            log.exception("reactive.enrich_fail portal=%s url=%s err=%s",
                          sig.portal, sig.raw_url, e)
        return 0

    async def _enrich(self, sig: ReactiveSignal) -> list[NormalisedJob]:
        """
        Crawl4AI single-page LLM extraction on the detail URL — produces
        ONE NormalisedJob in the common case.  For RSS feeds that already
        carry rich item bodies we synthesise the job directly without
        another HTTP fetch.
        """
        # Fast path: RSS item with enough info → synthesise without re-fetch
        if sig.source == "rss" and sig.title and sig.company:
            return [
                NormalisedJob(
                    job_id              = NormalisedJob.make_id(
                        sig.portal, sig.raw_url, sig.title or sig.raw_url
                    ),
                    portal              = sig.portal,
                    company             = sig.company,
                    title               = sig.title,
                    location            = None,
                    remote              = False,
                    stipend_raw         = None,
                    stipend_inr_monthly = None,
                    deadline            = None,
                    posted_at           = sig.received_at,
                    discovered_at       = sig.received_at,
                    discovery_mode      = "reactive_rss",
                    jd_text             = (sig.payload.get("summary") or "")[:1000],
                    raw_url             = sig.raw_url,
                    raw_payload         = sig.payload,
                )
            ]

        # Slow path: drill down with Crawl4AI to the detail page.
        # We reuse the universal discovery facade by pointing it at a
        # single-URL CrawlerConfig.
        from core.crawl4ai_discovery import CrawlerConfig, DEFAULT_CRAWLERS
        cfg = CrawlerConfig(
            portal=sig.portal,
            list_url=sig.raw_url,
            max_pages=1,
            extract_hint=DEFAULT_CRAWLERS.get(
                sig.portal, CrawlerConfig(sig.portal, "")
            ).extract_hint,
        )
        # Temporarily swap the portal's recipe so .discover() hits the
        # detail URL (single page, max_pages=1).
        original = self.crawler.crawlers.get(sig.portal)
        self.crawler.crawlers[sig.portal] = cfg
        try:
            jobs = await self.crawler.discover(
                sig.portal,
                discovery_mode=(
                    "reactive_webhook" if sig.source == "webhook" else "reactive_rss"
                ),
            )
        finally:
            if original is not None:
                self.crawler.crawlers[sig.portal] = original
        return jobs


__all__ = [
    "ReactiveDiscovery",
    "ReactiveSignal",
    "JobSink",
]
