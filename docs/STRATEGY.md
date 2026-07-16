# JobIndex — Global AI Job Index Strategy

> Working title. Product name TBD.

---

## 1. The Problem

### 1.1 Corporate Jobs Are Invisible to AI

When someone asks ChatGPT, Claude, Perplexity, or Google's AI Overview "show me software engineer jobs at Microsoft," the answer is incomplete or wrong. This is because **the majority of corporate job postings are trapped inside Applicant Tracking Systems (ATS) that are invisible to AI crawlers.**

The numbers tell the story:

- **Workday** powers 37% of Fortune 500 career sites. Its career pages are client-side JavaScript applications that return blank HTML to crawlers.
- **SAP SuccessFactors** powers 13% of Fortune 500. Same problem — behind authentication walls with minimal structured data.
- **Oracle Taleo** uses iframe-based rendering with session-dependent URLs that break when crawled.
- **iCIMS**, the #1 ATS by revenue, renders job listings dynamically with no static HTML.

**Result:** An estimated 60-70% of enterprise job postings — positions at the world's largest employers — are effectively invisible to AI search, traditional search engines (without special handling), and job aggregators that rely on structured data.

### 1.2 Indeed's Model Is Broken for Employers

Indeed built a $4B+/year business by scraping company career pages and charging employers $5-15 per click to access the candidates that Indeed redirected away from the employer's own site. Employers are paying to reach candidates who were looking for them anyway.

- Indeed charges per click, not per hire. Employers pay regardless of candidate quality.
- Indeed actively blocks AI crawlers (GPTBot, ClaudeBot) — it doesn't want AI assistants answering job search queries because that bypasses Indeed's ad model.
- Employers have no control over how their listings appear on Indeed.

### 1.3 The AI Search Shift

Job search is moving from "go to a job board and browse" to "ask an AI assistant to find me relevant jobs." This shift will be as significant as the move from newspaper classifieds to online job boards in the 2000s.

- **61 million people** use LinkedIn to search for jobs weekly.
- **ChatGPT has 300M+ weekly active users** — a growing number use it for job search queries.
- **Google AI Overviews** now appear for job-related queries, pulling from structured data.
- **Perplexity** and other AI search engines are growing rapidly, and they need structured job data to answer queries.

The opportunity: **become the data layer that powers AI job search globally.**

---

## 2. The Solution

### 2.1 What JobIndex Does

JobIndex is a **global, AI-native job index** that:

1. **Ingests every job** from every corporate ATS platform, job board, government portal, and career page — automatically, without employer action.
2. **Normalizes** all job data into a canonical format with structured fields (title, employer, location, salary, seniority, remote status, categories).
3. **Republishes** every job in formats that AI search engines and traditional search can consume — server-rendered HTML with JobPosting JSON-LD, MCP server for AI assistants, open REST API.
4. **Free for employers.** Jobs are indexed automatically. Employers don't pay to be found.

### 2.2 How It's Different

| | Indeed | LinkedIn | Google for Jobs | **JobIndex** |
|---|---|---|---|---|
| **Cost to employers** | $5-15/click | $1.20-1.50/click | Free (but limited) | **Free** |
| **AI assistant access** | ❌ Blocks AI crawlers | ❌ No public API | ❌ No retrieval API | **✅ MCP server + API** |
| **ATS coverage** | Scrapes + partnerships | Employer-posted only | Schema.org only | **All ATS platforms** |
| **Structured data** | Proprietary, locked | Proprietary, locked | Aggregates existing | **Open, queryable** |
| **Enterprise jobs (Workday/SAP)** | Partial | Partial | Often missing | **Primary focus** |

---

## 3. Where Every Job Comes From

### 3.1 The Global Job Landscape

There are approximately **40-60 million unique active job postings** at any time worldwide (~100-150M counting duplication across platforms). They're spread across hundreds of ATS platforms, thousands of job boards, and millions of company career pages.

Here is every source, categorized by access method and priority.

---

### 3.2 Source Category A: ATS Platforms with Public APIs

These ATS platforms expose free, unauthenticated APIs for their clients' job listings. This is the highest-quality data — direct from the employer's ATS, structured, and reliable.

