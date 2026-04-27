"""
NEXUS v0.2 — Layer 5: Four-Tier CAPTCHA Resolution Engine
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Four tiers, escalated in order until one succeeds:

  Tier  Method                                Handles                         Cost
  ────  ────────────────────────────────────  ──────────────────────────────  ────
  T1    Gemini 2.5 Flash vision (free 500 RPD) reCAPTCHA v2 image grids       0
  T2    Groq Whisper Large v3 audio (14.4K)    reCAPTCHA v2 audio challenge   0
  T3    Telegram human relay (45 s window)    Any CAPTCHA                    0
  T4    Skyvern surgical_fallback             Alt submission paths           0
        (alt-path detection — quick apply,
        apply with LinkedIn, etc.)

Public surface
--------------
  CaptchaResolver(adapter, ...)
      .resolve(page, portal, job_id) -> ResolveResult
      .telegram_relay_response(challenge_id, answer)   # called by Telegram bot

Heavy imports (Skyvern, PIL, etc.) are guarded.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from core.nexus_config import (
    CAPTCHA_TELEGRAM_TIMEOUT_SEC,
    CAPTCHA_TIERS,
    STACK,
)

log = logging.getLogger("nexus.captcha")


# ────────────────────────────────────────────────────────────────────────────
# Enums + result type
# ────────────────────────────────────────────────────────────────────────────
class Tier(str, Enum):
    T1_GEMINI_VISION    = "T1_gemini_vision"
    T2_GROQ_WHISPER     = "T2_groq_whisper"
    T3_TELEGRAM_RELAY   = "T3_telegram_relay"
    T4_SKYVERN_SURGICAL = "T4_skyvern_surgical"


@dataclass
class ResolveResult:
    solved:        bool
    tier_used:     Tier | None
    duration_ms:   int
    fallback_to:   Tier | None = None
    error:         str | None  = None
    artefact:      str | None  = None       # answer text, surgical alt path, etc.


# ────────────────────────────────────────────────────────────────────────────
# Adapter — the real "look at the page and extract image/audio" glue
# (concrete impl lives on the worker dyno).  Methods may return None if the
# corresponding artefact is not present on the current page.
# ────────────────────────────────────────────────────────────────────────────
class CaptchaPageAdapter:
    async def grab_image_bytes(self, page) -> bytes | None:
        """Screenshot of the CAPTCHA image grid, or None if not detected."""
        return None

    async def grab_audio_bytes(self, page) -> bytes | None:
        """MP3 bytes of the audio challenge, or None if not detected."""
        return None

    async def submit_text(self, page, answer: str) -> bool:
        """Type `answer` into the response field and submit."""
        return False

    async def click_audio_button(self, page) -> bool:
        """Switch to audio challenge mode."""
        return False


# ────────────────────────────────────────────────────────────────────────────
# T1 — Gemini 2.5 Flash vision
# ────────────────────────────────────────────────────────────────────────────
async def _solve_with_gemini_vision(image_bytes: bytes) -> str | None:
    """Returns the textual answer the user should type, or None on failure."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.debug("captcha.t1_skip — GEMINI_API_KEY not set")
        return None

    try:
        import aiohttp                                                # type: ignore
    except Exception:                                                # noqa: BLE001
        log.warning("captcha.t1_no_aiohttp")
        return None

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{STACK.gemini_flash}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": (
                    "You are solving a reCAPTCHA image grid.  The user will be "
                    "shown 9 images and asked to select all matching a label.  "
                    "Look at the attached screenshot, infer the label and the "
                    "matching tile coordinates as a comma-separated list of "
                    "row,col pairs (1-indexed).  If it's a text CAPTCHA, return "
                    "ONLY the characters.  Reply with the answer ONLY."
                )},
                {"inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(image_bytes).decode(),
                }},
            ],
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 64},
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, timeout=20) as r:
                data = await r.json()
        text = (
            data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
        )
        return text or None
    except Exception as e:                                           # noqa: BLE001
        log.warning("captcha.t1_err err=%s", e)
        return None


# ────────────────────────────────────────────────────────────────────────────
# T2 — Groq Whisper Large v3 (audio CAPTCHA)
# ────────────────────────────────────────────────────────────────────────────
async def _solve_with_groq_whisper(audio_bytes: bytes) -> str | None:
    if not audio_bytes:
        return None
    try:
        from groq import AsyncGroq                                    # type: ignore
    except Exception:                                                # noqa: BLE001
        log.warning("captcha.t2_no_groq")
        return None
    try:
        client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
        resp = await client.audio.transcriptions.create(
            model = STACK.groq_whisper,
            file  = ("captcha.mp3", audio_bytes, "audio/mpeg"),
            response_format = "text",
            language = "en",
        )
        text = (resp if isinstance(resp, str) else resp.text).strip()  # type: ignore
        # Audio CAPTCHAs return digits / words separated by spaces — drop
        # punctuation and trailing fillers.
        text = "".join(c for c in text if c.isalnum() or c == " ").strip()
        return text or None
    except Exception as e:                                           # noqa: BLE001
        log.warning("captcha.t2_err err=%s", e)
        return None


