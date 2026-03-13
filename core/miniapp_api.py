"""
============================================================
OPERATION FIRST MOVER v5.4 -- MINI-APP API ENDPOINTS
============================================================
REST API endpoints for the InternHub Pro Telegram Mini App.
These endpoints replace the mock data layer in the frontend
with real data from the SQLite database.

Endpoints:
    GET  /api/internships         -- Paginated listing browser
    GET  /api/internships/:id     -- Single listing detail
    GET  /api/analytics           -- Dashboard analytics data
    POST /api/apply/:id           -- Mark listing as applied
    POST /api/llm/chat            -- AI chat (cover letter, advice)
    GET  /api/sources             -- Source health stats
    GET  /api/filters             -- Available filter options + counts

All endpoints require valid session (X-Session-Token header)
except /api/health-check which is public.
============================================================
"""

import json
import os
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from aiohttp import web
except ImportError:
    web = None

from core.config import IST

MODULE_ID = "MINIAPP-API"


# ============================================================
# HELPER: Extract session user from request
# ============================================================

def _get_user_id(request) -> Optional[int]:
    """Extract authenticated telegram_id from request (set by auth middleware)."""
    return request.get('telegram_id')


def _json_response(data: Any, status: int = 200) -> web.Response:
    """Create a JSON response with CORS headers for Mini App."""
    resp = web.json_response(data, status=status)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Session-Token, Authorization'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp


# ============================================================
# API HANDLERS
# ============================================================