#### Greenhouse
- **Market:** Mid-market and tech companies. Top 7 ATS by revenue.
- **Companies using it:** Airbnb, Stripe, Figma, Notion, Discord, Spotify, Canva, Cloudflare, Coinbase, MongoDB, Atlassian, and ~10,000 others.
- **API:** `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- **Auth:** None. Fully public.
- **Data quality:** Excellent. Returns title, full HTML description, location, departments, metadata.
- **Discovery:** Board tokens are company URL slugs. Community lists on GitHub have 5,000+. Validate by hitting the API.
- **Estimated yield:** 500K-1M active jobs across ~10,000 employers.
- **Our status:** ✅ Connector built and verified (239 Airbnb jobs pulled live).

#### Lever
- **Market:** ~3% market share. Tech mid-market (Netflix, GitHub, GitLab, Shopify).
- **API:** `GET https://api.lever.co/v0/postings/{company}?mode=json`
- **Auth:** None. Public.
- **Data quality:** Good. Includes salary ranges, department, team, commitment level, location.
- **Discovery:** Board tokens are company slugs at `jobs.lever.co/{company}`.
- **Estimated yield:** 200K-400K active jobs across ~5,000 employers.
- **Our status:** ✅ Connector built.

#### Ashby
- **Market:** Fast-growing, popular with startups and scaleups.
- **API:** `GET https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true`
- **Auth:** None. Public.
- **Data quality:** Best compensation data of any ATS API.
- **Estimated yield:** 50K-100K active jobs across ~2,000 employers.
- **Our status:** ❌ Connector needed.

#### Workable
- **Market:** Mid-market, global presence.
- **API:** `GET https://www.workable.com/api/accounts/{subdomain}?details=true`
- **Auth:** None. Public.
- **Data quality:** Good. Also has `/locations` and `/departments` endpoints.
- **Estimated yield:** 100K-200K active jobs across ~3,000 employers.
- **Our status:** ❌ Connector needed.

#### Recruitee
- **Market:** SMB to mid-market, strong in Europe.
- **API:** `GET https://{company}.recruitee.com/api/offers/`
- **Auth:** None. Public.
- **Data quality:** Department and tag filtering supported.
- **Estimated yield:** 30K-80K active jobs across ~2,000 employers.
- **Our status:** ❌ Connector needed.

#### Personio
- **Market:** European SMB HR platform, strong in DACH region.
- **API:** `GET https://{company}.jobs.personio.de/xml?language=en`
- **Auth:** None. Public XML feed.
- **Data quality:** Standard job fields in XML format.
- **Estimated yield:** 100K-200K active jobs across ~5,000 employers.
- **Our status:** ❌ Connector needed.

**Category A Total: ~27,000 employers → 1M-2M active jobs**

---

### 3.3 Source Category B: Enterprise ATS Platforms (Reverse-Engineered Access)

These are the largest ATS platforms in the world. They don't publish official APIs, but their career sites expose JSON endpoints that can be accessed programmatically. This is where the Fortune 500 jobs live.

#### Workday
- **Market:** #1 enterprise ATS. 37.1% of Fortune 500.
- **Companies:** Microsoft, Amazon, Google, Salesforce, Adobe, Cisco, Oracle, JPMorgan, Goldman Sachs, Deloitte, and ~3,000 others.
- **API:** `POST https://{company}.wd{1-5}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs`
- **Auth:** None, but requires a POST with specific JSON body (`appliedFacets`, `limit`, `offset`, `searchText`).
- **Data quality:** Full descriptions, location, time type, remote type, posting dates.
- **Risk:** Undocumented API — Workday could change it without warning.
- **Discovery:** DNS probe company names against all 5 instance variants (`wd1` through `wd5`). Start with Fortune Global 2000.
- **Estimated yield:** 2M-5M active jobs across ~3,000 employers.
- **Our status:** ✅ Connector built. 10 Fortune 500 companies seeded.

#### SAP SuccessFactors
- **Market:** #2 enterprise ATS. 13.4% of Fortune 500.
- **Companies:** Major enterprise employers globally.
- **Access:** Hidden XML sitemap at `/sitemal.xml` on career sites. OData API exists but requires auth.
- **Data quality:** Variable. Sitemap gives job URLs; details must be crawled.
- **Discovery:** Probe known enterprise domains for the hidden sitemap path.
- **Estimated yield:** 1M-3M active jobs across ~2,000 employers.
- **Our status:** ❌ Crawler needed.

#### iCIMS
- **Market:** #1 ATS by revenue globally. 11% market share.
- **Companies:** Major enterprise and mid-market employers.
- **Access:** Portal search API requires POST. Standard XML feed (3x daily) available to approved partners only (OAuth 2.0).
- **Data quality:** Good if you can access it.
- **Discovery:** Detect via HTML patterns, then crawl with Playwright.
- **Estimated yield:** 1M-2M active jobs across ~3,000 employers.
- **Our status:** ❌ Crawler needed.

#### Oracle Taleo
- **Market:** Legacy enterprise. Still widely used.
- **Companies:** Large traditional enterprises.
- **Access:** `{company}.taleo.net/careersection/{section}/jobsearch.ftl` — no public API. iframe-based, session URLs.
- **Data quality:** Poor without rendering. Requires Playwright.
- **Estimated yield:** 500K-1M active jobs across ~2,000 employers.
- **Our status:** ❌ Playwright crawler needed.

