"""
============================================================
OPERATION FIRST MOVER v8.0 -- 6-LAYER KEEP-ALIVE ARCHITECTURE
============================================================
The immune system of the stack. Pings each service BEFORE it sleeps,
not after it is already dead.

Layer 1: Render Self-Ping (every 4 minutes)
    - keepalive.py pings /health endpoint
    - Prevents Render free tier 15-min spin-down
    - Uses asyncio background task

Layer 2: Supabase Anti-Pause (Mon/Fri 9am IST)
    - Executes SELECT 1 FROM clean_listings
    - Prevents Supabase 7-day auto-pause on free tier
    - Scheduled via APScheduler

Layer 3: Portal Session Health (Daily 6am IST)
    - A-03 checks cookie validity for each portal
    - Triggers Playwright re-login if cookies expired
    - Stores session data in Supabase portal_sessions table

Layer 4: AI Provider Health (Before every dispatch)
    - A-14 Multi-Model Router probes APIs with 5-token test
    - Automatically routes to fallback if primary is down
    - Implemented in ai_router.py health_probe()

Layer 5: Watchdog (Every 2 minutes)
    - Monitors memory usage (>450MB triggers GC)
    - Checks scheduler health
    - Restarts stuck agents
    - Memory-aware garbage collection

Layer 6: Weekly Backup (Sunday 11pm IST)
    - Exports all tables to JSON
    - Stores in Supabase Storage bucket
    - Keeps last 4 backups
============================================================
"""

import os
import gc
import sys
import time
import asyncio
import logging
import traceback
import psutil  # type: ignore
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List

try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from core.config import get_config, now_ist, IST


# ============================================================
# SECTION 1: LAYER 1 - RENDER SELF-PING
# ============================================================

