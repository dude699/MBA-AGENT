"""
============================================================
OPERATION FIRST MOVER — PRISM v0.1 WEEKLY SMART SCHEDULER
============================================================
PRISM 3-Wave scheduling engine with AI-powered optimization.

PRISM v0.1 Upgrades from OFM v7.0:
    1. 20-Agent Support: Schedules all 20 PRISM agents
    2. Auto-Apply Integration: A-13 at 08:00 + 15:00 IST
    3. Email Outreach: A-15 at 09:30 IST daily
    4. Outcome Tracking: A-19 at 10:30 IST daily
    5. Company Intel: A-20 at 07:00 IST (pre-apply research)
    6. A-14 Nightly Reset: midnight IST quota reset
    7. Sunday Alumni Remap: A-09 at 10:00 IST

PRISM 3-WAVE WEEKLY SCHEDULE (IST):
    Wave 1 (05:15 IST, Mon/Wed/Fri):
        A-03 -> Internshala + Naukri API + IIMjobs
        A-06 -> Dedup on overnight batch
        A-05 -> Ghost scoring
        A-07 -> Intelligence enrichment + Blue Ocean
        A-08 -> PPO V11 scoring -> top 25 shortlist
        A-12 -> MORNING BRIEF

    Wave 2 (14:00 IST, Tue/Thu/Sat):
        A-04 -> Greenhouse/Lever/Workday + LinkedIn DDG
        A-05 -> Ghost scoring (afternoon batch)
        A-13 -> Auto-apply run #2

    Night (22:30 IST, Mon/Wed):
        A-04 -> All portals, all Tier 1-3 companies
        A-05 -> Ghost scoring (night batch)

    Daily Operations (Every Day):
        08:00 A-13 -> Auto-apply run #1
        09:00 A-01 -> Intent signal scan
        09:30 A-15 -> Email outreach (Brevo)
        10:30 A-19 -> Follow-up check
        16:00 A-01 -> Second intent scan
        20:00 A-12 -> EVENING SUMMARY

    Sunday Specials:
        10:00 A-09 -> Alumni re-mapping
        14:00 A-04 -> Deep ATS discovery
        18:00 A-11 -> PPO weight retraining
        21:00 A-11 -> Second retrain pass

    Always Running:
        24/7 A-16 -> Telegram Group Monitor
        24/7 A-02 -> Dark Channel Listener
        24/7 A-14 -> Multi-Model Router
        24/7 A-17 -> Adaptive Scheduler
============================================================
"""

import os
import time
import asyncio
import traceback
import inspect
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
# WEEKLY SCHEDULE STRATEGY v7.0
# ============================================================

class DayOfWeek(Enum):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


# Which portals to scrape on which days — 3x per week each (upgraded from 2x)
PORTAL_SCHEDULE: Dict[str, List[int]] = {
    'internshala':  [0, 2, 3],  # Mon, Wed, Thu
    'naukri':       [0, 1, 4],  # Mon, Tue, Fri
    'iimjobs':      [0, 3, 5],  # Mon, Thu, Sat
    'indeed':       [1, 4, 5],  # Tue, Fri, Sat
    'glassdoor':    [1, 2, 5],  # Tue, Wed, Sat
    'wellfound':    [1, 4, 5],  # Tue, Fri, Sat
    'workday':      [2, 5, 3],  # Wed, Sat, Thu
    'greenhouse':   [0, 2, 4],  # Mon, Wed, Fri
    'lever':        [0, 3, 4],  # Mon, Thu, Fri
}

# Company tier -> ATS crawl days (now 3x per week)
COMPANY_TIER_SCHEDULE: Dict[str, List[int]] = {
    'tier_1_2': [0, 2, 4],  # Mon, Wed, Fri (priority — Elite + Strong MNC = 300)
    'tier_3':   [1, 3, 5],  # Tue, Thu, Sat (Indian Unicorns = 180)
    'tier_4_5': [1, 3, 5],  # Tue, Thu, Sat (Growing + Niche = 600)
}

# Deep crawl days (4x per week — Mon, Wed, Fri, Sun)
DEEP_CRAWL_DAYS: List[int] = [0, 2, 4, 6]

# Proxy IP allocation per day (10 IPs, rotate more aggressively)
PROXY_DAY_POOLS: Dict[int, List[int]] = {
    0: [0, 1, 2, 3, 4],     # Mon: IPs 0-4 (5 IPs for heavy day)
    1: [2, 3, 4, 5, 6],     # Tue: IPs 2-6
    2: [4, 5, 6, 7, 8],     # Wed: IPs 4-8
    3: [6, 7, 8, 9, 0],     # Thu: IPs 6-9,0
    4: [8, 9, 0, 1, 2],     # Fri: IPs 8-9,0-2
    5: [0, 2, 4, 6, 8],     # Sat: Even IPs (spread)
    6: [1, 3, 5, 7, 9],     # Sun: Odd IPs (spread)
}


@dataclass
class WeeklyScheduleEntry:
    """A single scheduled job entry with weekly awareness."""
    job_id: str
    description: str
    agent: str
    hour: int
    minute: int
    days_of_week: str = "mon-sat"
    estimated_duration_min: int = 15
    enabled: bool = True
    priority: int = 5
    portals: List[str] = field(default_factory=list)
    company_tiers: List[str] = field(default_factory=list)
    ai_enhanced: bool = False  # v7.0: AI-enhanced job
    deep_mode: bool = False     # v7.0: deep crawl mode


# ============================================================
# FULL WEEKLY SCHEDULE v7.0 (IST) — 3 WAVES + AI TASKS
# ============================================================