#### SmartRecruiters
- **Market:** Top 7 by revenue. Acquired by SAP in 2025.
- **Access:** XML sitemap at `careers.smartrecruiters.com/{company}/sitemap.xml`. Posting API exists but requires marketplace access.
- **Estimated yield:** 200K-500K active jobs across ~2,000 employers.
- **Our status:** ❌ Sitemap connector needed.

#### BrassRing (IBM/Kenexa)
- **Market:** Top 7 by revenue. Legacy enterprise.
- **Access:** No API whatsoever. Scraping only.
- **Estimated yield:** 200K-500K active jobs across ~1,000 employers.
- **Our status:** ❌ Playwright crawler needed.

**Category B Total: ~13,000 employers → 5M-12M active jobs**

---

### 3.4 Source Category C: Job Aggregator APIs

These services have already aggregated jobs from thousands of sources. We can use their APIs to bootstrap our index with massive volume immediately while building our own ATS crawlers.

#### Adzuna
- **Coverage:** 16 countries (US, UK, AU, DE, FR, IN, BR, CA, NL, PL, ZA, SG, AT, CH, NZ and more).
- **API:** `GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}`
- **Free tier:** 250 requests/day. Returns title, description, company, salary, location, category.
- **Volume:** 10M+ active jobs.
- **Why it matters:** Single API, 16 countries, salary data included. Best free aggregator.

#### Jooble
- **Coverage:** 71 countries.
- **API:** `POST https://jooble.org/api/{api_key}`
- **Free tier:** Free for publishers (application required).
- **Volume:** Millions active across 71 countries.
- **Why it matters:** Broadest country coverage of any free API.

#### Careerjet
- **Coverage:** 90+ countries, multilingual.
- **API:** `GET https://search.api.careerjet.net/v4/query`
- **Free tier:** Free for publishers (registration required).
- **Volume:** Millions. JSON and XML output.
- **Why it matters:** 90 countries with multilingual support.

#### JSearch (RapidAPI)
- **Coverage:** Global. Aggregates from LinkedIn, Indeed, Glassdoor, ZipRecruiter.
- **API:** `GET https://jsearch.p.rapidapi.com/search`
- **Free tier:** 500 requests/month. Paid: $30/mo for 10K requests.
- **Volume:** Millions. Rich data — qualifications, salary range, apply links.
- **Why it matters:** Only API that aggregates LinkedIn and Indeed jobs.

#### Reed.co.uk
- **Coverage:** UK's #1 domestic job board.
- **API:** `GET https://www.reed.co.uk/api/1.0/search`
- **Free tier:** Free API key on registration.
- **Volume:** 250K active UK jobs.

#### Free Open APIs (No Auth)
- **RemoteOK:** `GET https://remoteok.com/api` — 5K-10K remote tech jobs. Fully open.
- **Remotive:** `GET https://remotive.com/api/remote-jobs` — 1K-3K curated remote jobs.
- **Arbeitnow:** `GET https://arbeitnow.com/api/job-board-api` — 5K-15K European jobs.
- **The Muse:** `GET https://themuse.com/api/public/jobs` — 5K-10K US jobs with company culture data.

**Category C Total: 10M-20M+ accessible jobs (with cross-source duplication)**

---

### 3.5 Source Category D: Common Crawl & Structured Data Extraction

Common Crawl is a nonprofit that crawls 3-5 billion web pages monthly and publishes all data for free. Web Data Commons extracts structured data (including JobPosting JSON-LD) from these crawls.

- **Source:** `commoncrawl.org` (raw data) + `webdatacommons.org` (pre-extracted structured data)
- **JobPosting pages per crawl:** 5-15 million pages containing schema.org JobPosting markup.
- **Access:** Free. Data on AWS S3. Can query with AWS Athena ($5-20 per scan) or download Web Data Commons extractions directly.
- **Data quality:** Variable — includes expired listings, template pages. Requires heavy dedup.
- **Cost:** $100-500 for a targeted extraction from one month's crawl.

**Why this matters:** This is how you get millions of jobs from thousands of small company career pages that you'd never discover through ATS discovery. Google for Jobs indexes the same data — any page with JobPosting JSON-LD.

**Category D Total: 5M-15M job pages per crawl (significant overlap with Categories A-C)**

---

### 3.6 Source Category E: Government & Public Sector

Governments collectively employ millions. Some publish job data through APIs.