async def handle_internships(request: web.Request) -> web.Response:
    """
    GET /api/internships?page=1&per_page=20&sort=ppo&category=marketing&source=internshala
                        &location=mumbai&min_stipend=5000&max_duration=3&search=digital

    Returns paginated internship listings from the real database.
    """
    try:
        from core.database import get_db
        db = get_db()

        # Parse query parameters
        page = int(request.query.get('page', '1'))
        per_page = min(int(request.query.get('per_page', '20')), 50)
        sort_by = request.query.get('sort', 'ppo')
        category = request.query.get('category', '') or None
        source = request.query.get('source', '') or None
        location = request.query.get('location', '') or None
        min_stipend = int(request.query.get('min_stipend', '0'))
        max_duration = int(request.query.get('max_duration', '6'))
        search = request.query.get('search', '') or None

        offset = (page - 1) * per_page

        # Use the management internships query (excludes sales/BD)
        listings, total = db.get_management_internships(
            limit=per_page,
            offset=offset,
            max_duration_months=max_duration,
            sort_by=sort_by,
            category=category,
            source=source,
            min_stipend=min_stipend,
            location=location,
        )

        # Transform to frontend-friendly format
        items = []
        for l in listings:
            items.append(_transform_listing(l))

        total_pages = max(1, (total + per_page - 1) // per_page)

        return _json_response({
            "success": True,
            "data": items,
            "meta": {
                "total": total,
                "page": page,
                "pageSize": per_page,
                "totalPages": total_pages,
                "hasMore": page < total_pages,
                "sort": sort_by,
                "filters": {
                    "category": category,
                    "source": source,
                    "location": location,
                    "minStipend": min_stipend,
                    "maxDuration": max_duration,
                    "search": search,
                },
            },
            "timestamp": datetime.now(IST).isoformat(),
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/internships error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_internship_detail(request: web.Request) -> web.Response:
    """
    GET /api/internships/:id

    Returns full listing detail by ID.
    """
    try:
        from core.database import get_db
        db = get_db()

        listing_id = request.match_info.get('id', '')
        try:
            lid = int(listing_id)
        except ValueError:
            return _json_response({"success": False, "error": "Invalid listing ID"}, status=400)

        listing = db.get_clean_listing_by_id(lid)
        if not listing:
            return _json_response({"success": False, "error": "Listing not found"}, status=404)

        item = _transform_listing(listing, detailed=True)
        return _json_response({"success": True, "data": item})

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/internships/:id error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_analytics(request: web.Request) -> web.Response:
    """
    GET /api/analytics

    Returns dashboard analytics data.
    """
    try:
        from core.database import get_db
        db = get_db()

        # Gather analytics
        source_counts = db.get_source_counts()
        category_counts = db.get_category_counts()

        # Application funnel
        try:
            stats = db.get_weekly_stats()
            funnel = stats.get('funnel', {})
        except Exception:
            funnel = {}

        total_listings = sum(source_counts.values()) if source_counts else 0

        # Source stats
        top_sources = []
        for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            top_sources.append({
                "source": src,
                "count": count,
                "applied": 0,
                "successRate": 0,
            })

        # Category stats
        top_categories = []
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            top_categories.append({
                "category": cat,
                "count": count,
                "avgStipend": 0,
            })

        return _json_response({
            "success": True,
            "data": {
                "totalListings": total_listings,
                "totalApplied": funnel.get('applied', 0),
                "totalShortlisted": funnel.get('shortlisted', 0),
                "totalRejected": funnel.get('rejected', 0),
                "totalOffers": funnel.get('offer', 0),
                "successRate": 0,
                "avgResponseTime": 0,
                "topSources": top_sources,
                "topCategories": top_categories,
                "applicationTimeline": [],
                "stipendDistribution": [],
                "weeklyActivity": [],
            },
            "timestamp": datetime.now(IST).isoformat(),
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/analytics error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_apply(request: web.Request) -> web.Response:
    """
    POST /api/apply/:id

    Mark a listing as applied.
    """
    try:
        from core.database import get_db, Outcome
        db = get_db()

        listing_id = request.match_info.get('id', '')
        try:
            lid = int(listing_id)
        except ValueError:
            return _json_response({"success": False, "error": "Invalid listing ID"}, status=400)

        listing = db.get_clean_listing_by_id(lid)
        if not listing:
            return _json_response({"success": False, "error": "Listing not found"}, status=404)

        outcome = Outcome(
            listing_id=lid,
            company_id=listing.get('company_id'),
            status='applied',
            ppo_score_at_apply=listing.get('ppo_score', 0),
        )
        db.insert_outcome(outcome)
        db.update_clean_listing_scores(lid, status='applied')

        return _json_response({
            "success": True,
            "data": {"status": "applied", "listing_id": lid},
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/apply error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_llm_chat(request: web.Request) -> web.Response:
    """
    POST /api/llm/chat
    Body: { "message": "...", "context": { "internshipIds": [...] } }

    AI-powered chat for cover letters, advice, comparisons.
    """
    try:
        body = await request.json()
    except Exception:
        return _json_response({"success": False, "error": "Invalid JSON"}, status=400)

    message = body.get('message', '')
    if not message:
        return _json_response({"success": False, "error": "Message required"}, status=400)

    try:
        from core.ai_router import get_router
        router = get_router()

        # Use a general-purpose AI call
        prompt = (
            f"You are InternHub Pro AI assistant, helping MBA students with internship applications.\n"
            f"User question: {message}\n\n"
            f"Provide helpful, actionable advice. Be concise but thorough.\n"
            f"If asked about cover letters, provide a template.\n"
            f"If asked about comparisons, analyze the key factors.\n"
            f"Format your response with markdown for readability."
        )

        response = router.quick_classify(prompt)
        if response and response.success:
            return _json_response({
                "success": True,
                "data": response.content,
            })
        else:
            # Fallback response
            return _json_response({
                "success": True,
                "data": (
                    "**Internship Application Tips:**\n\n"
                    "1. **Customize each application** to the company and role\n"
                    "2. **Apply within 48 hours** of posting for 3x higher response rate\n"
                    "3. **Focus on Tier-1 companies** for brand value (long-term ROI)\n"
                    "4. **Use /package [id]** in the bot for AI-generated application materials\n\n"
                    "Try asking me to help with a specific listing!"
                ),
            })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/llm/chat error: {e}")
        return _json_response({
            "success": True,
            "data": (
                "I'm having trouble connecting to the AI backend right now.\n\n"
                "**Quick Tips:**\n"
                "- Use /package [id] in the Telegram bot for full application packages\n"
                "- Use /cover [id] for AI cover letters\n"
                "- Use /ats [id] for ATS keyword analysis"
            ),
        })


async def handle_sources(request: web.Request) -> web.Response:
    """
    GET /api/sources

    Returns source health data.
    """
    try:
        from core.database import get_db
        db = get_db()

        source_counts = db.get_source_counts()
        raw_counts = db.get_raw_source_counts()

        sources = []
        all_sources = set(list(source_counts.keys()) + list(raw_counts.keys()))
        for src in sorted(all_sources):
            clean = source_counts.get(src, 0)
            raw = raw_counts.get(src, 0)
            sources.append({
                "source": src,
                "cleanCount": clean,
                "rawCount": raw,
                "healthy": clean > 0,
            })

        return _json_response({
            "success": True,
            "data": sources,
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/sources error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_filters(request: web.Request) -> web.Response:
    """
    GET /api/filters

    Returns available filter options with counts.
    """
    try:
        from core.database import get_db
        db = get_db()

        category_counts = db.get_category_counts()
        source_counts = db.get_source_counts()

        return _json_response({
            "success": True,
            "data": {
                "categories": category_counts,
                "sources": source_counts,
            },
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/filters error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_cors_preflight(request: web.Request) -> web.Response:
    """Handle CORS preflight OPTIONS requests."""
    return web.Response(
        status=204,
        headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, X-Session-Token, Authorization',
            'Access-Control-Max-Age': '3600',
        },
    )


# ============================================================
# STATIC FILE SERVING FOR MINI-APP
# ============================================================

# Cache the dist path — gets invalidated and re-checked if None
_cached_dist_path: Optional[str] = None


def _get_miniapp_dist_path() -> Optional[str]:
    """
    Find the mini-app dist directory. 
    Caches result after first successful find.
    Re-scans every time if not found (in case build completed after startup).
    """
    global _cached_dist_path
    
    # Return cached path if still valid
    if _cached_dist_path and os.path.isdir(_cached_dist_path) and os.path.isfile(os.path.join(_cached_dist_path, 'index.html')):
        return _cached_dist_path
    
    # Reset cache if invalid
    _cached_dist_path = None
    
    candidates = [
        # Relative to this file: core/miniapp_api.py -> project_root/mini-app/dist
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mini-app', 'dist'),
        # Relative to CWD
        os.path.join(os.getcwd(), 'mini-app', 'dist'),
        # Render's default project path
        '/opt/render/project/src/mini-app/dist',
        # Docker WORKDIR
        '/app/mini-app/dist',
        # Sandbox path
        '/home/user/webapp/mini-app/dist',
    ]
    # De-duplicate candidates (normpath)
    seen = set()
    unique_candidates = []
    for path in candidates:
        normed = os.path.normpath(path)
        if normed not in seen:
            seen.add(normed)
            unique_candidates.append(normed)
    
    for path in unique_candidates:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, 'index.html')):
            _cached_dist_path = path
            logger.info(f"[{MODULE_ID}] Found mini-app dist at: {path}")
            return path
    
    return None


def invalidate_dist_cache():
    """Call this after building the mini-app to force re-scan on next request."""
    global _cached_dist_path
    _cached_dist_path = None


async def handle_miniapp_static(request: web.Request) -> web.Response:
    """
    Serve static files from mini-app dist/ directory.
    This handles /app/assets/*, /app/favicon.svg, etc. DYNAMICALLY
    so it works even if dist/ was built after server startup.
    """
    import mimetypes
    
    req_path = request.match_info.get('path', '')
    
    # Security: prevent path traversal
    if '..' in req_path or req_path.startswith('/'):
        return web.Response(text="Forbidden", status=403)
    
    dist = _get_miniapp_dist_path()
    if not dist:
        return web.Response(text="Not Found", status=404)
    
    file_path = os.path.normpath(os.path.join(dist, req_path))
    
    # Security: ensure resolved path is within dist
    if not file_path.startswith(os.path.normpath(dist)):
        return web.Response(text="Forbidden", status=403)
    
    if not os.path.isfile(file_path):
        return web.Response(text="Not Found", status=404)
    
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = 'application/octet-stream'
    
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        
        resp = web.Response(body=content, content_type=content_type)
        # Cache static assets aggressively (they have hashed filenames)
        if '/assets/' in req_path:
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp
    except Exception as e:
        logger.error(f"[{MODULE_ID}] Error serving static file {file_path}: {e}")
        return web.Response(text="Internal Server Error", status=500)


async def handle_miniapp_index(request: web.Request) -> web.Response:
    """Serve the mini-app index.html for /app/ route."""
    dist = _get_miniapp_dist_path()
    if not dist:
        return web.Response(
            text=_get_not_built_page(),
            content_type='text/html',
            status=503,
        )
    
    index_path = os.path.join(dist, 'index.html')
    if not os.path.isfile(index_path):
        return web.Response(
            text=_get_not_built_page(),
            content_type='text/html',
            status=503,
        )
    
    try:
        with open(index_path, 'r') as f:
            html = f.read()
        return web.Response(text=html, content_type='text/html')
    except Exception as e:
        logger.error(f"[{MODULE_ID}] Error reading index.html: {e}")
        return web.Response(
            text=_get_not_built_page(),
            content_type='text/html',
            status=503,
        )


async def handle_miniapp_spa_catchall(request: web.Request) -> web.Response:
    """
    SPA catch-all: serve index.html for any /app/* path that isn't a static asset.
    This enables React Router client-side navigation.
    """
    path = request.match_info.get('path', '')
    
    # If the path looks like a static file (has extension), try serving it
    last_segment = path.split('/')[-1] if path else ''
    if '.' in last_segment:
        # Try to serve as static file first
        return await handle_miniapp_static(request)
    
    # Otherwise, serve index.html (React Router will handle the route)
    return await handle_miniapp_index(request)


def _get_not_built_page() -> str:
    """Return a user-friendly error page when mini-app isn't built."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>InternHub Pro — Loading</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #ffffff;
            color: #212529;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            text-align: center;
            max-width: 380px;
        }
        .icon { font-size: 64px; margin-bottom: 16px; }
        h1 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
        p { font-size: 14px; color: #868e96; line-height: 1.5; margin-bottom: 16px; }
        .retry-btn {
            display: inline-block;
            padding: 12px 24px;
            background: #1a1a2e;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
        }
        .retry-btn:hover { opacity: 0.9; }
        .hint { font-size: 12px; color: #adb5bd; margin-top: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🔨</div>
        <h1>Setting Up InternHub Pro</h1>
        <p>The app is being built for the first time. This usually takes 1-2 minutes after a fresh deploy.</p>
        <button class="retry-btn" onclick="location.reload()">Retry</button>
        <p class="hint">If this persists, use /jobs in the Telegram bot to browse internships.</p>
    </div>
    <script>
        try {
            const tg = window.Telegram?.WebApp;
            if (tg) {
                tg.ready();
                tg.expand();
            }
        } catch(e) {}
        // Auto-retry after 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>"""


# ============================================================
# LISTING TRANSFORMER
# ============================================================

def _transform_listing(listing: Dict, detailed: bool = False) -> Dict:
    """Transform a database listing dict to frontend-friendly format."""
    tier_map = {1: 'tier1', 2: 'tier1', 3: 'tier2', 4: 'tier3', 5: 'startup'}
    source_map = {
        'internshala': 'internshala', 'naukri': 'naukri', 'linkedin': 'linkedin',
        'indeed': 'indeed', 'iimjobs': 'iimjobs', 'glassdoor': 'glassdoor',
        'greenhouse': 'angellist', 'lever': 'angellist', 'wellfound': 'wellfound',
    }

    lid = listing.get('id', 0)
    stipend = listing.get('stipend_monthly', 0) or 0
    ppo_score = listing.get('ppo_score', 0) or 0
    ghost_score = listing.get('ghost_score', 0) or 0
    applicants = listing.get('applicants', 0) or 0
    duration = listing.get('duration_months', 0) or 0
    tier = listing.get('tier')
    source = listing.get('source', '')

    item = {
        "id": str(lid),
        "title": listing.get('title', 'Unknown'),
        "company": listing.get('company', 'Unknown'),
        "companyLogo": None,
        "companySize": "",
        "companyRating": 0,
        "source": source_map.get(source, source),
        "sourceUrl": listing.get('url', ''),
        "stipend": stipend,
        "stipendCurrency": "INR",
        "stipendType": "monthly" if stipend > 0 else "unpaid",
        "duration": duration,
        "durationUnit": "months",
        "location": listing.get('location', '') or 'Not specified',
        "locationType": "remote" if listing.get('is_wfh') else "onsite",
        "category": listing.get('category', '') or 'general',
        "skills": [],
        "description": listing.get('description_text', '') or '',
        "responsibilities": [],
        "requirements": [],
        "perks": [],
        "openings": 1,
        "applicants": applicants,
        "postedDate": listing.get('first_seen', datetime.now(IST).isoformat()),
        "deadline": listing.get('deadline', ''),
        "startDate": "",
        "isExpired": listing.get('status') == 'expired',
        "isPremium": listing.get('is_blue_ocean', False),
        "isVerified": True,
        "matchScore": min(100, int(ppo_score)),
        "ghostScore": int(ghost_score),
        "successRate": max(5, 100 - int(ghost_score)),
        "avgResponseDays": 5,
        "alreadyApplied": listing.get('status') == 'applied',
        "companyTier": tier_map.get(tier, 'startup') if tier else 'startup',
        "sector": listing.get('sector', ''),
        "tags": [
            listing.get('category', ''),
            listing.get('sector', ''),
        ],
        "lastUpdated": listing.get('last_seen', datetime.now(IST).isoformat()),
        "hash": f"{lid}-{listing.get('title', '')}-{listing.get('company', '')}",
    }

    # Add PPO-specific fields
    if listing.get('is_ppo'):
        item['tags'].append('PPO')
    if listing.get('is_blue_ocean'):
        item['tags'].append('Blue Ocean')
    if listing.get('is_wfh'):
        item['tags'].append('WFH')

    # Clean empty tags
    item['tags'] = [t for t in item['tags'] if t]

    return item


# ============================================================
# ROUTE REGISTRATION
# ============================================================

def register_miniapp_routes(app):
    """Register all mini-app API routes with an aiohttp application."""
    if web is None:
        logger.warning(f"[{MODULE_ID}] aiohttp not available, skipping route registration")
        return

    # CORS preflight for all /api/ paths
    app.router.add_route('OPTIONS', '/api/{tail:.*}', handle_cors_preflight)

    # Data API endpoints
    app.router.add_get('/api/internships', handle_internships)
    app.router.add_get('/api/internships/{id}', handle_internship_detail)
    app.router.add_get('/api/analytics', handle_analytics)
    app.router.add_post('/api/apply/{id}', handle_apply)
    app.router.add_post('/api/llm/chat', handle_llm_chat)
    app.router.add_get('/api/sources', handle_sources)
    app.router.add_get('/api/filters', handle_filters)

    # Mini-app: All static file serving is DYNAMIC (not add_static)
    # This way, even if dist/ is built AFTER server startup, files will be served.
    # The handle_miniapp_spa_catchall handles both static files and SPA routes.
    dist = _get_miniapp_dist_path()
    if dist:
        logger.info(f"[{MODULE_ID}] Mini-app dist found at: {dist}")
    else:
        logger.warning(f"[{MODULE_ID}] Mini-app dist/ not found at startup — will check dynamically on each request")

    # SPA: /app/ and /app -> serve index.html
    app.router.add_get('/app/', handle_miniapp_index)
    app.router.add_get('/app', handle_miniapp_index)
    # SPA catch-all: /app/{anything} -> serve static file or index.html
    app.router.add_get('/app/{path:.*}', handle_miniapp_spa_catchall)

    logger.info(f"[{MODULE_ID}] Mini-app API routes registered: /api/internships, /api/analytics, /api/apply, /api/llm/chat, /api/sources, /api/filters, /app/")