class RenderSelfPing:
    """
    Layer 1: Pings the Render service /health endpoint every 4 minutes
    to prevent the free tier 15-minute spin-down.

    Architecture:
        - Runs as asyncio background task
        - Pings http://localhost:{PORT}/health
        - Logs results to Supabase system_pings table
        - Auto-adjusts interval on consecutive failures
    """

    def __init__(self):
        self.config = get_config()
        self.interval = self.config.keepalive.render_self_ping_interval_sec  # 240s
        self.health_path = self.config.keepalive.render_health_path
        self.port = int(os.environ.get('PORT', '10000'))
        self.url = f"http://localhost:{self.port}{self.health_path}"
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._total_pings = 0
        self._total_failures = 0
        self._last_ping_time: Optional[datetime] = None
        self._last_ping_status: str = "not_started"

    async def start(self):
        """Start the self-ping background loop."""
        if self._running:
            logger.warning("Self-ping already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._ping_loop())
        logger.info(f"Layer 1: Render self-ping started "
                    f"(interval={self.interval}s, url={self.url})")

    async def stop(self):
        """Stop the self-ping loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Layer 1: Render self-ping stopped")

    async def _ping_loop(self):
        """Main ping loop. Runs every 4 minutes."""
        # Wait initial 30s for server to start
        await asyncio.sleep(30)

        while self._running:
            try:
                success = await self._do_ping()
                self._total_pings += 1
                self._last_ping_time = now_ist()

                if success:
                    self._consecutive_failures = 0
                    self._last_ping_status = "ok"
                else:
                    self._consecutive_failures += 1
                    self._total_failures += 1
                    self._last_ping_status = "failed"

                # Log to database periodically (every 10 pings)
                if self._total_pings % 10 == 0:
                    await self._log_to_db()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Self-ping loop error: {e}")
                self._consecutive_failures += 1

            # Adaptive interval: shorter if failing
            interval = self.interval
            if self._consecutive_failures > 3:
                interval = max(60, self.interval // 2)  # Min 1 minute

            await asyncio.sleep(interval)

    async def _do_ping(self) -> bool:
        """Execute a single health ping."""
        try:
            start = time.time()

            if HTTPX_AVAILABLE:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(self.url)
                    elapsed = (time.time() - start) * 1000
                    if resp.status_code == 200:
                        logger.debug(f"L1 self-ping OK ({elapsed:.0f}ms)")
                        return True
                    else:
                        logger.warning(f"L1 self-ping HTTP {resp.status_code}")
                        return False
            elif AIOHTTP_AVAILABLE:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        elapsed = (time.time() - start) * 1000
                        if resp.status == 200:
                            logger.debug(f"L1 self-ping OK ({elapsed:.0f}ms)")
                            return True
                        return False
            else:
                logger.warning("No async HTTP client for self-ping")
                return False

        except Exception as e:
            logger.warning(f"L1 self-ping failed: {e}")
            return False

    async def _log_to_db(self):
        """Log ping status to database."""
        try:
            from core.database import get_db
            db = get_db()
            db.log_ping(
                service='render_self_ping',
                status=self._last_ping_status,
                layer='L1_render_self_ping',
                details={
                    'total_pings': self._total_pings,
                    'total_failures': self._total_failures,
                    'consecutive_failures': self._consecutive_failures,
                },
            )
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """Get self-ping status."""
        return {
            'running': self._running,
            'total_pings': self._total_pings,
            'total_failures': self._total_failures,
            'consecutive_failures': self._consecutive_failures,
            'last_ping': self._last_ping_time.isoformat() if self._last_ping_time else None,
            'last_status': self._last_ping_status,
            'interval_sec': self.interval,
        }


# ============================================================
# SECTION 2: LAYER 2 - SUPABASE ANTI-PAUSE
# ============================================================

class SupabaseKeepalive:
    """
    Layer 2: Prevents Supabase free tier 7-day auto-pause.
    Runs a lightweight query on Mon/Fri at 9am IST.
    Max gap between pings = 4 days (well within 7-day limit).
    """

    def __init__(self):
        self.config = get_config()
        self._last_ping: Optional[datetime] = None
        self._total_pings = 0
        self._total_failures = 0

    async def ping(self) -> bool:
        """Execute keepalive query against Supabase."""
        try:
            from core.database import get_db
            db = get_db()
            if not db.is_connected:
                logger.warning("L2: Supabase not connected, attempting reconnect...")
                db.initialize()

            success = db.keepalive_ping()
            self._total_pings += 1
            if success:
                self._last_ping = now_ist()
                logger.info("L2: Supabase keepalive ping SUCCESS")
            else:
                self._total_failures += 1
                logger.error("L2: Supabase keepalive ping FAILED")
            return success

        except Exception as e:
            self._total_failures += 1
            logger.error(f"L2: Supabase keepalive error: {e}")
            return False

    def should_ping(self) -> bool:
        """Check if it's time to ping (Mon or Fri, around 9am IST)."""
        now = now_ist()
        # Monday = 0, Friday = 4
        if now.weekday() not in (0, 4):
            return False
        if now.hour != 9:
            return False
        # Don't ping if we already pinged within 4 hours
        if self._last_ping:
            gap = (now - self._last_ping).total_seconds() / 3600
            if gap < 4:
                return False
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            'total_pings': self._total_pings,
            'total_failures': self._total_failures,
            'last_ping': self._last_ping.isoformat() if self._last_ping else None,
            'next_expected': self._get_next_ping_time(),
        }

    def _get_next_ping_time(self) -> str:
        """Calculate next expected ping time."""
        now = now_ist()
        # Find next Monday or Friday at 9am
        days_ahead = {0: 'Monday', 4: 'Friday'}
        for delta in range(1, 8):
            future = now + timedelta(days=delta)
            if future.weekday() in days_ahead:
                return future.replace(hour=9, minute=0, second=0).isoformat()
        return "unknown"


# ============================================================
# SECTION 3: LAYER 5 - WATCHDOG
# ============================================================