| Country | Source | Access | Volume |
|---|---|---|---|
| **USA** | USAJobs API | Free API key at `developer.usajobs.gov` | 30K federal jobs |
| **USA** | State government portals | Crawling (50 state sites) | 200K+ |
| **Canada** | Job Bank API | Free at `jobbank.gc.ca/api` | 100K |
| **Germany** | Bundesagentur für Arbeit | Crawling | 800K (largest single-country source) |
| **EU** | EURES portal | Crawling (30+ countries) | 3M cross-border jobs |
| **UK** | Civil Service Jobs | Crawling (API withdrawn) | 10K |
| **Australia** | APS Jobs | Crawling | 5K |

**Category E Total: ~4M public sector jobs**

---

### 3.7 Source Category F: Staffing & Recruitment Agencies

Staffing agencies collectively place millions of workers. Their jobs are heavily temp/contract but represent significant volume.

| Platform | Market | API | Volume |
|---|---|---|---|
| **Bullhorn** | #1 staffing ATS globally | Public REST API (read-only) | 500K-1M |
| **JobAdder** | AU/NZ/UK | Partner API | 100K-200K |
| **Vincere** | EU/UK/APAC | Partner API | 50K-100K |
| **Loxo** | US mid-market | API available | 50K-100K |

**Category F Total: 500K-1.5M jobs (temp/contract/staffing heavy)**

---

### 3.8 Source Category G: Direct Employer Submission

After we have volume and visibility, employers will want to submit jobs directly for better control over their listings.

- **Self-service API:** Employers push jobs via REST API or webhook from their ATS.
- **Feed submission:** Accept Indeed XML format, HRXML, or simple JSON.
- **Claimed profiles:** Employers verify domain ownership and manage their company profile.
- **This becomes Phase 2 (Employer Portal) — not launch priority.**

---

### 3.9 Total Addressable Job Universe

| Category | Source Type | Unique Jobs | Priority |
|---|---|---|---|
| A | ATS Public APIs | 1M-2M | **P0 — Week 1** |
| B | Enterprise ATS (reverse-engineered) | 5M-12M | **P0 — Week 1-2** |
| C | Aggregator APIs | 10M-20M | **P0 — Week 1** |
| D | Common Crawl extraction | 5M-15M | P1 — Month 2 |
| E | Government portals | 4M | P1 — Month 2 |
| F | Staffing platforms | 500K-1.5M | P2 — Month 3 |
| G | Direct employer submission | Grows over time | P3 — Month 4+ |
| | **Total after deduplication** | **~20M-40M unique** | |

---

## 4. How We Lead AI Job Search

### 4.1 The AI Distribution Strategy

Having the jobs is only half the battle. The other half is making them **findable by AI systems.** Here's how every AI search channel works and how we plug into each.

#### Channel 1: Google for Jobs + Google AI Overviews

**How it works:** Google crawls the web for pages with `JobPosting` JSON-LD structured data. It deduplicates and shows results in a dedicated job search widget and in AI Overviews.

**Our approach:**
- Every job in our index gets its own server-rendered HTML page at `/jobs/{uuid}`.
- Every page includes complete `JobPosting` JSON-LD schema (title, employer, location, salary, employment type, description, application URL).
- Auto-generated `sitemap-jobs.xml` lists all active jobs — submitted to Google Search Console.
- **Google Indexing API** notifies Google within minutes when a new job is added or removed. Google explicitly supports this for job posting pages.
- **IndexNow** notifies Bing simultaneously.

**Why we win:** Most ATS career sites (Workday, Taleo, iCIMS) produce NO structured data. We take the same jobs and republish them with proper schema.org markup. Google will prefer our structured pages over the original JS-rendered ATS pages.

**Built:** ✅ JSON-LD generation, sitemap.xml, server-rendered pages.
**Needed:** IndexNow integration, Google Indexing API integration, deployment to public URL.

#### Channel 2: Claude (Anthropic) via MCP

**How it works:** Claude supports the Model Context Protocol (MCP). MCP servers expose tools that Claude can call directly — no web scraping needed.

**Our approach:**
- MCP server with 5 tools: `search_jobs`, `find_jobs` (natural language), `get_job_details`, `get_index_stats`, `list_employers`.
- Natural language query parser converts "remote Python jobs paying over 100K in Europe" into structured filters.
- Publish as a pip package (`pip install jobindex-mcp`) and apply to Anthropic's MCP directory.
- Claude Desktop users add the server to their config and can ask Claude about any job in our index.

**Why we win:** No other job data source offers an MCP server. Indeed actively blocks Claude's web crawler. We're the only structured job data that Claude can access natively.

**Built:** ✅ MCP server with 5 tools, NL parser.
**Needed:** pip packaging, Anthropic directory submission.

#### Channel 3: ChatGPT via GPT Actions

**How it works:** OpenAI allows custom GPTs to call external APIs via "Actions." A custom GPT can be published to the GPT Store where millions of ChatGPT users can find it.

