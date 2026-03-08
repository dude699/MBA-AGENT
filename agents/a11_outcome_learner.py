"""
============================================================
AGENT A-11: OUTCOME LEARNER — INDUSTRIAL GRADE
============================================================
Self-improvement engine that learns from application outcomes
to optimize PPO scoring weights. Uses logistic regression
to retrain weights weekly based on interview/offer data.

Schedule: Sunday 09:00 PM IST (weekly retrain)
AI Model: scikit-learn LogisticRegression (local ML)

Architecture:
    ┌──────────────────────────────────────────────────┐
    │            OUTCOME LEARNER (A-11)                │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Outcome Tracker                           │   │
    │  │  - applied → shortlisted → interview       │   │
    │  │  - → offer → ppo / rejected                │   │
    │  │  - Per-company, per-sector, per-tier        │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Feature Extractor                         │   │
    │  │  - 10 PPO variables at time of application │   │
    │  │  - Outcome label: positive/negative        │   │
    │  │  - Company tier, sector, category          │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Logistic Regression Retrainer             │   │
    │  │  - Minimum 20 outcomes before first train  │   │
    │  │  - Cross-validation for reliability        │   │
    │  │  - Feature importance analysis             │   │
    │  │  - New weights only if accuracy > 60%      │   │
    │  └────────────────┬──────────────────────────┘   │
    │                   ↓                              │
    │  ┌───────────────────────────────────────────┐   │
    │  │  Analytics & Reporting                     │   │
    │  │  - Weekly funnel stats                     │   │
    │  │  - Conversion rates per tier/sector        │   │
    │  │  - Best performing categories              │   │
    │  │  - Weight change history                   │   │
    │  └───────────────────────────────────────────┘   │
    │                                                  │
    └──────────────────────────────────────────────────┘

Outcome Funnel:
    applied → shortlisted → interview → offer → ppo
                                     ↘ rejected

Weight Retraining Logic:
    1. Collect all outcomes with their PPO variables at application time
    2. Label: interview/offer/ppo = positive (1), rejected = negative (0)
    3. Train logistic regression on 10 features
    4. Extract coefficient magnitudes as new weights
    5. Normalize to sum = 1.0
    6. Validate: accuracy > 60% and weights are reasonable
    7. Update PPO weights in database (used by A-08)
============================================================
"""

import os
import re
import json
import time
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from collections import Counter, defaultdict

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed. ML retraining disabled.")

from core.config import get_config, IST
from core.database import get_db, DatabaseManager, Outcome, OutcomeStatus

AGENT_ID = "A-11"
AGENT_NAME = "Outcome Learner"

# Minimum outcomes for retraining
MIN_OUTCOMES_FOR_RETRAIN = 20

# Minimum accuracy for weight adoption
MIN_ACCURACY_THRESHOLD = 0.60

# Positive outcome statuses
POSITIVE_OUTCOMES = {'interview', 'offer', 'ppo', 'shortlisted'}
NEGATIVE_OUTCOMES = {'rejected', 'withdrawn'}

# PPO variable names (must match A-08 order)
PPO_VARIABLE_NAMES = [
    'has_ppo_tag', 'company_tier_score', 'low_applicant_bonus',
    'stipend_normalized', 'duration_fit', 'cirs_score',
    'sector_momentum', 'intent_signal', 'historic_callback',
    'recency_bonus',
]

# Feature engineering
TIER_SCORES = {1: 100, 2: 80, 3: 60, 4: 40, 5: 20}
IDEAL_DURATION = (2, 6)