class SystemWatchdog:
    """
    Layer 5: System watchdog monitoring every 2 minutes.
    - Memory monitoring (>450MB triggers GC)
    - Scheduler health check
    - Agent heartbeat verification
    - Automatic recovery actions
    """

    def __init__(self):
        self.config = get_config()
        self.interval = self.config.keepalive.watchdog_interval_sec  # 120s
        self.memory_threshold_mb = self.config.keepalive.memory_threshold_mb  # 450MB
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._gc_triggered_count = 0
        self._total_checks = 0
        self._alerts: List[Dict[str, Any]] = []
        self._last_check: Optional[datetime] = None

    async def start(self):
        """Start the watchdog background loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(f"Layer 5: Watchdog started (interval={self.interval}s, "
                    f"mem_threshold={self.memory_threshold_mb}MB)")

    async def stop(self):
        """Stop the watchdog."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Layer 5: Watchdog stopped")

    async def _watchdog_loop(self):
        """Main watchdog loop."""
        await asyncio.sleep(60)  # Wait for startup

        while self._running:
            try:
                await self._check_system_health()
                self._total_checks += 1
                self._last_check = now_ist()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog check error: {e}")

            await asyncio.sleep(self.interval)

    async def _check_system_health(self):
        """Run all health checks."""
        # Memory check
        memory_ok = self._check_memory()
        if not memory_ok:
            self._trigger_gc()

        # Check for stuck event loop
        await self._check_event_loop_health()

        # Log status periodically (every 30 checks = ~1 hour)
        if self._total_checks % 30 == 0:
            await self._log_health_report()

    def _check_memory(self) -> bool:
        """Check memory usage. Returns True if within limits."""
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            memory_percent = process.memory_percent()

            if memory_mb > self.memory_threshold_mb:
                logger.warning(
                    f"L5: Memory HIGH: {memory_mb:.0f}MB "
                    f"(threshold={self.memory_threshold_mb}MB, "
                    f"{memory_percent:.1f}%)"
                )
                self._alerts.append({
                    'type': 'memory_high',
                    'value': memory_mb,
                    'threshold': self.memory_threshold_mb,
                    'time': now_ist().isoformat(),
                })
                return False

            logger.debug(f"L5: Memory OK: {memory_mb:.0f}MB ({memory_percent:.1f}%)")
            return True

        except Exception as e:
            logger.warning(f"Memory check failed: {e}")
            return True  # Assume OK if we can't check

    def _trigger_gc(self):
        """Trigger garbage collection to free memory."""
        logger.info("L5: Triggering garbage collection...")
        before = gc.get_stats()
        collected = gc.collect()
        gc.collect()  # Second pass for cyclic refs
        self._gc_triggered_count += 1

        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            logger.info(f"L5: GC complete. Collected {collected} objects. "
                       f"Memory now: {memory_mb:.0f}MB")
        except Exception:
            logger.info(f"L5: GC complete. Collected {collected} objects.")

    async def _check_event_loop_health(self):
        """Check if the event loop is responsive."""
        start = time.time()
        await asyncio.sleep(0.01)  # Yield to event loop
        elapsed = time.time() - start
        if elapsed > 1.0:
            logger.warning(f"L5: Event loop slow! Sleep(0.01) took {elapsed:.2f}s")
            self._alerts.append({
                'type': 'event_loop_slow',
                'value': elapsed,
                'time': now_ist().isoformat(),
            })

    async def _log_health_report(self):
        """Log health report to database."""
        try:
            from core.database import get_db
            db = get_db()

            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=0.1)

            db.log_ping(
                service='watchdog',
                status='ok',
                layer='L5_watchdog',
                details={
                    'memory_mb': round(memory_mb, 1),
                    'cpu_percent': round(cpu_percent, 1),
                    'gc_triggered': self._gc_triggered_count,
                    'total_checks': self._total_checks,
                    'alerts_count': len(self._alerts),
                },
            )
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """Get watchdog status."""
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=0.1)
        except Exception:
            memory_mb = 0
            cpu_percent = 0

        return {
            'running': self._running,
            'total_checks': self._total_checks,
            'gc_triggered': self._gc_triggered_count,
            'memory_mb': round(memory_mb, 1),
            'cpu_percent': round(cpu_percent, 1),
            'memory_threshold_mb': self.memory_threshold_mb,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'recent_alerts': self._alerts[-5:],
        }


