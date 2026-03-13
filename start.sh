#!/usr/bin/env bash
# ============================================================
# OPERATION FIRST MOVER — START SCRIPT
# ============================================================
# This script ensures the mini-app frontend is built before
# starting the Python backend. It's the startCommand for Render.
#
# WHY THIS EXISTS:
#   Render's render.yaml buildCommand changes require a manual
#   "Sync Blueprint" in the Dashboard. If the buildCommand was
#   updated in render.yaml but the blueprint wasn't re-synced,
#   the npm build step never runs. This script guarantees the
#   mini-app is built regardless of Render's blueprint state.
#
# BEHAVIOR:
#   1. If mini-app/dist/ exists → skip build (already built)
#   2. If mini-app/dist/ missing → run npm install + build
#   3. Start Python main.py
# ============================================================

set -e

echo "========================================================"
echo "  OPERATION FIRST MOVER — Startup Script"
echo "========================================================"

MINI_APP_DIR="mini-app"
DIST_DIR="$MINI_APP_DIR/dist"

# ── Step 1: Build mini-app if dist/ doesn't exist ──────────
if [ -d "$DIST_DIR" ] && [ -f "$DIST_DIR/index.html" ]; then
    echo "[START] ✅ Mini-app already built (dist/index.html exists)"
    echo "[START]    $(ls -la $DIST_DIR/index.html)"
else
    echo "[START] ⚠️  Mini-app dist/ not found — building now..."

    if [ -d "$MINI_APP_DIR" ] && [ -f "$MINI_APP_DIR/package.json" ]; then
        echo "[START] 📦 Installing mini-app dependencies..."
        cd "$MINI_APP_DIR"

        # Check if node/npm are available
        if command -v node &> /dev/null && command -v npm &> /dev/null; then
            echo "[START]    Node $(node --version), npm $(npm --version)"

            npm install --no-audit --no-fund 2>&1 | tail -5
            echo "[START] 🔨 Building mini-app (tsc + vite)..."

            # Try the full build (tsc + vite)
            if npm run build 2>&1; then
                echo "[START] ✅ Mini-app built successfully!"
                ls -la dist/ 2>/dev/null || true
            else
                echo "[START] ⚠️  TypeScript compilation failed, trying vite-only build..."
                # Fallback: skip tsc, just run vite build directly
                npx vite build 2>&1 || echo "[START] ❌ Mini-app build failed completely"
            fi
        else
            echo "[START] ❌ Node.js/npm not available — cannot build mini-app"
            echo "[START]    The mini-app will show 'Not Built' error"
            echo "[START]    To fix: sync the Render blueprint or add Node.js"
        fi

        cd ..
    else
        echo "[START] ❌ mini-app/ directory or package.json not found"
    fi
fi

# Verify final state
if [ -f "$DIST_DIR/index.html" ]; then
    ASSET_COUNT=$(find "$DIST_DIR" -type f | wc -l)
    echo "[START] 📱 Mini-app ready: $ASSET_COUNT files in dist/"
else
    echo "[START] ⚠️  Mini-app NOT available (dist/index.html missing)"
    echo "[START]    The /app/ endpoint will show an error page"
fi

echo "========================================================"
echo "[START] 🚀 Starting Python backend..."
echo "========================================================"

# ── Step 2: Start the Python application ───────────────────
exec python main.py
