"""
============================================================
PRISM v0.1 — MAIN ENTRY POINT (20-AGENT ORCHESTRATOR)
============================================================
Precision Recruitment Intelligence & Scoring Machine
Zero-cost MBA Hunt Agent system orchestrator.

Architecture:
    - Phased startup with dependency ordering & circuit breakers
    - 20-agent heartbeat system (PRISM: was 12 agents)
    - 5-provider AI routing (Groq, Cerebras, OpenRouter, Groq Compound, Mistral)
    - Structured health probing at every init stage
    - Graceful degradation: each subsystem can fail independently
    - Signal-safe shutdown with ordered teardown (Telegram FIRST)
    - Memory-aware GC on 512 MB Render constraint
    - Watchdog: monitors subsystem health
    - Startup diagnostic report to Telegram on success

Startup Phases (PRISM v0.1 — dependency-ordered):
    Phase 1 — FOUNDATION:  Config, Logging, Data dirs
    Phase 2 — STORAGE:     Database init, schema v3 migration, WAL
    Phase 3 — DATA SEED:   Company DB (1081), 20 agent heartbeats
    Phase 3.5 — SECURITY:  Admin, user whitelist, access codes
    Phase 4 — AI LAYER:    AI Router (5-provider PRISM architecture)
    Phase 5 — WEB LAYER:   aiohttp server, health endpoints
    Phase 6 — COMMS:       Telegram bot (delayed on Render)
    Phase 7 — SCHEDULER:   APScheduler (3-wave weekly PRISM cycle)
    Phase 8 — WATCHDOG:    Background monitor loop
    Phase 8.5 — TELETHON:  [PRISM] A-16 real-time TG listener (optional)
    Phase 9 — EMBEDDINGS:  [PRISM] Warmup sentence-transformers (lazy)

PRISM v0.1 Changes from OFM v5.x:
    - 20-agent heartbeat seeds (was 12)
    - 5-provider AI router init status
    - Phase 8.5: Telethon MTProto listener for A-16
    - Phase 9: Embedding engine lazy warmup
    - PRISM banner with 20-agent / 5-provider display
    - Updated startup report with PRISM provider status
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
import subprocess
import shutil
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

VERSION = "0.1.0-prism"
RENDER_OVERLAP_GRACE_SEC = int(os.getenv('RENDER_OVERLAP_GRACE_SEC', '20'))
WATCHDOG_INTERVAL_SEC = 120
STARTUP_TIMEOUT_SEC = 120
GC_INTERVAL_SEC = 300

BANNER = """
+============================================================+
|                                                              |
|   PRISM v0.1 — Precision Recruitment Intelligence            |
|                & Scoring Machine                             |
|                                                              |
|   20 AI Agents | 5 AI Providers | 1081 Companies            |
|   Groq + Cerebras + OpenRouter + Compound + Mistral          |
|   Telegram Command Center | InternHub Pro Mini App           |
|   3-Wave Weekly Schedule | PPO V11 | Total Daily Cost: $0    |
|                                                              |
+============================================================+
"""


# ============================================================
# MINI-APP BUILD (runs before web server starts)
# ============================================================

def build_miniapp_if_needed():
    """
    Build the mini-app frontend if dist/ doesn't exist.
    
    ROOT CAUSE FIX (v5.4.2):
        Previous build attempts failed for THREE reasons:
        1. postcss.config.js and tailwind.config.js used ESM 'export default'
           syntax with .js extensions — Node v22 strict ESM resolution breaks.
           FIX: Renamed to .cjs (CommonJS), use module.exports.
        2. Render sets NODE_ENV=production which skips devDependencies (vite,
           typescript, @types/*). The fallback 'npx vite build' also fails
           because node_modules/.bin isn't on PATH.
           FIX: Unset NODE_ENV, use --include=dev, add node_modules/.bin to PATH.
        3. 'tsc && vite build' fails because tsc requires @types/react-dom and
           @types/uuid which are devDependencies. But tsc is configured with
           noEmit:true (only type-checks, doesn't produce output). Vite uses
           esbuild for transpilation, making tsc unnecessary for production builds.
           FIX: Changed 'npm run build' to just 'vite build', added separate
           'typecheck' script for development.
        4. render.yaml didn't set NODE_VERSION env var, so Render used its default
           Node (v22) which has stricter ESM resolution rules.
           FIX: Added NODE_VERSION=20.19.0 to render.yaml envVars.
    
    This runs synchronously BEFORE the async event loop starts,
    so it won't block health checks (web server isn't up yet).
    """
    project_root = Path(__file__).parent
    miniapp_dir = project_root / "mini-app"
    dist_dir = miniapp_dir / "dist"
    index_html = dist_dir / "index.html"
    
    # Already built? Skip.
    if index_html.is_file():
        asset_count = sum(1 for _ in dist_dir.rglob("*") if _.is_file())
        logger.info(f"[MINIAPP-BUILD] dist/ exists ({asset_count} files) — skipping build")
        return True
    
    logger.warning("[MINIAPP-BUILD] mini-app/dist/ not found — building now...")
    
    # Check prerequisites
    if not (miniapp_dir / "package.json").is_file():
        logger.error("[MINIAPP-BUILD] mini-app/package.json not found — cannot build")
        return False
    
    npm_path = shutil.which("npm")
    node_path = shutil.which("node")
    
    if not npm_path or not node_path:
        logger.error(f"[MINIAPP-BUILD] Node.js/npm not found (node={node_path}, npm={npm_path})")
        logger.error("[MINIAPP-BUILD]    Mini-app will show 'Not Built' error")
        return False
    
    # Build environment: ensure node_modules/.bin is on PATH
    # CRITICAL: Remove NODE_ENV=production so devDependencies get installed
    # (Render sets NODE_ENV=production which skips devDeps like vite, typescript)
    build_env = os.environ.copy()
    build_env.pop("NODE_ENV", None)
    node_modules_bin = str(miniapp_dir / "node_modules" / ".bin")
    build_env["PATH"] = node_modules_bin + os.pathsep + build_env.get("PATH", "")
    
    # Log versions
    try:
        node_ver = subprocess.check_output([node_path, "--version"], timeout=10).decode().strip()
        npm_ver = subprocess.check_output([npm_path, "--version"], timeout=10).decode().strip()
        logger.info(f"[MINIAPP-BUILD] Node {node_ver}, npm {npm_ver}")
    except Exception:
        pass
    
    # Step 1: npm install (MUST include dev for vite, typescript, etc.)
    logger.info("[MINIAPP-BUILD] Running npm install --include=dev ...")
    try:
        result = subprocess.run(
            [npm_path, "install", "--include=dev", "--no-audit", "--no-fund"],
            cwd=str(miniapp_dir),
            capture_output=True,
            text=True,
            timeout=180,
            env=build_env,
        )
        if result.returncode != 0:
            logger.error(f"[MINIAPP-BUILD] npm install failed (exit {result.returncode}):")
            logger.error(f"[MINIAPP-BUILD] stdout: {result.stdout[-1000:]}")
            logger.error(f"[MINIAPP-BUILD] stderr: {result.stderr[-1000:]}")
            return False
        logger.info("[MINIAPP-BUILD] npm install complete")
    except subprocess.TimeoutExpired:
        logger.error("[MINIAPP-BUILD] npm install timed out (180s)")
        return False
    except Exception as e:
        logger.error(f"[MINIAPP-BUILD] npm install error: {e}")
        return False
    
    # Step 2: Build the mini-app
    # STRATEGY: Skip tsc entirely — it only type-checks (noEmit: true in tsconfig.json)
    # and fails on Render due to missing @types/* when NODE_ENV=production.
    # Vite uses esbuild for transpilation, not tsc, so this is safe.
    vite_bin = str(miniapp_dir / "node_modules" / ".bin" / "vite")
    build_commands = [
        ("npm run build (vite build)", [npm_path, "run", "build"]),
        ("direct vite binary", [vite_bin, "build"]),
    ]
    
    for desc, cmd in build_commands:
        logger.info(f"[MINIAPP-BUILD] Running {desc}...")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(miniapp_dir),
                capture_output=True,
                text=True,
                timeout=180,
                env=build_env,
            )
            if result.returncode == 0:
                # Check if dist was actually created
                if index_html.is_file():
                    asset_count = sum(1 for _ in dist_dir.rglob("*") if _.is_file())
                    logger.info(f"[MINIAPP-BUILD] Build successful via '{desc}'! {asset_count} files in dist/")
                    return True
                else:
                    logger.warning(f"[MINIAPP-BUILD] '{desc}' exited 0 but dist/index.html not found, trying next...")
                    continue
            else:
                logger.warning(f"[MINIAPP-BUILD] '{desc}' failed (exit {result.returncode})")
                if result.stdout.strip():
                    logger.warning(f"[MINIAPP-BUILD] stdout: {result.stdout[-1500:]}")
                if result.stderr.strip():
                    logger.warning(f"[MINIAPP-BUILD] stderr: {result.stderr[-1500:]}")
                # Continue to next fallback
                continue
        except subprocess.TimeoutExpired:
            logger.error(f"[MINIAPP-BUILD] '{desc}' timed out (180s)")
            continue
        except Exception as e:
            logger.error(f"[MINIAPP-BUILD] '{desc}' error: {e}")
            continue
    
    # Final check
    if index_html.is_file():
        asset_count = sum(1 for _ in dist_dir.rglob("*") if _.is_file())
        logger.info(f"[MINIAPP-BUILD] Build successful! {asset_count} files in dist/")
        return True
    else:
        logger.error("[MINIAPP-BUILD] All build attempts failed. dist/index.html not found.")
        logger.error("[MINIAPP-BUILD] The /app/ endpoint will show an error page.")
        logger.error("[MINIAPP-BUILD] To fix: ensure Node.js v20 is available and run 'cd mini-app && npm install && npm run build'")
        return False


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

            # Initialize Supabase (persistent cloud database)
            try:
                from core.supabase_client import get_supabase, is_supabase_configured, get_status_summary
                if is_supabase_configured():
                    client = get_supabase()
                    if client:
                        self._status.mark_ok('supabase', get_status_summary())
                        logger.info(f"[Phase 2] Supabase: {get_status_summary()}")
                    else:
                        self._status.mark_degraded('supabase', 'Client init failed')
                        logger.warning("[Phase 2] Supabase client init failed (will retry)")
                else:
                    self._status.mark_degraded('supabase', 'Not configured (set SUPABASE_URL + key)')
                    logger.info("[Phase 2] Supabase: not configured (optional)")
            except Exception as e:
                self._status.mark_degraded('supabase', str(e))
                logger.warning(f"[Phase 2] Supabase init warning: {e}")

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
            detail += ", heartbeats A-01..A-20 (PRISM)"

            self._status.mark_ok('seed', detail)
            logger.info(f"[Phase 3] {detail}")
        except Exception as e:
            self._status.mark_degraded('seed', str(e))
            logger.error(f"[Phase 3] Seed error: {e}")

    # ================================================================
    # PHASE 3.5: SECURITY LAYER
    # ================================================================

    def _init_security(self):
        """Initialize the security layer (admin, user whitelist, access codes)."""
        try:
            from core.security import get_security_manager, ADMIN_TELEGRAM_ID, ADMIN_USERNAME
            sec = get_security_manager()
            status = sec.get_security_status()
            detail = (
                f"admin=@{ADMIN_USERNAME} (ID:{ADMIN_TELEGRAM_ID}), "
                f"users={status['active_users']}"
            )
            self._status.mark_ok('security', detail)
            logger.info(f"[Phase 3.5] Security initialized: {detail}")
        except Exception as e:
            self._status.mark_degraded('security', str(e))
            logger.warning(f"[Phase 3.5] Security degraded: {e}")
            logger.warning("[Phase 3.5] System continues WITHOUT security layer")

    # ================================================================
    # PHASE 4: AI LAYER
    # ================================================================

    def _init_ai_layer(self):
        try:
            from core.ai_router import get_router
            router = get_router()
            health = router.get_health()

            # Count configured providers
            providers_ready = []
            for prov_name in ['groq', 'cerebras', 'openrouter', 'groq_compound', 'mistral']:
                prov_info = health.get(prov_name, {})
                if prov_info.get('api_key_set', False):
                    providers_ready.append(prov_name)

            detail = f"PRISM 5-provider: {len(providers_ready)}/5 configured ({', '.join(providers_ready)})"
            self._status.mark_ok('ai_router', detail)
            logger.info(f"[Phase 4] AI Router ready — {detail}")
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
            # v6.0: Use weekly scheduler if configured, else fall back to daily
            schedule_mode = os.getenv('SCHEDULE_MODE', 'weekly').lower()

            if schedule_mode == 'weekly':
                from core.weekly_scheduler import get_weekly_scheduler
                self._scheduler = get_weekly_scheduler()
                await self._scheduler.start()
                self._status.mark_ok('scheduler', 'v6.0 weekly smart schedule running')
                logger.info("[Phase 7] v6.0 Weekly Smart Scheduler running")
            else:
                from core.scheduler import get_scheduler
                self._scheduler = get_scheduler()
                await self._scheduler.start()
                self._status.mark_ok('scheduler', 'v5.1 daily schedule running')
                logger.info("[Phase 7] v5.1 Daily Scheduler running (legacy)")

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
                        schedule_mode = os.getenv('SCHEDULE_MODE', 'weekly').lower()
                        if schedule_mode == 'weekly':
                            from core.weekly_scheduler import get_weekly_scheduler
                            sched = get_weekly_scheduler()
                        else:
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
        logger.info(f"  PRISM v{VERSION} -- STARTING")
        logger.info(f"  Mode: {'Render' if self._is_render else 'Local'} Web Service")
        logger.info(f"  PID: {os.getpid()}")
        logger.info("=" * 60)

        start_time = time.monotonic()

        logger.info("[Phase 1/11] Loading configuration...")
        config = self._init_foundation()

        # Phase 0 (post-foundation): Build mini-app if needed
        # This MUST run before web server (Phase 5) so /app/ can serve the built files
        logger.info("[Phase 1.5/11] Checking mini-app build status...")
        miniapp_built = build_miniapp_if_needed()
        if miniapp_built:
            # Invalidate any cached dist path so the web server picks up the fresh build
            try:
                from core.miniapp_api import invalidate_dist_cache
                invalidate_dist_cache()
            except ImportError:
                pass
            self._status.mark_ok('miniapp_build', 'dist/ ready')
        else:
            self._status.mark_degraded('miniapp_build', 'dist/ not available — /app/ will show error')

        logger.info("[Phase 2/11] Initializing database...")
        db = self._init_storage()

        logger.info("[Phase 3/11] Seeding data...")
        self._init_data_seed(db)

        logger.info("[Phase 3.5/11] Initializing security layer...")
        self._init_security()

        logger.info("[Phase 4/11] Initializing AI router...")
        self._init_ai_layer()

        logger.info("[Phase 5/11] Starting web server + keep-alive...")
        await self._init_web_layer()

        logger.info("[Phase 6/11] Starting Telegram bot...")
        await self._init_telegram()

        logger.info("[Phase 7/11] Starting scheduler...")
        await self._init_scheduler()

        logger.info("[Phase 8/11] Starting watchdog + memory manager...")
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        self._gc_task = asyncio.create_task(self._gc_loop())
        self._status.mark_ok('watchdog', f'interval={WATCHDOG_INTERVAL_SEC}s')

        # Start Supabase keepalive loop (Layer 1)
        try:
            from core.supabase_client import is_supabase_configured
            if is_supabase_configured():
                from core.supabase_keepalive import keepalive_loop
                self._supabase_keepalive_task = asyncio.create_task(
                    keepalive_loop(interval_hours=12.0)
                )
                logger.info("[Phase 8/11] Supabase keepalive L1 loop started")
        except Exception as e:
            logger.debug(f"[Phase 8/11] Supabase keepalive skip: {e}")

        # ============================================================
        # PRISM v0.1: Phase 8.5 — Telethon A-16 Real-time Listener
        # ============================================================
        logger.info("[Phase 8.5/11] Initializing A-16 Telethon listener...")
        try:
            from agents.a16_tg_listener import get_tg_monitor
            tg_monitor = get_tg_monitor()
            tg_health = tg_monitor.get_health()
            if tg_health.get('configured', False):
                self._status.mark_ok('telethon_a16', 'configured, will start with scheduler')
                logger.info("[Phase 8.5/11] A-16 Telethon: configured (start deferred to scheduler)")
            else:
                self._status.mark_degraded('telethon_a16', 'not configured (set TG_API_ID + TG_API_HASH)')
                logger.info("[Phase 8.5/11] A-16 Telethon: not configured (optional)")
        except Exception as e:
            self._status.mark_degraded('telethon_a16', str(e))
            logger.info(f"[Phase 8.5/11] A-16 Telethon: skipped ({e})")

        # ============================================================
        # PRISM v0.1: Phase 9 — Embedding Engine Warmup
        # ============================================================
        logger.info("[Phase 9/11] PRISM embedding engine warmup...")
        try:
            from core.embedding_engine import get_embedding_engine
            embed_engine = get_embedding_engine()
            embed_health = embed_engine.get_health()
            lazy = embed_health.get('lazy_load', True)
            if lazy:
                self._status.mark_ok('embeddings', 'lazy-load enabled (will load on first use)')
                logger.info("[Phase 9/11] Embedding engine: lazy-load (will load on first PPO V11 call)")
            else:
                # Force load now
                embed_engine._ensure_loaded()
                self._status.mark_ok('embeddings', f'loaded: {embed_health["model_name"]}')
                logger.info(f"[Phase 9/11] Embedding engine: loaded ({embed_health['model_name']})")
        except Exception as e:
            self._status.mark_degraded('embeddings', str(e))
            logger.info(f"[Phase 9/11] Embedding engine: skipped ({e})")

        gc.collect()

        duration = time.monotonic() - start_time
        self._running = True

        render_url = os.getenv('RENDER_EXTERNAL_URL', '')
        port = os.getenv('PORT', '10000')
        mini_app_url = os.getenv('MINI_APP_URL', '')

        logger.info("=" * 60)
        logger.info(f"  PRISM v{VERSION} STARTUP COMPLETE in {duration:.1f}s")
        logger.info(f"  Status: {'ALL OK' if self._status.all_ok else 'DEGRADED'}")
        logger.info(f"  Web: http://0.0.0.0:{port}")
        if render_url:
            logger.info(f"  Render URL: {render_url}")
            logger.info(f"  Health: {render_url}/health")
            logger.info(f"  Mini App: {render_url}/app/")
        if mini_app_url:
            logger.info(f"  Mini App URL: {mini_app_url}")
        logger.info(f"  Architecture: 20 Agents | 5 AI Providers")
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
            # Detect mini app URL
            mini_app_url = os.getenv('MINI_APP_URL', '')
            if not mini_app_url and render_url != 'N/A':
                mini_app_url = f"{render_url.rstrip('/')}/app/"
            miniapp_line = f"📱 Mini App: {'✅ ' + mini_app_url if mini_app_url else '❌ Not configured'}"
            
            msg = (
                f"🚀 <b>PRISM v0.1 SYSTEM STARTUP COMPLETE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⏱ Duration: <b>{duration:.1f}s</b>\n"
                f"🔗 {render_url}\n"
                f"📦 Version: {VERSION}\n"
                f"🤖 Architecture: 20 Agents | 5 AI Providers\n"
                f"{miniapp_line}\n\n"
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
