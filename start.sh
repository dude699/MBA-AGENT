#!/usr/bin/env bash
# ============================================================
# OPERATION FIRST MOVER — START SCRIPT (v5.4.1)
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
#   1. If mini-app/dist/ exists -> skip build (already built)
#   2. If mini-app/dist/ missing -> run npm install + build
#   3. Start Python main.py
# ============================================================

set -e

echo "========================================================"
echo "  OPERATION FIRST MOVER v5.4.1 — Startup Script"
echo "========================================================"

MINI_APP_DIR="mini-app"
DIST_DIR="$MINI_APP_DIR/dist"

# -- Step 1: Build mini-app if dist/ doesn't exist -----------
if [ -d "$DIST_DIR" ] && [ -f "$DIST_DIR/index.html" ]; then
    ASSET_COUNT=$(find "$DIST_DIR" -type f | wc -l)
    echo "[START] Mini-app already built ($ASSET_COUNT files in dist/)"
else
    echo "[START] Mini-app dist/ not found — building now..."

    if [ -d "$MINI_APP_DIR" ] && [ -f "$MINI_APP_DIR/package.json" ]; then
        # Check if node/npm are available
        if command -v node &> /dev/null && command -v npm &> /dev/null; then
            echo "[START] Node $(node --version), npm $(npm --version)"

            cd "$MINI_APP_DIR"

            # Add node_modules/.bin to PATH for direct binary access
            export PATH="$(pwd)/node_modules/.bin:$PATH"
            # CRITICAL: Unset NODE_ENV=production so devDependencies get installed
            # Render sets NODE_ENV=production which skips vite, typescript, etc.
            unset NODE_ENV

            echo "[START] Installing dependencies (including devDependencies)..."
            npm install --include=dev --no-audit --no-fund 2>&1 | tail -5

            echo "[START] Building mini-app..."

            # Try 1: Full build (tsc + vite)
            if npm run build 2>&1; then
                echo "[START] Full build (tsc + vite) succeeded!"
            else
                echo "[START] Full build failed, trying vite-only (npm run build:vite)..."
                # Try 2: Vite-only build via npm script (uses local node_modules)
                if npm run build:vite 2>&1; then
                    echo "[START] Vite-only build succeeded!"
                else
                    echo "[START] npm run build:vite failed, trying direct vite binary..."
                    # Try 3: Direct vite binary from node_modules
                    if [ -x "node_modules/.bin/vite" ]; then
                        node_modules/.bin/vite build 2>&1 || echo "[START] All build methods failed"
                    else
                        echo "[START] vite binary not found in node_modules/.bin/"
                        echo "[START] Mini-app will show 'Not Built' error"
                    fi
                fi
            fi

            cd ..
        else
            echo "[START] Node.js/npm not available — cannot build mini-app"
            echo "[START] The mini-app will show 'Not Built' error"
        fi
    else
        echo "[START] mini-app/ directory or package.json not found"
    fi
fi

# -- Verify final state --------------------------------------
if [ -f "$DIST_DIR/index.html" ]; then
    ASSET_COUNT=$(find "$DIST_DIR" -type f | wc -l)
    echo "[START] Mini-app ready: $ASSET_COUNT files in dist/"
else
    echo "[START] WARNING: Mini-app NOT available (dist/index.html missing)"
    echo "[START] The /app/ endpoint will show an error page"
fi

echo "========================================================"
echo "[START] Starting Python backend..."
echo "========================================================"

# -- Step 2: Start the Python application ---------------------
exec python main.py
