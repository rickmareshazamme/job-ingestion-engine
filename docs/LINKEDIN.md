# LinkedIn — XML job feed ingestion

ZammeJobs publishes a LinkedIn-spec **Basic Jobs XML feed** at:

```
https://zammejobs.com/feeds/linkedin.xml
```

LinkedIn's crawler ingests this feed once registered. No API key, no OAuth — partnership conversation only.

Spec we conform to: **[LinkedIn XML Feeds Development Guide — 2026-03](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/xml-feeds-development-guide?view=li-lts-2026-03)**

---

## Why XML, not the Jobs API

| Path | Access | What it gets you |
|---|---|---|
| **Job Posting API** (`/simpleJobPostings`) | Partner-only — LinkedIn approves ATSs and major job boards | Real LinkedIn Job Postings with native apply |
| **OAuth Jobs API** (`/jobPostings`) | Partner-only, same gate | Same as above, REST-flavored |
| **Limited Listings XML feed** | Open — register the URL via your LinkedIn Talent Solutions rep | Jobs surface in LinkedIn Search results, click-out to your apply URL |

We use option 3. Once registered, LinkedIn polls the feed daily and ingests every valid job.

---

## What gets emitted

The feed only includes jobs that pass LinkedIn's mandatory-field bar:

- **Title** present
- **Description** ≥ 100 chars (HTML allowed, only safe tags)
- **Apply URL** starts with `https://`
- **Location** present (raw string or city/state/country)
- **Status** = `active`

Per LinkedIn policy on aggregated content, the feed defaults to **claimed employers only** — companies that self-registered via `POST /employer/register`. Override with `?claimed_only=false` (but expect LinkedIn to reject the feed if you submit aggregator content).

---

## Endpoint reference

`GET /feeds/linkedin.xml`

| Query param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50000 | Max jobs per response (LinkedIn caps at 500K — split by country if you hit it) |
| `country` | string | — | ISO-3166 alpha-2 code (`US`, `GB`, `DE`…) to scope the feed |
| `employer_id` | UUID | — | Scope to a single employer |
| `claimed_only` | bool | env default | Override `LINKEDIN_FEED_CLAIMED_ONLY` |

Response: `application/xml`, UTF-8, pretty-printed.

---

## Field mapping (Job model → LinkedIn XML)

| LinkedIn field | Source | Notes |
|---|---|---|
| `partnerJobId` | `jobs.id` (UUID) | 36 chars, well under the 40-char cap |
| `company` | `jobs.employer_name` | Required when the feed spans multiple companies |
| `title` | `jobs.title` | Immutable once posted |
| `description` | `jobs.description_html` (fallback `description_text`) | Wrapped in CDATA. Allowed tags: `<b> <strong> <u> <i> <br> <p> <ul> <li> <em>` (others stripped by LinkedIn) |
| `applyUrl` | `jobs.source_url` | Must be HTTPS. Direct ATS URL — no redirects |
| `companyId` | `employers.linkedin_company_id` | Required for ATS feeds. Find it in the LinkedIn Page admin URL |
| `location` | `jobs.location_raw` | Falls back to assembled `city, state, country` |
| `city` / `state` / `country` | structured columns | When present, take precedence over `location` |
| `workplaceTypes` | `jobs.remote_type` | Mapped → `On-site` / `Hybrid` / `Remote` |
| `experienceLevel` | `jobs.seniority` | Mapped → LinkedIn enum (`ENTRY_LEVEL`, `MID_SENIOR_LEVEL`, …) |
| `jobtype` | `jobs.employment_type` | Mapped → `FULL_TIME` / `PART_TIME` / `CONTRACT` / `INTERNSHIP` / `VOLUNTEER` |
| `salaries/salary/highEnd/lowEnd` | `salary_max` / `salary_min` | Only emitted if both currency and period are present |
| `salaries/salary/period` | `salary_period` | Mapped → `YEARLY`, `MONTHLY`, `WEEKLY`, `HOURLY`, … |
| `salaries/salary/type` | constant `BASE_SALARY` | TOTAL_ADDITIONAL not currently used |
| `listDate` | `jobs.date_posted` | `MM/DD/YYYY` |
| `expirationDate` | `jobs.date_expires` | `MM/DD/YYYY` |
| `posterEmail` | `employers.linkedin_poster_email` | Falls back to `LINKEDIN_DEFAULT_POSTER_EMAIL`. LinkedIn Trust & Safety uses this to verify the posting entity |

