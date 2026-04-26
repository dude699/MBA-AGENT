# NEXUS v0.2 — Build Execution Plan & Live Progress Tracker

> **Source Doc**: `NEXUS_v0.2_Architecture.docx` (verified April 26, 2026)
> **Author**: MD Abuzar Salim · 25IBMMA143 · AMU International Business
> **Branch**: `genspark_ai_developer` → PR to `main`
> **Rule**: Every file created/updated → immediate `git commit` + `git push` → PR auto-updates with progress.

---

## 🎯 The Mission

> **Zero Selectors. Zero Bans. Zero Manual Input After Setup.**

NEXUS v0.2 is a full architectural rebuild on verified 2026 tooling, replacing the three most brittle assumptions of PRISM v0.1:

| PRISM v0.1 (brittle) | NEXUS v0.2 (verified 2026) |
|----------------------|----------------------------|
| Custom per-portal scrapers | **Crawl4AI** (#1 GitHub crawler, Apache 2.0) |
| Manual Playwright + selectors | **Browser-Use v2.0** + **Skyvern 2.0** (zero selectors) |
| Vision-screenshot fill plans | **Skyvern self-generated + self-healed Playwright code** |

---

## 🧱 The 10-Layer Architecture

| Layer | Name | Responsibility |
|-------|------|----------------|
| 0 | Cryptographic Credential Vault | Encrypted sessions + Freshness Oracle |
| 1 | Stealth Browser Triad | Camoufox + Browser-Use v2.0 + Skyvern 2.0 |
| 2 | Universal Job Discovery | Crawl4AI + Reactive (RSS/webhook) layer |
| 3 | Multi-Dimensional Scoring | 9 dimensions + pgvector profile match |
| 4 | Adaptive Answer Generation | RAG over answer bank → Cerebras |
| 5 | Four-Tier CAPTCHA Resolution | Vision · Audio · Telegram · Surgical Fallback |
| 6 | Intelligent Application Orchestrator | Priority Queue + Risk Governor |
| 7 | Semantic Deduplication | pgvector cosine + exact match |
| 8 | Interview Intelligence | 90-second briefing package |
| 9 | Telegram Intelligence Dashboard | Full command surface + inline buttons |

---

## 📋 Live File Build Tracker

> ✅ = Committed & Pushed · 🔄 = In Progress · ⏳ = Pending
> **Each row commits and pushes to genspark_ai_developer immediately on completion.**

### Phase A — Foundation & Plan
- [x] `NEXUS_V02_PLAN.md` — this living plan ✅
- [x] `docs/NEXUS_ARCHITECTURE.md` — 10-layer architecture deep-dive ✅

### Phase B — Schema & Config (data backbone)
- [x] `data/nexus_v02_schema.sql` — pgvector + vault + queue + answer_bank ✅
- [x] `core/nexus_config.py` — central config: portal limits, scoring weights, risk thresholds ✅
- [x] `requirements.txt` + `requirements-nexus.txt` — Camoufox/Browser-Use/Crawl4AI/Skyvern ✅

### Phase C — Layer 0 · Cryptographic Vault
- [x] `core/session_vault.py` — AES-256 vault + Session Freshness Oracle (health 0–100) ✅

### Phase D — Layer 1 · Stealth Browser Triad
- [x] `core/stealth_triad.py` — Decision tree: known portal → Skyvern code · new → Browser-Use → cache ✅
- [x] `agents/n01_skyvern_apply.py` — Skyvern code-cache executor ✅
- [x] `agents/n02_browser_use_apply.py` — Browser-Use v2.0 AI apply (new portals) ✅

### Phase E — Layer 2 · Universal Discovery
- [x] `core/crawl4ai_discovery.py` — Crawl4AI universal extraction → NormalisedJob ✅
- [x] `core/reactive_discovery.py` — RSS/webhook event-driven layer (5–15 min apply latency) ✅
- [x] `agents/n03_crawl4ai_scraper.py` — Per-portal Crawl4AI scraper agent ✅

### Phase F — Layer 3 · Scoring & Match
- [x] `core/scoring_engine_v2.py` — 9-dimension scoring (incl. Cultural Fit, Trajectory) ✅
- [x] `core/pgvector_matcher.py` — Groq embeddings + cosine semantic profile match ✅

### Phase G — Layer 4 · Adaptive Answers
- [x] `core/answer_rag.py` — Top-3 retrieval + Cerebras voice-consistent generation + validator ✅

### Phase H — Layer 5 · CAPTCHA
- [x] `core/captcha_resolver.py` — T1 vision · T2 audio · T3 Telegram relay · T4 surgical fallback ✅

### Phase I — Layer 6 · Orchestrator
- [x] `core/orchestrator.py` — Priority queue + dynamic re-scoring + apply windows + Risk Governor ✅

### Phase J — Layer 7 · Dedup
- [x] `core/dedup_semantic.py` — pgvector cosine ≥0.88 + exact SHA256 match ✅

### Phase K — Layer 8 · Interview Intel
- [x] `core/interview_intel.py` — Gmail/LinkedIn/WhatsApp signals + 90s Crawl4AI briefing ✅

### Phase L — Layer 9 · Telegram Dashboard
- [x] `core/telegram_dashboard.py` — 15+ commands + inline buttons + digests ✅

### Phase M — The 15 Innovations
- [x] `core/innovations.py` — Trajectory scoring, FOMO/deadline cliffs, stealth warmup, multi-resume routing, employer perspective, applicant-count estimator, applied-but-not-viewed loop, salary normaliser, cold-start bypass, portal benchmarking ✅

### Phase N — Bootstrap
- [x] `scripts/nexus_bootstrap.sh` — The exact first 4 commands from the doc ✅

### Phase O — Wire-up (PRISM ↔ NEXUS coexistence)
- [x] `core/nexus_runtime.py` — single ignition point: assembles Layer 0–9 + Telegram dashboard, runs queue tick + rescore loops, publishes `get_runtime()` singleton ✅
- [x] `main.py` — Phase 10/11 boot hook (env-gated by `NEXUS_ENABLED`), graceful-shutdown integration, `_nexus` field on Application ✅
- [x] `core/keepalive.py` — public `/nexus` endpoint returning live layer snapshot (503 when disabled) ✅
- [x] `core/nexus_config.py` — convenience aliases `PORTALS`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` so the dashboard imports cleanly ✅
- [x] `.env.example` + `render.yaml` — `NEXUS_ENABLED`, `SESSION_VAULT_KEY`, `GEMINI_API_KEY`, `DATABASE_URL`, profile vars ✅

---

## 📦 The Verified Free Stack (April 2026)

| Layer | Tool | Free Tier |
|-------|------|-----------|
| Browser foundation | Camoufox (coryking fork) | MIT — Firefox 142.0.1 |
| AI Browser Agent | Browser-Use v2.0 | MIT — 79K stars |
| RPA Agent | Skyvern 2.0 (YC S23) | Apache 2.0 |
| Universal Scraper | Crawl4AI | Apache 2.0 — #1 GitHub |
| CAPTCHA T1 | ai-captcha-bypass + Gemini 2.5 Flash | 500 RPD free |
| CAPTCHA T2 | Groq Whisper Large v3 | 14,400 RPD free |
| AI Scoring | Gemini 2.5 Flash-Lite | 1,000 RPD/project |
| LLM Extraction | Groq llama-3.3-70b | ~14,400 RPD free |
| Custom Answers | Cerebras llama-3.3-70b | ~900 RPD free |
| Vector DB | Supabase pgvector | 500 MB free |
| Hosting | Render.com | 750 hrs/mo free |
| Interface | Telegram Bot API | Free forever |
| Proxy/IP | Cloudflare Workers | 100K req/day free |

> ⚠️ Gemini 2.0 Flash retired March 3, 2026 — **NOT REFERENCED** anywhere in NEXUS.

---

## 🗓 8-Week Build Sprint (from the doc)

- **Week 1** — Foundation + The Fix (Camoufox + session vault → kill the login error)
- **Week 2** — Crawl4AI discovery (3 portals) + pgvector dedup
- **Week 3** — 9-dim scoring + Skyvern code cache
- **Week 4** — Browser-Use integration + Answer RAG
- **Week 5** — CAPTCHA engine + Risk Governor
- **Week 6** — Session Oracle + warmup + remaining 8 portals
- **Week 7** — Interview Intelligence + Telegram dashboard
- **Week 8** — Trajectory scoring + Employer perspective + multi-resume + load test

---

## 🛡 The Risk Governor (Layer 6 — Pre-emptive ban prevention)

| Signal | Threshold | Action |
|--------|-----------|--------|
| Apps/hour LinkedIn | > 8 | Throttle |
| Apps/hour Internshala | > 15 | Throttle |
| Apps/hour Naukri | > 12 | Throttle |
| CAPTCHA rate | > 15% | -50% rate |
| Session age | > 60 days | Reduce rate |
| Error rate | > 10% in 20 attempts | Pause portal + alert |
| Time-of-day variance | High | Snap to human hours |

---

## 🔁 Live PR

This plan auto-updates after every committed file. Watch the checkboxes flip from `[ ]` → `[x]` in the PR diff in real-time.

## ✅ Build Complete — All files committed, pushed & wired

| Phase | Files | Status |
|-------|-------|--------|
| A — Foundation | `NEXUS_V02_PLAN.md`, `docs/NEXUS_ARCHITECTURE.md` | ✅ |
| B — Schema & Config | `data/nexus_v02_schema.sql`, `core/nexus_config.py`, `requirements*.txt` | ✅ |
| C — Layer 0 Vault | `core/session_vault.py` | ✅ |
| D — Layer 1 Stealth Triad | `core/stealth_triad.py`, `agents/n01_skyvern_apply.py`, `agents/n02_browser_use_apply.py` | ✅ |
| E — Layer 2 Discovery | `core/crawl4ai_discovery.py`, `core/reactive_discovery.py`, `agents/n03_crawl4ai_scraper.py` | ✅ |
| F — Layer 3 Scoring | `core/scoring_engine_v2.py`, `core/pgvector_matcher.py` | ✅ |
| G — Layer 4 Answers | `core/answer_rag.py` | ✅ |
| H — Layer 5 CAPTCHA | `core/captcha_resolver.py` | ✅ |
| I — Layer 6 Orchestrator | `core/orchestrator.py` | ✅ |
| J — Layer 7 Dedup | `core/dedup_semantic.py` | ✅ |
| K — Layer 8 Interview | `core/interview_intel.py` | ✅ |
| L — Layer 9 Telegram | `core/telegram_dashboard.py` | ✅ |
| M — Innovations | `core/innovations.py` | ✅ |
| N — Bootstrap | `scripts/nexus_bootstrap.sh` | ✅ |
| **O — Wire-up** | `core/nexus_runtime.py`, `main.py` (Phase 10), `core/keepalive.py` (`/nexus`), `.env.example`, `render.yaml` | ✅ |

---

## 🚀 Operator Ship Path (after this PR is merged)

### Step 1 — Render web service (light mode, free 512MB tier)
1. In the Render dashboard, open the service → **Environment** tab.
2. Set `NEXUS_ENABLED=true`.
3. (Optional, recommended) generate `SESSION_VAULT_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. Add `GEMINI_API_KEY`, `DATABASE_URL`, `NEXUS_USER_HANDLE`.
5. Trigger a deploy. Phase 10 will boot all 6 implementable layers in light mode.
6. Verify: `GET https://<your-service>.onrender.com/nexus` → JSON with `layers_ok`.

### Step 2 — Worker dyno (FULL mode, ≥ 2 GB RAM)
On a separate beefier worker process, run the bootstrap installer (the exact "first 4 commands" from the doc):
```bash
chmod +x scripts/nexus_bootstrap.sh
./scripts/nexus_bootstrap.sh                       # all 4 steps
# OR step-by-step:
./scripts/nexus_bootstrap.sh --step schema         # apply pgvector schema
./scripts/nexus_bootstrap.sh --step deps           # heavy stack
./scripts/nexus_bootstrap.sh --step camoufox       # FF142 fork
./scripts/nexus_bootstrap.sh --step vault          # gen key + capture sessions
```
Then start the same `python main.py` on the worker — Phase 10 will detect `requirements-nexus.txt` is installed and flip `triad_live=True` automatically.

### Step 3 — Capture sessions (one-time per portal)
```bash
python -m core.session_vault capture --portal linkedin
python -m core.session_vault capture --portal naukri
python -m core.session_vault capture --portal internshala
```

### Step 4 — Watch the cockpit
The Telegram dashboard polls automatically once `TG_BOT_TOKEN` is set. Use `/help` for the 15-command surface.

> _Last update: PR #64 wired into PRISM via Phase O — main.py boots NEXUS as Phase 10/11, graceful shutdown integrated, `/nexus` endpoint live, opt-in via `NEXUS_ENABLED=true`._
