#!/bin/bash
# ============================================================
# OPERATION FIRST MOVER v5 — CLOUDFLARE WORKER SETUP
# ============================================================
# This script helps you deploy the relay worker to Cloudflare.
# Free tier: 100,000 requests/day (more than enough).
#
# PREREQUISITES:
#   1. A Cloudflare account (free: https://dash.cloudflare.com/sign-up)
#   2. Node.js installed (for wrangler CLI)
#
# WHAT THIS DOES:
#   Deploys an HTTP relay worker to Cloudflare's edge network.
#   Your scraper sends requests to the worker, which fetches
#   from Naukri/etc. using Cloudflare's IPs. Sites see Cloudflare
#   instead of your Render IP, bypassing IP-based blocks.
# ============================================================

set -e

echo "============================================"
echo " Cloudflare Worker Relay — Setup"
echo "============================================"
echo ""

# Step 1: Check prerequisites
if ! command -v npx &> /dev/null; then
    echo "❌ npx not found. Install Node.js first:"
    echo "   https://nodejs.org/"
    exit 1
fi

echo "✅ Node.js found"
echo ""

# Step 2: Login to Cloudflare
echo "Step 1: Logging in to Cloudflare..."
echo "   (A browser window will open — log in with your Cloudflare account)"
echo ""
npx wrangler login
echo ""
echo "✅ Logged in to Cloudflare"
echo ""

# Step 3: Generate a relay secret
RELAY_SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
echo "Step 2: Generated relay secret"
echo "   Secret: $RELAY_SECRET"
echo ""

# Step 4: Deploy the worker
echo "Step 3: Deploying worker..."
cd "$(dirname "$0")"
npx wrangler deploy
echo ""
echo "✅ Worker deployed!"
echo ""

# Step 5: Set the secret
echo "Step 4: Setting RELAY_SECRET..."
echo "$RELAY_SECRET" | npx wrangler secret put RELAY_SECRET
echo ""
echo "✅ Secret configured!"
echo ""

# Step 6: Get the worker URL
echo "============================================"
echo " SETUP COMPLETE!"
echo "============================================"
echo ""
echo "Your worker URL will look like:"
echo "   https://firstmover-relay.<your-subdomain>.workers.dev"
echo ""
echo "Now add these to your Render environment variables:"
echo ""
echo "   CF_WORKER_URL=https://firstmover-relay.<your-subdomain>.workers.dev"
echo "   CF_RELAY_SECRET=$RELAY_SECRET"
echo ""
echo "Or add them to your .env file:"
echo ""
echo "   CF_WORKER_URL=https://firstmover-relay.<your-subdomain>.workers.dev"
echo "   CF_RELAY_SECRET=$RELAY_SECRET"
echo ""
echo "Then redeploy your Render service."
echo "============================================"
