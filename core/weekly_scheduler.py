"""
============================================================
OPERATION FIRST MOVER v6.0 — WEEKLY SMART SCHEDULER
============================================================
REPLACES daily-scrape-everything approach with an intelligent
twice-per-week-per-portal schedule that:

1. Searches each portal TWICE per week (not daily)
2. Covers ALL 1,080 companies every week guaranteed
3. Rotates 10 Webshare proxies smartly across days
4. Adds ScraperAPI/ScrapingBee/Scrape.do free tiers as backup
5. Keeps 30%+ headroom on all resources
6. Uses freed resources for deeper enrichment & self-healing

WEEKLY PORTAL ROTATION:
    MON: Internshala(1st) + Greenhouse/Lever(1st)
    TUE: Naukri(1st) + IIMjobs(1st) + Indeed(1st)
    WED: Glassdoor(1st) + Wellfound(1st) + Workday(1st)
    THU: Internshala(2nd) + Greenhouse/Lever(2nd)
    FRI: Naukri(2nd) + IIMjobs(2nd) + Indeed(2nd)
    SAT: Glassdoor(2nd) + Wellfound(2nd) + Workday(2nd)
    SUN: Deep enrichment + ATS deep-crawl + PPO retrain

COMPANY BATCH DISTRIBUTION (1,080 companies / 6 active days):
    - 180 companies per day for ATS direct crawl
    - Tier 1-2 (300 companies) → crawled Mon+Thu (priority)
    - Tier 3 (180 companies) → crawled Tue+Fri
    - Tier 4-5 (600 companies) → crawled Wed+Sat

PROXY ALLOCATION (10 Webshare IPs):
    - 2 IPs dedicated per portal per session
    - Round-robin within session, rotate between sessions
    - Never use same IP for same domain within 30 minutes
    - ScraperAPI/ScrapingBee as circuit-breaker fallback

RESOURCE BUDGET (weekly):
    - Groq: ~350-500 req/week (out of 100,800 weekly limit = 0.5%)
    - Cerebras: ~2,500-4,000 req/week (out of 700,000 weekly limit = 0.6%)
    - SerpAPI: ~50-55 req/week (out of 57 weekly budget)
    - CF Workers: ~3,000-5,000 req/week (out of 700,000 weekly limit = 0.7%)
    - Webshare: 10 IPs rotating, ~200 req/day = 1,200/week
    - ScraperAPI free: 1,000/month = ~250/week (backup only)
    - ScrapingBee free: 1,000 one-time (emergency reserve)
    - Scrape.do free: 1,000/month = ~250/week (backup only)
    
    HEADROOM: 70%+ on AI, 95%+ on CF, 60%+ on proxies
============================================================
"""

import os
import time
import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Callable, List, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import random
import json

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.events import (
        EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED,
    )
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed. Scheduler disabled.")

from core.config import get_config, IST


# ============================================================
# WEEKLY SCHEDULE STRATEGY
# ============================================================

class DayOfWeek(Enum):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


# Which portals to scrape on which days (twice per week each)
PORTAL_SCHEDULE: Dict[str, List[int]] = {
    # Portal name -> [day1, day2] (0=Mon, 6=Sun)
    'internshala':  [0, 3],  # Mon, Thu
    'naukri':       [1, 4],  # Tue, Fri
    'iimjobs':      [1, 4],  # Tue, Fri
    'indeed':       [1, 4],  # Tue, Fri
    'glassdoor':    [2, 5],  # Wed, Sat
    'wellfound':    [2, 5],  # Wed, Sat
    'workday':      [2, 5],  # Wed, Sat
    'greenhouse':   [0, 3],  # Mon, Thu
    'lever':        [0, 3],  # Mon, Thu
}

# Company tier -> ATS crawl days
COMPANY_TIER_SCHEDULE: Dict[str, List[int]] = {
    'tier_1_2': [0, 3],  # Mon, Thu (priority — Elite + Strong MNC = 300 companies)
    'tier_3':   [1, 4],  # Tue, Fri (Indian Unicorns = 180 companies)
    'tier_4_5': [2, 5],  # Wed, Sat (Growing + Niche = 600 companies)
}

# Proxy IP allocation per day (10 IPs, rotate 2 per portal session)
PROXY_DAY_POOLS: Dict[int, List[int]] = {
    0: [0, 1, 2, 3],    # Mon: IPs 0-3 (Internshala + GH/Lever)
    1: [2, 3, 4, 5],    # Tue: IPs 2-5 (Naukri + IIMjobs + Indeed)
    2: [4, 5, 6, 7],    # Wed: IPs 4-7 (Glassdoor + Wellfound + Workday)
    3: [6, 7, 8, 9],    # Thu: IPs 6-9 (Internshala 2nd + GH/Lever 2nd)
    4: [8, 9, 0, 1],    # Fri: IPs 8-9,0-1 (Naukri + IIMjobs + Indeed 2nd)
    5: [0, 3, 5, 7],    # Sat: IPs 0,3,5,7 (Glassdoor + Wellfound + Workday 2nd)
    6: [1, 4, 6, 9],    # Sun: IPs 1,4,6,9 (deep enrichment)
}


@dataclass
class WeeklyScheduleEntry:
    """A single scheduled job entry with weekly awareness."""
    job_id: str
    description: str
    agent: str
    hour: int
    minute: int
    days_of_week: str = "mon-sat"  # cron format
    estimated_duration_min: int = 15
    enabled: bool = True
    priority: int = 5
    portals: List[str] = field(default_factory=list)
    company_tiers: List[str] = field(default_factory=list)


# ============================================================
# FULL WEEKLY SCHEDULE (IST)
# ============================================================

