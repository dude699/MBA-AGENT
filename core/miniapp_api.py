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
    Body: {
        "message": "...",
        "profile": "generalist|resume_builder|ats_checker|career_counselor",
        "context": { "internshipIds": [...], "clientJobCount": N, "hasLoadedJobs": bool },
        "history": [{"role":"user","content":"..."},...]
    }

    Resource-aware AI chat with specialist profiles and job database context.
    - Groq primary, Cerebras automatic fallback
    - Caches job context for 5 minutes to minimize DB calls
    - Anti-hallucination: only references real data from database
    - Self-aware of available resources before responding
    """
    try:
        body = await request.json()
    except Exception:
        return _json_response({"success": False, "error": "Invalid JSON"}, status=400)

    message = body.get('message', '')
    if not message:
        return _json_response({"success": False, "error": "Message required"}, status=400)

    profile = body.get('profile', 'generalist')
    history = body.get('history', [])
    context = body.get('context', {})
    client_job_count = context.get('clientJobCount', 0)
    has_loaded_jobs = context.get('hasLoadedJobs', False)

    # ---- Resource-aware job context with caching ----
    job_context = ""
    total_jobs = 0
    try:
        import time as _time

        # Simple in-memory cache for job context (5 min TTL)
        cache_key = '_llm_job_context_cache'
        cache_ts_key = '_llm_job_context_ts'
        cached_ctx = getattr(handle_llm_chat, cache_key, None)
        cached_ts = getattr(handle_llm_chat, cache_ts_key, 0)

        if cached_ctx and (_time.time() - cached_ts) < 300:
            job_context = cached_ctx['context']
            total_jobs = cached_ctx['total']
            logger.debug(f"[{MODULE_ID}] Using cached job context ({total_jobs} listings)")
        else:
            from core.database import get_db
            db = get_db()
            listings, total = db.get_management_internships(limit=10, offset=0, sort_by='ppo')
            total_jobs = total
            if listings:
                job_lines = []
                for j in listings[:8]:
                    title = j.get('title', 'N/A')
                    company = j.get('company', 'N/A')
                    stipend = j.get('stipend', 0)
                    location = j.get('location', 'N/A')
                    source = j.get('source', 'N/A')
                    duration = j.get('duration', 0)
                    category = j.get('category', 'N/A')
                    job_lines.append(
                        f"- {title} at {company} | INR {stipend}/mo | {location} | {duration}mo | {category} | via {source}"
                    )
                job_context = (
                    f"\n\n--- CURRENT JOB DATABASE ({total} total verified listings) ---\n"
                    f"Top listings by relevance:\n" + "\n".join(job_lines)
                )
            else:
                job_context = "\n\n--- JOB DATABASE: Currently empty. No listings available. ---"

            # Cache result
            setattr(handle_llm_chat, cache_key, {'context': job_context, 'total': total_jobs})
            setattr(handle_llm_chat, cache_ts_key, _time.time())

    except Exception as e:
        logger.debug(f"[{MODULE_ID}] Job context fetch skipped: {e}")
        job_context = "\n\n--- JOB DATABASE: Temporarily unavailable ---"

    # ---- Profile-specific system prompts with anti-hallucination rules ----
    ANTI_HALLUCINATION = (
        "\n\nCRITICAL RULES (NEVER VIOLATE):\n"
        "- ONLY reference jobs/companies that appear in the JOB DATABASE section above.\n"
        "- If the database is empty or unavailable, clearly state that no listings are currently loaded.\n"
        "- NEVER invent job titles, company names, stipend amounts, or statistics.\n"
        "- If you don't have data to answer a question, say so honestly and suggest the user "
        "refresh their listings or use Telegram bot commands.\n"
        "- Keep responses concise. Use bullet points and short paragraphs.\n"
        "- Do NOT use markdown heading syntax (# or ##). Use bold text (**text**) for emphasis instead.\n"
        f"- The user's app currently shows {client_job_count} listings on their device.\n"
        f"- The database has {total_jobs} total verified listings.\n"
    )
    SYSTEM_PROMPTS = {
        "generalist": (
            "You are InternHub Pro AI -- a senior career counselor and student advisor "
            "specializing in MBA internship placements in India. You have 15+ years of experience "
            "placing students at Tier-1 companies (McKinsey, Goldman Sachs, Google, HUL, P&G, etc.) "
            "and deep knowledge of the Indian internship ecosystem.\n\n"
            "CORE EXPERTISE:\n"
            "- Internship search strategy and application prioritization\n"
            "- Company culture analysis and fit assessment\n"
            "- Stipend negotiation and offer evaluation\n"
            "- Career path planning for MBA students (finance, consulting, marketing, ops, tech)\n"
            "- Platform-specific tips (Internshala, LinkedIn, Naukri, Unstop, etc.)\n"
            "- Understanding of PPO conversion rates and ghost posting detection\n\n"
            "BEHAVIORAL GUIDELINES:\n"
            "- Be direct, actionable, and data-driven. No fluff.\n"
            "- Reference specific companies, programs, and timelines when relevant.\n"
            "- If asked about a specific listing, analyze its strengths and red flags.\n"
            "- Proactively suggest better alternatives when appropriate.\n"
            "- Use bullet points and markdown for clarity.\n"
            "- Keep responses concise (150-300 words) unless detailed analysis is requested.\n"
            "- Always consider the user's time constraints (MBA programs are demanding).\n"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
        "resume_builder": (
            "You are ResumeForge AI -- an elite resume and application materials specialist "
            "with deep expertise in MBA-level professional documents. You have personally reviewed "
            "5,000+ resumes and helped candidates land roles at BCG, Bain, JP Morgan, Amazon, "
            "Flipkart, Swiggy, Razorpay, and other top firms.\n\n"
            "CORE EXPERTISE:\n"
            "- Resume optimization for ATS (Applicant Tracking Systems)\n"
            "- Cover letter generation tailored to specific roles and companies\n"
            "- LinkedIn profile optimization for recruiter visibility\n"
            "- Statement of Purpose (SOP) and motivation letter writing\n"
            "- Action verb optimization and quantification of achievements\n"
            "- Industry-specific resume formatting (consulting, finance, tech, FMCG)\n\n"
            "DOCUMENT STANDARDS:\n"
            "- Harvard Business School resume format as baseline\n"
            "- STAR method for all bullet points (Situation, Task, Action, Result)\n"
            "- Quantify every achievement (revenue, users, efficiency, %, $)\n"
            "- Tailor keywords to match JD requirements (ATS optimization)\n"
            "- One page max for internship resumes\n\n"
            "BEHAVIORAL GUIDELINES:\n"
            "- When generating a cover letter, ask for the role details if not provided.\n"
            "- Always provide before/after examples when editing resume bullets.\n"
            "- Flag weak verbs and vague statements immediately.\n"
            "- Suggest role-specific keywords for ATS optimization.\n"
            "- Format output in clean markdown with clear sections.\n"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
        "ats_checker": (
            "You are ATScan Pro -- an advanced Applicant Tracking System analyzer and "
            "optimization engine. You reverse-engineer how Workday, Greenhouse, Lever, "
            "iCIMS, Taleo, and other ATS platforms parse and rank resumes.\n\n"
            "CORE EXPERTISE:\n"
            "- ATS compatibility scoring (0-100) with detailed breakdown\n"
            "- Keyword density analysis and gap identification\n"
            "- Format compliance checking (fonts, headers, sections, file type)\n"
            "- Industry-specific keyword databases\n"
            "- Section ordering optimization for maximum ATS score\n"
            "- Hidden ATS requirements that most candidates miss\n\n"
            "ANALYSIS FRAMEWORK:\n"
            "When analyzing a resume or application:\n"
            "1. **Keyword Match Score**: Compare resume keywords vs. JD requirements\n"
            "2. **Format Score**: Check ATS-friendly formatting\n"
            "3. **Section Score**: Verify required sections exist\n"
            "4. **Quantification Score**: Measure data-driven achievements\n"
            "5. **Action Verb Score**: Evaluate verb strength and variety\n"
            "6. **Overall ATS Score**: Weighted composite (0-100)\n\n"
            "BEHAVIORAL GUIDELINES:\n"
            "- Always provide a numerical score with detailed breakdown.\n"
            "- List exact missing keywords from the job description.\n"
            "- Suggest specific replacement phrases (not vague advice).\n"
            "- Warn about ATS-breaking formatting issues.\n"
            "- Provide the optimized version alongside the analysis.\n"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
        "career_counselor": (
            "You are PathFinder AI -- a specialized career strategist for MBA students in India, "
            "with deep domain knowledge of campus placements, summer internships, and lateral moves. "
            "You understand the nuances of IIM/ISB/XLRI/FMS/MDI placement processes and have "
            "advised 1,000+ students on career pivots and specialization choices.\n\n"
            "CORE EXPERTISE:\n"
            "- MBA specialization selection (Finance, Marketing, Ops, HR, Strategy, Analytics)\n"
            "- Internship-to-PPO conversion strategies (industry-specific conversion rates)\n"
            "- Salary and stipend benchmarking across sectors and tiers\n"
            "- Day Zero / Day One / Day Two placement strategy\n"
            "- Career pivot strategies (Engineering to Consulting, etc.)\n"
            "- Industry trend analysis (which sectors are hiring, compensation trends)\n"
            "- Short-listing strategy based on student profile, prior experience, and goals\n\n"
            "ADVISORY FRAMEWORK:\n"
            "1. Understand the student's background (prior experience, MBA year, college tier)\n"
            "2. Assess career goals (short-term vs long-term)\n"
            "3. Map target companies and roles to the student's profile\n"
            "4. Create a prioritized application strategy with timelines\n"
            "5. Provide preparation guidance (case interviews, GDs, technical rounds)\n\n"
            "BEHAVIORAL GUIDELINES:\n"
            "- Ask clarifying questions when background info is missing.\n"
            "- Provide honest, realistic advice (don't sugarcoat weak profiles).\n"
            "- Reference specific company names, stipend ranges, and timelines.\n"
            "- Consider ROI (brand value + stipend + PPO probability).\n"
            "- Use data from the job database to make recommendations concrete.\n"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
    }

    system_prompt = SYSTEM_PROMPTS.get(profile, SYSTEM_PROMPTS["generalist"])

    # ---- Build conversation with history (minimize tokens) ----
    conversation_context = ""
    if history and len(history) > 0:
        recent = history[-4:]  # Last 2 exchanges only (save tokens)
        for msg in recent:
            role = msg.get('role', 'user')
            content = msg.get('content', '')[:300]  # Truncate to save tokens
            conversation_context += f"\n[{role.upper()}]: {content}"
        conversation_context = f"\n\n--- RECENT CONTEXT ---{conversation_context}\n---\n"

    full_prompt = f"{conversation_context}\nUser: {message}"

    # ---- Token budget: adjust based on profile ----
    token_budget = {
        'generalist': 800,
        'resume_builder': 1200,  # Needs more for cover letters
        'ats_checker': 1000,
        'career_counselor': 900,
    }.get(profile, 800)

    try:
        from core.ai_router import get_router
        router = get_router()

        response = router.call(
            task='cover_letter',  # Use heavy-analysis task routing (Groq primary)
            prompt=full_prompt,
            system_prompt=system_prompt,
            max_tokens=token_budget,
            temperature=0.65,
            use_cache=True,  # Enable cache for repeated similar queries
        )

        if response and response.success:
            return _json_response({
                "success": True,
                "data": response.content,
                "meta": {
                    "model": response.model or "unknown",
                    "provider": response.provider or "unknown",
                    "profile": profile,
                    "tokens": response.tokens_used or 0,
                    "latency_ms": response.latency_ms or 0,
                    "fallback": getattr(response, 'fallback_used', False),
                },
            })
        else:
            return _json_response({
                "success": True,
                "data": (
                    "I'm processing your request but the AI engine is momentarily busy. "
                    "Please try again in a few seconds.\n\n"
                    "**Meanwhile, you can:**\n"
                    "- Use /package [id] in Telegram for application materials\n"
                    "- Use /cover [id] for AI-generated cover letters\n"
                    "- Use /ats [id] for ATS keyword analysis"
                ),
                "meta": {"profile": profile, "model": "fallback"},
            })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/llm/chat error: {e}\n{traceback.format_exc()}")
        return _json_response({
            "success": True,
            "data": (
                "I encountered a temporary connection issue with the AI engine.\n\n"
                "**Quick alternatives:**\n"
                "- Use /package [id] in the Telegram bot for full application packages\n"
                "- Use /cover [id] for AI cover letters\n"
                "- Use /ats [id] for ATS keyword analysis\n\n"
                "*Tip: The Telegram bot has direct access to the AI engine and may work better.*"
            ),
            "meta": {"profile": profile, "model": "error"},
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
# SUPABASE LISTING TRANSFORMER
# ============================================================

def _transform_supabase_listing(row: Dict) -> Dict:
    """Transform a Supabase job row to frontend-friendly Internship format."""
    import json as _json

    def _parse_json_list(val):
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            try:
                parsed = _json.loads(val)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return [v.strip() for v in val.split(",") if v.strip()] if val else []
        return []

    lid = row.get("id", 0)
    stipend = row.get("stipend", 0) or 0
    match_score = row.get("match_score", 50) or 50
    ghost_score = row.get("ghost_score", 0) or 0
    applicants = row.get("applicants", 0) or 0
    duration = row.get("duration", 0) or 0

    return {
        "id": f"sb_{lid}",
        "title": row.get("title", "Unknown"),
        "company": row.get("company", "Unknown"),
        "companyLogo": row.get("company_logo") or None,
        "companySize": row.get("company_size", ""),
        "companyRating": row.get("company_rating", 0) or 0,
        "source": row.get("source", ""),
        "sourceUrl": row.get("source_url", ""),
        "stipend": stipend,
        "stipendCurrency": row.get("stipend_currency", "INR") or "INR",
        "stipendType": row.get("stipend_type", "monthly") if stipend > 0 else "unpaid",
        "duration": duration,
        "durationUnit": row.get("duration_unit", "months"),
        "location": row.get("location", "") or "Not specified",
        "locationType": row.get("location_type", "onsite"),
        "category": row.get("category", "") or "general",
        "skills": _parse_json_list(row.get("skills", "[]")),
        "description": row.get("description", ""),
        "responsibilities": _parse_json_list(row.get("responsibilities", "[]")),
        "requirements": _parse_json_list(row.get("requirements", "[]")),
        "perks": _parse_json_list(row.get("perks", "[]")),
        "openings": row.get("openings", 1) or 1,
        "applicants": applicants,
        "postedDate": row.get("posted_date", row.get("created_at", "")),
        "deadline": row.get("deadline", ""),
        "startDate": row.get("start_date", ""),
        "isExpired": bool(row.get("is_expired", False)),
        "isPremium": bool(row.get("is_premium", False)),
        "isVerified": bool(row.get("is_verified", True)),
        "matchScore": min(100, int(match_score)),
        "ghostScore": int(ghost_score),
        "successRate": max(5, 100 - int(ghost_score)),
        "avgResponseDays": 5,
        "alreadyApplied": bool(row.get("applied", False)),
        "appliedDate": row.get("applied_at", ""),
        "applicationStatus": row.get("application_status", "not_applied"),
        "companyTier": row.get("company_tier", "startup"),
        "sector": row.get("sector", ""),
        "tags": _parse_json_list(row.get("tags", "[]")),
        "lastUpdated": row.get("updated_at", row.get("created_at", "")),
        "hash": row.get("content_hash", f"sb-{lid}"),
    }


# ============================================================
# SUPABASE API HANDLERS
# ============================================================

async def handle_supabase_latest_jobs(request: web.Request) -> web.Response:
    """GET /api/supabase/latest-jobs — Current scraping session jobs."""
    try:
        from core.supabase_client import is_operational
        if not is_operational():
            return _json_response({"success": False, "error": "Supabase not available", "data": []}, 503)

        from core.supabase_db import SupabaseJobDB

        page = int(request.query.get("page", "1"))
        per_page = min(int(request.query.get("per_page", "20")), 50)
        source = request.query.get("source", "")
        category = request.query.get("category", "")
        location = request.query.get("location", "")
        search = request.query.get("search", "")
        sort_by = request.query.get("sort", "scraped_at")

        sort_map = {
            "ppo": "ppo_score", "stipend": "stipend", "date": "scraped_at",
            "applicants": "applicants", "duration": "duration",
        }
        sort_col = sort_map.get(sort_by, "scraped_at")
        offset = (page - 1) * per_page

        jobs, total = SupabaseJobDB.get_latest_jobs(
            limit=per_page, offset=offset,
            source=source, category=category,
            location=location, search=search,
            sort_by=sort_col,
        )

        items = [_transform_supabase_listing(j) for j in jobs]
        return _json_response({
            "success": True,
            "data": items,
            "meta": {
                "total": total, "page": page, "pageSize": per_page,
                "hasMore": offset + per_page < total, "table": "latest_jobs",
            },
            "timestamp": datetime.now(IST).isoformat(),
        })
    except Exception as e:
        logger.error(f"[{MODULE_ID}] handle_supabase_latest_jobs error: {e}")
        return _json_response({"success": False, "error": str(e)[:200], "data": []}, 500)


async def handle_supabase_all_jobs(request: web.Request) -> web.Response:
    """GET /api/supabase/all-jobs — Complete job archive."""
    try:
        from core.supabase_client import is_operational
        if not is_operational():
            return _json_response({"success": False, "error": "Supabase not available", "data": []}, 503)

        from core.supabase_db import SupabaseJobDB

        page = int(request.query.get("page", "1"))
        per_page = min(int(request.query.get("per_page", "20")), 50)
        source = request.query.get("source", "")
        category = request.query.get("category", "")
        location = request.query.get("location", "")
        search = request.query.get("search", "")
        applied_only = request.query.get("applied", "").lower() in ("true", "1")
        include_expired = request.query.get("include_expired", "").lower() in ("true", "1")
        sort_by = request.query.get("sort", "created_at")

        sort_map = {
            "ppo": "ppo_score", "stipend": "stipend", "date": "created_at",
            "applicants": "applicants", "duration": "duration", "applied": "applied_at",
        }
        sort_col = sort_map.get(sort_by, "created_at")
        offset = (page - 1) * per_page

        jobs, total = SupabaseJobDB.get_all_jobs(
            limit=per_page, offset=offset,
            source=source, category=category,
            location=location, search=search,
            applied_only=applied_only,
            exclude_expired=not include_expired,
            sort_by=sort_col,
        )

        items = [_transform_supabase_listing(j) for j in jobs]
        return _json_response({
            "success": True,
            "data": items,
            "meta": {
                "total": total, "page": page, "pageSize": per_page,
                "hasMore": offset + per_page < total, "table": "all_jobs",
            },
            "timestamp": datetime.now(IST).isoformat(),
        })
    except Exception as e:
        logger.error(f"[{MODULE_ID}] handle_supabase_all_jobs error: {e}")
        return _json_response({"success": False, "error": str(e)[:200], "data": []}, 500)


async def handle_supabase_apply(request: web.Request) -> web.Response:
    """POST /api/supabase/apply/{id} — Mark a Supabase job as applied."""
    try:
        from core.supabase_client import is_operational
        if not is_operational():
            return _json_response({"success": False, "error": "Supabase not available"}, 503)

        from core.supabase_db import SupabaseJobDB

        raw_id = request.match_info.get("id", "")
        job_id = int(raw_id.replace("sb_", "")) if raw_id.replace("sb_", "").isdigit() else 0

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        notes = str(body.get("notes", ""))[:1000]

        if not job_id:
            return _json_response({"success": False, "error": "Invalid job ID"}, 400)

        # Try to find the job to get content_hash
        job = SupabaseJobDB.get_job_by_id(job_id, "all_jobs")
        if not job:
            job = SupabaseJobDB.get_job_by_id(job_id, "latest_jobs")

        if job:
            success = SupabaseJobDB.mark_applied(
                content_hash=job["content_hash"],
                status="applied", notes=notes,
            )
        else:
            success = SupabaseJobDB.mark_applied(
                job_id=job_id, status="applied", notes=notes,
            )

        return _json_response({
            "success": success,
            "data": {"status": "applied" if success else "not_applied"},
            "timestamp": datetime.now(IST).isoformat(),
        })
    except Exception as e:
        logger.error(f"[{MODULE_ID}] handle_supabase_apply error: {e}")
        return _json_response({"success": False, "error": str(e)[:200]}, 500)


async def handle_supabase_stats(request: web.Request) -> web.Response:
    """GET /api/supabase/stats — Database statistics."""
    try:
        from core.supabase_client import is_operational
        if not is_operational():
            return _json_response({"success": False, "error": "Supabase not available"}, 503)

        from core.supabase_db import SupabaseJobDB
        stats = SupabaseJobDB.get_stats()
        return _json_response({
            "success": True, "data": stats,
            "timestamp": datetime.now(IST).isoformat(),
        })
    except Exception as e:
        logger.error(f"[{MODULE_ID}] handle_supabase_stats error: {e}")
        return _json_response({"success": False, "error": str(e)[:200]}, 500)


async def handle_supabase_job_detail(request: web.Request) -> web.Response:
    """GET /api/supabase/job/{id} — Single job detail from Supabase."""
    try:
        from core.supabase_client import is_operational
        if not is_operational():
            return _json_response({"success": False, "error": "Supabase not available"}, 503)

        from core.supabase_db import SupabaseJobDB

        raw_id = request.match_info.get("id", "")
        job_id = int(raw_id.replace("sb_", "")) if raw_id.replace("sb_", "").isdigit() else 0
        if not job_id:
            return _json_response({"success": False, "error": "Invalid job ID"}, 400)

        job = SupabaseJobDB.get_job_by_id(job_id, "all_jobs")
        if not job:
            job = SupabaseJobDB.get_job_by_id(job_id, "latest_jobs")
        if not job:
            return _json_response({"success": False, "error": "Job not found"}, 404)

        return _json_response({
            "success": True,
            "data": _transform_supabase_listing(job),
            "timestamp": datetime.now(IST).isoformat(),
        })
    except Exception as e:
        logger.error(f"[{MODULE_ID}] handle_supabase_job_detail error: {e}")
        return _json_response({"success": False, "error": str(e)[:200]}, 500)


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

    # Supabase persistent database API endpoints
    app.router.add_get('/api/supabase/latest-jobs', handle_supabase_latest_jobs)
    app.router.add_get('/api/supabase/all-jobs', handle_supabase_all_jobs)
    app.router.add_get('/api/supabase/job/{id}', handle_supabase_job_detail)
    app.router.add_post('/api/supabase/apply/{id}', handle_supabase_apply)
    app.router.add_get('/api/supabase/stats', handle_supabase_stats)

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