WEEKLY_SCHEDULE: List[WeeklyScheduleEntry] = [
    # ==== WAVE 1: MORNING (05:00 - 08:00) — MAIN PORTAL SCRAPE ====
    WeeklyScheduleEntry(
        "smart_portal_scrape_am",
        "Wave 1: Smart portal scrape (AI-enhanced day routing)",
        "A-03", 5, 15,
        days_of_week="mon-sat",
        estimated_duration_min=55, priority=1,
        portals=['internshala', 'naukri', 'iimjobs', 'glassdoor',
                 'indeed', 'wellfound'],
        ai_enhanced=True,
    ),

    # AI Quality Scoring on morning batch
    WeeklyScheduleEntry(
        "ai_quality_scoring_am",
        "AI quality scoring on morning scrape batch",
        "AI-QS", 6, 15,
        days_of_week="mon-sat",
        estimated_duration_min=20, priority=2,
        ai_enhanced=True,
    ),

    # Processing pipeline — parallel execution
    WeeklyScheduleEntry(
        "morning_dedup", "Dedup engine on morning batch",
        "A-06", 6, 40,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=2,
    ),
    WeeklyScheduleEntry(
        "ghost_scoring", "Ghost scoring (Cerebras AI)",
        "A-05", 6, 40,  # Same time — runs in parallel with dedup
        days_of_week="mon-sat",
        estimated_duration_min=20, priority=2,
        ai_enhanced=True,
    ),
    WeeklyScheduleEntry(
        "morning_enrichment", "Intelligence enrichment + Blue Ocean + AI analysis",
        "A-07", 7, 5,
        days_of_week="mon-sat",
        estimated_duration_min=20, priority=3,
        ai_enhanced=True,
    ),
    WeeklyScheduleEntry(
        "ppo_scoring", "PPO model scoring -> top 25 with AI insights",
        "A-08", 7, 30,
        days_of_week="mon-sat",
        estimated_duration_min=10, priority=2,
        ai_enhanced=True,
    ),
    WeeklyScheduleEntry(
        "morning_brief", "MORNING BRIEF -> Telegram (AI-compiled)",
        "A-12", 7, 45,
        days_of_week="mon-sun",
        estimated_duration_min=2, priority=1,
        ai_enhanced=True,
    ),

    # ==== MIDDAY (09:00 - 13:00) — INTENT + ATS ====
    WeeklyScheduleEntry(
        "intent_am", "Intent signal scan AM (Tier 1+2, AI-boosted)",
        "A-01", 9, 0,
        days_of_week="mon-fri",  # 5x/week (upgraded from 3x)
        estimated_duration_min=30, priority=3,
        ai_enhanced=True,
    ),

    # AI Schedule Optimizer — runs at 10 AM to optimize rest of the day
    WeeklyScheduleEntry(
        "ai_schedule_optimize",
        "AI analyzes morning results and optimizes afternoon schedule",
        "AI-SO", 10, 0,
        days_of_week="mon-sat",
        estimated_duration_min=5, priority=4,
        ai_enhanced=True,
    ),

    # ATS direct crawl — company tier-based routing
    WeeklyScheduleEntry(
        "smart_ats_crawl",
        "Smart ATS crawl (tier-based with AI career page discovery)",
        "A-04", 11, 0,
        days_of_week="mon-sat",
        estimated_duration_min=60, priority=3,
        company_tiers=['tier_1_2', 'tier_3', 'tier_4_5'],
        ai_enhanced=True,
    ),

    # ==== WAVE 2: AFTERNOON (14:00 - 18:00) — SECONDARY PORTALS ====
    WeeklyScheduleEntry(
        "smart_portal_scrape_pm",
        "Wave 2: Secondary portal scrape (ATS platforms + sweeps)",
        "A-03", 14, 0,
        days_of_week="mon-sat",
        estimated_duration_min=45, priority=2,
        portals=['greenhouse', 'lever', 'workday'],
        ai_enhanced=True,
    ),

    WeeklyScheduleEntry(
        "intent_pm", "Intent signal scan PM (AI-enhanced)",
        "A-01", 16, 0,
        days_of_week="mon-fri",  # 5x/week (upgraded)
        estimated_duration_min=30, priority=4,
        ai_enhanced=True,
    ),

    # AI Anomaly Detection — check for unusual patterns
    WeeklyScheduleEntry(
        "ai_anomaly_check",
        "AI anomaly detection on day's scraping results",
        "AI-AD", 17, 0,
        days_of_week="mon-sat",
        estimated_duration_min=10, priority=4,
        ai_enhanced=True,
    ),

    # ==== WAVE 2.5: EVENING (18:00 - 21:00) — PROCESSING ====
    WeeklyScheduleEntry(
        "evening_dedup", "Evening batch dedup + AI quality check",
        "A-06", 18, 0,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=3,
    ),
    WeeklyScheduleEntry(
        "evening_enrichment", "Evening enrichment pass (deep AI analysis)",
        "A-07", 18, 20,
        days_of_week="mon-sat",
        estimated_duration_min=20, priority=3,
        ai_enhanced=True,
    ),
    WeeklyScheduleEntry(
        "dark_channels", "Dark channel batch check (AI-classified)",
        "A-02", 20, 0,
        days_of_week="mon-fri",  # 5x/week (upgraded from 3x)
        estimated_duration_min=15, priority=4,
        ai_enhanced=True,
    ),

    # ==== WAVE 3: NIGHT (22:00 - 04:00) — DEEP CRAWL + ANALYSIS ====
    WeeklyScheduleEntry(
        "smart_portal_scrape_night",
        "Wave 3: Night deep crawl (AI-selected portals, deep pagination)",
        "A-03", 22, 30,
        days_of_week="mon,wed,fri",  # Deep crawl days
        estimated_duration_min=60, priority=3,
        ai_enhanced=True,
        deep_mode=True,
    ),

    WeeklyScheduleEntry(
        "evening_summary", "EVENING SUMMARY -> Telegram (AI-compiled with insights)",
        "A-12", 22, 0,
        days_of_week="mon-sun",
        estimated_duration_min=2, priority=1,
        ai_enhanced=True,
    ),

    # Night ATS deep crawl
    WeeklyScheduleEntry(
        "night_ats_deep",
        "Night ATS deep crawl (AI-powered career page discovery)",
        "A-04", 23, 30,
        days_of_week="tue,thu,sat",  # Alternate nights
        estimated_duration_min=60, priority=4,
        ai_enhanced=True,
        deep_mode=True,
    ),

    # AI Resource Rebalancer — runs at 1 AM to optimize next day
    WeeklyScheduleEntry(
        "ai_resource_rebalance",
        "AI resource rebalancer — optimize next day's resource allocation",
        "AI-RB", 1, 0,
        days_of_week="mon-sun",
        estimated_duration_min=5, priority=5,
        ai_enhanced=True,
    ),

    # ==== SUNDAY DEEP OPS (AI-INTENSIVE) ====
    WeeklyScheduleEntry(
        "sunday_deep_enrichment",
        "Sunday deep enrichment (full AI analysis of all 1080 companies)",
        "A-07", 10, 0,
        days_of_week="sun",
        estimated_duration_min=90, priority=3,
        ai_enhanced=True,
        deep_mode=True,
    ),
    WeeklyScheduleEntry(
        "sunday_deep_ats",
        "Sunday deep ATS (AI career page discovery for new companies)",
        "A-04", 14, 0,
        days_of_week="sun",
        estimated_duration_min=90, priority=4,
        ai_enhanced=True,
        deep_mode=True,
    ),
    WeeklyScheduleEntry(
        "sunday_ai_retrain",
        "Sunday AI model retrain + PPO weight optimization",
        "A-11", 18, 0,
        days_of_week="sun",
        estimated_duration_min=15, priority=5,
        ai_enhanced=True,
    ),
    WeeklyScheduleEntry(
        "weekly_retrain",
        "Weekly PPO weight retrain + outcome analysis (AI-enhanced)",
        "A-11", 21, 0,
        days_of_week="sun",
        estimated_duration_min=10, priority=5,
        ai_enhanced=True,
    ),

    # ==== PRISM v0.1: NEW AGENT SCHEDULES ====

    # A-13 Auto-Apply: 08:00 IST (run #1) + 15:00 IST (run #2)
    WeeklyScheduleEntry(
        "auto_apply_am",
        "Auto-apply run #1 (morning, top PPO listings)",
        "A-13", 8, 0,
        days_of_week="mon-sat",
        estimated_duration_min=30, priority=1,
    ),
    WeeklyScheduleEntry(
        "auto_apply_pm",
        "Auto-apply run #2 (afternoon, remaining queue)",
        "A-13", 15, 0,
        days_of_week="mon-sat",
        estimated_duration_min=30, priority=2,
    ),

    # A-15 Email Auto-Applier: 09:30 IST daily
    WeeklyScheduleEntry(
        "email_outreach",
        "Email auto-apply (Brevo cold outreach to HR/alumni)",
        "A-15", 9, 30,
        days_of_week="mon-sat",
        estimated_duration_min=20, priority=2,
    ),

    # A-19 Outcome Amplifier: 10:30 IST daily
    WeeklyScheduleEntry(
        "outcome_followup",
        "Outcome amplifier (follow-up checks + email tracking)",
        "A-19", 10, 30,
        days_of_week="mon-sat",
        estimated_duration_min=15, priority=3,
    ),

    # A-20 Deep Company Intel: 1 hour before A-13
    WeeklyScheduleEntry(
        "company_intel",
        "Deep company intel (pre-application research via Groq Compound)",
        "A-20", 7, 0,
        days_of_week="mon-sat",
        estimated_duration_min=25, priority=3,
        ai_enhanced=True,
    ),

    # A-09 Alumni Re-mapping: Sunday 10:00
    WeeklyScheduleEntry(
        "sunday_alumni_remap",
        "Sunday alumni re-mapping (DDG/SerpAPI/Hunter.io)",
        "A-09", 10, 0,
        days_of_week="sun",
        estimated_duration_min=30, priority=3,
    ),

    # A-14 Nightly Reset: midnight IST
    WeeklyScheduleEntry(
        "ai_router_nightly_reset",
        "A-14 Multi-Model Router nightly quota reset + efficiency report",
        "A-14", 0, 5,
        days_of_week="mon-sun",
        estimated_duration_min=2, priority=5,
    ),
]


# ============================================================
# PORTAL DAY ROUTER v7.0 — AI-Enhanced Portal Selection
# ============================================================

