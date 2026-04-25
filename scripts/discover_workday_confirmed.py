"""Load confirmed Workday career sites and validate them.

Unlike discover_workday.py which probes blindly, this script uses
CONFIRMED slug|instance|site combinations from web research.

Usage:
    python3 -m scripts.discover_workday_confirmed
    python3 -m scripts.discover_workday_confirmed --test
"""

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover.workday.confirmed")


async def validate_instance(
    session: aiohttp.ClientSession,
    slug: str,
    instance: str,
    site: str,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """Validate a confirmed Workday instance and get job count."""
    async with semaphore:
        url = f"https://{slug}.wd{instance}.myworkdayjobs.com/wday/cxs/{slug}/{site}/jobs"
        payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}

        try:
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    total = data.get("total", 0)
                    logger.info("VALID: %s.wd%s/%s (%d jobs)", slug, instance, site, total)
                    return {
                        "company": slug,
                        "instance": int(instance),
                        "site": site,
                        "total_jobs": total,
                        "board_token": f"{slug}|{instance}|{site}",
                        "url": f"https://{slug}.wd{instance}.myworkdayjobs.com",
                    }
                else:
                    logger.debug("Failed: %s.wd%s/%s (HTTP %d)", slug, instance, site, resp.status)
        except Exception as e:
            logger.debug("Error: %s.wd%s/%s: %s", slug, instance, site, str(e)[:50])

        await asyncio.sleep(0.5)
        return None


async def discover(entries: list[tuple[str, str, str]], concurrency: int = 10) -> list[dict]:
    """Validate all confirmed entries concurrently."""
    semaphore = asyncio.Semaphore(concurrency)
    valid = []

    async with aiohttp.ClientSession(
        headers={"User-Agent": "JobIndexBot/1.0 (+https://jobindex.ai/bot)"},
    ) as session:
        tasks = [validate_instance(session, slug, inst, site, semaphore) for slug, inst, site in entries]
        results = await asyncio.gather(*tasks)
        valid = [r for r in results if r is not None]

    return valid


def load_confirmed_entries() -> list[tuple[str, str, str]]:
    """Load confirmed Workday entries from data file."""
    data_file = Path(__file__).parent.parent / "data" / "workday_confirmed.txt"
    entries = []

    if data_file.exists():
        with open(data_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                if len(parts) == 3:
                    entries.append((parts[0], parts[1], parts[2]))

    return entries


def save_to_db(valid_instances: list[dict]):
    """Save discovered Workday instances to database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.config import settings
    from src.models import Employer, SourceConfig

    engine = create_engine(settings.database_url_sync)
    Session = sessionmaker(bind=engine)
    session = Session()

    created = 0
    for inst in valid_instances:
        company = inst["company"]
        # Use the slug as domain since Workday slugs are often abbreviations
        domain = company + ".com"

        existing = session.query(Employer).filter_by(domain=domain).first()
        if existing:
            # Update source config if it has wrong board_token
            continue

        employer = Employer(
            id=uuid.uuid4(),
            name=company.upper() if len(company) <= 4 else company.title(),
            domain=domain,
            ats_platform="workday",
            career_page_url=inst["url"],
        )
        session.add(employer)
        session.flush()

        source = SourceConfig(
            id=uuid.uuid4(),
            employer_id=employer.id,
            source_type="workday_feed",
            config={"board_token": inst["board_token"], "employer_domain": domain},
            crawl_interval_hours=12,
        )
        session.add(source)
        created += 1

    session.commit()
    session.close()
    logger.info("Created %d new Workday employer + source configs", created)


def main():
    test_only = "--test" in sys.argv

    entries = load_confirmed_entries()
    logger.info("Loaded %d confirmed Workday entries", len(entries))

    valid = asyncio.run(discover(entries))

    total_jobs = sum(v["total_jobs"] for v in valid)
    logger.info("Validated %d / %d entries. Total jobs: %d", len(valid), len(entries), total_jobs)

    # Sort by job count
    valid.sort(key=lambda x: x["total_jobs"], reverse=True)

    with open("workday_confirmed_results.json", "w") as f:
        json.dump(valid, f, indent=2)
    logger.info("Saved to workday_confirmed_results.json")

    # Print top employers
    logger.info("\nTop employers by job count:")
    for v in valid[:20]:
        logger.info("  %s.wd%d/%s: %d jobs", v["company"], v["instance"], v["site"], v["total_jobs"])

    if not test_only and valid:
        save_to_db(valid)


if __name__ == "__main__":
    main()
