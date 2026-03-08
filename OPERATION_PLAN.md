# ⚡ OPERATION FIRST MOVER v5 — ZERO COST MBA HUNT AGENT
## Complete Build Plan & Architecture Document

**Version:** 5.0 — Free Edition  
**Date:** March 2026  
**Target:** Render Free Tier Deployment  
**Total Daily Cost:** ₹0.00  
**Capability:** 95% of a paid system  

---

## TABLE OF CONTENTS

1. [System Overview](#system-overview)
2. [Free-Tier Arsenal](#free-tier-arsenal)
3. [Architecture Diagram](#architecture-diagram)
4. [Smart AI Routing Engine](#smart-ai-routing-engine)
5. [Agent Registry (A-01 to A-12)](#agent-registry)
6. [Source Priority Stack](#source-priority-stack)
7. [1080+ Indian Company Database](#indian-company-database)
8. [Zero-Detection Stealth System](#zero-detection-stealth-system)
9. [SQLite Database Schema (12 Tables)](#database-schema)
10. [PPO Scoring Formula (10 Variables)](#ppo-scoring-formula)
11. [Ghost Detection (5 Signals)](#ghost-detection)
12. [Dedup Engine (6 Layers)](#dedup-engine)
13. [24-Hour Agent Schedule](#agent-schedule)
14. [Telegram Command Center (22 Commands)](#telegram-commands)
15. [Render Free Tier Deployment](#render-deployment)
16. [File-by-File Build Checklist](#build-checklist)
17. [Environment Variables](#environment-variables)
18. [Technology Stack](#technology-stack)

---

## 1. SYSTEM OVERVIEW <a name="system-overview"></a>

Operation First Mover is a **fully automated, zero-cost AI-driven job search system** built for MBA students hunting internships in India. It operates 24/7 with 12 specialized agents that:

- **Scrape** 8+ job platforms (Internshala, Naukri, IIMjobs, LinkedIn, Glassdoor, Greenhouse, Lever, Workday, Wellfound, Indeed)
- **Analyze** every listing using dual-brain AI (Groq + Cerebras)
- **Filter** ghost jobs, deduplicate across platforms, enrich with competition data
- **Rank** using a 10-variable PPO (Probability of Positive Outcome) formula
- **Alert** via Telegram with morning briefs, Blue Ocean alerts, and application packages
- **Learn** from outcomes to improve ranking over time
- **Monitor** 1,080+ Indian companies for hiring intent signals
- **Generate** tailored cover letters, ATS-optimized resume tweaks, and warm intro drafts

### Core Principle: Route Each Task to the Cheapest Model That Can Do It
- **Cerebras** (llama-3.3-70b): Fast tasks — classification, scoring, parsing, tagging
- **Groq** (llama-3.3-70b-versatile): Heavy tasks — generation, analysis, research
- **Cloudflare Workers**: Request relay, IP masking (100k req/day free)

---

## 2. FREE-TIER ARSENAL <a name="free-tier-arsenal"></a>

| Service | Free Tier Limit | Used For | Daily Usage |
|---------|----------------|----------|-------------|
| **Groq** (llama-3.3-70b-versatile) | 14,400 req/day | Cover letters, JD analysis, ATS simulation, company research | ~50-100 req |
| **Cerebras** (llama-3.3-70b) | Generous free tier | Ghost classify, intent classify, extract basics, dedup score, parse, tag | ~400-600 req |
| **Cloudflare Workers** | 100,000 req/day | Proxy relay, IP rotation, request masking | ~500-2000 req |
| **Cloudflare KV** | 100,000 reads/day | Cache company scores, proxy health, rate limit counters | ~1000 reads |
| **SerpAPI** | 100 queries/month | Alumni discovery, HR poster identification (HIGH VALUE ONLY) | ~3-4/day max |
| **Webshare Proxy** | 10 free rotating IPs | Primary proxy for Internshala, IIMjobs, Wellfound | All scraping |
| **Telegram Bot API** | Unlimited | Command center, reports, alerts | Unlimited |
| **DuckDuckGo Search** | Unlimited (rate-limited) | LinkedIn job dorks, news search, HR post discovery | ~50-100/day |
| **Render Free Tier** | 750 hrs/month, 512MB RAM | 24/7 hosting of all 12 agents | Always-on |

### SerpAPI Budget Rules (CRITICAL — Only 100/month)
- ❌ **NEVER use for:** routine daily operations, general job searches
- ✅ **USE ONLY for:** Alumni discovery on LinkedIn, HR poster identification, dark channel seed discovery
- 🔄 **Alternatives:** DuckDuckGo for news/signals, Bing Search API (1000 free/month) as backup

---

## 3. ARCHITECTURE DIAGRAM <a name="architecture-diagram"></a>

```
┌─────────────────────────────────────────────────────────────────┐
│                    TELEGRAM COMMAND CENTER                       │
│                  (A-12: 22 Commands + Reports)                  │
└─────────────────────┬───────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                       │
│              24-Hour IST Schedule + Heartbeats                  │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬─────┘
   │      │      │      │      │      │      │      │      │
┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐
│A-01 ││A-02 ││A-03 ││A-04 ││A-05 ││A-06 ││A-07 ││A-08 ││A-09 │
│Intel││Dark ││Scrp ││ATS  ││Ghost││Dedup││Enrch││PPO  ││Netwk│
│Scan ││Chan ││Main ││Crawl││Dtct ││Engn ││Blue ││Rank ││Map  │
└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘
   │      │      │      │      │      │      │      │      │
┌──▼──────▼──────▼──────▼──────▼──────▼──────▼──────▼──────▼─────┐
│                 CORE INFRASTRUCTURE                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │AI Router │ │ Stealth  │ │ Database │ │ Company  │          │
│  │Groq+Cere │ │ Engine   │ │ SQLite   │ │ DB 1080+ │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐                                     │
│  │A-10: ATS │ │A-11:Learn│                                     │
│  │Simulator │ │Outcomes  │                                     │
│  └──────────┘ └──────────┘                                     │
└─────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│              EXTERNAL SERVICES & PROXIES                         │
│  Webshare(10 IPs) → Cloudflare Workers → Tor → Free Proxy List │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. SMART AI ROUTING ENGINE <a name="smart-ai-routing-engine"></a>

### 4.1 Dual-Brain Architecture

| Task Type | Model | Provider | Reason |
|-----------|-------|----------|--------|
| `ghost_classify` | llama-3.3-70b | Cerebras | Fast binary classification |
| `intent_classify` | llama-3.3-70b | Cerebras | Quick signal scoring |
| `extract_basics` | llama-3.3-70b | Cerebras | Entity extraction from HTML |
| `dedup_score` | llama-3.3-70b | Cerebras | Similarity comparison |
| `internshala_parse` | llama-3.3-70b | Cerebras | Listing card parsing |
| `sector_tag` | llama-3.3-70b | Cerebras | Company sector classification |
| `cover_letter` | llama-3.3-70b-versatile | Groq | Creative generation |
| `ats_simulation` | llama-3.3-70b-versatile | Groq | Deep keyword analysis |
| `resume_tweaks` | llama-3.3-70b-versatile | Groq | Nuanced resume optimization |
| `jd_analysis` | llama-3.3-70b-versatile | Groq | Comprehensive JD breakdown |
| `outreach_draft` | llama-3.3-70b-versatile | Groq | Professional email drafting |
| `company_research` | llama-3.3-70b-versatile | Groq | Deep company intelligence |

### 4.2 Quota Budget (Daily)

| Task | Provider | Estimated Calls/Day | % of Quota |
|------|----------|--------------------:|------------|
| Internshala Parsing | Cerebras | ~200 | Minimal |
| Ghost Scoring | Cerebras | ~150 | Minimal |
| Intent Classification | Cerebras | ~80 | Minimal |
| Dedup Scoring | Cerebras | ~100 | Minimal |
| Sector Tagging | Cerebras | ~50 | Minimal |
| Cover Letters | Groq | ~10-25 | <0.2% |
| ATS Simulation | Groq | ~10-20 | <0.2% |
| JD Analysis | Groq | ~20-30 | <0.2% |
| Company Research | Groq | ~5-10 | <0.1% |
| Report Compilation | Groq | 1-2 | <0.01% |
| **Total Groq** | | **~50-100** | **<0.7%** |
| **Total Cerebras** | | **~580** | **Minimal** |

### 4.3 Fallback & Error Handling
- If Cerebras fails → retry once → fallback to Groq
- If Groq fails → retry once → fallback to Cerebras with simpler prompt
- If both fail → queue task for next cycle, log error
- Rate limit tracking per provider per hour
- Exponential backoff: 2s → 4s → 8s → 16s → skip

---

## 5. AGENT REGISTRY <a name="agent-registry"></a>

### A-01: Intent Signal Scanner (`agents/a01_intent_scanner.py`)
**Purpose:** Detect companies actively hiring BEFORE they post on job boards  
**Sources:** Google News RSS, Inc42 RSS, DuckDuckGo HR post dorks, Economic Times  
**AI Model:** Cerebras (`intent_classify`)  
**Output:** Intent signals with scores (0-100), urgent alerts if score ≥ 70  
**Schedule:** 09:00 AM + 04:00 PM IST  
**Key Features:**
- RSS feed parsing for hiring news (feedparser)
- DuckDuckGo dorks: `"[company] hiring interns 2026"`, `"[company] MBA internship"`
- Economic signal correlation (RBI data, BSE sector indices, Inc42 funding)
- Signal decay: -10 points/day without reinforcement
- Urgent Telegram alert for Tier 1+2 companies with score ≥ 70

### A-02: Dark Channel Listener (`agents/a02_dark_channel.py`)
**Purpose:** Monitor Telegram groups, Discord, and X/Twitter for unadvertised positions  
**Sources:** Telethon (Telegram groups), X API v2 (Twitter search), Discord webhooks  
**AI Model:** Cerebras (`intent_classify`)  
**Schedule:** 08:00 PM IST (batch check)  
**Key Features:**
- Telethon client for Telegram group monitoring (MBA job groups)
- X API v2 bearer token search for hiring tweets
- Message classification: job post vs noise (Cerebras)
- Keyword extraction and company matching
- Dedup against known listings

### A-03: Primary Scraper (`agents/a03_primary_scraper.py`)
**Purpose:** Scrape all major job boards — Internshala first, then Naukri, IIMjobs, LinkedIn (via DDG), Glassdoor  
**Sources:** See Source Priority Stack (Section 6)  
**AI Model:** Cerebras (`internshala_parse`, `extract_basics`)  
**Schedule:** 05:30 AM (Internshala) + 12:00 PM (Naukri/IIMjobs)  
**Key Features:**
- Internshala: Mobile API (`ajax/search_ajax`), 10 MBA categories, full pagination
- Naukri: Mobile API (`api.naukri.com`), curl_cffi + CF relay
- IIMjobs: Direct requests, rotating UA
- LinkedIn: DDG dorks only (`site:linkedin.com/jobs [query]`), max 5 dorks/hr
- Glassdoor: chrome120 impersonation, 15-30s delays
- Extraction: title, company, location, stipend, duration, applicants, PPO tag, WFH tag, URL
- Auto-store to `raw_listings` table

### A-04: Company ATS Crawler (`agents/a04_ats_crawler.py`)
**Purpose:** Crawl company career pages directly via their ATS APIs  
**Sources:** Greenhouse REST API, Lever REST API, Workday REST API  
**AI Model:** Cerebras (`extract_basics`)  
**Schedule:** 02:00 PM + 11:00 PM IST  
**Key Features:**
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{company}/jobs`
- Lever: `https://api.lever.co/v0/postings/{company}`
- Workday: Company-specific career page URLs
- No authentication needed for public job boards
- 2-5 second delays between requests
- Filter for MBA/intern/strategy/marketing/finance keywords
- Cross-reference with company_db for tier scoring

### A-05: Ghost Job Detector (`agents/a05_ghost_detector.py`)
**Purpose:** Identify fake/stale/ghost job listings that waste application time  
**AI Model:** Cerebras (`ghost_classify`)  
**Schedule:** 06:15 AM IST  
**Key Features — 5-Signal Scoring System:**
1. **Listing Age:** Days since posted (>30 days = +25 ghost score)
2. **Applicant Overload:** High applicants without closing (>500 applicants still open = +20)
3. **Repetitive Posting:** Same company posts same role monthly = +20
4. **No HR Response Signal:** Company has no recent hiring signals in A-01 data = +15
5. **ATS Mismatch:** Listing doesn't exist on company's actual ATS page = +20
- **Ghost Score 0-100:** ≥60 = flagged as likely ghost
- **Result:** ~35% of daily listings filtered out

### A-06: Deduplication Engine (`agents/a06_dedup_engine.py`)
**Purpose:** 6-layer cross-platform deduplication  
**AI Model:** Cerebras (`dedup_score`)  
**Schedule:** 06:00 AM + 06:00 PM IST  
**6 Layers:**
1. **URL Match:** Exact URL dedup (instant)
2. **Title+Company String:** Exact match on normalized title + company
3. **Fuzzy String:** RapidFuzz ratio ≥ 85 on JD text
4. **BERT Semantic:** Sentence-transformers cosine similarity ≥ 0.92 on JD
5. **Location+Stipend Normalization:** Same company + same city + same stipend = likely same
6. **Cross-Platform ID:** LinkedIn ID vs Internshala ID vs Naukri ID matching

### A-07: Intelligence Enricher (`agents/a07_intelligence_enricher.py`)
**Purpose:** Enrich listings with competition data and flag Blue Ocean opportunities  
**AI Model:** Cerebras (`sector_tag`)  
**Schedule:** 06:30 AM + 06:00 PM IST  
**Key Features:**
- Extract applicant count from Internshala (publicly visible)
- Calculate competition ratio per listing
- **Blue Ocean Criteria:** Company Prestige ≥ 60 AND Applicant Count ≤ 35
- Stipend normalization (monthly/total → monthly)
- WFH flag extraction
- PPO (Pre-Placement Offer) tag detection
- Sector momentum scoring from economic signals

### A-08: PPO Optimizer (`agents/a08_ppo_optimizer.py`)
**Purpose:** Rank ALL listings by Probability of Positive Outcome  
**Schedule:** 07:00 AM IST  
**10-Variable PPO Formula:**
```
PPO_Score = w1×has_ppo_tag + w2×company_tier_score + w3×low_applicant_bonus +
            w4×stipend_normalized + w5×duration_fit + w6×cirs_score +
            w7×sector_momentum + w8×intent_signal + w9×historic_callback +
            w10×recency_bonus
```
| Variable | Weight (default) | Range | Description |
|----------|:---:|:---:|-------------|
| `has_ppo_tag` | 0.20 | 0-1 | Binary: listing mentions PPO |
| `company_tier_score` | 0.18 | 0-100 | Tier 1=100, 2=80, 3=60, 4=40, 5=20 |
| `low_applicant_bonus` | 0.15 | 0-100 | Inverse of applicant count |
| `stipend_normalized` | 0.08 | 0-100 | Stipend relative to category median |
| `duration_fit` | 0.05 | 0-100 | 2-6 months preferred |
| `cirs_score` | 0.12 | 0-100 | Company Intern Readiness Score |
| `sector_momentum` | 0.07 | 0-100 | Economic sector signals |
| `intent_signal` | 0.08 | 0-100 | From A-01 signal scanner |
| `historic_callback` | 0.05 | 0-100 | From A-11 outcome data |
| `recency_bonus` | 0.02 | 0-100 | Posted today=100, decay -15/day |

### A-09: Network Mapper (`agents/a09_network_mapper.py`)
**Purpose:** Discover alumni connections and warm intro paths  
**Sources:** DuckDuckGo dorks, SerpAPI (reserved budget)  
**AI Model:** Groq (`outreach_draft`)  
**Schedule:** On-demand via `/network [company]`  
**Key Features:**
- DDG dorks: `site:linkedin.com/in "[college name]" "[company]" alumni`
- SerpAPI for high-value Tier 1 companies only
- Outreach draft generation (200-word warm intro email)
- Alumni path mapping: 1st degree → 2nd degree → cold outreach
- Rate: max 5 network lookups/day to conserve SerpAPI

### A-10: ATS Simulator (`agents/a10_ats_simulator.py`)
**Purpose:** Simulate ATS keyword scanning on resume vs JD  
**AI Model:** Groq (`ats_simulation`, `resume_tweaks`)  
**Schedule:** On-demand via `/ats [id]`  
**Key Features:**
- Extract top 20 keywords from JD using Groq
- Compare against user's resume keywords
- Calculate keyword match score (%)
- Generate 3 bullet-point resume tweaks
- Suggest exact phrases to add for ATS pass
- Section-by-section resume optimization suggestions

### A-11: Outcome Learner (`agents/a11_outcome_learner.py`)
**Purpose:** Self-improvement loop — learn from application outcomes  
**AI Model:** scikit-learn LogisticRegression  
**Schedule:** Sunday 09:00 PM IST (weekly retrain)  
**Key Features:**
- Log outcomes: applied → shortlisted → interview → offer → PPO
- Track conversion rates per company, sector, tier
- Retrain PPO weights using logistic regression on outcome data
- Feature importance analysis for weight adjustment
- Weekly stats report: funnel visualization, top performing sectors
- Minimum 20 outcomes before first retrain

### A-12: Telegram Reporter (`agents/a12_telegram_reporter.py`)
**Purpose:** User interface — 22 commands, morning/evening reports, alerts  
**Framework:** python-telegram-bot v21  
**Key Features:** See Telegram Command Center (Section 14)

---

## 6. SOURCE PRIORITY STACK <a name="source-priority-stack"></a>

| Priority | Source | Listings/Day | Difficulty | Method |
|:--------:|--------|:------------:|:----------:|--------|
| P1 ⭐ | **Internshala** | 200-400 | Easy | Mobile API + curl_cffi |
| P1 ⭐ | **Naukri MBA/Intern** | 100-200 | Medium | Mobile API + CF relay |
| P2 | **LinkedIn (Guest)** | 50-150 | Hard | DDG dorks only |
| P2 | **IIMjobs** | 30-80 | Easy | Direct requests + rotating UA |
| P2 | **Glassdoor** | 20-60 | Medium | chrome120 impersonation |
| P3 | **Greenhouse/Lever/Workday** | 50-100 | Easy | Direct REST APIs |
| P3 | **Wellfound (AngelList)** | 30-50 | Easy | GraphQL API |
| P3 | **Indeed India** | 40-80 | Medium | RSS feeds + curl_cffi |
| P4 | **Telegram/X Dark Channels** | 5-30 | Easy | Telethon + X API v2 |

### Internshala Categories (10 MBA Tracks)
```
MBA_CATEGORIES = [
    'marketing',           # https://internshala.com/internships/marketing
    'finance',             # https://internshala.com/internships/finance
    'business-development',# https://internshala.com/internships/business-development
    'operations',          # https://internshala.com/internships/operations
    'strategy',            # https://internshala.com/internships/strategy
    'consulting',          # https://internshala.com/internships/consulting
    'product-management',  # https://internshala.com/internships/product-management
    'human-resources',     # https://internshala.com/internships/human-resources
    'supply-chain',        # https://internshala.com/internships/supply-chain
    'analytics',           # https://internshala.com/internships/analytics
]
```

### Per-Site Stealth Settings
| Site | TLS Profile | API Type | Delay | Proxy | Max Req/Hr |
|------|-------------|----------|:-----:|-------|:----------:|
| Internshala | curl_cffi chrome120 | Mobile Ajax | 5-15s | Webshare | 50 |
| Naukri | curl_cffi + CF relay | Mobile API | 10-20s | CF Worker | 30 |
| LinkedIn | DDG dorks only | — | — | None | 5 dorks |
| IIMjobs | Standard requests | Web | 8-12s | Webshare | 40 |
| Glassdoor | curl_cffi chrome120 | Web | 15-30s | Webshare | 20 |
| Greenhouse/Lever | Standard | REST API | 2-5s | None | 100 |
| Telegram | Telethon | Native | Normal | None | Normal |

---

## 7. 1080+ INDIAN COMPANY DATABASE <a name="indian-company-database"></a>

### Tier System

| Tier | Name | Count | Examples | PPO Tier Score |
|:----:|------|:-----:|---------|:--------------:|
| 1 | **Elite** | 80 | McKinsey, BCG, Bain, Goldman, HUL, ITC, P&G, Amazon, Google, Microsoft, Flipkart, Reliance, HDFC | 100 |
| 2 | **Strong MNC** | 220 | Deloitte, EY, PwC, KPMG, Accenture, Infosys, TCS, Samsung, Siemens, ABB, Asian Paints | 80 |
| 3 | **Indian Unicorns** | 180 | Zepto, Meesho, PhonePe, CRED, Razorpay, Groww, Lenskart, Nykaa, Swiggy, Zomato, OYO | 60 |
| 4 | **Growing Startups** | 320 | Series B/C fintech, edtech, healthtech, SaaS, D2C (YC India, Antler, Blume, Sequoia India) | 40 |
| 5 | **Niche/Sector** | 280 | PE/VC firms, boutique consulting, sector specialists | 20 |

### Seeding Sources
- `india-unicorns.json` (maintained list)
- NSE NIFTY 500 API: `api1.nseindia.com/api/equity-stockIndices?index=NIFTY+500`
- Inc42 startup database
- Internshala company list
- Auto-classification: Cerebras `sector_tag` for tier, sector, size band

### CIRS — Company Intern Readiness Score
- **Default:** 40 (for new companies)
- **Components:**
  - Intent signal strength (from A-01)
  - Historical PPO conversion rate
  - Glassdoor intern reviews
  - Funding recency (for startups)
  - LinkedIn intern posting frequency
- **Update:** After each A-01 signal scan

---

## 8. ZERO-DETECTION STEALTH SYSTEM <a name="zero-detection-stealth-system"></a>

### Philosophy
> You are not hiding from law enforcement. You are mimicking normal human browser behavior.
> A human researcher visits 5-10 pages per session with 30-120 second gaps.

### 4-Layer Proxy Stack

| Layer | Service | IPs | Used For | Speed |
|:-----:|---------|:---:|----------|:-----:|
| L1 | **Webshare Free** | 10 rotating | Internshala, IIMjobs, Wellfound | Fast |
| L2 | **Cloudflare Workers** | Global | Naukri, LinkedIn (relay) | Fast |
| L3 | **Tor** (stem) | Unlimited | Sensitive alumni dorks | Slow |
| L4 | **Free Proxy Lists** | 50-200 | Fallback (health-checked hourly) | Variable |

### TLS Fingerprint Impersonation (curl_cffi)
```python
IMPERSONATION_PROFILES = [
    'chrome120', 'chrome119', 'chrome124',
    'firefox121', 'safari17_0',
]
```

### User-Agent Pool (20+ Agents)
```python
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/17.0',
    'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36',
    # ... 17 more agents
]
```

### Timing
- **Inter-request delay:** 8-25 seconds (random uniform)
- **Micro-pauses:** 0.5-2.0 seconds (simulates human reading)
- **Session length:** 5-10 pages then rotate IP
- **Per-domain cooldown:** Never hit same IP twice in <10 minutes

### Cloudflare Worker Relay
```javascript
// cloudflare_relay_worker.js
export default {
  async fetch(request, env) {
    const body = await request.json();
    const { url, headers, method } = body;
    const secret = request.headers.get('X-Relay-Secret');
    if (secret !== env.RELAY_SECRET) return new Response('403', {status: 403});
    const resp = await fetch(url, {
      method: method || 'GET',
      headers: { ...headers, 'User-Agent': headers['User-Agent'] || 'Mozilla/5.0 Chrome/120' }
    });
    const text = await resp.text();
    return new Response(JSON.stringify({
      status: resp.status, body: text,
      headers: Object.fromEntries(resp.headers)
    }), { headers: {'Content-Type': 'application/json'} });
  }
}
```

---

## 9. DATABASE SCHEMA (12 Tables) <a name="database-schema"></a>

### Table 1: `raw_listings`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| title | TEXT NOT NULL | Job title |
| company | TEXT NOT NULL | Company name |
| location | TEXT | City/Remote |
| stipend | TEXT | Stipend text (e.g., "₹15,000/month") |
| stipend_normalized | REAL | Monthly stipend in INR |
| duration | TEXT | Duration text |
| duration_months | INTEGER | Normalized months |
| applicants | INTEGER | Applicant count |
| is_ppo | BOOLEAN DEFAULT 0 | PPO tag present |
| is_wfh | BOOLEAN DEFAULT 0 | Work from home |
| posted_days_ago | INTEGER | Days since posted |
| url | TEXT UNIQUE | Listing URL |
| source | TEXT | Platform name |
| category | TEXT | MBA category |
| description_text | TEXT | Full JD text |
| scraped_at | DATETIME DEFAULT CURRENT_TIMESTAMP | When scraped |
| batch_id | TEXT | Scraping batch identifier |

### Table 2: `clean_listings`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| raw_id | INTEGER REFERENCES raw_listings(id) | Link to raw |
| title | TEXT NOT NULL | Cleaned title |
| company | TEXT NOT NULL | Normalized company name |
| company_id | INTEGER REFERENCES companies(id) | Link to company DB |
| location | TEXT | Normalized location |
| stipend_monthly | REAL | Monthly stipend (INR) |
| duration_months | INTEGER | Duration in months |
| applicants | INTEGER | Current applicant count |
| is_ppo | BOOLEAN | PPO confirmed |
| is_wfh | BOOLEAN | WFH confirmed |
| ghost_score | REAL DEFAULT 0 | From A-05 (0-100) |
| is_ghost | BOOLEAN DEFAULT 0 | ghost_score ≥ 60 |
| ppo_score | REAL DEFAULT 0 | From A-08 (0-100) |
| is_blue_ocean | BOOLEAN DEFAULT 0 | From A-07 |
| competition_ratio | REAL | Applicants/days posted |
| source | TEXT | Original platform |
| url | TEXT UNIQUE | Listing URL |
| description_text | TEXT | Full JD |
| created_at | DATETIME DEFAULT CURRENT_TIMESTAMP | First seen |
| updated_at | DATETIME | Last updated |
| status | TEXT DEFAULT 'active' | active/expired/ghost |

### Table 3: `companies`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| name | TEXT UNIQUE NOT NULL | Company name |
| normalized_name | TEXT | Lowercase cleaned |
| tier | INTEGER CHECK(tier BETWEEN 1 AND 5) | 1=Elite, 5=Niche |
| sector | TEXT | Industry sector |
| sub_sector | TEXT | Sub-industry |
| size_band | TEXT | startup/mid/large/enterprise |
| hq_city | TEXT | Headquarters city |
| careers_url | TEXT | Career page URL |
| ats_platform | TEXT | greenhouse/lever/workday/custom |
| ats_board_id | TEXT | ATS board identifier |
| cirs | REAL DEFAULT 40 | Company Intern Readiness Score |
| glassdoor_rating | REAL | Glassdoor rating if available |
| last_signal_scan | DATETIME | Last A-01 scan |
| created_at | DATETIME DEFAULT CURRENT_TIMESTAMP | Added date |
| updated_at | DATETIME | Last updated |

### Table 4: `ghost_scores`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| listing_id | INTEGER REFERENCES clean_listings(id) | Listing |
| listing_age_score | REAL | Signal 1: age score |
| applicant_overload_score | REAL | Signal 2: overload |
| repetitive_posting_score | REAL | Signal 3: repeat |
| no_hr_signal_score | REAL | Signal 4: no HR |
| ats_mismatch_score | REAL | Signal 5: ATS mismatch |
| total_score | REAL | Sum of 5 signals |
| is_ghost | BOOLEAN | total_score ≥ 60 |
| scored_at | DATETIME DEFAULT CURRENT_TIMESTAMP | When scored |

### Table 5: `intent_signals`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| company_id | INTEGER REFERENCES companies(id) | Company |
| signal_type | TEXT | news/hr_post/funding/expansion |
| signal_text | TEXT | Raw signal text |
| signal_score | REAL | Strength (0-100) |
| source_url | TEXT | Where found |
| detected_at | DATETIME DEFAULT CURRENT_TIMESTAMP | When detected |
| decay_applied | BOOLEAN DEFAULT 0 | Signal decay applied |
| expires_at | DATETIME | Auto-expire date |

### Table 6: `outcomes`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| listing_id | INTEGER REFERENCES clean_listings(id) | Which listing |
| company_id | INTEGER REFERENCES companies(id) | Which company |
| status | TEXT | applied/shortlisted/interview/rejected/offer/ppo |
| applied_at | DATETIME | When applied |
| outcome_at | DATETIME | When outcome received |
| notes | TEXT | User notes |
| ppo_score_at_apply | REAL | PPO score when applied |
| created_at | DATETIME DEFAULT CURRENT_TIMESTAMP | Record created |

### Table 7: `dark_channel_listings`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| channel_name | TEXT | Telegram group/X handle |
| channel_type | TEXT | telegram/twitter/discord |
| message_text | TEXT | Original message |
| extracted_company | TEXT | Detected company |
| extracted_role | TEXT | Detected role |
| extracted_url | TEXT | Any URL in message |
| is_job | BOOLEAN | AI classified as job posting |
| confidence | REAL | Classification confidence |
| detected_at | DATETIME DEFAULT CURRENT_TIMESTAMP | When found |

### Table 8: `alumni_contacts`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| company_id | INTEGER REFERENCES companies(id) | Target company |
| name | TEXT | Alumni name |
| linkedin_url | TEXT | Profile URL |
| college | TEXT | College name |
| batch_year | TEXT | Graduation year |
| current_role | TEXT | Current designation |
| connection_degree | INTEGER | 1st/2nd/3rd |
| outreach_draft | TEXT | Generated email draft |
| outreach_status | TEXT DEFAULT 'pending' | pending/sent/replied |
| discovered_at | DATETIME DEFAULT CURRENT_TIMESTAMP | When found |

### Table 9: `application_packages`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| listing_id | INTEGER REFERENCES clean_listings(id) | For which listing |
| cover_letter | TEXT | Generated cover letter |
| resume_tweaks | TEXT | ATS resume suggestions |
| keyword_gaps | TEXT | Missing keywords (JSON) |
| keyword_match_pct | REAL | ATS match percentage |
| warm_intro_draft | TEXT | Outreach email if alumni found |
| generated_at | DATETIME DEFAULT CURRENT_TIMESTAMP | When generated |

### Table 10: `api_quotas`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| provider | TEXT NOT NULL | groq/cerebras/serpapi/ddg |
| date | DATE NOT NULL | Date of usage |
| hour | INTEGER | Hour of usage (0-23) |
| requests_made | INTEGER DEFAULT 0 | Calls made |
| tokens_used | INTEGER DEFAULT 0 | Tokens consumed |
| errors | INTEGER DEFAULT 0 | Error count |
| rate_limited | BOOLEAN DEFAULT 0 | Hit rate limit |
| UNIQUE(provider, date, hour) | | Unique constraint |

### Table 11: `proxy_health`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| proxy_url | TEXT NOT NULL | Proxy address |
| proxy_type | TEXT | webshare/tor/free/cloudflare |
| is_alive | BOOLEAN DEFAULT 1 | Health status |
| avg_latency_ms | REAL | Average response time |
| success_rate | REAL DEFAULT 1.0 | Success ratio |
| last_check | DATETIME | Last health check |
| last_used | DATETIME | Last used for request |
| fail_count | INTEGER DEFAULT 0 | Consecutive failures |
| blocked_by | TEXT | Sites that blocked this proxy |

### Table 12: `agent_heartbeats`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| agent_id | TEXT NOT NULL | A-01 through A-12 |
| agent_name | TEXT | Human-readable name |
| status | TEXT DEFAULT 'idle' | idle/running/error/disabled |
| last_run | DATETIME | Last execution time |
| last_success | DATETIME | Last successful run |
| items_processed | INTEGER DEFAULT 0 | Items in last run |
| errors_last_run | INTEGER DEFAULT 0 | Errors in last run |
| total_runs | INTEGER DEFAULT 0 | Lifetime run count |
| total_items | INTEGER DEFAULT 0 | Lifetime items processed |
| avg_duration_sec | REAL | Average run duration |
| updated_at | DATETIME DEFAULT CURRENT_TIMESTAMP | Last heartbeat |

### Indexes
```sql
CREATE INDEX idx_raw_listings_source ON raw_listings(source);
CREATE INDEX idx_raw_listings_company ON raw_listings(company);
CREATE INDEX idx_raw_listings_scraped_at ON raw_listings(scraped_at);
CREATE INDEX idx_clean_listings_ppo_score ON clean_listings(ppo_score DESC);
CREATE INDEX idx_clean_listings_ghost ON clean_listings(is_ghost);
CREATE INDEX idx_clean_listings_blue_ocean ON clean_listings(is_blue_ocean);
CREATE INDEX idx_clean_listings_company_id ON clean_listings(company_id);
CREATE INDEX idx_clean_listings_status ON clean_listings(status);
CREATE INDEX idx_companies_tier ON companies(tier);
CREATE INDEX idx_companies_name ON companies(normalized_name);
CREATE INDEX idx_companies_sector ON companies(sector);
CREATE INDEX idx_intent_signals_company ON intent_signals(company_id);
CREATE INDEX idx_intent_signals_score ON intent_signals(signal_score DESC);
CREATE INDEX idx_outcomes_listing ON outcomes(listing_id);
CREATE INDEX idx_outcomes_status ON outcomes(status);
CREATE INDEX idx_api_quotas_provider_date ON api_quotas(provider, date);
CREATE INDEX idx_agent_heartbeats_agent ON agent_heartbeats(agent_id);
CREATE INDEX idx_dark_channel_detected ON dark_channel_listings(detected_at);
CREATE INDEX idx_proxy_health_alive ON proxy_health(is_alive);
```

---

## 10. PPO SCORING FORMULA <a name="ppo-scoring-formula"></a>

### Formula
```
PPO = Σ(wi × vi) for i in 1..10

Where:
  v1 = has_ppo_tag (0 or 1, ×100)
  v2 = tier_score (Tier1=100, Tier2=80, Tier3=60, Tier4=40, Tier5=20, Unknown=30)
  v3 = applicant_bonus = max(0, 100 - (applicants × 0.2))
  v4 = stipend_score = min(100, (stipend_monthly / category_median) × 50)
  v5 = duration_score = 100 if 2-6mo, 70 if 1mo, 50 if >6mo
  v6 = cirs_score (from companies table, 0-100)
  v7 = sector_momentum (from economic signals, 0-100)
  v8 = intent_signal (from A-01, latest score for company, 0-100)
  v9 = historic_callback = (company_interview_rate × 100) if ≥20 samples, else 50
  v10 = recency_bonus = max(0, 100 - (posted_days_ago × 15))

Default Weights:
  w = [0.20, 0.18, 0.15, 0.08, 0.05, 0.12, 0.07, 0.08, 0.05, 0.02]
  Sum = 1.00
```

### Weight Retraining (A-11)
After ≥20 outcomes logged, logistic regression retrains weights weekly using:
- Features: same 10 variables at time of application
- Target: binary (interview=1, reject=0)
- New weights replace defaults if model accuracy > 60%

---

## 11. GHOST DETECTION <a name="ghost-detection"></a>

### 5-Signal System
```
Ghost_Score = S1 + S2 + S3 + S4 + S5

S1 (Listing Age):     >30d = 25pts, 20-30d = 15pts, 10-20d = 8pts, <10d = 0pts
S2 (Applicant Flood):  >500 still open = 20pts, >300 = 12pts, >200 = 5pts
S3 (Repeat Posting):   Same role posted 3+ times = 20pts, 2x = 10pts
S4 (No HR Signal):     Company has 0 intent signals in 30d = 15pts, <3 signals = 8pts
S5 (ATS Mismatch):     Listing NOT on company ATS = 20pts, ATS unknown = 5pts

CLASSIFICATION:
  Ghost_Score ≥ 60  → GHOST (filtered out)
  Ghost_Score 40-59 → SUSPICIOUS (flagged)
  Ghost_Score < 40  → CLEAN (keep)
```

---

## 12. DEDUP ENGINE <a name="dedup-engine"></a>

### 6-Layer Pipeline
```
Layer 1: URL Exact Match        → O(1) hash lookup
Layer 2: Title+Company Exact    → Normalized string equality
Layer 3: Fuzzy String (RapidFuzz) → Ratio ≥ 85 = duplicate
Layer 4: BERT Semantic Similarity → Cosine ≥ 0.92 = duplicate
Layer 5: Location+Stipend Match → Same company + city + stipend = likely dup
Layer 6: Cross-Platform ID      → Extract platform IDs, match across sources
```

Each layer has a confidence score. If ANY layer flags duplicate, merge entries (keep earliest, update applicant count).

---

## 13. 24-HOUR AGENT SCHEDULE <a name="agent-schedule"></a>

| Time (IST) | Agent | Task | Est. Duration |
|:----------:|:-----:|------|:-------------:|
| 05:30 | A-03 | Internshala full scrape (10 categories) | 45 min |
| 06:00 | A-06 | Dedup engine on overnight batch | 15 min |
| 06:15 | A-05 | Ghost scoring (Cerebras) | 20 min |
| 06:30 | A-07 | Intelligence enrichment | 15 min |
| 07:00 | A-08 | PPO model runs → top 25 shortlist | 10 min |
| 07:15 | A-12 | **📱 MORNING BRIEF → Telegram** | 1 min |
| 09:00 | A-01 | Intent signal scan (Tier 1+2 companies) | 30 min |
| 12:00 | A-03 | Naukri + IIMjobs scrape | 30 min |
| 14:00 | A-04 | Company ATS pages (Greenhouse/Lever/Workday) | 45 min |
| 16:00 | A-01 | Second intent scan (RSS + LinkedIn HR via DDG) | 30 min |
| 18:00 | A-06+A-07 | Afternoon batch dedup + enrichment | 20 min |
| 20:00 | A-02 | Telegram dark channel batch check | 15 min |
| 22:00 | A-12 | **📱 EVENING SUMMARY → Telegram** | 1 min |
| 23:00 | A-04 | Nightly company career page crawl (300 companies) | 60 min |
| Sun 21:00 | A-11 | Weekly outcome learner / retrain PPO weights | 10 min |

---

## 14. TELEGRAM COMMAND CENTER (22 Commands) <a name="telegram-commands"></a>

### Morning Report Template
```
🌅 MORNING BRIEF — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Total New: [X] | After Ghost Filter: [Y]
🌊 Blue Ocean Alerts: [Z]
📡 Intent Signals Fired: [N]

🏆 TOP 10 BY PPO SCORE:
1. [Title] @ [Company] — PPO: [Score] 🔵[Blue Ocean if applicable]
2. ...

🌑 DARK CHANNEL FINDS: [count]
⏰ URGENT DEADLINES (48hrs): [count]
📡 INTENT ALERTS: [details]
```

### Command Reference

| # | Command | Description | Agent(s) |
|---|---------|-------------|----------|
| 1 | `/morning` | Full morning brief | A-08, A-12 |
| 2 | `/top [N]` | Top N by PPO score | A-08 |
| 3 | `/ocean` | Blue Ocean listings | A-07 |
| 4 | `/internshala [query]` | Live Internshala search | A-03 |
| 5 | `/dark` | Latest dark channel finds | A-02 |
| 6 | `/signals` | Active intent signals this week | A-01 |
| 7 | `/package [id]` | Full application package (cover+ATS+intro) | A-10, A-09, A-12 |
| 8 | `/ats [id]` | ATS simulation + keyword gap + resume tweaks | A-10 |
| 9 | `/cover [id]` | 200-word tailored cover letter | A-12 |
| 10 | `/network [company]` | Alumni/warm intro map + outreach draft | A-09 |
| 11 | `/apply [id]` | Mark listing as applied | A-12 |
| 12 | `/outcome [id] [result]` | Log outcome (interview/reject/offer/ppo) | A-11 |
| 13 | `/cirs [company]` | Company Intern Readiness Score breakdown | A-07 |
| 14 | `/research [company]` | Full company brief (News+Glassdoor+CIRS+Signals) | A-01, A-09 |
| 15 | `/stats` | Weekly funnel + top sector performance | A-11 |
| 16 | `/health` | Heartbeats for all 12 agents | A-12 |
| 17 | `/quota` | Daily API usage (Groq, Cerebras, SerpAPI) | A-12 |
| 18 | `/help` | Command reference | A-12 |
| 19 | `/start` | Welcome message + setup | A-12 |
| 20 | `/export` | Export listings to Excel | A-12 |
| 21 | `/settings` | User preferences (sectors, locations, min stipend) | A-12 |
| 22 | `/refresh` | Force re-scrape current sources | A-03 |

---

## 15. RENDER FREE TIER DEPLOYMENT <a name="render-deployment"></a>

### Render Constraints
- **RAM:** 512 MB (free tier)
- **CPU:** Shared
- **Hours:** 750 hours/month (enough for 24/7)
- **Disk:** Ephemeral (need SQLite backup strategy)
- **Spin-down:** After 15 min inactivity (use keep-alive ping)

### Deployment Strategy
1. **Worker Service** (not Web Service) to avoid HTTP requirement
2. **SQLite** stored on ephemeral disk with periodic backup to Cloudflare KV
3. **Keep-alive:** Self-ping every 10 minutes via Telegram webhook or internal timer
4. **Memory optimization:** Lazy-load sentence-transformers, batch processing
5. **Startup:** Initialize DB → Seed companies → Start scheduler → Start Telegram bot

### render.yaml
```yaml
services:
  - type: worker
    name: operation-firstmover
    runtime: python
    buildCommand: pip install -r requirements.txt && python -c "import nltk; nltk.download('punkt_tab')"
    startCommand: python main.py
    envVars:
      - key: GROQ_API_KEY
        sync: false
      - key: CEREBRAS_API_KEY
        sync: false
      - key: TG_BOT_TOKEN
        sync: false
      - key: TG_CHAT_ID
        sync: false
      - key: SERP_API_KEY
        sync: false
      - key: WEBSHARE_KEY
        sync: false
      - key: CF_WORKER_URL
        sync: false
      - key: CF_RELAY_SECRET
        sync: false
    plan: free
    region: oregon
```

### Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import nltk; nltk.download('punkt_tab')"
COPY . .
CMD ["python", "main.py"]
```

---

## 16. FILE-BY-FILE BUILD CHECKLIST <a name="build-checklist"></a>

### Core Infrastructure
- [ ] `core/__init__.py` — Package init
- [ ] `core/config.py` — All configuration, env vars, constants, rate limits
- [ ] `core/database.py` — SQLite schema, migrations, all CRUD operations
- [ ] `core/ai_router.py` — Dual-brain AI routing (Groq + Cerebras) + quota tracking
- [ ] `core/stealth_engine.py` — 4-layer proxy, UA rotation, TLS fingerprinting, timing
- [ ] `core/company_db_seed.py` — 1080+ company seeder with auto-classification

### 12 Agents
- [ ] `agents/__init__.py` — Package init
- [ ] `agents/a01_intent_scanner.py` — Intent Signal Scanner
- [ ] `agents/a02_dark_channel.py` — Dark Channel Listener
- [ ] `agents/a03_primary_scraper.py` — Primary Multi-Source Scraper
- [ ] `agents/a04_ats_crawler.py` — Company ATS Crawler
- [ ] `agents/a05_ghost_detector.py` — Ghost Job Detector
- [ ] `agents/a06_dedup_engine.py` — 6-Layer Deduplication
- [ ] `agents/a07_intelligence_enricher.py` — Intelligence Enricher + Blue Ocean
- [ ] `agents/a08_ppo_optimizer.py` — PPO Ranking Optimizer
- [ ] `agents/a09_network_mapper.py` — Network/Alumni Mapper
- [ ] `agents/a10_ats_simulator.py` — ATS Keyword Simulator
- [ ] `agents/a11_outcome_learner.py` — Self-Improvement Learner
- [ ] `agents/a12_telegram_reporter.py` — Telegram Bot (22 commands)

### Orchestration & Deployment
- [ ] `core/scheduler.py` — APScheduler 24-hour orchestration
- [ ] `main.py` — Entry point
- [ ] `requirements.txt` — All dependencies
- [ ] `Dockerfile` — Container definition
- [ ] `render.yaml` — Render deployment config
- [ ] `.env.example` — Environment variable template
- [ ] `.gitignore` — Git ignore rules

### Cloudflare
- [ ] `cloudflare/relay_worker.js` — CF Worker relay code

---

## 17. ENVIRONMENT VARIABLES <a name="environment-variables"></a>

```env
# === AI PROVIDERS ===
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
CEREBRAS_API_KEY=csk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx

# === TELEGRAM ===
TG_BOT_TOKEN=7xxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TG_CHAT_ID=xxxxxxxxxx
TG_API_ID=xxxxxxxx          # For Telethon (dark channels)
TG_API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# === SEARCH & DISCOVERY ===
SERP_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BING_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# === PROXY & STEALTH ===
WEBSHARE_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CF_WORKER_URL=https://your-relay.your-subdomain.workers.dev
CF_RELAY_SECRET=your-secret-key-here

# === TWITTER/X ===
X_BEARER_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# === APP CONFIG ===
DATABASE_PATH=data/firstmover.db
LOG_LEVEL=INFO
TIMEZONE=Asia/Kolkata
RENDER_DEPLOY=true
```

---

## 18. TECHNOLOGY STACK <a name="technology-stack"></a>

### Python Dependencies
```
# AI & LLM
groq>=0.9
cerebras-cloud-sdk>=1.0

# Scraping & HTTP
curl_cffi>=0.7
requests>=2.31
aiohttp>=3.9
beautifulsoup4>=4.12
lxml>=5.0

# Browser Automation
playwright>=1.44
playwright-stealth>=1.0

# Telegram
python-telegram-bot>=21
telethon>=1.36

# Twitter/X
tweepy>=4.14

# Search
duckduckgo-search>=4.0
feedparser>=6.0

# NLP & ML
rapidfuzz>=3.0
sentence-transformers>=3.0
scikit-learn>=1.4
numpy>=1.26
nltk>=3.8

# Scheduling
APScheduler>=3.10

# Proxy & Anonymity
stem>=1.8

# Data & Export
openpyxl>=3.1
icalendar>=5.0

# Utilities
python-dotenv>=1.0
loguru>=0.7
```

---

## BUILD STATUS TRACKER

**Total: 21,251 lines of Python | 22,385 lines total (including JS, MD, YAML)**

| # | File | Status | Lines | Notes |
|---|------|--------|:-----:|-------|
| 1 | `OPERATION_PLAN.md` | ✅ COMPLETE | 1,025 | Full build plan |
| 2 | Project Structure + configs | ✅ COMPLETE | — | .env, .gitignore, render.yaml, Dockerfile, requirements.txt |
| 3 | `core/config.py` | ✅ COMPLETE | 1,789 | 20 config sections, singleton, validation |
| 4 | `core/database.py` | ✅ COMPLETE | 2,263 | 12 tables, 30+ indexes, full CRUD |
| 5 | `core/ai_router.py` | ✅ COMPLETE | 1,549 | Dual-brain routing, rate limiting, circuit breaker |
| 6 | `core/stealth_engine.py` | ✅ COMPLETE | 1,165 | 4-layer proxy, TLS fingerprinting, timing |
| 7 | `agents/a01_intent_scanner.py` | ✅ COMPLETE | 1,525 | RSS + GNews + DDG, signal scoring, decay engine |
| 8 | `agents/a02_dark_channel.py` | ✅ COMPLETE | 1,242 | Telegram + Twitter + Reddit, AI classify |
| 9 | `agents/a03_primary_scraper.py` | ✅ COMPLETE | 1,210 | Internshala + Naukri + IIMjobs + LinkedIn |
| 10 | `agents/a04_ats_crawler.py` | ✅ COMPLETE | 2,313 | Greenhouse + Lever + Workday + Wellfound + Ashby |
| 11 | `agents/a05_ghost_detector.py` | ✅ COMPLETE | 726 | 5-signal ghost scoring system |
| 12 | `agents/a06_dedup_engine.py` | ✅ COMPLETE | 1,437 | 6-layer dedup (URL/fuzzy/BERT/location/platform) |
| 13 | `agents/a07_intelligence_enricher.py` | ✅ COMPLETE | 1,202 | Blue Ocean + CIRS + competition analysis |
| 14 | `agents/a08_ppo_optimizer.py` | ✅ COMPLETE | 961 | 10-variable PPO formula with batch scoring |
| 15 | `agents/a09_network_mapper.py` | ✅ COMPLETE | 639 | Alumni DDG + SerpAPI + outreach drafts |
| 16 | `agents/a10_ats_simulator.py` | ✅ COMPLETE | 458 | ATS keyword gap + resume tweaks |
| 17 | `agents/a11_outcome_learner.py` | ✅ COMPLETE | 469 | LogReg retrain + funnel analytics |
| 18 | `agents/a12_telegram_reporter.py` | ✅ COMPLETE | 1,032 | 22 commands + scheduled reports + alerts |
| 19 | `core/scheduler.py` | ✅ COMPLETE | 490 | APScheduler 24-hour IST, 16 daily + 2 infra jobs |
| 20 | `core/company_db_seed.py` | ✅ COMPLETE | 462 | 1,080+ companies across 5 tiers |
| 21 | `main.py` | ✅ COMPLETE | 317 | 8-step startup, signal handling, graceful shutdown |
| 22 | `cloudflare/relay_worker.js` | ✅ COMPLETE | 109 | CF Worker relay for IP masking |

---

*This document is the single source of truth for Operation First Mover v5. Every file built must conform to these specifications.*
