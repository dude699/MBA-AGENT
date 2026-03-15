# PRISM v0.1 — PRECISION RECRUITMENT INTELLIGENCE & SCORING MACHINE

## System Overhaul Plan: OFM v5.x → PRISM v0.1

**Status**: IN PROGRESS
**Branch**: `genspark_ai_developer`
**Date**: 2026-03-15
**Author**: AI Developer (automated implementation of @abuzarkhan999's PRISM architecture document)

---

## ARCHITECTURE SUMMARY

| Metric | OFM v5.x (Current) | PRISM v0.1 (Target) |
|--------|-------------------|---------------------|
| Agents | 13 (A-01 → A-13) | 20 (A-01 → A-20) |
| AI Providers | 2 (Groq + Cerebras) | 5 (Groq, Cerebras, OpenRouter, Groq Compound, Mistral) |
| Tool Types | 8 | 15 |
| Schedule | Daily (single wave) | 3-Wave Weekly (Mon/Wed/Fri, Tue/Thu/Sat, Night) |
| PPO Variables | 10 | 11 (+ Semantic CV-JD V11) |
| Database Tables | 12 | 14 (+ company_intel, sector_momentum) |
| Email Integration | None | Brevo (300/day free) |
| CV Tailoring | None | WeasyPrint PDF generation |
| Real-time TG | Batch only | Telethon MTProto continuous |
| Cost | $0/day | $0/day |

---

## FILE IMPLEMENTATION PLAN

### Legend
- 🔴 = Not Started
- 🟡 = In Progress
- 🟢 = Complete
- **[NEW]** = Brand new file
- **[UPD]** = Updating existing file

---

### PHASE 0 — CRITICAL FIXES (Foundation)

| # | File | Type | Est. Lines | Status | Description |
|---|------|------|-----------|--------|-------------|
| 1 | `core/config.py` | [UPD] | ~2400 | 🔴 | Add OpenRouter, Groq Compound, Mistral, Brevo configs; PPO V11 with semantic match; new env vars |
| 2 | `core/ai_router.py` | [UPD] | ~2500 | 🔴 | 5-provider routing engine; OpenRouter (1M ctx), Groq Compound (agentic), Mistral fallback; circuit breakers per provider |
| 3 | `core/database.py` | [UPD] | ~3500 | 🔴 | Add 5 missing methods; 2 new tables (company_intel, sector_momentum); PRISM schema v3 |
| 4 | `requirements.txt` | [UPD] | ~80 | 🔴 | Add openai (OpenRouter), weasyprint, sentence-transformers, brevo-python, hunter-python |
| 5 | `.env.example` | [UPD] | ~100 | 🔴 | Add OPENROUTER_API_KEY, MISTRAL_API_KEY, BREVO_API_KEY, HUNTER_IO_KEY, etc. |

### PHASE 1 — NEW AGENTS (High-Impact)

| # | File | Type | Est. Lines | Status | Description |
|---|------|------|-----------|--------|-------------|
| 6 | `agents/a14_multi_model_router.py` | [NEW] | ~1200 | 🔴 | A-14: Multi-Model Router — AI traffic controller, quota mgr, 5-provider failover chain with real-time health monitoring |
| 7 | `agents/a15_email_applier.py` | [NEW] | ~1400 | 🔴 | A-15: Email Auto-Applier — Brevo cold outreach to HR/Alumni, personalization, webhook tracking, daily 09:30 IST |
| 8 | `agents/a16_tg_listener.py` | [NEW] | ~1300 | 🔴 | A-16: Telegram Group Monitor — Real-time Telethon MTProto listener for 10-15 MBA groups, instant extraction |
| 9 | `agents/a17_scheduler.py` | [NEW] | ~1500 | 🔴 | A-17: Adaptive Scheduler — Dynamic schedule adjustment based on portal health, AI quota, success rates |
| 10 | `agents/a18_cv_enhancer.py` | [NEW] | ~1400 | 🔴 | A-18: CV Intelligence Enhancer — ATS keyword gap fill, WeasyPrint PDF, per-application tailoring |
| 11 | `agents/a19_outcome_amplifier.py` | [NEW] | ~1200 | 🔴 | A-19: Outcome Amplifier — Application status tracking, 7-day follow-up emails, Internshala status API |
| 12 | `agents/a20_company_intel.py` | [NEW] | ~1300 | 🔴 | A-20: Deep Company Intel — Pre-application Groq Compound research, 500-word intel briefs, personalization hooks |

### PHASE 1.5 — NEW CORE MODULES

| # | File | Type | Est. Lines | Status | Description |
|---|------|------|-----------|--------|-------------|
| 13 | `core/email_sender.py` | [NEW] | ~1100 | 🔴 | Brevo REST API integration — send_email(), webhook handler, open/click tracking, 300/day quota |
| 14 | `core/cv_generator.py` | [NEW] | ~1100 | 🔴 | WeasyPrint PDF engine — HTML-to-PDF CV rendering, bullet rewrite injection, professional templates |
| 15 | `core/embedding_engine.py` | [NEW] | ~1000 | 🔴 | Local sentence-transformers (all-MiniLM-L6-v2) — 384-dim embeddings for dedup Layer 4 + PPO V11 |

### PHASE 2 — UPGRADE EXISTING AGENTS

| # | File | Type | Est. Lines | Status | Description |
|---|------|------|-----------|--------|-------------|
| 16 | `agents/a03_primary_scraper.py` | [UPD] | ~2500 | 🔴 | Fix Naukri: direct API v2 as PRIMARY, DDG fallback; Internshala mobile Ajax with category IDs |
| 17 | `agents/a07_intelligence_enricher.py` | [UPD] | ~1600 | 🔴 | Groq Compound live funding verification; enhanced CIRS; Blue Ocean detection upgrade |
| 18 | `agents/a08_ppo_optimizer.py` | [UPD] | ~1400 | 🔴 | PPO V11: Semantic CV-JD cosine similarity via embedding_engine; 11-variable scoring |
| 19 | `agents/a10_ats_simulator.py` | [UPD] | ~1200 | 🔴 | OpenRouter Gemini 2.0 Flash (1M context); full JD+CV analysis; 3 bullet rewrites |
| 20 | `agents/a13_auto_apply.py` | [UPD] | ~1500 | 🔴 | Pre-check with A-18 CV tailoring; portal-specific submission (Internshala, Greenhouse, Lever) |

### PHASE 3 — ORCHESTRATION UPGRADES

| # | File | Type | Est. Lines | Status | Description |
|---|------|------|-----------|--------|-------------|
| 21 | `core/weekly_scheduler.py` | [UPD] | ~2200 | 🔴 | PRISM 3-wave schedule: Wave 1 (05:15), Wave 2 (14:00), Night (22:30); Sunday specials |
| 22 | `main.py` | [UPD] | ~1200 | 🔴 | PRISM v0.1 banner; 20-agent heartbeats; Phase 8.5 Telethon; Phase 9 embedding warmup |
| 23 | `agents/__init__.py` | [UPD] | ~50 | 🔴 | Export all 20 agents |

---

## IMPLEMENTATION ORDER (Sequential)

Each file is committed individually. PR updated after each commit.

```
Step 01: PRISM_V01_UPGRADE_PLAN.md          ← This file (plan) ✅
Step 02: core/config.py                      ← Phase 0: Foundation config
Step 03: core/database.py                    ← Phase 0: Schema + missing methods
Step 04: core/ai_router.py                   ← Phase 0: 5-provider routing
Step 05: core/embedding_engine.py            ← Phase 1.5: Embeddings (PPO V11 dep)
Step 06: core/email_sender.py                ← Phase 1.5: Brevo (A-15 dep)
Step 07: core/cv_generator.py                ← Phase 1.5: PDF gen (A-18 dep)
Step 08: agents/a14_multi_model_router.py    ← Phase 1: AI traffic controller
Step 09: agents/a15_email_applier.py         ← Phase 1: Email outreach
Step 10: agents/a16_tg_listener.py           ← Phase 1: Real-time TG
Step 11: agents/a17_scheduler.py             ← Phase 1: Adaptive scheduler
Step 12: agents/a18_cv_enhancer.py           ← Phase 1: CV tailoring
Step 13: agents/a19_outcome_amplifier.py     ← Phase 1: Follow-up tracker
Step 14: agents/a20_company_intel.py         ← Phase 1: Deep intel
Step 15: agents/a03_primary_scraper.py       ← Phase 2: Naukri API fix
Step 16: agents/a07_intelligence_enricher.py ← Phase 2: Groq Compound
Step 17: agents/a08_ppo_optimizer.py         ← Phase 2: PPO V11
Step 18: agents/a10_ats_simulator.py         ← Phase 2: OpenRouter 1M
Step 19: agents/a13_auto_apply.py            ← Phase 2: Portal submission
Step 20: core/weekly_scheduler.py            ← Phase 3: 3-wave schedule
Step 21: main.py                             ← Phase 3: PRISM orchestrator
Step 22: requirements.txt                    ← Dependencies
Step 23: .env.example                        ← New env vars
Step 24: agents/__init__.py                  ← Agent exports
```

---

## RENDER ENVIRONMENT SETUP (New Components)

### New Environment Variables to Add in Render Dashboard

```bash
# === PRISM v0.1 NEW PROVIDERS ===
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx    # Free: 200 req/day, 20 RPM
MISTRAL_API_KEY=xxxxxxxxxxxx                # Free: 1B tokens/month, 2 RPM
BREVO_API_KEY=xkeysib-xxxxxxxxxxxx         # Free: 300 emails/day
HUNTER_IO_KEY=xxxxxxxxxxxx                  # Free: 25 searches/month

# === PRISM v0.1 GROQ COMPOUND ===
# Uses same GROQ_API_KEY — Compound Beta is a model, not separate provider
# Model: compound-beta (auto web_search + visit_url)

# === PRISM v0.1 EMBEDDING ===
# sentence-transformers runs LOCALLY — no API key needed
# Model: all-MiniLM-L6-v2 (384-dim, ~80MB)
# First load takes ~30s on Render, then cached in memory
LAZY_LOAD_EMBEDDINGS=true   # Don't load at startup, load on first use
```

### Render Build Command Update
```bash
pip install -r requirements.txt && cd mini-app && npm install --include=dev && npm run build
```

### New Python Dependencies (pip install)
```
openai>=1.0            # OpenRouter API (compatible endpoint)
weasyprint>=60.0       # PDF generation for CVs
sentence-transformers>=2.0  # Local embeddings (all-MiniLM-L6-v2)
sib-api-v3-sdk>=7.0    # Brevo (Sendinblue) email API
pyhunter>=1.7          # Hunter.io email verification
```

### Memory Considerations (Render 512MB)
- sentence-transformers loads ~80MB model — use LAZY_LOAD_EMBEDDINGS=true
- WeasyPrint is lightweight (~20MB)
- OpenRouter/Mistral use REST API, no heavy SDK
- Max concurrent agents: 3 (unchanged)
- Batch size limit: 50 (unchanged)

---

## PORTAL-SPECIFIC STRATEGIES (PRISM v0.1)

### Internshala (A-03)
- **Method**: POST to mobile Ajax API `/internships/ajax/search_ajax`
- **Headers**: `app-version: 5.x`, mobile User-Agent
- **Categories**: management, finance, marketing, data-science, AI, ops, HR
- **Rate**: 50 req/hour, 10 pages/session, 5-15s delays

### Naukri (A-03) — FIXED
- **Method**: GET `jobapi/v2/search` (direct API v2 — PRIMARY)
- **Headers**: `appid=109`, `systemid=Naukri`, `X-Requested-With: XMLHttpRequest`
- **Fallback**: DDG dorks if API returns 403
- **Rate**: 30 req/hour, 8 pages/session, 10-20s delays

### IIMjobs (A-03)
- **Method**: DDG site dorks `site:iimjobs.com "intern"`
- **Fallback**: Direct HTML scraping with stealth
- **Rate**: 40 req/hour

### LinkedIn (A-03)
- **Method**: DDG site dorks ONLY `site:linkedin.com/jobs`
- **NEVER**: Scrape LinkedIn directly
- **Rate**: 5 req/hour max

### Greenhouse (A-04)
- **API**: `boards-api.greenhouse.io/v1/boards/{slug}/jobs`
- **Method**: Direct JSON API — no auth needed
- **Rate**: 100 req/hour, no stealth needed

### Lever (A-04)
- **API**: `api.lever.co/v0/postings/{company}`
- **Method**: Direct JSON API — no auth needed
- **Rate**: 100 req/hour, no stealth needed

### Workday (A-04)
- **Method**: Cloudflare Browser Rendering → extract LD+JSON
- **Fallback**: AI extraction from rendered HTML
- **Rate**: 40 req/hour, requires JS rendering

### Auto-Apply (A-13)
- **Internshala**: Session replay with mobile API, human-mimicry delays
- **Greenhouse**: Direct form POST to apply endpoint
- **Lever**: Direct form POST to apply endpoint
- **Email (A-15)**: Brevo REST for cold outreach to HR

---

## 20-AGENT MANIFEST (PRISM v0.1)

| Agent | Name | AI Provider | Schedule | Status |
|-------|------|------------|----------|--------|
| A-01 | Intel Scanner | Groq Compound Beta | 09:00 + 16:00 IST | Existing (upgrade) |
| A-02 | Dark Channel Listener | Cerebras 8B | Continuous + 4h batch | Existing (upgrade) |
| A-03 | Primary Scraper | Cerebras 8B | Wave 1 + 2 | Existing (fix Naukri) |
| A-04 | ATS Crawler | Cerebras 70B | Wave 2 + Night | Existing (upgrade) |
| A-05 | Ghost Detector | Cerebras 8B | Post-scrape waves | Existing |
| A-06 | Dedup Engine | Local embeddings | Post-ghost detect | Existing (+ semantic layer) |
| A-07 | Intelligence Enricher | Groq Compound | Post-dedup | Existing (upgrade) |
| A-08 | PPO Optimizer | Cerebras + Embeddings | 07:00 IST daily | Existing (+ V11) |
| A-09 | Network Mapper | Groq 70B | PPO >75 trigger | Existing |
| A-10 | ATS Simulator | OpenRouter Gemini | PPO >70 trigger | Existing (upgrade) |
| A-11 | Outcome Learner | Groq 70B | Sunday 18:00 + 21:00 | Existing |
| A-12 | Telegram Reporter | Groq 70B | Always-on polling | Existing |
| A-13 | Auto Applier | Groq 70B | 08:00 + 15:00 IST | Existing (upgrade) |
| A-14 | Multi-Model Router | N/A (middleware) | Every AI request | **NEW** |
| A-15 | Email Auto-Applier | Groq 70B | 09:30 IST daily | **NEW** |
| A-16 | Telegram Group Monitor | Cerebras 8B | Continuous (asyncio) | **NEW** |
| A-17 | Adaptive Scheduler | Cerebras 8B | Every 30 min | **NEW** |
| A-18 | CV Intelligence Enhancer | OpenRouter Gemini | PPO >75 trigger | **NEW** |
| A-19 | Outcome Amplifier | Cerebras 8B | 10:30 IST daily | **NEW** |
| A-20 | Deep Company Intel | Groq Compound Beta | 1h before A-13 | **NEW** |

---

## 3-WAVE WEEKLY SCHEDULE (PRISM v0.1)

### Wave 1 — Morning Portals (05:15 IST, Mon/Wed/Fri)
```
05:15  A-03 → Internshala + Naukri API + IIMjobs
06:00  A-06 → Dedup engine on overnight batch
06:15  A-05 → Ghost scoring
06:30  A-07 → Intelligence enrichment + Blue Ocean
07:00  A-08 → PPO model → top 25 shortlist
07:15  A-12 → MORNING BRIEF → Telegram
```

### Wave 2 — ATS + LinkedIn (14:00 IST, Tue/Thu/Sat)
```
14:00  A-04 → Greenhouse/Lever/Workday + LinkedIn DDG
14:45  A-05 → Ghost scoring (afternoon batch)
15:00  A-13 → Auto-apply run #2
```

### Wave 3 — Night Deep Crawl (22:30 IST, Mon/Wed)
```
22:30  A-04 → All portals, all Tier 1-3 companies
23:15  A-05 → Ghost scoring (night batch)
```

### Daily Operations (Every Day)
```
08:00  A-13 → Auto-apply run #1
09:00  A-01 → Intent signal scan (Tier 1+2)
09:30  A-15 → Email outreach (Brevo)
10:30  A-19 → Follow-up check
16:00  A-01 → Second intent scan
20:00  A-12 → EVENING SUMMARY
```

### Sunday Specials
```
10:00  A-09 → Alumni re-mapping
14:00  A-04 → Deep ATS discovery
18:00  A-11 → PPO weight retraining
21:00  A-11 → Second retrain pass
```

### Always Running
```
24/7   A-16 → Telegram Group Monitor (Telethon)
24/7   A-02 → Dark Channel Listener
24/7   A-14 → Multi-Model Router (middleware)
24/7   A-17 → Adaptive Scheduler (30min checks)
```

---

## PROGRESS TRACKING

| Step | File | Status | Lines |
|------|------|--------|-------|
| 01 | PRISM_V01_UPGRADE_PLAN.md | 🟢 | 322 |
| 02 | core/config.py | 🟢 | 2,218 |
| 03 | core/database.py | 🟢 | 3,905 |
| 04 | core/ai_router.py | 🟢 | 2,232 |
| 05 | core/embedding_engine.py | 🟢 | 1,018 |
| 06 | core/email_sender.py | 🟢 | 1,098 |
| 07 | core/cv_generator.py | 🟢 | 1,017 |
| 08 | agents/a14_multi_model_router.py | 🟢 | 1,220 |
| 09 | agents/a15_email_applier.py | 🟢 | 517 |
| 10 | agents/a16_tg_listener.py | 🟢 | 548 |
| 11 | agents/a17_scheduler.py | 🟢 | 402 |
| 12 | agents/a18_cv_enhancer.py | 🟢 | 485 |
| 13 | agents/a19_outcome_amplifier.py | 🟢 | 391 |
| 14 | agents/a20_company_intel.py | 🟢 | 519 |
| 15 | agents/a03_primary_scraper.py | 🟢 | 2,384 |
| 16 | agents/a07_intelligence_enricher.py | 🟢 | 1,479 |
| 17 | agents/a08_ppo_optimizer.py | 🟢 | 1,120 |
| 18 | agents/a10_ats_simulator.py | 🟢 | 653 |
| 19 | agents/a13_auto_apply.py | 🟢 | 1,442 |
| 20 | core/weekly_scheduler.py | 🟢 | 1,880 |
| 21 | main.py | 🟢 | 1,078 |
| 22 | requirements.txt | 🟢 | 72 |
| 23 | .env.example | 🟢 | 90 |
| 24 | agents/__init__.py | 🟢 | 57 |
