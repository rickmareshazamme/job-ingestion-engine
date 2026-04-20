# Global AI Job Board — Concrete Plan

## Current State (Honest)

- **Jobs in database:** 0 (prototype only, no DB running)
- **Code built:** 51 files, 5,800 lines, 110 tests passing
- **Proven:** Greenhouse connector pulled 239 real Airbnb jobs
- **Employers seeded:** 40 (20 Greenhouse, 10 Lever, 10 Workday)

## What Actually Works

| Component | Status | Proof |
|---|---|---|
| Greenhouse API connector | ✅ Verified | 239 Airbnb jobs fetched live |
| Lever API connector | ✅ Code works | API is public, no auth needed |
| Workday API connector | ✅ Code works | Undocumented but reverse-engineered |
| Playwright headless crawler | ✅ Code works | For JS-rendered career pages |
| Normalization pipeline | ✅ 72 tests | Salary, location, classification, dedup |
| REST API (14 filters) | ✅ Built | FastAPI with search, employers, stats |
| MCP server (5 tools) | ✅ Built | Claude/ChatGPT integration ready |
| NL query parser | ✅ 29 tests | "remote Python jobs over 100K" → structured |
| SSR frontend + JSON-LD | ✅ Built | SEO-ready with JobPosting schema |
| Sitemap.xml | ✅ Built | Auto-generated for all active jobs |

## What's Missing (The Hard Truth)

| Gap | Impact | Effort |
|---|---|---|
| Rate limiting not enforced | Will get IP-banned at scale | 1-2 days |
| Error handling is silent | Won't know what's failing | 1-2 days |
| Only 40 employers seeded | Need 5,000+ for meaningful volume | 3-5 days |
| No proxy rotation | Blocked after ~100 requests/domain | Ongoing cost |
| Zero connector tests | No confidence in production | 2-3 days |
| No database running | Zero jobs stored | 1 hour |
| No deployment | Nothing is live | 1 day |

## Realistic Scale Targets

| Milestone | Jobs | Employers | Timeline |
|---|---|---|---|
| MVP Launch | 10,000 | 100-200 | Week 1-2 |
| Early Traction | 100,000 | 1,000-2,000 | Week 3-4 |
| Competitive | 1,000,000 | 5,000-10,000 | Month 2-3 |
| Scale | 10,000,000+ | 50,000+ | Month 6+ |

## Phase 1: Get to 10,000 Real Jobs (Week 1-2)

### Step 1: Greenhouse Board Discovery
- Greenhouse has ~10,000 public boards at predictable URLs
- Community lists exist on GitHub (5,000+ board tokens)
- Validate each by hitting `boards-api.greenhouse.io/v1/boards/{token}`
- **Expected: 5,000-8,000 valid employers → 200K-500K jobs**

### Step 2: Fix Rate Limiting
- Add `asyncio.Semaphore` in BaseConnector
- Per-domain throttling via Redis
- Respect `Retry-After` headers
- Max 2 requests/second/domain

### Step 3: Fix Error Handling
- Replace silent `except: pass` with logging
- Differentiate retryable (429, 503) from permanent (404) errors
- Circuit breaker: pause source after 5 consecutive failures

### Step 4: Run First Real Crawl
- Start PostgreSQL + Redis via Docker
- Run Alembic migration
- Seed discovered employers
- Start Celery workers
- **Target: 10K-50K jobs within 48 hours**

## Phase 2: Scale to 100K+ (Week 3-4)

### Step 5: Workday Instance Discovery
- Probe Fortune 2000 company names against `{company}.wd{1-5}.myworkdayjobs.com`
- DNS lookup + API validation
- **Expected: 1,000-2,000 employers → 500K-2M jobs**

### Step 6: Lever Board Discovery
- Similar pattern to Greenhouse
- Validate against `api.lever.co/v0/postings/{company}`

### Step 7: IndexNow Integration
- Ping Bing every time a new job is stored
- Batch submissions (up to 10K URLs per request)
- Reuse pattern from existing `duda-job-schema/job_schema.py`

### Step 8: Common Crawl Harvester
- Filter Common Crawl data for pages with `JobPosting` JSON-LD
- Extract and normalize without any crawling
- **Expected: 5M-10M jobs from existing web crawl data**

## Phase 3: AI Search Injection (Ongoing)

### Already Built:
- [x] MCP server with 5 tools
- [x] llms.txt endpoint
- [x] .well-known/llm-info
- [x] JobPosting JSON-LD on every page
- [x] sitemap.xml auto-generated
- [x] robots.txt allows AI crawlers

### Still Needed:
- [ ] Deploy to public URL (Railway/Fly.io)
- [ ] Submit sitemap to Google Search Console
- [ ] Submit sitemap to Bing Webmaster Tools
- [ ] Publish MCP server as pip package
- [ ] Build ChatGPT custom GPT action
- [ ] Apply to Anthropic MCP directory

## Cost Estimate

| Item | Monthly Cost |
|---|---|
| Railway (app + DB + Redis) | $25-60 |
| Proxy rotation (if needed) | $0-500 |
| Domain + SSL | $15/year |
| OpenCage geocoding | $0 (free tier) |
| **Total** | **$25-560/month** |

## Competitive Advantage

You won't beat Indeed on volume. You CAN beat them on:

1. **AI-native** — Indeed blocks AI crawlers. You serve them directly via MCP.
2. **Free for employers** — Indeed charges $5-15/click. You're $0.
3. **ATS transparency** — Workday/Taleo jobs are invisible everywhere. You surface them.
4. **Open API** — Anyone can query your index. Indeed locks data behind paywalls.

## Tech Stack

- **Backend:** Python 3.11+ / FastAPI / Celery / Redis
- **Database:** PostgreSQL
- **Crawling:** aiohttp (APIs) + Playwright (JS pages)
- **Search:** PostgreSQL full-text (upgrade to Meilisearch at scale)
- **AI:** MCP server + llms.txt + JobPosting JSON-LD
- **Frontend:** Jinja2 SSR (upgrade to Next.js at scale)
- **Deployment:** Docker → Railway
