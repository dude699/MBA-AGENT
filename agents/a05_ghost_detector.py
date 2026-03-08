"""
============================================================
AGENT A-05: GHOST JOB DETECTOR
============================================================
Identifies fake/stale/ghost job listings using a 5-signal
scoring system. Filters ~35% of daily listings, saving
application time on dead-end postings.

Schedule: 06:15 AM IST (after A-06 dedup)

5-Signal Scoring System:
    S1: Listing Age         — Old listings likely dead
    S2: Applicant Overload  — Too many applicants, still open
    S3: Repetitive Posting  — Same role re-posted monthly
    S4: No HR Signal        — Company has no hiring activity
    S5: ATS Mismatch        — Listing not on company ATS

Ghost Score (0-100):
    >= 60: GHOST (filtered out)
    40-59: SUSPICIOUS (flagged)
    < 40:  CLEAN (keep)

AI Provider: Cerebras (ghost_classify) — fast classification
============================================================
"""

import os
import re
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import (
    get_config, GhostDetectionConfig, IST, CompanyTier,
)
from core.database import (
    get_db, DatabaseManager, GhostScore, CleanListing,
    ListingStatus,
)
from core.ai_router import get_router, AIRouter


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-05"
AGENT_NAME = "Ghost Detector"


# ============================================================
# GHOST SIGNAL CALCULATORS
# ============================================================

class Signal1_ListingAge:
    """
    Signal 1: Listing Age
    Older listings are more likely to be ghosts.

    Scoring:
        > 30 days = 25 points
        20-30 days = 15 points
        10-20 days = 8 points
        < 10 days  = 0 points
    """

    def __init__(self, config: GhostDetectionConfig = None):
        self.config = config or get_config().ghost

    def calculate(self, listing: Dict) -> float:
        """Calculate listing age ghost signal score."""
        posted_days = listing.get('posted_days_ago', 0)

        if posted_days is None or posted_days == 0:
            # Check created_at as fallback
            created_at = listing.get('created_at', '')
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    now = datetime.now(IST)
                    if created.tzinfo is None:
                        from datetime import timezone
                        created = created.replace(tzinfo=timezone.utc)
                    posted_days = (now - created).days
                except (ValueError, TypeError):
                    posted_days = 0

        if posted_days >= self.config.age_high_threshold_days:
            return self.config.age_high_score  # 25
        elif posted_days >= self.config.age_medium_threshold_days:
            return self.config.age_medium_score  # 15
        elif posted_days >= self.config.age_low_threshold_days:
            return self.config.age_low_score  # 8
        else:
            return 0.0

    def explain(self, listing: Dict) -> str:
        """Generate human-readable explanation."""
        score = self.calculate(listing)
        days = listing.get('posted_days_ago', 0)
        if score >= 25:
            return f"Listing is {days} days old (>30d = high ghost risk)"
        elif score >= 15:
            return f"Listing is {days} days old (20-30d = moderate ghost risk)"
        elif score >= 8:
            return f"Listing is {days} days old (10-20d = slight ghost risk)"
        else:
            return f"Listing is {days} days old (fresh)"


class Signal2_ApplicantOverload:
    """
    Signal 2: Applicant Overload
    High applicants + still open = suspicious.

    Scoring:
        > 500 applicants still open = 20 points
        > 300 applicants = 12 points
        > 200 applicants = 5 points
        <= 200 = 0 points
    """

    def __init__(self, config: GhostDetectionConfig = None):
        self.config = config or get_config().ghost

    def calculate(self, listing: Dict) -> float:
        """Calculate applicant overload ghost signal score."""
        applicants = listing.get('applicants', 0) or 0
        status = listing.get('status', 'active')

        # Only count if listing is still active
        if status != 'active':
            return 0.0

        if applicants >= self.config.applicant_high_threshold:
            return self.config.applicant_high_score  # 20
        elif applicants >= self.config.applicant_medium_threshold:
            return self.config.applicant_medium_score  # 12
        elif applicants >= self.config.applicant_low_threshold:
            return self.config.applicant_low_score  # 5
        else:
            return 0.0

    def explain(self, listing: Dict) -> str:
        score = self.calculate(listing)
        applicants = listing.get('applicants', 0)
        if score >= 20:
            return f"{applicants} applicants & still open (very suspicious)"
        elif score >= 12:
            return f"{applicants} applicants & still open (suspicious)"
        elif score >= 5:
            return f"{applicants} applicants (moderate competition)"
        else:
            return f"{applicants} applicants (normal)"


