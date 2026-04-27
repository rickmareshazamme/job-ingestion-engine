"""Discover SAP SuccessFactors career sites.

Probes Fortune 2000 domains against SAP's URL convention:
    {slug}.successfactors.com/sitemal.xml   (the famous SAP typo)
    {slug}.successfactors.com/sitemap.xml   (modern variant)

For each subdomain that returns a valid sitemap, INSERT an Employer +
SourceConfig row using the same shape as scripts.discover_workday_confirmed.

Input: data/fortune2000_domains.txt — one company-slug per line.
If absent, falls back to a hardcoded sample of 50 known SF customers.

Usage:
    python3 -m scripts.discover_successfactors
    python3 -m scripts.discover_successfactors --test
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
logger = logging.getLogger("discover.successfactors")


# Known SuccessFactors-using companies (sample if no input file).
SAMPLE_SLUGS = [
    # Industrial / Manufacturing
    "siemens", "bosch", "abb", "schneider", "thyssenkrupp",
    "saint-gobain", "saintgobain", "henkel", "basf", "bayer",
    # Pharma
    "novartis", "roche", "boehringer", "bayer", "sanofi", "gsk",
    # Consumer
    "nestle", "unilever", "loreal", "danone", "philipmorris", "altria",
    # Tech / Telco
    "sap", "siemens-energy", "ericsson", "vodafone", "deutschetelekom",
    # Energy
    "shell", "totalenergies", "bp", "eni", "equinor", "rwe", "engie",
    # Consulting / Outsourcing
    "accenture", "capgemini", "infosys", "wipro", "tcs", "cognizant",
    "atos", "dxc",
    # Auto
    "vw", "volkswagen", "bmw", "daimler", "stellantis", "renault",
    # Aerospace
    "airbus", "thales", "leonardo",
    # Logistics
    "dhl", "kuehnenagel", "maersk",
    # Other
    "olympus", "honeywell", "emerson",
]


async def probe_one(
    session: aiohttp.ClientSession,
    slug: str,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """Try {slug}.successfactors.com sitemap variants."""
    async with semaphore:
        host = f"{slug}.successfactors.com"
        for path in ("/sitemal.xml", "/sitemap.xml", "/sitemap_1.xml"):
            url = f"https://{host}{path}"
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    if "<urlset" in text or "<sitemapindex" in text:
                        # Cheap quality check: count <loc> tags
                        loc_count = text.count("<loc>")
                        logger.info(
                            "VALID SuccessFactors: %s%s (~%d locs)",
                            host, path, loc_count,
                        )
                        return {
                            "slug": slug,
                            "host": host,
                            "sitemap_url": url,
                            "loc_count": loc_count,
                            "career_page_url": f"https://{host}/career",
                        }
            except Exception as e:
                logger.debug("SF probe %s%s failed: %s", host, path, str(e)[:60])

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
                ats_platform="successfactors",
                career_page_url=v["career_page_url"],
            )
            session.add(employer)
            session.flush()

            source = SourceConfig(
                id=uuid.uuid4(),
                employer_id=employer.id,
                source_type="successfactors_sitemap",
                config={"board_token": slug, "employer_domain": domain},
                crawl_interval_hours=12,
            )
            session.add(source)
            created += 1
        session.commit()
    finally:
        session.close()

    logger.info("Created %d new SuccessFactors employer + source configs", created)


def main() -> None:
    test_only = "--test" in sys.argv
    slugs = load_slugs()
    logger.info("Probing %d slugs against SuccessFactors", len(slugs))

    valid = asyncio.run(discover(slugs))
    logger.info("SuccessFactors valid: %d / %d", len(valid), len(slugs))

    out = Path(__file__).parent.parent / "successfactors_discoveries.json"
    out.write_text(json.dumps(valid, indent=2))
    logger.info("Saved to %s", out)

    if not test_only and valid:
        save_to_db(valid)


if __name__ == "__main__":
    main()
