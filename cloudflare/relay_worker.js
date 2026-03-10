// ============================================================
// OPERATION FIRST MOVER v5 — CLOUDFLARE WORKER RELAY (PRODUCTION)
// ============================================================
// Deploy: cd cloudflare && wrangler deploy
// Free tier: 100,000 requests/day
//
// Features:
//   - Authenticated relay (X-Relay-Secret header)
//   - Rate limiting (100 req/min per IP)
//   - Request timeout (30s)
//   - Health endpoint (/health)
//   - Error classification and logging
//   - CORS support
//   - User-Agent rotation
//   - Response size limit (5MB)
// ============================================================

const MAX_RESPONSE_SIZE = 5 * 1024 * 1024; // 5MB
const REQUEST_TIMEOUT_MS = 30000; // 30s
const RATE_LIMIT_PER_MIN = 100;

// Simple in-memory rate limiter (resets on worker restart)
const rateLimitMap = new Map();

function checkRateLimit(ip) {
  const now = Date.now();
  const windowStart = now - 60000; // 1 minute window

  if (!rateLimitMap.has(ip)) {
    rateLimitMap.set(ip, []);
  }

  const timestamps = rateLimitMap.get(ip).filter(t => t > windowStart);
  rateLimitMap.set(ip, timestamps);

  if (timestamps.length >= RATE_LIMIT_PER_MIN) {
    return false;
  }

  timestamps.push(now);
  return true;
}

// Clean up old rate limit entries periodically
function cleanupRateLimit() {
  const now = Date.now();
  const windowStart = now - 120000; // 2 minutes
  for (const [ip, timestamps] of rateLimitMap.entries()) {
    const filtered = timestamps.filter(t => t > windowStart);
    if (filtered.length === 0) {
      rateLimitMap.delete(ip);
    } else {
      rateLimitMap.set(ip, filtered);
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Health check endpoint
    if (url.pathname === '/health' || url.pathname === '/') {
      return new Response(JSON.stringify({
        status: 'ok',
        service: 'firstmover-relay',
        version: '2.0',
        timestamp: new Date().toISOString(),
      }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, X-Relay-Secret',
        },
      });
    }

    // Only accept POST to /relay
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'Method not allowed. POST to /relay' }), {
        status: 405,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Rate limiting
    const clientIP = request.headers.get('CF-Connecting-IP') || 'unknown';
    if (!checkRateLimit(clientIP)) {
      return new Response(JSON.stringify({ error: 'Rate limit exceeded (100/min)' }), {
        status: 429,
        headers: {
          'Content-Type': 'application/json',
          'Retry-After': '60',
        },
      });
    }

    // Validate secret
    const secret = request.headers.get('X-Relay-Secret');
    if (!secret || secret !== env.RELAY_SECRET) {
      return new Response(JSON.stringify({ error: 'Forbidden: invalid relay secret' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    try {
      const body = await request.json();
      const { url: targetUrl, headers: reqHeaders, method, body: reqBody } = body;

      if (!targetUrl) {
        return new Response(JSON.stringify({ error: 'Missing url parameter' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      // Validate URL (only allow HTTP/HTTPS)
      let parsedUrl;
      try {
        parsedUrl = new URL(targetUrl);
        if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
          throw new Error('Only HTTP/HTTPS allowed');
        }
      } catch (e) {
        return new Response(JSON.stringify({ error: `Invalid URL: ${e.message}` }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      // Build fetch options
      const fetchOptions = {
        method: method || 'GET',
        headers: {
          ...(reqHeaders || {}),
          'User-Agent':
            (reqHeaders && reqHeaders['User-Agent']) ||
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        },
        // Cloudflare-specific: follow redirects, don't cache
        redirect: 'follow',
        cf: {
          cacheTtl: 0,
          cacheEverything: false,
        },
      };

      // Add body for POST/PUT requests
      if (reqBody && ['POST', 'PUT', 'PATCH'].includes((method || '').toUpperCase())) {
        fetchOptions.body = typeof reqBody === 'string' ? reqBody : JSON.stringify(reqBody);
      }

      // Execute relay request with timeout using AbortController
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      fetchOptions.signal = controller.signal;

      let resp;
      try {
        resp = await fetch(targetUrl, fetchOptions);
      } finally {
        clearTimeout(timeoutId);
      }

      // Read response with size limit
      const reader = resp.body.getReader();
      const chunks = [];
      let totalSize = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        totalSize += value.length;
        if (totalSize > MAX_RESPONSE_SIZE) {
          reader.cancel();
          return new Response(JSON.stringify({
            error: 'Response too large',
            limit: `${MAX_RESPONSE_SIZE / 1024 / 1024}MB`,
            actual: `${(totalSize / 1024 / 1024).toFixed(1)}MB+`,
          }), {
            status: 413,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        chunks.push(value);
      }

      // Combine chunks into text
      const decoder = new TextDecoder();
      const text = chunks.map(chunk => decoder.decode(chunk, { stream: true })).join('') + decoder.decode();

      // Build response headers map
      const respHeaders = {};
      resp.headers.forEach((value, key) => {
        respHeaders[key] = value;
      });

      return new Response(
        JSON.stringify({
          status: resp.status,
          statusText: resp.statusText,
          body: text,
          headers: respHeaders,
        }),
        {
          headers: { 'Content-Type': 'application/json' },
        }
      );
    } catch (err) {
      // Classify error
      let errorType = 'relay_error';
      let statusCode = 500;

      if (err.name === 'AbortError') {
        errorType = 'timeout';
        statusCode = 504;
      } else if (err.message && err.message.includes('DNS')) {
        errorType = 'dns_error';
        statusCode = 502;
      }

      return new Response(
        JSON.stringify({
          error: errorType,
          message: err.message || 'Unknown error',
        }),
        {
          status: statusCode,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    } finally {
      // Periodic cleanup (every ~100 requests)
      if (Math.random() < 0.01) {
        cleanupRateLimit();
      }
    }
  },
};
