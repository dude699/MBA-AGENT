# NEXUS v0.2 — 10-Layer Architecture Reference

> **Networked Execution System for Unified eXternal Applications**
> Author: MD Abuzar Salim · 25IBMMA143 · AMU International Business · April 2026

This is the canonical architecture reference. The codebase mirrors this structure 1:1. Every layer has a single responsibility, a defined fallback, and graceful degradation.

> **Core principle**: _If Abuzar is asleep, NEXUS is working._

---

## Layer 0 — Cryptographic Credential Vault

**File**: `core/session_vault.py` · **Storage**: Supabase Vault (AES-256)

- Encrypted session-cookie storage per portal (LinkedIn, Internshala, Naukri, …).
- Each session carries `health_score: 0–100` updated by the **Session Freshness Oracle**.
- Portal-specific decay curves:
  - LinkedIn — linear decay over 90 days
  - Naukri — steeper decay over 30 days
- `health_score < 30` → Telegram pre-emptive 30-second re-auth alert _before_ failure.
- Each session bound to a `device_fingerprint` hash (Camoufox config). Fingerprint replayed on every apply for that portal.
- IP changes between sessions → Cloudflare Worker proxy maintains apparent-origin IP continuity.

---

## Layer 1 — Stealth Browser Triad

**File**: `core/stealth_triad.py` · **Agents**: `n01_skyvern_apply.py`, `n02_browser_use_apply.py`

Three tools in concert:

| Tool | Role |
|------|------|
| **Camoufox** (coryking fork, FF142) | C++ fingerprint spoofing — base layer, always on |
| **Browser-Use v2.0** | Natural-language reasoning agent for new portals |
| **Skyvern 2.0** | Generates + caches deterministic Playwright code, self-heals on layout change |

**Execution Decision Tree:**

```
new portal (no cache)        → Browser-Use (AI mode) → Skyvern observes & caches code
known portal (cache hit)     → Skyvern code path (3s, 0 LLM calls)
cached code fails            → Skyvern detects → AI mode → regenerate → re-cache
heavy WAF blocks             → Camoufox virtual display + behavioural entropy + CF Worker proxy
```

---

## Layer 2 — Universal Job Discovery (Crawl4AI-Powered)

**Files**: `core/crawl4ai_discovery.py`, `core/reactive_discovery.py` · **Agent**: `n03_crawl4ai_scraper.py`

Single unified extraction interface across all 11 portals — no custom scrapers, no brittle selectors.

**Reactive Layer (event-driven, not just cron):**

| Portal | Mechanism | Latency |
|--------|-----------|---------|
| LinkedIn | RSS subscription on company pages + job-alert feeds | 5–15 min |
| Internshala | Public RSS (15-min refresh) | 5–15 min |
| Naukri | Camoufox background watcher session | < 5 min |
| Others (8) | Enhanced cron (max 2-hour latency) | ≤ 2 hr |

Output schema: `NormalisedJob { job_id, portal, company, title, jd_text, location, stipend, deadline, posted_at }`.

---

## Layer 3 — Multi-Dimensional Intelligence Scoring (9 dimensions)

**Files**: `core/scoring_engine_v2.py`, `core/pgvector_matcher.py`

| # | Dimension | Source |
|---|-----------|--------|
| 1 | Profile Match | pgvector cosine (Groq embeddings) |
| 2 | Compensation Fit | Salary normaliser (LLM) |
| 3 | Role Type Match | Classifier (Groq) |
| 4 | Company Tier | Static + dynamic |
| 5 | Location Fit | Geo + remote tolerance |
| 6 | Recency / Freshness | `posted_at` decay |
| 7 | Competitive Position | Applicant count scrape |
| 8 | **Cultural Fit** *(NEW)* | LLM semantic match: company values vs profile |
| 9 | **Trajectory** *(NEW)* | Crawl4AI news → Cerebras sentiment |

**Routing thresholds:**
- ≥ 80 → AUTO_APPLY (priority)
- 60–79 → AUTO_APPLY (digest notify)
- 40–59 → MANUAL_REVIEW (Telegram inline buttons)
- < 40 → REJECT + log

---

## Layer 4 — Adaptive Answer Generation (RAG)

**File**: `core/answer_rag.py`

Voice-consistent custom answers via retrieval-augmented generation:

