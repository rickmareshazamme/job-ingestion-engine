"""Common Crawl JobPosting harvester.

Strategy: Web Data Commons publishes pre-extracted schema.org structured
data from each monthly Common Crawl. We download the JobPosting subset,
filter, normalize, and upsert into our index.

Sources:
- Web Data Commons schema.org JobPosting extracts:
  https://webdatacommons.org/structureddata/2024-12/files.html
- Common Crawl indexes (CC-MAIN-YYYY-WW):
  https://commoncrawl.org/get-started

Two run modes:
1. WDC subset (recommended) — pre-filtered to JobPosting-only, ~1-3GB per crawl
2. Full Common Crawl URL index query — slower, more complete, $100-500 in S3 fees

This module implements (1). Mode (2) is documented at the bottom for reference.

Usage:
    from src.harvest.common_crawl import harvest_latest
    inserted = await harvest_latest(max_records=100_000)
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
from datetime import datetime
from typing import AsyncIterator, Optional
from urllib.parse import urlparse

import aiohttp

from src.connectors.base import RawJob

logger = logging.getLogger("zammejobs.harvest.commoncrawl")

# Web Data Commons schema.org structured data extracts. Their CDN serves
# .nq.gz N-Quads files filtered by schema.org type. Each line is a quad,
# with the @id as the URL on the open web that contained the JobPosting.
# Index is at:
#   https://webdatacommons.org/structureddata/2024-12/files/
# We point at the most recent extract; bump CRAWL_ID when new ones drop.
WDC_BASE = "https://webdatacommons.org/structureddata"
DEFAULT_CRAWL = "2024-12"  # Update this monthly

# Pattern: <subject> <predicate> <object> <graph_url> .
QUAD_RE = re.compile(r'^<([^>]+)>\s+<([^>]+)>\s+(.+?)\s+<([^>]+)>\s*\.\s*$')


async def list_wdc_files(crawl_id: str = DEFAULT_CRAWL) -> list[str]:
    """Get the list of JobPosting NQ files for a given crawl from WDC's file index."""
    index_url = f"{WDC_BASE}/{crawl_id}/files/"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.get(index_url) as r:
            if r.status != 200:
                logger.error("WDC index unreachable for %s (HTTP %d)", crawl_id, r.status)
                return []
            html = await r.text()
    # WDC publishes a /JobPosting/ path containing the .nq.gz files
    files = re.findall(r'href="(JobPosting[^"]+\.nq\.gz)"', html)
    return [f"{WDC_BASE}/{crawl_id}/files/{f}" for f in files]


async def stream_quads(url: str) -> AsyncIterator[tuple[str, str, str, str]]:
    """Stream parsed N-Quads from a gzipped URL. Yields (subject, predicate, object, graph)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as s:
        async with s.get(url) as r:
            r.raise_for_status()
            data = await r.read()

    # WDC files can be 100MB-2GB. Decompress in memory; for production use
    # streaming + gzip.GzipFile + line iteration to keep RSS bounded.
    text = gzip.decompress(data).decode("utf-8", errors="replace")
    for line in text.splitlines():
        m = QUAD_RE.match(line)
        if not m:
            continue
        yield m.group(1), m.group(2), m.group(3), m.group(4)


def _strip_literal(obj: str) -> str:
    """Extract the literal value from an N-Quad object like \"foo\"@en or \"foo\"^^<...>."""
    if obj.startswith('"'):
        end = obj.rfind('"')
        return obj[1:end] if end > 0 else obj.strip('"')
    if obj.startswith("<") and obj.endswith(">"):
        return obj[1:-1]
    return obj


