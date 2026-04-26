"""
NEXUS v0.2 — Layer 2: Universal Job Discovery Engine (Crawl4AI-Powered)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Crawl4AI (#1 trending GitHub crawler, Apache 2.0 free) replaces every custom
per-portal scraper from PRISM v0.1.  ONE unified extraction interface that:

  • Converts any webpage to clean markdown (67% fewer tokens than raw HTML).
  • Has built-in session management, proxy rotation, stealth, JS execution.
  • Adapts to layout changes via LLM-guided schema extraction (Groq llama-3.3).

Public surface
--------------
  NormalisedJob              — canonical job schema all of NEXUS speaks
  CrawlerConfig              — per-portal tuning (selectors-of-interest only
                               as HINTS to the LLM, never required)
  Crawl4AIDiscovery          — async facade with `discover(portal)` entrypoint
  build_default_crawler()    — pre-wired Crawl4AI instance with stealth on

Heavy imports are guarded — the module loads on the slim Render dyno even
without `crawl4ai` installed; in that case `discover()` raises a clear
RuntimeError instead of an ImportError at import time.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from core.nexus_config import (
    REACTIVE_SOURCES,
    SALARY_NORMALISER,
    STACK,
    SUPPORTED_PORTALS,
    portal_supported,
)

log = logging.getLogger("nexus.crawl4ai")


# ─── Heavy import guard ───────────────────────────────────────────────────
try:
    from crawl4ai import (                                            # type: ignore
        AsyncWebCrawler,
        CrawlerRunConfig,
        BrowserConfig,
        LLMConfig,
    )
    from crawl4ai.extraction_strategy import LLMExtractionStrategy    # type: ignore
    CRAWL4AI_AVAILABLE = True
except Exception:                                                     # noqa: BLE001
    AsyncWebCrawler = None                                            # type: ignore
    CrawlerRunConfig = None                                           # type: ignore
    BrowserConfig = None                                              # type: ignore
    LLMConfig = None                                                  # type: ignore
    LLMExtractionStrategy = None                                      # type: ignore
    CRAWL4AI_AVAILABLE = False


# ────────────────────────────────────────────────────────────────────────────
# NormalisedJob — the single schema every layer downstream consumes
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class NormalisedJob:
    job_id:              str                       # portal:hash
    portal:              str
    company:             str
    title:               str
    location:            str | None
    remote:              bool
    stipend_inr_monthly: int | None
    stipend_raw:         str | None
    deadline:            datetime | None
    posted_at:           datetime
    discovered_at:       datetime
    discovery_mode:      str                       # cron | reactive_rss | reactive_webhook
    jd_text:             str
    raw_url:             str
    applicant_count:     int | None = None
    raw_payload:         dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("deadline", "posted_at", "discovered_at"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    @staticmethod
    def make_id(portal: str, raw_url: str, title: str) -> str:
        sig = f"{portal}|{raw_url}|{title.strip().lower()}"
        return f"{portal}:{hashlib.sha256(sig.encode()).hexdigest()[:16]}"


# ────────────────────────────────────────────────────────────────────────────
# Per-portal crawl recipe — HINTS only.  No CSS selectors are mandatory.
# ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CrawlerConfig:
    portal:           str
    list_url:         str                            # entry/listing URL
    list_url_paged:   str | None = None              # template with {page}
    js_required:      bool = True
    waiting_selector: str | None = None              # hint for LLM, not strict
    max_pages:        int = 3
    extract_hint:     str = ""                       # optional NL hint to LLM


# Sensible defaults for the 11 supported portals.  These are entry URLs only;
# Crawl4AI follows links inside via LLM guidance.
DEFAULT_CRAWLERS: dict[str, CrawlerConfig] = {
    "linkedin": CrawlerConfig(
        portal="linkedin",
        list_url="https://www.linkedin.com/jobs/search/?keywords=mba%20intern%20india&f_TPR=r86400",
        list_url_paged="https://www.linkedin.com/jobs/search/?keywords=mba%20intern%20india&f_TPR=r86400&start={page}",
        max_pages=3,
        extract_hint="Each card has a job title, company name, location, posted-time, and an Easy-Apply badge if present.",
    ),
    "internshala": CrawlerConfig(
        portal="internshala",
        list_url="https://internshala.com/internships/management-internships/",
        max_pages=4,
        extract_hint="Each row has role title, company, stipend (₹/month), duration, location, posted-on, deadline.",
    ),
    "naukri": CrawlerConfig(
        portal="naukri",
        list_url="https://www.naukri.com/mba-jobs",
        max_pages=3,
        extract_hint="Each card has title, company, experience required, salary band (LPA), location, posted date.",
    ),
    "iimjobs":     CrawlerConfig("iimjobs",     "https://www.iimjobs.com/", max_pages=2),
    "unstop":      CrawlerConfig("unstop",      "https://unstop.com/jobs", max_pages=2),
    "wellfound":   CrawlerConfig("wellfound",   "https://wellfound.com/jobs", max_pages=2),
    "indeed":      CrawlerConfig("indeed",      "https://in.indeed.com/jobs?q=mba+intern", max_pages=2),
    "ycombinator": CrawlerConfig("ycombinator", "https://www.ycombinator.com/jobs", max_pages=1),
    "instahyre":   CrawlerConfig("instahyre",   "https://www.instahyre.com/search-jobs/", max_pages=2),
    "shine":       CrawlerConfig("shine",       "https://www.shine.com/job-search/mba-jobs", max_pages=2),
    "timesjobs":   CrawlerConfig("timesjobs",   "https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&from=submit&txtKeywords=MBA", max_pages=2),
}


# ────────────────────────────────────────────────────────────────────────────
# Salary normaliser (Innovation 13)
# ────────────────────────────────────────────────────────────────────────────
_LPA_RE       = re.compile(r"(\d+(?:\.\d+)?)\s*(?:l|lakh|lpa)", re.I)
_PER_MONTH_RE = re.compile(r"(\d+(?:[\,\.]\d+)?)\s*(?:/|per)\s*(?:mo|month)", re.I)
_USD_PER_YR   = re.compile(r"\$\s*(\d+(?:[\,\.]\d+)?)\s*(?:/|per)?\s*(?:yr|year|annum)?", re.I)
_INR_NUMBER   = re.compile(r"₹\s*([\d,\.]+)")


def normalise_stipend_to_inr_monthly(raw: str | None) -> int | None:
    """Best-effort conversion of any stipend string → INR / month (in-hand)."""
    if not raw:
        return None
    s = raw.strip()
    cfg = SALARY_NORMALISER

    if (m := _PER_MONTH_RE.search(s)):
        n = float(m.group(1).replace(",", ""))
        return int(n)

    if (m := _LPA_RE.search(s)):
        lpa = float(m.group(1))
        annual_inr = lpa * 100_000 * cfg["ctc_to_inhand_factor"]
        return int(annual_inr / 12)

    if (m := _USD_PER_YR.search(s)):
        usd = float(m.group(1).replace(",", ""))
        annual_inr = usd * cfg["usd_to_inr"] * cfg["ctc_to_inhand_factor"]
        return int(annual_inr / 12)

    if (m := _INR_NUMBER.search(s)):
        n_str = m.group(1).replace(",", "")
        try:
            n = float(n_str)
            # Heuristic — if number looks annual (>3 lakh), convert
            if n > 300000:
                return int(n * cfg["ctc_to_inhand_factor"] / 12)
            return int(n)
        except ValueError:
            return None
    return None


# ────────────────────────────────────────────────────────────────────────────
# LLM extraction prompt — schema instruction handed to Crawl4AI's
# LLMExtractionStrategy (powered by Groq llama-3.3-70b)
# ────────────────────────────────────────────────────────────────────────────
EXTRACTION_SCHEMA_INSTRUCTION = """
Extract every job posting visible on the page as JSON array of objects with:

  - title          : str  (role / job title)
  - company        : str  (employer name)
  - location       : str  (city, country, or 'Remote' / 'Work from home')
  - remote         : bool (true if explicitly remote)
  - stipend_raw    : str  (whatever the page shows for compensation, raw)
  - deadline       : str  (ISO 8601 date if visible, else empty string)
  - posted_at      : str  (relative or absolute, parsed if possible)
  - jd_text        : str  (1-3 sentences summarising responsibilities)
  - raw_url        : str  (absolute permalink to the job detail page)
  - applicant_count: int  (visible applicant count, else 0)

