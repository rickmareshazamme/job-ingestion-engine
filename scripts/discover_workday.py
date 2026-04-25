"""Discover Workday career site instances.

Probes company names against Workday's URL pattern:
{company}.wd{1-5}.myworkdayjobs.com

Usage:
    python3 -m scripts.discover_workday
    python3 -m scripts.discover_workday --test
"""

import asyncio
import json
import logging
import sys
import uuid
from typing import Optional

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover.workday")

# Fortune 500 + major global employers (lowercase, no spaces)
COMPANY_SLUGS = [
    # Tech
    "microsoft", "amazon", "google", "apple", "meta", "netflix", "salesforce",
    "adobe", "cisco", "oracle", "ibm", "intel", "nvidia", "qualcomm", "amd",
    "servicenow", "workday", "vmware", "dell", "hp", "hpe",
    # Finance
    "jpmc", "jpmorgan", "goldmansachs", "morganstanley", "bankofamerica",
    "wellsfargo", "citigroup", "barclays", "hsbc", "ubs", "creditsuisse",
    "deutschebank", "bnpparibas", "societegenerale", "ing",
    "blackrock", "vanguard", "fidelity", "schwab", "statestreet",
    "visa", "mastercard", "americanexpress", "paypal",
    # Consulting / Professional Services
    "deloitte", "pwc", "ey", "kpmg", "accenture", "mckinsey",
    "bcg", "bain", "boozallen", "capgemini", "cognizant", "infosys",
    "wipro", "tcs", "hcl",
    # Healthcare / Pharma
    "unitedhealth", "cvs", "cigna", "anthem", "humana",
    "pfizer", "jnj", "merck", "abbvie", "amgen", "gilead",
    "bristol", "lilly", "novartis", "roche", "astrazeneca", "gsk",
    "sanofi", "bayer", "medtronic", "abbott", "baxter",
    # Retail / Consumer
    "walmart", "target", "costco", "kroger", "homedepot", "lowes",
    "nike", "starbucks", "mcdonalds", "cocacola", "pepsico",
    "pg", "unilever", "nestle", "loreal",
    # Industrial / Manufacturing
    "ge", "siemens", "honeywell", "3m", "caterpillar", "deere",
    "boeing", "airbus", "lockheed", "raytheon", "northrop", "gd",
    "ford", "gm", "toyota", "volkswagen", "bmw", "daimler",
    # Telecom / Media
    "att", "verizon", "tmobile", "comcast", "disney", "warner",
    # Energy
    "exxon", "chevron", "shell", "bp", "total", "conocophillips",
    # Other Fortune 500
    "ups", "fedex", "usps", "johnson", "procter", "colgate",
    "kraft", "mondelez", "generalmills", "kellogg",
]


async def probe_workday(
    session: aiohttp.ClientSession,
    company: str,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """Try all 5 Workday instances for a company."""
    async with semaphore:
        for instance in range(1, 6):
            url = f"https://{company}.wd{instance}.myworkdayjobs.com/wday/cxs/{company}/External/jobs"
            payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}

            try:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        total = data.get("total", 0)
                        if total > 0:
                            logger.info(
                                "FOUND: %s.wd%d (%d jobs)",
                                company, instance, total,
                            )
                            return {
                                "company": company,
                                "instance": instance,
                                "total_jobs": total,
                                "board_token": f"{company}|{instance}|External",
                                "url": f"https://{company}.wd{instance}.myworkdayjobs.com",
                            }
            except Exception:
                pass

            await asyncio.sleep(0.3)  # rate limit between probes

    return None


async def discover(slugs: list[str], concurrency: int = 5) -> list[dict]:
    """Probe all company slugs for Workday instances."""
    semaphore = asyncio.Semaphore(concurrency)
    valid = []

    async with aiohttp.ClientSession(
        headers={"User-Agent": "JobIndexBot/1.0 (+https://jobindex.ai/bot)"},
    ) as session:
        tasks = [probe_workday(session, slug, semaphore) for slug in slugs]
        results = await asyncio.gather(*tasks)
        valid = [r for r in results if r is not None]

    return valid


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
        domain = company + ".com"

        existing = session.query(Employer).filter_by(domain=domain).first()
        if existing:
            continue

        employer = Employer(
            id=uuid.uuid4(),
            name=company.title(),
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
    slugs = list(set(COMPANY_SLUGS))

    # Load from data file
    from pathlib import Path
    data_file = Path(__file__).parent.parent / "data" / "workday_slugs.txt"
    if data_file.exists():
        with open(data_file) as f:
            extra = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        slugs = list(set(slugs + extra))
        logger.info("Loaded %d slugs from data/workday_slugs.txt", len(extra))

    logger.info("Probing %d company slugs for Workday instances...", len(slugs))
    valid = asyncio.run(discover(slugs))
    logger.info("Found %d Workday instances out of %d probed", len(valid), len(slugs))

    total_jobs = sum(v["total_jobs"] for v in valid)
    logger.info("Total jobs across all Workday instances: %d", total_jobs)

    with open("workday_instances.json", "w") as f:
        json.dump(valid, f, indent=2)
    logger.info("Saved to workday_instances.json")

    if not test_only and valid:
        save_to_db(valid)


if __name__ == "__main__":
    main()
