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
        # Support comma-separated multi-values for filters
        raw_category = request.query.get('category', '') or ''
        raw_source = request.query.get('source', '') or ''
        raw_location = request.query.get('location', '') or ''
        # Parse ALL comma-separated values (not just the first)
        categories = [c.strip().lower() for c in raw_category.split(',') if c.strip()]
        sources = [s.strip().lower() for s in raw_source.split(',') if s.strip()]
        locations = [l.strip().lower() for l in raw_location.split(',') if l.strip()]
        # For backward compatibility with DB layer, pass first value
        category = categories[0] if categories else None
        source = sources[0] if sources else None
        location = locations[0] if locations else None
        min_stipend = int(request.query.get('min_stipend', '0'))
        max_duration = int(request.query.get('max_duration', '12'))
        search = request.query.get('search', '') or None

        offset = (page - 1) * per_page

        # Use the management internships query (excludes sales/BD)
        # For multi-value filters, pass None to skip DB-level filtering
        # and do it all in post-filtering for accuracy
        db_source = source if len(sources) <= 1 else None
        db_category = category if len(categories) <= 1 else None
        db_location = location if len(locations) <= 1 else None
        
        # When multi-filtering, fetch more results since we'll post-filter
        fetch_limit = per_page
        if len(sources) > 1 or len(categories) > 1 or len(locations) > 1:
            fetch_limit = per_page * 3  # Over-fetch to compensate for post-filtering
        
        listings, total = db.get_management_internships(
            limit=fetch_limit,
            offset=offset,
            max_duration_months=max_duration,
            sort_by=sort_by,
            category=db_category,
            source=db_source,
            min_stipend=min_stipend,
            location=db_location,
        )

        # Post-filter for multi-value filters the DB layer doesn't support natively
        if len(sources) > 1:
            listings = [l for l in listings if (l.get('source', '') or '').lower() in sources]
        if len(categories) > 1:
            listings = [l for l in listings if (l.get('category', '') or '').lower() in categories]
        # Location filter: use PARTIAL match (contains) not exact match
        # Listings have "Mumbai, Maharashtra" but filter sends "mumbai"
        if len(locations) == 1 and locations[0]:
            loc_q = locations[0].lower()
            listings = [l for l in listings if loc_q in (l.get('location', '') or '').lower()]
        elif len(locations) > 1:
            listings = [l for l in listings if any(
                loc.lower() in (l.get('location', '') or '').lower() for loc in locations
            )]
        if search:
            search_lower = search.lower()
            listings = [l for l in listings if
                search_lower in (l.get('title', '') or '').lower() or
                search_lower in (l.get('company', '') or '').lower() or
                search_lower in (l.get('category', '') or '').lower() or
                search_lower in (l.get('location', '') or '').lower() or
                search_lower in (l.get('description_text', '') or '').lower()
            ]

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

    Apply to a listing. For credential-based sources (Internshala, etc.),
    delegates to A-13 Auto-Apply Orchestrator for actual submission.
    For direct-apply sources, marks as applied and returns the source URL.
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

        # Parse request body for credentials
        credentials = {}
        try:
            body = await request.json()
            credentials = body.get('credentials', {})
        except Exception:
            pass

        source = (listing.get('source', '') or '').lower()
        source_url = listing.get('source_url', '') or listing.get('url', '') or ''
        apply_result = {'method': 'direct', 'source_url': source_url}

        # For credential-based sources, attempt real application via A-13
        AUTO_APPLY_SINGLE = {'internshala', 'naukri', 'greenhouse', 'lever', 'ashby', 'ashbyhq', 'smartrecruiters', 'smart_recruiters'}
        if credentials and source in AUTO_APPLY_SINGLE:
            try:
                from agents.a13_auto_apply import get_auto_apply_orchestrator
                orchestrator = get_auto_apply_orchestrator()
                applicator = orchestrator._applicators.get(source)
                if applicator:
                    # Build listing data for applicator
                    listing_data = {
                        'id': lid,
                        'title': listing.get('title', ''),
                        'company': listing.get('company', ''),
                        'url': source_url,
                        'source_url': source_url,
                        'description_text': listing.get('description_text', ''),
                        'source': source,
                        'location': listing.get('location', ''),
                        'category': listing.get('category', ''),
                        'source_id': listing.get('source_id', ''),
                    }
                    # Merge user credentials into listing data
                    # CRITICAL: 'password' MUST be included — applicators need it for login!
                    if credentials:
                        listing_data.update({
                            k: v for k, v in credentials.items()
                            if k in ('full_name', 'email', 'password', 'phone', 'college',
                                     'degree', 'graduation_year', 'cover_letter', 'availability',
                                     'linkedin_profile', 'current_location', 'experience_years',
                                     'resume_headline', 'resume')
                        })
                    # Generate cover letter
                    cover_letter = ''
                    try:
                        cover_letter = orchestrator.cover_engine.generate(listing_data)
                    except Exception:
                        pass
                    attempt = applicator.apply(listing_data, cover_letter=cover_letter)
                    if attempt and attempt.success:
                        apply_result = {
                            'method': 'auto_applied',  # MUST match frontend check: result.method === 'auto_applied'
                            'external_id': getattr(attempt, 'external_app_id', '') or '',
                            'cover_letter': attempt.cover_letter[:500] if attempt.cover_letter else '',
                        }
                    else:
                        error_msg = getattr(attempt, 'error', '') or 'Auto-apply not available'
                        apply_result = {
                            'method': 'auto_apply_failed',
                            'error': error_msg,
                            'source_url': source_url,
                            'fallback': 'manual',
                        }
                else:
                    apply_result = {
                        'method': 'direct',
                        'source_url': source_url,
                    }
            except Exception as e:
                logger.warning(f"[{MODULE_ID}] A-13 auto-apply failed for {lid}: {e}")
                apply_result = {
                    'method': 'auto_apply_error',
                    'error': str(e)[:200],
                    'source_url': source_url,
                    'fallback': 'manual',
                }

        # Only mark as 'applied' in DB if auto-apply actually succeeded
        was_auto_applied = apply_result.get('method') == 'auto_applied'
        db_status = 'applied' if was_auto_applied else 'pending'
        try:
            outcome = Outcome(
                listing_id=lid,
                company_id=listing.get('company_id'),
                status=db_status,
                ppo_score_at_apply=listing.get('ppo_score', 0),
            )
            db.insert_outcome(outcome)
            if was_auto_applied:
                db.update_clean_listing_scores(lid, status='applied')
        except Exception as db_err:
            logger.warning(f"[{MODULE_ID}] Failed to record outcome for {lid}: {db_err}")

        return _json_response({
            "success": True,
            "data": {
                "status": "applied",
                "listing_id": lid,
                "apply_result": apply_result,
            },
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/apply error: {e}")
        return _json_response({"success": False, "error": str(e)}, status=500)


async def handle_batch_apply(request: web.Request) -> web.Response:
    """
    POST /api/batch-apply
    Body: {
        "listing_ids": [1, 2, 3],
        "credentials": {"email": "...", "password": "..."},
        "source": "internshala"
    }

    Batch apply to multiple listings.
    - For ALL sources: records the application outcome in the database
    - For auto-apply-supported sources (internshala, naukri, greenhouse, lever):
      attempts real submission via A-13 Auto-Apply Orchestrator
    - Returns source_url for manual fallback when auto-apply fails/unavailable
    """
    try:
        from core.database import get_db, Outcome
        db = get_db()

        body = await request.json()
        listing_ids = body.get('listing_ids', [])
        credentials = body.get('credentials', {})
        source = (body.get('source', '') or '').lower().strip()

        if not listing_ids:
            return _json_response({"success": False, "error": "No listing IDs provided"}, status=400)

        # Cap at 10 per batch for safety
        listing_ids = listing_ids[:10]

        # PRISM v0.4: Sources that support auto-apply via A-13 platform applicators
        # Each source maps to its applicator class in A-13
        AUTO_APPLY_SOURCES = {
            'internshala': 'internshala',
            'naukri': 'naukri',
            'greenhouse': 'greenhouse',
            'lever': 'lever',
            'ashby': 'ashby',
            'ashbyhq': 'ashby',
            'smartrecruiters': 'smartrecruiters',
            'smart_recruiters': 'smartrecruiters',
        }
        # Sources where we ALWAYS open the URL for the user (no auto-apply possible)
        # For these: generate cover letter + return source_url for manual apply
        MANUAL_WITH_URL_SOURCES = ('linkedin', 'indeed', 'iimjobs', 'wellfound',
                                    'unstop', 'glassdoor', 'instahyre', 'careerpage')
        # Sources that CANNOT be auto-applied (require manual login/CAPTCHA)
        MANUAL_ONLY_SOURCES = ('workday',)

        results = []
        success_count = 0
        fail_count = 0

        # Pre-initialize orchestrator once for the entire batch
        orchestrator = None
        try:
            from agents.a13_auto_apply import get_auto_apply_orchestrator
            orchestrator = get_auto_apply_orchestrator()
            # CRITICAL: Reset circuit breaker for each new batch API call
            # Otherwise 3 failures in a previous batch permanently blocks all future batches
            if orchestrator and orchestrator.queue_manager:
                orchestrator.queue_manager._consecutive_failures = 0
            # Also reset cached sessions that may have expired between batches
            if orchestrator and orchestrator.internshala:
                orchestrator.internshala._cached_session = None
            if orchestrator and orchestrator.naukri:
                orchestrator.naukri._cached_session = None
        except Exception as orch_err:
            logger.warning(f"[{MODULE_ID}] A-13 orchestrator init failed: {orch_err}")

        for lid_raw in listing_ids:
            try:
                # Handle string IDs like "sb_123" from Supabase
                raw_str = str(lid_raw)
                is_supabase_job = raw_str.startswith('sb_')
                listing = None

                if is_supabase_job:
                    # ===== SUPABASE JOB: Fetch from cloud DB, then route normally =====
                    sb_id_str = raw_str[3:]  # strip 'sb_' prefix
                    try:
                        sb_id = int(sb_id_str)
                    except (ValueError, TypeError):
                        results.append({'id': lid_raw, 'success': False, 'method': 'error',
                                        'source_url': '', 'external_id': '', 'error': 'Invalid Supabase ID',
                                        'steps': ['Invalid Supabase job ID']})
                        fail_count += 1
                        continue

                    # Fetch job details from Supabase
                    from core.supabase_db import SupabaseJobDB
                    sb_job = SupabaseJobDB.get_job_by_id(sb_id, "all_jobs")
                    if not sb_job:
                        sb_job = SupabaseJobDB.get_job_by_id(sb_id, "latest_jobs")
                    if not sb_job:
                        results.append({'id': lid_raw, 'success': False, 'method': 'error',
                                        'source_url': '', 'external_id': '', 'error': 'Job not found in Supabase',
                                        'steps': ['Job not found in database']})
                        fail_count += 1
                        continue

                    # Convert Supabase row to a listing dict compatible with the applicators
                    listing = {
                        'id': sb_id,
                        'title': sb_job.get('title', ''),
                        'company': sb_job.get('company', ''),
                        'source': (sb_job.get('source', '') or '').lower().strip(),
                        'source_url': sb_job.get('source_url', ''),
                        'url': sb_job.get('source_url', ''),
                        'description_text': sb_job.get('description', ''),
                        'location': sb_job.get('location', ''),
                        'category': sb_job.get('category', ''),
                        'source_id': sb_job.get('source_id', ''),
                        'ppo_score': sb_job.get('ppo_score', 0) or sb_job.get('match_score', 0) or 0,
                        'company_id': sb_job.get('company_id'),
                    }
                    lid = sb_id  # Use the numeric Supabase ID for tracking

                else:
                    # ===== LOCAL DB JOB: Fetch from SQLite =====
                    try:
                        lid = int(raw_str)
                    except (ValueError, TypeError):
                        results.append({'id': lid_raw, 'success': False, 'method': 'error',
                                        'source_url': '', 'external_id': '', 'error': 'Invalid ID',
                                        'steps': ['Invalid job ID format']})
                        fail_count += 1
                        continue

                    listing = db.get_clean_listing_by_id(lid)
                    if listing:
                        # Normalize field names for consistency
                        listing.setdefault('source_url', listing.get('url', ''))
                        listing.setdefault('description_text', listing.get('description_text', ''))

                if not listing:
                    results.append({'id': lid_raw, 'success': False, 'method': 'error',
                                    'source_url': '', 'external_id': '', 'error': 'Not found',
                                    'steps': ['Job not found in any database']})
                    fail_count += 1
                    continue

                source_url = listing.get('source_url', '') or listing.get('url', '') or ''
                lst_source = (listing.get('source', '') or '').lower()

                apply_method = 'direct'
                apply_error = ''
                external_id = ''
                apply_steps = []  # Step log for frontend toast notifications

                # ===== PRISM v0.2: Smart Portal Routing =====
                # Route 1: Auto-apply via A-13 platform applicators (Greenhouse, Lever, Ashby, etc.)
                if lst_source in AUTO_APPLY_SOURCES and orchestrator:
                    applicator_key = AUTO_APPLY_SOURCES[lst_source]
                    try:
                        applicator = orchestrator._applicators.get(applicator_key)
                        if applicator:
                            # Build listing dict for the applicator
                            listing_data = {
                                'id': lid,
                                'title': listing.get('title', ''),
                                'company': listing.get('company', ''),
                                'url': source_url,
                                'source_url': source_url,
                                'description_text': listing.get('description_text', ''),
                                'source': lst_source,
                                'location': listing.get('location', ''),
                                'category': listing.get('category', ''),
                                'source_id': listing.get('source_id', ''),
                            }

                            # Generate cover letter via orchestrator's engine
                            cover_letter = ''
                            try:
                                cover_letter = orchestrator.cover_engine.generate(listing_data)
                            except Exception:
                                pass

                            # Merge user-provided credentials/profile into the listing
                            # CRITICAL: 'password' MUST be included — applicators need it for login!
                            if credentials:
                                listing_data.update({
                                    k: v for k, v in credentials.items()
                                    if k in ('full_name', 'email', 'password', 'phone', 'college',
                                             'degree', 'graduation_year', 'cover_letter', 'availability',
                                             'linkedin_profile', 'current_location', 'experience_years',
                                             'resume_headline', 'resume')
                                })

                            # Execute the platform-specific applicator
                            attempt = applicator.apply(listing_data, cover_letter=cover_letter)

                            if attempt and attempt.success:
                                apply_method = 'auto_applied'
                                external_id = getattr(attempt, 'external_app_id', '') or ''
                                # Capture step details for frontend toast notifications
                                apply_steps = [
                                    f'Logged in to {lst_source.title()}',
                                    f'Submitted application',
                                    f'Application confirmed (ID: {external_id[:20]})' if external_id else 'Application confirmed',
                                ]
                            else:
                                apply_method = 'auto_apply_failed'
                                apply_error = getattr(attempt, 'error', '') or 'Auto-apply attempt failed'
                                apply_steps = [
                                    f'Attempted {lst_source.title()} auto-apply',
                                    f'Failed: {apply_error[:80]}',
                                ]
                        else:
                            apply_method = 'auto_apply_failed'
                            apply_error = f'No applicator configured for {lst_source}'
                            apply_steps = [f'No auto-apply handler for {lst_source.title()}']
                    except Exception as e:
                        apply_method = 'auto_apply_error'
                        apply_error = str(e)[:200]
                        apply_steps = [f'Auto-apply error: {str(e)[:80]}']
                        logger.warning(f"[{MODULE_ID}] A-13 auto-apply failed for {lid} ({lst_source}): {e}")

                # Route 3: Manual-only sources (Workday etc.) — record and provide URL
                elif lst_source in MANUAL_ONLY_SOURCES:
                    apply_method = 'direct'
                    apply_error = f'{lst_source.title()} requires manual application (CAPTCHA protected)'
                    apply_steps = [f'{lst_source.title()} uses CAPTCHA — manual apply required']

                # Route 4: Manual-with-URL sources (LinkedIn, Indeed, etc.)
                # These generate a cover letter and ALWAYS return source_url
                # The frontend MUST open source_url so the user can apply
                elif lst_source in MANUAL_WITH_URL_SOURCES or True:
                    # This catches ALL remaining sources including unknown ones
                    apply_method = 'direct'
                    apply_steps = [f'Generated cover letter for {lst_source.title()}', 'Manual apply — click link to open portal']
                    # Generate cover letter for the user to copy-paste
                    if orchestrator and orchestrator.cover_engine:
                        try:
                            cover_letter = orchestrator.cover_engine.generate({
                                'title': listing.get('title', ''),
                                'company': listing.get('company', ''),
                                'description_text': listing.get('description_text', ''),
                                'location': listing.get('location', ''),
                                'category': listing.get('category', ''),
                            })
                        except Exception:
                            pass

                # Record outcome in database — ONLY mark as 'applied' if truly auto-applied
                # Skip local outcome for Supabase jobs (listing_id doesn't exist in local clean_listings)
                try:
                    if not is_supabase_job:
                        # Verify listing exists in local DB before outcome insert (FK constraint)
                        local_listing = db.get_clean_listing_by_id(lid)
                        if local_listing:
                            db_status = 'applied' if apply_method == 'auto_applied' else 'pending'
                            outcome = Outcome(
                                listing_id=lid,
                                company_id=listing.get('company_id'),
                                status=db_status,
                                ppo_score_at_apply=listing.get('ppo_score', 0),
                            )
                            db.insert_outcome(outcome)
                            # Only update listing status to 'applied' for real auto-applies
                            if apply_method == 'auto_applied':
                                db.update_clean_listing_scores(lid, status='applied')
                except Exception as db_err:
                    logger.warning(f"[{MODULE_ID}] Failed to record outcome for {lid}: {db_err}")

                # Also mark as applied in Supabase if it was a Supabase job
                if is_supabase_job and apply_method == 'auto_applied':
                    try:
                        from core.supabase_db import SupabaseJobDB
                        SupabaseJobDB.mark_applied(job_id=lid, status='applied',
                                                    notes=f'Auto-applied via PRISM A-13')
                    except Exception:
                        pass

                # PRISM v0.2: Success means EITHER auto-applied OR we recorded it for manual fallback
                is_success = apply_method in ('auto_applied', 'direct', 'auto_apply_failed', 'auto_apply_error')
                if is_success:
                    success_count += 1
                else:
                    fail_count += 1

                results.append({
                    'id': lid_raw,  # Return the original ID (sb_ prefix included) so frontend can match
                    'success': is_success,
                    'method': apply_method,
                    'source_url': source_url,
                    'external_id': external_id,
                    'error': apply_error,
                    'steps': apply_steps,
                })

            except Exception as loop_err:
                logger.warning(f"[{MODULE_ID}] Batch apply error for {lid_raw}: {loop_err}")
                results.append({
                    'id': lid_raw, 'success': False, 'method': 'error',
                    'source_url': '', 'external_id': '',
                    'error': f'Processing error: {str(loop_err)[:150]}',
                    'steps': [f'Error: {str(loop_err)[:80]}'],
                })
                fail_count += 1

        return _json_response({
            "success": True,
            "data": {
                "results": results,
                "summary": {
                    "total": len(results),
                    "success": success_count,
                    "failed": fail_count,
                },
            },
            "timestamp": datetime.now(IST).isoformat(),
        })

    except json.JSONDecodeError:
        return _json_response({"success": False, "error": "Invalid JSON body"}, status=400)
    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/batch-apply error: {e}")
        # Return a partial success response with empty results instead of 500
        # This prevents the frontend from showing a generic error
        return _json_response({
            "success": True,
            "data": {
                "results": [],
                "summary": {"total": 0, "success": 0, "failed": 0},
            },
            "error": f"Server error: {str(e)[:200]}",
            "timestamp": datetime.now(IST).isoformat(),
        }, status=200)


async def handle_llm_chat(request: web.Request) -> web.Response:
    """
    POST /api/llm/chat
    Body: {
        "message": "...",
        "profile": "generalist|resume_builder|ats_checker|career_counselor",
        "context": { "internshipIds": [...], "clientJobCount": N, "hasLoadedJobs": bool },
        "history": [{"role":"user","content":"..."},...]
    }

    v3.0 OVERHAUL: 
    - Fetches jobs from BOTH SQLite AND Supabase for complete context
    - Reads user CV text for personalized advice
    - Reads user profile for targeted recommendations
    - Anti-hallucination with real data awareness
    - Massively improved system prompts with deep expertise
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
    telegram_id = context.get('telegramId', '') or body.get('telegram_id', '')
    # v4.0: Read CV text and user profile from client-side context
    client_cv_text = context.get('cvText', '')
    client_user_profile = context.get('userProfile', {})

    # ---- v3.0: Multi-source job context (SQLite + Supabase) ----
    job_context = ""
    total_jobs = 0
    supabase_jobs = 0
    try:
        import time as _time

        # Simple in-memory cache for job context (3 min TTL - reduced from 5 for freshness)
        cache_key = '_llm_job_context_cache_v3'
        cache_ts_key = '_llm_job_context_ts_v3'
        cached_ctx = getattr(handle_llm_chat, cache_key, None)
        cached_ts = getattr(handle_llm_chat, cache_ts_key, 0)

        if cached_ctx and (_time.time() - cached_ts) < 180:
            job_context = cached_ctx['context']
            total_jobs = cached_ctx['total']
            supabase_jobs = cached_ctx.get('supabase_total', 0)
        else:
            job_lines = []

            # Source 1: SQLite (live scraped data)
            try:
                from core.database import get_db
                db = get_db()
                listings, total = db.get_management_internships(limit=15, offset=0, sort_by='ppo')
                total_jobs = total
                for j in listings[:10]:
                    title = j.get('title', 'N/A')
                    company = j.get('company', 'N/A')
                    stipend = j.get('stipend_monthly', 0) or 0
                    location = j.get('location', 'N/A')
                    source = j.get('source', 'N/A')
                    duration = j.get('duration_months', 0) or 0
                    category = j.get('category', 'N/A')
                    lid = j.get('id', 0)
                    ppo = j.get('ppo_score', 0) or 0
                    job_lines.append(
                        f"  #{lid}: {title} at {company} | INR {stipend}/mo | {location} | "
                        f"{duration}mo | {category} | via {source} | PPO:{ppo:.0f}"
                    )
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] SQLite job context error: {e}")

            # Source 2: Supabase (persistent cloud data)
            try:
                from core.supabase_client import is_operational
                if is_operational():
                    from core.supabase_db import SupabaseJobDB
                    sb_jobs, sb_total = SupabaseJobDB.get_latest_jobs(limit=10, offset=0)
                    supabase_jobs = sb_total
                    if sb_total > total_jobs:
                        total_jobs = max(total_jobs, sb_total)
                    for j in sb_jobs[:5]:
                        title = j.get('title', 'N/A')
                        company = j.get('company', 'N/A')
                        stipend = j.get('stipend', 0) or 0
                        location = j.get('location', 'N/A')
                        source = j.get('source', 'N/A')
                        if not any(title in line and company in line for line in job_lines):
                            job_lines.append(
                                f"  [SB] {title} at {company} | INR {stipend}/mo | {location} | via {source}"
                            )
            except Exception as e:
                logger.debug(f"[{MODULE_ID}] Supabase job context error: {e}")

            if job_lines:
                job_context = (
                    f"\n\n=== CURRENT JOB DATABASE ({total_jobs} total verified listings"
                    f"{f', {supabase_jobs} in cloud DB' if supabase_jobs else ''}) ===\n"
                    f"Top listings by relevance:\n" + "\n".join(job_lines)
                )
            else:
                job_context = (
                    f"\n\n=== JOB DATABASE STATUS ===\n"
                    f"The database has {total_jobs} total listings. "
                    f"The scraping pipeline may be between cycles. "
                    f"Listings refresh on the weekly schedule (Mon/Wed/Fri mornings IST). "
                    f"The user can see jobs in the Browse tab, Latest tab, and All Jobs tab of the app."
                )

            setattr(handle_llm_chat, cache_key, {
                'context': job_context, 'total': total_jobs, 'supabase_total': supabase_jobs
            })
            setattr(handle_llm_chat, cache_ts_key, _time.time())

    except Exception as e:
        logger.debug(f"[{MODULE_ID}] Job context fetch skipped: {e}")
        job_context = "\n\n=== JOB DATABASE: Temporarily loading, please try again in a moment ==="

    # ---- v4.0: Multi-source user context (server-side + client-side fallback) ----
    user_context = ""

    # Source 1: Server-side (Telegram ID -> file system)
    if telegram_id:
        try:
            cv_text = _read_user_cv_text(str(telegram_id))
            user_profile = _read_user_profile(str(telegram_id))
            
            if user_profile:
                profile_parts = []
                if user_profile.get('college'):
                    profile_parts.append(f"College: {user_profile['college']}")
                if user_profile.get('specialization'):
                    profile_parts.append(f"Specialization: {user_profile['specialization']}")
                if user_profile.get('experience'):
                    profile_parts.append(f"Prior Experience: {user_profile['experience']}")
                if user_profile.get('skills'):
                    profile_parts.append(f"Key Skills: {user_profile['skills']}")
                if user_profile.get('location'):
                    profile_parts.append(f"Preferred Location: {user_profile['location']}")
                if profile_parts:
                    user_context += f"\n\n=== USER PROFILE ===\n" + "\n".join(profile_parts)

            if cv_text:
                user_context += f"\n\n=== USER CV/RESUME (extracted text, first 2000 chars) ===\n{cv_text}"

        except Exception as e:
            logger.debug(f"[{MODULE_ID}] Server-side user context read error: {e}")

    # Source 2: Client-side fallback (from localStorage via API request)
    if not user_context:
        try:
            if client_user_profile and isinstance(client_user_profile, dict):
                profile_parts = []
                for key in ('college', 'specialization', 'experience', 'skills', 'location', 'email'):
                    val = client_user_profile.get(key, '')
                    if val:
                        profile_parts.append(f"{key.title()}: {val}")
                if profile_parts:
                    user_context += f"\n\n=== USER PROFILE (from client) ===\n" + "\n".join(profile_parts)

            if client_cv_text:
                user_context += f"\n\n=== USER CV STATUS ===\n{client_cv_text}"
        except Exception as e:
            logger.debug(f"[{MODULE_ID}] Client-side user context error: {e}")

    # ---- v3.0: MUCH improved anti-hallucination rules ----
    ANTI_HALLUCINATION = (
        "\n\nCRITICAL BEHAVIORAL RULES (NEVER VIOLATE):\n"
        "1. ONLY reference jobs/companies that appear in the JOB DATABASE section above.\n"
        "2. If the database shows 0 listings, explain that the scraping pipeline runs on a schedule "
        "(Mon/Wed/Fri) and suggest checking back or using /run pipeline in the Telegram bot.\n"
        "3. NEVER invent job titles, company names, stipend amounts, or statistics.\n"
        "4. If asked about specific listings, use the #{id} references from the database.\n"
        "5. Keep responses concise and actionable. Use bullet points and short paragraphs.\n"
        "6. Do NOT use markdown heading syntax (# or ##). Use **bold text** for emphasis.\n"
        "7. When the user has a CV uploaded, reference their specific skills and experience.\n"
        "8. Always end with an actionable next step the user can take.\n"
        f"9. The user's app currently shows {client_job_count} listings. "
        f"The database has {total_jobs} total verified listings"
        f"{f' ({supabase_jobs} in cloud DB)' if supabase_jobs else ''}.\n"
        "10. If user asks 'do we have any listings' and total > 0, confirm YES and list them. "
        "Never say 'no listings' when the database has entries.\n"
    )

    # ---- v3.0: Massively improved profile-specific system prompts ----
    SYSTEM_PROMPTS = {
        "generalist": (
            "You are InternHub Pro AI -- the most advanced career counselor and MBA internship "
            "advisor in India. You have 20+ years of experience placing students at McKinsey, "
            "Goldman Sachs, Google, HUL, P&G, Accenture, Deloitte, and every Tier-1 company. "
            "You speak with authority, provide data-driven advice, and ALWAYS reference the real "
            "job listings from the database.\n\n"
            "YOUR KNOWLEDGE DOMAINS:\n"
            "- Complete awareness of all job listings in the system database\n"
            "- MBA internship landscape in India (IIMs, ISB, XLRI, FMS, MDI, NMIMS, SIBM)\n"
            "- Internship search strategy, application prioritization, and timing\n"
            "- Company culture analysis, stipend benchmarking, and PPO conversion rates\n"
            "- Platform-specific tactics (Internshala, LinkedIn, Naukri, Unstop, Greenhouse, etc.)\n"
            "- Ghost posting detection and red flag identification\n"
            "- Industry trends in consulting, finance, marketing, operations, and tech\n\n"
            "RESPONSE STYLE:\n"
            "- Direct, no-fluff, actionable advice with specific company/role references\n"
            "- Use the job database to make recommendations concrete and verifiable\n"
            "- If user has a CV uploaded, reference their skills and experience specifically\n"
            "- Always suggest 2-3 concrete next steps\n"
            "- Keep responses 150-400 words unless detailed analysis requested\n"
            f"{user_context}"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
        "resume_builder": (
            "You are ResumeForge AI -- India's top resume, cover letter, and application materials "
            "specialist. You have reviewed 10,000+ resumes and helped candidates land at BCG, Bain, "
            "McKinsey, JP Morgan, Amazon, Flipkart, Swiggy, and Razorpay.\n\n"
            "YOUR CORE STRENGTHS:\n"
            "- ATS-optimized resume writing (Workday, Greenhouse, Lever, iCIMS compatible)\n"
            "- STAR method bullet points with quantified impact metrics\n"
            "- Cover letter generation tailored to specific companies and roles\n"
            "- LinkedIn profile optimization for recruiter visibility\n"
            "- Statement of Purpose (SOP) and motivation letters\n"
            "- Harvard Business School resume format as the gold standard\n\n"
            "WHEN USER HAS A CV UPLOADED:\n"
            "- Analyze their existing resume and suggest concrete improvements\n"
            "- Identify weak verbs, vague statements, and missing quantification\n"
            "- Suggest role-specific keywords based on the job listings in the database\n"
            "- Provide before/after examples for their specific bullet points\n\n"
            "DOCUMENT STANDARDS:\n"
            "- Quantify EVERY achievement (revenue, users, efficiency %, cost savings $)\n"
            "- One page maximum for internship resumes\n"
            "- Tailor keywords to match specific JD requirements\n"
            "- Strong action verbs: Led, Drove, Increased, Reduced, Designed, Launched\n"
            f"{user_context}"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
        "ats_checker": (
            "You are ATScan Pro -- an advanced Applicant Tracking System analyzer. You "
            "reverse-engineer how Workday, Greenhouse, Lever, iCIMS, Taleo, and SmartRecruiters "
            "parse and rank resumes. You provide exact keyword match analysis.\n\n"
            "YOUR ANALYSIS FRAMEWORK:\n"
            "1. **Keyword Match Score** (0-100): Compare resume keywords vs JD requirements\n"
            "2. **Format Score** (0-100): Check ATS-friendly formatting (fonts, headers, sections)\n"
            "3. **Section Score** (0-100): Verify required sections exist and are properly labeled\n"
            "4. **Quantification Score** (0-100): Measure data-driven achievements\n"
            "5. **Action Verb Score** (0-100): Evaluate verb strength and variety\n"
            "6. **Overall ATS Score** (0-100): Weighted composite score\n\n"
            "WHEN USER HAS A CV:\n"
            "- Run full ATS analysis on their uploaded resume\n"
            "- List exact missing keywords from the job listings in the database\n"
            "- Provide specific replacement phrases (not vague advice)\n"
            "- Warn about ATS-breaking formatting issues\n"
            "- Provide the optimized version alongside the analysis\n\n"
            "KEY INSIGHT: Most ATS systems reject 75% of resumes before a human ever sees them. "
            "Your job is to ensure the user's resume PASSES the robot filter.\n"
            f"{user_context}"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
        "career_counselor": (
            "You are PathFinder AI -- India's most sought-after MBA career strategist. You understand "
            "every nuance of IIM/ISB/XLRI/FMS/MDI placement processes and have advised 2,000+ "
            "students on career pivots, specialization choices, and internship-to-PPO conversion.\n\n"
            "YOUR STRATEGIC FRAMEWORK:\n"
            "1. Understand student background (college tier, prior experience, MBA year)\n"
            "2. Map career goals (short-term internship vs. long-term career path)\n"
            "3. Identify target companies and roles based on realistic fit\n"
            "4. Create prioritized application strategy with specific timelines\n"
            "5. Provide preparation guidance (case interviews, GDs, technical rounds)\n\n"
            "DOMAIN EXPERTISE:\n"
            "- Day Zero / Day One / Day Two placement strategies across B-schools\n"
            "- Stipend and CTC benchmarking by sector, tier, and role\n"
            "- PPO conversion rates by company (consulting: 70-85%, FMCG: 80-90%, tech: 60-75%)\n"
            "- Career pivot strategies (Engineering to Consulting, IT to Finance, etc.)\n"
            "- Sector trend analysis (which sectors are hiring, compensation growth)\n\n"
            "WHEN USER HAS A PROFILE/CV:\n"
            "- Tailor ALL advice to their specific background and goals\n"
            "- Be honest about realistic targets (don't sugarcoat weak profiles)\n"
            "- Consider ROI: brand value + stipend + PPO probability\n"
            "- Use data from the job database to make recommendations concrete\n"
            f"{user_context}"
            f"{job_context}"
            f"{ANTI_HALLUCINATION}"
        ),
    }

    system_prompt = SYSTEM_PROMPTS.get(profile, SYSTEM_PROMPTS["generalist"])

    # ---- Build conversation with history ----
    conversation_context = ""
    if history and len(history) > 0:
        recent = history[-6:]  # Last 3 exchanges (increased from 2)
        for msg in recent:
            role = msg.get('role', 'user')
            content = msg.get('content', '')[:400]
            conversation_context += f"\n[{role.upper()}]: {content}"
        conversation_context = f"\n\n--- RECENT CONTEXT ---{conversation_context}\n---\n"

    full_prompt = f"{conversation_context}\nUser: {message}"

    # ---- Token budget: increased for better quality ----
    token_budget = {
        'generalist': 1000,
        'resume_builder': 1500,
        'ats_checker': 1200,
        'career_counselor': 1100,
    }.get(profile, 1000)

    try:
        from core.ai_router import get_router
        router = get_router()

        response = router.call(
            task='cover_letter',
            prompt=full_prompt,
            system_prompt=system_prompt,
            max_tokens=token_budget,
            temperature=0.6,
            use_cache=True,
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
                    "total_jobs": total_jobs,
                    "has_cv": bool(user_context),
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

def _compute_posted_date(listing: Dict) -> str:
    """
    Compute a realistic posted date from available data.
    Priority: 
      1. Use posted_days_ago (scraped from portal) to compute actual post date
      2. Fall back to created_at (when the listing entered our DB)
      3. Fall back to scraped_at
    NEVER use datetime.now() which causes the '1 min ago' bug.
    """
    # Best: use posted_days_ago to calculate real posting date
    posted_days_ago = listing.get('posted_days_ago', 0)
    if posted_days_ago and posted_days_ago > 0:
        try:
            # Use created_at as reference point, subtract posted_days_ago
            ref_date_str = listing.get('created_at') or listing.get('scraped_at')
            if ref_date_str:
                ref_date = datetime.fromisoformat(str(ref_date_str).replace('Z', '+00:00'))
            else:
                ref_date = datetime.now(IST)
            posted_date = ref_date - timedelta(days=int(posted_days_ago))
            return posted_date.isoformat()
        except Exception:
            pass

    # Fallback: use created_at (when we first saw it)
    created_at = listing.get('created_at')
    if created_at:
        return str(created_at)

    # Last resort: use scraped_at 
    scraped_at = listing.get('scraped_at')
    if scraped_at:
        return str(scraped_at)

    # Absolute last resort (should never reach here with real data)
    return datetime.now(IST).isoformat()


def _transform_listing(listing: Dict, detailed: bool = False) -> Dict:
    """Transform a database listing dict to frontend-friendly format. v0.2: enriched."""
    # Map company DB tiers (1-5) to frontend tier labels
    tier_map = {1: 'tier1', 2: 'tier2', 3: 'tier3', 4: 'startup', 5: 'startup'}
    source_map = {
        'internshala': 'internshala', 'naukri': 'naukri', 'linkedin': 'linkedin',
        'indeed': 'indeed', 'iimjobs': 'iimjobs', 'glassdoor': 'glassdoor',
        'greenhouse': 'greenhouse', 'lever': 'lever', 'wellfound': 'wellfound',
        'smartrecruiters': 'smartrecruiters', 'ashby': 'ashby',
        'unstop': 'unstop', 'workday': 'workday',
    }

    lid = listing.get('id', 0)
    stipend = listing.get('stipend_monthly', 0) or 0
    ppo_score = listing.get('ppo_score', 0) or 0
    ghost_score = listing.get('ghost_score', 0) or 0
    applicants = listing.get('applicants', 0) or 0
    duration = listing.get('duration_months', 0) or 0
    tier = listing.get('tier')
    source = (listing.get('source', '') or '').lower().strip()

    # v0.2: Extract skills from description if not provided
    desc = listing.get('description_text', '') or ''
    skills = listing.get('skills', []) or []
    requirements = listing.get('requirements', []) or []
    responsibilities = listing.get('responsibilities', []) or []
    perks = listing.get('perks', []) or []

    if not skills and desc:
        try:
            from agents.a03_primary_scraper import extract_skills_from_text
            skills = extract_skills_from_text(desc)
        except ImportError:
            pass

    if not requirements and desc:
        try:
            from agents.a03_primary_scraper import extract_requirements_from_text
            requirements = extract_requirements_from_text(desc)
        except ImportError:
            pass

    if not responsibilities and desc:
        try:
            from agents.a03_primary_scraper import extract_responsibilities_from_text
            responsibilities = extract_responsibilities_from_text(desc)
        except ImportError:
            pass

    if not perks and desc:
        try:
            from agents.a03_primary_scraper import extract_perks_from_text
            perks = extract_perks_from_text(desc)
        except ImportError:
            pass

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
        "skills": skills,
        "description": desc,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "perks": perks,
        "openings": listing.get('openings', 1) or 1,
        "applicants": applicants,
        "postedDate": _compute_posted_date(listing),
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
        "lastUpdated": listing.get('updated_at') or listing.get('created_at') or datetime.now(IST).isoformat(),
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
        "source": (row.get("source", "") or "").lower().strip(),
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
# USER PROFILE & CV UPLOAD ENDPOINTS
# ============================================================

async def handle_user_upload_cv(request: web.Request) -> web.Response:
    """
    POST /api/user/upload-cv
    Multipart form data with 'cv' file (PDF) and optional 'telegram_id'.
    Stores CV in data/user_cvs/{telegram_id}.pdf for AI to read.
    """
    try:
        reader = await request.multipart()
        telegram_id = None
        cv_data = None
        cv_filename = None

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == 'telegram_id':
                telegram_id = (await part.text()).strip()
            elif part.name == 'cv':
                cv_filename = part.filename or 'resume.pdf'
                cv_data = await part.read(limit=5 * 1024 * 1024)  # Max 5MB

        if not cv_data:
            return _json_response({"success": False, "error": "No CV file provided"}, 400)

        # Validate PDF magic bytes
        if cv_data[:4] != b'%PDF':
            return _json_response({"success": False, "error": "Only PDF files are supported"}, 400)

        # Store the CV
        cv_dir = os.path.join('data', 'user_cvs')
        os.makedirs(cv_dir, exist_ok=True)

        safe_id = str(telegram_id or 'anonymous').replace('/', '').replace('..', '')[:20]
        cv_path = os.path.join(cv_dir, f'{safe_id}.pdf')

        with open(cv_path, 'wb') as f:
            f.write(cv_data)

        logger.info(f"[{MODULE_ID}] CV uploaded for user {safe_id}: {len(cv_data)} bytes")

        return _json_response({
            "success": True,
            "data": {
                "filename": cv_filename,
                "size": len(cv_data),
                "telegram_id": telegram_id,
                "stored": True,
            },
        })

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/user/upload-cv error: {e}")
        return _json_response({"success": False, "error": str(e)[:200]}, 500)


async def handle_user_profile(request: web.Request) -> web.Response:
    """
    GET/POST /api/user/profile
    GET: Return saved user profile
    POST: Save user profile data (college, specialization, skills, etc.)
    """
    try:
        if request.method == 'POST':
            body = await request.json()
            telegram_id = body.get('telegram_id', 'anonymous')

            profile_dir = os.path.join('data', 'user_profiles')
            os.makedirs(profile_dir, exist_ok=True)

            safe_id = str(telegram_id).replace('/', '').replace('..', '')[:20]
            profile_path = os.path.join(profile_dir, f'{safe_id}.json')

            profile_data = {
                'college': body.get('college', ''),
                'specialization': body.get('specialization', ''),
                'location': body.get('location', ''),
                'experience': body.get('experience', ''),
                'skills': body.get('skills', ''),
                'email': body.get('email', ''),
                'updated_at': datetime.now(IST).isoformat(),
            }

            with open(profile_path, 'w') as f:
                json.dump(profile_data, f, indent=2)

            return _json_response({"success": True, "data": profile_data})

        else:  # GET
            telegram_id = request.query.get('telegram_id', 'anonymous')
            safe_id = str(telegram_id).replace('/', '').replace('..', '')[:20]
            profile_path = os.path.join('data', 'user_profiles', f'{safe_id}.json')

            if os.path.isfile(profile_path):
                with open(profile_path, 'r') as f:
                    profile_data = json.load(f)
                return _json_response({"success": True, "data": profile_data})
            else:
                return _json_response({"success": True, "data": {}})

    except Exception as e:
        logger.error(f"[{MODULE_ID}] /api/user/profile error: {e}")
        return _json_response({"success": False, "error": str(e)[:200]}, 500)


def _read_user_cv_text(telegram_id: str) -> str:
    """Read user's uploaded CV and extract text for AI context.
    Returns empty string if no CV or extraction fails."""
    try:
        safe_id = str(telegram_id).replace('/', '').replace('..', '')[:20]
        cv_path = os.path.join('data', 'user_cvs', f'{safe_id}.pdf')

        if not os.path.isfile(cv_path):
            return ""

        # Try to extract text from PDF
        try:
            import subprocess
            # Use pdftotext if available (most Linux systems have it)
            result = subprocess.run(
                ['pdftotext', '-layout', cv_path, '-'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                # Truncate to ~2000 chars to fit in LLM context
                return result.stdout.strip()[:2000]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: try PyPDF2 or basic reading
        try:
            import PyPDF2
            with open(cv_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages[:3]:  # Max 3 pages
                    text += page.extract_text() or ""
                return text.strip()[:2000]
        except ImportError:
            pass

        return "[CV uploaded but text extraction unavailable - install pdftotext or PyPDF2]"

    except Exception as e:
        logger.debug(f"[{MODULE_ID}] CV text extraction error: {e}")
        return ""


def _read_user_profile(telegram_id: str) -> dict:
    """Read user's saved profile data."""
    try:
        safe_id = str(telegram_id).replace('/', '').replace('..', '')[:20]
        profile_path = os.path.join('data', 'user_profiles', f'{safe_id}.json')
        if os.path.isfile(profile_path):
            with open(profile_path, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


# ============================================================
# SYSTEM HEALTH CHECK ENDPOINT
# ============================================================

async def handle_system_health(request: web.Request) -> web.Response:
    """
    GET /api/system/health
    PRISM v0.1 — Comprehensive real-time system health matrix.
    Returns actual connection status, agent heartbeats, system metrics,
    and AI provider status — all without any AI token spend.
    """
    import os

    result = {
        "backend": True,
        "supabase": {"connected": False, "error": "Not checked"},
        "ai": False,
        "database": False,
        "version": "PRISM v0.1",
        "supabase_stats": {},
        "system_metrics": {},
        "agents": {},
        "ai_providers": {},
        "uptime": 0,
    }

    # ===== CANONICAL JOB COUNT =====
    # Single source of truth for ALL surfaces (mini-app tabs, Telegram bot, profile)
    canonical_count = 0
    sqlite_count = 0
    supabase_count = 0

    # System metrics — zero-cost, pure computation
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()
        result["system_metrics"] = {
            "memory_mb": round(mem_info.rss / 1024 / 1024, 1),
            "memory_pct": round(proc.memory_percent(), 1),
            "cpu_pct": round(psutil.cpu_percent(interval=0.1), 1),
            "threads": proc.num_threads(),
            "open_files": len(proc.open_files()) if hasattr(proc, 'open_files') else 0,
            "pid": os.getpid(),
        }
    except ImportError:
        # psutil not installed — provide basic metrics from /proc if available
        result["system_metrics"] = {"pid": os.getpid(), "note": "psutil not installed, limited metrics"}
        try:
            with open(f'/proc/{os.getpid()}/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        rss_kb = int(line.split()[1])
                        result["system_metrics"]["memory_mb"] = round(rss_kb / 1024, 1)
                    elif line.startswith('Threads:'):
                        result["system_metrics"]["threads"] = int(line.split()[1])
        except Exception:
            pass
    except Exception as e:
        result["system_metrics"] = {"error": str(e)[:100]}

    # Uptime
    try:
        from core.keepalive import get_health_tracker
        ht = get_health_tracker()
        result["uptime"] = round(ht.uptime_seconds, 0)
        result["uptime_str"] = ht.uptime_str
    except Exception:
        pass

    # Check SQLite database + get counts
    try:
        from core.database import get_db
        db = get_db()
        if db:
            result["database"] = True
            try:
                stats = db.get_stats() if hasattr(db, 'get_stats') else {}
                result["db_stats"] = stats
                # Get SQLite count for canonical total
                source_counts = db.get_source_counts()
                sqlite_count = sum(source_counts.values()) if source_counts else 0
            except Exception:
                pass
    except Exception:
        result["database"] = False

    # Agent heartbeats — from DB, no AI spend
    try:
        from core.database import get_db
        db = get_db()
        if db:
            heartbeats = db.get_all_heartbeats()
            agents_summary = {}
            for h in heartbeats:
                aid = h.get('agent_id', '?')
                agents_summary[aid] = {
                    "name": h.get('agent_name', '?'),
                    "status": h.get('status', 'idle'),
                    "total_runs": h.get('total_runs', 0),
                    "total_items": h.get('total_items', 0),
                    "errors": h.get('errors_last_run', 0),
                    "last_run": str(h.get('last_run', 'Never'))[:19],
                }
            result["agents"] = agents_summary
    except Exception:
        pass

    # AI provider status — check configured, no API calls
    try:
        from core.ai_router import get_router
        router = get_router()
        if router:
            result["ai"] = True
            # Expose provider health without making any API calls
            providers_status = {}
            for provider_name in ['groq', 'cerebras', 'openrouter', 'groq_compound', 'mistral']:
                try:
                    prov = getattr(router, f'_{provider_name}_configured', False)
                    providers_status[provider_name] = {
                        "configured": bool(prov),
                        "calls_today": router._provider_call_counts.get(provider_name, 0) if hasattr(router, '_provider_call_counts') else 0,
                    }
                except Exception:
                    providers_status[provider_name] = {"configured": False}
            result["ai_providers"] = providers_status
    except Exception:
        result["ai"] = False

    # Check Supabase with real ping
    try:
        from core.supabase_client import is_supabase_configured, health_check as sb_health_check
        if is_supabase_configured():
            hc = sb_health_check()
            result["supabase"] = hc
            try:
                from core.supabase_db import SupabaseJobDB
                stats = SupabaseJobDB.get_stats()
                result["supabase_stats"] = stats
                # Get Supabase count for canonical total
                supabase_count = stats.get('all_jobs_total', 0) or stats.get('total', 0) or 0
            except Exception:
                pass
        else:
            result["supabase"] = {"connected": False, "error": "Not configured - check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars"}
    except Exception as e:
        result["supabase"] = {"connected": False, "error": str(e)[:200]}

    # ===== CANONICAL JOB COUNT: The ONE number used everywhere =====
    # Rule: max(sqlite_count, supabase_count) to avoid undercounting
    canonical_count = max(sqlite_count, supabase_count)
    result["canonical_job_count"] = canonical_count
    result["canonical_breakdown"] = {
        "sqlite": sqlite_count,
        "supabase": supabase_count,
        "note": "Use canonical_job_count as THE job count everywhere",
    }

    return _json_response({
        "success": True,
        "data": result,
        "timestamp": datetime.now(IST).isoformat(),
    })


async def handle_canonical_count(request: web.Request) -> web.Response:
    """
    GET /api/canonical-count
    Returns THE single source of truth job count for all UI surfaces.
    Lightweight endpoint — no agent heartbeats, no AI check, just counts.
    Use this everywhere: mini-app header, Telegram bot, profile tab.
    """
    sqlite_count = 0
    supabase_count = 0

    try:
        from core.database import get_db
        db = get_db()
        if db:
            source_counts = db.get_source_counts()
            sqlite_count = sum(source_counts.values()) if source_counts else 0
    except Exception:
        pass

    try:
        from core.supabase_client import is_operational
        if is_operational():
            from core.supabase_db import SupabaseJobDB
            stats = SupabaseJobDB.get_stats()
            supabase_count = stats.get('all_jobs_total', 0) or stats.get('total', 0) or 0
    except Exception:
        pass

    canonical = max(sqlite_count, supabase_count)

    return _json_response({
        "success": True,
        "data": {
            "canonical_count": canonical,
            "sqlite_count": sqlite_count,
            "supabase_count": supabase_count,
        },
        "timestamp": datetime.now(IST).isoformat(),
    })


async def handle_admin_reset_db(request):
    """Admin endpoint to reset all database listings for fresh start.
    POST /api/admin/reset-db
    Body: { "confirm": true, "clear_supabase": true }
    """
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}

    if not body.get("confirm"):
        return _json_response({"success": False, "error": "Send {confirm: true} to confirm"}, status=400)

    results = {}

    # Clear local SQLite
    try:
        from core.database import get_db
        db = get_db()
        counts = db.delete_all_listings()
        results["sqlite"] = counts
        logger.info(f"[{MODULE_ID}] Admin DB reset - SQLite: {counts}")
    except Exception as e:
        results["sqlite_error"] = str(e)

    # Clear Supabase if requested
    if body.get("clear_supabase", True):
        try:
            from core.supabase_db import SupabaseDB
            sb_counts = SupabaseDB.clear_all_jobs()
            results["supabase"] = sb_counts
            logger.info(f"[{MODULE_ID}] Admin DB reset - Supabase: {sb_counts}")
        except Exception as e:
            results["supabase_error"] = str(e)

    return _json_response({
        "success": True,
        "message": "Database reset complete. All old listings cleared.",
        "results": results,
        "timestamp": datetime.now(IST).isoformat(),
    })


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
    app.router.add_post('/api/batch-apply', handle_batch_apply)
    app.router.add_post('/api/llm/chat', handle_llm_chat)
    app.router.add_get('/api/sources', handle_sources)
    app.router.add_get('/api/filters', handle_filters)

    # Supabase persistent database API endpoints
    app.router.add_get('/api/supabase/latest-jobs', handle_supabase_latest_jobs)
    app.router.add_get('/api/supabase/all-jobs', handle_supabase_all_jobs)
    app.router.add_get('/api/supabase/job/{id}', handle_supabase_job_detail)
    app.router.add_post('/api/supabase/apply/{id}', handle_supabase_apply)
    app.router.add_get('/api/supabase/stats', handle_supabase_stats)

    # User profile & CV endpoints
    app.router.add_post('/api/user/upload-cv', handle_user_upload_cv)
    app.router.add_get('/api/user/profile', handle_user_profile)
    app.router.add_post('/api/user/profile', handle_user_profile)

    # System health check
    app.router.add_get('/api/system/health', handle_system_health)

    # Canonical job count — single source of truth for all surfaces
    app.router.add_get('/api/canonical-count', handle_canonical_count)

    # Admin: Database reset (clears all listings for fresh start)
    app.router.add_post('/api/admin/reset-db', handle_admin_reset_db)

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
