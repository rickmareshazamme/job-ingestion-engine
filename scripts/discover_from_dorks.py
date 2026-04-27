"""URL-pattern discovery via Common Crawl's CDX index.

This is the "Google dork at scale" play. Instead of hitting Google's
rate-limited search, we query Common Crawl's CDX index — which has
indexed every URL its crawler has seen across ~3-5 billion pages per
monthly crawl. CDX accepts wildcard patterns and returns JSON.

Endpoint:
    https://index.commoncrawl.org/CC-MAIN-{YYYY-WW}-index
        ?url={pattern}&output=json&limit={N}

Why this beats Google dorks:
- Free, no API key, no rate limit
- Returns up to 100M+ matches per pattern (not 100/day)
- Direct access to every URL ever crawled

Why it might miss things:
- 6-12 month time lag — companies that newly adopted an ATS in 2025
  won't appear in 2024 crawls
- CC doesn't crawl pages behind login walls or anti-bot gates

For each ATS, we know the URL pattern that uniquely identifies a customer.
Pull every CDX hit, extract the slug, dedupe, run ATS-detect (or skip
if the pattern is already unambiguous), insert source_configs.

Usage:
    python3 -m scripts.discover_from_dorks
    python3 -m scripts.discover_from_dorks --ats greenhouse --limit 5000
    python3 -m scripts.discover_from_dorks --crawl CC-MAIN-2024-51
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import uuid
from typing import Optional
from urllib.parse import urlparse

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover_dorks")

DEFAULT_CRAWL = "CC-MAIN-2024-51"  # Latest publicly indexed crawl as of 2026-04
CDX_BASE = "https://index.commoncrawl.org"

# Per-ATS URL pattern → (CDX query pattern, regex to extract slug, source_type)
ATS_PATTERNS = {
    "greenhouse": {
        "patterns": [
            "*.boards.greenhouse.io/*",
            "boards.greenhouse.io/*",
            "*.greenhouse.io/*/jobs/*",
        ],
        "slug_re": re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+)"),
        "source_type": "greenhouse_api",
    },
    "lever": {
        "patterns": [
            "*.jobs.lever.co/*",
            "jobs.lever.co/*",
        ],
        "slug_re": re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)"),
        "source_type": "lever_api",
    },
    "ashby": {
        "patterns": [
            "*.ashbyhq.com/*",
            "jobs.ashbyhq.com/*",
        ],
        "slug_re": re.compile(r"ashbyhq\.com/([a-zA-Z0-9_-]+)"),
        "source_type": "ashby_api",
    },
    "workable": {
        "patterns": [
            "*.workable.com/*",
            "apply.workable.com/*",
        ],
        "slug_re": re.compile(r"(?:apply\.workable\.com|([a-zA-Z0-9_-]+)\.workable\.com)/"),
        "source_type": "workable_api",
    },
    "recruitee": {
        "patterns": [
            "*.recruitee.com/*",
        ],
        "slug_re": re.compile(r"^https?://([a-zA-Z0-9_-]+)\.recruitee\.com"),
        "source_type": "recruitee_api",
    },
    "personio": {
        "patterns": [
            "*.jobs.personio.de/*",
            "*.jobs.personio.com/*",
        ],
        "slug_re": re.compile(r"^https?://([a-zA-Z0-9_-]+)\.jobs\.personio\.(?:de|com)"),
        "source_type": "personio_xml",
    },
    "smartrecruiters": {
        "patterns": [
            "*.smartrecruiters.com/*",
            "careers.smartrecruiters.com/*",
            "jobs.smartrecruiters.com/*",
        ],
        "slug_re": re.compile(r"smartrecruiters\.com/([a-zA-Z0-9_-]+)"),
        "source_type": "smartrecruiters_sitemap",
    },
    "workday": {
        # Workday is special — pattern is {company}.wd{N}.myworkdayjobs.com/{site}
        "patterns": [
            "*.myworkdayjobs.com/*",
        ],
        "slug_re": re.compile(r"^https?://([a-zA-Z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com/[^/]+/([a-zA-Z0-9_-]+)"),
        "source_type": "workday_feed",
    },
}


async def query_cdx(
    session: aiohttp.ClientSession,
    crawl: str,
    pattern: str,
    limit: int = 10000,
) -> list[str]:
    """Query CC's CDX index for every URL matching `pattern`. Returns unique URLs."""
    url = f"{CDX_BASE}/{crawl}-index?url={pattern}&output=json&limit={limit}"
    logger.info("CDX query: %s", url)
    found: set[str] = set()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as r:
            if r.status != 200:
                logger.warning("CDX %s returned HTTP %d", pattern, r.status)
                return []
            async for line_bytes in r.content:
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and rec.get("url"):
                        found.add(rec["url"])
                except json.JSONDecodeError:
                    continue
    except (aiohttp.ClientError, TimeoutError) as e:
        logger.warning("CDX request failed for %s: %s", pattern, str(e)[:120])
    logger.info("CDX %s: %d unique URLs", pattern, len(found))
    return list(found)