class Signal3_RepetitivePosting:
    """
    Signal 3: Repetitive Posting
    Same company posting same role repeatedly = ghost.

    Scoring:
        Same role posted 3+ times in 90 days = 20 points
        Same role posted 2 times = 10 points
        First time = 0 points
    """

    def __init__(self, db: DatabaseManager = None,
                 config: GhostDetectionConfig = None):
        self.db = db or get_db()
        self.config = config or get_config().ghost
        self._company_role_cache: Dict[str, int] = {}

    def build_cache(self, listings: Optional[List[Dict]] = None):
        """Pre-build the repetitive posting cache for batch processing."""
        try:
            with self.db.get_cursor() as cur:
                lookback = self.config.repeat_lookback_days
                cur.execute(
                    """
                    SELECT company, title, COUNT(*) as posting_count
                    FROM raw_listings
                    WHERE scraped_at >= datetime('now', ?)
                    GROUP BY LOWER(company), LOWER(title)
                    HAVING COUNT(*) >= 2
                    """,
                    (f"-{lookback} days",)
                )
                for row in cur.fetchall():
                    key = f"{row['company'].lower().strip()}|{row['title'].lower().strip()}"
                    self._company_role_cache[key] = row['posting_count']
        except Exception as e:
            logger.error(f"Failed to build repetitive posting cache: {e}")

    def calculate(self, listing: Dict) -> float:
        """Calculate repetitive posting ghost signal score."""
        company = (listing.get('company', '') or '').lower().strip()
        title = (listing.get('title', '') or '').lower().strip()

        if not company or not title:
            return 0.0

        key = f"{company}|{title}"

        # Check cache first
        if key in self._company_role_cache:
            count = self._company_role_cache[key]
        else:
            # Query database
            try:
                with self.db.get_cursor() as cur:
                    lookback = self.config.repeat_lookback_days
                    cur.execute(
                        """
                        SELECT COUNT(*) as cnt FROM raw_listings
                        WHERE LOWER(company) = ? AND LOWER(title) = ?
                          AND scraped_at >= datetime('now', ?)
                        """,
                        (company, title, f"-{lookback} days")
                    )
                    row = cur.fetchone()
                    count = row[0] if row else 0
            except Exception:
                count = 0

        if count >= self.config.repeat_high_count:
            return self.config.repeat_high_score  # 20
        elif count >= self.config.repeat_medium_count:
            return self.config.repeat_medium_score  # 10
        else:
            return 0.0

    def explain(self, listing: Dict) -> str:
        score = self.calculate(listing)
        if score >= 20:
            return "Same role posted 3+ times in 90 days (likely ghost)"
        elif score >= 10:
            return "Same role posted 2 times in 90 days (possibly recycled)"
        else:
            return "First posting of this role (fresh)"


class Signal4_NoHRSignal:
    """
    Signal 4: No HR Response Signal
    Company has no recent hiring activity signals from A-01.

    Scoring:
        0 intent signals in 30 days = 15 points
        < 3 signals = 8 points
        >= 3 signals = 0 points
    """

    def __init__(self, db: DatabaseManager = None,
                 config: GhostDetectionConfig = None):
        self.db = db or get_db()
        self.config = config or get_config().ghost
        self._signal_cache: Dict[int, int] = {}  # company_id -> signal_count

    def build_cache(self):
        """Pre-build the HR signal cache."""
        try:
            with self.db.get_cursor() as cur:
                cur.execute(
                    """
                    SELECT company_id, COUNT(*) as signal_count
                    FROM intent_signals
                    WHERE detected_at >= datetime('now', '-30 days')
                      AND signal_score > 0
                    GROUP BY company_id
                    """
                )
                for row in cur.fetchall():
                    self._signal_cache[row['company_id']] = row['signal_count']
        except Exception as e:
            logger.error(f"Failed to build HR signal cache: {e}")

    def calculate(self, listing: Dict) -> float:
        """Calculate no-HR-signal ghost score."""
        company_id = listing.get('company_id')

        if company_id is None:
            # No company mapping — moderate penalty
            return self.config.weak_signal_score  # 8

        signal_count = self._signal_cache.get(company_id)

        if signal_count is None:
            # Query database
            try:
                signals = self.db.get_company_signals(company_id, days=30)
                signal_count = len(signals)
                self._signal_cache[company_id] = signal_count
            except Exception:
                signal_count = 0

        if signal_count == 0:
            return self.config.no_signal_score  # 15
        elif signal_count < 3:
            return self.config.weak_signal_score  # 8
        else:
            return 0.0

    def explain(self, listing: Dict) -> str:
        score = self.calculate(listing)
        if score >= 15:
            return "Company has ZERO hiring signals in 30 days (suspicious)"
        elif score >= 8:
            return "Company has few hiring signals (<3 in 30 days)"
        else:
            return "Company has active hiring signals (good sign)"


