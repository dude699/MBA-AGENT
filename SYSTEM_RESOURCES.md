# SYSTEM RESOURCES & ARCHITECTURE DOCUMENTATION
## Operation First Mover v6.0 — InternHub Pro

> Comprehensive documentation of all resources, constraints, features, and system architecture.

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [All Resources & APIs](#all-resources--apis)
4. [Constraints & Limitations](#constraints--limitations)
5. [Feature Matrix](#feature-matrix)
6. [Agent System (A-01 to A-13)](#agent-system)
7. [Mini App (InternHub Pro)](#mini-app)
8. [Telegram Bot Commands](#telegram-bot-commands)
9. [Database Schema](#database-schema)
10. [Deployment](#deployment)
11. [Security](#security)
12. [Weekly Schedule](#weekly-schedule)
13. [Cost Breakdown](#cost-breakdown)

---

## System Overview

**Operation First Mover** is a zero-cost MBA internship hunting system that runs 13 AI agents, scrapes 8+ job boards, and provides a Telegram bot + web mini-app for browsing and auto-applying to internships.

**Stack:**
- Backend: Python 3.11+ (aiohttp web server)
- Frontend: React + TypeScript + Vite + Tailwind CSS
- Database: SQLite (local) + Supabase (cloud persistent)
- AI: Groq LLaMA (primary) + Cerebras (fallback)
- Bot: python-telegram-bot v21
- Deployment: Render.com free tier
- Proxy: Webshare residential proxies
- Relay: Cloudflare Workers (anti-block)

---

## Architecture

```
Telegram Bot (A-12)
    |
    v
Main Entry (main.py) --> aiohttp Web Server (port $PORT)
    |                         |
    |-- Phase 1: Config       |-- /health, /status, /ping
    |-- Phase 2: SQLite DB    |-- /api/* (Mini App REST API)
    |-- Phase 3: Data Seed    |-- /app/* (Mini App SPA)
    |-- Phase 4: AI Router    |
    |-- Phase 5: Web Layer    |-- Supabase Cloud DB
    |-- Phase 6: Telegram     |
    |-- Phase 7: Scheduler    |
    |-- Phase 8: Watchdog     |
    |
    v
13 AI Agents (A-01 to A-13)
    |-- A-01: Intent Scanner (SerpAPI + Bing)
    |-- A-02: Dark Channel Listener (Twitter/X)
    |-- A-03: Primary Scraper (Internshala, Naukri, etc.)
    |-- A-04: ATS Crawler (Greenhouse, Lever, Workday)
    |-- A-05: Ghost Detector (identifies fake postings)
    |-- A-06: Dedup Engine (content hash deduplication)
    |-- A-07: Intelligence Enricher (company data)
    |-- A-08: PPO Optimizer (scoring algorithm)
    |-- A-09: Network Mapper (alumni connections)
    |-- A-10: ATS Simulator (keyword matching)
    |-- A-11: Outcome Learner (ML feedback loop)
    |-- A-12: Telegram Reporter (bot + commands)
    |-- A-13: Auto Apply Orchestrator
```

---

## All Resources & APIs

### AI Providers (Free Tier)
| Provider | Model | Rate Limit | Daily Budget | Usage |
|----------|-------|------------|--------------|-------|
| Groq | LLaMA 3 70B | 30 req/min, 14,400 tokens/min | ~500 calls/day | Primary AI brain |
| Cerebras | LLaMA 3 8B | 30 req/min | ~300 calls/day | Fallback AI brain |

### Search & Discovery APIs
| API | Free Quota | Monthly Budget | Usage |
|-----|-----------|----------------|-------|
| SerpAPI | 100 searches/month | 8/day weekdays, 5/day weekends | A-01 Intent Scanner, A-09 Network Mapper |
| Bing Search API | 1,000/month | ~33/day | Fallback search |
| DuckDuckGo | Unlimited | Unlimited | Free fallback |

### Scraping APIs (All Free Tier, No Credit Card)
| API | Free Credits | Usage |
|-----|-------------|-------|
| ScraperAPI | 1,000/month | Fallback scraping |
| Scrape.do | 1,000/month | Fallback scraping |
| ScrapingBee | 1,000 one-time | Fallback scraping |

### Proxy & Anti-Block
| Service | Details | Usage |
|---------|---------|-------|
| Webshare | 10 residential proxies (free tier) | Rotate for scraping |
| Cloudflare Workers | 100K requests/day (free) | Anti-block relay |

### Database
| Service | Details | Usage |
|---------|---------|-------|
| SQLite | Local file (data/firstmover.db) | Primary local DB |
| Supabase | Free tier (500MB, 50K rows) | Persistent cloud DB |

### Telegram
| Resource | Details |
|----------|---------|
| Bot Token | python-telegram-bot v21, polling mode |
| Telegram API (MTProto) | TG_API_ID + TG_API_HASH for Telethon |
| Mini App | WebApp served from /app/ path |

### Hosting
| Service | Plan | Constraints |
|---------|------|-------------|
| Render.com | Free Web Service | 512MB RAM, auto-sleep after 15min inactivity |
| Keep-Alive | 5 layers (self-ping, scheduler, cron-job.org, UptimeRobot, Telegram) |

---

## Constraints & Limitations

### Memory
- **512 MB RAM** on Render free tier
- GC runs every 5 minutes to manage memory
- Watchdog monitors memory usage every 2 minutes
- Mini-app build requires ~300MB during build time

### Rate Limits
- **Groq**: 30 requests/minute, 14,400 tokens/minute
- **Cerebras**: 30 requests/minute (fallback only)
- **SerpAPI**: 100 searches/month total
- **Telegram**: 30 messages/second globally, 1 message/second per chat
- **Scraping**: Rate-limited per source (2-5 second delays)

### Deployment Constraints
- **Render free tier**: Service sleeps after 15 minutes of inactivity
- **Cold start**: ~60-90 seconds to boot + build mini-app
- **Single instance**: Only one instance can poll Telegram at a time
- **No persistent disk**: SQLite DB resets on redeploy (Supabase persists)

### Anti-Detection
- Rotating proxy pool via Webshare
- Cloudflare Worker relay for JavaScript-heavy sites
- Random delays between requests (2-8 seconds)
- User-agent rotation
- Session management with cookies

### Telegram Mini App
- Max 92vh height for bottom sheet panels
- Safe area insets for iOS notch
- Haptic feedback via Telegram WebApp API
- Theme matches Telegram user's theme

---

## Feature Matrix

### Mini App (InternHub Pro) Features
| Feature | Status | Description |
|---------|--------|-------------|
| Browse Listings (Live) | Working | SQLite-based, real-time from scraping |
| Browse Listings (Latest) | Working | Supabase latest session |
| Browse Listings (All Jobs) | Working | Supabase full archive |
| Infinite Scroll | Working | IntersectionObserver sentinel |
| Source Filtering | Working | Filter by Internshala, LinkedIn, etc. |
| Sort Options (16 types) | Working | Stipend, duration, PPO, date, etc. |
| Search | Working | Full-text search across listings |
| Internship Detail View | Working | Full listing with description, skills |
| Batch Auto-Apply | Working | Select multiple + apply with credentials |
| AI Chat (4 profiles) | Working | Career Advisor, Resume, ATS, Strategy |
| CV Upload | NEW v3.0 | PDF upload for AI-aware advice |
| User Profile Editor | NEW v3.0 | College, specialization, skills |
| Analytics Dashboard | Working | Stats, charts, source breakdown |
| Credential Management | Working | Encrypted storage per portal |
| System Status | NEW v3.0 | API, DB, AI, Encryption status |

### Telegram Bot Commands (40+)
| Category | Commands |
|----------|----------|
| Browse | /jobs, /top, /ocean, /loadall, /browse, /filter, /sources |
| Reports | /morning, /dark, /signals, /stats |
| Search | /internshala, /refresh |
| Application | /package, /ats, /cover, /network, /apply, /outcome |
| Auto-Apply | /queue, /autoapply, /appstatus |
| Company Intel | /cirs, /research |
| Agent Control | /run, /schedule, /status, /cancel |
| System | /health, /quota, /cfstatus, /reprocess, /settings |
| Mini App | /miniapp, /webapp |
| Supabase | /dbstatus, /latestjobs, /alljobs |
| Admin | /adduser, /removeuser, /listusers, /gencode, /secstatus |
| Pipeline | /startpipeline, /stoppipeline |

### AI Capabilities
| Profile | Capabilities |
|---------|-------------|
| Career Advisor | Job matching, career strategy, application priority, ghost detection |
| Resume Builder | Cover letters, resume bullets, LinkedIn optimization, SOP writing |
| ATS Analyzer | ATS scoring (0-100), keyword analysis, format checking |
| Career Strategist | Career path planning, stipend benchmarking, PPO strategy, interview prep |

---

## Agent System

### A-01: Intent Scanner
- **Purpose**: Detect hiring intent signals from web searches
- **APIs**: SerpAPI, Bing, DuckDuckGo
- **Budget**: 8 searches/day weekdays, 5/day weekends
- **Output**: Intent signals with confidence scores

### A-02: Dark Channel Listener
- **Purpose**: Monitor X/Twitter for hidden job postings
- **API**: X Bearer Token
- **Output**: Dark channel listings not on job boards

### A-03: Primary Scraper
- **Purpose**: Scrape major Indian job boards
- **Sources**: Internshala, Naukri, Indeed, LinkedIn, IIMJobs, Glassdoor
- **Anti-detection**: Proxy rotation, delays, user-agent randomization

### A-04: ATS Crawler
- **Purpose**: Crawl company ATS platforms directly
- **Sources**: Greenhouse, Lever, Workday, SmartRecruiters, Ashby
- **Method**: API endpoints + HTML parsing

### A-05: Ghost Detector
- **Purpose**: Identify fake/ghost job postings
- **Signals**: Age, applicant count, company activity, duplicate detection
- **Output**: Ghost score (0-100) per listing

### A-06: Dedup Engine
- **Purpose**: Remove duplicate listings across sources
- **Method**: Content hash + fuzzy title matching
- **Output**: Clean, deduplicated listing set

### A-07: Intelligence Enricher
- **Purpose**: Enrich listings with company data
- **Data**: Company tier, sector, CIRS score, funding info

### A-08: PPO Optimizer
- **Purpose**: Score listings by PPO (Placement Probability Optimization)
- **Factors**: Company tier, stipend, applicants, ghost score, category

### A-09: Network Mapper
- **Purpose**: Map alumni connections at target companies
- **API**: SerpAPI for LinkedIn search
- **Output**: Warm intro paths, outreach templates

### A-10: ATS Simulator
- **Purpose**: Simulate ATS keyword matching
- **Method**: JD keyword extraction vs. resume analysis
- **Output**: Match percentage, missing keywords, optimization suggestions

### A-11: Outcome Learner
- **Purpose**: Learn from application outcomes
- **Method**: Track applied -> shortlisted -> interview -> offer pipeline
- **Output**: Model improvements over time

### A-12: Telegram Reporter
- **Purpose**: User interface via Telegram bot
- **Commands**: 40+ commands for browsing, applying, analytics
- **Features**: Inline keyboards, persistent reply keyboard, Mini App integration

### A-13: Auto Apply Orchestrator
- **Purpose**: Automated job application
- **Method**: Browser automation with credentials
- **Features**: Cover letter generation, form filling, rate limiting

---

## Database Schema

### SQLite (Local)
- `companies` - 1081 Indian companies with tier/sector/ATS info
- `raw_listings` - Raw scraped listings before processing
- `clean_listings` - Processed, deduplicated, scored listings
- `outcomes` - Application tracking (applied/interview/offer)
- `agent_heartbeats` - Agent health monitoring
- `settings` - User preferences

### Supabase (Cloud)
- `latest_jobs` - Current scraping session jobs
- `all_jobs` - Complete job archive
- `applied_jobs` - Application tracking (persistent)

---

## Deployment

### Render.com Configuration
```yaml
services:
  - type: web
    name: operation-firstmover
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: python main.py
    envVars:
      - NODE_VERSION: 20.19.0
      - PYTHON_VERSION: 3.11.0
```

### Docker
```dockerfile
FROM python:3.11-slim
# ... (see Dockerfile for full config)
```

### Environment Variables Required
- `GROQ_API_KEY` - Groq AI provider
- `CEREBRAS_API_KEY` - Cerebras fallback
- `TG_BOT_TOKEN` - Telegram bot token
- `TG_CHAT_ID` - Default notification chat
- `SUPABASE_URL` + `SUPABASE_ANON_KEY` - Cloud database
- `SERP_API_KEY` - Search API
- `WEBSHARE_KEY` - Proxy provider
- `ADMIN_TELEGRAM_ID` - Bot admin ID

---

## Security

### Access Control
- Admin-only commands require `ADMIN_TELEGRAM_ID` match
- User whitelist managed via /adduser, /removeuser
- Access codes for Mini App authentication
- Rate limiting on all bot commands

### Credential Storage
- Credentials stored in Zustand persist (localStorage)
- AES-256 encryption indicators in UI
- No plaintext transmission to external servers
- Per-user isolation via Telegram ID

### Anti-Abuse
- Bot polling lock prevents dual instances
- SIGTERM graceful shutdown with session release
- Pre-flight drain to prevent Telegram Conflict errors
- Rate limiting on auto-apply (2-5s delays)

---

## Weekly Schedule

### Mode: Weekly Smart Schedule (v6.0)
Reduces ban risk by 70% compared to daily scraping.

| Day | Time (IST) | Task |
|-----|-----------|------|
| **Monday** | 07:00 | Full pipeline scrape (all sources) |
| | 07:15 | Morning brief report |
| | 12:00 | Dedup + Ghost detection |
| | 18:00 | PPO scoring + enrichment |
| | 22:00 | Evening summary |
| **Wednesday** | 07:00 | Targeted scrape (top sources) |
| | 07:15 | Morning brief |
| | 18:00 | Scoring update |
| | 22:00 | Evening summary |
| **Friday** | 07:00 | Full pipeline scrape |
| | 07:15 | Morning brief |
| | 12:00 | Full processing pipeline |
| | 18:00 | Weekly stats generation |
| | 22:00 | Weekly summary report |
| **Daily** | Every 4min | Self-ping keep-alive |
| | Every 10min | Health check |
| | Every 12hr | Supabase sync |

---

## Cost Breakdown

| Resource | Monthly Cost |
|----------|-------------|
| Render.com hosting | $0 (free tier) |
| Groq AI | $0 (free tier) |
| Cerebras AI | $0 (free tier) |
| SerpAPI | $0 (100 free/month) |
| Supabase | $0 (free tier) |
| Webshare Proxies | $0 (free tier) |
| Cloudflare Workers | $0 (100K free/day) |
| ScraperAPI | $0 (1000 free/month) |
| Scrape.do | $0 (1000 free/month) |
| cron-job.org | $0 (free) |
| UptimeRobot | $0 (free tier) |
| **TOTAL** | **$0.00/month** |

---

## File Structure

```
webapp/
├── main.py                    # Entry point, phased startup
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Docker deployment
├── render.yaml                # Render.com config
├── start.sh                   # Startup script
├── .env.example               # Environment variables template
├── SYSTEM_RESOURCES.md        # This file
│
├── core/                      # Core system modules
│   ├── config.py              # Configuration management
│   ├── database.py            # SQLite database manager
│   ├── ai_router.py           # Groq + Cerebras dual-brain
│   ├── miniapp_api.py         # REST API for Mini App
│   ├── auth_middleware.py     # Authentication
│   ├── security.py            # Access control
│   ├── scheduler.py           # Legacy daily scheduler
│   ├── weekly_scheduler.py    # v6.0 smart weekly scheduler
│   ├── keepalive.py           # 5-layer keep-alive
│   ├── supabase_client.py     # Supabase connection
│   ├── supabase_db.py         # Supabase CRUD operations
│   ├── supabase_keepalive.py  # Supabase connection ping
│   ├── cloudflare_crawl.py    # CF Worker relay
│   ├── smart_proxy_manager.py # Proxy rotation
│   ├── stealth_engine.py      # Anti-detection
│   ├── company_db_seed.py     # 1081 company database
│   ├── job_filter.py          # Management-only filter
│   └── self_healing.py        # Auto-recovery
│
├── agents/                    # 13 AI agents
│   ├── a01_intent_scanner.py
│   ├── a02_dark_channel.py
│   ├── a03_primary_scraper.py
│   ├── a04_ats_crawler.py
│   ├── a05_ghost_detector.py
│   ├── a06_dedup_engine.py
│   ├── a07_intelligence_enricher.py
│   ├── a08_ppo_optimizer.py
│   ├── a09_network_mapper.py
│   ├── a10_ats_simulator.py
│   ├── a11_outcome_learner.py
│   ├── a12_telegram_reporter.py
│   └── a13_auto_apply.py
│
├── mini-app/                  # InternHub Pro frontend
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.cjs
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx           # App entry
│       ├── App.tsx            # Root component
│       ├── index.css          # Global styles
│       ├── components/
│       │   ├── Header.tsx
│       │   ├── BottomBar.tsx
│       │   ├── InternshipCard.tsx
│       │   ├── InternshipDetail.tsx
│       │   ├── FilterPanel.tsx
│       │   ├── SortPanel.tsx
│       │   ├── BatchApplyPanel.tsx
│       │   ├── LLMPanel.tsx
│       │   ├── AnalyticsDashboard.tsx
│       │   ├── SettingsPage.tsx
│       │   ├── Skeletons.tsx
│       │   └── SourceIcons.tsx
│       ├── hooks/useHooks.ts
│       ├── services/api.ts
│       ├── store/useAppStore.ts
│       ├── types/index.ts
│       └── utils/
│           ├── constants.ts
│           └── helpers.ts
│
└── cloudflare/                # CF Worker relay
    ├── relay_worker.js
    ├── wrangler.toml
    └── setup.sh
```

---

*Last updated: 2026-03-14 | Version: 6.0.0 | Overhaul: Major v3.0*