**Our approach:**
- Create a custom GPT ("JobIndex — Global Job Search") that calls our REST API.
- OpenAPI spec is already auto-generated by FastAPI at `/openapi.json`.
- The GPT uses natural language to call `/api/v1/jobs/search` with appropriate filters.
- Publish to GPT Store for organic discovery.

**Why we win:** ChatGPT's built-in web browsing is unreliable for job search (can't render JS career pages). A dedicated GPT Action with structured API access is far more reliable.

**Built:** ✅ REST API with OpenAPI spec.
**Needed:** GPT Action configuration, GPT Store submission.

#### Channel 4: Perplexity, You.com, and AI Search Engines

**How it works:** These AI search engines crawl the web like Google but generate AI-powered answers. They look for structured data, `llms.txt`, and well-structured HTML.

**Our approach:**
- `llms.txt` at root domain describes our index, API endpoints, and capabilities.
- `/.well-known/llm-info` provides structured metadata in JSON.
- Server-rendered HTML pages (not JavaScript SPAs) are directly crawlable.
- `robots.txt` explicitly allows AI crawlers (GPTBot, ClaudeBot, PerplexityBot).

**Why we win:** Indeed.com blocks these crawlers. LinkedIn requires auth. Our pages are open, structured, and designed for AI consumption.

**Built:** ✅ llms.txt, llm-info, SSR pages, robots.txt.
**Needed:** Deployment to public URL.

#### Channel 5: Open API for Developers

**How it works:** Developers, startups, and other AI products need job data. There is no comprehensive, free job search API today. Indeed deprecated theirs. LinkedIn requires enterprise partnership.

**Our approach:**
- Free public REST API at `/api/v1/jobs/search` with 14 filter parameters.
- Rate-limited free tier (1,000 requests/day).
- Paid tier for higher volume.
- This becomes a platform — other products build on our data.

**Why we win:** We're the only free, comprehensive job search API. Every developer who builds a job-related AI feature is a potential consumer.

**Built:** ✅ REST API with search, employers, stats.
**Needed:** Rate limiting, API key management, developer docs.

#### Channel 6: Embeddable Widgets

**How it works:** Employers, career coaches, staffing agencies, and content sites want to show relevant jobs on their websites.

**Our approach:**
- JavaScript widget: `<script src="jobindex.ai/widget.js" data-query="python remote" data-country="US"></script>`
- Calls our API, renders job cards on any website.
- Each click-through links to our job detail page (SEO value) or directly to employer's apply page.

**Not built yet.** Phase 2 priority.

---

### 4.2 The Flywheel

```
More jobs indexed
     ↓
More pages with JobPosting JSON-LD
     ↓
Google/Bing/AI crawlers index more of our pages
     ↓
More people find jobs through AI search → our site
     ↓
More employers discover they're indexed (free)
     ↓
Some employers claim profiles, upgrade to paid features
     ↓
Revenue funds more crawling capacity
     ↓
More jobs indexed
```

---

## 5. Competitive Positioning

### 5.1 Why Not Just Use Indeed?

Indeed's model has three structural weaknesses:

1. **Anti-AI:** Indeed blocks AI crawlers. As search shifts to AI assistants, Indeed becomes less discoverable. We do the opposite — we're built for AI.
2. **Anti-employer:** Indeed charges employers $5-15/click to reach candidates who were searching for them anyway. We're free.
3. **Incomplete:** Indeed doesn't index all ATS platforms. Workday, Taleo, and SuccessFactors career sites are inconsistently indexed. We go direct to every ATS.

### 5.2 Why Not Just Use Google for Jobs?

Google for Jobs only indexes pages that already have JobPosting JSON-LD. The problem is:
- Most enterprise career sites (Workday, Taleo, iCIMS) don't produce JSON-LD.
- Google for Jobs is a search feature, not a data source — no API, no MCP, no embeddable widgets.
- We take unstructured career pages, add the structured data Google needs, and publish it. **We're a supply chain for Google for Jobs, not a competitor.**

### 5.3 Why Not Just Use LinkedIn?

LinkedIn has 1B+ members and 15-20M active jobs. But:
- LinkedIn jobs are behind authentication. AI crawlers can't access them.
- No public API. Enterprise partnership costs six figures.
- LinkedIn is a social network with a job board feature. We're infrastructure for the job data itself.

### 5.4 Our Unique Position

We're not a job board. We're not a social network. We're **job data infrastructure.**

| Layer | Indeed | LinkedIn | Google | **JobIndex** |
|---|---|---|---|---|
| Job data source | Scraping + posting | Employer posting | Crawling JSON-LD | **All ATS APIs + crawling + aggregators** |
| AI access | ❌ Blocked | ❌ Requires auth | ❌ No API | **✅ MCP + API + llms.txt** |
| Employer cost | $5-15/click | $1.20-1.50/click | Free | **Free** |
| Structured data | Proprietary | Proprietary | Depends on source | **Open, standardized** |
| Developer API | Deprecated | Partner only ($$$) | None | **Free public API** |

