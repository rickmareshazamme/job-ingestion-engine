"""Discover Greenhouse board tokens at scale.

Validates board tokens by hitting the Greenhouse API and auto-creates
Employer + SourceConfig records for valid boards.

Usage:
    python3 -m scripts.discover_greenhouse
    python3 -m scripts.discover_greenhouse --file boards.txt
    python3 -m scripts.discover_greenhouse --test  # just validate, don't save
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
logger = logging.getLogger("discover.greenhouse")

# Known Greenhouse board tokens from the tech ecosystem
# These are public URL slugs — e.g., boards.greenhouse.io/{token}
KNOWN_BOARDS = [
    # Tech giants
    "airbnb", "stripe", "figma", "notion", "discord", "reddit", "coinbase",
    "brex", "flexport", "plaid", "airtable", "postman", "hashicorp",
    "datadog", "mongodb", "cloudflare", "twitch", "spotify", "canva",
    "atlassian", "databricks", "snowflake", "docusign", "okta",
    "pagerduty", "twilio", "elastic", "confluent", "zscaler",
    # Fintech
    "square", "robinhood", "chime", "sofi", "affirm", "checkout",
    "marqeta", "ramp", "mercury", "moderntreasury", "column",
    # SaaS / Enterprise
    "hubspot", "zendesk", "asana", "notion", "linear", "vercel",
    "supabase", "netlify", "grafana", "dbt", "fivetran", "airbyte",
    "temporal", "pulumi", "launchdarkly", "harness", "codefresh",
    # AI/ML
    "openai", "anthropic", "deepmind", "stability", "cohere",
    "mistral", "anyscale", "weights-and-biases", "huggingface",
    "scale", "labelbox", "snorkel", "determined",
    # Security
    "crowdstrike", "sentinelone", "snyk", "lacework", "orca",
    "wiz", "semgrep", "chainguard", "tailscale",
    # Gaming / Media
    "riotgames", "epicgames", "unity", "niantic", "nianticlabs",
    "bethesda", "blizzard", "ea", "zynga",
    # Health / Bio
    "tempus", "flatiron", "veracyte", "guardanthealth", "color",
    "devoted", "noom", "hims", "cerebral", "ro",
    # E-commerce / Consumer
    "doordash", "instacart", "gopuff", "faire", "glossier",
    "warbyparker", "allbirds", "casper", "peloton", "rivian",
    # Infrastructure
    "cockroachlabs", "timescale", "planetscale", "neon", "turso",
    "fly", "render", "railway", "replit", "gitpod",
    # Other well-known tech companies
    "palantir", "anduril", "relativity", "astranis", "hadrian",
    "jobyaviation", "archer", "boom", "relativityspace",
    "duolingo", "coursera", "masterclass", "substack", "medium",
    "zapier", "calendly", "loom", "miro", "figma",
]


async def validate_board(session: aiohttp.ClientSession, token: str) -> Optional[dict]:
    """Check if a Greenhouse board token is valid and return company info."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {
                    "token": token,
                    "name": data.get("name", token),
                    "url": f"https://boards.greenhouse.io/{token}",
                }
            return None
    except Exception:
        return None


async def discover(tokens: list[str], concurrency: int = 10) -> list[dict]:
    """Validate a list of board tokens concurrently."""
    semaphore = asyncio.Semaphore(concurrency)
    valid = []

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=10),
        headers={"User-Agent": "ZammeJobsBot/1.0 (+https://zammejobs.com/bot)"},
    ) as session:

        async def check(token):
            async with semaphore:
                await asyncio.sleep(0.2)  # rate limit
                result = await validate_board(session, token)
                if result:
                    valid.append(result)
                    logger.info("VALID: %s (%s)", token, result["name"])
                else:
                    logger.debug("invalid: %s", token)

        tasks = [check(t) for t in tokens]
        await asyncio.gather(*tasks)

    return valid


def save_to_db(valid_boards: list[dict]):
    """Save discovered boards to the database as Employers + SourceConfigs."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.config import settings
    from src.models import Employer, SourceConfig

    engine = create_engine(settings.database_url_sync)
    Session = sessionmaker(bind=engine)
    session = Session()

    created = 0
    for board in valid_boards:
        token = board["token"]
        domain = token + ".com"  # best guess, will be refined

        existing = session.query(Employer).filter_by(domain=domain).first()
        if existing:
            continue

        employer = Employer(
            id=uuid.uuid4(),
            name=board["name"],
            domain=domain,
            ats_platform="greenhouse",
            career_page_url=board["url"],
        )
        session.add(employer)
        session.flush()

        source = SourceConfig(
            id=uuid.uuid4(),
            employer_id=employer.id,
            source_type="greenhouse_api",
            config={"board_token": token, "employer_domain": domain},
            crawl_interval_hours=6,
        )
        session.add(source)
        created += 1

    session.commit()
    session.close()
    logger.info("Created %d new employer + source configs", created)


def main():
    test_only = "--test" in sys.argv
    file_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == "--file" and i + 1 < len(sys.argv):
            file_arg = sys.argv[i + 1]

    tokens = list(set(KNOWN_BOARDS))

    # Always load from data file if it exists
    data_file = Path(__file__).parent.parent / "data" / "greenhouse_tokens.txt"
    if data_file.exists():
        with open(data_file) as f:
            extra = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        tokens = list(set(tokens + extra))
        logger.info("Loaded %d tokens from data/greenhouse_tokens.txt", len(extra))

    if file_arg:
        path = Path(file_arg)
        if path.exists():
            with open(path) as f:
                extra = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            tokens = list(set(tokens + extra))
            logger.info("Loaded %d extra tokens from %s", len(extra), file_arg)

    logger.info("Validating %d Greenhouse board tokens...", len(tokens))
    valid = asyncio.run(discover(tokens))
    logger.info("Found %d valid boards out of %d checked", len(valid), len(tokens))

    # Save results to JSON
    with open("greenhouse_boards.json", "w") as f:
        json.dump(valid, f, indent=2)
    logger.info("Saved to greenhouse_boards.json")

    if not test_only and valid:
        save_to_db(valid)


if __name__ == "__main__":
    main()
