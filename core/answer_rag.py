"""
NEXUS v0.2 — Layer 4: Adaptive Answer Generation Engine (RAG)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Voice-consistent custom-answer generation via Retrieval-Augmented Generation
over Abuzar's growing answer bank.

Flow (per the architecture doc, Section 4)
------------------------------------------
1. New custom question detected in form (e.g. "What excites you about this
   role in supply chain consulting?").
2. Question embedded via Groq → cosine search in `answer_bank` pgvector table.
3. Top-K (default 3) similar past answers retrieved as few-shot examples.
4. Cerebras prompt:
       system = "You are Abuzar.  Voice examples below."
       user   = "Answer this NEW question for [Company] [Role]: ..."
5. Generated answer added to bank for future RAG.
6. Quality validator runs:
       - word count 100..180 (configurable)
       - banned phrases filter
       - company name inclusion required
       - reject + regenerate (1 retry) on failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from core.crawl4ai_discovery import NormalisedJob
from core.nexus_config import (
    ANSWER_RAG,
    STACK,
    USER_HANDLE,
)
from core.pgvector_matcher import EMBED_DIM, cosine, embed_text

log = logging.getLogger("nexus.answer_rag")


# ─── Optional Cerebras client guard ───────────────────────────────────────
try:
    from cerebras.cloud.sdk import AsyncCerebras                     # type: ignore
    CEREBRAS_AVAILABLE = True
except Exception:                                                    # noqa: BLE001
    AsyncCerebras = None                                             # type: ignore
    CEREBRAS_AVAILABLE = False


# ────────────────────────────────────────────────────────────────────────────
# Data types
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class AnswerRecord:
    user_handle:        str
    question_text:      str
    question_embedding: list[float]
    answer_text:        str
    company:            str | None = None
    role:               str | None = None
    portal:             str | None = None
    word_count:         int = 0
    quality_score:      int = 0
    created_at:         datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GenerationResult:
    answer:        str
    used_examples: list[AnswerRecord]
    word_count:    int
    quality_score: int
    duration_ms:   int
    retried:       bool = False
    rejected:      bool = False


# ────────────────────────────────────────────────────────────────────────────
# Validator (Step 6)
# ────────────────────────────────────────────────────────────────────────────
def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def validate_answer(
    answer:  str,
    company: str | None,
) -> tuple[bool, list[str], int]:
    """Returns (ok, reasons_failed, quality_score 0..100)."""
    reasons: list[str] = []
    cfg = ANSWER_RAG

    # Word count
    wc = _word_count(answer)
    if wc < cfg["min_word_count"]:
        reasons.append(f"too_short:{wc}<{cfg['min_word_count']}")
    if wc > cfg["max_word_count"]:
        reasons.append(f"too_long:{wc}>{cfg['max_word_count']}")

    # Banned phrases
    lower = answer.lower()
    for phrase in cfg["banned_phrases"]:
        if phrase in lower:
            reasons.append(f"banned:{phrase!r}")

    # Company-name inclusion
    if cfg["must_include_company"] and company:
        # Forgive case + minor punctuation differences
        company_simple = re.sub(r"[^\w]", "", company.lower())
        answer_simple  = re.sub(r"[^\w]", "", answer.lower())
        if company_simple and company_simple not in answer_simple:
            reasons.append("missing_company_name")

    ok = not reasons
    # Quality score: word-count sweet spot + clean of bans + company present
    sweet_spot = (cfg["min_word_count"] + cfg["max_word_count"]) / 2.0
    span = max(1, cfg["max_word_count"] - cfg["min_word_count"])
    word_score = max(0.0, 1.0 - abs(wc - sweet_spot) / span) * 60      # up to 60
    bonus = 40 if ok else max(0, 40 - 10 * len(reasons))
    quality = int(round(word_score + bonus))
    return ok, reasons, max(0, min(100, quality))


# ────────────────────────────────────────────────────────────────────────────
# RAG facade
# ────────────────────────────────────────────────────────────────────────────
class AnswerRAG:
    """
    Wraps the `answer_bank` table.  The provided `db` must expose:

        async def fetch_top_k_similar(user_handle, q_embedding, k) -> list[AnswerRecord]
        async def insert_answer(rec: AnswerRecord) -> None
    """

    def __init__(self, db, *, model: str | None = None):
        self.db    = db
        self.model = model or STACK.cerebras_llm

    # ---- Cerebras client (lazy) -------------------------------------------
    _client_cache: "AsyncCerebras | None" = None

    @classmethod
    def _client(cls) -> "AsyncCerebras":
        if not CEREBRAS_AVAILABLE:
            raise RuntimeError("cerebras-cloud-sdk not installed")
        if cls._client_cache is None:
            cls._client_cache = AsyncCerebras(api_key=os.getenv("CEREBRAS_API_KEY", ""))
        return cls._client_cache

    # ---- main entry --------------------------------------------------------
    async def generate(
        self,
        question:    str,
        job:         NormalisedJob,
        profile:     dict,
        user_handle: str = USER_HANDLE,
    ) -> GenerationResult:
        t0 = time.monotonic()

        # Step 2: embed question
        q_emb = await embed_text(question)

        # Step 3: retrieve top-K examples
        examples = await self.db.fetch_top_k_similar(
            user_handle, q_emb, ANSWER_RAG["top_k"]
        )

        # Step 4–5: generate (with 1 retry on validation failure)
        prompt_system, prompt_user = self._build_prompt(question, job, profile, examples)
        answer = await self._cerebras_call(prompt_system, prompt_user)

        ok, reasons, quality = validate_answer(answer, job.company)
        retried = False
        if not ok:
            log.warning("rag.validate_fail reasons=%s — retrying once", reasons)
            answer  = await self._cerebras_call(prompt_system, prompt_user, temperature=0.5)
            ok, reasons, quality = validate_answer(answer, job.company)
            retried = True

        rejected = not ok
        wc = _word_count(answer)

        # Step 5: store on success
        if ok:
            try:
                await self.db.insert_answer(AnswerRecord(
                    user_handle        = user_handle,
                    question_text      = question,
                    question_embedding = q_emb,
                    answer_text        = answer,
                    company            = job.company,
                    role               = job.title,
                    portal             = job.portal,
                    word_count         = wc,
                    quality_score      = quality,
                ))
            except Exception as e:                                   # noqa: BLE001
                log.warning("rag.insert_fail err=%s", e)

        result = GenerationResult(
            answer        = answer,
            used_examples = examples,
            word_count    = wc,
            quality_score = quality,
            duration_ms   = int((time.monotonic() - t0) * 1000),
            retried       = retried,
            rejected      = rejected,
        )
        log.info(
            "rag.done q=%r company=%s words=%s quality=%s retried=%s rejected=%s",
            question[:60], job.company, wc, quality, retried, rejected,
        )
        return result

    # ---- prompt builder ---------------------------------------------------
    @staticmethod
    def _build_prompt(
        question: str,
        job:      NormalisedJob,
        profile:  dict,
        examples: Sequence[AnswerRecord],
    ) -> tuple[str, str]:
        ex_block = "\n\n".join(
            f"Past Q: {e.question_text}\nPast A: {e.answer_text}"
            for e in examples
        ) or "(no past answers yet — produce a fresh first one)"

        system = (
            "You are MD Abuzar Salim, an MBA student at AMU specialising in "
            "International Business.  Below are 3 of your own past answers — "
            "they capture YOUR voice (first-person, specific projects mentioned, "
            "no generic MBA jargon).  Match this voice exactly.  Never use the "
            "phrases 'I am passionate about', 'highly motivated', or 'as a "
            "recent graduate'.  Always reference ONE concrete past project.  "
            "Always mention the target company by name.\n\n"
            f"=== Voice examples ===\n{ex_block}\n=== end examples ==="
        )

        cfg = ANSWER_RAG
        profile_brief = (
            f"name={profile.get('name')}, "
            f"projects={profile.get('projects', [])[:3]}, "
            f"focus_area={profile.get('focus_area', 'International Business')}"
        )

        user = (
            f"Write a NEW custom-question answer ({cfg['min_word_count']}–"
            f"{cfg['max_word_count']} words) for:\n"
            f"  Company : {job.company}\n"
            f"  Role    : {job.title}\n"
            f"  JD      : {job.jd_text[:500]}\n"
            f"  Profile : {profile_brief}\n\n"
            f"  Question: {question}\n\n"
            "Rules:\n"
            "  • Mention the company by name at least once.\n"
            "  • Reference exactly one specific past project.\n"
            "  • First person, no emojis, no bullet points.\n"
            "  • Return ONLY the answer text — no preamble, no markdown."
        )
        return system, user

    # ---- Cerebras call ----------------------------------------------------
    async def _cerebras_call(
        self,
        system:      str,
        user:        str,
        temperature: float = 0.3,
    ) -> str:
        if not CEREBRAS_AVAILABLE:
            log.warning("rag.cerebras_unavailable — returning stub answer")
            return f"[stub answer — Cerebras SDK not installed]"
        try:
            client = self._client()
            resp = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                temperature=temperature,
                max_tokens=400,
            )
            return resp.choices[0].message.content.strip()           # type: ignore[attr-defined]
        except Exception as e:                                       # noqa: BLE001
            log.exception("rag.cerebras_fail err=%s", e)
            return f"[generation failed: {type(e).__name__}]"


# ────────────────────────────────────────────────────────────────────────────
# In-memory bank — for tests and offline dev
# ────────────────────────────────────────────────────────────────────────────
class InMemoryAnswerBank:
    def __init__(self):
        self._store: list[AnswerRecord] = []

    async def fetch_top_k_similar(
        self,
        user_handle: str,
        q_embedding: list[float],
        k:           int,
    ) -> list[AnswerRecord]:
        if not q_embedding or not any(q_embedding):
            return []
        scored = []
        for rec in self._store:
            if rec.user_handle != user_handle:
                continue
            if not rec.question_embedding or len(rec.question_embedding) != len(q_embedding):
                continue
            sim = cosine(rec.question_embedding, q_embedding)
            scored.append((sim, rec))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [r for _, r in scored[:k]]

    async def insert_answer(self, rec: AnswerRecord) -> None:
        self._store.append(rec)


__all__ = [
    "AnswerRAG",
    "AnswerRecord",
    "GenerationResult",
    "InMemoryAnswerBank",
    "validate_answer",
]