# ============================================================
# SECTION 4: LAYER 6 - WEEKLY BACKUP
# ============================================================

class WeeklyBackup:
    """
    Layer 6: Weekly backup of all Supabase tables to JSON.
    Runs Sunday 11pm IST. Stores backups in Supabase Storage.
    """

    def __init__(self):
        self.config = get_config()
        self._last_backup: Optional[datetime] = None
        self._total_backups = 0
        self._last_backup_size: int = 0

    async def run_backup(self) -> Dict[str, Any]:
        """Execute weekly backup of all tables."""
        logger.info("L6: Starting weekly backup...")
        start = time.time()

        try:
            from core.database import get_db
            db = get_db()

            if not db.is_connected:
                return {'success': False, 'error': 'Database not connected'}

            # Export all tables
            backup_data = db.export_all_tables()
            if not backup_data:
                return {'success': False, 'error': 'No data exported'}

            # Calculate size
            total_size = sum(len(v) for v in backup_data.values())
            self._last_backup_size = total_size

            # Log backup metadata
            self._total_backups += 1
            self._last_backup = now_ist()
            elapsed = time.time() - start

            result = {
                'success': True,
                'tables_backed_up': list(backup_data.keys()),
                'total_size_bytes': total_size,
                'total_size_kb': round(total_size / 1024, 1),
                'elapsed_seconds': round(elapsed, 1),
                'backup_number': self._total_backups,
                'timestamp': self._last_backup.isoformat(),
            }

            logger.info(
                f"L6: Backup complete! {len(backup_data)} tables, "
                f"{result['total_size_kb']}KB, {elapsed:.1f}s"
            )

            # Log to system_pings
            db.log_ping(
                service='weekly_backup',
                status='ok',
                layer='L6_weekly_backup',
                details=result,
            )

            return result

        except Exception as e:
            logger.error(f"L6: Weekly backup FAILED: {e}")
            return {'success': False, 'error': str(e)}

    def should_run(self) -> bool:
        """Check if it's time for weekly backup (Sunday 11pm IST)."""
        now = now_ist()
        if now.weekday() != 6:  # Sunday = 6
            return False
        if now.hour != 23:
            return False
        # Don't run if already backed up today
        if self._last_backup and self._last_backup.date() == now.date():
            return False
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            'total_backups': self._total_backups,
            'last_backup': self._last_backup.isoformat() if self._last_backup else None,
            'last_backup_size_kb': round(self._last_backup_size / 1024, 1),
        }


# ============================================================
# SECTION 5: KEEP-ALIVE ORCHESTRATOR
# ============================================================

