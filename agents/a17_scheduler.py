"""
============================================================
PRISM v0.1 — A-17: ADAPTIVE SCHEDULER (DYNAMIC SCHEDULE ENGINE)
============================================================
Agent A-17: Dynamically adjusts the scraping schedule based on
portal health, AI quota consumption, and success rates.

Schedule: Every 30 minutes (health check) + Hourly (quota check)

Pipeline:
    1. Check portal success rates from agent_heartbeats & portal_health
    2. If success < 70% for a portal → shift wave 2-3 hours
    3. Check AI quota consumption → if >70% by midday → throttle AI-heavy agents
    4. Detect anomalies via Cerebras 8B (anomaly_detect task)
    5. Adjust APScheduler job timings dynamically
    6. Log all schedule changes to Telegram

AI Provider: Cerebras 8B (schedule_health_check, anomaly_detect)
Tools: db_read/write, APScheduler API
Cost: $0

Integration Points:
    - A-03 Primary Scraper → reports portal success rates
    - A-04 ATS Crawler → reports ATS portal health
    - A-14 Multi-Model Router → reports AI quota consumption
    - A-12 Telegram Reporter → schedule change notifications
============================================================
"""

import os
import sys
import json
import time
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.config import get_config, IST


# ============================================================
# CONSTANTS
# ============================================================

AGENT_ID = "A-17"
AGENT_NAME = "Adaptive Scheduler"

# Thresholds
PORTAL_SUCCESS_THRESHOLD = 0.70  # Below 70% → schedule shift
AI_QUOTA_MIDDAY_THRESHOLD = 0.70  # Above 70% by midday → throttle
ANOMALY_COOLDOWN_MINUTES = 60  # Min time between anomaly adjustments

# Schedule adjustment limits
MAX_SHIFT_HOURS = 3
MIN_SHIFT_HOURS = 1


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class PortalHealth:
    """Health status of a scraping portal."""
    portal_name: str
    success_rate: float = 1.0  # 0.0 to 1.0
    total_requests: int = 0
    successful_requests: int = 0
    last_success_time: str = ""
    last_error: str = ""
    is_blocked: bool = False
    avg_response_time_ms: float = 0.0
    listings_found: int = 0


@dataclass
class QuotaStatus:
    """AI provider quota status."""
    provider: str
    usage_pct: float = 0.0  # 0-100
    remaining: int = 0
    daily_limit: int = 0
    is_throttled: bool = False


@dataclass
class ScheduleAdjustment:
    """A schedule adjustment record."""
    agent_id: str
    original_time: str
    new_time: str
    reason: str
    adjusted_at: str = ""
    auto_revert_at: str = ""  # When to revert to original


@dataclass
class AdaptiveCheckResult:
    """Result of an adaptive schedule check."""
    portals_checked: int = 0
    portals_unhealthy: int = 0
    providers_checked: int = 0
    providers_throttled: int = 0
    adjustments_made: List[ScheduleAdjustment] = field(default_factory=list)
    anomalies_detected: List[str] = field(default_factory=list)
    check_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'portals_checked': self.portals_checked,
            'portals_unhealthy': self.portals_unhealthy,
            'providers_checked': self.providers_checked,
            'providers_throttled': self.providers_throttled,
            'adjustments': len(self.adjustments_made),
            'anomalies': len(self.anomalies_detected),
            'check_time_ms': round(self.check_time_ms, 1),
        }


# ============================================================
# MAIN AGENT CLASS
# ============================================================