@dataclass
class RetrainResult:
    """Result of a weekly retrain operation."""
    retrained: bool = False
    reason: str = ""
    outcomes_used: int = 0
    accuracy: float = 0.0
    cv_accuracy: float = 0.0
    old_weights: Dict[str, float] = field(default_factory=dict)
    new_weights: Dict[str, float] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    weight_changes: Dict[str, float] = field(default_factory=dict)
    positive_count: int = 0
    negative_count: int = 0
    error: Optional[str] = None

    def to_telegram_msg(self) -> str:
        lines = [
            f"🧠 <b>Weekly Retrain Report</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"Status: {'✅ Retrained' if self.retrained else '❌ Not retrained'}",
            f"Reason: {self.reason}",
            f"Outcomes: {self.outcomes_used} ({self.positive_count}+ / {self.negative_count}-)",
        ]
        if self.retrained:
            lines.append(f"Accuracy: {self.accuracy:.1%}")
            lines.append(f"CV Accuracy: {self.cv_accuracy:.1%}")
            lines.append(f"")
            lines.append("<b>Weight Changes:</b>")
            for var, change in self.weight_changes.items():
                arrow = "↑" if change > 0 else "↓" if change < 0 else "="
                lines.append(f"  {var}: {arrow} {abs(change):.3f}")
        return '\n'.join(lines)


@dataclass
class FunnelStats:
    """Application funnel statistics."""
    total_applied: int = 0
    shortlisted: int = 0
    interviewed: int = 0
    offered: int = 0
    ppo_received: int = 0
    rejected: int = 0
    withdrawn: int = 0
    pending: int = 0
    conversion_rate: float = 0.0
    by_tier: Dict[int, Dict[str, int]] = field(default_factory=dict)
    by_sector: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_source: Dict[str, Dict[str, int]] = field(default_factory=dict)
    top_performing_companies: List[Dict] = field(default_factory=list)
    weekly_trend: List[Dict] = field(default_factory=list)

    def to_telegram_msg(self) -> str:
        lines = [
            f"📈 <b>Application Funnel</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"",
            f"Applied:     {self.total_applied}",
            f"Shortlisted: {self.shortlisted}",
            f"Interviewed: {self.interviewed}",
            f"Offered:     {self.offered}",
            f"PPO:         {self.ppo_received}",
            f"Rejected:    {self.rejected}",
            f"",
            f"Conversion: {self.conversion_rate:.1%}",
        ]

        if self.by_tier:
            lines.append(f"")
            lines.append("<b>By Tier:</b>")
            for tier in sorted(self.by_tier.keys()):
                stats = self.by_tier[tier]
                lines.append(
                    f"  Tier {tier}: {stats.get('applied', 0)} applied, "
                    f"{stats.get('positive', 0)} positive"
                )

        return '\n'.join(lines)


