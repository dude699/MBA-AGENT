"""
============================================================
OPERATION FIRST MOVER v5.1 — SCHEDULER (INDUSTRIAL GRADE)
============================================================
APScheduler-based 24-hour IST schedule that orchestrates
all 12 agents according to the daily schedule.

Schedule (IST):
    05:30  A-03  Internshala full scrape (10 categories)       45 min
    06:00  A-06  Dedup engine on overnight batch                15 min
    06:15  A-05  Ghost scoring (Cerebras)                       20 min
    06:30  A-07  Intelligence enrichment                        15 min
    07:00  A-08  PPO model runs → top 25 shortlist              10 min
    07:15  A-12  MORNING BRIEF → Telegram                        1 min
    09:00  A-01  Intent signal scan (Tier 1+2)                  30 min
    12:00  A-03  Naukri + IIMjobs scrape                        30 min
    14:00  A-04  Company ATS pages (Greenhouse/Lever/Workday)   45 min
    16:00  A-01  Second intent scan                             30 min
    18:00  A-06+07  Afternoon batch dedup + enrichment          20 min
    20:00  A-02  Telegram dark channel batch check              15 min
    22:00  A-12  EVENING SUMMARY → Telegram                      1 min
    23:00  A-04  Nightly company career page crawl              60 min
    Sun 21:00  A-11  Weekly outcome learner / retrain PPO       10 min

Infrastructure:
    Every 10 min  Keep-alive ping (Render anti-sleep)
    03:00 AM      DB maintenance (VACUUM, cleanup, backup)
    Every 30 min  Proxy health check
============================================================
"""

import os
import time
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field

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
# SCHEDULE CONFIGURATION
# ============================================================

@dataclass
class ScheduleEntry:
    """A single scheduled job entry."""
    job_id: str
    description: str
    agent: str
    hour: int
    minute: int
    day_of_week: str = "*"  # "*" = every day, "sun" = Sunday only
    estimated_duration_min: int = 15
    enabled: bool = True
    priority: int = 5  # 1=highest, 10=lowest


# Full 24-hour IST schedule
DAILY_SCHEDULE: List[ScheduleEntry] = [
    # ---- MORNING PIPELINE (05:30 - 07:15) ----
    ScheduleEntry("morning_scrape", "Internshala full scrape (10 categories)", "A-03", 5, 30, estimated_duration_min=45, priority=1),
    ScheduleEntry("morning_dedup", "Dedup engine on overnight batch", "A-06", 6, 0, estimated_duration_min=15, priority=2),
    ScheduleEntry("ghost_scoring", "Ghost scoring (Cerebras)", "A-05", 6, 15, estimated_duration_min=20, priority=2),
    ScheduleEntry("morning_enrichment", "Intelligence enrichment", "A-07", 6, 30, estimated_duration_min=15, priority=3),
    ScheduleEntry("ppo_scoring", "PPO model scoring → top 25", "A-08", 7, 0, estimated_duration_min=10, priority=2),
    ScheduleEntry("morning_brief", "MORNING BRIEF → Telegram", "A-12", 7, 15, estimated_duration_min=1, priority=1),

    # ---- DAYTIME (09:00 - 16:00) ----
    ScheduleEntry("intent_am", "Intent signal scan AM (Tier 1+2)", "A-01", 9, 0, estimated_duration_min=30, priority=3),
    ScheduleEntry("afternoon_scrape", "Naukri + IIMjobs scrape", "A-03", 12, 0, estimated_duration_min=30, priority=2),
    ScheduleEntry("ats_afternoon", "Company ATS crawl (GH/Lever/WD)", "A-04", 14, 0, estimated_duration_min=45, priority=3),
    ScheduleEntry("intent_pm", "Intent signal scan PM", "A-01", 16, 0, estimated_duration_min=30, priority=4),

    # ---- EVENING (18:00 - 23:00) ----
    ScheduleEntry("evening_dedup", "Afternoon batch dedup", "A-06", 18, 0, estimated_duration_min=15, priority=3),
    ScheduleEntry("evening_enrichment", "Afternoon enrichment", "A-07", 18, 20, estimated_duration_min=15, priority=3),
    ScheduleEntry("dark_channels", "Dark channel batch check", "A-02", 20, 0, estimated_duration_min=15, priority=4),
    ScheduleEntry("evening_summary", "EVENING SUMMARY → Telegram", "A-12", 22, 0, estimated_duration_min=1, priority=1),
    ScheduleEntry("ats_night", "Nightly ATS crawl (300 companies)", "A-04", 23, 0, estimated_duration_min=60, priority=4),

    # ---- WEEKLY ----
    ScheduleEntry("weekly_retrain", "Weekly PPO weight retrain", "A-11", 21, 0, day_of_week="sun", estimated_duration_min=10, priority=5),
]


