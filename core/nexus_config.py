"""
NEXUS v0.2 — Central Configuration
===================================
Single source of truth for portal limits, scoring weights, risk thresholds,
apply windows, decay curves, and stack endpoints.

Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Nothing in this module reaches out to the network. It is read-only data
imported by every other layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


# ────────────────────────────────────────────────────────────────────────────
# 0. Identity & Environment
# ────────────────────────────────────────────────────────────────────────────
NEXUS_VERSION       = "0.2.0"
USER_HANDLE         = os.getenv("NEXUS_USER_HANDLE", "abuzar_salim")
DEFAULT_TIMEZONE    = "Asia/Kolkata"
ENVIRONMENT         = os.getenv("NEXUS_ENV", "production")          # production | staging | dev


# ────────────────────────────────────────────────────────────────────────────
# 1. Stack Endpoints  (verified April 2026 — Gemini 2.0 Flash retired Mar 3 2026)
# ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StackEndpoints:
    # Gemini family — used per-project, multi-key pool
    gemini_flash       : str = "gemini-2.5-flash"
    gemini_flash_lite  : str = "gemini-2.5-flash-lite"
    gemini_pro         : str = "gemini-2.5-pro"

    # Groq (LLM extraction + embeddings + Whisper)
    groq_llm           : str = "llama-3.3-70b-versatile"
    groq_whisper       : str = "whisper-large-v3"
    groq_embed         : str = "text-embedding-3-large"   # 1024 dims via Groq endpoint

    # Cerebras (custom answer generation)
    cerebras_llm       : str = "llama-3.3-70b"

    # Supabase
    supabase_url       : str = os.getenv("SUPABASE_URL", "")
    supabase_anon_key  : str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # Cloudflare relay worker (Layer 0 IP continuity)
    cf_worker_url      : str = os.getenv("CF_RELAY_WORKER_URL", "")

    # Render keep-alive
    render_keepalive_url: str = os.getenv("RENDER_KEEPALIVE_URL", "")

    # Telegram
    telegram_bot_token : str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id   : str = os.getenv("TELEGRAM_CHAT_ID", "")


STACK = StackEndpoints()


# ────────────────────────────────────────────────────────────────────────────
# 2. Portals (the 11 supported portals)
# ────────────────────────────────────────────────────────────────────────────
SUPPORTED_PORTALS: tuple[str, ...] = (
    "linkedin",
    "internshala",
    "naukri",
    "iimjobs",
    "unstop",
    "wellfound",
    "indeed",
    "ycombinator",
    "instahyre",
    "shine",
    "timesjobs",
)


# ────────────────────────────────────────────────────────────────────────────
# 3. Risk Governor — pre-emptive throttle thresholds
#    (Layer 6 — prevents bans BEFORE they happen)
# ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PortalRiskProfile:
    portal               : str
    max_apps_per_hour    : int
    max_apps_per_day     : int
    captcha_rate_throttle: float = 0.15        # >15% CAPTCHA = throttle 50%
    error_rate_pause     : float = 0.10        # >10% errors in last 20 = pause
    session_age_warn_days: int   = 60
    decay_curve          : Literal["linear_90d", "steep_30d"] = "linear_90d"


PORTAL_RISK: dict[str, PortalRiskProfile] = {
    "linkedin":    PortalRiskProfile("linkedin",     max_apps_per_hour=8,  max_apps_per_day=40, decay_curve="linear_90d"),
    "internshala": PortalRiskProfile("internshala",  max_apps_per_hour=15, max_apps_per_day=80, decay_curve="steep_30d"),
    "naukri":      PortalRiskProfile("naukri",       max_apps_per_hour=12, max_apps_per_day=60, decay_curve="steep_30d"),
    "iimjobs":     PortalRiskProfile("iimjobs",      max_apps_per_hour=10, max_apps_per_day=40),
    "unstop":      PortalRiskProfile("unstop",       max_apps_per_hour=12, max_apps_per_day=50),
    "wellfound":   PortalRiskProfile("wellfound",    max_apps_per_hour=10, max_apps_per_day=30),
    "indeed":      PortalRiskProfile("indeed",       max_apps_per_hour=12, max_apps_per_day=50),
    "ycombinator": PortalRiskProfile("ycombinator",  max_apps_per_hour=6,  max_apps_per_day=20),
    "instahyre":   PortalRiskProfile("instahyre",    max_apps_per_hour=10, max_apps_per_day=40),
    "shine":       PortalRiskProfile("shine",        max_apps_per_hour=12, max_apps_per_day=50),
    "timesjobs":   PortalRiskProfile("timesjobs",    max_apps_per_hour=12, max_apps_per_day=50),
}


# ────────────────────────────────────────────────────────────────────────────
# 4. Apply-Window Intelligence (Innovation 6 — when to submit)
#    Times are local IST.  None = any time.
# ────────────────────────────────────────────────────────────────────────────
APPLY_WINDOWS: dict[str, list[tuple[str, str]] | None] = {
    "linkedin":    [("07:00", "11:00"), ("15:00", "19:00")],   # peak recruiter visibility
    "naukri":      [("09:00", "13:00")],
    "internshala": None,                                       # any time
    "iimjobs":     [("09:00", "18:00")],
    "unstop":      None,
    "wellfound":   [("19:00", "23:00")],                       # US founders' working hours
    "indeed":      [("09:00", "18:00")],
    "ycombinator": [("19:00", "23:00")],
    "instahyre":   [("09:00", "18:00")],
    "shine":       [("09:00", "18:00")],
    "timesjobs":   [("09:00", "18:00")],
}


# ────────────────────────────────────────────────────────────────────────────
# 5. Reactive discovery sources (RSS / webhook — Layer 2)
# ────────────────────────────────────────────────────────────────────────────
REACTIVE_SOURCES: dict[str, dict] = {
    "linkedin":    {"mode": "rss",            "url_template": "https://www.linkedin.com/jobs/search-results-rss/?keywords={kw}"},
    "internshala": {"mode": "rss",            "url_template": "https://internshala.com/internships/feed"},
    "naukri":      {"mode": "browser_watch",  "url_template": "https://www.naukri.com/mnjuser/recommendedjobs"},
}


# ────────────────────────────────────────────────────────────────────────────
# 6. Scoring (9-dimension weights — Layer 3)
# ────────────────────────────────────────────────────────────────────────────
SCORING_WEIGHTS: dict[str, float] = {
    "profile_match":    0.22,    # pgvector cosine
    "compensation_fit": 0.10,
    "role_type_match":  0.12,
    "company_tier":     0.10,
    "location_fit":     0.06,
    "recency":          0.08,
    "competitive_pos":  0.10,    # Innovation 7
    "cultural_fit":     0.10,    # NEW v0.2
    "trajectory":       0.12,    # NEW v0.2 — real-time news intel
}
assert abs(sum(SCORING_WEIGHTS.values()) - 1.0) < 1e-6, "Scoring weights must sum to 1.0"

ROUTING_THRESHOLDS = {
    "AUTO_APPLY_PRIORITY": 80,
    "AUTO_APPLY_DIGEST":   60,
    "MANUAL_REVIEW":       40,
    # below 40 → REJECT
}

# Innovation 7 — Competitive Position
APPLICANT_COUNT_GATES = {
    "fresh_bonus_under":     50,    # <50 applicants → +urgency bonus
    "saturated_penalty_over": 500,  # >500 applicants → penalty unless profile_match > 85
    "saturated_match_floor":  85,
}

# Innovation 11 — Deadline Cliffs / FOMO
DEADLINE_CLIFFS = [
    {"hours_before":  72, "score_bonus": 15, "elevate_priority": True},
    {"hours_before":  24, "score_bonus": 25, "elevate_priority": True, "ignore_window": True},
    {"hours_before":   6, "score_bonus":  0, "manual_confirm": True},
]


# ────────────────────────────────────────────────────────────────────────────
# 7. Answer RAG (Layer 4)
# ────────────────────────────────────────────────────────────────────────────
ANSWER_RAG = {
    "top_k":                  3,
    "min_word_count":         100,
    "max_word_count":         180,
    "banned_phrases": [
        "i am passionate about",
        "i am highly motivated",
        "as a recent graduate",
        "to whom it may concern",
        "i believe i am the perfect fit",
    ],
    "must_include_company":   True,
    "embedding_dim":          1024,
}


# ────────────────────────────────────────────────────────────────────────────
# 8. CAPTCHA Resolver tiers (Layer 5)
# ────────────────────────────────────────────────────────────────────────────
CAPTCHA_TIERS = ["T1_gemini_vision", "T2_groq_whisper", "T3_telegram_relay", "T4_skyvern_surgical"]
CAPTCHA_TELEGRAM_TIMEOUT_SEC = 45


# ────────────────────────────────────────────────────────────────────────────
# 9. Stealth Warmup (Innovation 10)
# ────────────────────────────────────────────────────────────────────────────
STEALTH_WARMUP = {
    "feed_scroll_minutes":     (2, 4),     # range — random within
    "feed_posts_to_read":      (8, 12),
    "company_pages_to_view":   (2, 3),
    "skip_after_recent_apply_min": 30,     # if applied < 30 min ago, skip warmup
}


# ────────────────────────────────────────────────────────────────────────────
# 10. Resume Variants (Innovation 8)
# ────────────────────────────────────────────────────────────────────────────
RESUME_VARIANTS = ("ai_tech", "finance", "ib", "generalist")
RESUME_ROUTING = {
    # role classifier output → resume variant
    "data_science":       "ai_tech",
    "ml_engineer":        "ai_tech",
    "product_analyst":    "ai_tech",
    "finance_analyst":    "finance",
    "investment_banking": "finance",
    "consulting":         "ib",
    "supply_chain":       "ib",
    "international_trade":"ib",
    "general_management": "generalist",
    "operations":         "generalist",
}


# ────────────────────────────────────────────────────────────────────────────
# 11. Skyvern code-cache policy (Innovation 2)
# ────────────────────────────────────────────────────────────────────────────
SKYVERN_CODE_CACHE = {
    "min_success_before_cache_use": 1,
    "fail_streak_invalidate":       3,        # 3 fails in a row → drop cache, regenerate via AI mode
    "force_refresh_after_days":     30,       # weekly refresh of cached code even if working
}


# ────────────────────────────────────────────────────────────────────────────
# 12. Salary Normaliser (Innovation 13)
# ────────────────────────────────────────────────────────────────────────────
SALARY_NORMALISER = {
    "min_stipend_inr_monthly":  20000,        # filter floor
    "default_currency":         "INR",
    "usd_to_inr":               83.0,         # static fallback; LLM normaliser preferred
    "ctc_to_inhand_factor":     0.78,         # India avg
}


# ────────────────────────────────────────────────────────────────────────────
# 13. Interview Intelligence (Layer 8)
# ────────────────────────────────────────────────────────────────────────────
INTERVIEW_INTEL = {
    "briefing_target_seconds":     90,
    "likely_questions_count":      8,
    "follow_up_unviewed_days":     14,        # Innovation 12 — applied-but-not-viewed
    "subject_classes": ("INTERVIEW_INVITE", "REJECTION", "TEST_LINK", "OFFER", "GENERIC"),
}


# ────────────────────────────────────────────────────────────────────────────
# 14. Orchestrator cadence
# ────────────────────────────────────────────────────────────────────────────
ORCHESTRATOR = {
    "queue_tick_minutes":          15,
    "rescore_interval_hours":       2,
    "session_oracle_tick_minutes":  10,
    "risk_governor_tick_minutes":   5,
    "max_concurrent_applies":       2,
    "retry_max":                    3,
    "retry_backoff_seconds":       (30, 90, 300),
}


# ────────────────────────────────────────────────────────────────────────────
# 15. Helper accessors
# ────────────────────────────────────────────────────────────────────────────
def portal_supported(portal: str) -> bool:
    return portal in SUPPORTED_PORTALS


def risk_profile(portal: str) -> PortalRiskProfile:
    if portal not in PORTAL_RISK:
        raise KeyError(f"Unknown portal: {portal}")
    return PORTAL_RISK[portal]


def is_apply_window_open(portal: str, now_hhmm: str) -> bool:
    """now_hhmm in 24h IST format e.g. '14:30'."""
    spec = APPLY_WINDOWS.get(portal)
    if spec is None:                       # any time
        return True
    return any(start <= now_hhmm < end for start, end in spec)


# ────────────────────────────────────────────────────────────────────────────
# 16. Convenience aliases — keep doc/Layer 9 dashboard wiring frictionless
# ────────────────────────────────────────────────────────────────────────────
# `core.telegram_dashboard` imports these short names directly from the
# architecture doc. They are aliases over the canonical objects defined above
# so that nothing else has to change.
PORTALS             = SUPPORTED_PORTALS
TELEGRAM_BOT_TOKEN  = STACK.telegram_bot_token or os.getenv("TG_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = STACK.telegram_chat_id   or os.getenv("TG_CHAT_ID",   "")


__all__ = [
    "NEXUS_VERSION", "USER_HANDLE", "DEFAULT_TIMEZONE", "ENVIRONMENT",
    "STACK", "SUPPORTED_PORTALS", "PORTALS",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "PORTAL_RISK", "PortalRiskProfile",
    "APPLY_WINDOWS", "REACTIVE_SOURCES",
    "SCORING_WEIGHTS", "ROUTING_THRESHOLDS",
    "APPLICANT_COUNT_GATES", "DEADLINE_CLIFFS",
    "ANSWER_RAG", "CAPTCHA_TIERS", "CAPTCHA_TELEGRAM_TIMEOUT_SEC",
    "STEALTH_WARMUP", "RESUME_VARIANTS", "RESUME_ROUTING",
    "SKYVERN_CODE_CACHE", "SALARY_NORMALISER", "INTERVIEW_INTEL",
    "ORCHESTRATOR",
    "portal_supported", "risk_profile", "is_apply_window_open",
]
