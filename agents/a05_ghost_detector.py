"""
============================================================
OPERATION FIRST MOVER v8.0 -- AGENT A-05: GHOST DETECTOR
============================================================
5-signal ghost job detection to filter out fake/expired/dormant listings.
Saves time by preventing applications to ghost jobs.

Ghost Score Signals (0-100):
    Signal 1: Listing Age (0-25 pts)
        - >30 days old: +25
        - 20-30 days: +15
        - 10-20 days: +8
    Signal 2: Applicant Overload (0-20 pts)
        - >500 applicants: +20
        - 300-500: +12
        - 200-300: +5
    Signal 3: Repetitive Posting (0-20 pts)
        - 3+ times in 90 days: +20
        - 2 times: +10
    Signal 4: No HR Response Signal (0-15 pts)
        - 0 signals in 30 days: +15
        - <3 signals: +8
    Signal 5: ATS Mismatch (0-20 pts)
        - Listing NOT on ATS: +20
        - ATS platform unknown: +5

Classification:
    >= 60: GHOST (skip entirely)
    40-59: SUSPICIOUS (lower priority)
    < 40:  CLEAN (proceed normally)

AI Provider: Cerebras (primary), Groq (fallback), Mistral (emergency)
============================================================
"""

import os
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

from core.config import get_config, now_ist, GhostDetectionConfig
from core.database import get_db
from core.ai_router import get_router

AGENT_ID = 'A-05'
AGENT_NAME = 'Ghost Detector'


class GhostDetector:
    """
    5-signal ghost job detection engine.
    Analyzes each listing for signs of being a ghost/fake job.
    """

    def __init__(self):
        self.config = get_config()
        self.ghost_config = self.config.ghost
        self.db = get_db()
        self.router = get_router()
        self._total_analyzed = 0
        self._total_ghosts = 0
        self._total_suspicious = 0
        self._total_clean = 0

    async def analyze_listing(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a single listing for ghost signals.

        Returns:
            Dict with ghost_score, ghost_status, signal_breakdown
        """
        signals = {}
        total_score = 0

        # Signal 1: Listing Age
        age_score = self._score_age(listing)
        signals['age'] = age_score
        total_score += age_score

        # Signal 2: Applicant Overload
        applicant_score = self._score_applicants(listing)
        signals['applicants'] = applicant_score
        total_score += applicant_score

        # Signal 3: Repetitive Posting
        repeat_score = await self._score_repetition(listing)
        signals['repetition'] = repeat_score
        total_score += repeat_score

        # Signal 4: No HR Response Signal
        hr_score = await self._score_hr_signals(listing)
        signals['hr_signal'] = hr_score
        total_score += hr_score

        # Signal 5: ATS Mismatch (lightweight)
        ats_score = self._score_ats_mismatch(listing)
        signals['ats_mismatch'] = ats_score
        total_score += ats_score

        # Classify
        gc = self.ghost_config
        if total_score >= gc.ghost_threshold:
            status = 'ghost'
            self._total_ghosts += 1
        elif total_score >= gc.suspicious_threshold:
            status = 'suspicious'
            self._total_suspicious += 1
        else:
            status = 'clean'
            self._total_clean += 1

        self._total_analyzed += 1

        return {
            'ghost_score': total_score,
            'ghost_status': status,
            'signal_breakdown': signals,
        }

    def _score_age(self, listing: Dict[str, Any]) -> int:
        """Score based on listing age."""
        gc = self.ghost_config
        posted = listing.get('posted_date') or listing.get('created_at')
        if not posted:
            return 0

        try:
            if isinstance(posted, str):
                # Try multiple date formats
                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        posted_dt = datetime.strptime(posted[:19], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return 0
            else:
                posted_dt = posted

            age_days = (now_ist().replace(tzinfo=None) - posted_dt.replace(tzinfo=None)).days

            if age_days >= gc.age_high_threshold_days:
                return gc.age_high_score
            elif age_days >= gc.age_medium_threshold_days:
                return gc.age_medium_score
            elif age_days >= gc.age_low_threshold_days:
                return gc.age_low_score
            return 0

        except Exception:
            return 0

    def _score_applicants(self, listing: Dict[str, Any]) -> int:
        """Score based on number of applicants."""
        gc = self.ghost_config
        applicants = listing.get('applicants', 0) or 0

        if applicants >= gc.applicant_high_threshold:
            return gc.applicant_high_score
        elif applicants >= gc.applicant_medium_threshold:
            return gc.applicant_medium_score
        elif applicants >= gc.applicant_low_threshold:
            return gc.applicant_low_score
        return 0

    async def _score_repetition(self, listing: Dict[str, Any]) -> int:
        """Score based on how many times this company posted similar roles."""
        gc = self.ghost_config
        company = listing.get('company', '')
        title = listing.get('title', '')
        if not company:
            return 0

        try:
            similar = self.db.get_listings_by_company(company)
            # Count similar titles
            count = 0
            for s in similar:
                if s.get('title', '').lower() == title.lower():
                    count += 1

            if count >= gc.repeat_high_count:
                return gc.repeat_high_score
            elif count >= gc.repeat_medium_count:
                return gc.repeat_medium_score
            return 0
        except Exception:
            return 0

    async def _score_hr_signals(self, listing: Dict[str, Any]) -> int:
        """Score based on HR activity signals."""
        gc = self.ghost_config
        # For now, use a simplified heuristic
        # Full implementation would check outcomes table
        company = listing.get('company', '')
        if not company:
            return gc.weak_signal_score

        try:
            outcomes = self.db.get_outcomes(limit=50)
            company_outcomes = [
                o for o in outcomes
                if o.get('company', '').lower() == company.lower()
            ]

            if not company_outcomes:
                return gc.weak_signal_score

            # Check for any responses
            responses = [o for o in company_outcomes if o.get('status') not in ('applied', 'ghosted')]
            if not responses:
                return gc.no_signal_score
            elif len(responses) < gc.weak_signal_threshold:
                return gc.weak_signal_score
            return 0
        except Exception:
            return 0

    def _score_ats_mismatch(self, listing: Dict[str, Any]) -> int:
        """Score based on ATS platform presence."""
        gc = self.ghost_config
        platform = listing.get('platform', '')
        # ATS platforms (Greenhouse, Lever) are generally more trustworthy
        if platform in ('greenhouse', 'lever'):
            return 0
        # Unknown ATS
        return gc.ats_unknown_score

    async def analyze_batch(self, listings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze a batch of listings and update their ghost scores."""
        results = {'ghost': 0, 'suspicious': 0, 'clean': 0, 'total': 0}

        for listing in listings:
            try:
                analysis = await self.analyze_listing(listing)
                listing_id = listing.get('id')

                if listing_id:
                    self.db.update_listing_scores(listing_id, {
                        'ghost_score': analysis['ghost_score'],
                        'ghost_status': analysis['ghost_status'],
                    })

                results[analysis['ghost_status']] += 1
                results['total'] += 1

            except Exception as e:
                logger.error(f"Ghost analysis error: {e}")

        logger.info(
            f"A-05: Ghost analysis complete. "
            f"Ghost: {results['ghost']}, "
            f"Suspicious: {results['suspicious']}, "
            f"Clean: {results['clean']}"
        )
        return results

    def get_stats(self) -> Dict[str, Any]:
        return {
            'total_analyzed': self._total_analyzed,
            'total_ghosts': self._total_ghosts,
            'total_suspicious': self._total_suspicious,
            'total_clean': self._total_clean,
        }


def get_ghost_detector() -> GhostDetector:
    return GhostDetector()