---

## 6. Commercial Access & Entitlement Model

ZammeJobs must support different access and profile entitlements for Shazamme clients and non-clients.

**Clean commercial position:** Every recruitment company can be discovered. Shazamme clients get the full profile included. Everyone else pays to claim, enhance and manage theirs. This gives ZammeJobs broad coverage without giving away the valuable part.

### 6.1 Core Commercial Rules

- All eligible recruitment agencies may have a **basic public company page** on ZammeJobs.
- A basic public company page may be created **automatically** from public information, live job feeds and existing ZammeJobs data.
- Recruitment agencies **do not need to be paying customers** to appear on ZammeJobs.
- **Shazamme clients** receive access to the upgraded ZammeJobs profile and platform features **at no additional charge** while they remain an active Shazamme client.
- **Non-Shazamme clients** must register and pay to claim, manage or upgrade their profile.
- Payment **must not influence** factual rankings, hiring activity data, editorial comparisons or inclusion in objective lists.
- Paid profiles may contain more complete information and additional promotional features, but must **not** be falsely presented as more credible purely because they are paid.
- Sponsored placements must **always be clearly labelled**.

### 6.2 Basic Public Recruitment Agency Page

Create a free basic page for recruitment agencies where sufficient verified or public data exists.

The basic page may include: company name, company logo (where legally permitted), company website, company type, basic company description, main sectors, main locations, current live jobs, job count, link to the company website, link to current vacancies, date last updated, profile status, and a claim/upgrade profile button.

- Basic pages may be **unclaimed**.
- Basic pages must clearly distinguish between: **platform-generated**, **publicly sourced**, **company-supplied**, and **verified** information.
- The existence of a basic profile must **not imply** that the company is a ZammeJobs or Shazamme customer.

### 6.3 Shazamme Client Access

Active Shazamme clients should receive upgraded ZammeJobs access without paying a separate ZammeJobs subscription.

Create an **entitlement system** to identify an active Shazamme client. Possible entitlement sources: existing Shazamme account relationship, shared customer identifier, CRM/billing integration, admin-assigned entitlement, approved company domain, or an API/webhook from the Shazamme platform. **Do not rely only on an email domain** where a stronger customer identifier is available.

An active Shazamme client entitlement should unlock: profile claiming, verified profile workflow, full company profile management, multiple company administrators, expanded sectors & specialisms, office locations, consultant profiles, leadership profiles, awards, accreditations, case studies, salary guides, market reports, videos & transcripts, FAQs, additional contact options, enhanced branding, profile completeness tools, profile analytics, job referral analytics, website referral analytics, priority data refresh, profile verification, and access to future standard upgrade features.

The account should display **"Included with your active Shazamme subscription."** Do **not** show a separate ZammeJobs charge to eligible Shazamme clients.

### 6.4 Non-Client Registration & Payment

Non-Shazamme clients may **view** public ZammeJobs content without paying. They must register and purchase an upgrade to: claim/edit/manage a company profile, add enhanced company information, access profile analytics, add consultant profiles, case studies, salary guides, reports, videos and FAQs, receive verification, and access enhanced promotional features.

**Registration & upgrade journey:**
1. User selects "Claim this profile" or "Upgrade this profile."
2. User creates an account.
3. User verifies their email address.
4. User declares their relationship with the company.
5. User submits company verification information.
6. The platform **checks whether the company is an active Shazamme client**.
7. If an active Shazamme client → upgrade granted at **no additional charge**.
8. If not a Shazamme client → user is shown the available paid plans.
9. Payment is completed.
10. The claim enters **moderation**.
11. Once approved, the user receives company management access.

**Do not require payment before checking whether the company is entitled to free Shazamme client access.**

### 6.5 Profile Tiers

**Basic public profile** — available to all eligible recruitment agencies. Public company page, basic details, current live jobs, main sectors, main locations, company website link, claim option. May be generated and maintained by ZammeJobs.

**Upgraded profile** — included free for active Shazamme clients; available as a paid subscription for non-clients. Claimed + verified profile, full editing, expanded overview, additional sectors/specialisms, multiple office locations, consultant/leadership profiles, awards & accreditations, case studies, salary guides, reports, videos, FAQs, enhanced branding, analytics, referral reporting, more frequent updates, profile completeness recommendations.

**Premium visibility package** — optional paid add-on for both Shazamme clients and non-clients. Sponsored placement, featured company positions, sponsored editorial, newsletter inclusion, campaign promotion, enhanced market report participation, additional content production, advanced visibility reporting. Premium visibility features must be **clearly labelled where they affect placement** and must **not alter factual rankings or objective market data**.