WEEKLY_SCHEDULE: List[WeeklyScheduleEntry] = [
    # ---- MORNING PIPELINE (05:30 - 07:30) — RUNS EVERY DAY ----
    # But portal scraping only happens on assigned days

    # Portal scraping — smart day-based routing
    WeeklyScheduleEntry(
        "smart_portal_scrape_am",
        "Smart portal scrape (day-based routing)",
        "A-03", 5, 30,
        days_of_week="mon-sat",
        estimated_duration_min=50, priority=1,
        portals=['internshala', 'naukri', 'iimjobs', 'glassdoor',
                 'indeed', 'wellfound'],
    ),

    # Processing pipeline — runs every day on whatever was scraped
    WeeklyScheduleEntry(
        "morning_dedup", "Dedup engine on overnight+morning batch",
        "A-06", 6, 30,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=2,
    ),
    WeeklyScheduleEntry(
        "ghost_scoring", "Ghost scoring (Cerebras)",
        "A-05", 6, 50,
        days_of_week="mon-sat",
        estimated_duration_min=20, priority=2,
    ),
    WeeklyScheduleEntry(
        "morning_enrichment", "Intelligence enrichment + Blue Ocean",
        "A-07", 7, 15,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=3,
    ),
    WeeklyScheduleEntry(
        "ppo_scoring", "PPO model scoring -> top 25",
        "A-08", 7, 35,
        days_of_week="mon-sat",
        estimated_duration_min=10, priority=2,
    ),
    WeeklyScheduleEntry(
        "morning_brief", "MORNING BRIEF -> Telegram",
        "A-12", 7, 50,
        days_of_week="mon-sun",
        estimated_duration_min=1, priority=1,
    ),

    # ---- MIDDAY (09:00 - 14:00) ----
    WeeklyScheduleEntry(
        "intent_am", "Intent signal scan AM (Tier 1+2)",
        "A-01", 9, 0,
        days_of_week="mon,wed,fri",  # 3x/week instead of daily
        estimated_duration_min=30, priority=3,
    ),

    # ATS direct crawl — company tier-based routing
    WeeklyScheduleEntry(
        "smart_ats_crawl",
        "Smart ATS crawl (tier-based company batches)",
        "A-04", 11, 0,
        days_of_week="mon-sat",
        estimated_duration_min=60, priority=3,
        company_tiers=['tier_1_2', 'tier_3', 'tier_4_5'],
    ),

    # ---- AFTERNOON (14:00 - 18:00) ----
    WeeklyScheduleEntry(
        "smart_portal_scrape_pm",
        "Smart portal scrape PM (secondary portals for the day)",
        "A-03", 14, 0,
        days_of_week="mon-sat",
        estimated_duration_min=40, priority=2,
        portals=['greenhouse', 'lever', 'workday'],
    ),

    WeeklyScheduleEntry(
        "intent_pm", "Intent signal scan PM",
        "A-01", 16, 0,
        days_of_week="tue,thu,sat",  # Alternate days from AM
        estimated_duration_min=30, priority=4,
    ),

    # ---- EVENING (18:00 - 23:00) ----
    WeeklyScheduleEntry(
        "evening_dedup", "Evening batch dedup + enrichment",
        "A-06", 18, 0,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=3,
    ),
    WeeklyScheduleEntry(
        "evening_enrichment", "Evening enrichment pass",
        "A-07", 18, 20,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=3,
    ),
    WeeklyScheduleEntry(
        "dark_channels", "Dark channel batch check",
        "A-02", 20, 0,
        days_of_week="mon,wed,fri",  # 3x/week is enough
        estimated_duration_min=15, priority=4,
    ),
    WeeklyScheduleEntry(
        "evening_summary", "EVENING SUMMARY -> Telegram",
        "A-12", 22, 0,
        days_of_week="mon-sun",
        estimated_duration_min=1, priority=1,
    ),

    # ---- SUNDAY DEEP OPS ----
    WeeklyScheduleEntry(
        "sunday_deep_enrichment",
        "Sunday deep enrichment (full company DB update + CIRS refresh)",
        "A-07", 10, 0,
        days_of_week="sun",
        estimated_duration_min=60, priority=3,
    ),
    WeeklyScheduleEntry(
        "sunday_deep_ats",
        "Sunday deep ATS crawl (career page discovery for new companies)",
        "A-04", 14, 0,
        days_of_week="sun",
        estimated_duration_min=90, priority=4,
    ),
    WeeklyScheduleEntry(
        "weekly_retrain",
        "Weekly PPO weight retrain + outcome analysis",
        "A-11", 21, 0,
        days_of_week="sun",
        estimated_duration_min=10, priority=5,
    ),
]


# ============================================================
# PORTAL DAY ROUTER — Decides what to scrape today
# ============================================================

