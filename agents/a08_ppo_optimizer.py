"""
============================================================
OPERATION FIRST MOVER v8.0 -- AGENT A-08: PPO OPTIMIZER
============================================================
10-variable PPO (Probability of Positive Outcome) scoring model.
Ranks all clean listings to produce the Top 25 shortlist for apply.

PPO Variables (10 total, weights sum to 1.0):
    v1:  has_ppo_tag (0.20)         - Explicit PPO/pre-placement mention
    v2:  company_tier_score (0.18)  - Company tier (1-5)
    v3:  low_applicant_bonus (0.15) - Low competition bonus
    v4:  stipend_normalized (0.08)  - Stipend vs category median
    v5:  duration_fit (0.05)        - Ideal 2-6 month duration
    v6:  cirs_score (0.12)          - Company Intern Readiness Score
    v7:  sector_momentum (0.07)     - Sector hiring signals
    v8:  intent_signal (0.08)       - Hiring intent indicators
    v9:  historic_callback (0.05)   - Past response rates
    v10: recency_bonus (0.02)       - Fresh posting bonus

Innovation #1: Timing Engine
    Apply within 6 hours of posting for maximum visibility.

Innovation #10: Rate Optimizer
    Queue releases during 9am-11am IST Tuesday-Thursday for
    optimal recruiter viewing times.

AI Provider: Groq (primary), Cerebras (fallback), Mistral (emergency)
============================================================
"""

import os
import json
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

from core.config import (
    get_config, now_ist, IST,
    PPOWeights, PPO_PARAMS,
    TIER_PPO_SCORES, DEFAULT_TIER_SCORE,
    CompanyTier, BlueOceanConfig,
)
from core.database import get_db
from core.ai_router import get_router

AGENT_ID = 'A-08'
AGENT_NAME = 'PPO Optimizer'


