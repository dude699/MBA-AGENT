"""
NEXUS v0.2 — Layer M: The 15 Differentiator Innovations
================================================================================

This module consolidates the **15 innovations** that separate NEXUS from a
generic mass-applier. Some are pure functions, some are async helpers that
plug into other layers via callbacks.

Every innovation is referenced by number from the architecture doc:

   1. Skyvern Code Cache             → handled in core/stealth_triad.py + n01
   2. First-Apply Code Crystallisation → handled in agents/n02_browser_use_apply.py
   3. Cryptographic Session Vault    → handled in core/session_vault.py
   4. Session Freshness Oracle       → handled in core/session_vault.py
   5. Reactive Discovery Layer       → handled in core/reactive_discovery.py
   6. Trajectory Scoring             → THIS MODULE (TrajectoryScorer)
   7. Applicant-Count Estimator       → THIS MODULE (ApplicantCountEstimator)
   8. Multi-Resume Variant Routing   → handled in scoring + pgvector_matcher
   9. Portal Quality Benchmarking    → THIS MODULE (PortalBenchmark)
  10. Stealth Warmup Period          → THIS MODULE (StealthWarmup)
  11. Deadline Cliff / FOMO Override → THIS MODULE (DeadlineCliff)
  12. Applied-But-Not-Viewed Loop    → THIS MODULE (FollowupSweeper)
  13. Salary Normaliser              → handled in core/crawl4ai_discovery.py
  14. Cold-Start Bypass              → THIS MODULE (ColdStartBypass)
  15. Employer-Perspective Scoring   → THIS MODULE (EmployerPerspectiveScorer)

All classes are pure-Python with optional async LLM hooks; nothing here
crashes if external APIs are unavailable — every method falls back to a
neutral / safe default so the orchestrator never wedges.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Tuple

# Soft-import config — innovations.py degrades gracefully if any constant is
# absent so the module is robust against config schema drift.
try:
    from core.nexus_config import (
        APPLICANT_COUNT_GATES,
        DEADLINE_CLIFFS as _CFG_DEADLINE_CLIFFS,
        SCORING_WEIGHTS as _CFG_SCORING_WEIGHTS,
        STEALTH_WARMUP as _CFG_STEALTH_WARMUP,
    )
except Exception:  # pragma: no cover
    APPLICANT_COUNT_GATES = {}
    _CFG_DEADLINE_CLIFFS = []
    _CFG_SCORING_WEIGHTS = {}
    _CFG_STEALTH_WARMUP = {}

# Optional / forward-looking knobs — supplied as defaults if absent in config
try:
    from core.nexus_config import TRAJECTORY_THRESHOLDS  # type: ignore
except Exception:  # pragma: no cover
    TRAJECTORY_THRESHOLDS = {"rising": 0.25, "declining": -0.25}

# Convenience aliases used throughout this module
SCORING_WEIGHTS = _CFG_SCORING_WEIGHTS
STEALTH_WARMUP = _CFG_STEALTH_WARMUP

logger = logging.getLogger(__name__)


# ============================================================================
#  Innovation 6 — Trajectory Scoring
#  (Crawl4AI of news + Cerebras sentiment → -1..+1 → 0..100 axis)
# ============================================================================

class CrawlerProto(Protocol):
    async def fetch_news(self, company: str, days: int = 90) -> List[str]: ...


class SentimentProto(Protocol):
    async def aggregate(self, texts: List[str]) -> float:
        """Return aggregate sentiment in [-1.0, +1.0]."""
        ...


@dataclass
class TrajectorySignal:
    company: str
    headlines: int
    sentiment: float          # -1..+1
    score: float              # 0..100
    direction: str            # rising / steady / declining


class TrajectoryScorer:
    """
    Innovation 6 — Scores company trajectory by sentiment over recent news.

    Why it matters:
      Two companies with the same role can have wildly different career upside.
      A unicorn that just laid off 30% of staff is a worse bet than a Series B
      that just announced a $40M round, even if the JD looks identical.
    """

    def __init__(self, crawler: CrawlerProto, sentiment: SentimentProto) -> None:
        self.crawler = crawler
        self.sentiment = sentiment

    async def score(self, company: str, days: int = 90) -> TrajectorySignal:
        try:
            headlines = await self.crawler.fetch_news(company, days=days)
        except Exception:
            logger.exception("trajectory: news fetch failed for %s", company)
            headlines = []

        if not headlines:
            return TrajectorySignal(company=company, headlines=0, sentiment=0.0, score=60.0, direction="steady")

        try:
            sent = float(await self.sentiment.aggregate(headlines))
        except Exception:
            logger.exception("trajectory: sentiment failed for %s", company)
            sent = 0.0

        sent = max(-1.0, min(1.0, sent))
        # Map [-1, +1] → [20, 100] with neutral=60
        score = round(60.0 + sent * 40.0, 1)

        rising_thr = TRAJECTORY_THRESHOLDS.get("rising", 0.25)
        declining_thr = TRAJECTORY_THRESHOLDS.get("declining", -0.25)
        if sent >= rising_thr:
            direction = "rising"
        elif sent <= declining_thr:
            direction = "declining"
        else:
            direction = "steady"

        return TrajectorySignal(
            company=company,
            headlines=len(headlines),
            sentiment=sent,
            score=score,
            direction=direction,
        )


# ============================================================================
#  Innovation 7 — Applicant-Count Estimator
#  (Where the portal gives no number, we estimate from posted_at + portal velocity)
# ============================================================================

@dataclass
class ApplicantEstimate:
    estimated: int
    confidence: float  # 0..1
    source: str        # exact / estimated / unknown


class ApplicantCountEstimator:
    """
    Innovation 7 — early-mover advantage signal.

    Models a simple Poisson-ish ramp:
      • Hot portals (LinkedIn) accumulate ~25 apps/hr in first 4 hr, then decay.
      • Slow portals (TimesJobs) ~3 apps/hr.
      • Niche (YC Workatastartup) ~1 apps/hr.

    Returns 0–100 score band:
      <  50 applicants → 95 score (early mover)
      < 100 applicants → 80
      < 250 applicants → 60
      < 500 applicants → 45
      ≥ 500 applicants → 30
    """

    PORTAL_VELOCITY_PER_HOUR = {
        "linkedin": 22.0,
        "internshala": 14.0,
        "naukri": 11.0,
        "indeed": 9.0,
        "wellfound": 4.0,
        "workatastartup": 1.5,
        "ycombinator": 1.5,
        "monster": 5.0,
        "shine": 6.0,
        "foundit": 5.0,
        "timesjobs": 3.0,
    }

    @classmethod
    def estimate(
        cls,
        portal: str,
        posted_at: Optional[datetime],
        exact_count: Optional[int] = None,
    ) -> ApplicantEstimate:
        if exact_count is not None and exact_count >= 0:
            return ApplicantEstimate(estimated=int(exact_count), confidence=1.0, source="exact")

        if posted_at is None:
            return ApplicantEstimate(estimated=200, confidence=0.2, source="unknown")

        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)

        hours = max(0.0, (datetime.now(timezone.utc) - posted_at).total_seconds() / 3600.0)
        v0 = cls.PORTAL_VELOCITY_PER_HOUR.get(portal.lower(), 6.0)

        # Decay curve: high velocity in first 6 hr, falls to 30% by 48 hr
        decay = math.exp(-hours / 30.0)
        effective = v0 * (0.3 + 0.7 * decay)
        estimated = int(round(effective * hours))

        # Confidence drops as posting ages past 7d
        confidence = max(0.2, 1.0 - hours / (24 * 14))
        return ApplicantEstimate(
            estimated=estimated,
            confidence=round(confidence, 2),
            source="estimated",
        )

    @staticmethod
    def to_score(estimated: int) -> float:
        """
        Maps applicant count → 0..100 score band (early-mover bonus).
        Honours nexus_config.APPLICANT_COUNT_GATES when shaped as a list of
        (threshold, score) tuples; otherwise uses a static fallback ladder.
        """
        ladder: List[Tuple[int, float]]
        gates = APPLICANT_COUNT_GATES
        if isinstance(gates, list):
            try:
                ladder = [(int(t), float(s)) for (t, s) in gates]
            except Exception:
                ladder = []
        else:
            # Dict shape from current nexus_config — translate to a ladder
            ladder = []
            try:
                if isinstance(gates, dict) and gates:
                    fresh = int(gates.get("fresh_bonus_under", 50))
                    ladder.append((fresh, 95.0))
                    saturated = int(gates.get("saturated_penalty_over", 500))
                    ladder.append((saturated, 50.0))
            except Exception:
                ladder = []
        if not ladder:
            ladder = [(50, 95.0), (100, 80.0), (250, 60.0), (500, 45.0)]

        for thr, score in ladder:
            if estimated < thr:
                return float(score)
        return 30.0


# ============================================================================
#  Innovation 9 — Portal Quality Benchmarking
#  (Live callback rate per portal → quality multiplier)
# ============================================================================

@dataclass
class PortalQuality:
    portal: str
    apps_30d: int
    callbacks_30d: int
    callback_rate: float    # 0..1
    quality_score: int      # 0..100
    multiplier: float       # 0.7..1.3 (used in cross-post tie-break)


class PortalHealthDB(Protocol):
    async def fetch_portal_funnel(self, portal: str, days: int = 30) -> Dict[str, int]: ...
    async def upsert_portal_quality(self, q: PortalQuality) -> None: ...


class PortalBenchmark:
    """
    Innovation 9 — Live portal quality benchmarking.

    Every 24 h, recomputes callback_rate per portal from applied_jobs +
    interview_signals (last 30 d). Feeds into Layer 7's pick_best_portal
    cross-post winner selection (PORTAL_QUALITY_DEFAULT is overridden by
    this live signal).
    """

    BASELINE = {
        "linkedin": 100,
        "wellfound": 90,
        "ycombinator": 95,
        "workatastartup": 95,
        "internshala": 85,
        "naukri": 80,
        "indeed": 80,
        "shine": 70,
        "foundit": 70,
        "monster": 65,
        "timesjobs": 50,
    }

    def __init__(self, db: PortalHealthDB) -> None:
        self.db = db

    async def benchmark(self, portal: str, days: int = 30) -> PortalQuality:
        try:
            f = await self.db.fetch_portal_funnel(portal, days=days)
        except Exception:
            logger.exception("PortalBenchmark: fetch failed for %s", portal)
            f = {}
        apps = int(f.get("applied", 0))
        cbacks = int(f.get("callbacks", 0))
        rate = (cbacks / apps) if apps > 0 else 0.0

        # 0% callback → 0.7×, 5% → 1.0×, 15% → 1.3×
        if rate <= 0.0:
            mult = 0.7
        elif rate >= 0.15:
            mult = 1.3
        else:
            mult = 0.7 + (rate / 0.15) * 0.6

        baseline = self.BASELINE.get(portal.lower(), 70)
        quality = int(round(baseline * mult))

        q = PortalQuality(
            portal=portal,
            apps_30d=apps,
            callbacks_30d=cbacks,
            callback_rate=round(rate, 3),
            quality_score=quality,
            multiplier=round(mult, 2),
        )
        try:
            await self.db.upsert_portal_quality(q)
        except Exception:
            logger.exception("PortalBenchmark: upsert failed.")
        return q


# ============================================================================
#  Innovation 10 — Stealth Warmup Period
#  (New session must accumulate human-pattern activity before any apply)
# ============================================================================

@dataclass
class WarmupPlan:
    portal: str
    duration_days: int
    daily_actions: int        # browse / search / save (no apply)
    idle_minutes_total: int


class StealthWarmup:
    """
    Innovation 10 — When a brand-new vault session lands, throttle activity:
      • Day 1-2: 6-10 browse actions, 0 applies.
      • Day 3:   20-30 browse + 1-2 apply.
      • Day 4+: full operating volume.

    Implementation just returns a plan; orchestrator multiplies its rate by
    the warmup_factor.
    """

    DEFAULT_FULL_DAYS = 3

    @staticmethod
    def _full_days() -> int:
        cfg = STEALTH_WARMUP or {}
        try:
            # Allow either a flat "days" key or a per-portal nested dict
            if "days" in cfg:
                return int(cfg["days"])
        except Exception:
            pass
        return StealthWarmup.DEFAULT_FULL_DAYS

    @classmethod
    def plan(cls, portal: str, session_age_days: float) -> Tuple[WarmupPlan, float]:
        full_days = cls._full_days()
        if session_age_days >= full_days:
            return (
                WarmupPlan(portal=portal, duration_days=full_days, daily_actions=0, idle_minutes_total=0),
                1.0,
            )
        # 0..1 ramp
        ramp = max(0.0, min(1.0, session_age_days / max(1, full_days)))
        factor = round(0.1 + ramp * 0.9, 2)
        plan = WarmupPlan(
            portal=portal,
            duration_days=full_days,
            daily_actions=int(8 + ramp * 22),
            idle_minutes_total=int(20 + (1 - ramp) * 80),
        )
        return plan, factor


# ============================================================================
#  Innovation 11 — Deadline Cliff / FOMO Override
#  (24h cliff bypasses apply window; 6h cliff requires manual confirm)
# ============================================================================

@dataclass
class CliffDecision:
    bonus: int                  # add to score
    ignore_apply_window: bool
    require_manual_confirm: bool
    label: str                  # "GREEN" / "AMBER" / "RED" / "OVER"


class DeadlineCliff:
    """
    Innovation 11 — Deadline urgency override.

    Reads thresholds from nexus_config.DEADLINE_CLIFFS:
        amber_hours: 72  → bonus +15
        red_hours:   24  → bonus +25, ignore_apply_window=True
        critical_hours: 6 → bonus +30, require_manual_confirm=True
    """

    # Default fallback ladder if config is empty or malformed
    DEFAULT_LADDER = [
        {"hours_before": 72, "score_bonus": 15, "elevate_priority": True, "label": "AMBER"},
        {"hours_before": 24, "score_bonus": 25, "elevate_priority": True,
         "ignore_window": True, "label": "RED"},
        {"hours_before":  6, "score_bonus": 30, "manual_confirm": True,
         "ignore_window": True, "label": "RED"},
    ]

    @classmethod
    def _ladder(cls) -> List[Dict[str, Any]]:
        cfg = _CFG_DEADLINE_CLIFFS or []
        if isinstance(cfg, list) and cfg:
            try:
                # Sort ascending by hours_before so we can scan small→large
                return sorted(cfg, key=lambda d: float(d.get("hours_before", 0)))
            except Exception:
                pass
        return list(cls.DEFAULT_LADDER)

    @classmethod
    def evaluate(cls, deadline_at: Optional[datetime]) -> CliffDecision:
        if deadline_at is None:
            return CliffDecision(bonus=0, ignore_apply_window=False, require_manual_confirm=False, label="GREEN")

        if deadline_at.tzinfo is None:
            deadline_at = deadline_at.replace(tzinfo=timezone.utc)

        hours = (deadline_at - datetime.now(timezone.utc)).total_seconds() / 3600.0
        if hours <= 0:
            return CliffDecision(bonus=-50, ignore_apply_window=False, require_manual_confirm=False, label="OVER")

        # Walk the ladder bottom-up: tightest cliff that still encompasses `hours`
        # wins (e.g. 5 hours triggers 6h cliff, not 24h cliff).
        ladder = cls._ladder()
        chosen: Optional[Dict[str, Any]] = None
        for cliff in ladder:
            try:
                if hours <= float(cliff.get("hours_before", 0)):
                    chosen = cliff
                    break
            except Exception:
                continue

        if chosen is None:
            return CliffDecision(bonus=0, ignore_apply_window=False, require_manual_confirm=False, label="GREEN")

        return CliffDecision(
            bonus=int(chosen.get("score_bonus", 0)),
            ignore_apply_window=bool(chosen.get("ignore_window", False)),
            require_manual_confirm=bool(chosen.get("manual_confirm", False)),
            label=str(chosen.get("label", "AMBER")),
        )


# ============================================================================
#  Innovation 12 — Applied-But-Not-Viewed Follow-Up Loop
#  (>14d unviewed → polite follow-up dispatch)
# ============================================================================

@dataclass
class FollowupCandidate:
    job_id: str
    portal: str
    company: str
    title: str
    days_since_apply: float
    contact_hint: Optional[str] = None  # e.g. recruiter linkedin from Layer 8


class FollowupDB(Protocol):
    async def fetch_unviewed_applications(self, threshold_days: int = 14) -> List[Dict[str, Any]]: ...
    async def mark_followup_sent(self, job_id: str) -> None: ...


class FollowupSweeper:
    """
    Innovation 12 — Sweeps applied_jobs JOIN interview_signals where
    no view/contact in `threshold_days`, emits FollowupCandidate batch.
    """

    def __init__(self, db: FollowupDB, threshold_days: int = 14) -> None:
        self.db = db
        self.threshold_days = threshold_days

    async def sweep(self) -> List[FollowupCandidate]:
        try:
            rows = await self.db.fetch_unviewed_applications(self.threshold_days)
        except Exception:
            logger.exception("FollowupSweeper: fetch failed.")
            return []
        out: List[FollowupCandidate] = []
        for r in rows:
            try:
                applied_at = r.get("applied_at")
                if isinstance(applied_at, str):
                    applied_at = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                if applied_at is None:
                    continue
                if applied_at.tzinfo is None:
                    applied_at = applied_at.replace(tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - applied_at).total_seconds() / 86400.0
                if days < self.threshold_days:
                    continue
                out.append(
                    FollowupCandidate(
                        job_id=str(r.get("job_id")),
                        portal=str(r.get("portal", "?")),
                        company=str(r.get("company", "?")),
                        title=str(r.get("title", "?")),
                        days_since_apply=round(days, 1),
                        contact_hint=r.get("contact_hint"),
                    )
                )
            except Exception:
                logger.exception("FollowupSweeper: row parse failed.")
        return out


# ============================================================================
#  Innovation 14 — Cold-Start Bypass
#  (No applied history? Seed scoring weights from public benchmarks for first 5 apps)
# ============================================================================

@dataclass
class ColdStartProfile:
    is_cold: bool
    apps_count: int
    bootstrap_weights: Dict[str, float]


class ColdStartBypass:
    """
    Innovation 14 — When applied_jobs has < 5 rows, the personal model has
    no signal yet. We:
      • Use BOOTSTRAP_WEIGHTS (heavier on compensation + role_match).
      • Apply a +10 score floor on tier-S companies (force initial swings).
      • Bypass employer-perspective scoring (Innovation 15) entirely.
    """

    BOOTSTRAP_WEIGHTS = {
        "role_match": 0.35,
        "compensation": 0.20,
        "location": 0.10,
        "recency": 0.10,
        "competitive_pos": 0.10,
        "company_tier": 0.10,
        "trajectory": 0.025,
        "cultural_fit": 0.025,
        "deadline_bonus": 0.0,
    }

    @classmethod
    def evaluate(cls, applied_history_count: int) -> ColdStartProfile:
        is_cold = applied_history_count < 5
        return ColdStartProfile(
            is_cold=is_cold,
            apps_count=applied_history_count,
            bootstrap_weights=dict(cls.BOOTSTRAP_WEIGHTS) if is_cold else dict(SCORING_WEIGHTS),
        )

    @staticmethod
    def tier_floor(company_tier: str, raw_score: float) -> float:
        if company_tier in {"TIER_S"}:
            return max(raw_score, 70.0)
        return raw_score


# ============================================================================
#  Innovation 15 — Employer-Perspective Scoring
#  (Will THEY say yes? Estimate fit from THEIR side, not just ours.)
# ============================================================================

@dataclass
class EmployerLens:
    likelihood_pct: float         # 0..100 — "they'd interview me"
    weak_signals: List[str]       # missing requirements
    strong_signals: List[str]     # matched requirements


class EmployerLLM(Protocol):
    async def reverse_score(self, jd_text: str, profile_text: str) -> Dict[str, Any]: ...


class EmployerPerspectiveScorer:
    """
    Innovation 15 — flips the scoring lens.

    Most scorers ask "Does this job fit me?" — wrong question.
    The recruiter asks "Does this candidate fit our role?".

    We send the JD + profile to an LLM with this exact instruction:
      "You are the recruiter for this role. Score this candidate 0-100
       on whether you would advance them to first-round interview.
       Return weak_signals (missing requirements) and strong_signals
       (clear matches)."

    Used as a multiplier on final_score: scores < 40 from THEIR side
    get capped at MANUAL_REVIEW band even if our side scored 95.
    """

    def __init__(self, llm: EmployerLLM) -> None:
        self.llm = llm

    async def evaluate(self, jd_text: str, profile_text: str) -> EmployerLens:
        try:
            raw = await self.llm.reverse_score(jd_text, profile_text)
        except Exception:
            logger.exception("EmployerPerspectiveScorer: LLM failed.")
            return EmployerLens(likelihood_pct=60.0, weak_signals=[], strong_signals=[])

        try:
            return EmployerLens(
                likelihood_pct=float(raw.get("likelihood_pct", 60.0)),
                weak_signals=list(raw.get("weak_signals", []))[:6],
                strong_signals=list(raw.get("strong_signals", []))[:6],
            )
        except Exception:
            return EmployerLens(likelihood_pct=60.0, weak_signals=[], strong_signals=[])

    @staticmethod
    def cap_for_employer_view(our_score: float, lens: EmployerLens) -> Tuple[float, str]:
        """
        Apply employer perspective as a soft cap:
          • lens<40 → cap at 79 (force MANUAL_REVIEW)
          • lens<25 → cap at 59 (force REJECT)
          • lens>75 → bonus +5 (they'd love us)
        """
        if lens.likelihood_pct < 25:
            return min(our_score, 59.0), "EMPLOYER_REJECT"
        if lens.likelihood_pct < 40:
            return min(our_score, 79.0), "EMPLOYER_WEAK"
        if lens.likelihood_pct > 75:
            return min(100.0, our_score + 5.0), "EMPLOYER_STRONG"
        return our_score, "EMPLOYER_NEUTRAL"


# ============================================================================
#  Composite "Innovation Pipeline" — single entry from orchestrator
# ============================================================================

@dataclass
class InnovationContext:
    portal: str
    posted_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    exact_applicant_count: Optional[int] = None
    company_tier: str = "TIER_B"
    session_age_days: float = 999.0     # default = warmed up
    applied_history_count: int = 100    # default = not cold


@dataclass
class InnovationOutput:
    applicant_estimate: ApplicantEstimate
    applicant_score: float
    cliff: CliffDecision
    cold: ColdStartProfile
    warmup_factor: float
    warmup_plan: WarmupPlan


def run_static_innovations(ctx: InnovationContext) -> InnovationOutput:
    """
    Cheap, sync, no-LLM innovations bundled in one call.
    Trajectory + EmployerPerspective are async + require LLM, kept separate.
    """
    est = ApplicantCountEstimator.estimate(ctx.portal, ctx.posted_at, ctx.exact_applicant_count)
    app_score = ApplicantCountEstimator.to_score(est.estimated)
    cliff = DeadlineCliff.evaluate(ctx.deadline_at)
    cold = ColdStartBypass.evaluate(ctx.applied_history_count)
    plan, factor = StealthWarmup.plan(ctx.portal, ctx.session_age_days)
    return InnovationOutput(
        applicant_estimate=est,
        applicant_score=app_score,
        cliff=cliff,
        cold=cold,
        warmup_factor=factor,
        warmup_plan=plan,
    )


__all__ = [
    # Innovation 6
    "TrajectoryScorer", "TrajectorySignal", "CrawlerProto", "SentimentProto",
    # Innovation 7
    "ApplicantCountEstimator", "ApplicantEstimate",
    # Innovation 9
    "PortalBenchmark", "PortalQuality", "PortalHealthDB",
    # Innovation 10
    "StealthWarmup", "WarmupPlan",
    # Innovation 11
    "DeadlineCliff", "CliffDecision",
    # Innovation 12
    "FollowupSweeper", "FollowupCandidate", "FollowupDB",
    # Innovation 14
    "ColdStartBypass", "ColdStartProfile",
    # Innovation 15
    "EmployerPerspectiveScorer", "EmployerLens", "EmployerLLM",
    # Composite
    "InnovationContext", "InnovationOutput", "run_static_innovations",
]