class PortalDayRouter:
    """
    Smart router that determines which portals to scrape today.
    v7.0: AI-predicted freshness scoring + 3-wave support.
    """

    def __init__(self):
        self._company_batches_cache: Dict[str, List] = {}
        self._portal_freshness: Dict[str, float] = {}
        self._last_scrape_results: Dict[str, Dict] = {}

    def get_today_portals(self, session: str = "am") -> List[str]:
        """Get list of portals to scrape right now (3 waves)."""
        today = datetime.now(IST).weekday()

        if today == 6:  # Sunday — no regular portal scraping
            return []

        if session == "am":
            return [
                portal for portal, days in PORTAL_SCHEDULE.items()
                if today in days and portal in (
                    'internshala', 'naukri', 'iimjobs',
                    'glassdoor', 'indeed', 'wellfound'
                )
            ]
        elif session == "pm":
            return [
                portal for portal, days in PORTAL_SCHEDULE.items()
                if today in days and portal in (
                    'greenhouse', 'lever', 'workday'
                )
            ]
        elif session == "night":
            # Night wave: AI-selected portals that had high yield today
            # Fallback: re-scrape portals with deepest pagination
            high_yield = self._get_high_yield_portals()
            if high_yield:
                return high_yield[:3]
            # Default night portals based on day
            night_rotation = {
                0: ['internshala', 'greenhouse'],
                1: ['naukri', 'indeed'],
                2: ['glassdoor', 'wellfound'],
                3: ['internshala', 'lever'],
                4: ['naukri', 'indeed'],
                5: ['glassdoor', 'workday'],
            }
            return night_rotation.get(today, [])
        return []

    def _get_high_yield_portals(self) -> List[str]:
        """Get portals that had highest new listing yield today."""
        if not self._last_scrape_results:
            return []
        sorted_portals = sorted(
            self._last_scrape_results.items(),
            key=lambda x: x[1].get('new_listings', 0),
            reverse=True
        )
        return [p for p, _ in sorted_portals if sorted_portals[0][1].get('new_listings', 0) > 5]

    def record_scrape_results(self, portal: str, results: Dict):
        """Record scraping results for AI-powered night wave selection."""
        self._last_scrape_results[portal] = {
            **results,
            'timestamp': time.time(),
        }

    def get_today_company_tiers(self) -> List[str]:
        """Get which company tiers to ATS-crawl today."""
        today = datetime.now(IST).weekday()
        if today == 6:
            return ['tier_1_2', 'tier_3', 'tier_4_5']
        return [
            tier for tier, days in COMPANY_TIER_SCHEDULE.items()
            if today in days
        ]

    def get_today_company_batch(self) -> Tuple[List[str], str]:
        """Get the batch of company tiers to ATS-crawl today."""
        tiers = self.get_today_company_tiers()
        if not tiers:
            return [], "none"
        return tiers, "+".join(tiers)

    def get_today_proxy_pool(self) -> List[int]:
        """Get which proxy indices to use today (5 IPs/day from pool of 10)."""
        today = datetime.now(IST).weekday()
        return PROXY_DAY_POOLS.get(today, [0, 1, 2, 3, 4])

    def is_deep_crawl_day(self) -> bool:
        """Check if today is a deep crawl day."""
        return datetime.now(IST).weekday() in DEEP_CRAWL_DAYS

    def get_schedule_summary(self) -> str:
        """Generate a human-readable schedule summary for today."""
        today = datetime.now(IST)
        day_name = today.strftime("%A")
        day_num = today.weekday()

        am_portals = self.get_today_portals("am")
        pm_portals = self.get_today_portals("pm")
        night_portals = self.get_today_portals("night")
        tiers = self.get_today_company_tiers()
        proxies = self.get_today_proxy_pool()
        is_deep = self.is_deep_crawl_day()

        lines = [
            f"📅 <b>Today's Schedule ({day_name}) — v7.0</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🌅 <b>Wave 1 (AM):</b> {', '.join(am_portals) or 'None (Sunday)'}",
            f"🌇 <b>Wave 2 (PM):</b> {', '.join(pm_portals) or 'None'}",
            f"🌙 <b>Wave 3 (Night):</b> {', '.join(night_portals) or 'None'}",
            f"🏢 <b>ATS Tiers:</b> {', '.join(tiers) or 'Deep crawl all'}",
            f"🔄 <b>Proxy IPs:</b> [{', '.join(str(p) for p in proxies)}]",
            f"🔬 <b>Deep Crawl:</b> {'YES' if is_deep else 'No'}",
            f"🤖 <b>AI Tasks:</b> Quality Scoring, Anomaly Detection, Schedule Optimizer",
            "",
        ]

        # Show weekly overview
        lines.append("📊 <b>Weekly Portal Schedule (3x/week each):</b>")
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
            'deep_crawl_days': len(DEEP_CRAWL_DAYS),
            'ai_tasks_per_day': 5,
        }

        for portal, days in PORTAL_SCHEDULE.items():
            report['portals_per_week'][portal] = len(days)
            report['total_scrape_sessions'] += len(days)

        report['companies_per_week'] = 1080
        report['companies_per_day'] = 180
        report['waves_per_day'] = 3

        for day, ips in PROXY_DAY_POOLS.items():
            for ip in ips:
                report['proxy_utilization'][ip] = \
                    report['proxy_utilization'].get(ip, 0) + 1

        return report


# ============================================================
# RESOURCE BUDGET TRACKER v7.0 — Aggressive Utilization
# ============================================================

class WeeklyResourceBudget:
    """
    Tracks resource usage against AGGRESSIVE weekly budgets.
    v7.0: Much higher targets — utilize resources properly.
    """

    BUDGETS = {
        'groq_requests':       {'weekly_limit': 100800, 'target_usage': 12000, 'headroom': 0.881},
        'cerebras_requests':   {'weekly_limit': 700000, 'target_usage': 175000, 'headroom': 0.750},
        'serpapi_searches':    {'weekly_limit': 57, 'target_usage': 54, 'headroom': 0.053},
        'cf_worker_requests':  {'weekly_limit': 700000, 'target_usage': 56000, 'headroom': 0.920},
        'webshare_requests':   {'weekly_limit': 8400, 'target_usage': 5040, 'headroom': 0.400},
        'scraperapi_credits':  {'weekly_limit': 250, 'target_usage': 225, 'headroom': 0.100},
        'scrapingbee_credits': {'weekly_limit': 250, 'target_usage': 50, 'headroom': 0.800},
        'scrapedo_credits':    {'weekly_limit': 250, 'target_usage': 225, 'headroom': 0.100},
        'ddg_searches':        {'weekly_limit': 1400, 'target_usage': 1000, 'headroom': 0.286},
        # v7.0: AI task budgets
        'ai_quality_checks':   {'weekly_limit': 50000, 'target_usage': 10000, 'headroom': 0.800},
        'ai_enrichment_deep':  {'weekly_limit': 20000, 'target_usage': 5000, 'headroom': 0.750},
        'ai_anomaly_scans':    {'weekly_limit': 5000, 'target_usage': 500, 'headroom': 0.900},
    }

    def __init__(self):
        self._usage: Dict[str, int] = {k: 0 for k in self.BUDGETS}
        self._week_start: datetime = self._get_week_start()
        self._daily_usage: Dict[str, Dict[int, int]] = {
            k: {} for k in self.BUDGETS
        }

    def _get_week_start(self) -> datetime:
        now = datetime.now(IST)
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)

    def _check_week_reset(self):
        current_week_start = self._get_week_start()
        if current_week_start > self._week_start:
            self._usage = {k: 0 for k in self.BUDGETS}
            self._daily_usage = {k: {} for k in self.BUDGETS}
            self._week_start = current_week_start
            logger.info("[BUDGET-v7] Weekly counters reset")

    def can_use(self, resource: str, amount: int = 1) -> bool:
        self._check_week_reset()
        if resource not in self.BUDGETS:
            return True
        budget = self.BUDGETS[resource]
        current = self._usage.get(resource, 0)
        return (current + amount) <= budget['target_usage']

    def use(self, resource: str, amount: int = 1):
        self._check_week_reset()
        if resource not in self._usage:
            self._usage[resource] = 0
        self._usage[resource] += amount
        today = datetime.now(IST).weekday()
        if resource not in self._daily_usage:
            self._daily_usage[resource] = {}
        self._daily_usage[resource][today] = \
            self._daily_usage[resource].get(today, 0) + amount

    def get_remaining(self, resource: str) -> int:
        """Get remaining budget for a resource."""
        self._check_week_reset()
        if resource not in self.BUDGETS:
            return 999999
        used = self._usage.get(resource, 0)
        return max(0, self.BUDGETS[resource]['target_usage'] - used)

    def get_utilization_pct(self, resource: str) -> float:
        """Get current utilization percentage."""
        self._check_week_reset()
        if resource not in self.BUDGETS:
            return 0.0
        used = self._usage.get(resource, 0)
        target = self.BUDGETS[resource]['target_usage']
        return round(used / target * 100, 1) if target > 0 else 0.0

    def get_status(self) -> Dict[str, Dict[str, Any]]:
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
        status = self.get_status()
        lines = [
            "📊 <b>Weekly Resource Budget v7.0</b>",
            f"Week of {self._week_start.strftime('%b %d')} — AGGRESSIVE UTILIZATION",
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
                f"({s['pct_of_target']}%) | Limit headroom: {s['headroom_pct']}%"
            )

        return '\n'.join(lines)

    def get_rebalance_suggestions(self) -> List[str]:
        """AI-powered resource rebalancing suggestions."""
        suggestions = []
        status = self.get_status()

        for resource, s in status.items():
            if s['pct_of_target'] < 30:
                suggestions.append(
                    f"Under-utilized: {resource} at {s['pct_of_target']}% — "
                    f"consider increasing {resource} usage by {s['remaining_target']} units"
                )
            elif s['pct_of_target'] > 95:
                suggestions.append(
                    f"Near-limit: {resource} at {s['pct_of_target']}% — "
                    f"reduce or redistribute usage"
                )

        return suggestions


