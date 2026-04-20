# Global AI Job Board — Complete Job Source Plan

## The Global Job Landscape

There are approximately **40-60 million unique active job postings** worldwide at any time (~100-150M with duplication across boards). Here's where they all live and how we get them.

---

## TIER 1: ATS Public APIs (No Auth Required)

These ATS platforms expose public, unauthenticated APIs for job listings. This is the highest-quality, most reliable data source.

| ATS Platform | Market Position | API Endpoint | Est. Employers | Est. Jobs | Status |
|---|---|---|---|---|---|
| **Greenhouse** | Mid-market/tech, top 7 by revenue | `GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | ~10,000 | 500K-1M | ✅ Connector built, verified |
| **Lever** | ~2.9% market, tech mid-market | `GET api.lever.co/v0/postings/{company}?mode=json` | ~5,000 | 200K-400K | ✅ Connector built |
| **Ashby** | Fast-growing startups | `GET api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true` | ~2,000 | 50K-100K | ❌ Need connector |
| **Workable** | Mid-market, global | `GET workable.com/api/accounts/{subdomain}?details=true` | ~3,000 | 100K-200K | ❌ Need connector |
| **Recruitee** | SMB/mid-market, EU-strong | `GET {company}.recruitee.com/api/offers/` | ~2,000 | 30K-80K | ❌ Need connector |
| **Personio** | European SMB | `GET {company}.jobs.personio.de/xml?language=en` | ~5,000 | 100K-200K | ❌ Need connector |

**Subtotal: ~27,000 employers → 1M-2M jobs**

### Discovery method:
- Community-maintained GitHub lists of board tokens
- DNS/subdomain enumeration
- Career-site-grader ATS detection patterns (already built — detects 13 ATS platforms from any URL)

---

## TIER 2: ATS Reverse-Engineered APIs (No Auth, But Undocumented)

These ATS platforms have APIs that work but aren't officially documented. Higher risk of breaking.

| ATS Platform | Market Position | API Pattern | Est. Employers | Est. Jobs | Status |
|---|---|---|---|---|---|
| **Workday** | 37.1% of Fortune 500 (#1 enterprise) | `POST {co}.wd{1-5}.myworkdayjobs.com/wday/cxs/{co}/{site}/jobs` | ~3,000 | 2M-5M | ✅ Connector built |
| **SAP SuccessFactors** | 13.4% of Fortune 500 (#2 enterprise) | Hidden sitemap at `/sitemal.xml`, OData API | ~2,000 | 1M-3M | ❌ Need crawler |
| **iCIMS** | #1 ATS by revenue, 11% market | Portal search API (requires POST) | ~3,000 | 1M-2M | ❌ Need crawler |
| **Oracle Taleo** | Legacy enterprise | `{co}.taleo.net/careersection/{section}/jobsearch.ftl` | ~2,000 | 500K-1M | ❌ Need Playwright crawler |
| **BrassRing (IBM/Kenexa)** | Top 7 by revenue | No API — scraping only | ~1,000 | 200K-500K | ❌ Need Playwright crawler |
| **SmartRecruiters** | Top 7 (acquired by SAP 2025) | XML sitemap at `careers.smartrecruiters.com/{co}/sitemap.xml` | ~2,000 | 200K-500K | ❌ Need connector |

**Subtotal: ~13,000 employers → 5M-12M jobs**

### Discovery method:
- Fortune Global 2000 company list + DNS probing for Workday instances
- SAP SuccessFactors: probe for `/sitemal.xml` on known enterprise domains
- Taleo/BrassRing: detect via career-site-grader patterns, crawl with Playwright

---

## TIER 3: Free Job Aggregator APIs (API Key Required, Free Tier)

These are existing aggregators that have already done the hard work of collecting jobs. We can bootstrap our index from them while we build our own crawling capacity.

| Aggregator | Coverage | Free Tier | Est. Accessible Jobs | API Endpoint | Notes |
|---|---|---|---|---|---|
| **Adzuna** | 16 countries (US, UK, AU, DE, FR, IN, BR, CA, NL, ZA...) | 250 requests/day | 10M+ | `GET api.adzuna.com/v1/api/jobs/{country}/search/{page}` | Best free aggregator API. Salary data included. |
| **Jooble** | 71 countries | Free for publishers | 1M+ active | `POST jooble.org/api/{api_key}` | Requires partner application |
| **Careerjet** | 90+ countries, multilingual | Free for publishers | Millions | `GET search.api.careerjet.net/v4/query` | Revenue-share publisher model |
| **JSearch (RapidAPI)** | Global (LinkedIn, Indeed, Glassdoor, ZipRecruiter) | 500 req/month free | Millions | `GET jsearch.p.rapidapi.com/search` | $30/mo for 10K req. Best aggregated coverage. |
| **Reed.co.uk** | UK | Free API key | 250K | `GET reed.co.uk/api/1.0/search` | UK's #1 domestic board |
| **RemoteOK** | Global (remote only) | Free, no auth | 5K-10K | `GET remoteok.com/api` | Single JSON endpoint, tech-heavy |
| **Remotive** | Global (remote only) | Free, no auth | 1K-3K | `GET remotive.com/api/remote-jobs` | Curated remote jobs |
| **Arbeitnow** | Europe (DACH focus) | Free, no auth | 5K-15K | `GET arbeitnow.com/api/job-board-api` | Good for German market |
| **The Muse** | US | Free, no auth | 5K-10K | `GET themuse.com/api/public/jobs` | Culture-focused, curated |
| **USAJobs** | US federal government | Free API key | 30K | `GET data.usajobs.gov/api/search` | All US federal positions |
| **Canada Job Bank** | Canada government | Free | 100K | `jobbank.gc.ca/api` | Canadian public sector |

**Subtotal: 10M-20M+ accessible jobs (with duplication across aggregators)**

### Value of this tier:
- **Bootstrapping.** While we build ATS crawlers, aggregator APIs give us immediate volume.
- **Gap filling.** These aggregators already index SMB jobs from thousands of small company career pages we'd never discover on our own.
- **Global coverage.** Adzuna alone covers 16 countries.

---

## TIER 4: Common Crawl / Web Data Commons (Bulk Extraction)

Common Crawl publishes monthly web crawls of 3-5 billion pages. Web Data Commons extracts structured data from these crawls.

| Source | What It Contains | Est. JobPosting Pages | Access | Cost |
|---|---|---|---|---|
| **Common Crawl** | Raw HTML of 3-5B pages/month | 5-15M pages with JobPosting JSON-LD per crawl | AWS S3 (free data, pay for compute) | $100-500 per extraction |
| **Web Data Commons** | Pre-extracted schema.org data from Common Crawl | All JobPosting data already extracted | Free download | Free (1-5TB download) |

### How this works:
1. Download Web Data Commons structured data extract
2. Filter for `@type: JobPosting`
3. Parse employer, title, location, salary, description
4. Normalize into our canonical model
5. Deduplicate against jobs we've already crawled from ATS APIs

**Subtotal: 5M-15M unique job pages per monthly crawl (significant overlap with Tier 1-3)**

---

## TIER 5: Recruiter/Staffing Platforms

Staffing agencies collectively post millions of jobs. Most flow through their ATS to job boards, but some have direct APIs.

| Platform | Market | API Access | Est. Jobs | Notes |
|---|---|---|---|---|
| **Bullhorn** | #1 staffing ATS globally | Public REST API (read-only, needs cluster ID) | 500K-1M | 300+ integrations |
| **JobAdder** | AU/NZ/UK staffing | Partner API | 100K-200K | Combined ATS+CRM |
| **Vincere** | EU/UK/APAC staffing | Partner API | 50K-100K | Front-to-back office |
| **Loxo** | US mid-market | API available | 50K-100K | AI-powered sourcing |

**Subtotal: 500K-1.5M jobs (staffing/temp/contract heavy)**

---

## TIER 6: Playwright Headless Crawling (Catch-All)

For any career page without an API — custom sites, legacy ATS, SMB employers.

| Target | Method | Est. Jobs | Notes |
|---|---|---|---|
| Custom career pages | Crawl + extract job links from DOM | 5M-10M | Heuristic job detection (built) |
| Taleo career sites | Render JS + parse | 500K-1M | iframe-based, session URLs |
| iCIMS career sites | Render JS + parse | 500K-1M | JS-rendered search widgets |
| SuccessFactors career sites | Render JS + parse hidden sitemap | 1M-2M | Check `/sitemal.xml` first |
| BambooHR career pages | Render JS + parse | 100K-200K | Embedded career widgets |

**Subtotal: 7M-15M jobs (highest effort, lowest reliability)**

---

## TIER 7: Government & Public Sector

| Country | Source | Jobs | Access |
|---|---|---|---|
| USA | USAJobs API | 30K | Free API key |
| USA | State government portals | 200K+ | Crawling |
| UK | GOV.UK Civil Service Jobs | 10K | Crawling (API withdrawn) |
| Germany | Bundesagentur für Arbeit | 800K | Crawling |
| Canada | Job Bank | 100K | Free API |
| EU | EURES portal | 3M | Crawling |
| Australia | APS Jobs | 5K | Crawling |

**Subtotal: 4M+ public sector jobs**

---

## Total Addressable Job Universe

| Tier | Source Type | Est. Unique Jobs | Effort | Priority |
|---|---|---|---|---|
| 1 | ATS Public APIs | 1M-2M | Low | **P0 — Start here** |
| 2 | ATS Reverse-Engineered | 5M-12M | Medium | **P0 — Start here** |
| 3 | Free Aggregator APIs | 10M-20M | Low | **P1 — Quick volume** |
| 4 | Common Crawl extraction | 5M-15M | Medium | **P2 — Bulk backfill** |
| 5 | Staffing platforms | 500K-1.5M | Medium | P3 |
| 6 | Playwright crawling | 7M-15M | High | P3 |
| 7 | Government portals | 4M | Low-Medium | P2 |
| | **TOTAL (with dedup)** | **~20M-40M unique** | | |

**After deduplication across all tiers: realistically 20-40M unique active jobs globally.**
Indeed claims 300M+ but that includes massive duplication and historical postings.

---

## Implementation Phases

### Phase 1: First 100K jobs (Week 1-2)

| Action | Source | Expected Jobs |
|---|---|---|
| Discover Greenhouse boards (10K companies) | Tier 1 | 500K |
| Discover Workday instances (Fortune 2000) | Tier 2 | 500K |
| Connect Adzuna API (16 countries) | Tier 3 | 1M+ |
| Connect RemoteOK + Remotive + Arbeitnow | Tier 3 | 15K |
| Connect USAJobs API | Tier 7 | 30K |
| Fix rate limiting + error handling | Infrastructure | — |

### Phase 2: First 1M jobs (Week 3-6)

| Action | Source | Expected Jobs |
|---|---|---|
| Build Ashby + Workable + Recruitee connectors | Tier 1 | 200K |
| Build SmartRecruiters + Personio connectors | Tier 1-2 | 300K |
| Connect Jooble + Careerjet APIs | Tier 3 | 2M+ |
| Discover Lever boards | Tier 1 | 200K |
| Build SAP SuccessFactors sitemap crawler | Tier 2 | 500K |
| Connect JSearch API (paid $30/mo) | Tier 3 | 1M+ |
| Connect Reed.co.uk API | Tier 3 | 250K |

### Phase 3: 5M+ jobs (Month 2-3)

| Action | Source | Expected Jobs |
|---|---|---|
| Common Crawl / Web Data Commons harvester | Tier 4 | 5M-15M |
| Build Taleo Playwright crawler | Tier 2/6 | 500K |
| Build iCIMS crawler | Tier 2/6 | 500K |
| Connect Bullhorn public API | Tier 5 | 500K |
| German Bundesagentur crawl | Tier 7 | 800K |
| EURES portal crawl | Tier 7 | 3M |
| Canada Job Bank API | Tier 7 | 100K |

### Phase 4: 10M+ jobs (Month 4-6)

| Action | Source | Expected Jobs |
|---|---|---|
| Scale Playwright crawling to custom career pages | Tier 6 | 5M+ |
| BrassRing/IBM crawling | Tier 2/6 | 200K |
| BambooHR career page crawling | Tier 6 | 100K |
| JazzHR, Breezy, Zoho Recruit crawling | Tier 6 | 200K |
| State government portals (US, UK, AU) | Tier 7 | 200K |
| Expand to regional job boards (Naukri, SEEK, StepStone) via crawling | Tier 6 | 2M+ |

---

## How Indeed Does It (For Reference)

1. **Employers post directly** (free basic, paid sponsored) — their primary revenue
2. **Web scraping** — aggressively crawl company career pages (controversial, lawsuits)
3. **XML feeds** — partners submit Indeed-format XML feeds
4. **ATS integrations** — 200+ ATS platforms push jobs to Indeed
5. **Publisher program** — job boards send jobs to Indeed in exchange for traffic

**We skip #1 (employer posting) and #4 (ATS partnerships) initially.** We do #2 (crawling), #3 (feeds/APIs), and add what Indeed doesn't: AI-native access via MCP server.

---

## How Google for Jobs Does It

1. **Crawls the web** for pages with `JobPosting` JSON-LD structured data
2. **Indexes job postings** from schema.org markup — this is why JSON-LD on every page matters
3. **Deduplicates** — same job from multiple sources shown as one listing with multiple "Apply" links
4. **Google Indexing API** — publishers can notify Google instantly when jobs are added/removed
5. **No API for retrieval** — Google for Jobs is a search feature, not a data source

**Our advantage:** Every job page we create has JobPosting JSON-LD + we use the Indexing API + IndexNow. We're building exactly what Google wants to index.

---

## Connectors Needed (Prioritized Build Order)

### Already Built:
1. ✅ Greenhouse (`src/connectors/greenhouse.py`)
2. ✅ Lever (`src/connectors/lever.py`)
3. ✅ Workday (`src/connectors/workday.py`)
4. ✅ Playwright generic crawler (`src/crawler/playwright_crawler.py`)

### Phase 1 (Week 1-2):
5. Adzuna aggregator API connector
6. RemoteOK API connector
7. USAJobs API connector
8. Greenhouse board discovery script
9. Workday instance discovery script

### Phase 2 (Week 3-6):
10. Ashby API connector
11. Workable API connector
12. Recruitee API connector
13. Personio XML connector
14. SmartRecruiters sitemap connector
15. Jooble API connector
16. Careerjet API connector
17. Reed.co.uk API connector

### Phase 3 (Month 2-3):
18. Common Crawl / Web Data Commons harvester
19. Taleo Playwright parser
20. iCIMS Playwright parser
21. SAP SuccessFactors sitemap parser
22. Bullhorn public API connector
23. Canada Job Bank API connector

---

## Cost Estimate (Revised)

| Item | Monthly Cost | What It Gets You |
|---|---|---|
| Railway (app + DB + Redis) | $25-60 | Hosting + PostgreSQL + task queue |
| JSearch API (RapidAPI) | $30 | 10K req/month, millions of aggregated jobs |
| Proxy rotation (Phase 3+) | $200-500 | Required for Playwright crawling at scale |
| Common Crawl processing (one-time) | $100-500 | 5-15M jobs from existing data |
| Domain + SSL | $1.25/mo | jobindex.ai |
| **Total Month 1-2** | **$55-90/mo** | |
| **Total Month 3+** | **$255-1,090/mo** | |

---

## What We're NOT Doing (And Why)

| What | Why Not |
|---|---|
| Indeed XML feed partnership | Requires commercial agreement, they charge |
| LinkedIn API | Requires Talent Solutions partnership ($$$) |
| SEEK API | Partner/advertiser only |
| Building our own web crawler from scratch | Common Crawl already does this monthly for free |
| Competing on employer posting features | We're an index, not a job board — employers don't need to do anything |
