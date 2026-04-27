# Render Environment Variable Checklist — NEXUS v0.2

> Last verified against running production: **2026-04-27**
> Service: `mba-agent` · Region: Oregon · Plan: free (512 MB)

This is the **authoritative** list of every env var the app reads.
Source-of-truth scan was done with:

```bash
grep -rhoE 'os\.getenv\(["\x27][A-Z][A-Z0-9_]+["\x27]' core/ agents/ main.py | sort -u
```

---

## 🚨 IMPORTANT — fix before next deploy

Looking at your screenshot of the Render `Environment` tab, **`CREDENTIAL_VAULT_KEY` has the literal command pasted as the value**, not the output of the command. You wrote:

```
CREDENTIAL_VAULT_KEY = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

That is a string, **not a Fernet key**. The vault will reject it on boot, fall back to a temp file in `/data/.vault.key`, and Render will wipe that file on every restart — meaning:

> Encrypted credentials saved to Supabase will become **undecryptable** on the next redeploy.

### How to fix — Render free tier (no Shell access)

The Shell tab is paid-only on Render. You have **three** zero-cost ways to generate the Fernet key:

#### Option A — Local Python (fastest, 10 seconds)
If you have Python 3 on Windows/Mac/Linux:
```bash
pip install cryptography
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### Option B — Online (browser, no install)
Open https://fernetkeygen.com/ → click *Generate* → copy the 44-character key.
*(The site runs the generator in your browser — keys never leave your machine.)*

#### Option C — Use the GitHub Codespaces / Replit shell (free)
1. Open https://replit.com/ → New Repl → Python.
2. In the shell tab, run the same one-liner above.

#### Option D — Use any Python REPL online
- https://www.online-python.com/ — paste the one-liner, hit *Run*.

Once you have the key, paste it into Render `CREDENTIAL_VAULT_KEY` (Environment tab → eye-pencil icon → paste → Save, rebuild, and deploy).

> ✅ Same options work for `SESSION_VAULT_KEY` (use a **different** Fernet key — generate twice).
> ✅ For `NEXUS_CALLBACK_SECRET` use `python -c "import secrets; print(secrets.token_hex(32))"` instead.

#### Quick test that your key is valid
After saving in Render and a redeploy, hit:
```
https://mba-agent-71hu.onrender.com/nexus
```
The JSON should report `"layers_ok": [..., "L0_vault", ...]`. If `L0_vault` is in `layers_fail`, the key was rejected — re-generate and try again.

---

## ✅ Render env audit (verified against latest screenshots — 2026-04-28)