# ============================================================
# AI TASK EXECUTOR — v7.0 NEW
# ============================================================

class AITaskExecutor:
    """
    Executes AI-enhanced tasks within the scheduler.
    Uses Cerebras for fast tasks and Groq for deep analysis.
    """

    def __init__(self, budget: WeeklyResourceBudget):
        self._budget = budget

    async def run_quality_scoring(self, listings: List[Dict]) -> List[Dict]:
        """AI quality scoring on scraped listings."""
        if not self._budget.can_use('ai_quality_checks', len(listings)):
            logger.info("[AI-QS] Budget exhausted for quality checks")
            return listings

        try:
            from core.ai_router import get_router
            router = get_router()

            scored = []
            for listing in listings[:50]:  # Batch limit
                prompt = (
                    f"Rate this job listing quality 0-100 for an MBA intern.\n"
                    f"Title: {listing.get('title', '')}\n"
                    f"Company: {listing.get('company', '')}\n"
                    f"Stipend: {listing.get('stipend', 'N/A')}\n"
                    f"Location: {listing.get('location', '')}\n"
                    f"Source: {listing.get('source', '')}\n\n"
                    f"JSON: {{\"quality_score\": 0-100, \"reason\": \"...\"}}"
                )
                resp = router.call('quick_classify', prompt)
                if resp.success:
                    try:
                        data = resp.get_json()
                        if data:
                            listing['ai_quality_score'] = data.get('quality_score', 50)
                    except Exception:
                        listing['ai_quality_score'] = 50
                scored.append(listing)
                self._budget.use('ai_quality_checks')

            logger.info(f"[AI-QS] Scored {len(scored)} listings")
            return scored

        except Exception as e:
            logger.error(f"[AI-QS] Quality scoring error: {e}")
            return listings

    async def run_anomaly_detection(self, day_stats: Dict) -> Dict:
        """AI anomaly detection on daily scraping results."""
        if not self._budget.can_use('ai_anomaly_scans'):
            return {'anomalies': [], 'healthy': True}

        try:
            from core.ai_router import get_router
            router = get_router()

            prompt = (
                f"Analyze these scraping statistics for anomalies:\n"
                f"{json.dumps(day_stats, indent=2)}\n\n"
                f"Look for: sudden drops in listings, unusual duplicate rates, "
                f"portal failures, proxy issues.\n"
                f"JSON: {{\"anomalies\": [...], \"healthy\": true/false, \"recommendations\": [...]}}"
            )

            resp = router.call('quick_classify', prompt)
            self._budget.use('ai_anomaly_scans')

            if resp.success:
                data = resp.get_json()
                if data:
                    return data

            return {'anomalies': [], 'healthy': True}

        except Exception as e:
            logger.error(f"[AI-AD] Anomaly detection error: {e}")
            return {'anomalies': [], 'healthy': True}

    async def run_schedule_optimization(self, current_stats: Dict) -> Dict:
        """AI-powered schedule optimization for the rest of the day."""
        if not self._budget.can_use('cerebras_requests', 2):
            return {}

        try:
            from core.ai_router import get_router
            router = get_router()

            today = datetime.now(IST).strftime("%A")
            prompt = (
                f"Given today's ({today}) scraping results so far:\n"
                f"{json.dumps(current_stats, indent=2)}\n\n"
                f"Suggest optimizations for the afternoon/evening scraping:\n"
                f"- Which portals to prioritize?\n"
                f"- Should we increase/decrease batch sizes?\n"
                f"- Any portals to skip (if they're blocked)?\n"
                f"JSON: {{\"priority_portals\": [...], \"skip_portals\": [...], "
                f"\"batch_size_factor\": 1.0, \"recommendations\": [...]}}"
            )

            resp = router.call('quick_classify', prompt)
            self._budget.use('cerebras_requests', 2)

            if resp.success:
                return resp.get_json() or {}
            return {}

        except Exception as e:
            logger.error(f"[AI-SO] Schedule optimization error: {e}")
            return {}


# ============================================================
# WEEKLY AGENT SCHEDULER v7.0 — AI-POWERED
# ============================================================