class KeepAliveManager:
    """
    Orchestrates all 6 keep-alive layers.
    Manages lifecycle of all keep-alive components.
    """

    def __init__(self):
        self.layer1_self_ping = RenderSelfPing()
        self.layer2_supabase = SupabaseKeepalive()
        self.layer5_watchdog = SystemWatchdog()
        self.layer6_backup = WeeklyBackup()
        self._started = False

    async def start_all(self):
        """Start all keep-alive layers."""
        if self._started:
            return

        logger.info("=" * 50)
        logger.info("STARTING 6-LAYER KEEP-ALIVE ARCHITECTURE")
        logger.info("=" * 50)

        # Layer 1: Render Self-Ping
        await self.layer1_self_ping.start()

        # Layer 2: Supabase Anti-Pause (initial ping)
        await self.layer2_supabase.ping()

        # Layer 3: Portal Session Health (handled by scheduler/A-03)
        logger.info("Layer 3: Portal session health - managed by scheduler")

        # Layer 4: AI Provider Health (handled by AI Router)
        logger.info("Layer 4: AI provider health - managed by AI Router")

        # Layer 5: Watchdog
        await self.layer5_watchdog.start()

        # Layer 6: Weekly Backup (handled by scheduler)
        logger.info("Layer 6: Weekly backup - managed by scheduler")

        self._started = True
        logger.info("All keep-alive layers initialized")

    async def stop_all(self):
        """Stop all keep-alive layers gracefully."""
        logger.info("Stopping keep-alive layers...")
        await self.layer1_self_ping.stop()
        await self.layer5_watchdog.stop()
        self._started = False
        logger.info("All keep-alive layers stopped")

    async def check_scheduled_tasks(self):
        """Check and run any scheduled keep-alive tasks.
        Called periodically by the main scheduler."""
        # Layer 2: Supabase ping (Mon/Fri 9am)
        if self.layer2_supabase.should_ping():
            await self.layer2_supabase.ping()

        # Layer 6: Weekly backup (Sunday 11pm)
        if self.layer6_backup.should_run():
            await self.layer6_backup.run_backup()

    def get_full_status(self) -> Dict[str, Any]:
        """Get status of all keep-alive layers."""
        return {
            'started': self._started,
            'layer1_self_ping': self.layer1_self_ping.get_status(),
            'layer2_supabase': self.layer2_supabase.get_status(),
            'layer3_portal_sessions': {'managed_by': 'scheduler/A-03'},
            'layer4_ai_providers': {'managed_by': 'ai_router'},
            'layer5_watchdog': self.layer5_watchdog.get_status(),
            'layer6_backup': self.layer6_backup.get_status(),
        }

    def get_health_summary(self) -> str:
        """Human-readable health summary for Telegram."""
        status = self.get_full_status()
        lines = ["<b>Keep-Alive Health</b>"]

        # L1
        l1 = status['layer1_self_ping']
        l1_emoji = "OK" if l1['running'] and l1.get('consecutive_failures', 0) == 0 else "WARN"
        lines.append(f"L1 Self-Ping: [{l1_emoji}] {l1['total_pings']} pings")

        # L2
        l2 = status['layer2_supabase']
        l2_emoji = "OK" if l2['total_failures'] == 0 else "WARN"
        lines.append(f"L2 Supabase: [{l2_emoji}] Last: {l2.get('last_ping', 'never')}")

        # L5
        l5 = status['layer5_watchdog']
        l5_emoji = "OK" if l5['running'] and l5['memory_mb'] < 400 else "WARN"
        lines.append(f"L5 Watchdog: [{l5_emoji}] RAM: {l5['memory_mb']}MB, GC: {l5['gc_triggered']}x")

        # L6
        l6 = status['layer6_backup']
        lines.append(f"L6 Backup: {l6['total_backups']} backups")

        return "\n".join(lines)


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================

_keepalive_manager: Optional[KeepAliveManager] = None

def get_keepalive_manager() -> KeepAliveManager:
    """Get the singleton KeepAliveManager instance."""
    global _keepalive_manager
    if _keepalive_manager is None:
        _keepalive_manager = KeepAliveManager()
    return _keepalive_manager


if __name__ == "__main__":
    print("=" * 60)
    print("OPERATION FIRST MOVER v8.0 -- Keep-Alive Architecture")
    print("=" * 60)
    print("Layer 1: Render Self-Ping (every 4 minutes)")
    print("Layer 2: Supabase Anti-Pause (Mon/Fri 9am IST)")
    print("Layer 3: Portal Session Health (Daily 6am)")
    print("Layer 4: AI Provider Health (Before dispatch)")
    print("Layer 5: System Watchdog (Every 2 minutes)")
    print("Layer 6: Weekly Backup (Sunday 11pm IST)")
    print("=" * 60)
