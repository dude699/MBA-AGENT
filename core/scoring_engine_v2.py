"""
NEXUS v0.2 — Layer 3: Multi-Dimensional Intelligence Scoring (9 dimensions)
================================================================================
Author : MD Abuzar Salim · 25IBMMA143
Date   : April 2026

Upgraded from PRISM v0.1's 7 dims to 9 dims. New additions:
  • Cultural Fit  — LLM semantic match: company values vs profile.
  • Trajectory    — Crawl4AI news → Cerebras sentiment.

Output is one normalised final_score (0..100), a routing decision
(AUTO_APPLY / MANUAL_REVIEW / REJECT), and a full per-dimension breakdown
that gets stored in `job_scores`.

Heavy LLM calls are hidden behind small protocols so this module is
import-cheap on the slim Render dyno.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

from core.crawl4ai_discovery import NormalisedJob
from core.nexus_config import (
    APPLICANT_COUNT_GATES,
    DEADLINE_CLIFFS,
    RESUME_ROUTING,
    ROUTING_THRESHOLDS,
    SALARY_NORMALISER,
    SCORING_WEIGHTS,
)
from core.pgvector_matcher import ProfileMatcher

log = logging.getLogger("nexus.scoring")


# ────────────────────────────────────────────────────────────────────────────
# Helper protocols (LLM glue — concrete impl in core/ai_router.py later)
# ────────────────────────────────────────────────────────────────────────────
class TextClassifier(Protocol):
    """Groq llama-3.3-70b for role-type / cultural-fit classification."""
    async def classify(self, text: str, labels: list[str]) -> str: ...


class TrajectoryAnalyser(Protocol):
    """Crawl4AI news + Cerebras sentiment → -1..+1 trajectory."""
    async def trajectory(self, company: str) -> float: ...


# Pluggable LLM-shaped functions for cultural fit (returns 0..100 int)
CulturalFitFn = Callable[[NormalisedJob, dict[str, Any]], Awaitable[int]]


# ────────────────────────────────────────────────────────────────────────────
# Output dataclass
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class ScoreBreakdown:
    job_id:           str
    profile_match:    int
    compensation_fit: int
    role_type_match:  int
    company_tier:     int
    location_fit:     int
    recency:          int
    competitive_pos:  int
    cultural_fit:     int
    trajectory:       int
    final_score:      int
    routing:          str                 # AUTO_APPLY | MANUAL_REVIEW | REJECT
    bonuses:          dict[str, int]      = field(default_factory=dict)
    resume_variant:   str                 = "master"
    scored_at:        datetime            = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_db_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["scored_at"] = self.scored_at.isoformat()
        d["raw_breakdown"] = {
            "bonuses":        self.bonuses,
            "resume_variant": self.resume_variant,
        }
        return d


# ────────────────────────────────────────────────────────────────────────────
# Static dimension scorers (no LLM required)
# ────────────────────────────────────────────────────────────────────────────
def score_compensation(job: NormalisedJob, min_inr: int) -> int:
    if job.stipend_inr_monthly is None:
        return 60                                       # neutral when unknown
    if job.stipend_inr_monthly < min_inr:
        return 0
    # Linear above floor, cap at 2× min == 100
    ratio = job.stipend_inr_monthly / max(min_inr, 1)
    return min(100, int(round(50 + ratio * 25)))


def score_location(job: NormalisedJob, profile: dict[str, Any]) -> int:
    if job.remote:
        return 100
    preferred = {p.lower() for p in profile.get("preferred_cities", [])}
    if not job.location:
        return 60
    loc = job.location.lower()
    if any(c in loc for c in preferred):
        return 100
    if "india" in loc:
        return 80
    return 50


def score_recency(job: NormalisedJob, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    posted = job.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - posted).total_seconds() / 3600)
    # 100 at <1 hr, 80 at 24 hr, 50 at 72 hr, ~0 by 14 days
    if age_hours < 1:
        return 100
    if age_hours < 24:
        return 90
    if age_hours < 72:
        return 70
    if age_hours < 24 * 7:
        return 50
    if age_hours < 24 * 14:
        return 25
    return 5


def score_competitive_pos(job: NormalisedJob) -> tuple[int, str | None]:
    """
    Innovation 7 — Competitive Position Estimator.
    Returns (score, gate) where gate ∈ {None, 'fresh_bonus', 'saturated'}.
    """
    n = job.applicant_count
    if n is None:
        return 60, None
    if n < APPLICANT_COUNT_GATES["fresh_bonus_under"]:
        return 95, "fresh_bonus"
    if n > APPLICANT_COUNT_GATES["saturated_penalty_over"]:
        return 30, "saturated"
    # Smooth linear interp between the two gates
    lo = APPLICANT_COUNT_GATES["fresh_bonus_under"]
    hi = APPLICANT_COUNT_GATES["saturated_penalty_over"]
    frac = (n - lo) / max(1, hi - lo)
    return int(round(95 - frac * 65)), None


# ────────────────────────────────────────────────────────────────────────────
# Company tier — static + dynamic
# ────────────────────────────────────────────────────────────────────────────
TIER_S = {"mckinsey", "bcg", "bain", "google", "microsoft", "amazon", "goldman sachs",
          "morgan stanley", "jp morgan", "deloitte", "kpmg", "ey", "pwc", "accenture",
          "tata", "reliance", "tcs", "infosys", "wipro"}
TIER_A = {"meesho", "swiggy", "zomato", "razorpay", "cred", "phonepe", "paytm",
          "flipkart", "myntra", "ola", "uber", "byju", "unacademy", "upgrad",
          "icici", "hdfc", "axis", "kotak"}


def score_company_tier(job: NormalisedJob) -> int:
    name = job.company.lower()
    if any(t in name for t in TIER_S):
        return 100
    if any(t in name for t in TIER_A):
        return 80
    return 60


# ────────────────────────────────────────────────────────────────────────────
# Role-type classifier (Groq llama-3.3-70b)
# ────────────────────────────────────────────────────────────────────────────
ROLE_LABELS = list(RESUME_ROUTING.keys()) + ["other"]


async def classify_role_type(
    job: NormalisedJob,
    classifier: TextClassifier | None,
) -> tuple[str, int]:
    """Returns (role_label, role_type_match_score 0..100)."""
    if classifier is None:
        # Cheap regex fallback so the orchestrator works without an LLM.
        text = (job.title + " " + job.jd_text).lower()
        for label, _variant in RESUME_ROUTING.items():
            tokens = label.split("_")
            if all(re.search(rf"\b{re.escape(tok)}", text) for tok in tokens):
                return label, 80
        return "other", 50
    try:
        label = await classifier.classify(
            text=f"Title: {job.title}\nJD: {job.jd_text[:1000]}",
            labels=ROLE_LABELS,
        )
        return label, (85 if label != "other" else 40)
    except Exception as e:                                    # noqa: BLE001
        log.warning("scoring.role_classify_fail err=%s", e)
        return "other", 50


# ────────────────────────────────────────────────────────────────────────────
# Cultural-fit (LLM) — semantic match between company values + profile
# ────────────────────────────────────────────────────────────────────────────
async def score_cultural_fit(
    job:        NormalisedJob,
    profile:    dict[str, Any],
    fit_fn:     CulturalFitFn | None,
) -> int:
    if fit_fn is None:
        return 60                                             # neutral default
    try:
        return max(0, min(100, await fit_fn(job, profile)))
    except Exception as e:                                    # noqa: BLE001
        log.warning("scoring.cultural_fit_fail err=%s", e)
        return 60


# ────────────────────────────────────────────────────────────────────────────
# Trajectory — Crawl4AI + Cerebras sentiment, mapped -1..+1 → 0..100
# ────────────────────────────────────────────────────────────────────────────
async def score_trajectory(
    job: NormalisedJob,
    analyser: TrajectoryAnalyser | None,
) -> int:
    if analyser is None:
        return 60
    try:
        sentiment = await analyser.trajectory(job.company)    # -1..+1
        sentiment = max(-1.0, min(1.0, float(sentiment)))
        return int(round((sentiment + 1.0) / 2.0 * 100))
    except Exception as e:                                    # noqa: BLE001
        log.warning("scoring.trajectory_fail company=%s err=%s", job.company, e)
        return 60


# ────────────────────────────────────────────────────────────────────────────
# Deadline cliffs / FOMO bonus (Innovation 11)
# ────────────────────────────────────────────────────────────────────────────
def deadline_bonus(job: NormalisedJob, now: datetime | None = None) -> tuple[int, dict]:
    if not job.deadline:
        return 0, {}
    now = now or datetime.now(timezone.utc)
    dl = job.deadline if job.deadline.tzinfo else job.deadline.replace(tzinfo=timezone.utc)
    hours_to_deadline = (dl - now).total_seconds() / 3600
    if hours_to_deadline <= 0:
        return -50, {"reason": "expired"}
    # Pick the tightest cliff that still applies
    for cliff in sorted(DEADLINE_CLIFFS, key=lambda c: c["hours_before"]):
        if hours_to_deadline <= cliff["hours_before"]:
            return cliff["score_bonus"], {
                "hours_to_deadline":  round(hours_to_deadline, 1),
                "cliff":              cliff["hours_before"],
                "elevate_priority":   cliff.get("elevate_priority", False),
                "ignore_window":      cliff.get("ignore_window",   False),
                "manual_confirm":     cliff.get("manual_confirm",  False),
            }
    return 0, {"hours_to_deadline": round(hours_to_deadline, 1)}


# ────────────────────────────────────────────────────────────────────────────
# Routing
# ────────────────────────────────────────────────────────────────────────────
def route(final_score: int) -> str:
    if final_score >= ROUTING_THRESHOLDS["AUTO_APPLY_PRIORITY"]:
        return "AUTO_APPLY"
    if final_score >= ROUTING_THRESHOLDS["AUTO_APPLY_DIGEST"]:
        return "AUTO_APPLY"
    if final_score >= ROUTING_THRESHOLDS["MANUAL_REVIEW"]:
        return "MANUAL_REVIEW"
    return "REJECT"


# ────────────────────────────────────────────────────────────────────────────
# Engine
# ────────────────────────────────────────────────────────────────────────────
class ScoringEngine:
    def __init__(
        self,
        matcher:     ProfileMatcher,
        classifier:  TextClassifier | None        = None,
        cultural_fn: CulturalFitFn | None         = None,
        analyser:    TrajectoryAnalyser | None    = None,
    ):
        self.matcher     = matcher
        self.classifier  = classifier
        self.cultural_fn = cultural_fn
        self.analyser    = analyser

    async def score(
        self,
        job:     NormalisedJob,
        profile: dict[str, Any],
    ) -> ScoreBreakdown:
        # Variant routing first — Innovation 8.  We score against the BEST
        # variant rather than master, so a Finance JD doesn't get penalised
        # because the master profile leans IB.
        variant, variant_score = await self.matcher.best_variant(
            job.jd_text or job.title
        )
        profile_match = max(variant_score, 0)

        # Static / cheap dims
        compensation_fit = score_compensation(
            job, min_inr=profile.get("min_stipend",
                                     SALARY_NORMALISER["min_stipend_inr_monthly"])
        )
        location_fit = score_location(job, profile)
        recency      = score_recency(job)
        company_tier = score_company_tier(job)
        comp_pos, comp_gate = score_competitive_pos(job)

        # LLM dims
        role_label, role_type_match = await classify_role_type(job, self.classifier)
        cultural_fit = await score_cultural_fit(job, profile, self.cultural_fn)
        trajectory   = await score_trajectory(job, self.analyser)

        # Weighted final score
        weighted = (
            SCORING_WEIGHTS["profile_match"]    * profile_match    +
            SCORING_WEIGHTS["compensation_fit"] * compensation_fit +
            SCORING_WEIGHTS["role_type_match"]  * role_type_match  +
            SCORING_WEIGHTS["company_tier"]     * company_tier     +
            SCORING_WEIGHTS["location_fit"]     * location_fit     +
            SCORING_WEIGHTS["recency"]          * recency          +
            SCORING_WEIGHTS["competitive_pos"]  * comp_pos         +
            SCORING_WEIGHTS["cultural_fit"]     * cultural_fit     +
            SCORING_WEIGHTS["trajectory"]       * trajectory
        )
        final_score = int(round(weighted))

        # Bonuses (deadline cliffs, saturated penalty etc.)
        bonuses: dict[str, int] = {}
        d_bonus, d_meta = deadline_bonus(job)
        if d_bonus != 0:
            bonuses["deadline"] = d_bonus
            final_score += d_bonus

        # Innovation 7 saturated gate — only allow through if profile_match >= 85
        if comp_gate == "saturated" and profile_match < APPLICANT_COUNT_GATES["saturated_match_floor"]:
            bonuses["saturated_penalty"] = -10
            final_score -= 10

        final_score = max(0, min(100, final_score))
        breakdown = ScoreBreakdown(
            job_id           = job.job_id,
            profile_match    = profile_match,
            compensation_fit = compensation_fit,
            role_type_match  = role_type_match,
            company_tier     = company_tier,
            location_fit     = location_fit,
            recency          = recency,
            competitive_pos  = comp_pos,
            cultural_fit     = cultural_fit,
            trajectory       = trajectory,
            final_score      = final_score,
            routing          = route(final_score),
            bonuses          = bonuses,
            resume_variant   = RESUME_ROUTING.get(role_label, variant),
        )
        breakdown.bonuses["deadline_meta"] = d_meta if d_meta else {}     # type: ignore
        log.info(
            "scoring.done job=%s final=%s route=%s variant=%s",
            job.job_id, final_score, breakdown.routing, breakdown.resume_variant,
        )
        return breakdown


__all__ = [
    "ScoringEngine",
    "ScoreBreakdown",
    "TextClassifier",
    "TrajectoryAnalyser",
    "CulturalFitFn",
    "route",
    "deadline_bonus",
    "score_recency",
    "score_compensation",
    "score_competitive_pos",
    "score_company_tier",
    "score_location",
]