async def harvest_file(file_url: str, max_records: Optional[int] = None) -> list[RawJob]:
    """Parse one WDC file into RawJob records, deduped by URL."""
    logger.info("Harvesting Common Crawl file: %s", file_url)
    jobs_by_url: dict[str, dict] = {}

    async for subj, pred, obj, graph in stream_quads(file_url):
        url = graph  # the page where this JobPosting was found
        if url not in jobs_by_url:
            jobs_by_url[url] = {"_subject": subj}
        rec = jobs_by_url[url]

        pred_short = pred.split("/")[-1].lower()
        # Map the schema.org predicates we care about
        if pred_short in ("title", "name"):
            rec.setdefault("title", _strip_literal(obj))
        elif pred_short == "description":
            rec.setdefault("description", _strip_literal(obj))
        elif pred_short == "datePosted":
            rec.setdefault("date_posted", _strip_literal(obj))
        elif pred_short in ("validThrough", "expires"):
            rec.setdefault("date_expires", _strip_literal(obj))
        elif pred_short == "employmentType":
            rec.setdefault("employment_type", _strip_literal(obj))
        elif pred_short == "hiringOrganization":
            rec.setdefault("_org_subj", _strip_literal(obj))
        elif pred_short == "jobLocation":
            rec.setdefault("_loc_subj", _strip_literal(obj))
        elif pred_short == "baseSalary":
            rec.setdefault("_salary_subj", _strip_literal(obj))

        if max_records and len(jobs_by_url) >= max_records:
            break

    raw_jobs: list[RawJob] = []
    for url, rec in jobs_by_url.items():
        if not rec.get("title"):
            continue
        try:
            host = urlparse(url).netloc or "commoncrawl-source.invalid"
        except Exception:
            host = "commoncrawl-source.invalid"

        date_posted = None
        dp = rec.get("date_posted")
        if dp:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    date_posted = datetime.strptime(dp[:19], "%Y-%m-%dT%H:%M:%S")
                    break
                except ValueError:
                    continue

        raw_jobs.append(RawJob(
            source_type="commoncrawl_jobposting",
            source_id=url,
            source_url=url,
            title=rec.get("title", "")[:500],
            description_html=rec.get("description", "")[:50000],
            employer_name=host,  # WDC needs second-pass join to resolve org name
            employer_domain=host,
            location_raw="",
            employment_type_raw=rec.get("employment_type"),
            date_posted=date_posted,
            categories=[],
            is_remote=None,
            raw_data={"crawl_source": "common_crawl_wdc", "graph_url": url},
        ))

    logger.info("Common Crawl file yielded %d JobPostings (deduped)", len(raw_jobs))
    return raw_jobs


async def harvest_latest(crawl_id: str = DEFAULT_CRAWL, max_files: int = 3, max_records: Optional[int] = None) -> list[RawJob]:
    """Fetch the N most recent JobPosting NQ files from WDC and harvest them."""
    files = await list_wdc_files(crawl_id)
    if not files:
        logger.warning("No JobPosting files found for crawl %s", crawl_id)
        return []

    targets = files[:max_files]
    logger.info("Common Crawl harvest: %d files from crawl %s (of %d available)", len(targets), crawl_id, len(files))

    all_jobs: list[RawJob] = []
    for f in targets:
        try:
            chunk = await harvest_file(f, max_records=max_records)
            all_jobs.extend(chunk)
            if max_records and len(all_jobs) >= max_records:
                break
        except Exception as e:
            logger.warning("Common Crawl file failed: %s — %s", f, str(e)[:200])

    return all_jobs


# ---------------------------------------------------------------------------
# Reference: full Common Crawl URL-index query mode (NOT IMPLEMENTED HERE)
#
# The CDX index lets you query "all URLs containing JobPosting JSON-LD" in
# a given crawl. Pattern:
#   GET https://index.commoncrawl.org/CC-MAIN-{YYYY-WW}-index?url=*&filter=mime:application/ld%2Bjson&output=json
# Then for each match, fetch the WARC range and parse the JSON-LD blob.
# Costs $0.05/GB on AWS S3 for the WARC reads, ~$200-500 per full crawl
# pass. Use only when WDC's pre-extracted set isn't enough.
# ---------------------------------------------------------------------------
