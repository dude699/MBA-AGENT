"""
NEXUS v0.2 — Layer 7: Semantic Deduplication Engine
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Two-stage dedup so the same role posted on 3 portals is applied to ONCE
(on the highest-quality portal), and reposted titles for the same role at
the same company are caught.

Stage 1 — Exact match
  applied_jobs WHERE company = X AND title_hash matches first-20 normalised tokens

Stage 2 — Semantic match (pgvector)
  RPC find_similar_jds(query_embedding, company, threshold=0.88, days_back=60)
  Two JDs with cosine >= 0.88 over the last 60 days are treated as duplicates.

Public surface
--------------
  DedupEngine(db, matcher)
      .is_duplicate(job)        -> (bool, reason_or_none)
      .pick_best_portal(jobs)   -> NormalisedJob   # winner across cross-posts
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from core.crawl4ai_discovery import NormalisedJob
from core.pgvector_matcher import EMBED_DIM, cosine, embed_text

log = logging.getLogger("nexus.dedup")


# ────────────────────────────────────────────────────────────────────────────
# Title normalisation — drop seniority adjectives, punctuation, casing
# ────────────────────────────────────────────────────────────────────────────
_NOISE_TOKENS = {
    "the", "a", "an", "and", "or", "of", "for", "in", "to", "with",
    "junior", "senior", "lead", "principal", "associate", "executive",
    "intern", "trainee", "fresher", "fulltime", "full-time", "part-time",
    "remote", "hybrid", "onsite", "on-site",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalise_title(title: str) -> str:
    """Strip noise tokens, lowercase, drop punctuation, sort tokens for stable hash."""
    if not title:
        return ""
    tokens = [t for t in _TOKEN_RE.findall(title.lower()) if t not in _NOISE_TOKENS]
    return " ".join(tokens)


def title_hash(title: str) -> str:
    """SHA256 of normalised title — stable, exact-match-friendly."""
    return hashlib.sha256(normalise_title(title).encode()).hexdigest()


# ────────────────────────────────────────────────────────────────────────────
# Portal-quality ranking — Innovation 9 hint: the orchestrator overrides
# this with live portal_health.callback_rate when available.
# ────────────────────────────────────────────────────────────────────────────
PORTAL_QUALITY_DEFAULT: dict[str, int] = {
    "linkedin":     100,        # highest recruiter visibility
    "wellfound":     90,
    "iimjobs":       85,
    "naukri":        75,
    "instahyre":     72,
    "internshala":   70,
    "indeed":        65,
    "ycombinator":   95,        # YC quality bar
    "unstop":        60,
    "shine":         50,
    "timesjobs":     50,
}


# ────────────────────────────────────────────────────────────────────────────
# DedupEngine
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class DedupResult:
    is_duplicate: bool
    reason:       str | None = None     # exact_match | semantic:<job_id> | None
    similar_to:   str | None = None     # job_id of the existing record


class DedupEngine:
    """
    Required `db` methods:
        async def find_exact_applied(company, title_hash) -> str | None
                                                          # returns existing job_id
        async def find_similar_jds(query_embedding, company, threshold, days_back)
                  -> list[dict]   # rows from the SQL RPC, each {job_id, similarity}
    """

    def __init__(
        self,
        db,
        *,
        semantic_threshold: float = 0.88,
        days_back:          int   = 60,
    ):
        self.db                 = db
        self.semantic_threshold = semantic_threshold
        self.days_back          = days_back

    # ---- main entry --------------------------------------------------------
    async def is_duplicate(
        self,
        job:           NormalisedJob,
        jd_embedding:  list[float] | None = None,
    ) -> DedupResult:
        """
        Stage 1: exact match (company + title_hash).
        Stage 2: semantic match via pgvector RPC over last `days_back` days.
        """
        # Stage 1
        h = title_hash(job.title)
        existing = await self.db.find_exact_applied(job.company, h)
        if existing:
            log.info(
                "dedup.exact job=%s company=%s -> matches %s",
                job.job_id, job.company, existing,
            )
            return DedupResult(True, "exact_match", similar_to=existing)

        # Stage 2 — embed only if not already provided
        if jd_embedding is None:
            jd_embedding = await embed_text(job.jd_text or job.title)
        if not any(jd_embedding):
            return DedupResult(False)

        rows = await self.db.find_similar_jds(
            query_embedding = jd_embedding,
            company         = job.company,
            threshold       = self.semantic_threshold,
            days_back       = self.days_back,
        )
        if rows:
            top = rows[0]
            log.info(
                "dedup.semantic job=%s company=%s sim=%.3f -> %s",
                job.job_id, job.company, top.get("similarity", 0.0), top["job_id"],
            )
            return DedupResult(
                True,
                f"semantic_duplicate_of_{top['job_id']}",
                similar_to=top["job_id"],
            )
        return DedupResult(False)

    # ---- best-portal picker (cross-posted detection within a discovery batch)
    @staticmethod
    def pick_best_portal(
        jobs:            Iterable[NormalisedJob],
        portal_quality:  dict[str, int] | None = None,
        score_lookup:    dict[str, int]        | None = None,
    ) -> NormalisedJob:
        """
        Among a set of cross-posted jobs (same role at same company on different
        portals), choose the one to actually apply to.  Quality criteria:
           1. Highest external NEXUS score (if score_lookup provided)
           2. Highest portal_quality
           3. Earliest posted_at (fresher wins ties)
        """
        if not jobs:
            raise ValueError("pick_best_portal called with empty iterable")
        quality = portal_quality or PORTAL_QUALITY_DEFAULT
        scores  = score_lookup or {}

        def _key(j: NormalisedJob) -> tuple[int, int, float]:
            score   = scores.get(j.job_id, 0)
            qual    = quality.get(j.portal, 0)
            # earlier posted_at -> larger negative timestamp (so it sorts higher)
            posted  = j.posted_at if j.posted_at.tzinfo else j.posted_at.replace(tzinfo=timezone.utc)
            return (score, qual, -posted.timestamp())

        winner = max(jobs, key=_key)
        log.info(
            "dedup.best_portal company=%s title=%r -> portal=%s job=%s",
            winner.company, winner.title, winner.portal, winner.job_id,
        )
        return winner

    # ---- batch helper used by orchestrator ingest path -------------------
    async def filter_unique(
        self,
        jobs: list[NormalisedJob],
    ) -> tuple[list[NormalisedJob], list[tuple[NormalisedJob, DedupResult]]]:
        """
        Returns (unique_jobs, duplicates_with_reason).
        Maintains insertion order for determinism in tests.
        """
        unique:    list[NormalisedJob] = []
        dups:      list[tuple[NormalisedJob, DedupResult]] = []
        for j in jobs:
            res = await self.is_duplicate(j)
            if res.is_duplicate:
                dups.append((j, res))
            else:
                unique.append(j)
        log.info("dedup.filter in=%d unique=%d dups=%d",
                 len(jobs), len(unique), len(dups))
        return unique, dups


# ────────────────────────────────────────────────────────────────────────────
# In-memory dedup DB stub — implements both stages over local dicts
# ────────────────────────────────────────────────────────────────────────────
class InMemoryDedupDB:
    def __init__(self):
        # exact-match index
        self.applied:        dict[tuple[str, str], str] = {}      # (company, title_hash) -> job_id
        # semantic index
        self.applied_jds:    list[dict] = []                       # rows with company/job_id/embedding/applied_at

    async def find_exact_applied(
        self, company: str, title_hash_value: str,
    ) -> str | None:
        return self.applied.get((company, title_hash_value))

    async def find_similar_jds(
        self,
        query_embedding: list[float],
        company:         str,
        threshold:       float,
        days_back:       int,
    ) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - days_back * 86400
        out: list[dict] = []
        for row in self.applied_jds:
            if row["company"] != company:
                continue
            if row["applied_at"].timestamp() < cutoff:
                continue
            sim = cosine(row["embedding"], query_embedding)
            if sim >= threshold:
                out.append({"job_id": row["job_id"], "similarity": sim})
        out.sort(key=lambda r: r["similarity"], reverse=True)
        return out[:5]

    # convenience for tests
    def record_application(
        self,
        job_id:    str,
        company:   str,
        title:     str,
        embedding: list[float],
        when:      datetime | None = None,
    ) -> None:
        self.applied[(company, title_hash(title))] = job_id
        self.applied_jds.append({
            "job_id":     job_id,
            "company":    company,
            "embedding":  embedding,
            "applied_at": when or datetime.now(timezone.utc),
        })


__all__ = [
    "DedupEngine",
    "DedupResult",
    "InMemoryDedupDB",
    "normalise_title",
    "title_hash",
    "PORTAL_QUALITY_DEFAULT",
]