# ────────────────────────────────────────────────────────────────────────────
# T3 — Telegram human relay (45 s window)
# ────────────────────────────────────────────────────────────────────────────
class TelegramRelay:
    """
    Hub for in-flight T3 challenges keyed by challenge_id.  The Telegram
    dashboard registers a callback handler that calls
    `telegram_relay_response(challenge_id, answer)` to resolve the future.
    """

    def __init__(self):
        self._waiters: dict[str, asyncio.Future[str]] = {}

    def open_challenge(self) -> tuple[str, asyncio.Future[str]]:
        cid = uuid.uuid4().hex[:10]
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._waiters[cid] = fut
        return cid, fut

    def close_challenge(self, cid: str) -> None:
        self._waiters.pop(cid, None)

    def deliver(self, cid: str, answer: str) -> bool:
        fut = self._waiters.get(cid)
        if fut is None or fut.done():
            return False
        fut.set_result(answer)
        return True


async def _solve_with_telegram(
    relay:      TelegramRelay,
    notifier:   Callable[[str, bytes | None, str], Awaitable[None]] | None,
    image_bytes: bytes | None,
    portal:     str,
    job_id:     str,
) -> tuple[str | None, str]:
    """Returns (answer_or_none, challenge_id)."""
    cid, fut = relay.open_challenge()
    try:
        if notifier is not None:
            await notifier(cid, image_bytes, f"{portal}:{job_id}")
        try:
            answer = await asyncio.wait_for(
                fut, timeout=CAPTCHA_TELEGRAM_TIMEOUT_SEC,
            )
            return answer, cid
        except asyncio.TimeoutError:
            return None, cid
    finally:
        relay.close_challenge(cid)


# ────────────────────────────────────────────────────────────────────────────
# T4 — Skyvern surgical_fallback (alt-path detection)
# ────────────────────────────────────────────────────────────────────────────
async def _solve_with_surgical_fallback(page, portal: str, job_url: str) -> bool:
    try:
        from agents.n01_skyvern_apply import skyvern_surgical_fallback
    except Exception:                                                # noqa: BLE001
        return False
    return await skyvern_surgical_fallback(page, portal, job_url)


