"""Seed initial employers and source configurations.

Usage:
    python -m scripts.seed_employers

Seeds known Greenhouse and Lever boards + a few Workday employers.
"""

import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.models import Employer, SourceConfig

# Known public Greenhouse boards (company: domain)
GREENHOUSE_BOARDS = {
    "airbnb": "airbnb.com",
    "stripe": "stripe.com",
    "figma": "figma.com",
    "notion": "notion.so",
    "discord": "discord.com",
    "reddit": "reddit.com",
    "coinbase": "coinbase.com",
    "brex": "brex.com",
    "flexport": "flexport.com",
    "plaid": "plaid.com",
    "airtable": "airtable.com",
    "postman": "postman.com",
    "hashicorp": "hashicorp.com",
    "datadog": "datadoghq.com",
    "mongodb": "mongodb.com",
    "cloudflare": "cloudflare.com",
    "twitch": "twitch.tv",
    "spotify": "spotify.com",
    "canva": "canva.com",
    "atlassian": "atlassian.com",
}

# Known public Lever boards
LEVER_BOARDS = {
    "netflix": "netflix.com",
    "twilio": "twilio.com",
    "lever": "lever.co",
    "github": "github.com",
    "shopify": "shopify.com",
    "robinhood": "robinhood.com",
    "affirm": "affirm.com",
    "gitlab": "gitlab.com",
    "zapier": "zapier.com",
    "ramp": "ramp.com",
}

# Known Workday employers (company|instance|site)
WORKDAY_EMPLOYERS = {
    "microsoft|5|External": "microsoft.com",
    "amazon|5|External": "amazon.com",
    "google|5|External": "google.com",
    "salesforce|5|External": "salesforce.com",
    "adobe|5|External": "adobe.com",
    "cisco|5|External": "cisco.com",
    "oracle|5|External": "oracle.com",
    "jpmc|5|External": "jpmorgan.com",
    "goldmansachs|5|External": "goldmansachs.com",
    "deloitte|5|External": "deloitte.com",
}


def seed():
    engine = create_engine(settings.database_url_sync)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        total = 0

        # Greenhouse
        for board_token, domain in GREENHOUSE_BOARDS.items():
            employer = _get_or_create_employer(
                session, board_token.title(), domain, "greenhouse",
                f"https://boards.greenhouse.io/{board_token}"
            )
            _get_or_create_source(
                session, employer.id, "greenhouse_api",
                {"board_token": board_token, "employer_domain": domain},
                crawl_interval_hours=6,
            )
            total += 1

        # Lever
        for board_token, domain in LEVER_BOARDS.items():
            employer = _get_or_create_employer(
                session, board_token.title(), domain, "lever",
                f"https://jobs.lever.co/{board_token}"
            )
            _get_or_create_source(
                session, employer.id, "lever_api",
                {"board_token": board_token, "employer_domain": domain},
                crawl_interval_hours=6,
            )
            total += 1

        # Workday
        for board_token, domain in WORKDAY_EMPLOYERS.items():
            company = board_token.split("|")[0]
            instance = board_token.split("|")[1]
            employer = _get_or_create_employer(
                session, company.title(), domain, "workday",
                f"https://{company}.wd{instance}.myworkdayjobs.com"
            )
            _get_or_create_source(
                session, employer.id, "workday_feed",
                {"board_token": board_token, "employer_domain": domain},
                crawl_interval_hours=12,
            )
            total += 1

        session.commit()
        print(f"Seeded {total} employers with source configs.")


def _get_or_create_employer(
    session, name: str, domain: str, ats_platform: str, career_page_url: str
) -> Employer:
    existing = session.query(Employer).filter_by(domain=domain).first()
    if existing:
        return existing

    employer = Employer(
        id=uuid.uuid4(),
        name=name,
        domain=domain,
        ats_platform=ats_platform,
        career_page_url=career_page_url,
    )
    session.add(employer)
    session.flush()
    return employer


def _get_or_create_source(
    session, employer_id, source_type: str, config: dict, crawl_interval_hours: int
) -> SourceConfig:
    existing = session.query(SourceConfig).filter_by(
        employer_id=employer_id, source_type=source_type
    ).first()
    if existing:
        return existing

    source = SourceConfig(
        id=uuid.uuid4(),
        employer_id=employer_id,
        source_type=source_type,
        config=config,
        crawl_interval_hours=crawl_interval_hours,
    )
    session.add(source)
    session.flush()
    return source


if __name__ == "__main__":
    seed()
