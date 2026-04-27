"""Discover Oracle Taleo career sites.

Probes Fortune 2000 domains against Taleo's URL convention:
    {slug}.taleo.net/careersection/{section_id}/jobsearch.ftl

Auto-discovers section_id by HEAD-probing common values (1,2,3,...,1001,1002).
For each working subdomain + section_id, INSERT an Employer + SourceConfig
row using the same shape as scripts.discover_workday_confirmed.

Input: data/fortune2000_domains.txt — one company-slug per line.
If absent, falls back to a hardcoded sample of 50 known Taleo customers.

Usage:
    python3 -m scripts.discover_taleo
    python3 -m scripts.discover_taleo --test
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover.taleo")


# Known Taleo-using companies (sample if no input file).
SAMPLE_SLUGS = [
    # Banks
    "wellsfargo", "usbank", "pnc", "bnymellon", "citigroup",
    "scotiabank", "rbc", "td", "bmo", "barclays", "hsbc", "ubs",
    # Airlines
    "delta", "ual", "aa", "southwest", "alaska", "jetblue",
    "lufthansa", "airfrance", "klm", "britishairways", "qantas",
    # Retail
    "homedepot", "lowes", "bestbuy", "macys", "kohls", "target",
    "publix", "albertsons", "kroger",
    # Pharma / Healthcare
    "ibm", "cvs", "walgreens", "kaiserpermanente", "anthem",
    "cigna", "humana", "humanaonehealth",
    # Telco
    "vodafone", "tmobile", "sprint",
    # Consumer
    "nike", "underarmour", "adidas",
    # Energy
    "exxonmobil", "chevron", "shell", "conocophillips",
    # Insurance
    "metlife", "prudential", "aig", "allstate", "geico",
    # Hospitality
    "marriott", "hilton", "hyatt", "ihg", "accor",
    # Industrial
    "gm", "ford", "boeing", "raytheon", "lockheed",
]

COMMON_SECTION_IDS = ["1", "2", "3", "4", "5", "10", "100", "101", "1001", "1002"]


async def probe_section(
    session: aiohttp.ClientSession,
    host: str,
    section_id: str,
) -> Optional[str]:
    url = f"https://{host}/careersection/{section_id}/jobsearch.ftl"
    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                return section_id
            if resp.status in (405, 501):
                async with session.get(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as g:
                    if g.status == 200:
                        return section_id
    except Exception:
        return None
    return None


async def probe_one(
    session: aiohttp.ClientSession,
    slug: str,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    async with semaphore:
        host = f"{slug}.taleo.net"
        for sid in COMMON_SECTION_IDS:
            found = await probe_section(session, host, sid)
            if found:
                logger.info("VALID Taleo: %s/careersection/%s", host, found)
                return {
                    "slug": slug,
                    "host": host,
                    "section_id": found,
                    "career_page_url": (
                        f"https://{host}/careersection/{found}/jobsearch.ftl"
                    ),
                    "board_token": f"{slug}/{found}",
                }
        await asyncio.sleep(0.2)
        return None


async def discover(slugs: list[str], concurrency: int = 8) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(
        headers={"User-Agent": "ZammeJobsBot/1.0 (+https://zammejobs.com/bot)"},
    ) as session:
        results = await asyncio.gather(*(probe_one(session, slug, semaphore) for slug in slugs))
    return [r for r in results if r]


def load_slugs() -> list[str]:
    p = Path(__file__).parent.parent / "data" / "fortune2000_domains.txt"
    if p.exists():
        slugs = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            slug = line.split(".", 1)[0].lower()
            slugs.append(slug)
        return slugs
    return list(SAMPLE_SLUGS)


def save_to_db(valid: list[dict]) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.config import settings
    from src.models import Employer, SourceConfig

    engine = create_engine(settings.database_url_sync)
    Session = sessionmaker(bind=engine)
    session = Session()

    created = 0
    try:
        for v in valid:
            slug = v["slug"]
            domain = f"{slug}.com"
            existing = session.query(Employer).filter_by(domain=domain).first()
            if existing:
                continue

            employer = Employer(
                id=uuid.uuid4(),
                name=slug.title(),
                domain=domain,
                ats_platform="taleo",
                career_page_url=v["career_page_url"],
            )
            session.add(employer)
            session.flush()

            source = SourceConfig(
                id=uuid.uuid4(),
                employer_id=employer.id,
                source_type="taleo_html",
                config={"board_token": v["board_token"], "employer_domain": domain},
                crawl_interval_hours=12,
            )
            session.add(source)
            created += 1
        session.commit()
    finally:
        session.close()

    logger.info("Created %d new Taleo employer + source configs", created)


def main() -> None:
    test_only = "--test" in sys.argv
    slugs = load_slugs()
    logger.info("Probing %d slugs against Taleo", len(slugs))

    valid = asyncio.run(discover(slugs))
    logger.info("Taleo valid: %d / %d", len(valid), len(slugs))

    out = Path(__file__).parent.parent / "taleo_discoveries.json"
    out.write_text(json.dumps(valid, indent=2))
    logger.info("Saved to %s", out)

    if not test_only and valid:
        save_to_db(valid)


if __name__ == "__main__":
    main()
