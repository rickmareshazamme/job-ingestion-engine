"""Common Crawl / Web Data Commons JobPosting harvester.

Extracts JobPosting JSON-LD from Common Crawl data without crawling
the web ourselves. Common Crawl publishes 3-5 billion pages monthly.

Methods:
1. Web Data Commons pre-extracted structured data (easiest)
2. Common Crawl Index API (cc-index) to find job posting pages
3. Download targeted WARC segments for specific domains

This module focuses on method 2 (cc-index) as it's the most practical
for discovering career sites and extracting job data.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from src.config import settings
from src.connectors.base import RawJob

logger = logging.getLogger("jobindex.discovery.commoncrawl")

# Common Crawl Index API
CC_INDEX_URL = "https://index.commoncrawl.org"
# Latest crawl (update periodically)
LATEST_CRAWL = "CC-MAIN-2025-13"


@dataclass
class CCJobPage:
    """A page from Common Crawl that likely contains job postings."""
    url: str
    domain: str
    crawl_id: str
    warc_filename: str
    warc_offset: int
    warc_length: int
    status: int
    content_type: str


async def search_cc_index(
    query: str,
    crawl: str = LATEST_CRAWL,
    max_results: int = 1000,
) -> list[CCJobPage]:
    """Search Common Crawl index for URLs matching a pattern.

    Examples:
        search_cc_index("*.greenhouse.io/*/jobs/*")
        search_cc_index("*.myworkdayjobs.com/*")
        search_cc_index("*/careers/*")
    """
    url = f"{CC_INDEX_URL}/{crawl}-index"
    params = {
        "url": query,
        "output": "json",
        "limit": max_results,
    }

    results = []
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": settings.bot_user_agent},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("CC Index returned %d for query: %s", resp.status, query)
                    return []

                text = await resp.text()
                for line in text.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        results.append(CCJobPage(
                            url=data.get("url", ""),
                            domain=data.get("urlkey", "").split(")")[0] if ")" in data.get("urlkey", "") else "",
                            crawl_id=crawl,
                            warc_filename=data.get("filename", ""),
                            warc_offset=int(data.get("offset", 0)),
                            warc_length=int(data.get("length", 0)),
                            status=int(data.get("status", 0)),
                            content_type=data.get("mime", ""),
                        ))
                    except (json.JSONDecodeError, ValueError):
                        continue

    except Exception as e:
        logger.error("CC Index search failed: %s", str(e)[:200])

    logger.info("CC Index: found %d results for query '%s'", len(results), query)
    return results


async def discover_career_sites_from_cc(max_per_ats: int = 500) -> dict:
    """Discover career sites by querying Common Crawl for known ATS URL patterns.

    This finds career sites we don't know about by searching for ATS-hosted pages.
    """
    ats_queries = {
        "greenhouse": "boards.greenhouse.io/*",
        "lever": "jobs.lever.co/*",
        "ashby": "jobs.ashbyhq.com/*",
        "workable": "apply.workable.com/*",
        "smartrecruiters": "careers.smartrecruiters.com/*",
        "workday": "*.myworkdayjobs.com/*",
        "recruitee": "*.recruitee.com/*",
        "icims": "*.icims.com/*",
        "taleo": "*.taleo.net/*",
    }

    all_discoveries = {}

    for ats, query in ats_queries.items():
        logger.info("Searching Common Crawl for %s career pages...", ats)
        pages = await search_cc_index(query, max_results=max_per_ats)

        # Extract unique domains/board tokens
        tokens = set()
        for page in pages:
            url = page.url.lower()

            if ats == "greenhouse":
                import re
                m = re.search(r"boards\.greenhouse\.io/(\w+)", url)
                if m:
                    tokens.add(m.group(1))

            elif ats == "lever":
                import re
                m = re.search(r"jobs\.lever\.co/(\w+)", url)
                if m:
                    tokens.add(m.group(1))

            elif ats == "workday":
                import re
                m = re.search(r"(\w+)\.wd(\d+)\.myworkdayjobs\.com", url)
                if m:
                    tokens.add(f"{m.group(1)}|{m.group(2)}")

            elif ats == "ashby":
                import re
                m = re.search(r"jobs\.ashbyhq\.com/(\w+)", url)
                if m:
                    tokens.add(m.group(1))

            elif ats == "workable":
                import re
                m = re.search(r"apply\.workable\.com/(\w+)", url)
                if m:
                    tokens.add(m.group(1))

            elif ats == "smartrecruiters":
                import re
                m = re.search(r"careers\.smartrecruiters\.com/(\w+)", url)
                if m:
                    tokens.add(m.group(1))

            elif ats == "recruitee":
                import re
                m = re.search(r"(\w+)\.recruitee\.com", url)
                if m and m.group(1) not in ("www", "api", "app"):
                    tokens.add(m.group(1))

        all_discoveries[ats] = sorted(tokens)
        logger.info("  %s: found %d unique board tokens from %d CC pages", ats, len(tokens), len(pages))

    return all_discoveries


async def fetch_warc_record(page: CCJobPage) -> Optional[str]:
    """Fetch a single WARC record from Common Crawl S3.

    This downloads just the specific bytes for one page, not the entire WARC file.
    """
    warc_url = f"https://data.commoncrawl.org/{page.warc_filename}"
    headers = {
        "Range": f"bytes={page.warc_offset}-{page.warc_offset + page.warc_length - 1}",
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(warc_url, headers=headers) as resp:
                if resp.status in (200, 206):
                    compressed = await resp.read()
                    try:
                        decompressed = gzip.decompress(compressed)
                        return decompressed.decode("utf-8", errors="replace")
                    except Exception:
                        return compressed.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("Failed to fetch WARC record: %s", str(e)[:100])

    return None


async def extract_jobposting_from_html(html: str) -> list[dict]:
    """Extract JobPosting JSON-LD from HTML."""
    import re

    json_ld_pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )

    job_postings = []
    for match in json_ld_pattern.finditer(html):
        try:
            data = json.loads(match.group(1))

            if isinstance(data, dict):
                if data.get("@type") == "JobPosting":
                    job_postings.append(data)
                elif "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            job_postings.append(item)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        job_postings.append(item)

        except json.JSONDecodeError:
            continue

    return job_postings