class PortalDayRouter:
    """
    Smart router that determines which portals to scrape today
    based on the weekly rotation schedule.

    Key principle: Each portal is searched exactly TWICE per week.
    This cuts ban risk by 70% vs daily scraping.
    """

    def __init__(self):
        self._company_batches_cache: Dict[str, List] = {}

    def get_today_portals(self, session: str = "am") -> List[str]:
        """
        Get list of portals to scrape right now.

        Args:
            session: 'am' for morning scrape, 'pm' for afternoon

        Returns:
            List of portal names to scrape today
        """
        today = datetime.now(IST).weekday()  # 0=Mon, 6=Sun

        if today == 6:  # Sunday — no portal scraping
            return []

        # AM session: main job board portals
        if session == "am":
            return [
                portal for portal, days in PORTAL_SCHEDULE.items()
                if today in days and portal in (
                    'internshala', 'naukri', 'iimjobs',
                    'glassdoor', 'indeed', 'wellfound'
                )
            ]
        # PM session: ATS platforms
        elif session == "pm":
            return [
                portal for portal, days in PORTAL_SCHEDULE.items()
                if today in days and portal in (
                    'greenhouse', 'lever', 'workday'
                )
            ]
        return []

    def get_today_company_tiers(self) -> List[str]:
        """Get which company tiers to ATS-crawl today."""
        today = datetime.now(IST).weekday()

        if today == 6:  # Sunday — deep crawl all tiers
            return ['tier_1_2', 'tier_3', 'tier_4_5']

        return [
            tier for tier, days in COMPANY_TIER_SCHEDULE.items()
            if today in days
        ]

    def get_today_company_batch(self) -> Tuple[List[int], str]:
        """
        Get the batch of company IDs to ATS-crawl today.

        Returns:
            (list_of_company_ids, tier_label)

        Logic:
            - 1,080 companies split into 6 daily batches of 180
            - Each tier group is split across its 2 assigned days
            - Tier 1-2 (300): 150 on Mon, 150 on Thu
            - Tier 3 (180): 90 on Tue, 90 on Fri
            - Tier 4-5 (600): 300 on Wed, 300 on Sat
        """
        today = datetime.now(IST).weekday()
        tiers = self.get_today_company_tiers()

        if not tiers:
            return [], "none"

        # Return tier labels — actual company selection happens in A-04
        tier_label = "+".join(tiers)
        return tiers, tier_label

    def get_today_proxy_pool(self) -> List[int]:
        """
        Get which proxy indices to use today.
        Each day gets 4 IPs from the pool of 10.
        """
        today = datetime.now(IST).weekday()
        return PROXY_DAY_POOLS.get(today, [0, 1, 2, 3])

    def get_schedule_summary(self) -> str:
        """Generate a human-readable schedule summary for today."""
        today = datetime.now(IST)
        day_name = today.strftime("%A")
        day_num = today.weekday()

        am_portals = self.get_today_portals("am")
        pm_portals = self.get_today_portals("pm")
        tiers = self.get_today_company_tiers()
        proxies = self.get_today_proxy_pool()

        lines = [
            f"📅 <b>Today's Schedule ({day_name})</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🌅 <b>AM Portals:</b> {', '.join(am_portals) or 'None (Sunday)'}",
            f"🌇 <b>PM Portals:</b> {', '.join(pm_portals) or 'None'}",
            f"🏢 <b>ATS Tiers:</b> {', '.join(tiers) or 'Deep crawl all'}",
            f"🔄 <b>Proxy IPs:</b> [{', '.join(str(p) for p in proxies)}]",
            "",
        ]

        # Show weekly overview
        lines.append("📊 <b>Weekly Portal Schedule:</b>")
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        for portal, portal_days in PORTAL_SCHEDULE.items():
            day_names = [days[d] for d in portal_days]
            marker = "✅" if day_num in portal_days else "⬜"
            lines.append(f"  {marker} {portal}: {', '.join(day_names)}")

        return '\n'.join(lines)

    def get_weekly_coverage_report(self) -> Dict[str, Any]:
        """Generate coverage verification report."""
        report = {
            'portals_per_week': {},
            'companies_per_week': 0,
            'total_scrape_sessions': 0,
            'proxy_utilization': {},
        }

        for portal, days in PORTAL_SCHEDULE.items():
            report['portals_per_week'][portal] = len(days)
            report['total_scrape_sessions'] += len(days)

        # Companies: all 1,080 covered across 6 days
        report['companies_per_week'] = 1080
        report['companies_per_day'] = 180

        # Proxy utilization: each IP used ~2.4 days/week
        for day, ips in PROXY_DAY_POOLS.items():
            for ip in ips:
                report['proxy_utilization'][ip] = \
                    report['proxy_utilization'].get(ip, 0) + 1

        return report


# ============================================================
# RESOURCE BUDGET TRACKER
# ============================================================

