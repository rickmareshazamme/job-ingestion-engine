"""Run a single crawl for testing.

Usage:
    python -m scripts.run_single_crawl greenhouse airbnb airbnb.com
    python -m scripts.run_single_crawl lever netflix netflix.com
    python -m scripts.run_single_crawl workday "microsoft|5|External" microsoft.com
"""

import asyncio
import json
import sys

from src.connectors.greenhouse import GreenhouseConnector
from src.connectors.lever import LeverConnector
from src.connectors.workday import WorkdayConnector
from src.normalizer.pipeline import normalize_job

CONNECTORS = {
    "greenhouse": GreenhouseConnector,
    "lever": LeverConnector,
    "workday": WorkdayConnector,
}


async def main(connector_name: str, board_token: str, employer_domain: str):
    connector_cls = CONNECTORS.get(connector_name)
    if not connector_cls:
        print(f"Unknown connector: {connector_name}")
        print(f"Available: {', '.join(CONNECTORS.keys())}")
        sys.exit(1)

    print(f"Crawling {connector_name} board: {board_token} ({employer_domain})")

    async with connector_cls() as connector:
        raw_jobs = await connector.fetch_jobs(board_token, employer_domain)

    print(f"Found {len(raw_jobs)} raw jobs")

    for i, raw in enumerate(raw_jobs[:5]):
        job = await normalize_job(raw, do_geocode=False)
        print(f"\n--- Job {i + 1} ---")
        print(f"  Title: {job.title}")
        print(f"  Location: {job.location_raw} -> {job.location_city}, {job.location_state}, {job.location_country}")
        print(f"  Remote: {job.is_remote} ({job.remote_type})")
        print(f"  Salary: {job.salary_raw} -> {job.salary_min}-{job.salary_max} {job.salary_currency}/{job.salary_period}")
        print(f"  Type: {job.employment_type}")
        print(f"  Seniority: {job.seniority}")
        print(f"  Categories: {job.categories}")
        print(f"  Source URL: {job.source_url}")

    if len(raw_jobs) > 5:
        print(f"\n... and {len(raw_jobs) - 5} more jobs")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python -m scripts.run_single_crawl <connector> <board_token> <employer_domain>")
        print("Example: python -m scripts.run_single_crawl greenhouse airbnb airbnb.com")
        sys.exit(1)

    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
