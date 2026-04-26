"""
NEXUS v0.2 — Agent N03 · Crawl4AI Scraper Agent
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

This agent is the worker-side runner for Layer 2.

Responsibilities
----------------
1. `scrape_portal(portal)` — full cron-mode discovery for one portal:
      → Crawl4AIDiscovery.discover() → [NormalisedJob, ...]
      → opens scrape_log row, persists jobs, closes scrape_log row.

2. `snapshot_page(portal, url)` — lightweight detail-page snapshot used by
   reactive_discovery's browser-watch loop (Naukri).  Returns raw dicts
   (not NormalisedJob) so the reactive layer can decide whether to ingest.

3. `scrape_all_portals()` — fan-out helper that scrapes every supported
   portal in sequence (sequential by default to respect Risk Governor caps).

The agent uses a single shared Crawl4AI browser context per scrape_portal()
call so it does not spin up Firefox 11 times.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from core.crawl4ai_discovery import (
    CRAWL4AI_AVAILABLE,
    Crawl4AIDiscovery,
    CrawlerConfig,
    DEFAULT_CRAWLERS,
    NormalisedJob,
    build_default_crawler,
)
from core.nexus_config import (
    PORTAL_RISK,
    SUPPORTED_PORTALS,
    portal_supported,
)

log = logging.getLogger("nexus.n03_scraper")


# ────────────────────────────────────────────────────────────────────────────
# JobsDB protocol (duck-typed)
# ────────────────────────────────────────────────────────────────────────────
# The orchestrator wires a real Supabase-backed db here; tests use an
# in-memory stub.  Required methods:
#
#   async def open_scrape_log(portal, mode) -> scrape_log_id (int)
#   async def close_scrape_log(scrape_log_id, jobs_found, jobs_new, status, error)
#   async def upsert_jobs(jobs: list[NormalisedJob]) -> int   # returns NEW count
#
# ────────────────────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────────────────────
# scrape_portal — cron-mode full pass
# ────────────────────────────────────────────────────────────────────────────
async def scrape_portal(
    portal:    str,
    *,
    db,
    discovery: Crawl4AIDiscovery | None = None,
    mode:      str = "cron",
) -> dict[str, Any]:
    """
    Run a full Crawl4AI scrape for `portal`.  Returns a summary dict:
      { portal, jobs_found, jobs_new, duration_ms, status, error }
    Also persists scrape_log row + upserts jobs into the `jobs` table.
    """
    if not portal_supported(portal):
        return {"portal": portal, "status": "rejected",
                "error": "unsupported_portal", "jobs_found": 0, "jobs_new": 0}

    discovery = discovery or Crawl4AIDiscovery()
    log_id = await db.open_scrape_log(portal, mode)
    t0 = time.monotonic()

    crawler = None
    if CRAWL4AI_AVAILABLE:
        try:
            crawler = build_default_crawler()
        except Exception as e:                                        # noqa: BLE001
            log.exception("n03.crawler_build_fail portal=%s err=%s", portal, e)

    try:
        jobs: list[NormalisedJob] = await discovery.discover(
            portal,
            discovery_mode=mode,
            crawler_override=crawler,
        )
        jobs_new = await db.upsert_jobs(jobs)
        duration_ms = int((time.monotonic() - t0) * 1000)

        await db.close_scrape_log(
            log_id,
            jobs_found = len(jobs),
            jobs_new   = jobs_new,
            status     = "ok",
            error      = None,
        )
        log.info(
            "n03.scrape_done portal=%s found=%s new=%s ms=%s",
            portal, len(jobs), jobs_new, duration_ms,
        )
        return {
            "portal":      portal,
            "jobs_found":  len(jobs),
            "jobs_new":    jobs_new,
            "duration_ms": duration_ms,
            "status":      "ok",
            "error":       None,
        }
    except Exception as e:                                            # noqa: BLE001
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.exception("n03.scrape_fail portal=%s err=%s", portal, e)
        await db.close_scrape_log(
            log_id,
            jobs_found = 0,
            jobs_new   = 0,
            status     = "failed",
            error      = f"{type(e).__name__}:{e}",
        )
        return {
            "portal":      portal,
            "jobs_found":  0,
            "jobs_new":    0,
            "duration_ms": duration_ms,
            "status":      "failed",
            "error":       f"{type(e).__name__}:{e}",
        }
    finally:
        if crawler is not None:
            try:
                await crawler.close()                                 # type: ignore[attr-defined]
            except Exception:
                pass


# ────────────────────────────────────────────────────────────────────────────
# snapshot_page — lightweight detail-page LLM extraction (used by Layer 2b)
# ────────────────────────────────────────────────────────────────────────────
async def snapshot_page(
    portal: str,
    url:    str,
    *,
    discovery: Crawl4AIDiscovery | None = None,
) -> list[dict[str, Any]]:
    """
    Single-URL Crawl4AI extraction returning RAW dicts (not NormalisedJob).
    Used by reactive_discovery._browser_watch_loop to detect new cards on
    Naukri's recommended-jobs page without a full crawl.
    """
    if not CRAWL4AI_AVAILABLE:
        log.debug("n03.snapshot_unavailable portal=%s — crawl4ai missing", portal)
        return []

    discovery = discovery or Crawl4AIDiscovery()
    cfg_orig = discovery.crawlers.get(portal)
    discovery.crawlers[portal] = CrawlerConfig(
        portal=portal,
        list_url=url,
        max_pages=1,
        extract_hint=(cfg_orig.extract_hint if cfg_orig else ""),
    )
    try:
        jobs = await discovery.discover(portal, discovery_mode="reactive_watch")
        return [j.to_dict() for j in jobs]
    except Exception as e:                                            # noqa: BLE001
        log.warning("n03.snapshot_err portal=%s err=%s", portal, e)
        return []
    finally:
        if cfg_orig is not None:
            discovery.crawlers[portal] = cfg_orig


# ────────────────────────────────────────────────────────────────────────────
# scrape_all_portals — sequential fan-out (respects Risk Governor caps)
# ────────────────────────────────────────────────────────────────────────────
async def scrape_all_portals(
    *,
    db,
    portals: list[str] | None = None,
    discovery: Crawl4AIDiscovery | None = None,
    inter_portal_delay_seconds: float = 5.0,
) -> dict[str, dict[str, Any]]:
    """
    Run scrape_portal sequentially for each supported portal with a small
    delay between them so the orchestrator never bursts.

    Returns: { portal: summary_dict }
    """
    discovery = discovery or Crawl4AIDiscovery()
    portals   = portals or list(SUPPORTED_PORTALS)
    results: dict[str, dict[str, Any]] = {}

    for portal in portals:
        # Skip portals whose Risk Governor profile says paused; the orchestrator
        # is the source of truth — here we only honour static config.
        if portal not in PORTAL_RISK:
            continue
        results[portal] = await scrape_portal(
            portal, db=db, discovery=discovery, mode="cron",
        )
        await asyncio.sleep(inter_portal_delay_seconds)

    log.info(
        "n03.scrape_all done=%d new_total=%s",
        len(results),
        sum(r.get("jobs_new", 0) for r in results.values()),
    )
    return results


# ────────────────────────────────────────────────────────────────────────────
# In-memory JobsDB stub — for tests + offline dev
# ────────────────────────────────────────────────────────────────────────────
class InMemoryJobsDB:
    """Drop-in db for scrape_portal/snapshot_page in tests."""

    def __init__(self):
        self.scrape_log: dict[int, dict[str, Any]] = {}
        self.jobs:       dict[str, NormalisedJob] = {}
        self._next_log_id = 0

    async def open_scrape_log(self, portal: str, mode: str) -> int:
        self._next_log_id += 1
        self.scrape_log[self._next_log_id] = {
            "portal":      portal,
            "mode":        mode,
            "started_at":  datetime.now(timezone.utc),
            "status":      "running",
        }
        return self._next_log_id

    async def close_scrape_log(
        self,
        log_id:     int,
        jobs_found: int,
        jobs_new:   int,
        status:     str,
        error:      str | None,
    ) -> None:
        row = self.scrape_log.get(log_id, {})
        row.update({
            "finished_at": datetime.now(timezone.utc),
            "jobs_found":  jobs_found,
            "jobs_new":    jobs_new,
            "status":      status,
            "error":       error,
        })

    async def upsert_jobs(self, jobs: list[NormalisedJob]) -> int:
        new_count = 0
        for j in jobs:
            if j.job_id not in self.jobs:
                new_count += 1
            self.jobs[j.job_id] = j
        return new_count


__all__ = [
    "scrape_portal",
    "scrape_all_portals",
    "snapshot_page",
    "InMemoryJobsDB",
]