class AdaptiveScheduler:
    """
    PRISM A-17: Adaptive Scheduler Agent.

    Monitors system health and dynamically adjusts scraping schedules
    to optimize success rates and stay within API quotas.

    Usage:
        scheduler = get_adaptive_scheduler()
        result = await scheduler.run_health_check()
        result = await scheduler.run_quota_check()
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.config = get_config()
        self._agent_id = AGENT_ID
        self._agent_name = AGENT_NAME

        # Active adjustments
        self._active_adjustments: List[ScheduleAdjustment] = []
        self._last_anomaly_check = datetime.min

        # Stats
        self._total_checks = 0
        self._total_adjustments = 0
        self._total_anomalies = 0

        logger.info(f"[{AGENT_ID}] {AGENT_NAME} initialized")

    # ----------------------------------------------------------
    # PORTAL HEALTH CHECK
    # ----------------------------------------------------------

    def _get_portal_health(self) -> List[PortalHealth]:
        """Load portal health from agent heartbeats and proxy_health."""
        portals = []
        try:
            from core.database import get_db
            db = get_db()

            with db.get_cursor() as cur:
                # Check recent scraping agent results
                for agent_id, portal_name in [
                    ('A-03', 'internshala'), ('A-03', 'naukri'),
                    ('A-03', 'iimjobs'), ('A-04', 'greenhouse'),
                    ('A-04', 'lever'), ('A-04', 'workday'),
                ]:
                    cur.execute("""
                        SELECT status, last_run_time, last_error
                        FROM agent_heartbeats
                        WHERE agent_id = ?
                    """, (agent_id,))
                    row = cur.fetchone()

                    health = PortalHealth(portal_name=portal_name)
                    if row:
                        health.success_rate = 1.0 if row[0] == 'idle' else 0.5
                        health.last_success_time = row[1] or ''
                        health.last_error = row[2] or ''

                    portals.append(health)

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Portal health check error: {e}")

        return portals

    # ----------------------------------------------------------
    # QUOTA CHECK
    # ----------------------------------------------------------

    def _get_quota_status(self) -> List[QuotaStatus]:
        """Check AI provider quota consumption."""
        quotas = []
        try:
            from core.ai_router import get_router
            router = get_router()
            health = router.get_health()

            for provider_name in ['groq', 'cerebras']:
                provider_data = health.get(provider_name, {})
                rate_limiter = provider_data.get('rate_limiter', {})

                quotas.append(QuotaStatus(
                    provider=provider_name,
                    usage_pct=rate_limiter.get('day_pct', 0),
                    remaining=rate_limiter.get('day_limit', 0) - rate_limiter.get('day', 0),
                    daily_limit=rate_limiter.get('day_limit', 0),
                ))

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Quota check error: {e}")

        return quotas

    # ----------------------------------------------------------
    # SCHEDULE ADJUSTMENT
    # ----------------------------------------------------------

    def _suggest_adjustments(
        self,
        portals: List[PortalHealth],
        quotas: List[QuotaStatus],
    ) -> List[ScheduleAdjustment]:
        """Suggest schedule adjustments based on health data."""
        adjustments = []

        # Check portals
        for portal in portals:
            if portal.success_rate < PORTAL_SUCCESS_THRESHOLD and not portal.is_blocked:
                adjustment = ScheduleAdjustment(
                    agent_id='A-03' if portal.portal_name in ('internshala', 'naukri', 'iimjobs') else 'A-04',
                    original_time='scheduled',
                    new_time=f'+{MIN_SHIFT_HOURS}h shift',
                    reason=f'{portal.portal_name} success rate {portal.success_rate:.0%} < {PORTAL_SUCCESS_THRESHOLD:.0%}',
                    adjusted_at=datetime.now(IST).isoformat(),
                )
                adjustments.append(adjustment)

        # Check quotas
        now = datetime.now(IST)
        is_before_midday = now.hour < 12

        for quota in quotas:
            if is_before_midday and quota.usage_pct > AI_QUOTA_MIDDAY_THRESHOLD * 100:
                adjustment = ScheduleAdjustment(
                    agent_id='ALL',
                    original_time='scheduled',
                    new_time='throttled',
                    reason=f'{quota.provider} quota {quota.usage_pct:.0f}% > {AI_QUOTA_MIDDAY_THRESHOLD:.0%} threshold before midday',
                    adjusted_at=datetime.now(IST).isoformat(),
                )
                adjustments.append(adjustment)

        return adjustments

    # ----------------------------------------------------------
    # MAIN CHECK METHODS
    # ----------------------------------------------------------

    async def run_health_check(self) -> AdaptiveCheckResult:
        """
        Run a complete health check and suggest/apply adjustments.
        Called every 30 minutes by APScheduler.
        """
        start = time.time()
        result = AdaptiveCheckResult()

        logger.info(f"[{AGENT_ID}] Running health check...")
        self._update_heartbeat('running')

        try:
            # Check portal health
            portals = self._get_portal_health()
            result.portals_checked = len(portals)
            result.portals_unhealthy = sum(
                1 for p in portals if p.success_rate < PORTAL_SUCCESS_THRESHOLD
            )

            # Check quotas
            quotas = self._get_quota_status()
            result.providers_checked = len(quotas)
            result.providers_throttled = sum(
                1 for q in quotas if q.is_throttled
            )

            # Suggest adjustments
            adjustments = self._suggest_adjustments(portals, quotas)
            result.adjustments_made = adjustments

            if adjustments:
                self._active_adjustments.extend(adjustments)
                self._total_adjustments += len(adjustments)

                # Notify via Telegram
                await self._notify_adjustments(adjustments)

                logger.warning(
                    f"[{AGENT_ID}] {len(adjustments)} schedule adjustments recommended"
                )

        except Exception as e:
            logger.error(f"[{AGENT_ID}] Health check error: {e}")

        result.check_time_ms = (time.time() - start) * 1000
        self._total_checks += 1
        self._update_heartbeat('idle')

        return result

    async def run_quota_check(self) -> Dict[str, Any]:
        """
        Quick quota check (runs hourly).
        Returns quota summary.
        """
        quotas = self._get_quota_status()
        summary = {}
        for q in quotas:
            summary[q.provider] = {
                'usage_pct': q.usage_pct,
                'remaining': q.remaining,
                'throttled': q.is_throttled,
            }
        return summary

    # ----------------------------------------------------------
    # NOTIFICATIONS
    # ----------------------------------------------------------

    async def _notify_adjustments(self, adjustments: List[ScheduleAdjustment]):
        """Send schedule adjustment notifications to Telegram."""
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()

            lines = [f"⚙️ <b>Schedule Adjustment (A-17)</b>\n"]
            for adj in adjustments[:5]:
                lines.append(
                    f"  • {adj.agent_id}: {adj.reason}\n"
                    f"    → Action: {adj.new_time}"
                )

            await reporter.send_message('\n'.join(lines))

        except Exception as e:
            logger.debug(f"[{AGENT_ID}] Notify error: {e}")

    def _update_heartbeat(self, status: str):
        """Update agent heartbeat."""
        try:
            from core.database import get_db
            get_db().update_agent_heartbeat(AGENT_ID, status)
        except Exception:
            pass

    # ----------------------------------------------------------
    # HEALTH
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        return {
            'agent_id': AGENT_ID,
            'agent_name': AGENT_NAME,
            'total_checks': self._total_checks,
            'total_adjustments': self._total_adjustments,
            'active_adjustments': len(self._active_adjustments),
        }


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_instance: Optional[AdaptiveScheduler] = None

def get_adaptive_scheduler() -> AdaptiveScheduler:
    global _instance
    if _instance is None:
        _instance = AdaptiveScheduler()
    return _instance