class WeeklyAgentScheduler:
    """
    v7.0: AI-powered weekly scheduler with 3-wave scraping,
    parallel pipelines, deep crawl windows, and resource optimization.
    """

    def __init__(self):
        self.config = get_config()
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False
        self._tracker = ExecutionTracker()
        self._router = PortalDayRouter()
        self._budget = WeeklyResourceBudget()
        self._ai_executor = AITaskExecutor(self._budget)
        self._job_count = 0
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._day_stats: Dict[str, Any] = {}
        # Schedule conflict avoidance: tracks when a manual /run all or /run pipeline was triggered
        # If a manual run happened within CONFLICT_COOLDOWN_SEC before a scheduled job,
        # that scheduled job is SKIPPED to avoid portal clashes and duplicate scraping.
        self._last_manual_pipeline_run: float = 0.0
        self._manual_pipeline_running: bool = False
        self.CONFLICT_COOLDOWN_SEC: int = 3600  # 60 minutes cooldown after admin trigger

    def mark_manual_pipeline_run(self, running: bool = True):
        """Called by /run pipeline or /run all to record the timestamp.
        Scheduled scraping jobs within CONFLICT_COOLDOWN_SEC will be skipped.
        Call with running=False when the manual pipeline completes."""
        self._last_manual_pipeline_run = time.time()
        self._manual_pipeline_running = running
        if running:
            logger.info(f"[WEEKLY-SCHEDULER] Manual pipeline run STARTED at {time.time():.0f}. "
                         f"ALL scheduled scrapes will be PAUSED until completion + {self.CONFLICT_COOLDOWN_SEC}s cooldown.")
        else:
            logger.info(f"[WEEKLY-SCHEDULER] Manual pipeline run COMPLETED. "
                         f"Scheduled scrapes will resume after {self.CONFLICT_COOLDOWN_SEC}s cooldown.")

    def should_skip_scheduled_scrape(self, job_id: str = '') -> bool:
        """Check if a scheduled scrape should be skipped because a manual run is active or just completed."""
        # Skip if manual pipeline is currently running
        if self._manual_pipeline_running:
            logger.info(f"[WEEKLY-SCHEDULER] SKIPPING scheduled '{job_id}' — admin manual pipeline is STILL RUNNING")
            return True

        if self._last_manual_pipeline_run <= 0:
            return False
        elapsed = time.time() - self._last_manual_pipeline_run
        if elapsed < self.CONFLICT_COOLDOWN_SEC:
            logger.info(f"[WEEKLY-SCHEDULER] SKIPPING scheduled '{job_id}' — manual run was {elapsed:.0f}s ago "
                         f"(cooldown: {self.CONFLICT_COOLDOWN_SEC}s)")
            return True
        return False

    @property
    def router(self) -> PortalDayRouter:
        return self._router

    @property
    def budget(self) -> WeeklyResourceBudget:
        return self._budget

    async def start(self):
        """Start the v7.0 weekly scheduler with all AI-enhanced jobs."""
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
                'day_of_week': entry.days_of_week,
            }

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
        self._scheduler.add_job(
            self._keep_alive,
            IntervalTrigger(minutes=10),
            id='keep_alive',
            name='[SYS] Keep-Alive Ping',
            misfire_grace_time=600,
            coalesce=True,
        )
        self._job_count += 1

        self._scheduler.add_job(
            self._run_maintenance,
            CronTrigger(hour=3, minute=0, timezone='Asia/Kolkata'),
            id='db_maintenance',
            name='[SYS] DB Maintenance',
            misfire_grace_time=3600,
        )
        self._job_count += 1

        self._scheduler.add_job(
            self._proxy_health_check,
            IntervalTrigger(hours=1),  # v7.0: Every hour (was 2h)
            id='proxy_health',
            name='[SYS] Proxy Health Check',
            misfire_grace_time=3600,
            coalesce=True,
        )
        self._job_count += 1

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
            IntervalTrigger(hours=6, jitter=1200),  # v7.0: Every 6h (was 8h)
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
            f"[WEEKLY-SCHEDULER-v7] Started with {self._job_count} jobs "
            f"({len(WEEKLY_SCHEDULE)} weekly + infrastructure) — "
            f"AI-enhanced, 3-wave, deep crawl enabled"
        )

        # Startup pipeline check
        await self._check_and_run_startup_pipeline()

    async def stop(self):
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as e:
                logger.warning(f"[WEEKLY-SCHEDULER-v7] Shutdown error: {e}")
            self._running = False
            logger.info("[WEEKLY-SCHEDULER-v7] Stopped")

    def is_running(self) -> bool:
        return self._running

    def get_job_list(self) -> List[Dict]:
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
        lines = [
            "🕐 <b>Weekly Smart Schedule v7.0 (IST)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        lines.append(self._router.get_schedule_summary())
        lines.append("")
        lines.append("📋 <b>Scheduled Jobs:</b>")
        for entry in WEEKLY_SCHEDULE:
            if not entry.enabled:
                continue
            time_str = f"{entry.hour:02d}:{entry.minute:02d}"
            status = "🟢" if self._running else "🔴"
            ai_tag = " 🤖" if entry.ai_enhanced else ""
            deep_tag = " 🔬" if entry.deep_mode else ""
            lines.append(
                f"{status} {time_str} ({entry.days_of_week}) "
                f"[{entry.agent}] {entry.description}{ai_tag}{deep_tag}"
            )
        return '\n'.join(lines)

    def get_execution_stats(self) -> Dict[str, Any]:
        return self._tracker.get_stats()

    # ================================================================
    # EVENT HANDLERS
    # ================================================================

    def _on_job_executed(self, event):
        logger.debug(f"[WEEKLY-SCHEDULER-v7] Job '{event.job_id}' executed OK")

    def _on_job_error(self, event):
        logger.error(f"[WEEKLY-SCHEDULER-v7] Job '{event.job_id}' error: {event.exception}")
        self._tracker.record(JobExecution(
            job_id=event.job_id, success=False, error=str(event.exception),
        ))

    def _on_job_missed(self, event):
        logger.warning(f"[WEEKLY-SCHEDULER-v7] Job '{event.job_id}' missed!")

    # ================================================================
    # HANDLER ROUTER
    # ================================================================

    def _get_handler(self, job_id: str) -> Optional[Callable]:
        handlers = {
            # Smart day-routed portal scraping (3 waves)
            'smart_portal_scrape_am': self._run_smart_portal_scrape_am,
            'smart_portal_scrape_pm': self._run_smart_portal_scrape_pm,
            'smart_portal_scrape_night': self._run_smart_portal_scrape_night,
            # AI-enhanced tasks (v7.0 NEW)
            'ai_quality_scoring_am': self._run_ai_quality_scoring,
            'ai_schedule_optimize': self._run_ai_schedule_optimize,
            'ai_anomaly_check': self._run_ai_anomaly_check,
            'ai_resource_rebalance': self._run_ai_resource_rebalance,
            # Smart tier-based ATS crawl
            'smart_ats_crawl': self._run_smart_ats_crawl,
            'night_ats_deep': self._run_night_ats_deep,
            # Processing pipeline
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
            'sunday_ai_retrain': self._run_weekly_retrain,
            'weekly_retrain': self._run_weekly_retrain,
            # ---- PRISM v0.1: NEW AGENT HANDLERS ----
            'auto_apply_am': self._run_auto_apply,
            'auto_apply_pm': self._run_auto_apply,
            'email_outreach': self._run_email_outreach,
            'outcome_followup': self._run_outcome_followup,
            'company_intel': self._run_company_intel,
            'sunday_alumni_remap': self._run_alumni_remap,
            'ai_router_nightly_reset': self._run_ai_router_reset,
        }
        return handlers.get(job_id)

    # ================================================================
    # SAFE RUNNER v7.0 (enhanced with circuit breaker + parallel)
    # ================================================================

    async def _safe_run(self, name: str, func: Callable, *args, **kwargs):
        """Enhanced job runner with circuit breaker and budget tracking."""
        execution = JobExecution(job_id=name, start_time=time.time())
        job_timeout = kwargs.pop('job_timeout', 1800)
        max_retries = kwargs.pop('max_retries', 3)  # v7.0: 3 retries (was 2)
        retry_delay = 30

        # Check circuit breaker
        breaker = self._circuit_breakers.get(name)
        if breaker and breaker.is_open:
            logger.warning(f"[WEEKLY-SCHEDULER-v7] {name}: circuit breaker OPEN, skipping")
            return None

        self_managed_agents = {
            'A-01', 'A-02', 'A-03', 'A-04', 'A-05',
            'A-06', 'A-07', 'A-08', 'A-11'
        }

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"[WEEKLY-SCHEDULER-v7] {name}: retry {attempt}/{max_retries}")
                else:
                    logger.info(f"[WEEKLY-SCHEDULER-v7] Running {name}...")

                loop = asyncio.get_running_loop()
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

                if name in self._circuit_breakers:
                    self._circuit_breakers[name].record_success()

                agent_id = name.split(' ')[0] if ' ' in name else name
                if agent_id not in self_managed_agents:
                    self._update_heartbeat(name, execution)

                duration = execution.duration_sec
                logger.info(f"[WEEKLY-SCHEDULER-v7] {name} completed in {duration}s")

                # Record stats for AI anomaly detection
                self._day_stats[name] = {
                    'success': True,
                    'duration': duration,
                    'items': execution.items_processed,
                    'timestamp': time.time(),
                }

                return result

            except asyncio.TimeoutError:
                last_error = f"Timed out after {job_timeout}s"
                logger.error(f"[WEEKLY-SCHEDULER-v7] {name} TIMED OUT")
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(f"[WEEKLY-SCHEDULER-v7] {name} failed (attempt {attempt}): {last_error}")
                if attempt < max_retries:
                    delay = retry_delay * attempt * random.uniform(0.8, 1.2)
                    await asyncio.sleep(delay)

        # All retries exhausted
        execution.success = False
        execution.error = last_error
        execution.end_time = time.time()
        self._tracker.record(execution)

        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(name)
        self._circuit_breakers[name].record_failure()

        self._update_heartbeat(name, execution)
        self._day_stats[name] = {
            'success': False,
            'error': last_error,
            'timestamp': time.time(),
        }

        logger.error(f"[WEEKLY-SCHEDULER-v7] {name} FAILED after {max_retries} attempts")
        await self._alert_job_failure(name, last_error)
        return None

    async def _safe_run_parallel(self, jobs: List[Tuple[str, Callable]]):
        """Run multiple jobs in parallel (v7.0 NEW)."""
        tasks = []
        for name, func in jobs:
            tasks.append(self._safe_run(name, func))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[PARALLEL] {jobs[i][0]} failed: {result}")
        return results

    # ================================================================
    # WAVE 1: MORNING PORTAL SCRAPE (AI-ENHANCED)
    # ================================================================

    async def _run_smart_portal_scrape_am(self):
        # PRISM v0.1: Skip if manual run happened recently (conflict avoidance)
        if self.should_skip_scheduled_scrape('smart_portal_scrape_am'):
            return

        portals = self._router.get_today_portals("am")
        proxy_pool = self._router.get_today_proxy_pool()
        if not portals:
            logger.info("[WEEKLY-SCHEDULER-v7] No AM portals scheduled today")
            return

        logger.info(f"[WEEKLY-SCHEDULER-v7] Wave 1 AM: {portals} (proxies: {proxy_pool})")

        from agents.a03_primary_scraper import get_primary_scraper
        scraper = get_primary_scraper()
        scraper.set_active_portals(portals)
        scraper.set_proxy_pool_indices(proxy_pool)

        result = await self._safe_run(
            'A-03 Wave1 AM Scrape',
            scraper.run_morning_scrape,
            job_timeout=3600,
        )

        # Send run report with portal details
        if result and isinstance(result, dict):
            result['portals'] = portals
        elif result is None:
            result = {'portals': portals, 'new': 0}
        await self._send_scheduled_run_report('A-03 Wave 1 AM Scrape', result)

        await self._auto_process_pipeline("after Wave 1 AM scrape")
        await self._sync_to_supabase("wave1_am")
        self._budget.use('webshare_requests', len(portals) * 40)

    # ================================================================
    # WAVE 2: AFTERNOON PORTAL SCRAPE
    # ================================================================

    async def _run_smart_portal_scrape_pm(self):
        # PRISM v0.1: Skip if manual run happened recently (conflict avoidance)
        if self.should_skip_scheduled_scrape('smart_portal_scrape_pm'):
            return

        portals = self._router.get_today_portals("pm")
        proxy_pool = self._router.get_today_proxy_pool()
        if not portals:
            logger.info("[WEEKLY-SCHEDULER-v7] No PM portals scheduled today")
            return

        logger.info(f"[WEEKLY-SCHEDULER-v7] Wave 2 PM: {portals} (proxies: {proxy_pool})")

        from agents.a03_primary_scraper import get_primary_scraper
        scraper = get_primary_scraper()
        scraper.set_active_portals(portals)
        scraper.set_proxy_pool_indices(proxy_pool)

        result = await self._safe_run(
            'A-03 Wave2 PM Scrape',
            scraper.run_afternoon_scrape,
            job_timeout=2700,
        )

        if result and isinstance(result, dict):
            result['portals'] = portals
        elif result is None:
            result = {'portals': portals, 'new': 0}
        await self._send_scheduled_run_report('A-03 Wave 2 PM Scrape', result)

        await self._auto_process_pipeline("after Wave 2 PM scrape")
        await self._sync_to_supabase("wave2_pm")

    # ================================================================
    # WAVE 3: NIGHT DEEP CRAWL (v7.0 NEW)
    # ================================================================

    async def _run_smart_portal_scrape_night(self):
        """Night deep crawl — AI-selected portals with deep pagination."""
        # PRISM v0.1: Skip if manual run happened recently (conflict avoidance)
        if self.should_skip_scheduled_scrape('smart_portal_scrape_night'):
            return

        portals = self._router.get_today_portals("night")
        proxy_pool = self._router.get_today_proxy_pool()
        if not portals:
            logger.info("[WEEKLY-SCHEDULER-v7] No night portals selected")
            return

        logger.info(f"[WEEKLY-SCHEDULER-v7] Wave 3 Night Deep: {portals} (deep_mode=True)")

        from agents.a03_primary_scraper import get_primary_scraper
        scraper = get_primary_scraper()
        scraper.set_active_portals(portals)
        scraper.set_proxy_pool_indices(proxy_pool)

        # Deep mode: scrape more pages, follow deeper pagination
        result = await self._safe_run(
            'A-03 Wave3 Night Deep',
            scraper.run_afternoon_scrape,  # Uses deep config when set
            job_timeout=3600,
        )

        if result and isinstance(result, dict):
            result['portals'] = portals
        elif result is None:
            result = {'portals': portals, 'new': 0}
        await self._send_scheduled_run_report('A-03 Wave 3 Night Deep', result)

        await self._auto_process_pipeline("after Wave 3 Night deep")
        await self._sync_to_supabase("wave3_night")
        self._budget.use('webshare_requests', len(portals) * 50)

    # ================================================================
    # AI-ENHANCED TASKS (v7.0 NEW)
    # ================================================================

    async def _run_ai_quality_scoring(self):
        """Run AI quality scoring on recent listings."""
        try:
            from core.database import get_db
            db = get_db()
            recent = db.get_recent_clean_listings(days=1, limit=100)
            if recent:
                scored = await self._ai_executor.run_quality_scoring(recent)
                logger.info(f"[AI-QS] Quality scored {len(scored)} listings")
        except Exception as e:
            logger.error(f"[AI-QS] Error: {e}")

    async def _run_ai_schedule_optimize(self):
        """AI optimizes the afternoon schedule based on morning results."""
        try:
            suggestions = await self._ai_executor.run_schedule_optimization(self._day_stats)
            if suggestions:
                logger.info(f"[AI-SO] Schedule optimization: {json.dumps(suggestions)[:200]}")
        except Exception as e:
            logger.error(f"[AI-SO] Error: {e}")

    async def _run_ai_anomaly_check(self):
        """AI checks for anomalies in today's scraping results."""
        try:
            result = await self._ai_executor.run_anomaly_detection(self._day_stats)
            if result.get('anomalies'):
                logger.warning(f"[AI-AD] Anomalies detected: {result['anomalies']}")
                await self._alert_anomalies(result)
            else:
                logger.info("[AI-AD] No anomalies detected — all healthy")
        except Exception as e:
            logger.error(f"[AI-AD] Error: {e}")

    async def _run_ai_resource_rebalance(self):
        """AI rebalances resource allocation for next day."""
        try:
            suggestions = self._budget.get_rebalance_suggestions()
            if suggestions:
                logger.info(f"[AI-RB] Rebalance suggestions: {suggestions[:3]}")
        except Exception as e:
            logger.error(f"[AI-RB] Error: {e}")

    async def _alert_anomalies(self, result: Dict):
        """Send anomaly alert via Telegram."""
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()
            if reporter._running:
                anomalies = result.get('anomalies', [])
                recs = result.get('recommendations', [])
                msg = (
                    f"⚠️ <b>AI Anomaly Detection Alert</b>\n\n"
                    f"Anomalies found: {len(anomalies)}\n"
                )
                for a in anomalies[:5]:
                    msg += f"• {a}\n"
                if recs:
                    msg += f"\n💡 Recommendations:\n"
                    for r in recs[:3]:
                        msg += f"• {r}\n"
                await reporter.send_message(msg)
        except Exception:
            pass

    # ================================================================
    # ATS CRAWL
    # ================================================================

    async def _run_smart_ats_crawl(self):
        tiers, tier_label = self._router.get_today_company_batch()
        if not tiers:
            return
        logger.info(f"[WEEKLY-SCHEDULER-v7] ATS Crawl: tiers={tier_label}")

        from agents.a04_ats_crawler import get_ats_crawler
        crawler = get_ats_crawler()
        crawler.set_tier_filter(tiers)

        await self._safe_run('A-04 Smart ATS', crawler.run_crawl, job_timeout=3600)
        await self._auto_process_pipeline("after ATS crawl")
        await self._sync_to_supabase("ats_crawl")

    async def _run_night_ats_deep(self):
        """Night deep ATS crawl with AI-powered discovery."""
        logger.info("[WEEKLY-SCHEDULER-v7] Night ATS deep crawl starting...")
        from agents.a04_ats_crawler import get_ats_crawler
        crawler = get_ats_crawler()
        await self._safe_run(
            'A-04 Night ATS Deep',
            crawler.run_deep_discovery,
            job_timeout=3600,
        )

    # ================================================================
    # STANDARD JOB IMPLEMENTATIONS
    # ================================================================

    async def _run_dedup(self):
        from agents.a06_dedup_engine import get_dedup_engine
        await self._safe_run('A-06 Dedup', get_dedup_engine().run_dedup)

    async def _run_ghost_scoring(self):
        from agents.a05_ghost_detector import get_ghost_detector
        await self._safe_run('A-05 Ghost', get_ghost_detector().score_batch)

    async def _run_enrichment(self):
        from agents.a07_intelligence_enricher import get_intelligence_enricher
        await self._safe_run('A-07 Enrichment', get_intelligence_enricher().run_enrichment)

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
        self._budget.use('ddg_searches', 25)

    async def _run_dark_channels(self):
        from agents.a02_dark_channel import get_dark_channel_listener
        await self._safe_run('A-02 Dark', get_dark_channel_listener().run_batch_check)

    # ================================================================
    # PRISM v0.1: NEW AGENT HANDLERS
    # ================================================================

    async def _run_auto_apply(self):
        """Run A-13 Auto-Apply with Telegram run report."""
        from agents.a13_auto_apply import get_auto_apply_orchestrator
        applier = get_auto_apply_orchestrator()
        result = await self._safe_run('A-13 Auto-Apply', applier.run_auto_apply, job_timeout=1800)
        # Convert AutoApplyStats to dict for the report
        report_data = None
        if result and hasattr(result, 'applied'):
            report_data = {
                'processed': getattr(result, 'applied', 0),
                'errors': getattr(result, 'errors', []),
                'duration_sec': getattr(result, 'duration_sec', 0),
            }
        await self._send_scheduled_run_report('A-13 Auto-Apply', report_data or result)

    async def _run_email_outreach(self):
        """Run A-15 Email Auto-Applier via Brevo."""
        from agents.a15_email_applier import get_email_applier
        applier = get_email_applier()
        result = await self._safe_run('A-15 Email Outreach', applier.run_outreach, job_timeout=1200)
        report_data = None
        if result and hasattr(result, 'sent'):
            report_data = {
                'processed': getattr(result, 'sent', 0),
                'errors': getattr(result, 'errors', []),
            }
        await self._send_scheduled_run_report('A-15 Email Outreach', report_data or result)

    async def _run_outcome_followup(self):
        """Run A-19 Outcome Amplifier for follow-ups."""
        from agents.a19_outcome_amplifier import get_outcome_amplifier
        amplifier = get_outcome_amplifier()
        result = await self._safe_run('A-19 Follow-up', amplifier.run_followup_check, job_timeout=900)
        report_data = None
        if result and hasattr(result, 'followups_sent'):
            report_data = {
                'processed': getattr(result, 'followups_sent', 0),
                'errors': getattr(result, 'errors', []),
            }
        await self._send_scheduled_run_report('A-19 Outcome Amplifier', report_data or result)

    async def _run_company_intel(self):
        """Run A-20 Deep Company Intel before auto-apply."""
        from agents.a20_company_intel import get_company_intel
        intel = get_company_intel()
        result = await self._safe_run('A-20 Company Intel', intel.research_batch, job_timeout=1500)
        await self._send_scheduled_run_report('A-20 Company Intel', result)

    async def _run_alumni_remap(self):
        """Run A-09 Network Mapper for alumni re-mapping (Sunday)."""
        from agents.a09_network_mapper import get_network_mapper
        mapper = get_network_mapper()
        result = await self._safe_run('A-09 Alumni Remap', mapper.map_network, job_timeout=1800)
        report_data = None
        if result and hasattr(result, 'alumni_found'):
            report_data = {
                'processed': getattr(result, 'alumni_found', 0),
            }
        await self._send_scheduled_run_report('A-09 Alumni Remap', report_data or result)

    async def _run_ai_router_reset(self):
        """Run A-14 nightly quota reset."""
        from agents.a14_multi_model_router import get_multi_model_router
        router = get_multi_model_router()
        result = await self._safe_run('A-14 Nightly Reset', router.nightly_reset, job_timeout=120)
        await self._send_scheduled_run_report('A-14 AI Router Reset', result)

    # ================================================================
    # SCHEDULED RUN TELEGRAM REPORT
    # ================================================================

    async def _send_scheduled_run_report(self, agent_name: str, result: Any):
        """Send a Telegram report after each scheduled agent run.
        Reports: agent name, portal scraped, jobs found, total DB jobs."""
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()
            if not reporter._running:
                return

            from core.database import get_db
            db = get_db()

            # Gather DB stats
            total_raw = db.count_raw_listings()
            total_clean = db.count_clean_listings(status='active')
            source_counts = db.get_source_counts()
            raw_source_counts = db.get_raw_source_counts()

            # Extract result info
            items = 0
            portals_scraped = []
            errors = []
            duration = 0.0
            if isinstance(result, dict):
                items = result.get('new', 0) or result.get('total', 0) or result.get('processed', 0) or result.get('items', 0)
                portals_scraped = result.get('portals', []) or result.get('sources', [])
                errors = result.get('errors', [])
                duration = result.get('duration', 0.0) or result.get('duration_sec', 0.0)

            now_ist = datetime.now(IST).strftime('%H:%M IST')
            portal_str = ', '.join(portals_scraped) if portals_scraped else 'N/A'

            # Source breakdown
            source_lines = []
            for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
                raw_cnt = raw_source_counts.get(src, 0)
                source_lines.append(f"  {src}: {cnt} clean / {raw_cnt} raw")

            msg = (
                f"{'=' * 28}\n"
                f"SCHEDULED RUN REPORT\n"
                f"{'=' * 28}\n\n"
                f"Agent: <b>{agent_name}</b>\n"
                f"Time: {now_ist}\n"
                f"Status: {'OK' if result is not None else 'FAILED'}\n"
                f"Items Processed: <b>{items}</b>\n"
                f"Portals: {portal_str}\n"
                f"Duration: {duration:.1f}s\n\n"
                f"DATABASE STATUS:\n"
                f"  Total Raw Listings: <b>{total_raw}</b>\n"
                f"  Total Clean (Active): <b>{total_clean}</b>\n\n"
                f"SOURCE BREAKDOWN:\n"
            )
            if source_lines:
                msg += '\n'.join(source_lines[:12])
            else:
                msg += '  No listings yet'

            if errors:
                msg += f"\n\nErrors ({len(errors)}):\n"
                for err in errors[:3]:
                    msg += f"  {str(err)[:80]}\n"

            msg += f"\n{'=' * 28}"

            await reporter.send_message(msg)
        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER] Run report send failed: {e}")

    # ================================================================
    # SUNDAY DEEP OPERATIONS
    # ================================================================

    async def _run_sunday_deep_enrichment(self):
        logger.info("[WEEKLY-SCHEDULER-v7] Sunday deep enrichment (AI-intensive)...")
        from agents.a07_intelligence_enricher import get_intelligence_enricher
        enricher = get_intelligence_enricher()
        await self._safe_run(
            'A-07 Sunday Deep',
            enricher.run_deep_enrichment,
            job_timeout=5400,
        )

    async def _run_sunday_deep_ats(self):
        logger.info("[WEEKLY-SCHEDULER-v7] Sunday deep ATS (AI-powered discovery)...")
        from agents.a04_ats_crawler import get_ats_crawler
        crawler = get_ats_crawler()
        await self._safe_run(
            'A-04 Sunday Deep ATS',
            crawler.run_deep_discovery,
            job_timeout=5400,
        )

    async def _run_weekly_retrain(self):
        from agents.a11_outcome_learner import get_outcome_learner
        await self._safe_run('A-11 Retrain', get_outcome_learner().run_weekly_retrain)

    # ================================================================
    # AUTO-PROCESS PIPELINE v7.0 (with parallel option)
    # ================================================================

    async def _auto_process_pipeline(self, trigger_reason: str = ""):
        logger.info(f"[WEEKLY-SCHEDULER-v7] Auto-processing pipeline ({trigger_reason})...")

        try:
            from core.database import get_db
            db = get_db()
            unprocessed = db.count_unprocessed_raw_listings()
            if unprocessed == 0:
                logger.info("[WEEKLY-SCHEDULER-v7] 0 unprocessed listings, skipping")
                return
            logger.info(f"[WEEKLY-SCHEDULER-v7] {unprocessed} unprocessed raw listings")
        except Exception as e:
            logger.warning(f"[WEEKLY-SCHEDULER-v7] Auto-process check failed: {e}")

        # Run dedup + ghost in parallel, then enrich + PPO sequentially
        try:
            # Phase 1: Parallel dedup + ghost
            from agents.a06_dedup_engine import get_dedup_engine
            from agents.a05_ghost_detector import get_ghost_detector
            await self._safe_run_parallel([
                ('A-06 Auto-Dedup', get_dedup_engine().run_dedup),
                ('A-05 Auto-Ghost', get_ghost_detector().score_batch),
            ])
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER-v7] Parallel dedup+ghost failed: {e}")

        # Phase 2: Sequential enrich + PPO
        steps = [
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
                logger.error(f"[WEEKLY-SCHEDULER-v7] {step_name} failed: {e}")

        logger.info("[WEEKLY-SCHEDULER-v7] Auto-processing pipeline complete")

    # ================================================================
    # SUPABASE INTEGRATION
    # ================================================================

    async def _sync_to_supabase(self, trigger: str = ""):
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
            tier_map = {1: 'tier1', 2: 'tier2', 3: 'tier3', 4: 'startup', 5: 'startup'}
            for row in recent:
                tier_num = row.get("tier")
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
                    "company_tier": tier_map.get(tier_num, "startup") if tier_num else "startup",
                    "is_premium": bool(row.get("is_blue_ocean", False)),
                    "is_verified": True,
                    "skills": row.get("skills", "[]"),
                })

            batch_id = f"sync_{trigger}_{datetime.now(IST).strftime('%Y%m%d_%H%M')}"
            count = await async_insert_latest_jobs(jobs, batch_id)
            logger.info(f"[WEEKLY-SCHEDULER-v7] Supabase sync: {count}/{len(jobs)} ({trigger})")

            try:
                all_count = await async_insert_all_jobs(jobs, batch_id)
                logger.info(f"[WEEKLY-SCHEDULER-v7] all_jobs sync: {all_count}/{len(jobs)}")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER-v7] Supabase sync error: {e}")

    async def _supabase_ping(self):
        try:
            from core.supabase_keepalive import scheduler_ping
            result = await scheduler_ping()
            if result.get("success"):
                logger.debug("[WEEKLY-SCHEDULER-v7] Supabase ping OK")
        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER-v7] Supabase ping error: {e}")

    async def _supabase_morning_merge(self):
        try:
            from core.supabase_db import async_merge_latest_to_all, async_cleanup_expired_jobs
            from core.supabase_client import is_operational
            if not is_operational():
                return
            merged, total = await async_merge_latest_to_all()
            logger.info(f"[WEEKLY-SCHEDULER-v7] Merge: {merged} from {total}")
            deleted = await async_cleanup_expired_jobs(days=7)
            if deleted > 0:
                logger.info(f"[WEEKLY-SCHEDULER-v7] Cleanup: {deleted} expired")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER-v7] Morning merge error: {e}")

    async def _supabase_cleanup(self):
        try:
            from core.supabase_db import async_cleanup_expired_jobs
            from core.supabase_client import is_operational
            if not is_operational():
                return
            deleted = await async_cleanup_expired_jobs(days=7)
            logger.info(f"[WEEKLY-SCHEDULER-v7] Cleanup: {deleted} expired")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER-v7] Cleanup error: {e}")

    # ================================================================
    # INFRASTRUCTURE
    # ================================================================

    async def _keep_alive(self):
        logger.debug("[WEEKLY-SCHEDULER-v7] Keep-alive ping")
        try:
            import aiohttp
            port = int(os.getenv('PORT', '10000'))
            external_url = os.getenv('RENDER_EXTERNAL_URL', '')
            url = f"{external_url}/ping" if external_url else f"http://127.0.0.1:{port}/ping"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        logger.debug("[WEEKLY-SCHEDULER-v7] Keep-alive OK")
        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER-v7] Keep-alive error: {e}")

    async def _run_maintenance(self):
        logger.info("[WEEKLY-SCHEDULER-v7] Running DB maintenance...")
        try:
            from core.database import get_db
            db = get_db()
            db.cleanup_old_data(days=30)
            db.analyze()
            logger.info("[WEEKLY-SCHEDULER-v7] DB maintenance complete")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER-v7] Maintenance error: {e}")

    async def _proxy_health_check(self):
        try:
            from core.stealth_engine import get_stealth_client
            client = get_stealth_client()
            result = client.proxy_pool.health_check_all()
            alive = result.get('alive', 0)
            dead = result.get('dead', 0)
            logger.info(
                f"[WEEKLY-SCHEDULER-v7] Proxy health: "
                f"{alive} alive, {dead} dead"
            )

            # If too many proxies are dead, refresh the proxy list
            total = alive + dead
            if total > 0 and dead / total > 0.7:
                logger.info(
                    f"[WEEKLY-SCHEDULER-v7] >70% proxies dead ({dead}/{total}), "
                    f"refreshing proxy list..."
                )
                try:
                    # Clear dead proxies and reload
                    pool = client.proxy_pool
                    with pool._lock:
                        # Remove dead proxies
                        alive_proxies = [
                            p for p in pool._free_proxies
                            if pool._proxy_health.get(p, {}).get('alive', False)
                        ]
                        pool._free_proxies = alive_proxies
                    # Reload fresh proxies
                    pool._load_free_proxies()
                    logger.info(
                        f"[WEEKLY-SCHEDULER-v7] Proxy list refreshed: "
                        f"{len(pool._free_proxies)} proxies in pool"
                    )
                except Exception as e:
                    logger.warning(f"[WEEKLY-SCHEDULER-v7] Proxy refresh error: {e}")

        except Exception as e:
            logger.debug(f"[WEEKLY-SCHEDULER-v7] Proxy health error: {e}")

    async def _send_budget_report(self):
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
                    f"⚠️ <b>Job Failed (v7.0)</b>\n"
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
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        try:
            IST_TZ = _tz(_td(hours=5, minutes=30))
            now_ist = _dt.now(IST_TZ)

            from core.database import get_db
            db = get_db()
            total_active = total_raw = 0
            try:
                with db.get_cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM clean_listings WHERE status = 'active'")
                    total_active = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM raw_listings")
                    total_raw = cur.fetchone()[0]
            except Exception:
                pass

            should_scrape = should_process = False
            reason = ""

            if total_active == 0 and total_raw == 0:
                should_scrape = should_process = True
                reason = "no data at all (fresh start)"
            elif total_active == 0 and total_raw > 0:
                should_process = True
                reason = f"{total_raw} raw listings need processing"
            elif 6 <= now_ist.hour <= 12 and total_active == 0:
                should_scrape = should_process = True
                reason = "no active listings during morning window"

            if not should_scrape and not should_process:
                logger.info(f"[WEEKLY-SCHEDULER-v7] Startup: SKIP (active={total_active}, raw={total_raw})")
                return

            logger.info(f"[WEEKLY-SCHEDULER-v7] STARTUP PIPELINE: {reason}")

            if should_scrape:
                try:
                    from agents.a03_primary_scraper import get_primary_scraper
                    scraper = get_primary_scraper()
                    portals = self._router.get_today_portals("am")
                    if portals:
                        scraper.set_active_portals(portals)
                    await self._safe_run('A-03 Startup Scrape', scraper.run_afternoon_scrape)
                except Exception as e:
                    logger.error(f"[WEEKLY-SCHEDULER-v7] Startup scrape error: {e}")

            if should_process:
                await self._auto_process_pipeline("startup pipeline")

            logger.info("[WEEKLY-SCHEDULER-v7] Startup pipeline complete")
        except Exception as e:
            logger.error(f"[WEEKLY-SCHEDULER-v7] Startup error: {e}")


