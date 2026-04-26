#!/usr/bin/env bash
# =============================================================================
# NEXUS v0.2 — Bootstrap Installer
# =============================================================================
#
# The exact "first 4 commands" from the architecture doc, hardened:
#
#   1. Apply Postgres / pgvector schema (data/nexus_v02_schema.sql)
#   2. Install heavy worker stack (requirements-nexus.txt)
#   3. Install Camoufox Firefox runtime (camoufox download)
#   4. Generate session vault key + capture first sessions
#
# Usage:
#   chmod +x scripts/nexus_bootstrap.sh
#   ./scripts/nexus_bootstrap.sh                  # interactive, all 4 steps
#   ./scripts/nexus_bootstrap.sh --step schema    # only step 1
#   ./scripts/nexus_bootstrap.sh --step deps      # only step 2
#   ./scripts/nexus_bootstrap.sh --step camoufox  # only step 3
#   ./scripts/nexus_bootstrap.sh --step vault     # only step 4
#   ./scripts/nexus_bootstrap.sh --yes            # non-interactive (CI mode)
#
# Required env (set before running, or via .env in cwd):
#   DATABASE_URL              postgres://… (Supabase)
#   SESSION_VAULT_KEY         32-byte urlsafe-base64 key (or step 4 generates one)
#   GROQ_API_KEY              for Crawl4AI LLM extraction
#   GEMINI_API_KEY            for CAPTCHA T1 + scoring
#   CEREBRAS_API_KEY          for Layer 4 RAG
#   TELEGRAM_BOT_TOKEN        for dashboard alerts
#   TELEGRAM_CHAT_ID          your chat
#
# Render free tier:
#   Run only --step schema and --step vault. The base requirements.txt is
#   already installed by Render; the heavy worker stack must run on a beefier
#   dyno (≥ 2 GB) — typically a separate workers process.
# =============================================================================

set -euo pipefail

# ───────────────────────────── pretty output ─────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YEL='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
say()  { printf "${BLUE}▸${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn() { printf "${YEL}⚠${NC} %s\n" "$*"; }
err()  { printf "${RED}✗${NC} %s\n" "$*" >&2; }

cd "$(dirname "$0")/.."   # repo root
ROOT="$(pwd)"
say "NEXUS v0.2 bootstrap — repo root: ${ROOT}"

# ───────────────────────────── arg parsing ───────────────────────────────────
STEP="all"
NON_INTERACTIVE="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --step)        STEP="$2"; shift 2 ;;
    --yes|-y)      NON_INTERACTIVE="true"; shift ;;
    --help|-h)     sed -n '2,40p' "$0"; exit 0 ;;
    *)             err "Unknown arg: $1"; exit 2 ;;
  esac
done

# Load .env if present (without exporting noisy lines)
if [[ -f ".env" ]]; then
  say "Loading .env"
  set -a; source .env; set +a
fi

