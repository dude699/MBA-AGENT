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

### How to fix (30 seconds)

1. Open Render's **Shell** tab on this service.
2. Run:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Copy the **output** — a 44-character base64 string ending in `=`. It looks like:
   ```
   uQ5T2yEcL4-8mHs7wVnK_p-9XzZJv0qN3fTxR1iY6oA=
   ```
4. Open `Environment` → click the eye-pencil next to `CREDENTIAL_VAULT_KEY` → paste the output → **Save, rebuild, and deploy**.

> ✅ Same trick works for `NEXUS_CALLBACK_SECRET` (use `python -c "import secrets; print(secrets.token_hex(32))"` instead).

---

## ✅ Render env audit (against your screenshots)

### Already set ✓
| Variable | Visible in screenshot |
|---|---|
| `ADMIN_TELEGRAM_ID` | ✓ |
| `CEREBRAS_API_KEY` | ✓ |
| `CF_RELAY_SECRET` | ✓ |
| `CF_WORKER_URL` | ✓ |
| `DATABASE_PATH` | ✓ |
| `GROQ_API_KEY` | ✓ |
| `LOG_LEVEL` | ✓ |
| `RENDER_DEPLOY` | ✓ |
| `SCHEDULE_MODE` | ✓ |
| `SCRAPEDO_TOKEN` / `SCRAPERAPI_KEY` / `SCRAPINGBEE_KEY` | ✓ |
| `SERP_API_KEY` | ✓ |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | ✓ |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | ✓ |
| `TIMEZONE` | ✓ |
| `WEB_CONCURRENCY` / `WEBSHARE_KEY` | ✓ |
| `CREDENTIAL_VAULT_KEY` | ⚠️ **wrong value — fix per the box above** |

### Missing — required for NEXUS v0.2 ✗
| Variable | Purpose | How to generate |
|---|---|---|
| `NEXUS_ENABLED` | Master switch for NEXUS v0.2 layers (L0–L9) | set to `true` |
| `NEXUS_SUPER_ADMIN_ID` | Locks `/api/admin/*` to your Telegram ID | set to `1284690336` |
| `NEXUS_CALLBACK_SECRET` | HMAC for one-tap apply callbacks | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_VAULT_KEY` | Encrypts portal session cookies (NEXUS L0) | same Fernet command as above |
| `GEMINI_API_KEY` | Scoring (L3) + CAPTCHA T1 (L5) | https://aistudio.google.com/apikey |
| `DATABASE_URL` | Postgres + pgvector (FULL mode L7 dedup) | leave **blank** on free 512 MB tier |
| `JOB_LOW_TTL_DAYS` | Retention TTL for low-score (<60) jobs | `15` |
| `JOB_HIGH_TTL_DAYS` | Retention TTL for high-score (≥60) jobs | `25` |
| `JOB_SCORE_TIER_CUTOFF` | match_score boundary between tiers | `60` |

### Optional — only set if you want the feature
| Variable | Purpose |
|---|---|
| `TG_API_ID` + `TG_API_HASH` | Telethon userbot listener (A-16) — only if you want Telegram channel scraping |
| `OPENROUTER_API_KEY` | Cheap GPT-4-class fallback for cover-letter LLM |
| `MISTRAL_API_KEY` | Tertiary LLM fallback |
| `BING_API_KEY` | Discovery DDG → Bing failover |
| `BREVO_API_KEY` + `BREVO_SENDER_EMAIL` | A-15 email auto-applier |
| `HUNTER_IO_KEY` | Recruiter-email lookup for A-15 |
| `X_BEARER_TOKEN` | Twitter/X Layer 1 dark-channel scraper |
| `RENDER_KEEPALIVE_URL` | Self-ping URL when not on Render's natural URL |
| `CF_RELAY_WORKER_URL` | IP-continuity proxy (Innovation 3) |

### ❌ Should be REMOVED
| Variable | Why |
|---|---|
| `FORCE_DB_RESET` | Visible in screenshot. Wipes SQLite on every boot. The only reason this exists is for one-time reset emergencies — leaving it on means every redeploy starts with an empty DB, which is **why your `latest_jobs` looks fine but `clean_listings` keeps looking empty**. **DELETE this var.** |

---

## 🧭 Step-by-step fix sequence (in Render dashboard)

1. **Delete** `FORCE_DB_RESET` (Environment tab → red trash icon → save).
2. **Edit** `CREDENTIAL_VAULT_KEY` → paste the actual Fernet key output.
3. **Add** these new vars (Add variable button):
   - `NEXUS_ENABLED` = `true`
   - `NEXUS_SUPER_ADMIN_ID` = `1284690336`
   - `NEXUS_CALLBACK_SECRET` = output of `python -c "import secrets; print(secrets.token_hex(32))"`
   - `SESSION_VAULT_KEY` = output of the Fernet command (a fresh, different key — don't reuse the credential vault key)
   - `GEMINI_API_KEY` = your key from AI Studio
   - `JOB_LOW_TTL_DAYS` = `15`
   - `JOB_HIGH_TTL_DAYS` = `25`
   - `JOB_SCORE_TIER_CUTOFF` = `60`
4. Click **Save, rebuild, and deploy**.
5. Once redeployed, hit `https://mba-agent-71hu.onrender.com/nexus` — you should see `triad_live: true` (or false if FULL mode is off, which is fine on the 512 MB tier — light mode still gives you L0/L3/L7).
6. Open the mini-app at `/app/` from inside Telegram. The **Admin** tab should appear in the bottom bar (only on your account).

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