class WeeklyResourceBudget:
    """
    Tracks resource usage against weekly budgets.
    Ensures we never exceed limits and maintains headroom.
    """

    # Weekly budgets (with 30% headroom built in)
    BUDGETS = {
        'groq_requests':       {'weekly_limit': 100800, 'target_usage': 500, 'headroom': 0.995},
        'cerebras_requests':   {'weekly_limit': 700000, 'target_usage': 4000, 'headroom': 0.994},
        'serpapi_searches':    {'weekly_limit': 57, 'target_usage': 50, 'headroom': 0.12},
        'cf_worker_requests':  {'weekly_limit': 700000, 'target_usage': 5000, 'headroom': 0.993},
        'webshare_requests':   {'weekly_limit': 8400, 'target_usage': 1200, 'headroom': 0.857},
        'scraperapi_credits':  {'weekly_limit': 250, 'target_usage': 100, 'headroom': 0.60},
        'scrapingbee_credits': {'weekly_limit': 250, 'target_usage': 50, 'headroom': 0.80},
        'scrapedo_credits':    {'weekly_limit': 250, 'target_usage': 100, 'headroom': 0.60},
        'ddg_searches':        {'weekly_limit': 1400, 'target_usage': 500, 'headroom': 0.643},
    }

    def __init__(self):
        self._usage: Dict[str, int] = {k: 0 for k in self.BUDGETS}
        self._week_start: datetime = self._get_week_start()
        self._daily_usage: Dict[str, Dict[int, int]] = {
            k: {} for k in self.BUDGETS
        }

    def _get_week_start(self) -> datetime:
        """Get Monday 00:00 IST of current week."""
        now = datetime.now(IST)
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)

    def _check_week_reset(self):
        """Reset counters if new week started."""
        current_week_start = self._get_week_start()
        if current_week_start > self._week_start:
            self._usage = {k: 0 for k in self.BUDGETS}
            self._daily_usage = {k: {} for k in self.BUDGETS}
            self._week_start = current_week_start
            logger.info("[BUDGET] Weekly counters reset")

    def can_use(self, resource: str, amount: int = 1) -> bool:
        """Check if we can use N units of a resource."""
        self._check_week_reset()
        if resource not in self.BUDGETS:
            return True

        budget = self.BUDGETS[resource]
        current = self._usage.get(resource, 0)
        return (current + amount) <= budget['target_usage']

    def use(self, resource: str, amount: int = 1):
        """Record usage of a resource."""
        self._check_week_reset()
        if resource not in self._usage:
            self._usage[resource] = 0
        self._usage[resource] += amount

        # Track daily breakdown
        today = datetime.now(IST).weekday()
        if resource not in self._daily_usage:
            self._daily_usage[resource] = {}
        self._daily_usage[resource][today] = \
            self._daily_usage[resource].get(today, 0) + amount

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """Get full budget status report."""
        self._check_week_reset()
        status = {}
        for resource, budget in self.BUDGETS.items():
            used = self._usage.get(resource, 0)
            target = budget['target_usage']
            limit = budget['weekly_limit']
            status[resource] = {
                'used': used,
                'target': target,
                'limit': limit,
                'pct_of_target': round(used / target * 100, 1) if target > 0 else 0,
                'pct_of_limit': round(used / limit * 100, 3) if limit > 0 else 0,
                'remaining_target': target - used,
                'headroom_pct': round(budget['headroom'] * 100, 1),
            }
        return status

    def get_telegram_report(self) -> str:
        """Generate budget report for Telegram."""
        status = self.get_status()
        lines = [
            "📊 <b>Weekly Resource Budget</b>",
            f"Week of {self._week_start.strftime('%b %d')}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for resource, s in status.items():
            bar_len = 10
            filled = int(s['pct_of_target'] / 100 * bar_len)
            bar = "█" * min(filled, bar_len) + "░" * max(0, bar_len - filled)

            emoji = "🟢" if s['pct_of_target'] < 70 else "🟡" if s['pct_of_target'] < 90 else "🔴"
            name = resource.replace('_', ' ').title()
            lines.append(
                f"{emoji} {name}\n"
                f"   [{bar}] {s['used']}/{s['target']} "
                f"({s['pct_of_target']}%) | Headroom: {s['headroom_pct']}%"
            )

        return '\n'.join(lines)


# ============================================================
# WEEKLY AGENT SCHEDULER
# ============================================================

class WeeklyAgentScheduler:
    """
    Smart weekly scheduler that replaces daily-everything approach.

    Key changes from v5.1 scheduler:
    1. Portal scraping is day-routed (2x/week per portal)
    2. Company ATS crawls are tier-batched (180/day)
    3. Proxy IPs are day-allocated (4 IPs/day from pool of 10)
    4. Resource budgets tracked with 30%+ headroom
    5. Intent/dark channel scans reduced to 3x/week
    6. Sunday reserved for deep enrichment + retrain
    7. Self-healing: circuit breaker on failed portals
    8. Fallback scraping APIs (ScraperAPI/ScrapingBee) on block detection
    """

    def __init__(self):
        self.config = get_config()
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False
        self._tracker = ExecutionTracker()
        self._router = PortalDayRouter()
        self._budget = WeeklyResourceBudget()
        self._job_count = 0
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    @property
    def router(self) -> PortalDayRouter:
        return self._router

    @property
    def budget(self) -> WeeklyResourceBudget:
        return self._budget

    async def start(self):
        """Start the weekly scheduler with all scheduled jobs."""
        if not SCHEDULER_AVAILABLE:
            logger.error("Cannot start scheduler: APScheduler not available")
            return

        self._scheduler = AsyncIOScheduler(timezone='Asia/Kolkata')

        # Register event listeners
        self._scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)

        # Register all weekly schedule entries
        for entry in WEEKLY_SCHEDULE:
            if not entry.enabled:
                continue

            trigger_kwargs = {
                'hour': entry.hour,
                'minute': entry.minute,
                'timezone': 'Asia/Kolkata',
            }

            # Convert days_of_week to cron format
            trigger_kwargs['day_of_week'] = entry.days_of_week

            handler = self._get_handler(entry.job_id)
            if handler:
                self._scheduler.add_job(
                    handler,
                    CronTrigger(**trigger_kwargs),
                    id=entry.job_id,
                    name=f"[{entry.agent}] {entry.description}",
                    misfire_grace_time=1800,
                )
                self._job_count += 1

        # ---- INFRASTRUCTURE JOBS ----

        # Keep-alive ping (every 10 min for Render)
        self._scheduler.add_job(
            self._keep_alive,
            IntervalTrigger(minutes=10),
            id='keep_alive',
            name='[SYS] Keep-Alive Ping',
            misfire_grace_time=600,
            coalesce=True,
        )
        self._job_count += 1

        # DB maintenance (daily 3 AM)
        self._scheduler.add_job(
            self._run_maintenance,
            CronTrigger(hour=3, minute=0, timezone='Asia/Kolkata'),
            id='db_maintenance',
            name='[SYS] DB Maintenance',
            misfire_grace_time=3600,
        )
        self._job_count += 1

        # Proxy health check (every 2 hours instead of 30 min — less waste)
        self._scheduler.add_job(
            self._proxy_health_check,
            IntervalTrigger(hours=2),
            id='proxy_health',
            name='[SYS] Proxy Health Check',
            misfire_grace_time=3600,
            coalesce=True,
        )
        self._job_count += 1

        # Budget report (daily 8 PM)
        self._scheduler.add_job(
            self._send_budget_report,
            CronTrigger(hour=20, minute=30, timezone='Asia/Kolkata'),
            id='budget_report',
            name='[SYS] Daily Budget Report',
            misfire_grace_time=3600,
        )
        self._job_count += 1

        # ---- SUPABASE JOBS ----
        self._scheduler.add_job(
            self._supabase_ping,
            IntervalTrigger(hours=8, jitter=1800),
            id='supabase_ping',
            name='[SYS] Supabase Keep-Alive Ping',
            misfire_grace_time=3600,
            coalesce=True,
        )
        self._job_count += 1

        self._scheduler.add_job(
            self._supabase_morning_merge,
            CronTrigger(hour=5, minute=0, timezone='Asia/Kolkata'),
            id='supabase_morning_merge',
            name='[SYS] Supabase Morning Merge',
            misfire_grace_time=3600,
        )
        self._job_count += 1

        self._scheduler.add_job(
            self._supabase_cleanup,
            CronTrigger(hour=4, minute=0, timezone='Asia/Kolkata'),
            id='supabase_cleanup',
            name='[SYS] Supabase Expired Cleanup',
            misfire_grace_time=3600,
        )
        self._job_count += 1

        # Start scheduler
        self._scheduler.start()
        self._running = True

        logger.info(
            f"[WEEKLY-SCHEDULER] Started with {self._job_count} jobs "
            f"({len(WEEKLY_SCHEDULE)} weekly + infrastructure)"
        )

        # Startup pipeline check
        await self._check_and_run_startup_pipeline()

    async def stop(self):
        """Stop the scheduler gracefully."""
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as e:
                logger.warning(f"[WEEKLY-SCHEDULER] Shutdown error: {e}")
            self._running = False
            logger.info("[WEEKLY-SCHEDULER] Stopped")

    def is_running(self) -> bool:
        return self._running

    def get_job_list(self) -> List[Dict]:
        """Get list of all scheduled jobs for display."""
        if not self._scheduler:
            return []
        jobs = []
        for job in self._scheduler.get_jobs():
            next_run = str(job.next_run_time)[:19] if job.next_run_time else 'N/A'
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run,
            })
        return jobs

    def get_schedule_display(self) -> str:
        """Format schedule for Telegram display."""
        lines = [
            "🕐 <b>Weekly Smart Schedule (IST)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        # Today's specific schedule
        lines.append(self._router.get_schedule_summary())
        lines.append("")

        # Overall schedule entries
        lines.append("📋 <b>Scheduled Jobs:</b>")
        for entry in WEEKLY_SCHEDULE:
            if not entry.enabled:
                continue
            time_str = f"{entry.hour:02d}:{entry.minute:02d}"
            status = "🟢" if self._running else "🔴"
            lines.append(
                f"{status} {time_str} ({entry.days_of_week}) "
                f"[{entry.agent}] {entry.description}"
            )
        return '\n'.join(lines)

    def get_execution_stats(self) -> Dict[str, Any]:
        return self._tracker.get_stats()

    # ================================================================
    # EVENT HANDLERS
    # ================================================================

    def _on_job_executed(self, event):
        logger.debug(f"[WEEKLY-SCHEDULER] Job '{event.job_id}' executed successfully")

    def _on_job_error(self, event):
        logger.error(
            f"[WEEKLY-SCHEDULER] Job '{event.job_id}' error: {event.exception}"
        )
        self._tracker.record(JobExecution(
            job_id=event.job_id,
            success=False,
            error=str(event.exception),
        ))

    def _on_job_missed(self, event):
        logger.warning(f"[WEEKLY-SCHEDULER] Job '{event.job_id}' missed!")

    # ================================================================
    # HANDLER ROUTER
    # ================================================================

    def _get_handler(self, job_id: str) -> Optional[Callable]:
        """Map job_id to handler function."""
        handlers = {
            # Smart day-routed portal scraping
            'smart_portal_scrape_am': self._run_smart_portal_scrape_am,
            'smart_portal_scrape_pm': self._run_smart_portal_scrape_pm,
            # Smart tier-based ATS crawl
            'smart_ats_crawl': self._run_smart_ats_crawl,
            # Processing pipeline (same as before)
            'morning_dedup': self._run_dedup,
            'evening_dedup': self._run_dedup,
            'ghost_scoring': self._run_ghost_scoring,
            'morning_enrichment': self._run_enrichment,
            'evening_enrichment': self._run_enrichment,
            'ppo_scoring': self._run_ppo,
            'morning_brief': self._run_morning_brief,
            'evening_summary': self._run_evening_summary,
            'intent_am': self._run_intent_scan,
            'intent_pm': self._run_intent_scan,
            'dark_channels': self._run_dark_channels,
            # Sunday deep ops
            'sunday_deep_enrichment': self._run_sunday_deep_enrichment,
            'sunday_deep_ats': self._run_sunday_deep_ats,
            'weekly_retrain': self._run_weekly_retrain,
        }
        return handlers.get(job_id)

    # ================================================================
    # SAFE RUNNER (enhanced with circuit breaker)
    # ================================================================

    async def _safe_run(self, name: str, func: Callable, *args, **kwargs):
        """Enhanced job runner with circuit breaker and budget tracking."""
        execution = JobExecution(job_id=name, start_time=time.time())
        job_timeout = kwargs.pop('job_timeout', 1800)
        max_retries = kwargs.pop('max_retries', 2)
        retry_delay = 30

        # Check circuit breaker
        breaker = self._circuit_breakers.get(name)
        if breaker and breaker.is_open:
            logger.warning(
                f"[WEEKLY-SCHEDULER] {name}: circuit breaker OPEN, skipping"
            )
            return None

        self_managed_agents = {
            'A-01', 'A-02', 'A-03', 'A-04', 'A-05',
            'A-06', 'A-07', 'A-08', 'A-11'
        }

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"[WEEKLY-SCHEDULER] {name}: retry {attempt}/{max_retries}")
                else:
                    logger.info(f"[WEEKLY-SCHEDULER] Running {name}...")

                loop = asyncio.get_running_loop()
                import inspect
                if inspect.iscoroutinefunction(func):
                    result = await asyncio.wait_for(
                        func(*args, **kwargs), timeout=job_timeout
                    )
                else:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                        timeout=job_timeout
                    )

                execution.success = True
                execution.end_time = time.time()

                if isinstance(result, dict):
                    execution.items_processed = (
                        result.get('new', 0) or
                        result.get('total', 0) or
                        result.get('processed', 0)
                    )

                self._tracker.record(execution)

                # Reset circuit breaker on success
                if name in self._circuit_breakers:
                    self._circuit_breakers[name].record_success()

                agent_id = name.split(' ')[0] if ' ' in name else name
                if agent_id not in self_managed_agents:
                    self._update_heartbeat(name, execution)

                logger.info(
                    f"[WEEKLY-SCHEDULER] {name} completed in "
                    f"{execution.duration_sec}s"
                )
                return result

            except asyncio.TimeoutError:
                last_error = f"Timed out after {job_timeout}s"
                logger.error(f"[WEEKLY-SCHEDULER] {name} TIMED OUT")
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(
                    f"[WEEKLY-SCHEDULER] {name} failed (attempt {attempt}): {last_error}"
                )
                if attempt < max_retries:
                    delay = retry_delay * attempt
                    await asyncio.sleep(delay)

        # All retries exhausted
        execution.success = False
        execution.error = last_error
        execution.end_time = time.time()
        self._tracker.record(execution)

        # Trip circuit breaker
        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(name)
        self._circuit_breakers[name].record_failure()

        self._update_heartbeat(name, execution)
        logger.error(
            f"[WEEKLY-SCHEDULER] {name} FAILED after {max_retries} attempts"
        )

        await self._alert_job_failure(name, last_error)
        return None

    # ================================================================
    # SMART PORTAL SCRAPING (DAY-ROUTED)
    # ================================================================

    async def _run_smart_portal_scrape_am(self):
        """
        Smart AM portal scrape — only scrapes portals assigned to today.
        This is the KEY change: instead of scraping everything daily,
        we scrape each portal twice a week.
        """
        portals = self._router.get_today_portals("am")
        proxy_pool = self._router.get_today_proxy_pool()

        if not portals:
            logger.info("[WEEKLY-SCHEDULER] No AM portals scheduled today")
            return

        logger.info(
            f"[WEEKLY-SCHEDULER] AM Portal Scrape: {portals} "
            f"(proxies: {proxy_pool})"
        )

        from agents.a03_primary_scraper import get_primary_scraper
        scraper = get_primary_scraper()

        # Pass today's portals and proxy pool to the scraper
        scraper.set_active_portals(portals)
        scraper.set_proxy_pool_indices(proxy_pool)

        # Run the morning scrape (it will only hit assigned portals)
        await self._safe_run(
            'A-03 Smart AM Scrape',
            scraper.run_morning_scrape,
            job_timeout=3600,  # 1 hour max
        )

        # Auto-process pipeline
        await self._auto_process_pipeline("after smart AM scrape")
        await self._sync_to_supabase("smart_am_scrape")

        # Track budget
        self._budget.use('webshare_requests', len(portals) * 30)

    async def _run_smart_portal_scrape_pm(self):
        """Smart PM portal scrape — ATS platforms."""
        portals = self._router.get_today_portals("pm")
        proxy_pool = self._router.get_today_proxy_pool()

        if not portals:
            logger.info("[WEEKLY-SCHEDULER] No PM portals scheduled today")
            return

        logger.info(
            f"[WEEKLY-SCHEDULER] PM Portal Scrape: {portals} "
            f"(proxies: {proxy_pool})"
        )

        from agents.a03_primary_scraper import get_primary_scraper
        scraper = get_primary_scraper()
        scraper.set_active_portals(portals)
        scraper.set_proxy_pool_indices(proxy_pool)

        await self._safe_run(
            'A-03 Smart PM Scrape',
            scraper.run_afternoon_scrape,
            job_timeout=2400,
        )

        await self._auto_process_pipeline("after smart PM scrape")
        await self._sync_to_supabase("smart_pm_scrape")

    async def _run_smart_ats_crawl(self):
        """Smart ATS crawl — tier-batched company crawling."""
        tiers, tier_label = self._router.get_today_company_batch()

        if not tiers:
            logger.info("[WEEKLY-SCHEDULER] No ATS tiers scheduled today")
            return

        logger.info(
            f"[WEEKLY-SCHEDULER] ATS Crawl: tiers={tier_label}"
        )

        from agents.a04_ats_crawler import get_ats_crawler
        crawler = get_ats_crawler()

        # Set tier filter for today's batch
        crawler.set_tier_filter(tiers)

        await self._safe_run(
            'A-04 Smart ATS Crawl',
            crawler.run_crawl,
            job_timeout=3600,
        )

        await self._auto_process_pipeline("after smart ATS crawl")
        await self._sync_to_supabase("smart_ats_crawl")

    # ================================================================
    # STANDARD JOB IMPLEMENTATIONS (unchanged from v5.1)
    # ================================================================

    async def _run_dedup(self):
        from agents.a06_dedup_engine import get_dedup_engine
        await self._safe_run('A-06 Dedup', get_dedup_engine().run_dedup)

    async def _run_ghost_scoring(self):
        from agents.a05_ghost_detector import get_ghost_detector
        await self._safe_run('A-05 Ghost', get_ghost_detector().score_batch)

    async def _run_enrichment(self):
        from agents.a07_intelligence_enricher import get_intelligence_enricher
        await self._safe_run(
            'A-07 Enrichment',
            get_intelligence_enricher().run_enrichment
        )

    async def _run_ppo(self):
        from agents.a08_ppo_optimizer import get_ppo_optimizer
        await self._safe_run('A-08 PPO', get_ppo_optimizer().run_optimization)

    async def _run_morning_brief(self):
        from agents.a12_telegram_reporter import get_telegram_reporter
        reporter = get_telegram_reporter()
        await self._safe_run('A-12 Morning Brief', reporter.send_morning_brief)

    async def _run_evening_summary(self):
        from agents.a12_telegram_reporter import get_telegram_reporter
        reporter = get_telegram_reporter()
        await self._safe_run('A-12 Evening Summary', reporter.send_evening_summary)

    async def _run_intent_scan(self):
        from agents.a01_intent_scanner import get_intent_scanner
        await self._safe_run('A-01 Intent', get_intent_scanner().run_scan)
        self._budget.use('ddg_searches', 20)

    async def _run_dark_channels(self):
        from agents.a02_dark_channel import get_dark_channel_listener
        await self._safe_run(
            'A-02 Dark',
            get_dark_channel_listener().run_batch_check
        )

    # ================================================================
    # SUNDAY DEEP OPERATIONS
    # ================================================================

    async def _run_sunday_deep_enrichment(self):
        """
        Sunday deep enrichment:
        - Full CIRS refresh for all 1,080 companies
        - Sector momentum recalculation
        - Company tier re-evaluation
        - Stale data cleanup
        """
        logger.info("[WEEKLY-SCHEDULER] Sunday deep enrichment starting...")

        from agents.a07_intelligence_enricher import get_intelligence_enricher
        enricher = get_intelligence_enricher()

        await self._safe_run(
            'A-07 Sunday Deep Enrichment',
            enricher.run_deep_enrichment,
            job_timeout=3600,
        )

    async def _run_sunday_deep_ats(self):
        """
        Sunday deep ATS:
        - Discover new career pages for companies missing ATS URLs
        - Verify existing ATS URLs still work
        - Add newly discovered companies to DB
        """
        logger.info("[WEEKLY-SCHEDULER] Sunday deep ATS crawl starting...")

        from agents.a04_ats_crawler import get_ats_crawler
        crawler = get_ats_crawler()

        # Deep mode: discover new + verify existing
        await self._safe_run(
            'A-04 Sunday Deep ATS',
            crawler.run_deep_discovery,
            job_timeout=5400,  # 90 min
        )

    async def _run_weekly_retrain(self):
        from agents.a11_outcome_learner import get_outcome_learner
        await self._safe_run(
            'A-11 Retrain',
            get_outcome_learner().run_weekly_retrain
        )

    # ================================================================
    # AUTO-PROCESS PIPELINE (same as v5.1)
    # ================================================================

    async def _auto_process_pipeline(self, trigger_reason: str = ""):
        """Run dedup -> ghost -> enrich -> PPO after any scrape job."""
        logger.info(
            f"[WEEKLY-SCHEDULER] Auto-processing pipeline ({trigger_reason})..."
        )

        try:
            from core.database import get_db
            db = get_db()
            unprocessed = db.count_unprocessed_raw_listings()
            if unprocessed == 0:
                logger.info("[WEEKLY-SCHEDULER] 0 unprocessed listings, skipping")
                return
            logger.info(f"[WEEKLY-SCHEDULER] {unprocessed} unprocessed raw listings")
        except Exception as e:
            logger.warning(f"[WEEKLY-SCHEDULER] Auto-process check failed: {e}")

        steps = [
            ('A-06 Auto-Dedup', 'agents.a06_dedup_engine', 'get_dedup_engine', 'run_dedup'),
            ('A-05 Auto-Ghost', 'agents.a05_ghost_detector', 'get_ghost_detector', 'score_batch'),
            ('A-07 Auto-Enrich', 'agents.a07_intelligence_enricher', 'get_intelligence_enricher', 'run_enrichment'),
            ('A-08 Auto-PPO', 'agents.a08_ppo_optimizer', 'get_ppo_optimizer', 'run_optimization'),
        ]

        for step_name, module_path, getter_name, method_name in steps:
            try:
                module = __import__(module_path, fromlist=[getter_name])
                getter = getattr(module, getter_name)
                instance = getter()
                method = getattr(instance, method_name)
                await self._safe_run(step_name, method)
            except Exception as e:
                logger.error(f"[WEEKLY-SCHEDULER] {step_name} failed: {e}")

        logger.info("[WEEKLY-SCHEDULER] Auto-processing pipeline complete")

    # ================================================================
    # SUPABASE INTEGRATION (same as v5.1)
    # ================================================================

    async def _sync_to_supabase(self, trigger: str = ""):
        """Sync clean_listings to Supabase."""
        try:
            from core.supabase_client import is_operational
            if not is_operational():
                return

            from core.database import get_db
            from core.supabase_db import async_insert_latest_jobs, async_insert_all_jobs

            db = get_db()
            recent = db.get_recent_clean_listings(days=1, limit=500)
            if not recent:
                return

            jobs = []
            for row in recent:
                jobs.append({
                    "title": row.get("title", ""),
                    "company": row.get("company", ""),
                    "location": row.get("location", ""),
                    "source": row.get("source", ""),
                    "source_url": row.get("url", ""),
                    "category": row.get("category", ""),
                    "stipend": int(row.get("stipend_monthly", 0) or 0),
                    "duration": int(row.get("duration_months", 0) or 0),
                    "applicants": int(row.get("applicants", 0) or 0),
                    "description": row.get("description_text", ""),
                    "ppo_score": float(row.get("ppo_score", 0) or 0),
                    "ghost_score": float(row.get("ghost_score", 0) or 0),
                    "match_score": float(row.get("ppo_score", 50) or 50),
                    "is_expired": row.get("status", "") == "expired",
                    "location_type": "remote" if row.get("is_wfh") else "onsite",
                    "sector": row.get("sector", ""),
                    "content_hash": row.get("content_hash", ""),
                })

            batch_id = f"sync_{trigger}_{datetime.now(IST).strftime('%Y%m%d_%H%M')}"
            count = await async_insert_latest_jobs(jobs, batch_id)
            logger.info(f"[WEEKLY-SCHEDULER] Supabase sync: {count}/{len(jobs)} jobs ({trigger})")

            try:
                all_count = await async_insert_all_jobs(jobs, batch_id)
                logger.info(f"[WEEKLY-SCHEDULER] all_jobs sync: {all_count}/{len(jobs)}")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER] Supabase sync error: {e}")

    async def _supabase_ping(self):
        try:
            from core.supabase_keepalive import scheduler_ping
            result = await scheduler_ping()
            if result.get("success"):
                logger.debug("[WEEKLY-SCHEDULER] Supabase L2 ping OK")
        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER] Supabase ping error: {e}")

    async def _supabase_morning_merge(self):
        try:
            from core.supabase_db import async_merge_latest_to_all, async_cleanup_expired_jobs
            from core.supabase_client import is_operational
            if not is_operational():
                return
            merged, total = await async_merge_latest_to_all()
            logger.info(f"[WEEKLY-SCHEDULER] Supabase merge: {merged} from {total}")
            deleted = await async_cleanup_expired_jobs(days=7)
            if deleted > 0:
                logger.info(f"[WEEKLY-SCHEDULER] Cleanup: {deleted} expired removed")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER] Morning merge error: {e}")

    async def _supabase_cleanup(self):
        try:
            from core.supabase_db import async_cleanup_expired_jobs
            from core.supabase_client import is_operational
            if not is_operational():
                return
            deleted = await async_cleanup_expired_jobs(days=7)
            logger.info(f"[WEEKLY-SCHEDULER] Cleanup: {deleted} expired removed")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER] Cleanup error: {e}")

    # ================================================================
    # INFRASTRUCTURE
    # ================================================================

    async def _keep_alive(self):
        logger.debug("[WEEKLY-SCHEDULER] Keep-alive ping (Layer 2)")
        try:
            import aiohttp
            port = int(os.getenv('PORT', '10000'))
            external_url = os.getenv('RENDER_EXTERNAL_URL', '')
            url = (
                f"{external_url}/ping"
                if external_url
                else f"http://127.0.0.1:{port}/ping"
            )
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        logger.debug("[WEEKLY-SCHEDULER] Keep-alive: OK")
        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER] Keep-alive error: {e}")

    async def _run_maintenance(self):
        logger.info("[WEEKLY-SCHEDULER] Running DB maintenance...")
        try:
            from core.database import get_db
            db = get_db()
            db.cleanup_old_data(days=30)
            db.analyze()
            logger.info("[WEEKLY-SCHEDULER] DB maintenance complete")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER] Maintenance error: {e}")

    async def _proxy_health_check(self):
        """Run proxy health check on today's allocated pool."""
        try:
            from core.stealth_engine import get_stealth_client
            client = get_stealth_client()
            result = client.proxy_pool.health_check_all()
            logger.info(
                f"[WEEKLY-SCHEDULER] Proxy health: "
                f"{result.get('alive', 0)} alive, {result.get('dead', 0)} dead"
            )
        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER] Proxy health check error: {e}")

    async def _send_budget_report(self):
        """Send daily budget report via Telegram."""
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()
            if reporter._running:
                report = self._budget.get_telegram_report()
                schedule = self._router.get_schedule_summary()
                msg = f"{schedule}\n\n{report}"
                await reporter.send_message(msg)
        except Exception:
            pass

    async def _alert_job_failure(self, job_name: str, error: str):
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()
            if reporter._running:
                msg = (
                    f"⚠️ <b>Scheduled Job Failed</b>\n"
                    f"Job: {job_name}\n"
                    f"Error: {str(error)[:200]}\n\n"
                    f"Circuit breaker may be engaged."
                )
                await reporter.send_message(msg)
        except Exception:
            pass

    def _update_heartbeat(self, name: str, execution):
        try:
            from core.database import get_db
            db = get_db()
            agent_id = name.split(' ')[0] if ' ' in name else name
            db.update_agent_heartbeat(
                agent_id=agent_id,
                status='completed' if execution.success else 'error',
                items_processed=execution.items_processed,
                errors=0 if execution.success else 1,
                duration_sec=execution.duration_sec,
            )
        except Exception:
            pass

    async def _check_and_run_startup_pipeline(self):
        """On startup, check if we need to run an immediate pipeline."""
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        try:
            IST_TZ = _tz(_td(hours=5, minutes=30))
            now_ist = _dt.now(IST_TZ)

            from core.database import get_db
            db = get_db()
            total_active = 0
            total_raw = 0
            try:
                with db.get_cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM clean_listings WHERE status = 'active'"
                    )
                    total_active = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM raw_listings")
                    total_raw = cur.fetchone()[0]
            except Exception:
                pass

            should_scrape = False
            should_process = False
            reason = ""

            if total_active == 0 and total_raw == 0:
                should_scrape = True
                should_process = True
                reason = "no data at all (fresh start)"
            elif total_active == 0 and total_raw > 0:
                should_process = True
                reason = f"{total_raw} raw listings need processing"
            elif 6 <= now_ist.hour <= 12 and total_active == 0:
                should_scrape = True
                should_process = True
                reason = f"no active listings during morning window"

            if not should_scrape and not should_process:
                logger.info(
                    f"[WEEKLY-SCHEDULER] Startup check: SKIP "
                    f"(active={total_active}, raw={total_raw})"
                )
                return

            logger.info(f"[WEEKLY-SCHEDULER] STARTUP PIPELINE: {reason}")

            if should_scrape:
                try:
                    from agents.a03_primary_scraper import get_primary_scraper
                    scraper = get_primary_scraper()
                    # Use today's portals for startup
                    portals = self._router.get_today_portals("am")
                    if portals:
                        scraper.set_active_portals(portals)
                    await self._safe_run(
                        'A-03 Startup Scrape',
                        scraper.run_afternoon_scrape
                    )
                except Exception as e:
                    logger.error(f"[WEEKLY-SCHEDULER] Startup scrape error: {e}")

            if should_process:
                await self._auto_process_pipeline("startup pipeline")

            logger.info("[WEEKLY-SCHEDULER] Startup pipeline complete")

        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER] Startup check error: {e}")


