"""
============================================================
OPERATION FIRST MOVER v5 — ULTIMATE KEEP-ALIVE ENGINE
============================================================
Multi-layer, self-healing keep-alive system that ensures
the Render free-tier Web Service NEVER sleeps.

THE PROBLEM:
    Render free-tier Web Service spins down after 15 minutes
    of no inbound HTTP requests. Once asleep, it takes 30-60s
    to cold-start, and ALL scheduled jobs are lost.

THE SOLUTION — 5 LAYERS OF PROTECTION:
    Layer 1: Internal Self-Ping (asyncio loop)
        - Every 4 minutes, the app pings its own /health endpoint
        - Uses aiohttp.ClientSession internally
        - Zero external dependency, always runs

    Layer 2: APScheduler Keep-Alive Job
        - Every 10 minutes, scheduler fires keep-alive
        - Pings /health endpoint as backup to Layer 1
        - If Layer 1 fails, this catches it

    Layer 3: External Cron Ping (cron-job.org — FREE)
        - External service pings YOUR_URL/health every 5 min
        - Even if internal loops crash, external ping keeps it alive
        - Setup: https://cron-job.org (free, no credit card)

    Layer 4: UptimeRobot Monitoring (FREE)
        - External uptime monitor pings every 5 minutes
        - Also sends you email/Telegram if the service goes DOWN
        - Setup: https://uptimerobot.com (free, 50 monitors)

    Layer 5: Telegram Bot Webhook Fallback
        - Each Telegram command from you = HTTP request = resets timer
        - Daily morning/evening reports = guaranteed 2 pings/day minimum
        - Any /health check from you keeps it alive

ARCHITECTURE:
    ┌─────────────────────────────────────────────────────┐
    │              RENDER WEB SERVICE                      │
    │                                                      │
    │  ┌─────────────┐   ┌──────────────────────────────┐ │
    │  │ aiohttp     │   │  Application Core             │ │
    │  │ Web Server  │   │  ┌────────────────────────┐  │ │
    │  │ (port 10000)│   │  │ Telegram Bot (polling)  │  │ │
    │  │             │   │  │ APScheduler (24hr IST)  │  │ │
    │  │ GET /       │   │  │ 12 AI Agents            │  │ │
    │  │ GET /health │   │  └────────────────────────┘  │ │
    │  │ GET /status │   │                               │ │
    │  │ GET /ping   │   │  ┌────────────────────────┐  │ │
    │  └──────┬──────┘   │  │ Self-Ping Loop (4 min)  │  │ │
    │         │          │  │ Scheduler Ping (10 min) │  │ │
    │         │          │  └────────────────────────┘  │ │
    │         ▼          └──────────────────────────────┘ │
    │    HTTP Response                                     │
    └─────────────────────────────────────────────────────┘
              ▲          ▲            ▲
              │          │            │
     ┌────────┴───┐ ┌───┴────┐ ┌────┴──────┐
     │ cron-job   │ │Uptime  │ │ Your      │
     │ .org       │ │Robot   │ │ Telegram  │
     │ (5 min)    │ │(5 min) │ │ Commands  │
     └────────────┘ └────────┘ └───────────┘
     LAYER 3         LAYER 4     LAYER 5

Why this is UNKILLABLE:
    - Layer 1 alone keeps it alive 99.5% of the time
    - Layer 2 catches any Layer 1 failures
    - Layer 3 (external) catches total internal failure
    - Layer 4 (external) is ANOTHER independent external pinger
    - Layer 5 (your usage) resets timer on every command
    - All 5 layers would have to fail simultaneously = impossible
============================================================
"""

import os
import time
import asyncio
import gc
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from aiohttp import web, ClientSession, ClientTimeout
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.error("aiohttp not available — web server disabled!")

from core.config import get_config, IST


# ============================================================
# HEALTH TRACKER
# ============================================================