class PPOOptimizer:
    """
    10-variable PPO scoring model for ranking internship listings.
    Produces a daily Top 25 shortlist sorted by PPO score.
    """

    def __init__(self):
        self.config = get_config()
        self.weights = self.config.ppo_weights
        self.db = get_db()
        self.router = get_router()
        self._total_scored = 0
        self._blue_ocean_count = 0

    def compute_ppo_score(self, listing: Dict[str, Any]) -> float:
        """
        Compute the PPO score for a single listing.

        Args:
            listing: Dict with listing fields

        Returns:
            Float PPO score between 0.0 and 1.0
        """
        w = self.weights
        params = PPO_PARAMS

        # v1: has_ppo_tag (0-100)
        v1 = 100.0 if listing.get('ppo_eligible') else 0.0

        # v2: company_tier_score (0-100)
        tier = listing.get('company_tier', 5)
        v2 = float(TIER_PPO_SCORES.get(tier, DEFAULT_TIER_SCORE))

        # v3: low_applicant_bonus (0-100)
        applicants = listing.get('applicants', 0) or 0
        v3 = max(0.0, 100.0 - (applicants * params['applicant_decay_rate']))

        # v4: stipend_normalized (0-100)
        stipend = listing.get('stipend_numeric', 0) or 0
        category = listing.get('mba_category', '')
        median = params['category_median_stipends'].get(category, 10000)
        if median > 0 and stipend > 0:
            v4 = min(100.0, (stipend / median) * 100)
        else:
            v4 = 50.0  # Default if no stipend info

        # v5: duration_fit (0-100)
        duration = listing.get('duration_months', 0) or 0
        ideal_min, ideal_max = params['ideal_duration_range']
        if duration == 0:
            v5 = 50.0  # Unknown duration
        elif ideal_min <= duration <= ideal_max:
            v5 = 100.0  # Perfect fit
        elif duration < ideal_min:
            v5 = float(params['short_duration_score'])
        else:
            v5 = float(params['long_duration_score'])

        # v6: cirs_score (0-100)
        v6 = float(listing.get('cirs_score', 40.0))

        # v7: sector_momentum (0-100)
        v7 = float(listing.get('intent_signal_score', 50.0))

        # v8: intent_signal (0-100)
        v8 = v7  # Shared with sector momentum for now

        # v9: historic_callback (0-100)
        v9 = float(params['default_callback_score'])

        # v10: recency_bonus (0-100)
        posted = listing.get('posted_date') or listing.get('created_at')
        if posted:
            try:
                if isinstance(posted, str):
                    posted_dt = datetime.fromisoformat(posted.replace('Z', '+00:00'))
                else:
                    posted_dt = posted
                days_old = (now_ist() - posted_dt.replace(tzinfo=IST if posted_dt.tzinfo is None else posted_dt.tzinfo)).days
                v10 = max(0.0, 100.0 - (days_old * params['recency_decay_per_day']))
            except Exception:
                v10 = 50.0
        else:
            v10 = 50.0

        # Compute weighted score
        score = (
            w.has_ppo_tag * (v1 / 100) +
            w.company_tier_score * (v2 / 100) +
            w.low_applicant_bonus * (v3 / 100) +
            w.stipend_normalized * (v4 / 100) +
            w.duration_fit * (v5 / 100) +
            w.cirs_score * (v6 / 100) +
            w.sector_momentum * (v7 / 100) +
            w.intent_signal * (v8 / 100) +
            w.historic_callback * (v9 / 100) +
            w.recency_bonus * (v10 / 100)
        )

        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))

    def is_blue_ocean(self, listing: Dict[str, Any]) -> bool:
        """Check if a listing qualifies as Blue Ocean."""
        bo = self.config.blue_ocean
        tier = listing.get('company_tier', 5)
        tier_score = TIER_PPO_SCORES.get(tier, DEFAULT_TIER_SCORE)
        applicants = listing.get('applicants', 999)
        stipend = listing.get('stipend_numeric', 0)

        if (tier_score >= bo.min_prestige_score and
            applicants <= bo.max_applicant_count and
            stipend >= bo.min_stipend):
            return True
        return False

    async def score_all_listings(self) -> Dict[str, Any]:
        """Score all active listings and update database."""
        listings = self.db.get_active_listings(
            limit=500,
            exclude_ghosts=True,
            exclude_applied=True,
        )

        if not listings:
            logger.info("A-08: No active listings to score")
            return {'total': 0, 'blue_ocean': 0}

        logger.info(f"A-08: Scoring {len(listings)} active listings")

        scored_listings = []
        blue_ocean_count = 0

        for listing in listings:
            try:
                ppo_score = self.compute_ppo_score(listing)
                blue_ocean = self.is_blue_ocean(listing)

                if blue_ocean:
                    blue_ocean_count += 1

                # Update database
                listing_id = listing.get('id')
                if listing_id:
                    self.db.update_listing_scores(listing_id, {
                        'ppo_score': round(ppo_score, 4),
                        'blue_ocean': blue_ocean,
                    })

                scored_listings.append({
                    'id': listing_id,
                    'title': listing.get('title'),
                    'company': listing.get('company'),
                    'ppo_score': ppo_score,
                    'blue_ocean': blue_ocean,
                })

                self._total_scored += 1

            except Exception as e:
                logger.error(f"PPO scoring error: {e}")

        # Sort by PPO score
        scored_listings.sort(key=lambda x: x['ppo_score'], reverse=True)

        self._blue_ocean_count = blue_ocean_count

        result = {
            'total_scored': len(scored_listings),
            'blue_ocean': blue_ocean_count,
            'top_25': scored_listings[:25],
            'avg_ppo_score': sum(l['ppo_score'] for l in scored_listings) / max(len(scored_listings), 1),
            'timestamp': now_ist().isoformat(),
        }

        logger.info(
            f"A-08: Scoring complete. "
            f"Top PPO: {scored_listings[0]['ppo_score']:.3f} if scored_listings else 'N/A', "
            f"Blue Ocean: {blue_ocean_count}"
        )

        return result

    def get_top_listings(self, n: int = 25) -> List[Dict[str, Any]]:
        """Get the top N listings by PPO score."""
        return self.db.get_listings_for_apply(limit=n)

    def get_stats(self) -> Dict[str, Any]:
        return {
            'total_scored': self._total_scored,
            'blue_ocean_count': self._blue_ocean_count,
            'weights': self.weights.to_dict(),
        }


def get_ppo_optimizer() -> PPOOptimizer:
    return PPOOptimizer()
