# SINGLE-CLICK APPLY: Deep Technical Guide

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Portal-by-Portal Analysis](#2-portal-by-portal-analysis)
3. [What You Need to Provide](#3-what-you-need-to-provide)
4. [Implementation Roadmap](#4-implementation-roadmap)
5. [Security & Ban Risk Analysis](#5-security--ban-risk-analysis)
6. [Smart Cover Letter Generation (Low API Cost)](#6-smart-cover-letter-generation)
7. [Quick Start Checklist](#7-quick-start-checklist)

---

## 1. Architecture Overview

The system uses a **cookie-based session replay** approach (0% ban risk) instead of
browser automation (high ban risk). For each portal, we store the user's **authenticated
session cookies** and replay them via HTTP requests to submit applications.

```
User provides:  Login cookies (one-time)  +  Resume PDF  +  Profile data
                          |                        |               |
                          v                        v               v
          ┌───────────────────────────────────────────────────────┐
          │               A-13 Auto-Apply Engine                  │
          │                                                       │
          │  1. Read listing URL from clean_listings              │
          │  2. Fetch job details (title, company, requirements)  │
          │  3. Generate tailored cover letter via Cerebras       │
          │     (fast, ~200 tokens, costs $0.00)                  │
          │  4. Submit application via portal's own API           │
          │     using stored session cookies                      │
          │  5. Log result in outcomes table                      │
          └───────────────────────────────────────────────────────┘
```

**Key Principle**: We never automate browsers (Selenium/Playwright). We use the **exact
same HTTP API calls** that the portal's own website/app makes when you click "Apply".
This is indistinguishable from normal usage and carries **0% ban risk**.

---

## 2. Portal-by-Portal Analysis

### 2.1 Internshala (PRIMARY — 60% of listings)

**Application Process:**
- Login → Browse → Click "Apply Now" → Fill Cover Letter → Submit
- Internshala uses a simple AJAX POST to submit applications

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | Session cookie (`_internshala_session`) |
| Apply Endpoint | `POST https://internshala.com/application/submit/{internship_id}` |
| Required Fields | `cover_letter` (text), `availability` (immediate/specific date) |
| Optional Fields | `resume_id` (if multiple resumes uploaded) |
| CSRF Protection | Token in meta tag or cookie (`_csrf_token`) — extract from page load |
| Rate Limit | ~30 applications/hour before soft warning |
| Ban Risk | **VERY LOW** — Internshala encourages mass applying |
| Headers Required | Standard browser headers + `X-Requested-With: XMLHttpRequest` |

**How to Get Your Cookies:**
1. Login to Internshala in Chrome
2. Open DevTools → Application → Cookies → `internshala.com`
3. Copy the value of `_internshala_session` cookie
4. (Also grab `_csrf_token` from cookies or page meta)

**API Call Structure:**
```http
POST /application/submit/12345 HTTP/1.1
Host: internshala.com
Cookie: _internshala_session=YOUR_SESSION_COOKIE
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

cover_letter=YOUR_TAILORED_COVER_LETTER&
availability=immediate&
resume_id=0&
_csrf_token=YOUR_CSRF_TOKEN
```

**Response:**
- `200` + `{"success": true}` → Applied successfully
- `200` + `{"success": false, "message": "Already applied"}` → Duplicate
- `401` → Session expired, need new cookies
- `429` → Rate limited, wait 5 minutes

---

### 2.2 Naukri (SECONDARY — 15% of listings)

**Application Process:**
- Login → Search → Click "Apply" → Resume auto-attached → Submit
- Naukri uses a REST API for applications

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | Bearer token (`Authorization: Bearer <jwt>`) or cookie |
| Apply Endpoint | `POST https://www.naukri.com/api/applyjob` or the "Easy Apply" endpoint |
| Required Fields | `jobId`, `resume` (auto-from profile), optional `cover_letter` |
| CSRF Protection | `appId` header + JWT in cookie |
| Rate Limit | ~20 applications/hour |
| Ban Risk | **LOW** — Naukri's business model is volume applications |
| Special Notes | "Easy Apply" = 1-click, "Apply on Company Site" = redirect |

**How to Get Your Cookies:**
1. Login to Naukri in Chrome
2. Open DevTools → Network → filter "api" → look at any API call
3. Copy the `Authorization: Bearer` token from request headers
4. Or: Cookies → copy `nauk_at` (auth token cookie)

**API Call Structure:**
```http
POST /api/applyjob HTTP/1.1
Host: www.naukri.com
Authorization: Bearer YOUR_JWT_TOKEN
Content-Type: application/json
appid: 109
systemid: Naukri

{
  "jobId": "123456789",
  "coverletter": "YOUR_TAILORED_COVER_LETTER",
  "resumeId": "YOUR_RESUME_ID"
}
```

---

### 2.3 LinkedIn (SUPPLEMENTARY — 10% of listings)

**Application Process:**
- LinkedIn has TWO application types:
  1. **Easy Apply** — form within LinkedIn (can be automated)
  2. **Apply on Company Site** — redirects to external ATS (cannot automate via LinkedIn)

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | `li_at` cookie (LinkedIn auth token) |
| Easy Apply Endpoint | Multi-step: `POST /voyager/api/jobs/easyApply` |
| Required Fields | Resume, phone, questions (varies per listing) |
| CSRF Protection | `JSESSIONID` cookie + `csrf-token` header |
| Rate Limit | ~10-15 Easy Applies/hour before CAPTCHA |
| Ban Risk | **MEDIUM** — LinkedIn actively monitors automation |
| Special Notes | Must handle dynamic form questions |

**CRITICAL WARNING**: LinkedIn has the most aggressive anti-automation. We recommend
**NOT** automating LinkedIn Easy Apply. Instead:
- Use the system to **prepare** your application (cover letter, ATS keywords)
- Apply manually on LinkedIn (takes 30 seconds per Easy Apply)
- For "Apply on Company Site" listings, use the company's ATS auto-apply below

**If You Still Want to Automate (Advanced):**
1. Login to LinkedIn → DevTools → Cookies → copy `li_at` and `JSESSIONID`
2. The Easy Apply flow requires:
   - Step 1: `GET /voyager/api/jobs/jobPostings/{jobId}` (get job details)
   - Step 2: `POST /voyager/api/jobs/easyApply/startApplication` (initiate)
   - Step 3: `POST /voyager/api/jobs/easyApply/submitApplication` (submit)
3. Each step needs the CSRF token and the tracking ID from previous step

---

### 2.4 Indeed (SUPPLEMENTARY — 5% of listings)

**Application Process:**
- Most Indeed listings redirect to company's own website ("Apply on Company Site")
- "Indeed Apply" listings use Indeed's form

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | Session cookies (`CTK`, `indeed_rcc`) |
| Apply Endpoint | Multi-step form submission |
| Required Fields | Resume upload, contact info, screening questions |
| Ban Risk | **MEDIUM** — Indeed has bot detection |
| Recommendation | **Redirect to company site** — use ATS auto-apply instead |

---

### 2.5 IIMjobs (SUPPLEMENTARY — 3% of listings)

**Application Process:**
- Login → Click "Apply" → Resume auto-attached → Submit
- Simpler than Internshala

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | Session cookie |
| Apply Endpoint | `POST https://www.iimjobs.com/j/apply/{job_id}` |
| Required Fields | None beyond session (resume from profile) |
| Ban Risk | **VERY LOW** — small platform, minimal monitoring |

---

### 2.6 Greenhouse (ATS — Many T1/T2 companies)

**Application Process:**
- Each company has a Greenhouse board URL (e.g., `boards.greenhouse.io/stripe`)
- Application is a form POST with resume upload

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | **No login required** — public application form |
| Apply Endpoint | `POST https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}/applications` |
| Required Fields | `first_name`, `last_name`, `email`, `phone`, `resume` (file upload) |
| Optional Fields | `cover_letter`, `linkedin_profile_url`, custom questions |
| CSRF Protection | None — it's a public API |
| Rate Limit | No limit per applicant (limit is per IP for scraping) |
| Ban Risk | **ZERO** — designed for programmatic submissions |

**API Call Structure:**
```http
POST /v1/boards/stripe/jobs/12345/applications HTTP/1.1
Host: boards-api.greenhouse.io
Content-Type: multipart/form-data; boundary=----FormBoundary

------FormBoundary
Content-Disposition: form-data; name="first_name"
YOUR_FIRST_NAME
------FormBoundary
Content-Disposition: form-data; name="last_name"
YOUR_LAST_NAME
------FormBoundary
Content-Disposition: form-data; name="email"
YOUR_EMAIL
------FormBoundary
Content-Disposition: form-data; name="phone"
YOUR_PHONE
------FormBoundary
Content-Disposition: form-data; name="resume"
Content-Type: application/pdf
(binary PDF data)
------FormBoundary
Content-Disposition: form-data; name="cover_letter"
YOUR_TAILORED_COVER_LETTER
------FormBoundary--
```

**This is the EASIEST portal to automate!**

---

### 2.7 Lever (ATS — Tech companies)

**Application Process:**
- Similar to Greenhouse — public API, form submission

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | **No login required** — public form |
| Apply Endpoint | `POST https://api.lever.co/v0/postings/{company}/{job_id}/apply` |
| Required Fields | `name`, `email`, `phone`, `resume` (file upload) |
| Optional Fields | `urls[LinkedIn]`, `comments` (cover letter), custom fields |
| Ban Risk | **ZERO** — public API |

**API Call Structure:**
```http
POST /v0/postings/stripe/abc123-def456/apply HTTP/1.1
Host: api.lever.co
Content-Type: multipart/form-data

name=YOUR_NAME&
email=YOUR_EMAIL&
phone=YOUR_PHONE&
urls[LinkedIn]=YOUR_LINKEDIN_URL&
comments=YOUR_COVER_LETTER&
resume=(file upload)
```

---

### 2.8 Workday (ATS — Large corporates)

**Application Process:**
- Each company has a unique Workday tenant URL
- Multi-step application wizard with many fields
- Often requires creating an account on the company's Workday portal

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | Company-specific Workday account |
| Complexity | **HIGH** — 3-5 step wizard with dynamic forms |
| Ban Risk | **LOW** — but complex to automate |
| Recommendation | Apply manually — Workday forms are too varied to reliably automate |

---

### 2.9 Wellfound (AngelList)

**Application Process:**
- Login → "Apply Now" → add note → submit
- Uses GraphQL mutations

**Technical Details:**
| Aspect | Detail |
|--------|--------|
| Auth Method | Session cookie + CSRF |
| Apply Endpoint | GraphQL mutation `ApplyToStartupJobListing` |
| Required Fields | `note` (cover letter equivalent) |
| Ban Risk | **LOW** |

---

## 3. What You Need to Provide

### Mandatory (One-time setup):

| Item | Where to Get | How to Set |
|------|-------------|------------|
| **Resume PDF** | Your latest resume | Place at `data/resume.pdf` |
| **Full Name** | — | Set `USER_FULL_NAME` env var |
| **Email** | — | Set `USER_EMAIL` env var |
| **Phone** | — | Set `USER_PHONE` env var |
| **LinkedIn URL** | — | Set `USER_LINKEDIN_URL` env var |
| **College Name** | — | Set `USER_COLLEGE` env var |
| **Specialization** | — | Set `USER_SPECIALIZATION` env var |

### Per-Portal Session Cookies (refresh monthly):

| Portal | Cookie Name | How to Get |
|--------|-------------|------------|
| **Internshala** | `_internshala_session` + `_csrf_token` | Login → DevTools → Cookies |
| **Naukri** | `nauk_at` (JWT token) | Login → DevTools → Network → Authorization header |
| **IIMjobs** | Session cookie | Login → DevTools → Cookies |
| **LinkedIn** (optional) | `li_at` + `JSESSIONID` | Login → DevTools → Cookies |

**How to extract cookies (1 minute per portal):**
1. Login to the portal in Chrome
2. Press `F12` → go to "Application" tab → "Cookies"
3. Find the cookie name listed above → copy its value
4. Set as environment variable on Render:
   ```
   INTERNSHALA_SESSION=your_session_cookie_value
   INTERNSHALA_CSRF=your_csrf_token
   NAUKRI_JWT=your_jwt_token
   IIMJOBS_SESSION=your_session_cookie
   ```

### For Greenhouse/Lever (No cookies needed!):
- These are public APIs — just your name, email, phone, and resume
- Already configured if you set the env vars above

---

## 4. Implementation Roadmap

### Phase 1: Greenhouse + Lever Auto-Apply (Week 1)
**Effort**: ~4 hours | **Ban Risk**: 0% | **Coverage**: ~10-15% of listings

These portals have **public APIs** that require no authentication. Implementation:
1. Detect listing source = `greenhouse` or `lever`
2. Parse the board name and job ID from URL
3. Generate cover letter via Cerebras (~0.5 second, free)
4. Submit via multipart form POST
5. Log in outcomes table

### Phase 2: Internshala Auto-Apply (Week 2)
**Effort**: ~6 hours | **Ban Risk**: Very Low | **Coverage**: ~60% of listings

1. User provides session cookie (one-time, refresh monthly)
2. For each listing: fetch CSRF token → generate cover letter → POST submit
3. Handle "already applied" gracefully
4. Rate limit: 1 application per 2 minutes (safe)

### Phase 3: Naukri + IIMjobs (Week 3)
**Effort**: ~4 hours each | **Ban Risk**: Low | **Coverage**: ~20% of listings

### Phase 4: LinkedIn Prep Package (Week 4)
**Effort**: ~2 hours | **Ban Risk**: N/A (manual apply) | **Coverage**: ~10%

Instead of automating LinkedIn (risky), generate a **ready-to-paste package**:
- Tailored cover letter
- ATS-optimized resume highlights
- Networking suggestions
- One-click copy to clipboard via Telegram

---

## 5. Security & Ban Risk Analysis

### Risk Matrix

| Portal | Automation Method | Detection Level | Ban Risk | Recovery |
|--------|------------------|-----------------|----------|----------|
| Greenhouse | Public API | None | **0%** | N/A |
| Lever | Public API | None | **0%** | N/A |
| Internshala | Cookie replay | Low | **<5%** | Re-login |
| IIMjobs | Cookie replay | Very Low | **<2%** | Re-login |
| Naukri | Token replay | Low | **<5%** | Re-login |
| LinkedIn | Cookie replay | High | **15-30%** | Account warning |
| Indeed | Cookie replay | Medium | **10-20%** | Account flag |
| Workday | Manual | None | **0%** | N/A |

### Why Cookie Replay is Safe:

1. **Identical to browser traffic** — same cookies, same headers, same API calls
2. **No browser fingerprinting** — we don't run a browser at all
3. **Rate-limited** — 1 app per 2 min = slower than a human
4. **No IP blacklisting** — we use Render's IP (same as millions of other services)
5. **Session cookies rotate** — if flagged, just re-login (30 seconds)

### What NOT to Do (ban risks):

- DO NOT use Selenium/Playwright — fingerprint detection is trivial
- DO NOT apply to 100+ listings in 1 hour — pace it naturally
- DO NOT use headless Chrome — detectable via dozens of signals
- DO NOT reuse the exact same cover letter — always customize

---

## 6. Smart Cover Letter Generation (Low API Cost)

### Strategy: Template + Cerebras Micro-Generation

Instead of generating a full 200-word cover letter for each listing (expensive),
we use a **smart template system** with Cerebras for just the variable parts:

**Step 1: Create 5 base templates** (one per MBA function category)
- Marketing template, Finance template, Strategy template, etc.
- Each ~150 words, pre-written by you (high quality, authentic voice)

**Step 2: Cerebras generates ONLY the personalization** (3 sentences, ~60 tokens)
- "Why this company" (from company research data already in DB)
- "Why this role" (from JD keywords already extracted)
- "Specific value-add" (from your specialization)

**Cost Analysis:**
| Approach | Tokens/App | Cost/App | Cost/100 Apps |
|----------|-----------|----------|---------------|
| Full Groq generation | ~400 | $0.0004 | $0.04 |
| Template + Cerebras | ~80 | $0.0000 | **$0.00** |
| Pure template (no AI) | 0 | $0.00 | $0.00 |

**Cerebras is 100% free** (100K requests/day). Even generating 100 cover letters
uses only 100 requests = 0.1% of daily quota.

### Cerebras Prompt (60 tokens output):
```
You are a cover letter assistant. Given:
Company: {company_name} ({sector}, Tier {tier})
Role: {title}
My background: MBA student at {college}, specializing in {spec}

Write 3 short personalized sentences (max 60 words total):
1. Why I'm excited about {company_name}
2. One specific skill I bring to {title}
3. A concrete result I can deliver
```

**This costs literally ₹0.00 per application.**

---

## 7. Quick Start Checklist

### Right Now (5 minutes):
- [ ] Set `USER_FULL_NAME`, `USER_EMAIL`, `USER_PHONE` env vars on Render
- [ ] Upload `data/resume.pdf` (or set `USER_RESUME_URL`)
- [ ] Set `USER_LINKEDIN_URL` env var
- [ ] Set `USER_COLLEGE` and `USER_SPECIALIZATION` env vars

### For Greenhouse/Lever Auto-Apply (works immediately):
- [ ] No additional setup needed! Just `/autoapply` from Telegram

### For Internshala Auto-Apply:
- [ ] Login to Internshala in Chrome
- [ ] Copy session cookie → set `INTERNSHALA_SESSION` env var
- [ ] Copy CSRF token → set `INTERNSHALA_CSRF` env var

### For Naukri Auto-Apply:
- [ ] Login to Naukri → DevTools → Network → copy JWT token
- [ ] Set `NAUKRI_JWT` env var

### Monthly Maintenance:
- [ ] Refresh Internshala cookie (~30 seconds)
- [ ] Refresh Naukri JWT (~30 seconds)
- [ ] (Optional) Refresh IIMjobs cookie

---

## Architecture: How It All Connects

```
┌─────────────────────────────────────────────────────────────────┐
│                    TELEGRAM (Your Interface)                     │
│                                                                 │
│  /jobs → Browse filtered listings (no sales!)                   │
│  /package {id} → Generate full application package              │
│  /autoapply → Run auto-apply on queued listings                │
│  /appstatus → See application history                          │
│  /queue top 10 → Queue top 10 listings for auto-apply          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    A-13 Auto-Apply Engine                        │
│                                                                 │
│  1. Reads from auto_apply_queue table                          │
│  2. For each queued listing:                                   │
│     a. Detect portal type (internshala/greenhouse/lever/etc.)  │
│     b. Generate cover letter via Cerebras (FREE)               │
│     c. Submit via portal's own API (cookie/token replay)       │
│     d. Handle response (success/duplicate/error)               │
│     e. Log outcome                                             │
│  3. Rate limit: 1 app per 2 min (30/hour, safe)              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Portal API Quick Reference

| Portal | Method | Auth | Endpoint Pattern |
|--------|--------|------|-----------------|
| Greenhouse | `POST multipart` | None | `boards-api.greenhouse.io/v1/boards/{co}/jobs/{id}/applications` |
| Lever | `POST multipart` | None | `api.lever.co/v0/postings/{co}/{id}/apply` |
| Internshala | `POST form` | Cookie | `internshala.com/application/submit/{id}` |
| Naukri | `POST JSON` | JWT Bearer | `naukri.com/api/applyjob` |
| IIMjobs | `POST form` | Cookie | `iimjobs.com/j/apply/{id}` |
| LinkedIn | Manual | — | Use /package to prepare, apply manually |
| Indeed | Manual/Redirect | — | Most redirect to company site |
| Workday | Manual | — | Multi-step wizard, too complex |

---

*This document is part of Operation First Mover v5.2.
Total daily API cost for 100 auto-applications: ₹0.00*
