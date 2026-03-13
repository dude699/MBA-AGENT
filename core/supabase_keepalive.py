"""
============================================================
OPERATION FIRST MOVER v5.5 -- SUPABASE KEEP-ALIVE ENGINE
============================================================
4-layer anti-inactivity system to prevent Supabase free tier
from pausing after 7 days of inactivity.

Layer 1: Background asyncio loop (every 12h with jitter)
Layer 2: APScheduler job (every 8h) — see scheduler.py
Layer 3: Piggyback on existing Render keepalive pings
Layer 4: Every Supabase read/write counts as activity

Strategy:
    - Minimum 4h gap between pings to avoid wasting bandwidth
    - Writes a row to keepalive_pings table (proves DB is alive)
    - Cleans up old ping records (keep last 100)
    - Smart: won't ping if recent activity already happened
    - Never gets banned: legitimate DB operations, not API abuse
============================================================
"""

import time
import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from loguru import logger

MODULE_ID = "SB-KEEPALIVE"
IST = timezone(timedelta(hours=5, minutes=30))

# ---- State ----
_last_ping_time: float = 0.0
_total_pings: int = 0
_consecutive_failures: int = 0
_ping_history: list = []
MIN_PING_INTERVAL = 4 * 3600  # 4 hours minimum between pings


# ============================================================
# CORE PING FUNCTION
# ============================================================

def _do_ping(source: str = "keepalive") -> Dict[str, Any]:
    """
    Execute a keepalive ping by writing to keepalive_pings table.
    This is a real DB write — Supabase counts it as activity.
    """
    global _last_ping_time, _total_pings, _consecutive_failures

    from core.supabase_client import get_supabase, is_operational, record_success, record_failure

    if not is_operational():
        return {"success": False, "reason": "Supabase not operational"}

    # Rate limit: don't ping too often
    now = time.time()
    if _last_ping_time and (now - _last_ping_time) < MIN_PING_INTERVAL:
        remaining = MIN_PING_INTERVAL - (now - _last_ping_time)
        return {"success": True, "skipped": True, "reason": f"Too soon ({remaining/3600:.1f}h remaining)"}

    client = get_supabase()
    if not client:
        return {"success": False, "reason": "No client"}

    start = time.monotonic()
    try:
        # Write a ping record
        resp = client.table("keepalive_pings").insert({
            "ping_type": "keepalive",
            "source": source,
            "latency_ms": 0,
        }).execute()

        latency = (time.monotonic() - start) * 1000

        # Update the row with actual latency
        if resp.data and resp.data[0].get("id"):
            try:
                client.table("keepalive_pings").update({
                    "latency_ms": round(latency, 1)
                }).eq("id", resp.data[0]["id"]).execute()
            except Exception:
                pass

        # Cleanup old records (keep last 100)
        try:
            all_pings = client.table("keepalive_pings").select("id").order(
                "created_at", desc=True
            ).execute()
            if all_pings.data and len(all_pings.data) > 100:
                old_ids = [p["id"] for p in all_pings.data[100:]]
                for old_id in old_ids[:50]:  # Delete in small batches
                    client.table("keepalive_pings").delete().eq("id", old_id).execute()
        except Exception:
            pass

        _last_ping_time = now
        _total_pings += 1
        _consecutive_failures = 0
        record_success()

        _ping_history.append({
            "time": datetime.now(IST).isoformat(),
            "source": source,
            "latency_ms": round(latency, 1),
        })
        if len(_ping_history) > 20:
            _ping_history.pop(0)

        logger.info(f"[{MODULE_ID}] Ping OK ({source}) latency={latency:.0f}ms total={_total_pings}")
        return {
            "success": True,
            "latency_ms": round(latency, 1),
            "total_pings": _total_pings,
        }

    except Exception as e:
        _consecutive_failures += 1
        record_failure()
        logger.warning(f"[{MODULE_ID}] Ping FAILED ({source}): {e}")

        error_str = str(e)[:200]
        # If table doesn't exist, that's a setup issue, not a failure
        if "does not exist" in error_str or "42P01" in error_str:
            _last_ping_time = now  # Don't retry immediately
            return {"success": False, "reason": "Tables not created yet — run schema SQL"}

        return {"success": False, "reason": error_str}


# ============================================================
# LAYER 1: ASYNC BACKGROUND LOOP
# ============================================================

async def keepalive_loop(interval_hours: float = 12.0):
    """
    Background asyncio loop that pings Supabase every N hours.
    Adds random jitter (0-2h) to avoid predictable patterns.
    Runs forever — meant to be started as asyncio.create_task().
    """
    logger.info(f"[{MODULE_ID}] L1 keepalive loop started (interval={interval_hours}h)")

    # Initial delay (30-120 seconds) to let everything else start first
    await asyncio.sleep(30 + random.random() * 90)

    while True:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, _do_ping, "L1_loop"
            )
            if result.get("success") and not result.get("skipped"):
                logger.debug(f"[{MODULE_ID}] L1 ping done: {result}")
        except Exception as e:
            logger.debug(f"[{MODULE_ID}] L1 loop error: {e}")

        # Sleep with jitter
        jitter = random.random() * 7200  # 0-2h jitter
        sleep_sec = interval_hours * 3600 + jitter
        await asyncio.sleep(sleep_sec)


# ============================================================
# LAYER 2: SCHEDULER PING (called from scheduler.py)
# ============================================================

async def scheduler_ping() -> Dict[str, Any]:
    """Called by APScheduler every 8 hours."""
    return await asyncio.get_event_loop().run_in_executor(
        None, _do_ping, "L2_scheduler"
    )


# ============================================================
# LAYER 3: PIGGYBACK PING (called from keepalive.py)
# ============================================================

def piggyback_ping():
    """
    Called during Render self-ping cycle.
    Only actually pings if enough time has passed.
    """
    return _do_ping("L3_piggyback")


# ============================================================
# STATUS
# ============================================================

def get_keepalive_status() -> Dict[str, Any]:
    """Get keepalive statistics."""
    return {
        "total_pings": _total_pings,
        "consecutive_failures": _consecutive_failures,
        "hours_since_last_ping": round(max(
            (MIN_PING_INTERVAL - (time.time() - _last_ping_time)) / 3600, 0
        ), 1) if _last_ping_time else None,
        "last_ping_time": datetime.fromtimestamp(
            _last_ping_time, tz=IST
        ).isoformat() if _last_ping_time else None,
        "recent_pings": _ping_history[-5:],
    }