Unmapped enum values are **omitted**, not passed through — LinkedIn would reject unknown tokens.

---

## Operator runbook — going live

### 1. Run the migration

```bash
railway run alembic upgrade head
```

Adds `employers.linkedin_company_id` and `employers.linkedin_poster_email`.

### 2. Backfill LinkedIn Company IDs

Each employer that has a LinkedIn Page needs `linkedin_company_id` set. Find it via:

- Go to `linkedin.com/company/<slug>/admin/`
- The URL becomes `linkedin.com/company/<numeric-id>/admin/dashboard` after redirect
- That numeric ID is what we store

Quickest path is a one-off SQL backfill — direct from a CSV of company name → LinkedIn ID. Talk to a LinkedIn Talent Solutions rep about getting a bulk lookup file for your registered employer set.

### 3. Set the global poster email

```bash
railway variables set LINKEDIN_DEFAULT_POSTER_EMAIL=hello@zammejobs.com
```

Per-employer overrides can be set in `employers.linkedin_poster_email` later.

### 4. Smoke-test the feed

```bash
curl -s https://zammejobs.com/feeds/linkedin.xml | head -50
curl -s 'https://zammejobs.com/feeds/linkedin.xml?country=US&limit=10' | xmllint --noout -
```

The `xmllint` round-trip catches any malformed XML.

### 5. Validate against the spec

For each `<job>` element, confirm:
- `<partnerJobId>` ≤ 40 chars
- `<description>` ≥ 100 chars
- `<applyUrl>` starts with `https://`
- One of `<location>` or all of `<city>/<state>/<country>` is present
- `<posterEmail>` is set
- `<companyId>` is set (mandatory for ATS feeds)

### 6. Register the URL with LinkedIn

Email your LinkedIn Talent Solutions / Partner Engineering contact:

> Subject: Job feed registration — ZammeJobs (zammejobs.com)
>
> Hi —
>
> Please register the following XML job feed for ingestion:
>
> URL: https://zammejobs.com/feeds/linkedin.xml
> Format: LinkedIn Basic Jobs XML feed (per 2026-03 spec)
> Refresh: daily
> Job volume: ~N active jobs at launch, scaling to ~M
> Apply model: direct click-out to employer ATS apply URL
> Trust & Safety contact email: hello@zammejobs.com
>
> Let me know what else you need from our side.

LinkedIn will respond with onboarding instructions and confirm crawl frequency. They typically run a manual review of the first crawl before enabling production ingestion.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| LinkedIn reports "no valid jobs in feed" | `claimed_only=true` and no employers have `claimed=true` | Either claim employers (via `/employer/register` flow) or set `LINKEDIN_FEED_CLAIMED_ONLY=false` |
| LinkedIn rejects feed as "aggregated content" | Feed includes scraped jobs from third-party sources | Keep `claimed_only=true`. Confirm only direct-from-employer crawls are emitting jobs |
| Some jobs missing from LinkedIn search | Failed per-job validation (HTTP apply URL, < 100 char description, no location) | Run `curl /feeds/linkedin.xml?employer_id=X` and grep for the job ID — if absent, that's why |
| `applyUrl` validation errors from LinkedIn | URL doesn't start with `https://www` (LinkedIn's literal regex per spec) | Most ATSes don't include `www.` — LinkedIn typically still accepts these in practice. Escalate to your LinkedIn rep if rejected |
| Feed too large (> 500K jobs) | Single feed exceeds LinkedIn's cap | Split by country: register one feed per country (`?country=US`, `?country=GB`, …). Do not rotate jobs between feeds |

---

## Why the `claimed_only` default

LinkedIn's spec explicitly states:

> LinkedIn only accepts jobs that are directly posted by employers on your platform... Ensure to exclude jobs from the feed that are aggregated from other third-party sites

ZammeJobs crawls public ATS endpoints (Greenhouse, Lever, Workday, etc.) — that's arguably "direct from employer". But to stay on the safe side of LinkedIn's reviewer interpretation, we default to **only emitting jobs from employers who have self-registered**. Those employers have explicitly opted in, which removes any ambiguity.

If you have a partnership conversation where LinkedIn has signed off on broader ingestion, flip `LINKEDIN_FEED_CLAIMED_ONLY=false` and the full index becomes available.