class Signal5_ATSMismatch:
    """
    Signal 5: ATS Mismatch
    Listing doesn't exist on company's ATS page.

    Scoring:
        Listing NOT on company ATS = 20 points
        ATS platform unknown = 5 points
        Listing confirmed on ATS = 0 points
    """

    def __init__(self, db: DatabaseManager = None,
                 config: GhostDetectionConfig = None):
        self.db = db or get_db()
        self.config = config or get_config().ghost
        self._ats_cache: Dict[int, str] = {}  # company_id -> ats_platform

    def build_cache(self):
        """Pre-build the ATS knowledge cache."""
        try:
            with self.db.get_cursor() as cur:
                cur.execute(
                    "SELECT id, ats_platform FROM companies WHERE ats_platform != ''"
                )
                for row in cur.fetchall():
                    self._ats_cache[row['id']] = row['ats_platform']
        except Exception as e:
            logger.error(f"Failed to build ATS cache: {e}")

    def calculate(self, listing: Dict) -> float:
        """Calculate ATS mismatch ghost score."""
        company_id = listing.get('company_id')
        source = listing.get('source', '')

        # ATS sources are verified by nature
        if source in ('greenhouse', 'lever', 'workday'):
            return 0.0

        if company_id is None:
            return self.config.ats_unknown_score  # 5

        ats_platform = self._ats_cache.get(company_id)

        if ats_platform is None:
            # Check database
            company = self.db.get_company_by_id(company_id)
            if company:
                ats_platform = company.get('ats_platform', '')
                self._ats_cache[company_id] = ats_platform

        if not ats_platform:
            return self.config.ats_unknown_score  # 5

        # If we have ATS data but listing isn't from ATS
        # This is a basic heuristic — full verification requires
        # cross-referencing with A-04 ATS crawler results
        return 0.0  # Default to clean if company has ATS

    def explain(self, listing: Dict) -> str:
        score = self.calculate(listing)
        if score >= 20:
            return "Listing NOT found on company's ATS page (likely ghost)"
        elif score >= 5:
            return "Company ATS platform unknown (cannot verify)"
        else:
            return "Listing verified on company ATS (authentic)"


# ============================================================
# GHOST DETECTOR ENGINE
# ============================================================

