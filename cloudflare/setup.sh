#!/bin/bash
# ============================================================
# OPERATION FIRST MOVER v5 — CLOUDFLARE WORKER SETUP
# ============================================================
# One-command setup for the HTTP relay worker.
#
# PREREQUISITES:
#   1. Cloudflare account (free): https://dash.cloudflare.com/sign-up
#   2. Node.js 18+ installed
#
# USAGE:
#   cd cloudflare && bash setup.sh
#
# WHAT THIS DOES:
#   1. Logs you into Cloudflare (browser opens)
#   2. Deploys the relay worker to Cloudflare's edge
#   3. Generates and sets a relay secret
#   4. Prints env vars to add to Render
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  Cloudflare Worker Relay — Automated Setup     ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# Step 0: Check prerequisites
echo "[0/5] Checking prerequisites..."
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Install it first: https://nodejs.org/"
    exit 1
fi
NODE_VER=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VER" -lt 18 ]; then
    echo "❌ Node.js 18+ required (found: $(node -v))"
    exit 1
fi
echo "  ✅ Node.js $(node -v)"

if ! command -v npx &> /dev/null; then
    echo "❌ npx not found"
    exit 1
fi
echo "  ✅ npx available"
echo ""

# Step 1: Login to Cloudflare
echo "[1/5] Logging into Cloudflare..."
echo "  A browser window will open — log in with your Cloudflare account."
echo ""
npx wrangler login 2>&1
echo ""
echo "  ✅ Logged in to Cloudflare"
echo ""

# Step 2: Check if worker already exists
echo "[2/5] Checking for existing deployment..."
if npx wrangler deployments list --name firstmover-relay 2>/dev/null | grep -q "Active"; then
    echo "  ⚠️  Worker already deployed. Will update."
else
    echo "  📦 Fresh deployment."
fi
echo ""

# Step 3: Deploy the worker
echo "[3/5] Deploying relay_worker.js..."
DEPLOY_OUTPUT=$(npx wrangler deploy 2>&1)
echo "$DEPLOY_OUTPUT"
echo ""

# Extract worker URL from deploy output
WORKER_URL=$(echo "$DEPLOY_OUTPUT" | grep -oP 'https://[a-zA-Z0-9.-]+\.workers\.dev' | head -1)
if [ -z "$WORKER_URL" ]; then
    WORKER_URL="https://firstmover-relay.<your-subdomain>.workers.dev"
    echo "  ⚠️  Could not auto-detect URL. Check Cloudflare dashboard."
else
    echo "  ✅ Worker deployed at: $WORKER_URL"
fi
echo ""

# Step 4: Generate and set relay secret
echo "[4/5] Setting RELAY_SECRET..."
RELAY_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64)
echo "$RELAY_SECRET" | npx wrangler secret put RELAY_SECRET 2>&1
echo ""
echo "  ✅ Secret set"
echo ""

# Step 5: Verify deployment
echo "[5/5] Verifying deployment..."
sleep 2
HEALTH=$(curl -s --max-time 10 "$WORKER_URL/health" 2>/dev/null)
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "  ✅ Health check passed: $HEALTH"
else
    echo "  ⚠️  Health check inconclusive (worker may need a few seconds)"
    echo "  Try: curl $WORKER_URL/health"
fi
echo ""

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                    SETUP COMPLETE!                         ║"
echo "╠════════════════════════════════════════════════════════════╣"
echo "║                                                            ║"
echo "║  Worker URL: $WORKER_URL"
echo "║                                                            ║"
echo "║  Add these to your Render environment variables:           ║"
echo "║                                                            ║"
echo "║    CF_WORKER_URL=$WORKER_URL"
echo "║    CF_RELAY_SECRET=$RELAY_SECRET"
echo "║                                                            ║"
echo "║  Then redeploy your Render service (Manual Deploy).        ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Quick test:"
echo "  curl -X POST $WORKER_URL/relay \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -H 'X-Relay-Secret: $RELAY_SECRET' \\"
echo "    -d '{\"url\": \"https://httpbin.org/ip\"}'"
echo ""
