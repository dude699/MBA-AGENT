"""
============================================================
OPERATION FIRST MOVER v5.1 — ULTIMATE KEEP-ALIVE ENGINE
(INDUSTRIAL GRADE)
============================================================
Multi-layer, self-healing keep-alive system with:
  - Exponential backoff with jitter on self-ping failures
  - Health aggregation across all subsystems
  - Adaptive ping frequency based on failure rate
  - Structured JSON health responses with versioned schema
  - Memory pressure detection and proactive GC
  - Render spin-down prevention with 5 independent layers

5 LAYERS OF PROTECTION:
    Layer 1: Internal Self-Ping (asyncio, 4 min, exponential backoff)
    Layer 2: APScheduler Keep-Alive (10 min via scheduler.py)
    Layer 3: cron-job.org external ping (5 min, free)
    Layer 4: UptimeRobot monitoring (5 min, free)
    Layer 5: Telegram commands (user activity)
============================================================
"""

import os
import time
import asyncio
import gc
import random
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

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
    logger.error("aiohttp not available -- web server disabled!")

from core.config import get_config, IST


# ============================================================
# CONSTANTS
# ============================================================

HEALTH_SCHEMA_VERSION = "1.1"
MEMORY_WARNING_MB = 400
MEMORY_CRITICAL_MB = 480
SELF_PING_BASE_INTERVAL = 240
SELF_PING_MIN_INTERVAL = 60
SELF_PING_MAX_INTERVAL = 300
SELF_PING_INITIAL_DELAY = 30
MAX_CONSECUTIVE_FAILURES = 5
PING_TIMEOUT_SECONDS = 15
HEALTH_HISTORY_SIZE = 50


# ============================================================
# HEALTH TRACKER
# ============================================================

class HealthTracker:
    """Aggregated health tracking across all subsystems."""

    def __init__(self):
        self._start_time = time.monotonic()
        self._start_wall = time.time()
        self._ping_count = 0
        self._last_ping_time = 0.0
        self._last_self_ping = 0.0
        self._last_external_ping = 0.0
        self._self_ping_failures = 0
        self._self_ping_successes = 0
        self._total_requests = 0
        self._scheduler_running = False
        self._telegram_running = False
        self._db_healthy = False
        self._shutdown_requested = False
        self._last_error: Optional[str] = None
        self._error_count = 0
        self._ping_history: List[Dict[str, Any]] = []
        self._subsystem_status: Dict[str, str] = {}

    def record_ping(self, source: str = "unknown"):
        now = time.time()
        self._ping_count += 1
        self._last_ping_time = now
        self._total_requests += 1

        if source == "self":
            self._last_self_ping = now
            self._self_ping_successes += 1
        elif source in ("cron-job", "uptimerobot", "external"):
            self._last_external_ping = now

        self._ping_history.append({
            'source': source,
            'time': now,
            'uptime_s': now - self._start_wall,
        })
        if len(self._ping_history) > HEALTH_HISTORY_SIZE:
            self._ping_history.pop(0)

    def record_self_ping_failure(self):
        self._self_ping_failures += 1

    def record_request(self):
        self._total_requests += 1

    def set_scheduler_status(self, running: bool):
        self._scheduler_running = running
        self._subsystem_status['scheduler'] = 'running' if running else 'stopped'

    def set_telegram_status(self, running: bool):
        self._telegram_running = running
        self._subsystem_status['telegram'] = 'running' if running else 'stopped'

    def set_db_status(self, healthy: bool):
        self._db_healthy = healthy
        self._subsystem_status['database'] = 'healthy' if healthy else 'unhealthy'

    def _get_supabase_status(self) -> str:
        """Get Supabase operational status for health report."""
        try:
            from core.supabase_client import is_operational, is_supabase_configured
            if not is_supabase_configured():
                return "not_configured"
            return "operational" if is_operational() else "degraded"
        except Exception:
            return "unknown"

    def set_shutdown_requested(self):
        self._shutdown_requested = True

    def record_error(self, error_msg: str):
        self._last_error = error_msg
        self._error_count += 1

    def set_subsystem(self, name: str, status: str):
        self._subsystem_status[name] = status

    @property
    def ping_count(self) -> int:
        return self._ping_count

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

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

    @property
    def self_ping_success_rate(self) -> float:
        total = self._self_ping_successes + self._self_ping_failures
        if total == 0:
            return 1.0
        return self._self_ping_successes / total

    @property
    def memory_mb(self) -> int:
        return self._get_memory_usage()

    @property
    def memory_pressure(self) -> str:
        mem = self.memory_mb
        if mem >= MEMORY_CRITICAL_MB:
            return "CRITICAL"
        elif mem >= MEMORY_WARNING_MB:
            return "WARNING"
        return "OK"

    def get_health(self) -> Dict[str, Any]:
        now = time.time()
        mem = self.memory_mb

        if self._shutdown_requested:
            overall = "shutting_down"
        elif mem >= MEMORY_CRITICAL_MB:
            overall = "degraded"
        elif self._error_count > 50:
            overall = "degraded"
        else:
            overall = "healthy"

        return {
            "schema_version": HEALTH_SCHEMA_VERSION,
            "status": overall,
            "uptime": self.uptime_str,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "started_at": datetime.fromtimestamp(
                self._start_wall, tz=IST
            ).strftime("%Y-%m-%d %H:%M:%S IST"),
            "pings": {
                "total": self._ping_count,
                "self_successes": self._self_ping_successes,
                "self_failures": self._self_ping_failures,
                "self_success_rate": f"{self.self_ping_success_rate:.1%}",
                "last_ping_ago_sec": round(now - self._last_ping_time, 1) if self._last_ping_time else None,
                "last_self_ping_ago_sec": round(now - self._last_self_ping, 1) if self._last_self_ping else None,
                "last_external_ping_ago_sec": round(now - self._last_external_ping, 1) if self._last_external_ping else None,
            },
            "subsystems": {
                "scheduler": self._scheduler_running,
                "telegram": self._telegram_running,
                "database": self._db_healthy,
                "supabase": self._get_supabase_status(),
                **{k: v for k, v in self._subsystem_status.items()
                   if k not in ('scheduler', 'telegram', 'database')},
            },
            "memory": {
                "usage_mb": mem,
                "pressure": self.memory_pressure,
                "render_limit_mb": 512,
            },
            "errors": {
                "total": self._error_count,
                "last": self._last_error,
            },
            "requests": self._total_requests,
            "shutdown_requested": self._shutdown_requested,
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }

    def get_status_text(self) -> str:
        h = self.get_health()
        return (
            f"OK | up={h['uptime']} | pings={h['pings']['total']} | "
            f"mem={h['memory']['usage_mb']}MB/{h['memory']['pressure']} | "
            f"sched={'ON' if h['subsystems']['scheduler'] else 'OFF'} | "
            f"tg={'ON' if h['subsystems']['telegram'] else 'OFF'} | "
            f"ping_rate={h['pings']['self_success_rate']}"
        )

    @staticmethod
    def _get_memory_usage() -> int:
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return int(usage.ru_maxrss / 1024)
        except Exception:
            return 0


