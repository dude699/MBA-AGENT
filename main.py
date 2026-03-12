"""
============================================================
OPERATION FIRST MOVER v5.1 — MAIN ENTRY POINT (INDUSTRIAL GRADE)
============================================================
Zero-cost MBA Hunt Agent system orchestrator.

Architecture:
    - Phased startup with dependency ordering & circuit breakers
    - Structured health probing at every init stage
    - Graceful degradation: each subsystem can fail independently
    - Signal-safe shutdown with ordered teardown (Telegram FIRST)
    - Memory-aware GC on 512 MB Render constraint
    - Watchdog: monitors subsystem health
    - Startup diagnostic report to Telegram on success

Startup Phases (dependency-ordered):
    Phase 1 — FOUNDATION:  Config, Logging, Data dirs
    Phase 2 — STORAGE:     Database init, schema migration, WAL
    Phase 3 — DATA SEED:   Company DB (1081), agent heartbeats
    Phase 4 — AI LAYER:    AI Router (Groq + Cerebras dual-brain)
    Phase 5 — WEB LAYER:   aiohttp server, health endpoints (Render needs this ASAP)
    Phase 6 — COMMS:       Telegram bot (delayed on Render for overlap grace)
    Phase 7 — SCHEDULER:   APScheduler (24-hour IST cycle)
    Phase 8 — WATCHDOG:    Background monitor loop

Deployment:
    Render:  python main.py  ($PORT auto-set, usually 10000)
    Docker:  python main.py  (PORT=10000)
    Local:   python main.py  (PORT=10000)

Keep-Alive (5 layers):
    L1: Self-ping every 4 min  (asyncio internal)
    L2: Scheduler ping 10 min  (APScheduler)
    L3: cron-job.org 5 min     (external)
    L4: UptimeRobot 5 min      (external)
    L5: Telegram commands       (user activity = HTTP activity)
============================================================
"""

import os
import sys
import time
import signal
import asyncio
import gc
import warnings
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

# Suppress ResourceWarning about unclosed sockets during shutdown
warnings.filterwarnings('ignore', category=ResourceWarning)

# ============================================================
# LOGGING SETUP (before anything else)
# ============================================================

try:
    from loguru import logger

    logger.remove()
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=log_level,
        colorize=True,
    )
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger.add(
        "logs/firstmover_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
    )
    logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

VERSION = "5.1.0"
RENDER_OVERLAP_GRACE_SEC = int(os.getenv('RENDER_OVERLAP_GRACE_SEC', '15'))
WATCHDOG_INTERVAL_SEC = 120
STARTUP_TIMEOUT_SEC = 120
GC_INTERVAL_SEC = 300

BANNER = """
+============================================================+
|                                                              |
|   OPERATION FIRST MOVER v5.1 — Zero Cost MBA Agent          |
|                                                              |
|   12 AI Agents | 1081 Companies | 8+ Job Boards             |
|   Groq + Cerebras Dual-Brain | Telegram Command Center      |
|   Render Web Service + 5-Layer Keep-Alive                    |
|   Industrial-Grade Orchestration | Total Daily Cost: $0      |
|                                                              |
+============================================================+
"""


# ============================================================
# SUBSYSTEM STATUS TRACKER
# ============================================================

class SubsystemStatus:
    """Track health of each subsystem for diagnostics."""

    def __init__(self):
        self._status: Dict[str, Dict[str, Any]] = {}
        self._start_time = time.monotonic()

    def mark_ok(self, name: str, detail: str = ""):
        self._status[name] = {
            'state': 'OK',
            'detail': detail,
            'timestamp': time.monotonic() - self._start_time,
        }

    def mark_degraded(self, name: str, error: str):
        self._status[name] = {
            'state': 'DEGRADED',
            'detail': error,
            'timestamp': time.monotonic() - self._start_time,
        }

    def mark_failed(self, name: str, error: str):
        self._status[name] = {
            'state': 'FAILED',
            'detail': error,
            'timestamp': time.monotonic() - self._start_time,
        }

    @property
    def all_ok(self) -> bool:
        return all(s['state'] == 'OK' for s in self._status.values())

    @property
    def has_critical_failure(self) -> bool:
        web = self._status.get('web_server', {})
        return web.get('state') == 'FAILED'

    def to_report(self) -> str:
        lines = []
        for name, info in self._status.items():
            icon = {'OK': '+', 'DEGRADED': '~', 'FAILED': 'X'}.get(info['state'], '?')
            detail_str = f" -- {info['detail']}" if info['detail'] else ''
            lines.append(
                f"  [{icon}] {name}: {info['state']}{detail_str}"
                f" ({info['timestamp']:.1f}s)"
            )
        return '\n'.join(lines)

    def to_telegram_msg(self) -> str:
        lines = []
        for name, info in self._status.items():
            icon = {'OK': '✅', 'DEGRADED': '⚠️', 'FAILED': '❌'}.get(info['state'], '❓')
            lines.append(f"{icon} <b>{name}</b>: {info['state']}")
            if info['detail']:
                lines.append(f"   <i>{info['detail'][:80]}</i>")
        return '\n'.join(lines)


