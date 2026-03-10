"""
============================================================
OPERATION FIRST MOVER v5 — MAIN ENTRY POINT
============================================================
Entry point for the zero-cost MBA Hunt Agent system.
Runs as a Render FREE-TIER WEB SERVICE with an embedded
aiohttp HTTP server for keep-alive + health checks.

Startup Sequence:
    1.  Load configuration and validate environment
    2.  Initialize database (create tables, migrate)
    3.  Seed company database (1080+ companies)
    4.  Initialize AI router (Groq + Cerebras)
    5.  Seed agent heartbeats (A-01 to A-12)
    6.  Stealth engine: lazy-load mode
    7.  Start aiohttp Web Server (port from $PORT env)
    8.  Start Self-Ping keep-alive loop (Layer 1)
    9.  Start Telegram bot (22 commands, polling mode)
    10. Start APScheduler (24-hour IST schedule)
    11. Enter main event loop
    12. Handle graceful shutdown (SIGTERM/SIGINT)

Deployment:
    - Render Free Tier: Web Service (python main.py)
      Render sets $PORT automatically (usually 10000)
      Health check: GET /health
    - Docker: python main.py (PORT=10000)
    - Local: python main.py (PORT=10000)

Keep-Alive Architecture (5 layers):
    Layer 1: Internal self-ping every 4 min (asyncio)
    Layer 2: Scheduler keep-alive every 10 min (APScheduler)
    Layer 3: cron-job.org external ping every 5 min (free)
    Layer 4: UptimeRobot monitoring every 5 min (free)
    Layer 5: Your Telegram commands (each = HTTP activity)

Memory Optimization (512MB Render limit):
    - Lazy-load heavy modules
    - Batch processing with bounded queues
    - Periodic garbage collection
    - SQLite WAL mode for concurrent access
============================================================
"""

import os
import sys
import time
import signal
import asyncio
import gc
from datetime import datetime
from pathlib import Path

# ============================================================
# RENDER DEPLOYMENT OVERLAP PROTECTION
# ============================================================
# Render starts the NEW instance FIRST, waits for health check,
# THEN sends SIGTERM to the OLD instance. This means both run
# simultaneously for ~30-60 seconds. Telegram polling allows
# only ONE consumer — the overlap causes Conflict errors.
#
# FIX: The NEW instance delays starting Telegram polling by
# RENDER_OVERLAP_GRACE_SEC seconds, giving the OLD instance
# time to receive SIGTERM and release the polling lock.
# The web server starts IMMEDIATELY (Render needs /health).
# ============================================================
# Grace period is now SHORTER because the real fix is in the
# pre-flight /close API call (in a12_telegram_reporter.py).
# The /close call server-side releases the polling lock, so we
# don't need to blindly wait 45s and hope for the best.
# 15s is enough for Render to send SIGTERM to the old instance.
RENDER_OVERLAP_GRACE_SEC = int(os.getenv('RENDER_OVERLAP_GRACE_SEC', '15'))

try:
    from loguru import logger

    # Configure loguru
    logger.remove()  # Remove default handler
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
    # File logger
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
# BANNER
# ============================================================

