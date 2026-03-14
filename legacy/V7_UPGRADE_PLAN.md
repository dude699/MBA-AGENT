# OPERATION FIRST MOVER v7.0 — ULTIMATE PREMIUM UPGRADE PLAN

## Overview
Version 7.0 transforms the scraping system from a basic scheduler into an **AI-powered deep crawling + intelligent scheduling + premium UI platform** that maximizes every available resource with industrial-grade robustness.

---

## KEY CHANGES FROM v6.0

### 1. UI OVERHAUL — Pure White Premium Theme
**Problem:** Current dark theme makes text unreadable on many devices. Screenshots show contrast issues.

**Solution:** Complete flip to **pure white background (#FFFFFF)** with **deep dark black elements (#0A0A0A)** — clean, professional, enterprise-grade readability.

| Element | v6.0 (Dark) | v7.0 (White Premium) |
|---------|-------------|---------------------|
| Background | `#000000` | `#FFFFFF` |
| Cards | `#0a0a0a` | `#FFFFFF` with subtle shadow |
| Text Primary | `#ffffff` | `#0A0A0A` |
| Text Secondary | `rgba(255,255,255,0.5)` | `#6B7280` |
| Borders | `rgba(255,255,255,0.06)` | `#E5E7EB` |
| Buttons Primary | `#ffffff` on black | `#0A0A0A` on white |
| Badges | Dark glass | Light with colored accents |
| Bottom Bar | Black glass | White glass with shadow |
| Chat User Bubble | White on black | Black on white |
| Chat AI Bubble | Dark card | Light gray card |

**Files Changed:**
- `mini-app/src/index.css` — Complete theme rewrite
- `mini-app/index.html` — Theme color meta tag
- `mini-app/src/App.tsx` — Background and text color classes

---

### 2. WEEKLY SCHEDULER v7.0 — AI-Enhanced Deep Scheduling
**Problem:** v6.0 scheduler has lots of unused AI quota headroom (99%+ on Groq/Cerebras).

**Solution:** Use that headroom for AI-powered scheduling decisions, deeper enrichment, and smarter resource allocation.

**New Features:**
- **AI-Powered Schedule Optimization**: Use Cerebras to analyze scraping success rates and dynamically adjust portal timing
- **Deep Crawl Windows**: 4 dedicated deep crawl windows per week instead of just Sunday
- **Predictive Portal Selection**: AI predicts which portals will have fresh listings based on historical patterns
- **Smart Batch Sizing**: Dynamically adjust batch sizes based on available resources and time
- **Multi-Wave Scraping**: 3 waves per day (morning, afternoon, night) instead of 2
- **AI-Enhanced Quality Scoring**: Run AI quality check on every scraped listing during pipeline
- **Resource Optimizer**: Auto-redistribute unused quota to deepening existing data
- **Parallel Pipeline Processing**: Run dedup + ghost + enrich concurrently where possible
- **AI Anomaly Detection**: Detect unusual patterns in scraping results (sudden drops, duplicates surge)

**Resource Utilization Targets (v7.0 vs v6.0):**
| Resource | v6.0 Usage | v7.0 Target | Improvement |
|----------|-----------|-------------|-------------|
| Groq | 0.5% | 8-12% | 16-24x more AI analysis |
| Cerebras | 0.6% | 15-25% | 25-42x more classification |
| CF Workers | 0.7% | 5-8% | 7-11x more relay requests |
| Webshare | 14% | 40-60% | 3-4x more scraping |
| ScraperAPI | 40% | 85-90% | 2x backup coverage |
| SerpAPI | 88% | 95% | Near-full utilization |

---

### 3. SMART PROXY MANAGER v7.0 — AI-Driven Proxy Intelligence
**New Features:**
- **AI Proxy Scorer**: Use Cerebras to score proxy health and predict ban probability
- **Domain-Specific Strategy**: AI determines best proxy type per domain based on history
- **Adaptive Cooldown**: AI adjusts cooldown periods based on ban pattern analysis
- **Intelligent Retry Routing**: When blocked, AI chooses next best proxy source instead of linear fallover
- **Usage Prediction**: Predict daily proxy needs and pre-warm connections
- **Geolocation Optimization**: Match proxy country to target site for best results
- **TLS Fingerprint Rotation**: AI-driven TLS profile selection per request

---

### 4. SELF-HEALING v7.0 — AI-Powered Recovery
**New Features:**
- **AI Error Analysis**: Send error patterns to Cerebras for root cause analysis
- **Predictive Healing**: Detect degradation trends before failures occur
- **Smart Recovery Plans**: AI generates recovery action plans for each error type
- **Cross-Agent Health Correlation**: Detect cascade failures across agents
- **AI-Generated Alerts**: More actionable Telegram alerts with AI-suggested fixes
- **Automatic Mitigation**: AI decides whether to retry, rotate, delay, or escalate
- **Performance Baselining**: AI establishes baselines and detects deviations

---

### 5. AI ROUTER v7.0 — Deeper Integration
**New Tasks:**
- `listing_quality_score`: AI rates listing quality (0-100) before adding to pipeline
- `deep_jd_parse`: Extract 20+ fields from job descriptions using LLM
- `company_intent_predict`: Predict hiring intent from company news/signals
- `salary_benchmark`: AI benchmarks stipend against market rates
- `duplicate_semantic`: Semantic duplicate detection using AI embeddings
- `schedule_optimize`: AI optimizes next day's scraping schedule
- `proxy_strategy`: AI decides proxy routing for next batch
- `anomaly_detect`: AI detects anomalies in scraping results
- `enrichment_priority`: AI ranks which listings need enrichment most

---

### 6. AGENT UPGRADES — Deep Crawling Mode

**A-03 Primary Scraper:**
- 3-wave scraping (AM, PM, Night)
- AI-enhanced listing extraction with quality scoring
- Deep page navigation (follow pagination deeper)
- AI-driven search query generation for each portal

**A-04 ATS Crawler:**
- AI-powered career page discovery (use LLM to find career URLs)
- Deep crawl: follow links 3 levels deep on career pages
- AI extraction of structured data from any career page format
- Company career page monitoring with change detection

**A-07 Intelligence Enricher:**
- AI-powered CIRS score calculation
- Deep company research using LLM
- AI-generated hiring probability scores
- Sector trend analysis using AI

---

## IMPLEMENTATION ORDER

1. **UI Theme Overhaul** (index.css, index.html, App.tsx)
2. **Weekly Scheduler v7.0** (weekly_scheduler.py)
3. **Smart Proxy Manager v7.0** (smart_proxy_manager.py)
4. **Self-Healing v7.0** (self_healing.py)
5. **AI Router v7.0** (ai_router.py)
6. **Config v7.0** (config.py)
7. **Agent Upgrades** (a03, a04, a07)

**Git Strategy:** Commit + PR after every 3 files to save progress.

---

## ENVIRONMENT VARIABLES (No Changes Required)
All existing env vars remain the same. v7.0 uses the SAME free-tier APIs more efficiently.

```
SCRAPERAPI_KEY=     # https://www.scraperapi.com/signup
SCRAPEDO_TOKEN=     # https://scrape.do/signup
SCHEDULE_MODE=weekly
```

---

## SUCCESS METRICS
- **UI Readability**: Pure white background, zero unreadable elements
- **AI Utilization**: Groq 8-12%, Cerebras 15-25% (vs 0.5% today)
- **Scraping Depth**: 3x more pages crawled per portal
- **Data Quality**: AI quality score on 100% of listings
- **Recovery Speed**: 50% faster self-healing
- **Resource Efficiency**: 90%+ utilization on all paid/limited resources
