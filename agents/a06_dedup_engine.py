"""
============================================================
OPERATION FIRST MOVER v8.0 -- AGENT A-06: DEDUP ENGINE
============================================================
Cross-portal deduplication engine ensuring no listing is counted twice.
Uses the "best path" logic to determine canonical portal.

Dedup Strategy:
    1. Compute dedup_hash from normalized title + company
    2. If hash exists, merge enrichment data
    3. Select canonical_portal based on:
       - Portal with most data (description, applicants, etc.)
       - Historical response time for the portal
       - Apply ease (Internshala > Naukri > LinkedIn)

Innovation #6: Cross-Portal Dedup
    When the same role appears on multiple portals, the system
    selects the "best-path" portal based on historical response
    times from the outcomes table.

AI Provider: Cerebras (primary), Groq (fallback), OpenRouter (emergency)
============================================================
"""

import os
import json
import hashlib
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, Tuple
from collections import defaultdict

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

from core.config import get_config, now_ist
from core.database import get_db, DatabaseManager
from core.ai_router import get_router

AGENT_ID = 'A-06'
AGENT_NAME = 'Dedup Engine'

# Portal priority for canonical selection (higher = better)
PORTAL_PRIORITY: Dict[str, int] = {
    'internshala': 10,  # Best for apply (cover letter + profile)
    'naukri': 9,        # Good API, easy apply
    'linkedin': 8,      # Good visibility
    'unstop': 7,
    'iimjobs': 6,
    'wellfound': 5,
    'foundit': 4,
    'timesjobs': 3,
    'greenhouse': 8,    # Direct ATS - great for apply
    'lever': 8,         # Direct ATS - great for apply
}


class DedupEngine:
    """
    Cross-portal deduplication engine.
    Identifies and merges duplicate listings across portals.
    """

    def __init__(self):
        self.config = get_config()
        self.db = get_db()
        self.router = get_router()
        self._total_processed = 0
        self._total_duplicates_found = 0
        self._total_merged = 0

    async def run_dedup(self, listings: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Run deduplication on new listings or all active listings.

        Args:
            listings: Optional list of new listings to dedup.
                     If None, fetches from database.

        Returns:
            Dict with dedup statistics
        """
        if listings is None:
            listings = self.db.get_active_listings(limit=1000)

        if not listings:
            return {'total': 0, 'duplicates': 0, 'merged': 0}

        logger.info(f"A-06: Starting dedup on {len(listings)} listings")

        # Group by dedup_hash
        hash_groups: Dict[str, List[Dict]] = defaultdict(list)
        for listing in listings:
            h = listing.get('dedup_hash', '')
            if h:
                hash_groups[h].append(listing)

        duplicates_found = 0
        merged_count = 0

        for hash_val, group in hash_groups.items():
            if len(group) > 1:
                duplicates_found += len(group) - 1
                # Select canonical and merge
                canonical = self._select_canonical(group)
                merged = self._merge_listings(canonical, group)
                if merged:
                    merged_count += 1

        # Also do fuzzy matching for near-duplicates
        if RAPIDFUZZ_AVAILABLE:
            fuzzy_dupes = await self._find_fuzzy_duplicates(listings)
            duplicates_found += len(fuzzy_dupes)

        self._total_processed += len(listings)
        self._total_duplicates_found += duplicates_found
        self._total_merged += merged_count

        result = {
            'total_processed': len(listings),
            'exact_duplicates': duplicates_found,
            'merged': merged_count,
            'unique_hashes': len(hash_groups),
        }

        logger.info(
            f"A-06: Dedup complete. {duplicates_found} duplicates found, "
            f"{merged_count} merged"
        )
        return result

    def _select_canonical(self, group: List[Dict]) -> Dict:
        """Select the canonical (best) listing from a group of duplicates."""
        if len(group) == 1:
            return group[0]

        # Score each listing
        def score_listing(listing: Dict) -> float:
            score = 0.0
            # Portal priority
            platform = listing.get('platform', '')
            score += PORTAL_PRIORITY.get(platform, 1) * 10

            # Data completeness
            if listing.get('description'):
                score += 20
            if listing.get('stipend'):
                score += 10
            if listing.get('applicants', 0) > 0:
                score += 10
            if listing.get('ppo_eligible'):
                score += 15
            if listing.get('skills_required'):
                score += 5
            if listing.get('apply_url'):
                score += 10

            return score

        scored = [(score_listing(l), l) for l in group]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _merge_listings(self, canonical: Dict, group: List[Dict]) -> bool:
        """Merge data from duplicates into canonical listing."""
        if len(group) <= 1:
            return False

        try:
            canonical_id = canonical.get('id')
            if not canonical_id:
                return False

            # Collect best data from all listings
            merged_data = {}

            for listing in group:
                if listing.get('id') == canonical_id:
                    continue

                # Merge missing fields from duplicates
                if not canonical.get('description') and listing.get('description'):
                    merged_data['description'] = listing['description']
                if not canonical.get('stipend') and listing.get('stipend'):
                    merged_data['stipend'] = listing['stipend']
                    merged_data['stipend_numeric'] = listing.get('stipend_numeric', 0)
                if (listing.get('applicants', 0) > canonical.get('applicants', 0)):
                    merged_data['applicants'] = listing['applicants']
                if listing.get('ppo_eligible') and not canonical.get('ppo_eligible'):
                    merged_data['ppo_eligible'] = True

                # Mark duplicate
                dup_id = listing.get('id')
                if dup_id:
                    self.db.update_listing_status(dup_id, 'duplicate', {
                        'duplicate_of': canonical_id,
                    })

            # Update canonical with merged data
            if merged_data:
                merged_data['canonical_portal'] = canonical.get('platform', '')
                self.db.update_listing_scores(canonical_id, merged_data)

            return True

        except Exception as e:
            logger.error(f"Merge error: {e}")
            return False

    async def _find_fuzzy_duplicates(self, listings: List[Dict]) -> List[Tuple[str, str]]:
        """Find near-duplicate listings using fuzzy string matching."""
        duplicates = []

        if not RAPIDFUZZ_AVAILABLE or len(listings) < 2:
            return duplicates

        # Compare titles within same company
        company_groups: Dict[str, List[Dict]] = defaultdict(list)
        for listing in listings:
            company = listing.get('company', '').lower().strip()
            if company:
                company_groups[company].append(listing)

        for company, company_listings in company_groups.items():
            if len(company_listings) < 2:
                continue

            for i in range(len(company_listings)):
                for j in range(i + 1, len(company_listings)):
                    title_a = company_listings[i].get('title', '')
                    title_b = company_listings[j].get('title', '')

                    similarity = fuzz.ratio(title_a.lower(), title_b.lower())
                    if similarity > 85:  # >85% similar = likely duplicate
                        id_a = company_listings[i].get('id', '')
                        id_b = company_listings[j].get('id', '')
                        if id_a and id_b:
                            duplicates.append((id_a, id_b))

        return duplicates

    def get_stats(self) -> Dict[str, Any]:
        return {
            'total_processed': self._total_processed,
            'total_duplicates_found': self._total_duplicates_found,
            'total_merged': self._total_merged,
        }


def get_dedup_engine() -> DedupEngine:
    return DedupEngine()