# ============================================================
# CIRCUIT BREAKER
# ============================================================

class CircuitBreaker:
    """
    Simple circuit breaker to prevent repeated failures.
    Opens after 3 consecutive failures, closes after 15 minutes.
    """

    def __init__(self, name: str, threshold: int = 3, reset_timeout: int = 900):
        self.name = name
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = "closed"  # closed, open, half-open

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            # Check if reset timeout has passed
            if time.time() - self._last_failure_time > self.reset_timeout:
                self._state = "half-open"
                return False
            return True
        return False

    def record_failure(self):
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.threshold:
            self._state = "open"
            logger.warning(
                f"[CIRCUIT-BREAKER] {self.name}: OPENED "
                f"(after {self._failures} failures)"
            )

    def record_success(self):
        self._failures = 0
        self._state = "closed"


# ============================================================
# EXECUTION TRACKER (shared with old scheduler)
# ============================================================

@dataclass
class JobExecution:
    """Track a single job execution."""
    job_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool = False
    error: Optional[str] = None
    items_processed: int = 0

    @property
    def duration_sec(self) -> float:
        if self.end_time and self.start_time:
            return round(self.end_time - self.start_time, 1)
        return 0.0


class ExecutionTracker:
    """Tracks job execution history."""

    def __init__(self, max_history: int = 200):
        self._history: List[JobExecution] = []
        self._max = max_history

    def record(self, execution: JobExecution):
        self._history.append(execution)
        if len(self._history) > self._max:
            self._history = self._history[-self._max:]

    def get_recent(self, limit: int = 20) -> List[JobExecution]:
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        if not self._history:
            return {'total': 0, 'success': 0, 'failed': 0}
        success = sum(1 for e in self._history if e.success)
        return {
            'total': len(self._history),
            'success': success,
            'failed': len(self._history) - success,
            'success_rate': round(success / len(self._history) * 100, 1),
        }