# ============================================================
# APPLICATION CLASS
# ============================================================

class Application:
    """
    Main application orchestrator with phased startup, ordered shutdown,
    watchdog monitoring, and graceful degradation.
    """

    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._scheduler = None
        self._telegram = None
        self._keepalive = None
        self._db = None
        self._running = False
        self._startup_complete = False  # SIGTERM deferred until startup done
        self._watchdog_task: Optional[asyncio.Task] = None
        self._gc_task: Optional[asyncio.Task] = None
        self._status = SubsystemStatus()
        self._start_time = time.monotonic()
        self._is_render = bool(
            os.getenv('RENDER', '') or os.getenv('RENDER_DEPLOY', '')
        )

    # ================================================================
    # PHASE 1: FOUNDATION
    # ================================================================

    def _init_foundation(self):
        os.makedirs("data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

        try:
            from core.config import get_config
            config = get_config()
            checks = config.validate_critical()
            missing = [k for k, v in checks.items() if not v]

            detail = (
                f"env={'Render' if self._is_render else 'Local'}, "
                f"port={os.getenv('PORT', '10000')}"
            )
            if missing:
                detail += f", MISSING: {', '.join(missing)}"
                self._status.mark_degraded('config', detail)
                logger.warning(f"[Phase 1] Config degraded: {detail}")
            else:
                self._status.mark_ok('config', detail)
                logger.info(f"[Phase 1] Config loaded: {detail}")
            return config
        except Exception as e:
            self._status.mark_degraded('config', str(e))
            logger.error(f"[Phase 1] Config error: {e}")
            return None

    # ================================================================
    # PHASE 2: STORAGE
    # ================================================================

    def _init_storage(self):
        try:
            from core.database import get_db
            db = get_db()
            self._db = db
            self._status.mark_ok('database', f"path={db.db_path}")
            logger.info(f"[Phase 2] Database ready: {db.db_path}")
            return db
        except Exception as e:
            self._status.mark_failed('database', str(e))
            logger.error(f"[Phase 2] Database FAILED: {e}")
            return None

    # ================================================================
    # PHASE 3: DATA SEED
    # ================================================================

    def _init_data_seed(self, db):
        if not db:
            self._status.mark_degraded('seed', 'skipped (no db)')
            return

        try:
            from core.company_db_seed import seed_companies, TOTAL_COMPANIES
            count = seed_companies()
            if count > 0:
                detail = f"seeded {count}/{TOTAL_COMPANIES} companies"
            else:
                existing = db.count_companies()
                detail = f"already seeded ({existing} companies)"

            db.seed_agent_heartbeats()
            detail += ", heartbeats A-01..A-12"

            self._status.mark_ok('seed', detail)
            logger.info(f"[Phase 3] {detail}")
        except Exception as e:
            self._status.mark_degraded('seed', str(e))
            logger.error(f"[Phase 3] Seed error: {e}")

    # ================================================================
    # PHASE 4: AI LAYER
    # ================================================================

    def _init_ai_layer(self):
        try:
            from core.ai_router import get_router
            router = get_router()
            self._status.mark_ok('ai_router', 'Groq + Cerebras dual-brain')
            logger.info("[Phase 4] AI Router ready (Groq + Cerebras)")
            return router
        except Exception as e:
            self._status.mark_degraded('ai_router', str(e))
            logger.warning(f"[Phase 4] AI Router degraded: {e}")
            return None

    # ================================================================
    # PHASE 5: WEB LAYER (CRITICAL for Render)
    # ================================================================

    async def _init_web_layer(self):
        try:
            from core.keepalive import get_keepalive_manager, get_health_tracker
            self._keepalive = get_keepalive_manager()
            await self._keepalive.start()

            health_tracker = get_health_tracker()
            health_tracker.set_db_status(self._db is not None)

            port = os.getenv('PORT', '10000')
            detail = (
                f"port={port}, endpoints=/ /health /status /ping, "
                f"self-ping=240s"
            )
            self._status.mark_ok('web_server', detail)
            logger.info(f"[Phase 5] Web server LIVE on port {port}")
        except Exception as e:
            self._status.mark_failed('web_server', str(e))
            logger.error(f"[Phase 5] Web server FAILED: {e}")
            logger.error("[Phase 5] CRITICAL: Render health checks will fail!")

    # ================================================================
    # PHASE 6: COMMS (Telegram)
    # ================================================================

    async def _init_telegram(self):
        if self._is_render:
            logger.info(
                f"[Phase 6] Render detected -- {RENDER_OVERLAP_GRACE_SEC}s "
                f"grace for old instance to release polling lock..."
            )
            await asyncio.sleep(RENDER_OVERLAP_GRACE_SEC)
            logger.info("[Phase 6] Grace period complete.")

        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            self._telegram = get_telegram_reporter()
            await self._telegram.start_bot()

            if self._telegram._running:
                self._status.mark_ok('telegram', 'polling active, 29 commands')
                logger.info("[Phase 6] Telegram bot running (polling mode)")
                try:
                    from core.keepalive import get_health_tracker
                    get_health_tracker().set_telegram_status(True)
                except Exception:
                    pass
            else:
                self._status.mark_degraded(
                    'telegram', 'started but polling not confirmed'
                )
                logger.warning("[Phase 6] Telegram started but polling unclear")

        except Exception as e:
            self._status.mark_degraded('telegram', str(e))
            logger.error(f"[Phase 6] Telegram error: {e}")
            logger.warning("[Phase 6] System continues without Telegram commands")

    # ================================================================
    # PHASE 7: SCHEDULER
    # ================================================================

    async def _init_scheduler(self):
        try:
            from core.scheduler import get_scheduler
            self._scheduler = get_scheduler()
            await self._scheduler.start()

            self._status.mark_ok('scheduler', 'running with 18 jobs')
            logger.info("[Phase 7] Scheduler running")

            try:
                from core.keepalive import get_health_tracker
                get_health_tracker().set_scheduler_status(True)
            except Exception:
                pass

        except Exception as e:
            self._status.mark_degraded('scheduler', str(e))
            logger.error(f"[Phase 7] Scheduler error: {e}")
            logger.warning("[Phase 7] System continues without scheduled jobs")

    # ================================================================
    # PHASE 8: WATCHDOG + MEMORY MANAGER
    # ================================================================

    async def _watchdog_loop(self):
        check_count = 0
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(WATCHDOG_INTERVAL_SEC)
                if self._shutdown_event.is_set():
                    break

                check_count += 1

                # Check Telegram health
                if (self._telegram and hasattr(self._telegram, '_running')
                        and not self._telegram._running):
                    logger.warning("[WATCHDOG] Telegram polling stopped — may need restart")

                # Check scheduler health
                if self._scheduler:
                    try:
                        from core.scheduler import get_scheduler
                        sched = get_scheduler()
                        if hasattr(sched, '_scheduler') and sched._scheduler and not sched._scheduler.running:
                            logger.warning("[WATCHDOG] Scheduler stopped -- attempting restart")
                            await sched.start()
                    except Exception as e:
                        logger.error(f"[WATCHDOG] Scheduler check failed: {e}")

                # Every 10 checks (~20 min), log database health summary
                if check_count % 10 == 0 and self._db:
                    try:
                        from core.database import get_db
                        db = get_db()
                        raw_count = db.count_raw_listings()
                        unprocessed = db.count_unprocessed_raw_listings()
                        with db.get_cursor() as cur:
                            cur.execute("SELECT COUNT(*) FROM clean_listings WHERE status = 'active'")
                            clean_count = cur.fetchone()[0]
                        logger.info(
                            f"[WATCHDOG] DB health: raw={raw_count}, "
                            f"unprocessed={unprocessed}, clean_active={clean_count}"
                        )
                        # Alert if there are many unprocessed listings
                        if unprocessed > 100:
                            logger.warning(
                                f"[WATCHDOG] {unprocessed} unprocessed raw listings! "
                                f"Pipeline may be stalled."
                            )
                    except Exception as e:
                        logger.debug(f"[WATCHDOG] DB health check error: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WATCHDOG] Error: {e}")

    async def _gc_loop(self):
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(GC_INTERVAL_SEC)
                if self._shutdown_event.is_set():
                    break
                collected = gc.collect()
                if collected > 100:
                    logger.debug(f"[GC] Collected {collected} objects")
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    # ================================================================
    # MASTER STARTUP
    # ================================================================

    async def start(self):
        print(BANNER)
        logger.info("=" * 60)
        logger.info(f"  OPERATION FIRST MOVER v{VERSION} -- STARTING")
        logger.info(f"  Mode: {'Render' if self._is_render else 'Local'} Web Service")
        logger.info(f"  PID: {os.getpid()}")
        logger.info("=" * 60)

        start_time = time.monotonic()

        logger.info("[Phase 1/8] Loading configuration...")
        config = self._init_foundation()

        logger.info("[Phase 2/8] Initializing database...")
        db = self._init_storage()

        logger.info("[Phase 3/8] Seeding data...")
        self._init_data_seed(db)

        logger.info("[Phase 4/8] Initializing AI router...")
        self._init_ai_layer()

        logger.info("[Phase 5/8] Starting web server + keep-alive...")
        await self._init_web_layer()

        logger.info("[Phase 6/8] Starting Telegram bot...")
        await self._init_telegram()

        logger.info("[Phase 7/8] Starting scheduler...")
        await self._init_scheduler()

        logger.info("[Phase 8/8] Starting watchdog + memory manager...")
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        self._gc_task = asyncio.create_task(self._gc_loop())
        self._status.mark_ok('watchdog', f'interval={WATCHDOG_INTERVAL_SEC}s')

        gc.collect()

        duration = time.monotonic() - start_time
        self._running = True

        render_url = os.getenv('RENDER_EXTERNAL_URL', '')
        port = os.getenv('PORT', '10000')

        logger.info("=" * 60)
        logger.info(f"  STARTUP COMPLETE in {duration:.1f}s")
        logger.info(f"  Status: {'ALL OK' if self._status.all_ok else 'DEGRADED'}")
        logger.info(f"  Web: http://0.0.0.0:{port}")
        if render_url:
            logger.info(f"  Render URL: {render_url}")
            logger.info(f"  Health: {render_url}/health")
        logger.info(f"  Keep-Alive: 5 layers active")
        logger.info(f"  Version: {VERSION}")
        logger.info("=" * 60)
        logger.info("Subsystem Report:")
        logger.info(self._status.to_report())
        logger.info("=" * 60)

        # Mark startup as complete so SIGTERM handler can work
        self._startup_complete = True

        # Send startup report to Telegram
        await self._send_startup_report(duration)

    async def _send_startup_report(self, duration: float):
        if not self._telegram or not self._telegram._running:
            return

        try:
            render_url = os.getenv('RENDER_EXTERNAL_URL', 'N/A')
            msg = (
                f"🚀 <b>SYSTEM STARTUP COMPLETE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⏱ Duration: <b>{duration:.1f}s</b>\n"
                f"🔗 {render_url}\n"
                f"📦 Version: {VERSION}\n\n"
                f"<b>Subsystem Status:</b>\n"
                f"{self._status.to_telegram_msg()}\n\n"
                f"{'✅ All systems operational' if self._status.all_ok else '⚠️ Some subsystems degraded'}\n"
                f"💡 /health for live status | /quota for API usage"
            )
            await self._telegram.send_message(msg)
        except Exception as e:
            logger.debug(f"Startup report send failed (non-critical): {e}")

    # ================================================================
    # MAIN EVENT LOOP
    # ================================================================

    async def run(self):
        logger.info("Entering main event loop...")
        logger.info("Service is LIVE. Send SIGTERM or Ctrl+C to stop.")

        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    # ================================================================
    # GRACEFUL SHUTDOWN (ordered teardown)
    # ================================================================

    async def shutdown(self):
        """
        Graceful shutdown with strict ordering:
        1. Watchdog + GC -> stop monitoring
        2. Telegram FIRST -> release polling lock
        3. Scheduler -> stop firing jobs
        4. Keep-alive -> stop pinging
        5. Database -> close connections
        6. AI Router -> close HTTP clients
        """
        if not self._running:
            return
        self._running = False

        logger.info("=" * 60)
        logger.info("  GRACEFUL SHUTDOWN INITIATED")
        logger.info("=" * 60)

        shutdown_start = time.monotonic()

        try:
            from core.keepalive import get_health_tracker
            get_health_tracker().set_shutdown_requested()
            get_health_tracker().set_telegram_status(False)
        except Exception:
            pass

        # Stop background tasks
        for task_name, task in [('watchdog', self._watchdog_task), ('gc', self._gc_task)]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        logger.info("  [0/5] Background tasks stopped")

        # TELEGRAM FIRST
        if self._telegram:
            try:
                await asyncio.wait_for(self._telegram.stop_bot(), timeout=20.0)
                logger.info("  [1/5] Telegram: STOPPED (polling lock released)")
            except asyncio.TimeoutError:
                logger.warning("  [1/5] Telegram: stop timed out (20s)")
            except Exception as e:
                logger.error(f"  [1/5] Telegram: {e}")
        else:
            logger.info("  [1/5] Telegram: not running")

        # Scheduler
        if self._scheduler:
            try:
                await asyncio.wait_for(self._scheduler.stop(), timeout=10.0)
                logger.info("  [2/5] Scheduler: STOPPED")
            except asyncio.TimeoutError:
                logger.warning("  [2/5] Scheduler: stop timed out (10s)")
            except Exception as e:
                logger.error(f"  [2/5] Scheduler: {e}")
        else:
            logger.info("  [2/5] Scheduler: not running")

        # Keep-alive
        if self._keepalive:
            try:
                await asyncio.wait_for(self._keepalive.stop(), timeout=5.0)
                logger.info("  [3/5] Keep-alive: STOPPED")
            except asyncio.TimeoutError:
                logger.warning("  [3/5] Keep-alive: stop timed out (5s)")
            except Exception as e:
                logger.error(f"  [3/5] Keep-alive: {e}")
        else:
            logger.info("  [3/5] Keep-alive: not running")

        # Database
        try:
            from core.database import get_db
            db = get_db()
            db.close()
            logger.info("  [4/5] Database: CLOSED")
        except Exception as e:
            logger.error(f"  [4/5] Database: {e}")

        # AI Router
        try:
            from core.ai_router import get_router
            router = get_router()
            if hasattr(router, '_groq_client') and router._groq_client:
                router._groq_client.close()
            if hasattr(router, '_cerebras_client') and router._cerebras_client:
                router._cerebras_client.close()
            logger.info("  [5/5] AI Router: clients closed")
        except Exception:
            logger.info("  [5/5] AI Router: cleanup skipped")

        shutdown_duration = time.monotonic() - shutdown_start
        logger.info("=" * 60)
        logger.info(f"  SHUTDOWN COMPLETE in {shutdown_duration:.1f}s")
        logger.info("=" * 60)

    def request_shutdown(self):
        logger.info("Shutdown requested...")
        self._shutdown_event.set()


# ============================================================
# SIGNAL HANDLERS
# ============================================================

def setup_signal_handlers(app: Application, loop: asyncio.AbstractEventLoop):
    """Register OS signal handlers for graceful shutdown."""
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} -- GRACEFUL SHUTDOWN INITIATED")

        # If startup is not complete, defer the shutdown
        if not app._startup_complete:
            logger.warning(
                f"[{sig_name}] Received during startup — deferring shutdown. "
                f"Will shut down after startup completes."
            )
            # Set a flag and return — the main run loop will check
            app._shutdown_event.set()
            return

        if app._telegram:
            async def _emergency_stop():
                try:
                    if app._telegram._app:
                        tg_app = app._telegram._app
                        if tg_app.updater and tg_app.updater.running:
                            logger.info("[SIGTERM] Force-stopping Telegram updater...")
                            await asyncio.wait_for(
                                tg_app.updater.stop(), timeout=5.0
                            )
                            logger.info("[SIGTERM] Telegram updater STOPPED")

                    try:
                        import aiohttp
                        token = app._telegram.config.telegram.bot_token
                        if token:
                            base = f"https://api.telegram.org/bot{token}"
                            timeout = aiohttp.ClientTimeout(total=5)
                            async with aiohttp.ClientSession(timeout=timeout) as session:
                                async with session.post(f"{base}/close") as resp:
                                    result = await resp.json()
                                    logger.info(
                                        f"[SIGTERM] /close API: {result.get('ok', False)}"
                                    )
                    except Exception as close_err:
                        logger.warning(f"[SIGTERM] /close failed: {close_err}")

                except asyncio.TimeoutError:
                    logger.warning("[SIGTERM] Updater stop timed out (5s)")
                except Exception as e:
                    logger.error(f"[SIGTERM] Emergency stop error: {e}")
                finally:
                    try:
                        from core.keepalive import get_health_tracker
                        get_health_tracker().set_telegram_status(False)
                    except Exception:
                        pass

                    logger.info("[SIGTERM] Waiting 8s for running jobs to finish...")
                    await asyncio.sleep(8)
                    app.request_shutdown()

            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(_emergency_stop())
            )
        else:
            loop.call_soon_threadsafe(app.request_shutdown)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    app = Application()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    setup_signal_handlers(app, loop)

    try:
        loop.run_until_complete(app.start())
        loop.run_until_complete(app.run())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        loop.run_until_complete(app.shutdown())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        loop.run_until_complete(app.shutdown())
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        loop.close()


if __name__ == "__main__":
    main()