### 6.6 Entitlement Data Model

Add or reuse data structures for: `Account`, `Company`, `CompanyMembership`, `CompanyClaim`, `Subscription`, `SubscriptionPlan`, `CustomerEntitlement`, `EntitlementSource`, `BillingCustomer`, `BillingSubscription`, `FeatureAccess`, `SponsoredPlacement`.

Suggested `CustomerEntitlement` fields: `company_id`, `entitlement_type`, `source`, `external_customer_id`, `starts_at`, `expires_at`, `status`, `last_verified_at`, `created_by`, `notes`.

- **Entitlement types:** `basic_public_profile`, `shazamme_client_upgrade`, `paid_zammejobs_upgrade`, `premium_visibility`, `admin_granted`, `trial`.
- **Entitlement statuses:** `active`, `pending`, `expired`, `cancelled`, `suspended`, `grace_period`.

### 6.7 Shazamme Client Status Changes

**When a company becomes a Shazamme client:** detect/receive the updated status, activate the free upgraded entitlement, remove the need for a separate ZammeJobs subscription, preserve existing profile content, prevent duplicate billing, notify the administrator.

**When a company stops being a Shazamme client:** do **not** immediately delete profile/content; apply a **configurable grace period** (default **30 days** after the entitlement expires); notify administrators; offer conversion to a paid ZammeJobs subscription; preserve the public basic profile; restrict upgraded management features after the grace period; preserve data so it can be restored if the company re-subscribes.

### 6.8 Billing Safeguards

Prevent: a Shazamme client being charged for an included upgraded profile; duplicate subscriptions for the same company; multiple users purchasing separate plans for the same profile; access continuing indefinitely after failed payment; profile deletion immediately after cancellation; payment changing factual rankings; paid users editing system-generated statistics.

Before creating a paid subscription, **check**: existing Shazamme client entitlement, existing company subscription, pending company claim, existing company administrator, existing billing customer record.

### 6.9 Public Labels

Use clear labels: `Unclaimed profile`, `Claimed profile`, `Verified information`, `Information supplied by the company`, `Sponsored`, `Featured`, `ZammeJobs data`, `Last updated`, `Last verified`.

Do **not** display "Trusted company", "Recommended company", "Best company", or "Top agency" unless supported by a **published, objective methodology**. Do not publicly label companies as paying or non-paying unless required for a sponsored disclosure.

### 6.10 Admin Controls

Administrators must be able to: mark a company as an active Shazamme client; connect a company to an external Shazamme customer ID; grant/revoke an included upgrade; apply a grace period; convert an included entitlement to a paid subscription; resolve duplicate subscriptions; merge duplicate company profiles; view entitlement history; view billing status; grant temporary access; suspend access; preserve the public basic profile; override access in exceptional cases (recording the reason). **All entitlement and billing changes must be recorded in the audit log.**

### 6.11 UI Requirements

- **Unclaimed basic profile:** "Is this your company?" · "Claim and upgrade this profile" · "Shazamme clients receive upgraded access at no additional cost".
- **Logged-in Shazamme client:** "Your upgraded ZammeJobs profile is included with Shazamme" · "Complete your profile" · "Verify your company information".
- **Logged-in non-client:** current plan, upgrade options, included features, billing status, renewal date, cancellation controls.
- **Never block** public users from viewing jobs or basic company pages.

### 6.12 Acceptance Criteria

The commercial access system is complete when:
- Eligible recruitment agencies can have a basic public page.
- A company can appear without being a customer.
- A company representative can attempt to claim a profile.
- The platform checks Shazamme client status **before** requesting payment.
- Active Shazamme clients receive upgraded access for free.
- Non-clients can purchase upgraded access.
- A company cannot be charged twice.
- Multiple users can be assigned to an upgraded company profile.
- Paid status does not change factual rankings.
- Sponsored placements are labelled.
- A cancelled or expired company retains its basic public page.
- A former Shazamme client can convert to a paid ZammeJobs plan.
- Entitlement changes are audited.
- Billing and access rules are covered by automated tests.

---

## 7. Technical Architecture Summary