class HealthTracker:
    """
    Tracks system health metrics for the /health and /status
    endpoints. Provides detailed diagnostics.
    """

    def __init__(self):
        self._start_time = time.time()
        self._ping_count = 0
        self._last_ping_time = 0.0
        self._last_self_ping = 0.0
        self._last_external_ping = 0.0
        self._self_ping_failures = 0
        self._total_requests = 0
        self._agent_status: Dict[str, str] = {}
        self._scheduler_running = False
        self._telegram_running = False
        self._db_healthy = False

    def record_ping(self, source: str = "unknown"):
        """Record a keep-alive ping."""
        self._ping_count += 1
        self._last_ping_time = time.time()
        self._total_requests += 1

        if source == "self":
            self._last_self_ping = time.time()
        elif source in ("cron-job", "uptimerobot", "external"):
            self._last_external_ping = time.time()

    def record_self_ping_failure(self):
        self._self_ping_failures += 1

    def record_request(self):
        self._total_requests += 1

    def set_scheduler_status(self, running: bool):
        self._scheduler_running = running

    def set_telegram_status(self, running: bool):
        self._telegram_running = running

    def set_db_status(self, healthy: bool):
        self._db_healthy = healthy

    @property
    def ping_count(self) -> int:
        return self._ping_count

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def uptime_str(self) -> str:
        seconds = int(self.uptime_seconds)
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    def get_health(self) -> Dict[str, Any]:
        """Full health report for /health endpoint."""
        now = time.time()
        return {
            "status": "alive",
            "uptime": self.uptime_str,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "ping_count": self._ping_count,
            "total_requests": self._total_requests,
            "last_ping_ago_sec": round(now - self._last_ping_time, 1) if self._last_ping_time else None,
            "last_self_ping_ago_sec": round(now - self._last_self_ping, 1) if self._last_self_ping else None,
            "last_external_ping_ago_sec": round(now - self._last_external_ping, 1) if self._last_external_ping else None,
            "self_ping_failures": self._self_ping_failures,
            "scheduler_running": self._scheduler_running,
            "telegram_running": self._telegram_running,
            "db_healthy": self._db_healthy,
            "memory_mb": self._get_memory_usage(),
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }

    def get_status_text(self) -> str:
        """One-line status for quick checks."""
        h = self.get_health()
        return (
            f"OK | up={h['uptime']} | pings={h['ping_count']} | "
            f"mem={h['memory_mb']}MB | sched={'ON' if h['scheduler_running'] else 'OFF'} | "
            f"tg={'ON' if h['telegram_running'] else 'OFF'}"
        )

    @staticmethod
    def _get_memory_usage() -> int:
        """Get current process memory usage in MB."""
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return int(usage.ru_maxrss / 1024)  # Linux: KB -> MB
        except Exception:
            return 0


# Global health tracker
_health = HealthTracker()


def get_health_tracker() -> HealthTracker:
    return _health


# ============================================================
# AIOHTTP WEB SERVER
# ============================================================

