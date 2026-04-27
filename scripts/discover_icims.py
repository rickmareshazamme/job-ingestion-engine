"""Discover iCIMS career sites.

Probes Fortune 500 / Fortune 2000 domains against iCIMS' two URL conventions:
    careers-{slug}.icims.com
    {slug}.icims.com

For each subdomain that responds 200/3xx to a HEAD on /jobs/search, INSERT
an Employer + SourceConfig row using the same shape as
scripts.discover_workday_confirmed.

Input: data/fortune2000_domains.txt (one company-slug per line). If absent,
falls back to a hardcoded sample of 50 known Fortune 500 domains.

Usage:
    python3 -m scripts.discover_icims
    python3 -m scripts.discover_icims --test    # don't write to DB
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
logger = logging.getLogger("discover.icims")


# Known iCIMS-using companies — used if data/fortune2000_domains.txt is missing.
SAMPLE_SLUGS = [
    # Healthcare / Pharma
    "philips", "abbvie", "merck", "biogen", "regeneron", "vertex",
    "bostonscientific", "bd", "stryker", "zimmerbiomet",
    # Tech
    "att", "lumen", "hpe", "cisco", "akamai", "symantec",
    # Retail / Consumer
    "macys", "kohls", "nordstrom", "dollargeneral", "dollartree",
    "advanceautoparts", "autozone", "rossstores", "tjx", "burlington",
    # Industrial
    "honeywell", "eaton", "emerson", "rockwellautomation", "parker",
    "illinoistool", "danaher", "fortivecorp", "ametek", "dover",
    # Finance
    "citizensbank", "regions", "fifththird", "keybank", "huntington",
    "synchrony", "discover", "capitalone",
    # Aerospace / Defense
    "northropgrumman", "lockheedmartin", "l3harris", "leidos",
    # Other large enterprises
    "maersk", "zoetis", "kellogg", "campbellsoup", "hersheys",
]

ICIMS_PROBE_PAYLOAD = {
    "in_iframe": 1,
    "hashed": 0,
    "searchKeyword": "",
    "searchCategory": "",
    "searchLocation": "",
    "mobile": False,
    "to_rows": 1,
    "from_rows": 1,
}


async def probe_one(
    session: aiohttp.ClientSession,
    slug: str,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """Try both iCIMS host conventions and return whichever responds."""
    async with semaphore:
        for host in (f"careers-{slug}.icims.com", f"{slug}.icims.com"):
            url = f"https://{host}/jobs/search"
            try:
                async with session.post(
                    url,
                    json=ICIMS_PROBE_PAYLOAD,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/html;q=0.9",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status in (200, 201, 202):
                        logger.info("VALID iCIMS: %s (HTTP %d)", host, resp.status)
                        return {
                            "slug": slug,
                            "host": host,
                            "url": f"https://{host}/jobs/search",
                            "career_page_url": f"https://{host}/jobs/intro",
                        }
                    if resp.status in (301, 302, 303):
                        # Some return 302 to a real careers page. Treat as live.
                        logger.info("LIVE iCIMS (redirect): %s (HTTP %d)", host, resp.status)
                        return {
                            "slug": slug,
                            "host": host,
                            "url": f"https://{host}/jobs/search",
                            "career_page_url": f"https://{host}/jobs/intro",
                        }
            except Exception as e:
                logger.debug("iCIMS probe %s failed: %s", host, str(e)[:60])

        await asyncio.sleep(0.2)
        return None


async def discover(slugs: list[str], concurrency: int = 10) -> list[dict]:
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
            # Accept either bare slug or full domain — normalize
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
                ats_platform="icims",
                career_page_url=v["career_page_url"],
            )
            session.add(employer)
            session.flush()

            source = SourceConfig(
                id=uuid.uuid4(),
                employer_id=employer.id,
                source_type="icims_portal",
                config={"board_token": slug, "employer_domain": domain},
                crawl_interval_hours=12,
            )
            session.add(source)
            created += 1
        session.commit()
    finally:
        session.close()

    logger.info("Created %d new iCIMS employer + source configs", created)


def main() -> None:
    test_only = "--test" in sys.argv

    slugs = load_slugs()
    logger.info("Probing %d slugs against iCIMS", len(slugs))

    valid = asyncio.run(discover(slugs))
    logger.info("iCIMS valid: %d / %d", len(valid), len(slugs))

    out = Path(__file__).parent.parent / "icims_discoveries.json"
    out.write_text(json.dumps(valid, indent=2))
    logger.info("Saved to %s", out)

    if not test_only and valid:
        save_to_db(valid)


if __name__ == "__main__":
    main()