def extract_tokens(ats_name: str, urls: list[str]) -> dict[str, dict]:
    """Extract (slug, full_token, source_type) from a list of URLs.
    Returns {slug: {token, source_type, sample_url}} deduped.
    """
    cfg = ATS_PATTERNS[ats_name]
    rx = cfg["slug_re"]
    src = cfg["source_type"]
    out: dict[str, dict] = {}
    for u in urls:
        m = rx.search(u)
        if not m:
            continue
        if ats_name == "workday":
            company, instance, site = m.group(1), m.group(2), m.group(3)
            token = f"{company}|{instance}|{site}"
            slug = company
        elif ats_name == "workable":
            slug = m.group(1) or ""
            if not slug:
                continue
            token = slug
        else:
            slug = m.group(1)
            token = slug

        if not slug or len(slug) < 2:
            continue
        # Filter out obvious noise
        if slug.lower() in {"jobs", "careers", "static", "assets", "api", "www", "admin"}:
            continue
        if slug not in out:
            out[slug] = {"token": token, "source_type": src, "sample_url": u}
    return out


def insert_source_configs(matches: dict[str, dict[str, dict]]) -> int:
    """matches: {ats_name: {slug: {token, source_type, sample_url}}}.
    Idempotent: skip if (employer_domain, source_type) already exists.
    Returns count of NEW source_configs created.
    """
    from sqlalchemy import create_engine, text as sql_text
    from src.config import settings

    engine = create_engine(settings.database_url_sync)
    new_count = 0
    with engine.begin() as conn:
        for ats_name, slugs in matches.items():
            for slug, info in slugs.items():
                # Synthetic employer domain — connector will overwrite once real
                # data arrives (employer_name from API response is more accurate)
                domain = f"{slug}.{ats_name}-discovered.invalid"

                # Skip if already known via either domain or matching source_config
                existing = conn.execute(sql_text("""
                    SELECT 1 FROM source_configs
                     WHERE source_type = :st
                       AND config->>'board_token' = :tok
                """), {"st": info["source_type"], "tok": info["token"]}).fetchone()
                if existing:
                    continue

                # Upsert employer
                emp_id = conn.execute(sql_text("""
                    INSERT INTO employers (id, name, domain, ats_platform, created_at, updated_at)
                    VALUES (gen_random_uuid(), :name, :domain, :ats, NOW(), NOW())
                    ON CONFLICT (domain) DO UPDATE SET ats_platform = EXCLUDED.ats_platform
                    RETURNING id
                """), {"name": slug, "domain": domain, "ats": ats_name}).scalar()

                conn.execute(sql_text("""
                    INSERT INTO source_configs
                      (id, employer_id, source_type, config, crawl_interval_hours, is_active, created_at)
                    VALUES
                      (gen_random_uuid(), :eid, :st, :cfg, 6, TRUE, NOW())
                """), {
                    "eid": emp_id,
                    "st": info["source_type"],
                    "cfg": json.dumps({
                        "board_token": info["token"],
                        "employer_domain": domain,
                        "discovered_via": "cc_cdx_dork",
                        "sample_url": info["sample_url"],
                    }),
                })
                new_count += 1
    return new_count


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ats", help="Limit to one ATS (greenhouse/lever/ashby/workable/recruitee/personio/smartrecruiters/workday)")
    p.add_argument("--limit", type=int, default=10000, help="Max CDX results per pattern")
    p.add_argument("--crawl", default=DEFAULT_CRAWL, help="CC-MAIN-YYYY-WW crawl ID")
    args = p.parse_args()

    targets = [args.ats] if args.ats else list(ATS_PATTERNS.keys())

    matches: dict[str, dict[str, dict]] = {}
    headers = {"User-Agent": "ZammeJobsBot/1.0 (+https://zammejobs.com/bot; cdx-discovery)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for ats_name in targets:
            cfg = ATS_PATTERNS[ats_name]
            urls: list[str] = []
            for pat in cfg["patterns"]:
                urls.extend(await query_cdx(session, args.crawl, pat, args.limit))
            tokens = extract_tokens(ats_name, urls)
            matches[ats_name] = tokens
            logger.info("%-16s %d unique slugs from %d URLs", ats_name, len(tokens), len(urls))

    total_slugs = sum(len(v) for v in matches.values())
    logger.info("Total candidate slugs across all ATS: %d", total_slugs)

    if total_slugs == 0:
        logger.info("Nothing to insert.")
        return

    new_count = insert_source_configs(matches)
    logger.info("Inserted %d new source_configs (skipped %d duplicates)", new_count, total_slugs - new_count)
    logger.info("They'll be picked up by the next 30-min crawl_all_due_sources beat.")


if __name__ == "__main__":
    asyncio.run(main())
