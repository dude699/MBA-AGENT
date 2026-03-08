"""
============================================================
OPERATION FIRST MOVER v5 — MAIN ENTRY POINT
============================================================
Entry point for the zero-cost MBA Hunt Agent system.
Handles startup, initialization, signal handling,
and graceful shutdown.

Startup Sequence:
    1. Load configuration and validate environment
    2. Initialize database (create tables, migrate)
    3. Seed company database (1080+ companies)
    4. Initialize AI router (Groq + Cerebras)
    5. Initialize stealth engine (proxy pool)
    6. Seed agent heartbeats (A-01 to A-12)
    7. Start Telegram bot (22 commands)
    8. Start APScheduler (24-hour IST schedule)
    9. Enter main event loop
    10. Handle graceful shutdown (SIGTERM/SIGINT)

Deployment:
    - Render Free Tier: Worker service (python main.py)
    - Docker: python main.py
    - Local: python main.py

Memory Optimization (512MB Render limit):
    - Lazy-load heavy modules (sentence-transformers, sklearn)
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
    all components: database, AI router, scheduler, and
    Telegram bot.
    """

    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._scheduler = None
        self._telegram = None
        self._running = False

    async def start(self):
        """Execute full startup sequence."""
        print(BANNER)
        logger.info("=" * 60)
        logger.info("  OPERATION FIRST MOVER v5 — STARTING")
        logger.info("=" * 60)

        start_time = time.time()

        # Step 1: Configuration
        logger.info("[1/8] Loading configuration...")
        try:
            from core.config import get_config
            config = get_config()
            logger.info(f"  Environment: {os.getenv('RENDER_DEPLOY', 'local')}")
            logger.info(f"  Groq API: {'✅' if config.groq.api_key else '❌'}")
            logger.info(f"  Cerebras API: {'✅' if config.cerebras.api_key else '❌'}")
            logger.info(f"  Telegram Bot: {'✅' if config.telegram.bot_token else '❌'}")
        except Exception as e:
            logger.error(f"  Configuration error: {e}")
            logger.warning("  Continuing with defaults...")

        # Step 2: Database
        logger.info("[2/8] Initializing database...")
        try:
            from core.database import get_db
            db = get_db()
            logger.info(f"  Database: {db.db_path}")
            logger.info(f"  Tables: ready")
        except Exception as e:
            logger.error(f"  Database error: {e}")
            return

        # Step 3: Seed companies
        logger.info("[3/8] Seeding company database...")
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
        logger.info("[4/8] Initializing AI router...")
        try:
            from core.ai_router import get_router
            router = get_router()
            logger.info("  AI Router: ready (Groq + Cerebras)")
        except Exception as e:
            logger.warning(f"  AI Router error: {e}")

        # Step 5: Seed agent heartbeats
        logger.info("[5/8] Seeding agent heartbeats...")
        try:
            db.seed_agent_heartbeats()
            logger.info("  Heartbeats: A-01 to A-12 seeded")
        except Exception as e:
            logger.warning(f"  Heartbeat seed error: {e}")

        # Step 6: Stealth engine (lazy - don't initialize fully)
        logger.info("[6/8] Stealth engine: lazy-load mode")

        # Step 7: Telegram bot
        logger.info("[7/8] Starting Telegram bot...")
        try:
            from agents.a12_telegram_reporter import get_telegram_reporter
            self._telegram = get_telegram_reporter()
            await self._telegram.start_bot()
            logger.info("  Telegram bot: running")
        except Exception as e:
            logger.error(f"  Telegram bot error: {e}")
            logger.warning("  System will run without Telegram commands")

        # Step 8: Scheduler
        logger.info("[8/8] Starting scheduler...")
        try:
            from core.scheduler import get_scheduler
            self._scheduler = get_scheduler()
            await self._scheduler.start()
            logger.info("  Scheduler: running")
        except Exception as e:
            logger.error(f"  Scheduler error: {e}")
            logger.warning("  System will run without scheduled jobs")

        duration = time.time() - start_time
        self._running = True

        logger.info("=" * 60)
        logger.info(f"  STARTUP COMPLETE in {duration:.1f}s")
        logger.info(f"  Status: {'🟢 RUNNING' if self._running else '🔴 FAILED'}")
        logger.info("=" * 60)

        # Force garbage collection after startup
        gc.collect()

    async def run(self):
        """Main event loop — runs until shutdown signal."""
        logger.info("Entering main event loop...")
        logger.info("Send SIGTERM or SIGINT (Ctrl+C) to stop")

        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown sequence."""
        logger.info("=" * 60)
        logger.info("  SHUTTING DOWN...")
        logger.info("=" * 60)

        # Stop scheduler
        if self._scheduler:
            try:
                await self._scheduler.stop()
                logger.info("  Scheduler: stopped")
            except Exception as e:
                logger.error(f"  Scheduler stop error: {e}")

        # Stop Telegram bot
        if self._telegram:
            try:
                await self._telegram.stop_bot()
                logger.info("  Telegram bot: stopped")
            except Exception as e:
                logger.error(f"  Telegram stop error: {e}")

        # Database backup (for Render ephemeral disk)
        try:
            from core.database import get_db
            db = get_db()
            db.close()
            logger.info("  Database: closed")
        except Exception as e:
            logger.error(f"  Database close error: {e}")

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
    """Register OS signal handlers for graceful shutdown."""
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}")
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
        loop.run_until_complete(app.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