1. New custom question detected.
2. Question embedded (Groq) → cosine search in `answer_bank` pgvector table.
3. Top-3 similar past answers retrieved as few-shot examples.
4. Cerebras prompt: `system="You are Abuzar. Voice examples: [3 past answers]"`, `user="[new question]"`.
5. Generated answer added to bank for future RAG.
6. **Validator** runs:
   - Word count 100–180
   - No banned phrases (`"I am passionate about"`, etc.)
   - Company name inclusion required
   - Reject + regenerate on failure

---

## Layer 5 — Four-Tier CAPTCHA Resolution

**File**: `core/captcha_resolver.py`

| Tier | Method | Handles | Success | Cost |
|------|--------|---------|---------|------|
| T1 | Gemini 2.5 Flash vision | reCAPTCHA v2 image grids, text | ~75% | 0 |
| T2 | Groq Whisper Large v3 | reCAPTCHA v2 audio | ~90% | 0 |
| T3 | Telegram human relay (45s) | Any CAPTCHA | ~100% | 0 |
| T4 *(NEW)* | Skyvern `surgical_fallback` | CAPTCHA-gated submit, alt path detection | ~60% on known portals | 0 |

T4 looks for "Quick Apply via Email" / "Apply with LinkedIn" alt paths and switches automatically.

---

## Layer 6 — Intelligent Application Orchestrator

**File**: `core/orchestrator.py`

**Priority Queue:**
- Queue processor every 15 min.
- Dynamic re-scoring every 2 hr — deadlines elevate priority.
- `apply_window_open` per portal:
  - LinkedIn: 7–11 AM IST + 3–7 PM IST
  - Internshala: any time
  - Naukri: 9 AM – 1 PM IST
- Out-of-window jobs held; released at next open window.

**Risk Governor (5 signals — pre-emptive throttling):**

| Signal | Hard threshold | Action |
|--------|----------------|--------|
| Apps/hr LinkedIn | 8 | Throttle |
| Apps/hr Internshala | 15 | Throttle |
| Apps/hr Naukri | 12 | Throttle |
| CAPTCHA rate | > 15% | -50% rate |
| Session age | > 60 days | Reduce rate |
| Error rate | > 10% in last 20 | Pause portal + alert |
| Time-of-day variance | High | Snap to human hours |

---

## Layer 7 — Semantic Deduplication

**File**: `core/dedup_semantic.py`

Two-stage dedup:

1. **Exact** — `applied_jobs WHERE company = X AND title ILIKE %first20%`.
2. **Semantic** — pgvector RPC `find_similar_jds` with threshold `0.88` over last 60 days.

Same role posted on 3 portals → applied once on the highest-quality portal. Reposted titles ("Strategy Analyst" vs "Business Strategy Analyst" at Deloitte) → caught.

---

## Layer 8 — Interview Intelligence System

**File**: `core/interview_intel.py`

**Signal sources:**
- Gmail API — keyword + company-name watch.
- LinkedIn — Camoufox background session for "viewed" / "recruiter messaged" notifications.
- Email subject NLP — Cerebras classifies subjects only (privacy-preserving).
- WhatsApp Web *(new)* — Camoufox session watches for company mentions.

**90-Second Auto-Briefing Package** (Telegram):
- Company snapshot (Crawl4AI of website + Crunchbase)
- Last 3 news items (Crawl4AI + DuckDuckGo RSS)
- Glassdoor interview format intel
- 8 likely questions (Cerebras, JD + company stage + profile)
- Your own application copy (from Supabase)
- Suggested reply draft → one-tap Telegram approve & send

---

## Layer 9 — Telegram Intelligence Dashboard

**File**: `core/telegram_dashboard.py`

Sole user interface. Inline-button Mini App + 15-command surface:

```
/nexus           system overview
/applied [n]     last n applications
/queue           pending queue by portal
/interviews      detected signals + briefings
/pause [portal]  emergency stop / per-portal
/resume [portal] resume paused portal
/threshold [n]   change min auto-apply score
/blacklist [co]  blacklist company
/whitelist [co]  force-apply
/resync [portal] full session refresh
/debug [n]       full app details + screenshot
/analytics       weekly analytics on demand
/portal_status   all portals: health, scrape, queue
/set_profile     update master profile field
```

**Triggers → Alerts:**

| Trigger | Alert | Action |
|---------|-------|--------|
| Score 80+ apply sent | ⚡ Priority | Info |
| Score 60–79 apply sent | 📋 Digest | Batched 9 AM |
| Score 40–59 pending | 🔘 [Apply] [Skip] [Snooze] | Tap |
| Health < 30 | 🔐 [Refresh Now] | 30s tap |
| CAPTCHA T3 | 📸 Screenshot + answer | 45s solve |
| Interview signal | 🚨 URGENT + briefing + draft reply | Approve |
| Portal risk elevated | ⚠️ [Pause Portal] | Optional |