### Already set ✓
| Variable | Status |
|---|---|
| `ADMIN_TELEGRAM_ID` | ✓ |
| `CEREBRAS_API_KEY` | ✓ |
| `CF_RELAY_SECRET` / `CF_WORKER_URL` | ✓ wired into stealth_engine + nexus_config |
| `CREDENTIAL_VAULT_KEY` | ✓ (verify it's a 44-char Fernet key, not the command string) |
| `DATABASE_PATH` | ✓ |
| `GEMINI_API_KEY` | ✓ |
| `GROQ_API_KEY` | ✓ |
| `JOB_LOW_TTL_DAYS=15` / `JOB_HIGH_TTL_DAYS=25` / `JOB_SCORE_TIER_CUTOFF=60` | ✓ |
| `LOG_LEVEL` | ✓ |
| `NEXUS_ENABLED=true` | ✓ |
| `NEXUS_SUPER_ADMIN_ID=1284690336` | ✓ |
| `OPENROUTER_API_KEY` | ✓ |
| `RENDER_DEPLOY` / `SCHEDULE_MODE` | ✓ |
| `SCRAPEDO_TOKEN` / `SCRAPERAPI_KEY` / `SCRAPINGBEE_KEY` | ✓ |
| `SERP_API_KEY` | ✓ |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | ✓ |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | ✓ |
| `TIMEZONE` / `WEB_CONCURRENCY` / `WEBSHARE_KEY` | ✓ |

### Still missing — required for full NEXUS v0.2 ✗
| Variable | Purpose | How to generate |
|---|---|---|
| `NEXUS_CALLBACK_SECRET` | HMAC for one-tap apply callbacks | online Python: `import secrets; print(secrets.token_hex(32))` |
| `SESSION_VAULT_KEY` | Encrypts portal session cookies (NEXUS L0) | use any of the four free methods above to generate a Fernet key |

### ⚠️ Still needs to be DELETED
| Variable | Why |
|---|---|
| `FORCE_DB_RESET` | Visible in latest screenshot. **Click the trash icon and remove it.** Wipes SQLite on every boot. |

### Optional — only set if you want the feature
| Variable | Purpose | Where to get it |
|---|---|---|
| `TG_API_ID` + `TG_API_HASH` | Telethon userbot listener (A-16) — Telegram channel scraping | https://my.telegram.org/apps |
| `OPENROUTER_API_KEY` | Cheap GPT-4-class fallback for cover-letter LLM | https://openrouter.ai/keys (free $1 trial) |
| `MISTRAL_API_KEY` | Tertiary LLM fallback | https://console.mistral.ai/api-keys |
| `BING_API_KEY` | Discovery DDG → Bing failover (web search) | **See "How to get Bing API key" below** |
| `BREVO_API_KEY` + `BREVO_SENDER_EMAIL` | A-15 email auto-applier | https://app.brevo.com/settings/keys/api (free 300/day) |
| `HUNTER_IO_KEY` | Recruiter-email lookup for A-15 | https://hunter.io/api-keys (free 25/month) |
| `X_BEARER_TOKEN` | Twitter/X Layer 1 dark-channel scraper | https://developer.x.com/en/portal/dashboard |
| `RENDER_KEEPALIVE_URL` | Self-ping URL when not on Render's natural URL | leave blank if your service is on `*.onrender.com` |

#### How to get a Bing API key (Microsoft deprecated the original Bing Search API on **Aug 11, 2025**)

The original `Bing Web Search API v7` from Azure Cognitive Services is **shut down**. Microsoft now points you at *Microsoft Grounding with Bing Search* via Azure AI Foundry, which has a paid tier only ($35 per 1000 queries).

**Recommended free alternatives** (the codebase already supports these via `SERP_API_KEY` and `SCRAPERAPI_KEY` which you already have set):

1. **Brave Search API** — 2,000 free queries/month. https://api.search.brave.com/app/keys
   - The fastest free replacement. Set as `BRAVE_SEARCH_KEY` if/when we add support (currently not consumed).
2. **DuckDuckGo (no key needed)** — already used by `core.discovery_engine` as the primary fallback.
3. **SerpAPI** — `SERP_API_KEY` is already set in your env. This is what the discovery layer actually uses.

**Bottom line: leave `BING_API_KEY` empty.** The discovery layer falls through DDG → SerpAPI → ScraperAPI and works fine without it. Microsoft's replacement is paid-only and adds nothing the free chain doesn't already cover.

---

## 🧭 What you still need to do (latest state, 2026-04-28)

You're 90% there. Two things remaining:

1. **Delete** `FORCE_DB_RESET` (Environment tab → red trash icon → save).
2. **Add** two new vars:
   - `NEXUS_CALLBACK_SECRET` — generate with online Python: `import secrets; print(secrets.token_hex(32))` → paste output (a 64-char hex string)
   - `SESSION_VAULT_KEY` — generate a **fresh Fernet key** (different from CREDENTIAL_VAULT_KEY) using any free method in section above
3. Click **Save, rebuild, and deploy**.
4. After redeploy, verify:
   - `https://mba-agent-71hu.onrender.com/nexus` → `layers_ok` should include `L0_vault`
   - Open mini-app at `/app/` from Telegram → **Admin** tab should appear in bottom bar
   - Upload your CV via Settings → check Supabase `user_cvs` table — should have one row

## ⚠️ SECURITY NOTE — leaked GEMINI_API_KEY

Your screenshot revealed `GEMINI_API_KEY` in plain text (visible because the eye icon was on). **Rotate it immediately:**
1. Go to https://aistudio.google.com/apikey
2. Click the trash icon next to the leaked key
3. Click *Create API key* → copy new value
4. Update `GEMINI_API_KEY` in Render
5. *Save, rebuild, and deploy*

For future screenshots: click the eye icon to mask values before taking the screenshot.

---

## 🌐 Cloudflare Worker integration audit (2026-04-28)

You have `CF_WORKER_URL` and `CF_RELAY_SECRET` set in Render. Here is exactly which parts of the NEXUS pipeline use them:

| Component | Uses CF Worker? | Where |
|---|---|---|
| Legacy primary scraper (`agents/a03_primary_scraper.py`) | ✅ via `core.stealth_engine.get_stealth_client()` | every HTTP fetch tries CF relay first, falls back to Webshare |
| ATS crawler (`agents/a04_ats_crawler.py`) | ✅ same path | same |
| Auto-apply HTTP probes (`agents/a13_auto_apply.py`) | ✅ same path | login flows + form GETs |
| NEXUS L2 discovery (Crawl4AI) | ⚠️ **does NOT** use CF relay | uses Camoufox + Webshare directly. CF relay is a JSON request-relay (POST /relay), not an HTTP CONNECT proxy, so a real browser can't tunnel through it. |

**This is the correct architecture** — NEXUS L2 needs a real browser (Camoufox stealth) for portals like LinkedIn/Naukri that JS-render their listings, while the legacy scrapers use plain HTTP and benefit from CF-edge IP rotation.

### Verify your Cloudflare Worker is alive
```bash
# From any browser, hit your worker's health endpoint:
curl https://YOUR-WORKER.workers.dev/health
# Expected: {"status":"ok","service":"firstmover-relay","version":"2.0", ...}
```

### Verify Render is using it
After redeploy, check Render logs for either:
- `cloudflare_relay_request_ok` (good — using CF)
- `Cloudflare relay not configured` (bad — env vars not picked up)
- `CF Relay auth failed (403)` (bad — `CF_RELAY_SECRET` doesn't match the worker's `RELAY_SECRET` binding)

### Bug fixed in PR #67 (2026-04-28)
`core/nexus_config.py` was reading the env var as `CF_RELAY_WORKER_URL` (with the word "RELAY" in the middle) while every other module reads `CF_WORKER_URL`. The mismatch meant `STACK.cf_worker_url` was always empty in NEXUS contexts. Now fixed to read both names with `CF_WORKER_URL` taking priority. **Same fix applied to `TG_BOT_TOKEN` / `TG_CHAT_ID`** which were being read under the longer `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` names that aren't in your Render env.

---

## 📋 What each NEXUS layer needs

| Layer | What it does | Render 512 MB (light) | Worker 2 GB (full) |
|---|---|---|---|
| L0 — Vault | Per-portal encrypted session cookies | needs `SESSION_VAULT_KEY` | same |
| L0a — Access Control | RBAC + admin gate | needs `NEXUS_SUPER_ADMIN_ID` | same |
| L0b — CV Intake | Per-user CV parsing | needs Supabase + `CREDENTIAL_VAULT_KEY` | same |
| L1 — Stealth Triad | Skyvern → Browser-Use → Camoufox | runs in NullAdapter mode | needs `nexus_bootstrap.sh` |
| L2 — Discovery | Crawl4AI universal scraper | runs in NullAdapter mode | needs Crawl4AI installed |
| L3 — Scoring | 9-dim scorer + pgvector blend | runs (keyword-only) | full pgvector path |
| L4 — Answer RAG | Form-question → answer cache | runs (keyword-only) | full embedding path |
| L5 — CAPTCHA | 4-tier solver | needs `GEMINI_API_KEY` | same |
| L6 — Orchestrator + Risk Governor | Apps/hour throttle, ban prevention | runs | runs |
| L7 — Dedup | Semantic + exact dedup | runs (keyword-only) | full pgvector cosine |
| L8 — Interview Intel | Post-application followups | runs | runs |
| L9 — Telegram Dashboard | `/help`, `/queue`, `/apply_now` cmds | runs | runs |