# ============================================================
# CIRCUIT BREAKER (Enhanced v7.0)
# ============================================================

class CircuitBreaker:
    """Enhanced circuit breaker with exponential reset timeout."""

    def __init__(self, name: str, threshold: int = 3, reset_timeout: int = 900):
        self.name = name
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = "closed"
        self._consecutive_opens = 0

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            # Exponential reset timeout
            actual_timeout = self.reset_timeout * (2 ** min(self._consecutive_opens, 4))
            if time.time() - self._last_failure_time > actual_timeout:
                self._state = "half-open"
                return False
            return True
        return False

    def record_failure(self):
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.threshold:
            if self._state != "open":
                self._consecutive_opens += 1
            self._state = "open"
            logger.warning(
                f"[CIRCUIT-BREAKER-v7] {self.name}: OPENED "
                f"(failures={self._failures}, opens={self._consecutive_opens})"
            )

    def record_success(self):
        self._failures = 0
        self._state = "closed"
        self._consecutive_opens = max(0, self._consecutive_opens - 1)


# ============================================================
# EXECUTION TRACKER
# ============================================================

@dataclass
class JobExecution:
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
    def __init__(self, max_history: int = 500):
        self._history: List[JobExecution] = []
        self._max = max_history

    def record(self, execution: JobExecution):
        self._history.append(execution)
        if len(self._history) > self._max:
            self._history = self._history[-self._max:]

    def get_recent(self, limit: int = 30) -> List[JobExecution]:
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


