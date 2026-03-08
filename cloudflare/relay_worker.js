// ============================================================
// OPERATION FIRST MOVER v5 — CLOUDFLARE WORKER RELAY
// Deploy this to Cloudflare Workers (100k req/day free)
//
// Purpose: Relay HTTP requests through Cloudflare's global
// edge network so target sites see Cloudflare IPs instead
// of your server's IP. This is Layer 2 of the stealth system.
//
// Setup:
//   1. Create a Cloudflare Workers account (free)
//   2. Create a new Worker
//   3. Paste this code
//   4. Add environment variable: RELAY_SECRET = "your-secret"
//   5. Deploy
//   6. Set CF_WORKER_URL in your .env to the worker URL
// ============================================================

export default {
  async fetch(request, env) {
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

    // Only accept POST
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'Method not allowed' }), {
        status: 405,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Validate secret
    const secret = request.headers.get('X-Relay-Secret');
    if (!secret || secret !== env.RELAY_SECRET) {
      return new Response(JSON.stringify({ error: 'Forbidden' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    try {
      const body = await request.json();
      const { url, headers: reqHeaders, method, body: reqBody } = body;

      if (!url) {
        return new Response(JSON.stringify({ error: 'Missing url parameter' }), {
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
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        },
      };

      // Add body for POST/PUT requests
      if (reqBody && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
        fetchOptions.body = typeof reqBody === 'string' ? reqBody : JSON.stringify(reqBody);
      }

      // Execute relay request
      const resp = await fetch(url, fetchOptions);
      const text = await resp.text();

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
      return new Response(
        JSON.stringify({
          error: 'Relay error',
          message: err.message,
        }),
        {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    }
  },
};