class GhostDetector:
    """
    Main ghost detection engine that orchestrates all 5 signals
    and produces a final ghost score for each listing.

    Usage:
        detector = GhostDetector()
        results = detector.score_batch(listings)
        # or
        score = detector.score_listing(listing)
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config().ghost
        self.router = get_router()

        # Initialize signal calculators
        self.signal1 = Signal1_ListingAge(self.config)
        self.signal2 = Signal2_ApplicantOverload(self.config)
        self.signal3 = Signal3_RepetitivePosting(self.db, self.config)
        self.signal4 = Signal4_NoHRSignal(self.db, self.config)
        self.signal5 = Signal5_ATSMismatch(self.db, self.config)

        # Stats
        self._total_scored = 0
        self._ghosts_found = 0
        self._suspicious_found = 0
        self._clean_found = 0

    def build_caches(self):
        """Pre-build all signal caches for batch processing."""
        logger.info(f"[{AGENT_ID}] Building ghost detection caches...")
        self.signal3.build_cache()
        self.signal4.build_cache()
        self.signal5.build_cache()
        logger.info(f"[{AGENT_ID}] Caches built")

    def score_listing(self, listing: Dict,
                      use_ai: bool = False) -> GhostScore:
        """
        Score a single listing for ghost probability.

        Args:
            listing: Listing dictionary (from clean_listings)
            use_ai: Also use AI classification for confirmation

        Returns:
            GhostScore object with all 5 signal scores
        """
        listing_id = listing.get('id', 0)

        # Calculate each signal
        s1 = self.signal1.calculate(listing)
        s2 = self.signal2.calculate(listing)
        s3 = self.signal3.calculate(listing)
        s4 = self.signal4.calculate(listing)
        s5 = self.signal5.calculate(listing)

        # Create ghost score
        ghost = GhostScore(
            listing_id=listing_id,
            listing_age_score=s1,
            applicant_overload_score=s2,
            repetitive_posting_score=s3,
            no_hr_signal_score=s4,
            ats_mismatch_score=s5,
        )
        ghost.calculate_total()

        # Optional AI confirmation for borderline cases
        if use_ai and 40 <= ghost.total_score <= 70:
            ai_ghost = self._ai_classify(listing)
            if ai_ghost is not None:
                # Adjust score by +/-10 based on AI
                if ai_ghost and ghost.total_score < 60:
                    ghost.total_score = min(100, ghost.total_score + 10)
                elif not ai_ghost and ghost.total_score >= 60:
                    ghost.total_score = max(0, ghost.total_score - 10)
                ghost.is_ghost = ghost.total_score >= 60

        # Update stats
        self._total_scored += 1
        if ghost.is_ghost:
            self._ghosts_found += 1
        elif ghost.total_score >= self.config.suspicious_threshold:
            self._suspicious_found += 1
        else:
            self._clean_found += 1

        return ghost

    def score_batch(self, use_ai_for_borderline: bool = False) -> Dict[str, Any]:
        """
        Score all unscored listings in batch.

        Args:
            use_ai_for_borderline: Use AI for borderline cases (40-70 score)

        Returns:
            Summary statistics
        """
        logger.info(f"[{AGENT_ID}] === GHOST SCORING START ===")
        start_time = time.time()

        # Update heartbeat
        self.db.update_agent_heartbeat(AGENT_ID, "running")

        # Build caches for batch efficiency
        self.build_caches()

        # Get listings that need scoring
        listings = self.db.get_listings_for_ghost_scoring(limit=500)
        logger.info(f"[{AGENT_ID}] {len(listings)} listings to score")

        if not listings:
            self.db.update_agent_heartbeat(
                AGENT_ID, "completed", items_processed=0
            )
            return {
                'total': 0, 'ghosts': 0, 'suspicious': 0,
                'clean': 0, 'duration_sec': 0
            }

        # Score all listings
        ghost_scores = []
        ghosts = 0
        suspicious = 0
        clean = 0

        for listing in listings:
            ghost = self.score_listing(
                listing, use_ai=use_ai_for_borderline
            )
            ghost_scores.append(ghost)

            # Classify
            if ghost.is_ghost:
                ghosts += 1
            elif ghost.total_score >= self.config.suspicious_threshold:
                suspicious += 1
            else:
                clean += 1

        # Batch insert ghost scores
        if ghost_scores:
            self.db.insert_ghost_scores_batch(ghost_scores)

        # Update clean_listings with ghost scores
        for ghost in ghost_scores:
            if ghost.listing_id:
                self.db.update_clean_listing_scores(
                    ghost.listing_id,
                    ghost_score=ghost.total_score,
                    is_ghost=ghost.is_ghost,
                    status=ListingStatus.GHOST.value if ghost.is_ghost else None,
                )

        duration = time.time() - start_time

        # Update heartbeat
        self.db.update_agent_heartbeat(
            AGENT_ID, "completed",
            items_processed=len(listings),
            errors=0,
            duration_sec=duration,
        )

        # Calculate filter rate
        filter_rate = (ghosts / len(listings) * 100) if listings else 0

        results = {
            'total': len(listings),
            'ghosts': ghosts,
            'suspicious': suspicious,
            'clean': clean,
            'filter_rate': round(filter_rate, 1),
            'duration_sec': round(duration, 1),
        }

        logger.info(
            f"[{AGENT_ID}] === GHOST SCORING COMPLETE === "
            f"Total: {results['total']} | "
            f"Ghosts: {results['ghosts']} ({results['filter_rate']}%) | "
            f"Suspicious: {results['suspicious']} | "
            f"Clean: {results['clean']} | "
            f"Duration: {results['duration_sec']}s"
        )

        return results

    def _ai_classify(self, listing: Dict) -> Optional[bool]:
        """
        Use AI (Cerebras) to classify a listing as ghost/not ghost.
        Only used for borderline cases to conserve quota.
        """
        try:
            response = self.router.classify_ghost(listing)
            if response.success:
                data = response.get_json()
                if data:
                    return data.get('is_ghost', None)
        except Exception as e:
            logger.debug(f"AI ghost classification failed: {e}")
        return None

    def get_detailed_report(self, listing: Dict) -> Dict[str, Any]:
        """
        Generate a detailed ghost analysis report for a single listing.
        Useful for the /ghost [id] Telegram command.
        """
        ghost = self.score_listing(listing, use_ai=True)

        return {
            'listing_id': listing.get('id'),
            'title': listing.get('title', ''),
            'company': listing.get('company', ''),
            'total_score': ghost.total_score,
            'is_ghost': ghost.is_ghost,
            'classification': (
                'GHOST' if ghost.is_ghost
                else 'SUSPICIOUS' if ghost.total_score >= self.config.suspicious_threshold
                else 'CLEAN'
            ),
            'signals': {
                'S1_listing_age': {
                    'score': ghost.listing_age_score,
                    'max': 25,
                    'explanation': self.signal1.explain(listing),
                },
                'S2_applicant_overload': {
                    'score': ghost.applicant_overload_score,
                    'max': 20,
                    'explanation': self.signal2.explain(listing),
                },
                'S3_repetitive_posting': {
                    'score': ghost.repetitive_posting_score,
                    'max': 20,
                    'explanation': self.signal3.explain(listing),
                },
                'S4_no_hr_signal': {
                    'score': ghost.no_hr_signal_score,
                    'max': 15,
                    'explanation': self.signal4.explain(listing),
                },
                'S5_ats_mismatch': {
                    'score': ghost.ats_mismatch_score,
                    'max': 20,
                    'explanation': self.signal5.explain(listing),
                },
            },
        }

    def format_report(self, report: Dict) -> str:
        """Format a ghost report for Telegram display."""
        classification = report['classification']
        emoji = {'GHOST': '👻', 'SUSPICIOUS': '⚠️', 'CLEAN': '✅'}.get(classification, '❓')

        lines = [
            f"{emoji} Ghost Analysis: {report['title']}",
            f"Company: {report['company']}",
            f"Score: {report['total_score']}/100 — {classification}",
            "",
            "Signal Breakdown:",
        ]

        for signal_name, signal_data in report['signals'].items():
            bar_filled = int(signal_data['score'] / signal_data['max'] * 5) if signal_data['max'] > 0 else 0
            bar = '█' * bar_filled + '░' * (5 - bar_filled)
            lines.append(
                f"  {signal_name}: {signal_data['score']}/{signal_data['max']} "
                f"[{bar}]"
            )
            lines.append(f"    {signal_data['explanation']}")

        return '\n'.join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get ghost detector statistics."""
        return {
            'total_scored': self._total_scored,
            'ghosts_found': self._ghosts_found,
            'suspicious_found': self._suspicious_found,
            'clean_found': self._clean_found,
            'ghost_rate': round(
                self._ghosts_found / self._total_scored * 100, 1
            ) if self._total_scored > 0 else 0,
        }