Skip closed, expired, or duplicate listings.  Return ONLY the JSON array.
""".strip()


# ────────────────────────────────────────────────────────────────────────────
# Discovery facade
# ────────────────────────────────────────────────────────────────────────────
class Crawl4AIDiscovery:
    """Async facade that runs a Crawl4AI extraction for a portal."""

    def __init__(
        self,
        crawlers: dict[str, CrawlerConfig] | None = None,
        llm_provider: str = "groq",
        llm_model:    str | None = None,
    ):
        self.crawlers   = crawlers or DEFAULT_CRAWLERS
        self.llm_provider = llm_provider
        self.llm_model  = llm_model or STACK.groq_llm

    # ---- main entry -------------------------------------------------------
    async def discover(
        self,
        portal:         str,
        discovery_mode: str = "cron",
        crawler_override: AsyncWebCrawler | None = None,
    ) -> list[NormalisedJob]:
        if not portal_supported(portal):
            raise ValueError(f"unsupported portal {portal!r}")

        if not CRAWL4AI_AVAILABLE:
            raise RuntimeError(
                "crawl4ai not installed.  Install requirements-nexus.txt on "
                "the worker dyno (this dyno is the slim PRISM dyno)."
            )

        cfg = self.crawlers.get(portal)
        if cfg is None:
            raise KeyError(f"no CrawlerConfig for portal={portal!r}")

        crawler = crawler_override or build_default_crawler()
        results: list[NormalisedJob] = []
        t0 = time.monotonic()
        try:
            urls = self._paginate(cfg)
            for url in urls:
                try:
                    page_jobs = await self._scrape_one(crawler, cfg, url, discovery_mode)
                    results.extend(page_jobs)
                except Exception as e:                                # noqa: BLE001
                    log.exception("crawl4ai.page_err portal=%s url=%s err=%s",
                                  portal, url, e)
        finally:
            if crawler_override is None:
                try:
                    await crawler.close()                              # type: ignore[attr-defined]
                except Exception:
                    pass

        log.info(
            "crawl4ai.done portal=%s found=%s urls=%s ms=%s",
            portal, len(results), len(urls), int((time.monotonic() - t0) * 1000),
        )
        return results

    # ---- per-page scrape --------------------------------------------------
    async def _scrape_one(
        self,
        crawler:        Any,
        cfg:            CrawlerConfig,
        url:            str,
        discovery_mode: str,
    ) -> list[NormalisedJob]:
        run_cfg = CrawlerRunConfig(
            extraction_strategy=LLMExtractionStrategy(
                llm_config=LLMConfig(
                    provider=self.llm_provider,
                    api_token="env:GROQ_API_KEY",
                    model=self.llm_model,
                ),
                instruction=EXTRACTION_SCHEMA_INSTRUCTION
                + ("\nHints: " + cfg.extract_hint if cfg.extract_hint else ""),
                output_format="json",
            ),
            wait_for=cfg.waiting_selector,
            js_only=False,
            page_timeout=45_000,
        )
        result = await crawler.arun(url=url, config=run_cfg)
        if not result or not getattr(result, "extracted_content", None):
            return []

        try:
            import json as _json
            parsed: list[dict[str, Any]] = _json.loads(result.extracted_content)
        except Exception:
            log.warning("crawl4ai.parse_fail portal=%s url=%s", cfg.portal, url)
            return []

        out: list[NormalisedJob] = []
        for raw in parsed:
            try:
                out.append(self._materialise(cfg.portal, raw, discovery_mode))
            except Exception as e:                                    # noqa: BLE001
                log.debug("crawl4ai.row_skip portal=%s err=%s", cfg.portal, e)
        return out

    # ---- raw dict → NormalisedJob ----------------------------------------
    @staticmethod
    def _materialise(
        portal:         str,
        raw:            dict[str, Any],
        discovery_mode: str,
    ) -> NormalisedJob:
        title   = (raw.get("title")   or "").strip()
        company = (raw.get("company") or "").strip()
        url     = (raw.get("raw_url") or "").strip()
        if not title or not company or not url:
            raise ValueError("missing title/company/url")

        return NormalisedJob(
            job_id              = NormalisedJob.make_id(portal, url, title),
            portal              = portal,
            company             = company,
            title               = title,
            location            = (raw.get("location") or None),
            remote              = bool(raw.get("remote", False)),
            stipend_raw         = raw.get("stipend_raw") or None,
            stipend_inr_monthly = normalise_stipend_to_inr_monthly(
                raw.get("stipend_raw")
            ),
            deadline            = _parse_iso(raw.get("deadline")),
            posted_at           = _parse_iso(raw.get("posted_at"))
                                 or datetime.now(timezone.utc),
            discovered_at       = datetime.now(timezone.utc),
            discovery_mode      = discovery_mode,
            jd_text             = (raw.get("jd_text") or "").strip(),
            raw_url             = url,
            applicant_count     = (
                int(raw["applicant_count"]) if raw.get("applicant_count") else None
            ),
            raw_payload         = raw,
        )

    # ---- pagination ------------------------------------------------------
    @staticmethod
    def _paginate(cfg: CrawlerConfig) -> list[str]:
        if cfg.list_url_paged is None:
            return [cfg.list_url]
        # LinkedIn's `start=` index increments by 25 per page
        urls = []
        for i in range(cfg.max_pages):
            urls.append(cfg.list_url_paged.format(page=i * 25))
        return urls


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def build_default_crawler() -> Any:
    """Construct a Crawl4AI crawler with stealth + JS rendering enabled."""
    if not CRAWL4AI_AVAILABLE:
        raise RuntimeError("crawl4ai not installed")
    browser_cfg = BrowserConfig(
        browser_type="firefox",      # Camoufox underneath
        headless=True,
        user_agent_mode="random",
        verbose=False,
    )
    return AsyncWebCrawler(config=browser_cfg)


__all__ = [
    "NormalisedJob",
    "CrawlerConfig",
    "DEFAULT_CRAWLERS",
    "Crawl4AIDiscovery",
    "build_default_crawler",
    "normalise_stipend_to_inr_monthly",
    "EXTRACTION_SCHEMA_INSTRUCTION",
    "CRAWL4AI_AVAILABLE",
]
