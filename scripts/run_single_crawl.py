"""Run a single crawl for testing.

Usage:
    # ATS connectors
    python3 -m scripts.run_single_crawl greenhouse airbnb airbnb.com
    python3 -m scripts.run_single_crawl lever netflix netflix.com
    python3 -m scripts.run_single_crawl workday "microsoft|5|External" microsoft.com
    python3 -m scripts.run_single_crawl ashby company company.com
    python3 -m scripts.run_single_crawl workable company company.com

    # Aggregator connectors (no board_token/domain needed)
    python3 -m scripts.run_single_crawl remoteok
    python3 -m scripts.run_single_crawl arbeitnow
    python3 -m scripts.run_single_crawl themuse
    python3 -m scripts.run_single_crawl adzuna us        # country code as board_token
    python3 -m scripts.run_single_crawl usajobs           # needs USAJOBS_API_KEY
    python3 -m scripts.run_single_crawl reed              # needs REED_API_KEY
"""

import asyncio
import sys

from src.connectors.adzuna import AdzunaConnector
from src.connectors.arbeitnow import ArbeitnowConnector
from src.connectors.ashby import AshbyConnector
from src.connectors.careerjet import CareerjetConnector
from src.connectors.greenhouse import GreenhouseConnector
from src.connectors.jooble import JoobleConnector
from src.connectors.lever import LeverConnector
from src.connectors.personio import PersonioConnector
from src.connectors.recruitee import RecruiteeConnector
from src.connectors.reed import ReedConnector
from src.connectors.remoteok import RemoteOKConnector
from src.connectors.smartrecruiters import SmartRecruitersConnector
from src.connectors.themuse import TheMuseConnector
from src.connectors.usajobs import USAJobsConnector
from src.connectors.workable import WorkableConnector
from src.connectors.workday import WorkdayConnector
from src.normalizer.pipeline import normalize_job

CONNECTORS = {
    # ATS
    "greenhouse": GreenhouseConnector,
    "lever": LeverConnector,
    "workday": WorkdayConnector,
    "ashby": AshbyConnector,
    "workable": WorkableConnector,
    "smartrecruiters": SmartRecruitersConnector,
    "recruitee": RecruiteeConnector,
    "personio": PersonioConnector,
    # Aggregators
    "adzuna": AdzunaConnector,
    "remoteok": RemoteOKConnector,
    "arbeitnow": ArbeitnowConnector,
    "themuse": TheMuseConnector,
    "usajobs": USAJobsConnector,
    "reed": ReedConnector,
    "jooble": JoobleConnector,
    "careerjet": CareerjetConnector,
}


async def main(connector_name: str, board_token: str = "", employer_domain: str = ""):
    connector_cls = CONNECTORS.get(connector_name)
    if not connector_cls:
        print(f"Unknown connector: {connector_name}")
        print(f"Available: {', '.join(sorted(CONNECTORS.keys()))}")
        sys.exit(1)

    print(f"Crawling {connector_name}" + (f" board: {board_token}" if board_token else ""))

    async with connector_cls() as connector:
        raw_jobs = await connector.fetch_jobs(board_token, employer_domain)

    print(f"Found {len(raw_jobs)} raw jobs")

    for i, raw in enumerate(raw_jobs[:10]):
        job = await normalize_job(raw, do_geocode=False)
        print(f"\n--- Job {i + 1} ---")
        print(f"  Title: {job.title}")
        print(f"  Employer: {job.employer_name}")
        print(f"  Location: {job.location_raw} -> {job.location_city}, {job.location_state}, {job.location_country}")
        print(f"  Remote: {job.is_remote} ({job.remote_type})")
        print(f"  Salary: {job.salary_raw} -> {job.salary_min}-{job.salary_max} {job.salary_currency}/{job.salary_period}")
        print(f"  Type: {job.employment_type}")
        print(f"  Seniority: {job.seniority}")
        print(f"  Categories: {job.categories}")
        print(f"  Source URL: {job.source_url}")

    if len(raw_jobs) > 10:
        print(f"\n... and {len(raw_jobs) - 10} more jobs")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m scripts.run_single_crawl <connector> [board_token] [employer_domain]")
        print(f"Connectors: {', '.join(sorted(CONNECTORS.keys()))}")
        sys.exit(1)

    connector = sys.argv[1]
    token = sys.argv[2] if len(sys.argv) > 2 else ""
    domain = sys.argv[3] if len(sys.argv) > 3 else ""

    asyncio.run(main(connector, token, domain))
