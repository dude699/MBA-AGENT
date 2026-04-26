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
- [ ] `core/crawl4ai_discovery.py` — Crawl4AI universal extraction → NormalisedJob ⏳
- [ ] `core/reactive_discovery.py` — RSS/webhook event-driven layer (5–15 min apply latency) ⏳
- [ ] `agents/n03_crawl4ai_scraper.py` — Per-portal Crawl4AI scraper agent ⏳

### Phase F — Layer 3 · Scoring & Match
- [ ] `core/scoring_engine_v2.py` — 9-dimension scoring (incl. Cultural Fit, Trajectory) ⏳
- [ ] `core/pgvector_matcher.py` — Groq embeddings + cosine semantic profile match ⏳

### Phase G — Layer 4 · Adaptive Answers
- [ ] `core/answer_rag.py` — Top-3 retrieval + Cerebras voice-consistent generation + validator ⏳

### Phase H — Layer 5 · CAPTCHA
- [ ] `core/captcha_resolver.py` — T1 vision · T2 audio · T3 Telegram relay · T4 surgical fallback ⏳

### Phase I — Layer 6 · Orchestrator
- [ ] `core/orchestrator.py` — Priority queue + dynamic re-scoring + apply windows + Risk Governor ⏳

### Phase J — Layer 7 · Dedup
- [ ] `core/dedup_semantic.py` — pgvector cosine ≥0.88 + exact SHA256 match ⏳

### Phase K — Layer 8 · Interview Intel
- [ ] `core/interview_intel.py` — Gmail/LinkedIn/WhatsApp signals + 90s Crawl4AI briefing ⏳

### Phase L — Layer 9 · Telegram Dashboard
- [ ] `core/telegram_dashboard.py` — 15+ commands + inline buttons + digests ⏳

### Phase M — The 15 Innovations
- [ ] `core/innovations.py` — Trajectory scoring, FOMO/deadline cliffs, stealth warmup, multi-resume routing, employer perspective, applicant-count estimator, applied-but-not-viewed loop, salary normaliser, cold-start bypass, portal benchmarking ⏳

### Phase N — Bootstrap
- [ ] `scripts/nexus_bootstrap.sh` — The exact first 4 commands from the doc ⏳

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

> _Last update: bootstrapping plan._
