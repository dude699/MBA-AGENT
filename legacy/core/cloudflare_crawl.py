"""
============================================================
CLOUDFLARE BROWSER RENDERING /crawl API — FREE TIER INTEGRATION
============================================================

Cloudflare Browser Rendering API provides headless Chrome at the edge.
FREE TIER: 5,000 requests/month on Workers Free plan.
This is PERFECT for scraping JavaScript-heavy career pages.

Setup Guide (ONE-TIME, FREE):
    1. Create Cloudflare account: https://dash.cloudflare.com/sign-up
    2. Go to Workers & Pages → Overview
    3. Enable Browser Rendering (free tier = 5000 req/month)
    4. Create a Worker that calls /crawl:
    
    // worker.js
    export default {
        async fetch(request, env) {
            const url = new URL(request.url);
            const targetUrl = url.searchParams.get('url');
            const secret = url.searchParams.get('secret');
            
            if (secret !== env.CRAWL_SECRET) {
                return new Response('Unauthorized', { status: 401 });
            }
            
            if (!targetUrl) {
                return new Response('Missing url param', { status: 400 });
            }
            
            try {
                const browser = await env.BROWSER.fetch(
                    `https://browser-rendering.cloudflare.com/crawl?url=${encodeURIComponent(targetUrl)}`,
                    {
                        headers: { 'Content-Type': 'application/json' },
                    }
                );
                const result = await browser.json();
                return new Response(JSON.stringify(result), {
                    headers: { 'Content-Type': 'application/json' },
                });
            } catch (error) {
                return new Response(JSON.stringify({ error: error.message }), {
                    status: 500,
                    headers: { 'Content-Type': 'application/json' },
                });
            }
        }
    };
    
    5. Deploy Worker (free)
    6. Set env vars in Render:
       CF_CRAWL_WORKER_URL=https://your-worker.workers.dev
       CF_CRAWL_SECRET=your-secret-here

Usage in our system:
    from core.cloudflare_crawl import crawl_page, crawl_career_page
    
    # Crawl any URL with JS rendering
    result = crawl_page("https://careers.mckinsey.com/search/intern")
    
    # Extract job listings from a career page
    jobs = crawl_career_page("https://careers.bcg.com", keywords=["intern", "MBA"])
"""

import os
import json
import time
import re

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


# ============================================================
# CONFIGURATION
# ============================================================

CF_CRAWL_WORKER_URL = os.getenv('CF_CRAWL_WORKER_URL', '')
CF_CRAWL_SECRET = os.getenv('CF_CRAWL_SECRET', '')

# Rate limiting for free tier: 5000 req/month ≈ 166/day ≈ 7/hour
MAX_CRAWLS_PER_HOUR = 10
_crawl_timestamps = []


def is_configured() -> bool:
    """Check if Cloudflare /crawl is configured."""
    return bool(CF_CRAWL_WORKER_URL and CF_CRAWL_SECRET)


def _check_rate_limit() -> bool:
    """Check if we're within rate limits."""
    global _crawl_timestamps
    now = time.time()
    # Remove timestamps older than 1 hour
    _crawl_timestamps = [t for t in _crawl_timestamps if now - t < 3600]
    if len(_crawl_timestamps) >= MAX_CRAWLS_PER_HOUR:
        return False
    _crawl_timestamps.append(now)
    return True


def crawl_page(url: str, timeout: int = 30) -> dict:
    """
    Crawl a URL using Cloudflare Browser Rendering.
    Returns: {'success': bool, 'html': str, 'text': str, 'title': str, 'links': list}
    """
    if not is_configured():
        return {'success': False, 'error': 'Cloudflare /crawl not configured'}

    if not _check_rate_limit():
        return {'success': False, 'error': 'Rate limit exceeded (10/hour)'}

    if not httpx:
        return {'success': False, 'error': 'httpx not installed'}

    try:
        response = httpx.get(
            CF_CRAWL_WORKER_URL,
            params={'url': url, 'secret': CF_CRAWL_SECRET},
            timeout=timeout,
            follow_redirects=True,
        )

        if response.status_code != 200:
            return {
                'success': False,
                'error': f'HTTP {response.status_code}',
                'status_code': response.status_code,
            }

        data = response.json()

        # The /crawl API returns rendered content
        result = {
            'success': True,
            'html': data.get('html', ''),
            'text': data.get('text', ''),
            'title': data.get('title', ''),
            'links': data.get('links', []),
            'url': url,
        }

        # If we got HTML but no text, extract it
        if result['html'] and not result['text'] and BeautifulSoup:
            soup = BeautifulSoup(result['html'], 'html.parser')
            result['text'] = soup.get_text(separator=' ', strip=True)[:10000]

        return result

    except Exception as e:
        logger.debug(f"[CF-CRAWL] Error crawling {url}: {e}")
        return {'success': False, 'error': str(e)}


