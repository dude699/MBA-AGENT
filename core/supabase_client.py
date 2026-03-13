"""
============================================================
OPERATION FIRST MOVER v5.5 -- SUPABASE CLIENT MODULE
============================================================
Singleton Supabase client with retry logic, health checks,
and graceful degradation. Falls back silently if Supabase
is not configured (system works fine with just SQLite).

Supabase Free Tier Limits (2026):
    - 500 MB database storage
    - Unlimited API requests
    - 5 GB bandwidth/month
    - 50,000 monthly active users
    - 2 free projects max
    - Project pauses after 7 days inactivity → keepalive needed
============================================================
"""

import os
import time
import threading
from typing import Optional, Dict, Any, List

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    Client = None  # type: ignore

from loguru import logger

MODULE_ID = "SUPABASE-CLIENT"

# ============================================================
# SINGLETON CLIENT
# ============================================================

_client: Optional[Any] = None
_lock = threading.Lock()
_init_attempted = False
_consecutive_failures = 0
_MAX_CONSECUTIVE_FAILURES = 10
_last_success_time = 0.0


def is_supabase_configured() -> bool:
    """Check if Supabase env vars are set."""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.getenv("SUPABASE_ANON_KEY", "").strip()
    return bool(url and key)


def get_supabase() -> Optional[Any]:
    """
    Get or create the singleton Supabase client.
    Returns None if not configured or import failed.
    Thread-safe with double-checked locking.
    """
    global _client, _init_attempted

    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client

        if _init_attempted:
            return None

        _init_attempted = True

        if not HAS_SUPABASE:
            logger.info(f"[{MODULE_ID}] supabase-py not installed, Supabase disabled")
            return None

        url = os.getenv("SUPABASE_URL", "").strip()
        # Prefer service_role_key for server-side (full access)
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not key:
            key = os.getenv("SUPABASE_ANON_KEY", "").strip()

        if not url or not key:
            logger.info(f"[{MODULE_ID}] SUPABASE_URL or key not set, Supabase disabled")
            return None

        try:
            _client = create_client(url, key)
            logger.info(f"[{MODULE_ID}] Client initialized: {url[:40]}...")
            return _client
        except Exception as e:
            logger.error(f"[{MODULE_ID}] Failed to create client: {e}")
            return None


def reset_client():
    """Force re-init on next call (for recovery after errors)."""
    global _client, _init_attempted, _consecutive_failures
    with _lock:
        _client = None
        _init_attempted = False
        _consecutive_failures = 0


def is_operational() -> bool:
    """Check if Supabase client exists and hasn't hit failure threshold."""
    if not is_supabase_configured():
        return False
    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        return False
    return get_supabase() is not None


def record_success():
    """Record a successful Supabase operation."""
    global _consecutive_failures, _last_success_time
    _consecutive_failures = 0
    _last_success_time = time.time()


def record_failure():
    """Record a failed Supabase operation."""
    global _consecutive_failures
    _consecutive_failures += 1
    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        logger.warning(
            f"[{MODULE_ID}] {_consecutive_failures} consecutive failures — "
            f"Supabase marked degraded. Call reset_client() to retry."
        )


# ============================================================
# HEALTH CHECK
# ============================================================

def health_check() -> Dict[str, Any]:
    """
    Quick health check — try a lightweight query.
    Returns dict with connected, latency_ms, error.
    """
    client = get_supabase()
    if not client:
        return {"connected": False, "error": "Client not initialized"}

    start = time.monotonic()
    try:
        # Simple query on the keepalive_pings table (or any table)
        # This is the lightest possible query to verify connectivity
        resp = client.table("keepalive_pings").select("id").limit(1).execute()
        latency = (time.monotonic() - start) * 1000
        record_success()
        return {
            "connected": True,
            "latency_ms": round(latency, 1),
            "rows": len(resp.data) if resp.data else 0,
        }
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        error_str = str(e)[:200]
        # If table doesn't exist yet, connection itself is fine
        if "does not exist" in error_str or "42P01" in error_str:
            record_success()
            return {
                "connected": True,
                "latency_ms": round(latency, 1),
                "note": "Tables not created yet — run schema SQL first",
            }
        record_failure()
        return {"connected": False, "latency_ms": round(latency, 1), "error": error_str}


# ============================================================
# RETRY WRAPPER
# ============================================================

def execute_with_retry(operation, max_retries: int = 3, backoff: float = 1.0):
    """
    Execute a Supabase operation with exponential backoff retry.
    
    Usage:
        result = execute_with_retry(
            lambda client: client.table("x").select("*").execute()
        )
    """
    client = get_supabase()
    if not client:
        return None

    last_error = None
    for attempt in range(max_retries):
        try:
            result = operation(client)
            record_success()
            return result
        except Exception as e:
            last_error = e
            record_failure()
            if attempt < max_retries - 1:
                wait = backoff * (2 ** attempt)
                logger.debug(f"[{MODULE_ID}] Retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                time.sleep(wait)
            else:
                logger.error(f"[{MODULE_ID}] All {max_retries} retries failed: {last_error}")

    return None


# ============================================================
# STATUS SUMMARY
# ============================================================

def get_status_summary() -> str:
    """One-line status for health endpoint / logs."""
    if not is_supabase_configured():
        return "SUPABASE: Not configured"
    if not _init_attempted:
        return "SUPABASE: Not initialized yet"
    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        return f"SUPABASE: DEGRADED ({_consecutive_failures} failures)"
    if _client is not None:
        return "SUPABASE: Operational"
    return "SUPABASE: Init failed"