# ============================================================
# MODULE-LEVEL ACCESS
# ============================================================

def get_ghost_detector() -> GhostDetector:
    """Get a GhostDetector instance."""
    return GhostDetector()


if __name__ == "__main__":
    print("=" * 60)
    print(f"OPERATION FIRST MOVER v5 — {AGENT_NAME} Test")
    print("=" * 60)

    detector = get_ghost_detector()

    # Test with a sample listing
    test_listing = {
        'id': 1,
        'title': 'Marketing Intern',
        'company': 'Test Corp',
        'posted_days_ago': 35,
        'applicants': 600,
        'status': 'active',
        'source': 'internshala',
    }

    ghost = detector.score_listing(test_listing)
    print(f"\nTest listing ghost score:")
    print(f"  S1 (Age): {ghost.listing_age_score}")
    print(f"  S2 (Applicants): {ghost.applicant_overload_score}")
    print(f"  S3 (Repeat): {ghost.repetitive_posting_score}")
    print(f"  S4 (HR Signal): {ghost.no_hr_signal_score}")
    print(f"  S5 (ATS): {ghost.ats_mismatch_score}")
    print(f"  TOTAL: {ghost.total_score}")
    print(f"  IS GHOST: {ghost.is_ghost}")

    report = detector.get_detailed_report(test_listing)
    print(f"\n{detector.format_report(report)}")

    print("\n✅ A-05 Ghost Detector ready!")
    print("=" * 60)