confirm() {
  local q="$1"
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    return 0
  fi
  read -r -p "$(printf '%s [y/N] ' "$q")" ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

require_env() {
  local var="$1"
  if [[ -z "${!var:-}" ]]; then
    err "Missing required env var: $var"
    return 1
  fi
}

# ─────────────────────────── Step 1 — Schema ─────────────────────────────────
step_schema() {
  say "Step 1/4 — Apply Postgres / pgvector schema"

  if ! command -v psql >/dev/null 2>&1; then
    err "psql not found. Install postgresql-client (e.g. apt install postgresql-client)."
    return 1
  fi

  require_env DATABASE_URL || return 1

  if [[ ! -f "data/nexus_v02_schema.sql" ]]; then
    err "data/nexus_v02_schema.sql missing — are you on the genspark_ai_developer branch?"
    return 1
  fi

  if confirm "Apply schema to ${DATABASE_URL%%@*}@…"; then
    psql "$DATABASE_URL" -f data/nexus_v02_schema.sql
    ok "Schema applied (idempotent — safe to re-run)."
  else
    warn "Skipped schema apply."
  fi
}

# ─────────────────────────── Step 2 — Dependencies ───────────────────────────
step_deps() {
  say "Step 2/4 — Install heavy worker stack"

  if ! command -v pip >/dev/null 2>&1; then
    err "pip not found in PATH."
    return 1
  fi

  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  ok "Base PRISM stack installed."

  if [[ -f "requirements-nexus.txt" ]]; then
    if confirm "Install heavy NEXUS stack (Camoufox + Browser-Use + Skyvern + Crawl4AI, ~2 GB)?"; then
      pip install -r requirements-nexus.txt
      ok "Heavy NEXUS stack installed."
    else
      warn "Skipped heavy NEXUS stack — you can install later with:"
      printf "      pip install -r requirements-nexus.txt\n"
    fi
  fi
}

# ─────────────────────────── Step 3 — Camoufox ───────────────────────────────
step_camoufox() {
  say "Step 3/4 — Install Camoufox Firefox runtime"

  if ! python3 -c "import camoufox" 2>/dev/null; then
    warn "camoufox python pkg not installed; run --step deps first or:"
    printf "      pip install -r requirements-nexus.txt\n"
    if [[ "$NON_INTERACTIVE" != "true" ]]; then return 0; fi
  fi

  if python3 -c "import camoufox" 2>/dev/null; then
    if confirm "Download Camoufox Firefox 142 binary (~120 MB)?"; then
      python3 -m camoufox fetch || warn "camoufox fetch returned non-zero; check network."
      ok "Camoufox runtime ready."
    else
      warn "Skipped Camoufox download."
    fi
  fi

  # Playwright Firefox is the host process Camoufox steers
  if python3 -c "import playwright" 2>/dev/null; then
    if confirm "Install Playwright Firefox engine?"; then
      python3 -m playwright install firefox || warn "Playwright install non-zero."
      ok "Playwright Firefox installed."
    fi
  fi
}

# ─────────────────────────── Step 4 — Vault & sessions ──────────────────────
step_vault() {
  say "Step 4/4 — Generate vault key + capture sessions"

  # Make sure vault key exists
  if [[ -z "${SESSION_VAULT_KEY:-}" ]]; then
    if confirm "SESSION_VAULT_KEY missing. Generate a new one and append to .env?"; then
      KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
      printf '\n# NEXUS vault key (generated %s)\nSESSION_VAULT_KEY=%s\n' "$(date -u +%FT%TZ)" "$KEY" >> .env
      export SESSION_VAULT_KEY="$KEY"
      ok "Generated SESSION_VAULT_KEY and appended to .env"
      warn "ROTATE this key only via the encrypted re-key flow — never lose it."
    else
      err "SESSION_VAULT_KEY required for vault step."
      return 1
    fi
  else
    ok "SESSION_VAULT_KEY present."
  fi

  # Smoke-test vault module
  if python3 -c "from core.session_vault import SessionVault" 2>/dev/null; then
    ok "core.session_vault imports cleanly."
  else
    err "core.session_vault import failed — check cryptography install."
    return 1
  fi

  warn "Session capture is interactive and runs on the worker dyno."
  warn "From the worker, launch:"
  printf "      python3 -m core.session_vault capture --portal linkedin\n"
  printf "      python3 -m core.session_vault capture --portal naukri\n"
  printf "      python3 -m core.session_vault capture --portal internshala\n"
  printf "    The capture flow opens Camoufox, you log in once, vault encrypts cookies.\n"
}

# ─────────────────────────── Driver ──────────────────────────────────────────
case "$STEP" in
  schema)   step_schema ;;
  deps)     step_deps ;;
  camoufox) step_camoufox ;;
  vault)    step_vault ;;
  all)
    step_schema   || warn "schema step exited non-zero"
    step_deps     || warn "deps step exited non-zero"
    step_camoufox || warn "camoufox step exited non-zero"
    step_vault    || warn "vault step exited non-zero"
    ;;
  *)
    err "Unknown --step: $STEP (use schema|deps|camoufox|vault|all)"
    exit 2
    ;;
esac

ok "NEXUS v0.2 bootstrap complete."
say "Next:  start orchestrator on the worker dyno (see docs/NEXUS_ARCHITECTURE.md)."