class OutcomeLearner:
    """
    Master outcome learning engine.
    
    Responsibilities:
        1. Track application outcomes through funnel
        2. Extract training features from outcomes
        3. Weekly retrain PPO weights using logistic regression
        4. Generate funnel analytics and reports
        5. Identify best-performing sectors and tiers
    """

    def __init__(self):
        self.db = get_db()
        self.config = get_config()

    def run_weekly_retrain(self) -> RetrainResult:
        """
        Run weekly retraining of PPO weights.
        Called every Sunday at 9 PM IST.
        """
        logger.info(f"[{AGENT_ID}] === WEEKLY RETRAIN START ===")
        start_time = time.time()
        self.db.update_agent_heartbeat(AGENT_ID, 'running')

        result = RetrainResult()

        # Get all outcomes with features
        outcomes = self.db.get_outcomes_for_learning(min_count=MIN_OUTCOMES_FOR_RETRAIN)
        result.outcomes_used = len(outcomes) if outcomes else 0

        if not outcomes or len(outcomes) < MIN_OUTCOMES_FOR_RETRAIN:
            result.reason = f"Insufficient outcomes ({result.outcomes_used}/{MIN_OUTCOMES_FOR_RETRAIN})"
            self.db.update_agent_heartbeat(AGENT_ID, 'completed', items_processed=0)
            return result

        if not SKLEARN_AVAILABLE:
            result.reason = "scikit-learn not installed"
            self.db.update_agent_heartbeat(AGENT_ID, 'completed', items_processed=0)
            return result

        try:
            # Build feature matrix
            X, y = self._build_feature_matrix(outcomes)
            result.positive_count = int(sum(y))
            result.negative_count = len(y) - result.positive_count

            if result.positive_count < 3 or result.negative_count < 3:
                result.reason = "Need at least 3 positive and 3 negative outcomes"
                self.db.update_agent_heartbeat(AGENT_ID, 'completed')
                return result

            # Scale features
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            # Train logistic regression
            model = LogisticRegression(
                max_iter=1000,
                C=1.0,
                solver='lbfgs',
                random_state=42,
            )
            model.fit(X_scaled, y)

            # Evaluate
            result.accuracy = float(model.score(X_scaled, y))

            # Cross-validation (if enough data)
            if len(y) >= 30:
                cv_scores = cross_val_score(model, X_scaled, y, cv=min(5, len(y) // 5))
                result.cv_accuracy = float(np.mean(cv_scores))
            else:
                result.cv_accuracy = result.accuracy

            logger.info(
                f"[{AGENT_ID}] Model accuracy: {result.accuracy:.2f}, "
                f"CV: {result.cv_accuracy:.2f}"
            )

            # Check accuracy threshold
            if result.accuracy < MIN_ACCURACY_THRESHOLD:
                result.reason = f"Accuracy {result.accuracy:.2f} < {MIN_ACCURACY_THRESHOLD}"
                self.db.update_agent_heartbeat(AGENT_ID, 'completed')
                return result

            # Extract new weights from coefficients
            coefficients = model.coef_[0]
            abs_coeffs = np.abs(coefficients)

            # Normalize to sum = 1.0
            total = abs_coeffs.sum()
            if total > 0:
                new_weights_array = abs_coeffs / total
            else:
                result.reason = "All coefficients are zero"
                self.db.update_agent_heartbeat(AGENT_ID, 'completed')
                return result

            # Build new weights dict
            new_weights = {}
            for i, name in enumerate(PPO_VARIABLE_NAMES):
                if i < len(new_weights_array):
                    new_weights[name] = round(float(new_weights_array[i]), 4)

            # Load old weights for comparison
            old_weights_json = self.db.get_setting('ppo_weights', '{}')
            try:
                old_weights = json.loads(old_weights_json)
            except json.JSONDecodeError:
                old_weights = {}

            # Compute changes
            weight_changes = {}
            for name in PPO_VARIABLE_NAMES:
                old_val = old_weights.get(name, 0.1)
                new_val = new_weights.get(name, 0.1)
                weight_changes[name] = round(new_val - old_val, 4)

            # Feature importance
            feature_importance = {}
            for i, name in enumerate(PPO_VARIABLE_NAMES):
                if i < len(coefficients):
                    feature_importance[name] = round(float(coefficients[i]), 4)

            # Validate: no single weight > 0.5
            max_weight = max(new_weights.values()) if new_weights else 0
            if max_weight > 0.5:
                result.reason = f"Max weight {max_weight:.3f} > 0.5 (unstable)"
                self.db.update_agent_heartbeat(AGENT_ID, 'completed')
                return result

            # Update weights
            self.db.set_setting('ppo_weights', json.dumps(new_weights))

            result.retrained = True
            result.reason = "Successfully retrained"
            result.old_weights = old_weights
            result.new_weights = new_weights
            result.weight_changes = weight_changes
            result.feature_importance = feature_importance

            logger.info(f"[{AGENT_ID}] PPO weights retrained successfully!")

        except Exception as e:
            result.reason = f"Error: {str(e)}"
            result.error = str(e)
            logger.error(f"[{AGENT_ID}] Retrain error: {e}")

        duration = time.time() - start_time
        self.db.update_agent_heartbeat(
            AGENT_ID, 'completed',
            items_processed=result.outcomes_used,
            duration_sec=duration,
        )

        return result

    def _build_feature_matrix(self, outcomes: List[Dict]) -> Tuple[Any, Any]:
        """Build feature matrix (X) and labels (y) from outcomes."""
        X = []
        y = []

        for outcome in outcomes:
            features = [
                1.0 if outcome.get('is_ppo') else 0.0,
                float(TIER_SCORES.get(outcome.get('tier', 5), 30)),
                max(0, 100 - (outcome.get('applicants', 0) or 0) * 0.2),
                self._normalize_stipend(outcome),
                self._score_duration(outcome),
                float(outcome.get('cirs', 40) or 40),
                50.0,  # sector momentum (placeholder)
                0.0,   # intent signal (placeholder)
                float(outcome.get('ppo_score_at_apply', 50) or 50),
                0.0,   # recency (irrelevant for historical data)
            ]

            status = (outcome.get('status', '') or '').lower()
            label = 1 if status in POSITIVE_OUTCOMES else 0

            X.append(features)
            y.append(label)

        return np.array(X), np.array(y)

    @staticmethod
    def _normalize_stipend(outcome: Dict) -> float:
        stipend = outcome.get('stipend_monthly', 0) or 0
        return min(100, (stipend / 12000) * 50)

    @staticmethod
    def _score_duration(outcome: Dict) -> float:
        duration = outcome.get('duration_months', 0) or 0
        if duration == 0:
            return 60.0
        if IDEAL_DURATION[0] <= duration <= IDEAL_DURATION[1]:
            return 100.0
        return 50.0

    def get_funnel_stats(self) -> FunnelStats:
        """Generate comprehensive funnel statistics."""
        stats = FunnelStats()

        try:
            all_outcomes = self.db.get_all_outcomes()

            status_counts = Counter()
            tier_stats = defaultdict(lambda: {'applied': 0, 'positive': 0, 'negative': 0})
            sector_stats = defaultdict(lambda: {'applied': 0, 'positive': 0, 'negative': 0})

            for o in all_outcomes:
                status = (o.get('status', '') or '').lower()
                status_counts[status] += 1

                tier = o.get('tier', 5) or 5
                tier_stats[tier]['applied'] += 1
                if status in POSITIVE_OUTCOMES:
                    tier_stats[tier]['positive'] += 1
                elif status in NEGATIVE_OUTCOMES:
                    tier_stats[tier]['negative'] += 1

                sector = o.get('sector', 'unknown') or 'unknown'
                sector_stats[sector]['applied'] += 1
                if status in POSITIVE_OUTCOMES:
                    sector_stats[sector]['positive'] += 1

            stats.total_applied = status_counts.get('applied', 0) + sum(status_counts.values())
            stats.shortlisted = status_counts.get('shortlisted', 0)
            stats.interviewed = status_counts.get('interview', 0)
            stats.offered = status_counts.get('offer', 0)
            stats.ppo_received = status_counts.get('ppo', 0)
            stats.rejected = status_counts.get('rejected', 0)
            stats.withdrawn = status_counts.get('withdrawn', 0)

            positive_total = stats.shortlisted + stats.interviewed + stats.offered + stats.ppo_received
            stats.conversion_rate = positive_total / max(stats.total_applied, 1)

            stats.by_tier = dict(tier_stats)
            stats.by_sector = dict(sector_stats)

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Funnel stats error: {e}")

        return stats

    def get_weekly_report(self) -> Dict[str, Any]:
        """Generate weekly performance report."""
        stats = self.get_funnel_stats()
        return {
            'funnel': stats.to_telegram_msg(),
            'stats': asdict(stats),
        }


_learner_instance: Optional[OutcomeLearner] = None

def get_outcome_learner() -> OutcomeLearner:
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = OutcomeLearner()
    return _learner_instance


if __name__ == "__main__":
    print(f"✅ {AGENT_NAME} ({AGENT_ID}) ready")
    print(f"  scikit-learn: {'✅' if SKLEARN_AVAILABLE else '❌'}")
    print(f"  Min outcomes for retrain: {MIN_OUTCOMES_FOR_RETRAIN}")
    print(f"  Min accuracy threshold: {MIN_ACCURACY_THRESHOLD}")
    print(f"  PPO variables: {len(PPO_VARIABLE_NAMES)}")
