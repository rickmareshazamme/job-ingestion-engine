---
license: cc-by-4.0
pretty_name: ZammeJobs Global Job Index
task_categories:
  - text-retrieval
  - text-classification
  - feature-extraction
language:
  - en
  - de
  - fr
  - es
  - nl
  - it
  - pt
  - sv
  - da
  - no
  - fi
  - pl
size_categories:
  - 10K<n<100K
tags:
  - jobs
  - employment
  - recruiting
  - hiring
  - ats
  - job-postings
  - schema-org
  - json-ld
  - greenhouse
  - lever
  - workday
  - llm-training
  - retrieval
source_datasets:
  - original
multilinguality:
  - multilingual
annotations_creators:
  - machine-generated
language_creators:
  - found
paperswithcode_id: zammejobs
configs:
  - config_name: default
    data_files:
      - split: train
        path: jobs.jsonl.gz
---

# ZammeJobs — Global AI-Native Job Index

> A daily-refreshed, CC-BY-4.0 licensed snapshot of every active job posting
> indexed by [ZammeJobs](https://zammejobs.com): a global, AI-native job
> aggregator that crawls corporate ATS platforms (Greenhouse, Lever, Workday,
> Ashby, SmartRecruiters, Recruitee, Personio, Workable) plus public job
> aggregator APIs (Adzuna, USAJobs, Reed, Jooble, Careerjet, Canada Job Bank,
> RemoteOK, Remotive, Arbeitnow, The Muse).

**Currently indexed: {{TOTAL_RECORDS}} active job postings.**
**Last updated: {{LAST_UPDATED}}** (UTC).

## Why this dataset exists

Most job listings on the public web are *invisible to AI search* — they
render client-side via JavaScript ATS widgets, sit behind anti-bot walls, or
are hidden inside aggregator products that block AI crawlers (Indeed,
LinkedIn, Glassdoor). The result: every modern LLM has a giant blind spot
about what jobs actually exist *right now*.

ZammeJobs fixes that. We crawl the canonical source — the company's own ATS
— normalize every posting to schema.org `JobPosting` JSON-LD, and publish
the entire index as a free, attribution-only dataset. This Hugging Face
mirror exists so LLM trainers and retrieval-augmented systems can ingest
the index directly without scraping.

## What's in here

A single gzipped JSON Lines file — `jobs.jsonl.gz` — where each line is a
schema.org [`JobPosting`](https://schema.org/JobPosting) record. Plus a
`manifest.json` describing the snapshot.

## Quick start

```python
from datasets import load_dataset

ds = load_dataset("zammejobs/jobs")
print(ds)
print(ds["train"][0])
```

Or stream without downloading:

```python
ds = load_dataset("zammejobs/jobs", streaming=True)
for record in ds["train"].take(5):
    print(record["title"], "—", record["hiringOrganization"]["name"])
```

Raw file access:

```bash
huggingface-cli download zammejobs/jobs jobs.jsonl.gz --repo-type dataset
gunzip -c jobs.jsonl.gz | head -1 | jq
```

## Schema

Every record is a JSON-LD `JobPosting`. Fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `@context` | string | Always `https://schema.org`. | `"https://schema.org"` |
| `@type` | string | Always `JobPosting`. | `"JobPosting"` |
| `@id` | string | Canonical URL on zammejobs.com. | `"https://zammejobs.com/jobs/<uuid>"` |
| `identifier` | string | Stable UUID for the posting. | `"7c2b9e1a-..."` |
| `title` | string | Job title as published by the employer. | `"Senior Backend Engineer"` |
| `description` | string | Plain-text job description (HTML stripped). | `"We are hiring a senior..."` |
| `datePosted` | string \| null | ISO date the posting first appeared. | `"2026-04-15"` |
| `validThrough` | string \| null | ISO date the posting expires. | `"2026-05-15"` |
| `employmentType` | string \| null | One of `FULL_TIME`, `PART_TIME`, `CONTRACTOR`, `TEMPORARY`, `INTERN`, `VOLUNTEER`, `PER_DIEM`, `OTHER`. | `"FULL_TIME"` |
| `hiringOrganization` | object | `{ @type: Organization, name, sameAs }`. | `{"name": "Acme", "sameAs": "https://acme.com"}` |
| `jobLocation` | object | `{ @type: Place, address: { addressLocality, addressRegion, addressCountry } }`. | see below |
| `baseSalary` | object \| null | `MonetaryAmount` with `currency` and `value` (`QuantitativeValue` with `minValue`, `maxValue`, `unitText`). | see below |
| `applicantLocationRequirements` | array \| null | Present when remote — list of accepted countries. | `[{"@type":"Country","name":"US"}]` |
| `jobLocationType` | string \| null | `"TELECOMMUTE"` for remote roles. | `"TELECOMMUTE"` |
| `url` | string | Direct link to the original ATS posting. | `"https://boards.greenhouse.io/..."` |
| `industry` | array \| null | Inferred categories. | `["Engineering","Backend"]` |
| `experienceRequirements` | string \| null | Inferred seniority bucket. | `"senior"` |

### Example record

```json
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "@id": "https://zammejobs.com/jobs/7c2b9e1a-1f23-4f1c-9e10-1234567890ab",
  "identifier": "7c2b9e1a-1f23-4f1c-9e10-1234567890ab",
  "title": "Senior Backend Engineer",
  "description": "We are hiring a senior backend engineer to join our payments team...",
  "datePosted": "2026-04-15",
  "validThrough": "2026-05-15",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "Acme Corp",
    "sameAs": "https://acme.com"
  },
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "addressLocality": "Berlin",
      "addressRegion": "BE",
      "addressCountry": "DE"
    }
  },
  "baseSalary": {
    "@type": "MonetaryAmount",
    "currency": "EUR",
    "value": {
      "@type": "QuantitativeValue",
      "minValue": 80000,
      "maxValue": 110000,
      "unitText": "YEAR"
    }
  },
  "jobLocationType": "TELECOMMUTE",
  "applicantLocationRequirements": [{"@type": "Country", "name": "DE"}],
  "url": "https://boards.greenhouse.io/acme/jobs/1234567",
  "industry": ["Engineering", "Backend"],
  "experienceRequirements": "senior"
}
```

## Sources

Records are normalized from these connectors:

- **ATS APIs** — Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Recruitee, Personio, Workable, BambooHR, JazzHR, Teamtailor, Rippling, Pinpoint, Comeet, Breezy.
- **Job aggregator APIs** — Adzuna, USAJobs, Reed, Jooble, Careerjet, Canada Job Bank, RemoteOK, Remotive, Arbeitnow, The Muse.
- **Public sitemaps and Common Crawl** — for long-tail employer career pages.

We do **not** scrape Indeed, LinkedIn, Glassdoor, or any source that
prohibits crawling. Every record links back to the original ATS posting.

## Update cadence

- **Source crawl:** ATS APIs every 6h, aggregators every 12h, web crawls every 24h.
- **This dataset:** rebuilt and pushed daily at ~06:00 UTC by a GitHub Action.
- **Liveness:** expired or 404 postings are marked `expired` upstream and excluded from the snapshot.

The full live feed is always available at
[`https://web-production-10b8.up.railway.app/data/jobs.jsonl`](https://web-production-10b8.up.railway.app/data/jobs.jsonl).

## License

[**CC-BY-4.0**](https://creativecommons.org/licenses/by/4.0/) — you may copy,
redistribute, remix, transform, and build upon the data for any purpose,
including commercially and for LLM training, provided you give appropriate
credit. Suggested attribution:

> Source: ZammeJobs (https://zammejobs.com), CC-BY-4.0.

## Citation

```bibtex
@misc{zammejobs2026,
  title  = {ZammeJobs: Global AI-Native Job Index},
  author = {ZammeJobs},
  year   = {2026},
  url    = {https://zammejobs.com},
  note   = {CC-BY-4.0 licensed dataset of active job postings from corporate ATS platforms}
}
```

## Contact

- Website: [zammejobs.com](https://zammejobs.com)
- API docs: [zammejobs.com/docs](https://web-production-10b8.up.railway.app/docs)
- AI integration guide: [zammejobs.com/for-ai](https://web-production-10b8.up.railway.app/for-ai)
- Email: [hello@zammejobs.com](mailto:hello@zammejobs.com)

AI labs: we offer rate-limit-free access to the live feed. Email us with
your crawler User-Agent string and we'll allowlist it.

## Changelog

- **2026-04**: Initial public release. Daily mirror from production index.