# ────────────────────────────────────────────────────────────────────────────
# Resolver — orchestrates the four tiers
# ────────────────────────────────────────────────────────────────────────────
class CaptchaResolver:
    """
    Orchestrator that walks T1 → T2 → T3 → T4 until one succeeds, persists
    every attempt to `captcha_events`, and returns a single ResolveResult.

    Required `db` methods:
        async def log_captcha_event(
            job_id, portal, tier, method, duration_ms, solved, fallback_to
        ) -> None
    """

    def __init__(
        self,
        db,
        adapter:    CaptchaPageAdapter,
        relay:      TelegramRelay | None = None,
        telegram_notifier: Callable[[str, bytes | None, str], Awaitable[None]] | None = None,
    ):
        self.db                = db
        self.adapter           = adapter
        self.relay             = relay or TelegramRelay()
        self.telegram_notifier = telegram_notifier

    # ---- main entry --------------------------------------------------------
    async def resolve(
        self,
        page,
        portal: str,
        job_id: str,
        job_url: str = "",
    ) -> ResolveResult:
        chain: list[Tier] = []
        t_total = time.monotonic()

        # T1 — Gemini vision
        chain.append(Tier.T1_GEMINI_VISION)
        ok, art, ms = await self._try_t1(page)
        await self._log(job_id, portal, Tier.T1_GEMINI_VISION,
                        method="gemini_vision", duration_ms=ms,
                        solved=ok, fallback_to=None if ok else Tier.T2_GROQ_WHISPER)
        if ok:
            return self._wrap(ok=True, tier=Tier.T1_GEMINI_VISION,
                              t0=t_total, artefact=art)

        # T2 — Groq Whisper
        ok, art, ms = await self._try_t2(page)
        await self._log(job_id, portal, Tier.T2_GROQ_WHISPER,
                        method="groq_whisper", duration_ms=ms,
                        solved=ok, fallback_to=None if ok else Tier.T3_TELEGRAM_RELAY)
        if ok:
            return self._wrap(ok=True, tier=Tier.T2_GROQ_WHISPER,
                              t0=t_total, artefact=art,
                              fallback_to=Tier.T2_GROQ_WHISPER)

        # T3 — Telegram relay
        ok, art, ms = await self._try_t3(page, portal, job_id)
        await self._log(job_id, portal, Tier.T3_TELEGRAM_RELAY,
                        method="telegram_relay", duration_ms=ms,
                        solved=ok, fallback_to=None if ok else Tier.T4_SKYVERN_SURGICAL)
        if ok:
            return self._wrap(ok=True, tier=Tier.T3_TELEGRAM_RELAY,
                              t0=t_total, artefact=art,
                              fallback_to=Tier.T3_TELEGRAM_RELAY)

        # T4 — Skyvern surgical_fallback
        ok, ms = await self._try_t4(page, portal, job_url)
        await self._log(job_id, portal, Tier.T4_SKYVERN_SURGICAL,
                        method="skyvern_surgical", duration_ms=ms,
                        solved=ok, fallback_to=None)
        return self._wrap(
            ok=ok, tier=Tier.T4_SKYVERN_SURGICAL if ok else None,
            t0=t_total, artefact="alt_path" if ok else None,
            fallback_to=Tier.T4_SKYVERN_SURGICAL if ok else None,
            error=None if ok else "all_tiers_exhausted",
        )

    # ---- T1 ---------------------------------------------------------------
    async def _try_t1(self, page) -> tuple[bool, str | None, int]:
        t0 = time.monotonic()
        img = await self.adapter.grab_image_bytes(page)
        if img is None:
            return False, None, int((time.monotonic() - t0) * 1000)
        answer = await _solve_with_gemini_vision(img)
        if not answer:
            return False, None, int((time.monotonic() - t0) * 1000)
        ok = await self.adapter.submit_text(page, answer)
        return ok, answer if ok else None, int((time.monotonic() - t0) * 1000)

    # ---- T2 ---------------------------------------------------------------
    async def _try_t2(self, page) -> tuple[bool, str | None, int]:
        t0 = time.monotonic()
        # Switch to audio mode if needed
        await self.adapter.click_audio_button(page)
        audio = await self.adapter.grab_audio_bytes(page)
        if audio is None:
            return False, None, int((time.monotonic() - t0) * 1000)
        answer = await _solve_with_groq_whisper(audio)
        if not answer:
            return False, None, int((time.monotonic() - t0) * 1000)
        ok = await self.adapter.submit_text(page, answer)
        return ok, answer if ok else None, int((time.monotonic() - t0) * 1000)

    # ---- T3 ---------------------------------------------------------------
    async def _try_t3(self, page, portal: str, job_id: str) -> tuple[bool, str | None, int]:
        t0 = time.monotonic()
        img = await self.adapter.grab_image_bytes(page)
        answer, cid = await _solve_with_telegram(
            self.relay, self.telegram_notifier, img, portal, job_id,
        )
        if not answer:
            return False, None, int((time.monotonic() - t0) * 1000)
        ok = await self.adapter.submit_text(page, answer)
        return ok, f"cid={cid}", int((time.monotonic() - t0) * 1000)

    # ---- T4 ---------------------------------------------------------------
    async def _try_t4(self, page, portal: str, job_url: str) -> tuple[bool, int]:
        t0 = time.monotonic()
        ok = await _solve_with_surgical_fallback(page, portal, job_url)
        return ok, int((time.monotonic() - t0) * 1000)

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _wrap(
        ok:           bool,
        tier:         Tier | None,
        t0:           float,
        artefact:     str | None     = None,
        fallback_to:  Tier | None    = None,
        error:        str | None     = None,
    ) -> ResolveResult:
        return ResolveResult(
            solved      = ok,
            tier_used   = tier,
            duration_ms = int((time.monotonic() - t0) * 1000),
            artefact    = artefact,
            fallback_to = fallback_to,
            error       = error,
        )

    async def _log(
        self,
        job_id:       str,
        portal:       str,
        tier:         Tier,
        method:       str,
        duration_ms:  int,
        solved:       bool,
        fallback_to:  Tier | None,
    ) -> None:
        try:
            await self.db.log_captcha_event(
                job_id      = job_id,
                portal      = portal,
                tier        = tier.value,
                method      = method,
                duration_ms = duration_ms,
                solved      = solved,
                fallback_to = fallback_to.value if fallback_to else None,
            )
        except Exception as e:                                       # noqa: BLE001
            log.warning("captcha.log_fail err=%s", e)


# ────────────────────────────────────────────────────────────────────────────
# Null adapter + in-memory captcha event log — for tests
# ────────────────────────────────────────────────────────────────────────────
class NullCaptchaAdapter(CaptchaPageAdapter):
    pass


class InMemoryCaptchaDB:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    async def log_captcha_event(self, **kwargs) -> None:
        kwargs["created_at"] = datetime.now(timezone.utc).isoformat()
        self.events.append(kwargs)


__all__ = [
    "Tier",
    "ResolveResult",
    "CaptchaResolver",
    "CaptchaPageAdapter",
    "NullCaptchaAdapter",
    "TelegramRelay",
    "InMemoryCaptchaDB",
]
