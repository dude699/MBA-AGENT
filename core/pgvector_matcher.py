"""
NEXUS v0.2 — Layer 3a: Semantic Profile Matcher (pgvector + Groq embeddings)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Replaces PRISM v0.1's keyword overlap with cosine similarity over Groq
embeddings stored in Supabase pgvector.  A JD that says "global supply chain
optimisation" now correctly matches a profile that says "international trade
logistics" — without exact keyword overlap.

Public surface
--------------
  embed_text(text)              — Groq embeddings call (1024 dims, free tier)
  cosine(a, b)                  — pure-numpy cosine similarity
  ProfileMatcher                — async facade with .match(jd_text) → 0..100
  ProfileMatcher.refresh_profile(text, variant) — re-embed Abuzar's profile
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from core.nexus_config import (
    ANSWER_RAG,
    RESUME_VARIANTS,
    STACK,
    USER_HANDLE,
)

log = logging.getLogger("nexus.pgvector_matcher")

# ─── Optional Groq client guard ───────────────────────────────────────────
try:
    from groq import AsyncGroq                                       # type: ignore
    GROQ_AVAILABLE = True
except Exception:                                                    # noqa: BLE001
    AsyncGroq = None                                                 # type: ignore
    GROQ_AVAILABLE = False


EMBED_DIM = ANSWER_RAG["embedding_dim"]                              # 1024


# ────────────────────────────────────────────────────────────────────────────
# Pure cosine — no numpy required (we keep deps lean)
# ────────────────────────────────────────────────────────────────────────────
def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Returns cosine similarity in [-1, 1]; 1.0 = identical direction."""
    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def cosine_to_score(similarity: float) -> int:
    """Map cosine [-1..1] → integer score [0..100], clamped."""
    s = max(-1.0, min(1.0, similarity))
    return int(round(((s + 1.0) / 2.0) * 100))


# ────────────────────────────────────────────────────────────────────────────
# Embedding call — Groq free-tier endpoint (text-embedding-3-large, 1024 dims)
# ────────────────────────────────────────────────────────────────────────────
_groq_client: "AsyncGroq | None" = None


def _client() -> "AsyncGroq":
    global _groq_client
    if not GROQ_AVAILABLE:
        raise RuntimeError("groq package not installed")
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _groq_client


def _hash_embed(payload: str, dim: int = EMBED_DIM) -> list[float]:
    """
    Deterministic local hash-bucket embedding fallback. Token-level
    hashing-trick projection — costs $0, runs anywhere, never 404s.
    Quality is well below a real model, but it gives a stable, non-zero
    vector so downstream cosine similarity actually discriminates.
    """
    import hashlib

    vec = [0.0] * dim
    if not payload:
        return vec
    tokens = [t for t in payload.lower().split() if t]
    if not tokens:
        return vec
    for tok in tokens:
        h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        # Two independent hash functions (sign + bucket) — feature hashing
        bucket = int.from_bytes(h[:4], "big") % dim
        sign   = 1.0 if (h[4] & 1) else -1.0
        vec[bucket] += sign
    # L2-normalise so cosine downstream works as expected
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        vec = [x / norm for x in vec]
    return vec


async def embed_text(text: str, model: str | None = None) -> list[float]:
    """
    Single-string embedding.  Truncates to ~2000 chars and returns a list of
    EMBED_DIM floats.

    Resolution order:
      1. Groq embeddings endpoint (when GROQ_API_KEY is set AND the model
         name in STACK.groq_embed is actually hosted by Groq).
      2. Deterministic local hash-bucket fallback — never raises, never 404s.
    """
    if not text or not text.strip():
        return [0.0] * EMBED_DIM
    payload = text.strip()[:2000]

    if not GROQ_AVAILABLE or not os.getenv("GROQ_API_KEY"):
        return _hash_embed(payload)

    model = model or STACK.groq_embed
    try:
        resp = await _client().embeddings.create(
            model=model,
            input=payload,
        )
        vec = resp.data[0].embedding                                # type: ignore[attr-defined]
        # Pad/truncate to EMBED_DIM — the actual model may return 768 or
        # 1024 dims depending on what Groq currently hosts. We keep the
        # downstream contract of EMBED_DIM stable.
        vec = list(vec)
        if len(vec) < EMBED_DIM:
            vec = vec + [0.0] * (EMBED_DIM - len(vec))
        elif len(vec) > EMBED_DIM:
            vec = vec[:EMBED_DIM]
        return vec
    except Exception as e:                                          # noqa: BLE001
        # Log once per process at WARN, then silently degrade to hash fallback.
        global _embed_warned
        if not _embed_warned:
            log.warning("embed.fail err=%s — switching to hash-bucket fallback", e)
            _embed_warned = True
        return _hash_embed(payload)


_embed_warned = False


async def embed_many(texts: Iterable[str], model: str | None = None) -> list[list[float]]:
    """Sequential batched embeddings (Groq free tier rate-friendly)."""
    out: list[list[float]] = []
    for t in texts:
        out.append(await embed_text(t, model=model))
    return out


