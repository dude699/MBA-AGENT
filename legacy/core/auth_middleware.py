"""
============================================================
OPERATION FIRST MOVER v5.3 -- MINI-APP AUTH MIDDLEWARE
============================================================
Express-style middleware for protecting the Telegram Mini-App API.
Validates access codes and session tokens from the security module.

Endpoints added:
    POST /api/auth/login    -- Validate access code, return session token
    POST /api/auth/validate -- Validate session token
    POST /api/auth/logout   -- Invalidate session

Integration:
    - Import and register with the aiohttp web server in keepalive.py
    - Mini-app sends access code on first load
    - Receives session token for subsequent API calls
    - All protected endpoints check X-Session-Token header
============================================================
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from aiohttp import web
except ImportError:
    web = None

from core.security import get_security_manager, ADMIN_TELEGRAM_ID

MODULE_ID = "AUTH-MW"


# ============================================================
# API ROUTE HANDLERS
# ============================================================

async def handle_auth_login(request: web.Request) -> web.Response:
    """
    POST /api/auth/login
    Body: { "access_code": "abu46987291" }
    
    Returns: { "success": true, "session_token": "...", "user": {...} }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"},
            status=400
        )
    
    access_code = body.get('access_code', '').strip()
    if not access_code:
        return web.json_response(
            {"success": False, "error": "Access code required"},
            status=400
        )
    
    sec = get_security_manager()
    
    # Validate the access code
    user = sec.validate_access_code(access_code)
    if not user:
        # Log failed attempt
        sec._log_event('miniapp_login_fail', 0, f'Invalid code: {access_code[:4]}...')
        return web.json_response(
            {"success": False, "error": "Invalid or expired access code"},
            status=401
        )
    
    # Create session
    ip_address = request.remote or ""
    user_agent = request.headers.get('User-Agent', '')[:200]
    
    session_token = sec.create_miniapp_session(
        user['telegram_id'],
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    if not session_token:
        return web.json_response(
            {"success": False, "error": "Session creation failed"},
            status=500
        )
    
    sec._log_event(
        'miniapp_login', user['telegram_id'],
        f'Login from {ip_address}'
    )
    
    return web.json_response({
        "success": True,
        "session_token": session_token,
        "user": {
            "telegram_id": user['telegram_id'],
            "username": user['username'],
            "is_admin": bool(user.get('is_admin', False)),
        }
    })


async def handle_auth_validate(request: web.Request) -> web.Response:
    """
    POST /api/auth/validate
    Headers: X-Session-Token: <token>
    
    Returns: { "valid": true, "telegram_id": 1234 }
    """
    token = (
        request.headers.get('X-Session-Token', '') or
        request.headers.get('Authorization', '').replace('Bearer ', '')
    )
    
    if not token:
        return web.json_response(
            {"valid": False, "error": "No session token provided"},
            status=401
        )
    
    sec = get_security_manager()
    telegram_id = sec.validate_miniapp_session(token)
    
    if telegram_id is None:
        return web.json_response(
            {"valid": False, "error": "Invalid or expired session"},
            status=401
        )
    
    user = sec.get_user(telegram_id)
    return web.json_response({
        "valid": True,
        "telegram_id": telegram_id,
        "username": user.get('username', '') if user else '',
        "is_admin": bool(user.get('is_admin', False)) if user else False,
    })


async def handle_auth_logout(request: web.Request) -> web.Response:
    """
    POST /api/auth/logout
    Headers: X-Session-Token: <token>
    """
    token = (
        request.headers.get('X-Session-Token', '') or
        request.headers.get('Authorization', '').replace('Bearer ', '')
    )
    
    if token:
        sec = get_security_manager()
        sec._execute(
            "UPDATE miniapp_sessions SET is_active = 0 WHERE session_token = ?",
            (token,)
        )
    
    return web.json_response({"success": True, "message": "Logged out"})


async def handle_auth_status(request: web.Request) -> web.Response:
    """
    GET /api/auth/status
    Public endpoint returning auth system status (no secrets).
    """
    sec = get_security_manager()
    status = sec.get_security_status()
    
    return web.json_response({
        "auth_enabled": True,
        "active_users": status['active_users'],
        "active_sessions": status['active_sessions'],
    })


# ============================================================
# MIDDLEWARE FOR PROTECTING API ENDPOINTS
# ============================================================

def create_auth_middleware(protected_prefixes: list = None):
    """
    Create an aiohttp middleware that protects specified API paths.
    
    Usage:
        app = web.Application(middlewares=[create_auth_middleware(['/api/internships'])])
    """
    if protected_prefixes is None:
        protected_prefixes = ['/api/internships', '/api/batch', '/api/llm']
    
    # Paths that are always public
    public_paths = {
        '/', '/health', '/status', '/ping',
        '/api/auth/login', '/api/auth/validate', 
        '/api/auth/logout', '/api/auth/status',
        '/telegram-status',
    }
    
    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        path = request.path
        
        # Allow public paths
        if path in public_paths:
            return await handler(request)
        
        # Check if path needs protection
        needs_auth = any(path.startswith(prefix) for prefix in protected_prefixes)
        
        if not needs_auth:
            return await handler(request)
        
        # Validate session token
        token = (
            request.headers.get('X-Session-Token', '') or
            request.headers.get('Authorization', '').replace('Bearer ', '')
        )
        
        if not token:
            return web.json_response(
                {"error": "Authentication required", "code": "NO_TOKEN"},
                status=401
            )
        
        sec = get_security_manager()
        telegram_id = sec.validate_miniapp_session(token)
        
        if telegram_id is None:
            return web.json_response(
                {"error": "Invalid or expired session", "code": "INVALID_SESSION"},
                status=401
            )
        
        # Attach user info to request for downstream handlers
        request['telegram_id'] = telegram_id
        request['authenticated'] = True
        
        return await handler(request)
    
    return auth_middleware


# ============================================================
# ROUTE REGISTRATION
# ============================================================

def register_auth_routes(app):
    """Register auth API routes with an aiohttp application."""
    if web is None:
        logger.warning(f"[{MODULE_ID}] aiohttp not available, skipping route registration")
        return
    
    app.router.add_post('/api/auth/login', handle_auth_login)
    app.router.add_post('/api/auth/validate', handle_auth_validate)
    app.router.add_post('/api/auth/logout', handle_auth_logout)
    app.router.add_get('/api/auth/status', handle_auth_status)
    
    logger.info(f"[{MODULE_ID}] Auth routes registered: /api/auth/*")