_health = HealthTracker()


def get_health_tracker() -> HealthTracker:
    return _health


# ============================================================
# AIOHTTP WEB SERVER
# ============================================================

class WebServer:
    """
    Production-grade aiohttp web server for health checks.

    Endpoints:
        GET /                -> Alive confirmation (text)
        GET /health          -> Full JSON health report
        GET /status          -> One-line text status
        GET /ping            -> Bare minimum pong (fastest)
        GET /telegram-status -> Telegram polling status
        HEAD /,/health,/ping -> HEAD variants for monitors
    """

    def __init__(self):
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._port = int(os.getenv('PORT', '10000'))
        self.health = _health

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get('/', self._handle_root)
        app.router.add_get('/health', self._handle_health)
        app.router.add_get('/status', self._handle_status)
        app.router.add_get('/ping', self._handle_ping)
        app.router.add_get('/telegram-status', self._handle_telegram_status)
        # NEXUS v0.2 — public layer snapshot (returns 503 when disabled).
        app.router.add_get('/nexus', self._handle_nexus)
        app.router.add_route('HEAD', '/', self._handle_ping)
        app.router.add_route('HEAD', '/health', self._handle_ping)
        app.router.add_route('HEAD', '/ping', self._handle_ping)
        app.router.add_route('HEAD', '/nexus', self._handle_ping)
        
        # Register auth API routes for Mini-App security
        try:
            from core.auth_middleware import register_auth_routes
            register_auth_routes(app)
            logger.info("[WEBSERVER] Auth API routes registered")
        except ImportError as e:
            logger.warning(f"[WEBSERVER] Auth middleware not available: {e}")
        except Exception as e:
            logger.warning(f"[WEBSERVER] Auth route registration failed: {e}")
        
        # ALWAYS register Mini-App API routes + static file serving upfront.
        # aiohttp freezes the router on startup — routes CANNOT be added after.
        # The mini-app handlers gracefully return "Not Built" page if dist/
        # doesn't exist yet, and will serve files once dist/ appears.
        try:
            from core.miniapp_api import register_miniapp_routes
            register_miniapp_routes(app)
            logger.info("[WEBSERVER] Mini-App API + static routes registered")
        except ImportError as e:
            logger.warning(f"[WEBSERVER] Mini-App API module not available: {e}")
        except Exception as e:
            logger.warning(f"[WEBSERVER] Mini-App route registration failed: {e}")
        
        return app

    async def start(self):
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp not installed")

        self._app = self._create_app()
        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner, host='0.0.0.0', port=self._port,
        )
        await self._site.start()
        logger.info(f"[WEBSERVER] Listening on 0.0.0.0:{self._port}")
        logger.info(f"[WEBSERVER] Endpoints: / /health /status /ping /telegram-status /app/ /api/*")

    async def stop(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("[WEBSERVER] Stopped")

    @property
    def port(self) -> int:
        return self._port

    async def _handle_root(self, request: web.Request) -> web.Response:
        self.health.record_request()
        source = request.query.get('source', 'unknown')
        if source != 'unknown':
            self.health.record_ping(source)

        return web.Response(
            text=(
                f"PRISM v0.1 — Precision Recruitment Intelligence & Scoring Machine\n"
                f"Status: ALIVE\n"
                f"Uptime: {self.health.uptime_str}\n"
                f"Pings: {self.health.ping_count}\n"
                f"Memory: {self.health.memory_mb}MB ({self.health.memory_pressure})\n"
            ),
            content_type='text/plain',
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        self.health.record_request()
        source = request.query.get('source', 'external')
        self.health.record_ping(source)

        return web.Response(
            text=json.dumps(self.health.get_health(), indent=2),
            content_type='application/json',
        )

    async def _handle_status(self, request: web.Request) -> web.Response:
        self.health.record_request()
        return web.Response(
            text=self.health.get_status_text(),
            content_type='text/plain',
        )

    async def _handle_ping(self, request: web.Request) -> web.Response:
        self.health.record_ping("external")
        return web.Response(text="pong", content_type='text/plain')

    async def _handle_telegram_status(self, request: web.Request) -> web.Response:
        self.health.record_request()
        status = {
            "telegram_running": self.health._telegram_running,
            "uptime": self.health.uptime_str,
            "uptime_seconds": round(self.health.uptime_seconds, 1),
            "shutdown_requested": self.health._shutdown_requested,
            "memory_pressure": self.health.memory_pressure,
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }
        return web.Response(
            text=json.dumps(status),
            content_type='application/json',
        )

    async def _handle_nexus(self, request: web.Request) -> web.Response:
        """NEXUS v0.2 layer-status endpoint.

        Returns 200 + JSON snapshot when the runtime is live, 503 + reason
        when NEXUS is disabled or hasn't booted yet. Safe to call publicly —
        no secrets or session data is exposed.
        """
        self.health.record_request()
        try:
            from core.nexus_runtime import get_runtime
        except Exception as e:
            return web.Response(
                status=503,
                text=json.dumps({"enabled": False, "reason": f"import_error: {e}"}),
                content_type='application/json',
            )

        rt = get_runtime()
        if rt is None:
            return web.Response(
                status=503,
                text=json.dumps({
                    "enabled": False,
                    "reason": "NEXUS_ENABLED is not set or runtime has not booted",
                    "hint":   "Set NEXUS_ENABLED=true in env (and restart) to opt-in.",
                }),
                content_type='application/json',
            )

        try:
            snap = await rt.snapshot()
        except Exception as e:
            return web.Response(
                status=503,
                text=json.dumps({"enabled": True, "error": str(e)}),
                content_type='application/json',
            )

        snap["enabled"]   = True
        snap["timestamp"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        return web.Response(
            text=json.dumps(snap, default=str),
            content_type='application/json',
        )


# ============================================================
# LAYER 1: SELF-PING WITH EXPONENTIAL BACKOFF + JITTER
# ============================================================

class SelfPingLoop:
    """
    Self-ping with adaptive frequency:
    - Normal: 4 min interval
    - Recovery: exponential backoff with jitter
    - Relaxed: 5 min after 1h clean uptime
    """

    def __init__(self, port: int):
        self._port = port
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._total_pings = 0
        self._total_failures = 0
        self._in_recovery = False
        self._last_success_time = 0.0
        self.health = _health
        self._external_url = os.getenv('RENDER_EXTERNAL_URL', '')
        self._local_url = f"http://127.0.0.1:{self._port}"

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._ping_loop())
        logger.info(
            f"[KEEPALIVE] Layer 1 (Self-Ping) started -- "
            f"every {SELF_PING_BASE_INTERVAL}s"
        )

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[KEEPALIVE] Layer 1 (Self-Ping) stopped")

    def _compute_interval(self) -> float:
        if self._in_recovery:
            base = min(
                SELF_PING_MIN_INTERVAL * (2 ** min(self._consecutive_failures, 3)),
                SELF_PING_MAX_INTERVAL
            )
            jitter = random.uniform(0, base * 0.2)
            return base + jitter

        if (self._last_success_time > 0
                and self._consecutive_failures == 0
                and self.health.uptime_seconds > 3600):
            return SELF_PING_MAX_INTERVAL
        return SELF_PING_BASE_INTERVAL

    async def _ping_loop(self):
        await asyncio.sleep(SELF_PING_INITIAL_DELAY)

        while self._running:
            try:
                interval = self._compute_interval()
                success = await self._do_ping()

                if success:
                    self._consecutive_failures = 0
                    self._last_success_time = time.monotonic()
                    if self._in_recovery:
                        self._in_recovery = False
                        logger.info("[KEEPALIVE] Recovery complete -- back to normal")
                else:
                    self._consecutive_failures += 1
                    self._total_failures += 1
                    self.health.record_self_ping_failure()

                    if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        await self._attempt_recovery()

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[KEEPALIVE] Ping loop error: {e}")
                await asyncio.sleep(SELF_PING_MIN_INTERVAL)

    async def _do_ping(self) -> bool:
        self._total_pings += 1

        if self._external_url:
            try:
                timeout = ClientTimeout(total=PING_TIMEOUT_SECONDS)
                async with ClientSession(timeout=timeout) as session:
                    url = f"{self._external_url}/health?source=self"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            self.health.record_ping("self")
                            return True
            except Exception:
                pass

        try:
            timeout = ClientTimeout(total=5)
            async with ClientSession(timeout=timeout) as session:
                url = f"{self._local_url}/health?source=self"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        self.health.record_ping("self")
                        return True
        except Exception as e:
            logger.warning(f"[KEEPALIVE] Self-ping failed (both): {e}")

        return False

    async def _attempt_recovery(self):
        logger.warning(
            f"[KEEPALIVE] {self._consecutive_failures} consecutive failures -- "
            f"entering recovery mode"
        )
        self._in_recovery = True

        gc.collect(generation=2)
        collected = gc.collect()
        logger.info(f"[KEEPALIVE] GC recovered {collected} objects")

        mem = self.health.memory_mb
        if mem >= MEMORY_WARNING_MB:
            logger.warning(
                f"[KEEPALIVE] Memory pressure: {mem}MB / 512MB"
            )
            try:
                import linecache
                linecache.clearcache()
            except Exception:
                pass

        self._consecutive_failures = 0

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_pings": self._total_pings,
            "total_failures": self._total_failures,
            "consecutive_failures": self._consecutive_failures,
            "in_recovery": self._in_recovery,
            "success_rate": f"{self.health.self_ping_success_rate:.1%}",
            "current_interval_sec": round(self._compute_interval(), 1),
            "external_url": self._external_url or "not set",
        }


# ============================================================
# COMBINED KEEP-ALIVE MANAGER
# ============================================================

class KeepAliveManager:
    def __init__(self):
        self.web_server = WebServer()
        self.self_ping = SelfPingLoop(self.web_server.port)
        self.health = _health

    @property
    def _app(self):
        """Access the underlying aiohttp application."""
        return self.web_server._app

    async def start(self):
        await self.web_server.start()
        self.self_ping.start()

        logger.info(
            f"[KEEPALIVE] All layers active:\n"
            f"  Layer 1: Self-Ping (every 4 min) -- ACTIVE\n"
            f"  Layer 2: Scheduler Ping (every 10 min) -- via scheduler\n"
            f"  Layer 3: cron-job.org -- configure externally\n"
            f"  Layer 4: UptimeRobot -- configure externally\n"
            f"  Layer 5: Your Telegram commands -- automatic"
        )

    async def stop(self):
        await self.self_ping.stop()
        await self.web_server.stop()
        logger.info("[KEEPALIVE] All layers stopped")

    def get_full_report(self) -> Dict[str, Any]:
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
    print("  Keep-Alive Engine v5.1 -- Self-Test")
    print("=" * 60)

    print(f"\n  aiohttp available: {'YES' if AIOHTTP_AVAILABLE else 'NO'}")
    print(f"  PORT: {os.getenv('PORT', '10000')}")
    print(f"  RENDER_EXTERNAL_URL: {os.getenv('RENDER_EXTERNAL_URL', 'not set')}")

    health = _health
    print(f"\n  Health tracker initialized")
    print(f"  Uptime: {health.uptime_str}")
    print(f"  Memory: {health.memory_mb}MB ({health.memory_pressure})")

    print(f"\n  5 Layers of Protection:")
    print(f"    1. Self-Ping (adaptive, base={SELF_PING_BASE_INTERVAL}s)")
    print(f"    2. Scheduler Ping (APScheduler, every 10 min)")
    print(f"    3. cron-job.org (external, every 5 min)")
    print(f"    4. UptimeRobot (external, every 5 min)")
    print(f"    5. Telegram commands (on every use)")

    print(f"\n  RESULT: Keep-Alive Engine ready!")
    print("=" * 60)