```
┌─────────────────────────────────────────────────────┐
│                 DATA INGESTION                       │
├─────────┬─────────┬──────────┬──────────┬───────────┤
│  ATS    │ Enterprise│ Aggregator│ Common  │ Government│
│  APIs   │ ATS      │ APIs     │ Crawl   │ APIs      │
│Greenhouse│ Workday  │ Adzuna   │ Web Data│ USAJobs   │
│Lever    │ SAP SF   │ Jooble   │ Commons │ EURES     │
│Ashby    │ iCIMS    │ Careerjet│         │ Job Bank  │
│Workable │ Taleo    │ JSearch  │         │           │
│Recruitee│ BrassRing│ Reed     │         │           │
│Personio │ SmartRecr│ RemoteOK │         │           │
└────┬────┴────┬─────┴────┬─────┴────┬────┴─────┬─────┘
     │         │          │          │          │
     └─────────┴──────────┼──────────┴──────────┘
                          │
               ┌──────────▼──────────┐
               │  NORMALIZATION      │
               │  Location parsing   │
               │  Salary parsing     │
               │  Classification     │
               │  Deduplication      │
               └──────────┬──────────┘
                          │
               ┌──────────▼──────────┐
               │  JOB INDEX          │
               │  PostgreSQL         │
               │  20M-40M jobs       │
               └──────────┬──────────┘
                          │
     ┌────────────────────┼────────────────────┐
     │                    │                    │
┌────▼─────┐    ┌────────▼────────┐   ┌───────▼───────┐
│ AI Layer │    │ Web Frontend    │   │ Open API      │
│          │    │                 │   │               │
│ MCP      │    │ SSR pages with  │   │ REST API      │
│ server   │    │ JobPosting      │   │ 14 filters    │
│ llms.txt │    │ JSON-LD         │   │ Pagination    │
│ llm-info │    │ Sitemap.xml     │   │ Rate-limited  │
│          │    │ Google Indexing  │   │ Free tier     │
└──────────┘    └─────────────────┘   └───────────────┘
     │                    │                    │
     ▼                    ▼                    ▼
  Claude             Google for             Developers
  ChatGPT            Jobs/Bing              Startups
  Perplexity         AI Overviews           Widgets
```

---

## 8. Roadmap

### Month 1: Launch with 100K+ jobs
- Deploy to public URL
- Activate ATS API connectors (Greenhouse, Lever, Workday)
- Connect aggregator APIs (Adzuna, RemoteOK, USAJobs)
- Discover 5,000+ Greenhouse board tokens
- Discover 1,000+ Workday instances
- Submit sitemap to Google Search Console + Bing
- Activate IndexNow for real-time search engine notification

### Month 2: Scale to 1M+ jobs
- Build Ashby, Workable, Recruitee, Personio connectors
- Connect Jooble, Careerjet, JSearch, Reed APIs
- Process Common Crawl / Web Data Commons for JobPosting data
- Build SAP SuccessFactors sitemap crawler
- Connect USAJobs, Canada Job Bank, EURES
- Publish MCP server as pip package
- Launch ChatGPT custom GPT

### Month 3: Scale to 5M+ jobs
- Build Taleo, iCIMS Playwright crawlers
- Build SmartRecruiters sitemap connector
- Connect Bullhorn staffing API
- Launch embeddable job widget
- Launch employer claim/verify flow
- Activate Pro tier ($99/mo)

### Month 4-6: Scale to 10M+ jobs
- Full Playwright crawling of custom career pages
- BrassRing, BambooHR, JazzHR crawlers
- Regional job board crawling (Naukri, StepStone)
- Candidate matching features
- Enterprise tier launch ($499/mo)

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ATS APIs change/break | Medium | High | Multiple source redundancy. Monitor API health. Maintain Playwright fallback. |
| Rate limiting / IP blocking | High | Medium | Per-domain throttling, proxy rotation ($200-500/mo), respectful crawling. |
| Google sandboxes new domain | High | Medium | Start with aggregator APIs for volume. Build backlinks. Consider launching on existing Shazamme domain. |
| Legal challenges (scraping) | Low | High | We index publicly accessible career pages. Provide employer opt-out. Transparent bot identity. |
| Indeed/LinkedIn partnership exclusivity | Low | Medium | We don't depend on Indeed/LinkedIn data. Direct ATS access bypasses them. |
| Workday undocumented API breaks | Medium | High | Maintain Playwright fallback. Multiple data sources per employer. |

---

## 10. Why Now

1. **AI search is exploding.** ChatGPT has 300M+ WAU. Job search is one of the most common AI use cases. There's no structured data source for AI to pull from.

2. **MCP is new.** The Model Context Protocol is months old. First-mover advantage in building the definitive job search MCP server.

3. **Indeed is vulnerable.** Blocking AI crawlers is a losing strategy as search shifts to AI. The company that powers AI job search will capture the transition.

4. **ATS APIs are open.** The top 6 mid-market ATS platforms have free, public APIs. This wasn't always the case — Greenhouse and Lever opened up in the last few years.

5. **Common Crawl makes bulk extraction free.** 5-15M job pages per month, already crawled, already available. The data infrastructure cost is near zero.

The window is open. The question is who builds the AI-native job index first.