BANNER = """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ⚡ OPERATION FIRST MOVER v5 — Zero Cost MBA Agent     ║
║                                                          ║
║   12 AI Agents | 1080+ Companies | 8+ Job Boards        ║
║   Groq + Cerebras | Telegram Command Center             ║
║   Render Web Service + 5-Layer Keep-Alive               ║
║   Total Daily Cost: ₹0.00                               ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""


# ============================================================
# STARTUP SEQUENCE
# ============================================================

class Application:
    """
    Main application class that manages the lifecycle of
    all components: web server, keep-alive, database, AI router,
    scheduler, and Telegram bot.
    """

    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._scheduler = None
        self._telegram = None
        self._keepalive = None
        self._running = False

    async def start(self):
        """Execute full startup sequence."""
        print(BANNER)
        logger.info("=" * 60)
        logger.info("  OPERATION FIRST MOVER v5 — STARTING")
        logger.info("  Mode: Render Web Service + Keep-Alive")
        logger.info("=" * 60)

        start_time = time.time()

        # Step 1: Configuration
        logger.info("[1/10] Loading configuration...")
        try:
            from core.config import get_config
            config = get_config()
            logger.info(f"  Environment: {'Render' if config.is_render else 'Local'}")
            logger.info(f"  Port: {os.getenv('PORT', '10000')}")
            logger.info(f"  Groq API: {'SET' if config.groq.api_key else 'MISSING'}")
            logger.info(f"  Cerebras API: {'SET' if config.cerebras.api_key else 'MISSING'}")
            logger.info(f"  Telegram Bot: {'SET' if config.telegram.bot_token else 'MISSING'}")
            logger.info(f"  SerpAPI: {'SET' if config.serpapi.api_key else 'MISSING'}")
        except Exception as e:
            logger.error(f"  Configuration error: {e}")
            logger.warning("  Continuing with defaults...")

        # Step 2: Database
        logger.info("[2/10] Initializing database...")
        try:
            from core.database import get_db
            db = get_db()
            logger.info(f"  Database: {db.db_path}")
            logger.info(f"  Tables: ready")
        except Exception as e:
            logger.error(f"  Database error: {e}")
            # Don't return — web server must start for Render health check
            db = None

        # Step 3: Seed companies
        logger.info("[3/10] Seeding company database...")
        if db:
            try:
                from core.company_db_seed import seed_companies, TOTAL_COMPANIES
                count = seed_companies()
                if count > 0:
                    logger.info(f"  Seeded: {count}/{TOTAL_COMPANIES} companies")
                else:
                    existing = db.count_companies()
                    logger.info(f"  Already seeded: {existing} companies")
            except Exception as e:
                logger.error(f"  Company seed error: {e}")

        # Step 4: AI Router
        logger.info("[4/10] Initializing AI router...")
        try:
            from core.ai_router import get_router
            router = get_router()
            logger.info("  AI Router: ready (Groq + Cerebras)")
        except Exception as e:
            logger.warning(f"  AI Router error: {e}")

        # Step 5: Seed agent heartbeats
        logger.info("[5/10] Seeding agent heartbeats...")
        if db:
            try:
                db.seed_agent_heartbeats()
                logger.info("  Heartbeats: A-01 to A-12 seeded")
            except Exception as e:
                logger.warning(f"  Heartbeat seed error: {e}")

        # Step 6: Stealth engine (lazy - don't initialize fully)
        logger.info("[6/10] Stealth engine: lazy-load mode")

        # Step 7: Start Web Server + Keep-Alive (CRITICAL for Render)
        logger.info("[7/10] Starting web server + keep-alive...")
        try:
            from core.keepalive import get_keepalive_manager, get_health_tracker
            self._keepalive = get_keepalive_manager()
            await self._keepalive.start()

            health_tracker = get_health_tracker()
            health_tracker.set_db_status(db is not None)
            logger.info(f"  Web server: port {self._keepalive.web_server.port}")
            logger.info(f"  Self-ping: every 240s")
            logger.info(f"  Endpoints: / /health /status /ping")
        except Exception as e:
            logger.error(f"  Web server error: {e}")
            logger.error("  CRITICAL: Service may not stay alive on Render!")

        # Step 8: Telegram bot
        # On Render, we MUST delay polling to let the OLD instance die first.
        # Render sends SIGTERM to old instance only AFTER new instance is healthy.
        # The old instance gets a 30s grace period to shut down.
        # We wait RENDER_OVERLAP_GRACE_SEC to guarantee no overlap.
        logger.info("[8/10] Starting Telegram bot...")
        is_render = os.getenv('RENDER', '') or os.getenv('RENDER_DEPLOY', '')
        if is_render:
            logger.info(
                f"  Render detected — waiting {RENDER_OVERLAP_GRACE_SEC}s "
                f"for old instance to release polling lock..."
            )
            logger.info(
                f"  (Web server is already live on port "
                f"{os.getenv('PORT', '10000')} — health checks pass)"
            )
            await asyncio.sleep(RENDER_OVERLAP_GRACE_SEC)
            logger.info("  Grace period complete. Starting Telegram bot now.")

        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            self._telegram = get_telegram_reporter()
            await self._telegram.start_bot()
            self._running = True
            logger.info("  Telegram bot: running (polling mode)")

            if self._keepalive:
                get_health_tracker().set_telegram_status(True)
        except Exception as e:
            logger.error(f"  Telegram bot error: {e}")
            logger.warning("  System will run without Telegram commands")

        # Step 9: Scheduler
        logger.info("[9/10] Starting scheduler...")
        try:
            from core.scheduler import get_scheduler
            self._scheduler = get_scheduler()
            await self._scheduler.start()
            logger.info("  Scheduler: running")

            if self._keepalive:
                get_health_tracker().set_scheduler_status(True)
        except Exception as e:
            logger.error(f"  Scheduler error: {e}")
            logger.warning("  System will run without scheduled jobs")

        # Step 10: Final status
        duration = time.time() - start_time
        self._running = True

        # Force garbage collection after startup
        gc.collect()

        render_url = os.getenv('RENDER_EXTERNAL_URL', 'not set')
        port = os.getenv('PORT', '10000')

        logger.info("=" * 60)
        logger.info(f"  [10/10] STARTUP COMPLETE in {duration:.1f}s")
        logger.info(f"  Status: {'RUNNING' if self._running else 'FAILED'}")
        logger.info(f"  Web: http://0.0.0.0:{port}")
        if render_url != 'not set':
            logger.info(f"  Render URL: {render_url}")
            logger.info(f"  Health: {render_url}/health")
        logger.info(f"  Keep-Alive: 5 layers active")
        logger.info("=" * 60)

    async def run(self):
        """Main event loop — runs until shutdown signal."""
        logger.info("Entering main event loop...")
        logger.info("Service is LIVE. Send SIGTERM or Ctrl+C to stop.")

        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        """
        Graceful shutdown sequence.

        ORDER IS CRITICAL:
        1. Telegram FIRST — releases the getUpdates polling lock
           so the NEXT instance can start cleanly.
        2. Scheduler second — stops firing new jobs.
        3. Keep-alive last — stop pinging (let Render know we're done).
        4. Database close.

        Each step has a timeout to prevent hanging on Render's
        SIGTERM deadline (usually 30s grace period).
        """
        if not self._running:
            return  # Already shut down or never started

        logger.info("="  * 60)
        logger.info("  SHUTTING DOWN (graceful)...")
        logger.info("=" * 60)

        # Mark shutdown in health tracker so new instance can detect it
        try:
            from core.keepalive import get_health_tracker
            get_health_tracker().set_shutdown_requested()
            get_health_tracker().set_telegram_status(False)
        except Exception:
            pass

        # ---- STEP 1: TELEGRAM FIRST (release polling lock + /close) ----
        if self._telegram:
            try:
                await asyncio.wait_for(
                    self._telegram.stop_bot(), timeout=20.0
                )
                logger.info(
                    "  [1/4] Telegram bot: STOPPED "
                    "(polling lock + server session released)"
                )
            except asyncio.TimeoutError:
                logger.warning("  [1/4] Telegram bot: stop timed out (20s)")
            except Exception as e:
                logger.error(f"  [1/4] Telegram stop error: {e}")

        # ---- STEP 2: SCHEDULER ----
        if self._scheduler:
            try:
                await asyncio.wait_for(
                    self._scheduler.stop(), timeout=10.0
                )
                logger.info("  [2/4] Scheduler: STOPPED")
            except asyncio.TimeoutError:
                logger.warning("  [2/4] Scheduler: stop timed out (10s)")
            except Exception as e:
                logger.error(f"  [2/4] Scheduler stop error: {e}")

        # ---- STEP 3: KEEP-ALIVE ----
        if self._keepalive:
            try:
                await asyncio.wait_for(
                    self._keepalive.stop(), timeout=5.0
                )
                logger.info("  [3/4] Keep-alive: STOPPED")
            except asyncio.TimeoutError:
                logger.warning("  [3/4] Keep-alive: stop timed out (5s)")
            except Exception as e:
                logger.error(f"  [3/4] Keep-alive stop error: {e}")

        # ---- STEP 4: DATABASE ----
        try:
            from core.database import get_db
            db = get_db()
            db.close()
            logger.info("  [4/4] Database: CLOSED")
        except Exception as e:
            logger.error(f"  [4/4] Database close error: {e}")

        self._running = False
        logger.info("  Shutdown complete. Goodbye!")

    def request_shutdown(self):
        """Request graceful shutdown (called by signal handlers)."""
        logger.info("Shutdown requested...")
        self._shutdown_event.set()


# ============================================================
# SIGNAL HANDLERS
# ============================================================

def setup_signal_handlers(app: Application, loop: asyncio.AbstractEventLoop):
    """Register OS signal handlers for graceful shutdown.

    CRITICAL FOR RENDER DEPLOYMENTS:
    When Render deploys a new version, it sends SIGTERM to the old instance.
    We MUST stop the Telegram polling IMMEDIATELY so the new instance
    can start polling without hitting Conflict errors.

    PRIORITY: Kill Telegram polling FIRST, in the signal handler itself,
    before even entering the async shutdown sequence. This is the fastest
    possible way to release the getUpdates lock.
    """
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} — GRACEFUL SHUTDOWN INITIATED")

        # PRIORITY: Stop Telegram polling AND call /close API to release
        # the server-side session. This is THE critical step for Render
        # redeployments — the new instance needs the polling lock ASAP.
        # But we do NOT kill running scrape jobs — we let them finish
        # their current batch commit before the full shutdown.
        if app._telegram:
            async def _emergency_stop_telegram():
                """Emergency: release polling lock + /close API on SIGTERM."""
                try:
                    # Step 1: Stop the updater (releases local polling)
                    if app._telegram._app:
                        tg_app = app._telegram._app
                        if tg_app.updater and tg_app.updater.running:
                            logger.info(
                                "[SIGTERM] Force-stopping Telegram updater..."
                            )
                            await asyncio.wait_for(
                                tg_app.updater.stop(), timeout=5.0
                            )
                            logger.info("[SIGTERM] Telegram updater STOPPED")

                    # Step 2: Call /close API to release server-side session
                    try:
                        import aiohttp
                        token = app._telegram.config.telegram.bot_token
                        if token:
                            base = f"https://api.telegram.org/bot{token}"
                            timeout = aiohttp.ClientTimeout(total=5)
                            async with aiohttp.ClientSession(
                                timeout=timeout
                            ) as session:
                                async with session.post(
                                    f"{base}/close"
                                ) as resp:
                                    result = await resp.json()
                                    logger.info(
                                        f"[SIGTERM] /close API: "
                                        f"{result.get('ok', False)}"
                                    )
                    except Exception as close_err:
                        logger.warning(
                            f"[SIGTERM] /close API failed: {close_err}"
                        )

                except asyncio.TimeoutError:
                    logger.warning("[SIGTERM] Updater stop timed out (5s)")
                except Exception as e:
                    logger.error(f"[SIGTERM] Emergency stop error: {e}")
                finally:
                    # Update health tracker
                    try:
                        from core.keepalive import get_health_tracker
                        get_health_tracker().set_telegram_status(False)
                    except Exception:
                        pass

                    # Step 3: Give running scrape/crawl jobs 10s to finish
                    # their current batch commit before full shutdown.
                    # Render gives 30s total grace period — Telegram takes ~5s,
                    # so we have ~15s for scrapes to commit partial results.
                    logger.info(
                        "[SIGTERM] Waiting 8s for running jobs to finish "
                        "current batch commit..."
                    )
                    await asyncio.sleep(8)

                    # Now trigger the full graceful shutdown
                    app.request_shutdown()

            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(_emergency_stop_telegram())
            )
        else:
            loop.call_soon_threadsafe(app.request_shutdown)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    """Application entry point."""
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # Create application
    app = Application()

    # Create event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Setup signal handlers
    setup_signal_handlers(app, loop)

    try:
        # Start the application
        loop.run_until_complete(app.start())

        # Run main loop until shutdown
        loop.run_until_complete(app.run())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        loop.run_until_complete(app.shutdown())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        loop.run_until_complete(app.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