---

## The 15 Innovations (live in `core/innovations.py`)

1. **Zero-Selector Contract** — no hardcoded CSS/XPath/IDs anywhere.
2. **First-Apply Code Crystallisation** — Skyvern caches AI reasoning into deterministic code; cost approaches zero.
3. **Semantic Session Identity** — device fingerprint binding > IP binding.
4. **RAG-Powered Voice Consistency** — your answer bank teaches the model your voice.
5. **Trajectory-Aware Scoring** — real-time news bonuses/penalties.
6. **Optimal Apply Window Intelligence** — submission timing maximises recruiter views.
7. **Competitive Position Estimator** — applicant count scoring gate.
8. **Multi-Resume Variant Routing** — 4 variants (AI/Tech, Finance, IB, Generalist).
9. **Portal Health Benchmarking** — auto-reweights scraping schedule by callback rate.
10. **Stealth Warmup Sequence** — feed scroll → search → apply (3-step warmup).
11. **Deadline Cliffs / FOMO Engine** — 72/24/6-hour deadline boosts.
12. **Applied-But-Not-Viewed Detection** — closes the loop with polite follow-up.
13. **Salary/Stipend Floor Intelligence** — normalises CTC/in-hand/USD/equity to monthly INR.
14. **Cold Start Bypass** — first action on new portal = profile save (not apply).
15. **Employer Perspective Engine** — Crawl4AI of careers/about/blog before answer gen.

---

## Data Flow (text diagram)

```
[PORTAL] ──► [CRAWL4AI SCRAPER] ◄── RSS/webhook reactive layer
                  │ Crawl4AI + Groq LLM extract
                  ▼
            [DEDUP ENGINE] (pgvector + exact)
                  ▼
            [SCORING ENGINE] (9 dims)
              ≥80 / 60–79 → AUTO_APPLY queue
              40–59       → MANUAL_REVIEW → Telegram
              <40         → REJECT
                  ▼
            [APPLY WINDOW SCHEDULER]
                  ▼
            [SESSION VAULT]  health<30 → Telegram refresh
                  ▼
            [STEALTH WARMUP] (3-step)
                  ▼
            [APPLY EXECUTOR]
              cache hit → Skyvern code path (3s)
              cache miss → Browser-Use AI → Skyvern crystallise
                  ▼
            [CAPTCHA RESOLVER]  T1 → T2 → T3 → T4
                  ▼
            [ANSWER GENERATOR] (RAG + employer perspective)
                  ▼
            [SUBMISSION + VALIDATION]
                  ▼
            [APPLICATION TRACKER] (Supabase)
                  ▼
            [INTERVIEW SIGNAL WATCHER]  Gmail + LinkedIn + WhatsApp
                  ▼
            [RISK GOVERNOR] (continuous, 5 signals)
```

---

## Stack Summary (verified April 2026)

| Category | Tool | Free Tier |
|----------|------|-----------|
| Browser Foundation | Camoufox | MIT FF142 |
| AI Browser Agent | Browser-Use v2.0 | MIT, 79K stars |
| RPA Agent | Skyvern 2.0 | Apache 2.0 (YC S23) |
| Job Scraper | Crawl4AI | Apache 2.0 (#1 GH) |
| AI Vision / Scoring | Gemini 2.5 Flash / Flash-Lite | 500 / 1000 RPD per project |
| LLM Extraction | Groq llama-3.3-70b | ~14,400 RPD |
| Custom Answers | Cerebras llama-3.3-70b | ~900 RPD |
| Vector DB | Supabase pgvector | 500 MB |
| Hosting | Render.com | 750 hrs/mo |
| Interface | Telegram Bot API | Free |
| Proxy | Cloudflare Workers | 100K req/day |

> ⚠️ Gemini 2.0 Flash retired March 3, 2026 — never referenced.

---

## Why this architecture wins

- **Adapts on its own** — Skyvern self-heals; Crawl4AI is layout-resilient by LLM extraction.
- **Costs trend toward zero** — code cache eliminates repeat LLM calls.
- **Bans pre-empted, not detected** — Risk Governor throttles before the threshold.
- **Voice is yours** — RAG over your own answer bank.
- **Always on** — Render keep-alive + reactive RSS + Risk Governor + Session Oracle.