def get_scheduler() -> WeeklyAgentScheduler:
    """Drop-in replacement for core.scheduler.get_scheduler()"""
    return get_weekly_scheduler()


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Weekly Smart Scheduler v7.0 — Self-Test")
    print("=" * 60)

    print(f"\n  APScheduler available: {'yes' if SCHEDULER_AVAILABLE else 'no'}")
    print(f"  Schedule entries: {len(WEEKLY_SCHEDULE)}")
    ai_entries = sum(1 for e in WEEKLY_SCHEDULE if e.ai_enhanced)
    deep_entries = sum(1 for e in WEEKLY_SCHEDULE if e.deep_mode)
    print(f"  AI-enhanced entries: {ai_entries}")
    print(f"  Deep crawl entries: {deep_entries}")

    router = PortalDayRouter()
    print(f"\n  Today's AM portals: {router.get_today_portals('am')}")
    print(f"  Today's PM portals: {router.get_today_portals('pm')}")
    print(f"  Today's Night portals: {router.get_today_portals('night')}")
    print(f"  Today's ATS tiers: {router.get_today_company_tiers()}")
    print(f"  Today's proxy pool: {router.get_today_proxy_pool()}")
    print(f"  Deep crawl day: {router.is_deep_crawl_day()}")

    budget = WeeklyResourceBudget()
    print(f"\n  Budget status (v7.0 — aggressive):")
    for resource, status in budget.get_status().items():
        print(f"    {resource}: {status['used']}/{status['target']} "
              f"(headroom: {status['headroom_pct']}%)")

    coverage = router.get_weekly_coverage_report()
    print(f"\n  Weekly coverage:")
    print(f"    Portals: {coverage['portals_per_week']}")
    print(f"    Companies/week: {coverage['companies_per_week']}")
    print(f"    Waves/day: {coverage['waves_per_day']}")
    print(f"    Deep crawl days: {coverage['deep_crawl_days']}")
    print(f"    AI tasks/day: {coverage['ai_tasks_per_day']}")

    print("\n" + "=" * 60)