# ────────────────────────────────────────────────────────────────────────────
# Data type
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class ProfileEmbedding:
    user_handle:  str
    variant:      str                    # master | ai_tech | finance | ib | generalist
    profile_text: str
    embedding:    list[float]
    updated_at:   datetime


# ────────────────────────────────────────────────────────────────────────────
# Matcher facade
# ────────────────────────────────────────────────────────────────────────────
class ProfileMatcher:
    """
    Wraps Supabase `profile_embeddings` table.  The provided `db` must expose
    duck-typed methods:

        async def fetch_profile_embedding(user_handle, variant) -> ProfileEmbedding | None
        async def upsert_profile_embedding(rec: ProfileEmbedding) -> None
    """

    def __init__(self, db):
        self.db = db
        self._cache: dict[tuple[str, str], ProfileEmbedding] = {}

    # ---- profile management -------------------------------------------------
    async def refresh_profile(
        self,
        profile_text: str,
        variant:      str = "master",
        user_handle:  str = USER_HANDLE,
    ) -> ProfileEmbedding:
        if variant != "master" and variant not in RESUME_VARIANTS:
            raise ValueError(f"unknown variant {variant!r}")
        emb = await embed_text(profile_text)
        rec = ProfileEmbedding(
            user_handle  = user_handle,
            variant      = variant,
            profile_text = profile_text,
            embedding    = emb,
            updated_at   = datetime.now(timezone.utc),
        )
        await self.db.upsert_profile_embedding(rec)
        self._cache[(user_handle, variant)] = rec
        log.info("matcher.profile_refreshed handle=%s variant=%s", user_handle, variant)
        return rec

    async def _load_profile(
        self, user_handle: str, variant: str,
    ) -> ProfileEmbedding | None:
        key = (user_handle, variant)
        if key in self._cache:
            return self._cache[key]
        rec = await self.db.fetch_profile_embedding(user_handle, variant)
        if rec is not None:
            self._cache[key] = rec
        return rec

    # ---- match ------------------------------------------------------------
    async def match(
        self,
        jd_text:     str,
        variant:     str = "master",
        user_handle: str = USER_HANDLE,
    ) -> int:
        """
        Returns integer 0..100 representing semantic profile match.
        Falls back to 50 (neutral) if either embedding is unavailable.
        """
        prof = await self._load_profile(user_handle, variant)
        if prof is None or not any(prof.embedding):
            log.debug("matcher.no_profile handle=%s variant=%s — neutral 50",
                      user_handle, variant)
            return 50

        jd_vec = await embed_text(jd_text)
        if not any(jd_vec):
            return 50
        sim = cosine(prof.embedding, jd_vec)
        score = cosine_to_score(sim)
        log.debug("matcher.match variant=%s sim=%.3f score=%s", variant, sim, score)
        return score

    async def match_with_jd_embedding(
        self,
        jd_embedding: Sequence[float],
        variant:      str = "master",
        user_handle:  str = USER_HANDLE,
    ) -> int:
        """Same as match() but reuses an already-computed JD embedding."""
        prof = await self._load_profile(user_handle, variant)
        if prof is None or not any(prof.embedding) or not any(jd_embedding):
            return 50
        return cosine_to_score(cosine(prof.embedding, jd_embedding))

    # ---- variant selection ------------------------------------------------
    async def best_variant(
        self,
        jd_text:     str,
        user_handle: str = USER_HANDLE,
    ) -> tuple[str, int]:
        """
        Innovation 8 — Multi-Resume Variant Routing.
        Tries all variants, returns (best_variant, score).
        """
        jd_vec = await embed_text(jd_text)
        best = ("master", 0)
        for variant in ("master", *RESUME_VARIANTS):
            prof = await self._load_profile(user_handle, variant)
            if prof is None or not any(prof.embedding):
                continue
            score = cosine_to_score(cosine(prof.embedding, jd_vec))
            if score > best[1]:
                best = (variant, score)
        log.info("matcher.best_variant handle=%s -> %s (score=%s)",
                 user_handle, best[0], best[1])
        return best


# ────────────────────────────────────────────────────────────────────────────
# In-memory profile DB stub
# ────────────────────────────────────────────────────────────────────────────
class InMemoryProfileDB:
    def __init__(self):
        self._store: dict[tuple[str, str], ProfileEmbedding] = {}

    async def fetch_profile_embedding(
        self, user_handle: str, variant: str,
    ) -> ProfileEmbedding | None:
        return self._store.get((user_handle, variant))

    async def upsert_profile_embedding(self, rec: ProfileEmbedding) -> None:
        self._store[(rec.user_handle, rec.variant)] = rec


__all__ = [
    "ProfileMatcher",
    "ProfileEmbedding",
    "InMemoryProfileDB",
    "embed_text",
    "embed_many",
    "cosine",
    "cosine_to_score",
    "EMBED_DIM",
]