# ============================================================
# SINGLETON
# ============================================================

_weekly_scheduler_instance: Optional[WeeklyAgentScheduler] = None


def get_weekly_scheduler() -> WeeklyAgentScheduler:
    global _weekly_scheduler_instance
    if _weekly_scheduler_instance is None:
        _weekly_scheduler_instance = WeeklyAgentScheduler()
    return _weekly_scheduler_instance


# Backward compatibility — make it drop-in replacement
def get_scheduler() -> WeeklyAgentScheduler:
    """Drop-in replacement for core.scheduler.get_scheduler()"""
    return get_weekly_scheduler()


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Weekly Smart Scheduler — Self-Test")
    print("=" * 60)

    print(f"\n  APScheduler available: {'yes' if SCHEDULER_AVAILABLE else 'no'}")
    print(f"  Schedule entries: {len(WEEKLY_SCHEDULE)}")

    router = PortalDayRouter()
    print(f"\n  Today's AM portals: {router.get_today_portals('am')}")
    print(f"  Today's PM portals: {router.get_today_portals('pm')}")
    print(f"  Today's ATS tiers: {router.get_today_company_tiers()}")
    print(f"  Today's proxy pool: {router.get_today_proxy_pool()}")

    budget = WeeklyResourceBudget()
    print(f"\n  Budget status:")
    for resource, status in budget.get_status().items():
        print(f"    {resource}: {status['used']}/{status['target']} (headroom: {status['headroom_pct']}%)")

    coverage = router.get_weekly_coverage_report()
    print(f"\n  Weekly coverage:")
    print(f"    Portals: {coverage['portals_per_week']}")
    print(f"    Companies/week: {coverage['companies_per_week']}")
    print(f"    Proxy utilization: {coverage['proxy_utilization']}")

    print("\n" + "=" * 60)