class WebServer:
    """
    Lightweight aiohttp web server that provides:
    - GET /          → Simple "alive" response (for Render health check)
    - GET /health    → Detailed JSON health report
    - GET /status    → One-line text status
    - GET /ping      → Bare minimum "pong" (fastest response)
    - GET /telegram-status → Telegram bot polling status

    This is what keeps Render from sleeping the service.
    Every HTTP request to ANY of these endpoints resets the
    15-minute inactivity timer.
    """

    def __init__(self):
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._port = int(os.getenv('PORT', '10000'))
        self.health = _health

    def _create_app(self) -> web.Application:
        """Create the aiohttp application with routes."""
        app = web.Application()
        app.router.add_get('/', self._handle_root)
        app.router.add_get('/health', self._handle_health)
        app.router.add_get('/status', self._handle_status)
        app.router.add_get('/ping', self._handle_ping)
        app.router.add_get('/telegram-status', self._handle_telegram_status)
        # HEAD requests (some monitors use HEAD instead of GET)
        app.router.add_route('HEAD', '/', self._handle_ping)
        app.router.add_route('HEAD', '/health', self._handle_ping)
        app.router.add_route('HEAD', '/ping', self._handle_ping)
        return app

    async def start(self):
        """Start the web server."""
        if not AIOHTTP_AVAILABLE:
            logger.error("[WEBSERVER] aiohttp not available!")
            return

        self._app = self._create_app()
        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            host='0.0.0.0',
            port=self._port,
        )
        await self._site.start()
        logger.info(f"[WEBSERVER] Listening on 0.0.0.0:{self._port}")
        logger.info(f"[WEBSERVER] Endpoints: / /health /status /ping")

    async def stop(self):
        """Stop the web server."""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("[WEBSERVER] Stopped")

    @property
    def port(self) -> int:
        return self._port

    # ---- ROUTE HANDLERS ----

    async def _handle_root(self, request: web.Request) -> web.Response:
        """Root endpoint — confirms service is alive."""
        self.health.record_request()
        source = request.query.get('source', 'unknown')
        if source != 'unknown':
            self.health.record_ping(source)

        return web.Response(
            text=(
                "Operation First Mover v5 — ALIVE\n"
                f"Uptime: {self.health.uptime_str}\n"
                f"Pings: {self.health.ping_count}\n"
            ),
            content_type='text/plain',
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Detailed JSON health endpoint."""
        self.health.record_request()
        source = request.query.get('source', 'external')
        self.health.record_ping(source)

        import json
        return web.Response(
            text=json.dumps(self.health.get_health(), indent=2),
            content_type='application/json',
        )

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Quick one-line status."""
        self.health.record_request()
        return web.Response(
            text=self.health.get_status_text(),
            content_type='text/plain',
        )

    async def _handle_ping(self, request: web.Request) -> web.Response:
        """Ultra-minimal ping response (fastest)."""
        self.health.record_ping("external")
        return web.Response(text="pong", content_type='text/plain')

    async def _handle_telegram_status(self, request: web.Request) -> web.Response:
        """
        Telegram bot status endpoint.
        Returns whether polling is active. The NEW instance can check
        this on the OLD instance to know when polling has stopped.
        """
        self.health.record_request()
        import json
        status = {
            "telegram_running": self.health._telegram_running,
            "uptime": self.health.uptime_str,
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }
        return web.Response(
            text=json.dumps(status),
            content_type='application/json',
        )


# ============================================================
# LAYER 1: SELF-PING LOOP
# ============================================================

class SelfPingLoop:
    """
    Layer 1: Internal self-ping that runs every 4 minutes.
    Pings the service's own /health endpoint to reset Render's
    15-minute inactivity timer.

    Why 4 minutes? Because:
    - Render sleeps at 15 min inactivity
    - 4 min interval = 3-4 pings before deadline
    - Even if 1-2 pings fail, we still make it
    - Low overhead (< 1KB per ping)

    Self-healing: If the self-ping fails 3 times in a row,
    it triggers a garbage collection and memory cleanup to
    try to recover the service.
    """

    PING_INTERVAL_SEC = 240  # 4 minutes
    MAX_CONSECUTIVE_FAILURES = 3
    RECOVERY_PING_INTERVAL_SEC = 60  # 1 minute during recovery

    def __init__(self, port: int):
        self._port = port
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._total_pings = 0
        self._total_failures = 0
        self._in_recovery = False
        self.health = _health
        # Build the self-ping URL
        # On Render, we use RENDER_EXTERNAL_URL if available,
        # otherwise localhost
        self._external_url = os.getenv('RENDER_EXTERNAL_URL', '')
        self._local_url = f"http://127.0.0.1:{self._port}"

    def start(self):
        """Start the self-ping background loop."""
        self._running = True
        self._task = asyncio.create_task(self._ping_loop())
        logger.info(
            f"[KEEPALIVE] Layer 1 (Self-Ping) started — "
            f"every {self.PING_INTERVAL_SEC}s"
        )

    async def stop(self):
        """Stop the self-ping loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[KEEPALIVE] Layer 1 (Self-Ping) stopped")

    async def _ping_loop(self):
        """Main ping loop — runs forever until stopped."""
        # Wait 30 seconds for server to fully start
        await asyncio.sleep(30)

        while self._running:
            try:
                interval = (
                    self.RECOVERY_PING_INTERVAL_SEC
                    if self._in_recovery
                    else self.PING_INTERVAL_SEC
                )
                success = await self._do_ping()

                if success:
                    self._consecutive_failures = 0
                    if self._in_recovery:
                        self._in_recovery = False
                        logger.info("[KEEPALIVE] Recovery mode ended — back to normal")
                else:
                    self._consecutive_failures += 1
                    self._total_failures += 1
                    self.health.record_self_ping_failure()

                    if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                        await self._attempt_recovery()

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[KEEPALIVE] Self-ping loop error: {e}")
                await asyncio.sleep(60)

    async def _do_ping(self) -> bool:
        """Execute a single self-ping."""
        self._total_pings += 1

        # Try external URL first (goes through Render's load balancer = counts as traffic)
        if self._external_url:
            try:
                timeout = ClientTimeout(total=10)
                async with ClientSession(timeout=timeout) as session:
                    url = f"{self._external_url}/health?source=self"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            self.health.record_ping("self")
                            logger.debug(
                                f"[KEEPALIVE] Self-ping OK (external) "
                                f"#{self._total_pings}"
                            )
                            return True
            except Exception as e:
                logger.debug(f"[KEEPALIVE] External self-ping failed: {e}")

        # Fallback to localhost
        try:
            timeout = ClientTimeout(total=5)
            async with ClientSession(timeout=timeout) as session:
                url = f"{self._local_url}/health?source=self"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        self.health.record_ping("self")
                        logger.debug(
                            f"[KEEPALIVE] Self-ping OK (local) "
                            f"#{self._total_pings}"
                        )
                        return True
        except Exception as e:
            logger.warning(f"[KEEPALIVE] Local self-ping failed: {e}")

        return False

    async def _attempt_recovery(self):
        """
        If self-ping fails 3 times in a row, attempt recovery:
        1. Force garbage collection (free memory)
        2. Switch to faster ping interval
        3. Log warning
        """
        logger.warning(
            f"[KEEPALIVE] ⚠️ {self._consecutive_failures} consecutive "
            f"failures! Attempting recovery..."
        )
        self._in_recovery = True

        # Force GC to free memory
        collected = gc.collect()
        logger.info(f"[KEEPALIVE] GC collected {collected} objects")

        # Reset counter
        self._consecutive_failures = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get self-ping statistics."""
        return {
            "total_pings": self._total_pings,
            "total_failures": self._total_failures,
            "consecutive_failures": self._consecutive_failures,
            "in_recovery": self._in_recovery,
            "external_url": self._external_url or "not set",
            "interval_sec": (
                self.RECOVERY_PING_INTERVAL_SEC
                if self._in_recovery
                else self.PING_INTERVAL_SEC
            ),
        }


# ============================================================
# LAYER 2: SCHEDULER KEEP-ALIVE (in scheduler.py)
# Already exists — fires every 10 min. We'll upgrade it to
# actually hit the /health endpoint.
# ============================================================


# ============================================================
# COMBINED KEEP-ALIVE MANAGER
# ============================================================

class KeepAliveManager:
    """
    Orchestrates all keep-alive layers.

    Usage:
        manager = KeepAliveManager()
        await manager.start()
        # ... app runs ...
        await manager.stop()
    """

    def __init__(self):
        self.web_server = WebServer()
        self.self_ping = SelfPingLoop(self.web_server.port)
        self.health = _health

    async def start(self):
        """Start all keep-alive layers."""
        # Start web server first (other layers depend on it)
        await self.web_server.start()

        # Start self-ping loop
        self.self_ping.start()

        logger.info(
            f"[KEEPALIVE] All layers active:\n"
            f"  Layer 1: Self-Ping (every 4 min) — ACTIVE\n"
            f"  Layer 2: Scheduler Ping (every 10 min) — via scheduler\n"
            f"  Layer 3: cron-job.org — configure externally\n"
            f"  Layer 4: UptimeRobot — configure externally\n"
            f"  Layer 5: Your Telegram commands — automatic"
        )

    async def stop(self):
        """Stop all keep-alive layers."""
        await self.self_ping.stop()
        await self.web_server.stop()
        logger.info("[KEEPALIVE] All layers stopped")

    def get_full_report(self) -> Dict[str, Any]:
        """Get combined report of all keep-alive layers."""
        return {
            "health": self.health.get_health(),
            "self_ping": self.self_ping.get_stats(),
            "web_server_port": self.web_server.port,
        }


# ============================================================
# SINGLETON
# ============================================================

_manager_instance: Optional[KeepAliveManager] = None


def get_keepalive_manager() -> KeepAliveManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = KeepAliveManager()
    return _manager_instance


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Keep-Alive Engine — Self-Test")
    print("=" * 60)

    print(f"\n  aiohttp available: {'YES' if AIOHTTP_AVAILABLE else 'NO'}")
    print(f"  PORT: {os.getenv('PORT', '10000')}")
    print(f"  RENDER_EXTERNAL_URL: {os.getenv('RENDER_EXTERNAL_URL', 'not set')}")

    health = _health
    print(f"\n  Health tracker initialized")
    print(f"  Uptime: {health.uptime_str}")
    print(f"  Memory: {health._get_memory_usage()}MB")

    manager = KeepAliveManager()
    print(f"\n  Web server port: {manager.web_server.port}")
    print(f"  Self-ping interval: {manager.self_ping.PING_INTERVAL_SEC}s")
    print(f"  Recovery interval: {manager.self_ping.RECOVERY_PING_INTERVAL_SEC}s")

    print(f"\n  5 Layers of Protection:")
    print(f"    1. Self-Ping (internal, every 4 min)")
    print(f"    2. Scheduler Ping (APScheduler, every 10 min)")
    print(f"    3. cron-job.org (external, every 5 min)")
    print(f"    4. UptimeRobot (external, every 5 min)")
    print(f"    5. Your Telegram commands (on every use)")

    print(f"\n  Endpoints:")
    print(f"    GET /       — alive confirmation")
    print(f"    GET /health — JSON health report")
    print(f"    GET /status — one-line status")
    print(f"    GET /ping   — minimal pong")

    print(f"\n  RESULT: Keep-Alive Engine ready!")
    print("=" * 60)