def crawl_career_page(url: str, keywords: list = None) -> list:
    """
    Crawl a career page and extract job listings.
    
    Args:
        url: Career page URL (e.g., https://careers.mckinsey.com)
        keywords: Filter keywords (default: ['intern', 'MBA', 'trainee'])
    
    Returns:
        List of dicts: [{'title': ..., 'url': ..., 'description': ...}, ...]
    """
    if keywords is None:
        keywords = ['intern', 'internship', 'mba', 'trainee', 'associate', 'summer']

    result = crawl_page(url)
    if not result['success']:
        return []

    jobs = []

    # Strategy 1: Parse links that contain career-related keywords
    for link in result.get('links', []):
        link_url = link.get('href', '') or link.get('url', '')
        link_text = link.get('text', '') or link.get('title', '')

        if not link_url or not link_text:
            continue

        # Make absolute URL
        if link_url.startswith('/'):
            from urllib.parse import urljoin
            link_url = urljoin(url, link_url)

        text_lower = link_text.lower()
        url_lower = link_url.lower()

        # Check if this link looks like a job listing
        is_job_link = any(kw in text_lower for kw in keywords) or \
                      any(kw in url_lower for kw in ['job', 'career', 'position', 'opening'])

        if is_job_link:
            jobs.append({
                'title': link_text.strip(),
                'url': link_url,
                'description': '',
            })

    # Strategy 2: Parse HTML for structured job listings
    if BeautifulSoup and result.get('html'):
        soup = BeautifulSoup(result['html'], 'html.parser')

        # Common job listing selectors across ATS systems
        selectors = [
            '.job-listing', '.job-card', '.job-item',
            '[data-job-id]', '.opening', '.position',
            '.career-listing', '.job-title a',
            'article.job', 'li.job', 'div.job',
        ]

        for selector in selectors:
            cards = soup.select(selector)
            for card in cards:
                title_el = card.select_one('h2, h3, h4, .title, .job-title, a')
                if title_el:
                    title = title_el.get_text(strip=True)
                    link = title_el.get('href', '') or card.select_one('a[href]')
                    if isinstance(link, str) and link:
                        from urllib.parse import urljoin
                        link = urljoin(url, link)
                    elif hasattr(link, 'get'):
                        link = urljoin(url, link.get('href', ''))
                    else:
                        link = ''

                    if title and any(kw in title.lower() for kw in keywords):
                        jobs.append({
                            'title': title,
                            'url': link,
                            'description': card.get_text(strip=True)[:500],
                        })

    # Deduplicate
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        url_key = job.get('url', '')
        if url_key and url_key not in seen_urls:
            seen_urls.add(url_key)
            unique_jobs.append(job)

    logger.info(f"[CF-CRAWL] {url} → {len(unique_jobs)} job listings found")
    return unique_jobs


def get_status() -> dict:
    """Get Cloudflare /crawl configuration status."""
    global _crawl_timestamps
    now = time.time()
    recent = [t for t in _crawl_timestamps if now - t < 3600]
    return {
        'configured': is_configured(),
        'worker_url': CF_CRAWL_WORKER_URL[:50] + '...' if CF_CRAWL_WORKER_URL else 'NOT SET',
        'requests_this_hour': len(recent),
        'max_per_hour': MAX_CRAWLS_PER_HOUR,
        'free_tier_limit': '5,000/month',
        'setup_guide': 'Set CF_CRAWL_WORKER_URL and CF_CRAWL_SECRET env vars',
    }