# ============================================================
# JOB EXECUTION TRACKER
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

    def __init__(self, max_history: int = 100):
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
# AGENT SCHEDULER
# ============================================================

class AgentScheduler:
    """
    24-hour IST scheduler for all 12 agents.
    Uses APScheduler's AsyncIOScheduler with CronTrigger
    for precise scheduling in Indian Standard Time.

    Features:
        - Full daily schedule matching OPERATION_PLAN.md
        - Keep-alive ping for Render free tier (every 10 min)
        - DB maintenance (VACUUM, cleanup) at 3 AM
        - Error handling with logging
        - Job execution tracking
        - Graceful startup/shutdown
        - Schedule display for /health command
    """

    def __init__(self):
        self.config = get_config()
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False
        self._tracker = ExecutionTracker()
        self._job_count = 0

    async def start(self):
        """Start the scheduler with all scheduled jobs."""
        if not SCHEDULER_AVAILABLE:
            logger.error("Cannot start scheduler: APScheduler not available")
            return

        self._scheduler = AsyncIOScheduler(timezone='Asia/Kolkata')

        # Register event listeners
        self._scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)

        # Register all daily schedule entries
        for entry in DAILY_SCHEDULE:
            if not entry.enabled:
                continue

            trigger_kwargs = {
                'hour': entry.hour,
                'minute': entry.minute,
                'timezone': 'Asia/Kolkata',
            }

            if entry.day_of_week != "*":
                trigger_kwargs['day_of_week'] = entry.day_of_week

            handler = self._get_handler(entry.job_id)
            if handler:
                self._scheduler.add_job(
                    handler,
                    CronTrigger(**trigger_kwargs),
                    id=entry.job_id,
                    name=f"[{entry.agent}] {entry.description}",
                    misfire_grace_time=1800,  # 30 min grace
                )
                self._job_count += 1

        # ---- INFRASTRUCTURE JOBS ----

        # Keep-alive ping (every 10 min for Render)
        self._scheduler.add_job(
            self._keep_alive,
            IntervalTrigger(minutes=10),
            id='keep_alive',
            name='[SYS] Keep-Alive Ping',
            misfire_grace_time=600,  # 10 min grace — don't warn if slightly late
            coalesce=True,  # If multiple missed, only run once
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

        # Start scheduler
        self._scheduler.start()
        self._running = True

        logger.info(
            f"[SCHEDULER] Started with {self._job_count} jobs "
            f"({len(DAILY_SCHEDULE)} daily + 2 infrastructure)"
        )

    async def stop(self):
        """Stop the scheduler gracefully."""
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)  # Don't wait — SIGTERM has deadline
            except Exception as e:
                logger.warning(f"[SCHEDULER] Shutdown error (non-fatal): {e}")
            self._running = False
            logger.info("[SCHEDULER] Stopped")

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
            "🕐 <b>24-Hour Schedule (IST)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        for entry in DAILY_SCHEDULE:
            if not entry.enabled:
                continue
            time_str = f"{entry.hour:02d}:{entry.minute:02d}"
            day_str = f" ({entry.day_of_week})" if entry.day_of_week != "*" else ""
            status = "🟢" if self._running else "🔴"
            lines.append(
                f"{status} {time_str}{day_str} [{entry.agent}] {entry.description}"
            )
        return '\n'.join(lines)

    def get_execution_stats(self) -> Dict[str, Any]:
        return self._tracker.get_stats()

    # ================================================================
    # EVENT HANDLERS
    # ================================================================

    def _on_job_executed(self, event):
        logger.debug(f"[SCHEDULER] Job '{event.job_id}' executed successfully")

    def _on_job_error(self, event):
        logger.error(
            f"[SCHEDULER] Job '{event.job_id}' error: {event.exception}"
        )
        self._tracker.record(JobExecution(
            job_id=event.job_id,
            success=False,
            error=str(event.exception),
        ))

    def _on_job_missed(self, event):
        logger.warning(f"[SCHEDULER] Job '{event.job_id}' missed!")

    # ================================================================
    # HANDLER ROUTER
    # ================================================================

    def _get_handler(self, job_id: str) -> Optional[Callable]:
        """Map job_id to handler function."""
        handlers = {
            'morning_scrape': self._run_morning_scrape,
            'afternoon_scrape': self._run_afternoon_scrape,
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
            'ats_afternoon': self._run_ats_crawl,
            'ats_night': self._run_ats_crawl,
            'dark_channels': self._run_dark_channels,
            'weekly_retrain': self._run_weekly_retrain,
        }
        return handlers.get(job_id)

    # ================================================================
    # SAFE RUNNER
    # ================================================================

    async def _safe_run(self, name: str, func: Callable, *args, **kwargs):
        """
        Industrial-grade job runner with:
        - Per-job timeout (default 15 min)
        - Retry logic with exponential backoff (max 2 retries)
        - Execution tracking and heartbeat update
        - Structured error logging with traceback
        
        NOTE: Agents that self-manage heartbeats (A-03, A-04, A-05, A-06, A-07, A-08)
        should NOT have their heartbeats overwritten here. The scheduler only updates
        heartbeats for agents that don't self-manage (brief/summary jobs).
        """
        execution = JobExecution(job_id=name, start_time=time.time())
        job_timeout = kwargs.pop('job_timeout', 900)
        max_retries = kwargs.pop('max_retries', 2)
        retry_delay = 30  # seconds between retries

        # Agents that self-manage their own heartbeats
        # These agents call db.update_agent_heartbeat() internally
        self_managed_agents = {'A-01', 'A-02', 'A-03', 'A-04', 'A-05', 'A-06', 'A-07', 'A-08', 'A-11'}

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"[SCHEDULER] {name}: retry {attempt}/{max_retries}")
                else:
                    logger.info(f"[SCHEDULER] Running {name}...")

                # Determine if function is sync or async
                loop = asyncio.get_running_loop()
                import inspect
                if inspect.iscoroutinefunction(func):
                    # Async function — await it directly
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=job_timeout)
                else:
                    # Sync function — run in executor to avoid blocking event loop
                    # This is critical: long-running sync agents (A-01, A-03, A-04)
                    # can take 10-30 minutes. Running them in the main thread blocks
                    # APScheduler, keep-alive pings, and Telegram polling.
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                        timeout=job_timeout
                    )

                execution.success = True
                execution.end_time = time.time()

                # Extract items_processed from result if possible
                if isinstance(result, dict):
                    execution.items_processed = result.get('new', 0) or result.get('total', 0) or result.get('processed', 0)
                elif hasattr(result, 'total_processed'):
                    execution.items_processed = getattr(result, 'total_processed', 0)
                elif hasattr(result, 'new_clean_listings'):
                    execution.items_processed = getattr(result, 'new_clean_listings', 0)

                self._tracker.record(execution)

                # Only update heartbeat for agents that DON'T self-manage
                agent_id = name.split(' ')[0] if ' ' in name else name
                if agent_id not in self_managed_agents:
                    self._update_heartbeat(name, execution)

                logger.info(
                    f"[SCHEDULER] {name} completed in "
                    f"{execution.duration_sec}s"
                    f"{f' (attempt {attempt})' if attempt > 1 else ''}"
                )
                return result

            except asyncio.TimeoutError:
                last_error = f"Timed out after {job_timeout}s"
                logger.error(f"[SCHEDULER] {name} TIMED OUT after {job_timeout}s")
                break  # Don't retry timeouts

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(f"[SCHEDULER] {name} failed (attempt {attempt}): {last_error}")
                try:
                    tb = traceback.format_exc()
                    if tb and 'NoneType' not in tb:
                        logger.debug(f"[SCHEDULER] {name} traceback:\n{tb[-500:]}")
                except Exception:
                    pass

                if attempt < max_retries:
                    delay = retry_delay * attempt  # Linear backoff
                    logger.info(f"[SCHEDULER] {name}: waiting {delay}s before retry")
                    await asyncio.sleep(delay)

        # All retries exhausted
        execution.success = False
        execution.error = last_error
        execution.end_time = time.time()
        self._tracker.record(execution)

        # For failed agents, always update heartbeat to mark error
        self._update_heartbeat(name, execution)

        logger.error(
            f"[SCHEDULER] {name} FAILED after {max_retries} attempts: {last_error}"
        )

        # Send failure alert to Telegram
        await self._alert_job_failure(name, last_error)

        return None

    async def _alert_job_failure(self, job_name: str, error: str):
        """Send job failure alert to Telegram (best-effort)."""
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            reporter = get_telegram_reporter()
            if reporter._running:
                msg = (
                    f"⚠️ <b>Scheduled Job Failed</b>\n"
                    f"Job: {job_name}\n"
                    f"Error: {str(error)[:200]}\n\n"
                    f"The system will retry at next scheduled time."
                )
                await reporter.send_message(msg)
        except Exception:
            pass  # Best-effort alerting

    def _update_heartbeat(self, name: str, execution: JobExecution):
        """Update agent heartbeat in database (best-effort)."""
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

    # ================================================================
    # JOB IMPLEMENTATIONS
    # ================================================================

    async def _run_morning_scrape(self):
        from agents.a03_primary_scraper import get_primary_scraper
        await self._safe_run(
            'A-03 Morning Scrape',
            get_primary_scraper().run_morning_scrape
        )
        # AUTO-PROCESS: If morning scrape ran late and overlapped with
        # the scheduled dedup/ghost/enrich/PPO, this catches any
        # unprocessed listings.
        await self._auto_process_pipeline("after morning scrape")

    async def _run_afternoon_scrape(self):
        from agents.a03_primary_scraper import get_primary_scraper
        await self._safe_run(
            'A-03 Afternoon Scrape',
            get_primary_scraper().run_afternoon_scrape
        )
        # AUTO-PROCESS: Run pipeline after afternoon scrape so data
        # doesn't sit unprocessed until next morning
        await self._auto_process_pipeline("after afternoon scrape")

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

    async def _run_ats_crawl(self):
        from agents.a04_ats_crawler import get_ats_crawler
        await self._safe_run('A-04 ATS', get_ats_crawler().run_crawl)
        # AUTO-PROCESS: ATS crawl produces raw listings that need processing
        await self._auto_process_pipeline("after ATS crawl")

    async def _run_dark_channels(self):
        from agents.a02_dark_channel import get_dark_channel_listener
        await self._safe_run(
            'A-02 Dark',
            get_dark_channel_listener().run_batch_check
        )

    async def _run_weekly_retrain(self):
        from agents.a11_outcome_learner import get_outcome_learner
        await self._safe_run(
            'A-11 Retrain',
            get_outcome_learner().run_weekly_retrain
        )

    async def _auto_process_pipeline(self, trigger_reason: str = ""):
        """
        Auto-run dedup → ghost → enrich → PPO after any scrape/crawl job.
        This ensures raw listings are always processed into clean listings
        even if the next scheduled pipeline run is hours away.
        """
        logger.info(
            f"[SCHEDULER] Auto-processing pipeline ({trigger_reason})..."
        )

        # Check if there are unprocessed raw listings first
        try:
            from core.database import get_db
            db = get_db()
            unprocessed = db.count_unprocessed_raw_listings()
            if unprocessed == 0:
                logger.info(
                    "[SCHEDULER] Auto-process: 0 unprocessed raw listings, skipping"
                )
                return
            logger.info(
                f"[SCHEDULER] Auto-process: {unprocessed} unprocessed raw listings found"
            )
        except Exception as e:
            logger.warning(f"[SCHEDULER] Auto-process check failed: {e}")
            # Continue anyway — better to try than skip

        # Run each step directly via _safe_run (not via the wrapper methods
        # which would double-wrap). Each step gets its own error handling.
        try:
            from agents.a06_dedup_engine import get_dedup_engine
            await self._safe_run('A-06 Auto-Dedup', get_dedup_engine().run_dedup)
        except Exception as e:
            logger.error(f"[SCHEDULER] Auto-Dedup failed: {e}")

        try:
            from agents.a05_ghost_detector import get_ghost_detector
            await self._safe_run('A-05 Auto-Ghost', get_ghost_detector().score_batch)
        except Exception as e:
            logger.error(f"[SCHEDULER] Auto-Ghost failed: {e}")

        try:
            from agents.a07_intelligence_enricher import get_intelligence_enricher
            await self._safe_run('A-07 Auto-Enrich', get_intelligence_enricher().run_enrichment)
        except Exception as e:
            logger.error(f"[SCHEDULER] Auto-Enrich failed: {e}")

        try:
            from agents.a08_ppo_optimizer import get_ppo_optimizer
            await self._safe_run('A-08 Auto-PPO', get_ppo_optimizer().run_optimization)
        except Exception as e:
            logger.error(f"[SCHEDULER] Auto-PPO failed: {e}")

        logger.info(f"[SCHEDULER] Auto-processing pipeline complete")

    async def _keep_alive(self):
        """
        Layer 2 keep-alive: Scheduler pings the HTTP endpoint every 10 min.
        This is a backup to Layer 1 (self-ping loop).
        """
        logger.debug("[SCHEDULER] Keep-alive ping (Layer 2)")
        try:
            import aiohttp
            port = int(os.getenv('PORT', '10000'))
            external_url = os.getenv('RENDER_EXTERNAL_URL', '')

            # Prefer external URL (counts as real traffic for Render)
            url = (
                f"{external_url}/ping"
                if external_url
                else f"http://127.0.0.1:{port}/ping"
            )

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        logger.debug("[SCHEDULER] Keep-alive ping: OK")
                    else:
                        logger.warning(f"[SCHEDULER] Keep-alive ping: HTTP {resp.status}")
        except Exception as e:
            logger.debug(f"[SCHEDULER] Keep-alive ping error: {e}")

    async def _run_maintenance(self):
        logger.info("[SCHEDULER] Running DB maintenance...")
        try:
            from core.database import get_db
            db = get_db()
            db.cleanup_old_data(days=30)
            db.analyze()
            logger.info("[SCHEDULER] DB maintenance complete")
        except Exception as e:
            logger.error(f"[SCHEDULER] Maintenance error: {e}")


# ============================================================
# SINGLETON
# ============================================================

_scheduler_instance: Optional[AgentScheduler] = None


def get_scheduler() -> AgentScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AgentScheduler()
    return _scheduler_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Agent Scheduler — Self-Test")
    print("=" * 60)

    print(f"\n  APScheduler available: {'✅' if SCHEDULER_AVAILABLE else '❌'}")
    print(f"  Schedule entries: {len(DAILY_SCHEDULE)}")
    print(f"\n  Daily Schedule (IST):")

    for entry in DAILY_SCHEDULE:
        day = f" ({entry.day_of_week})" if entry.day_of_week != "*" else ""
        print(
            f"    {entry.hour:02d}:{entry.minute:02d}{day} "
            f"[{entry.agent}] {entry.description} "
            f"(~{entry.estimated_duration_min}min)"
        )

    print(f"\n  Infrastructure: keep-alive(10min) + maintenance(3AM)")
    print("=" * 60)
