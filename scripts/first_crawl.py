"""Run the first real crawl — populates the database with jobs.

Crawls all free, no-auth sources first (RemoteOK, Arbeitnow, The Muse),
then discovered Greenhouse boards, then confirmed Workday instances.

Usage:
    # Full crawl (all sources)
    python3 -m scripts.first_crawl

    # Quick crawl (free no-auth sources only — ~1,200 jobs in 30 seconds)
    python3 -m scripts.first_crawl --quick

    # Greenhouse only (132+ boards, ~30K-50K jobs)
    python3 -m scripts.first_crawl --greenhouse

    # Workday only (92 instances, ~104K jobs)
    python3 -m scripts.first_crawl --workday
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("first_crawl")


async def crawl_free_sources():
    """Crawl all free no-auth sources."""
    from src.connectors.arbeitnow import ArbeitnowConnector
    from src.connectors.remoteok import RemoteOKConnector
    from src.connectors.themuse import TheMuseConnector
    from src.normalizer.pipeline import normalize_job

    all_jobs = []

    # RemoteOK
    logger.info("=== RemoteOK ===")
    async with RemoteOKConnector() as c:
        jobs = await c.fetch_jobs()
        all_jobs.extend(jobs)
        logger.info("RemoteOK: %d jobs", len(jobs))

    # Arbeitnow
    logger.info("=== Arbeitnow ===")
    async with ArbeitnowConnector() as c:
        jobs = await c.fetch_jobs()
        all_jobs.extend(jobs)
        logger.info("Arbeitnow: %d jobs", len(jobs))

    # The Muse
    logger.info("=== The Muse ===")
    async with TheMuseConnector() as c:
        jobs = await c.fetch_jobs()
        all_jobs.extend(jobs)
        logger.info("The Muse: %d jobs", len(jobs))

    return all_jobs


async def crawl_greenhouse(max_boards: int = 50):
    """Crawl discovered Greenhouse boards."""
    from src.connectors.greenhouse import GreenhouseConnector

    boards_file = Path("greenhouse_boards.json")
    if not boards_file.exists():
        logger.warning("No greenhouse_boards.json found. Run discover_greenhouse first.")
        return []

    with open(boards_file) as f:
        boards = json.load(f)

    all_jobs = []
    async with GreenhouseConnector() as c:
        for i, board in enumerate(boards[:max_boards]):
            token = board["token"]
            logger.info("=== Greenhouse %d/%d: %s ===", i + 1, min(len(boards), max_boards), token)
            try:
                jobs = await c.fetch_jobs(token, f"{token}.com")
                all_jobs.extend(jobs)
                logger.info("  %s: %d jobs", token, len(jobs))
            except Exception as e:
                logger.warning("  %s: FAILED: %s", token, str(e)[:100])

    return all_jobs


async def crawl_workday(max_instances: int = 30):
    """Crawl confirmed Workday instances."""
    from src.connectors.workday import WorkdayConnector

    results_file = Path("workday_confirmed_results.json")
    if not results_file.exists():
        logger.warning("No workday_confirmed_results.json found. Run discover_workday_confirmed first.")
        return []

    with open(results_file) as f:
        instances = json.load(f)

    all_jobs = []
    async with WorkdayConnector() as c:
        for i, inst in enumerate(instances[:max_instances]):
            board_token = inst["board_token"]
            company = inst["company"]
            logger.info("=== Workday %d/%d: %s (%d listed) ===", i + 1, min(len(instances), max_instances), company, inst["total_jobs"])
            try:
                jobs = await c.fetch_jobs(board_token, f"{company}.com")
                all_jobs.extend(jobs)
                logger.info("  %s: %d jobs fetched", company, len(jobs))
            except Exception as e:
                logger.warning("  %s: FAILED: %s", company, str(e)[:100])

    return all_jobs


async def normalize_and_count(raw_jobs):
    """Normalize all jobs, persist to DB via upsert, then print summary."""
    from datetime import datetime
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.orm import sessionmaker
    from src.config import settings
    from src.models import Job
    from src.normalizer.pipeline import normalize_job

    normalized = []
    for raw in raw_jobs:
        try:
            job = await normalize_job(raw, do_geocode=False)
            normalized.append(job)
        except Exception:
            pass

    # Persist to DB via upsert on (source_type, source_id)
    if normalized:
        engine = create_engine(settings.database_url_sync)
        SessionLocal = sessionmaker(bind=engine)
        new_count = 0
        with SessionLocal() as session:
            for job in normalized:
                try:
                    stmt = insert(Job).values(
                        id=job.id, content_hash=job.content_hash,
                        source_type=job.source_type, source_id=job.source_id,
                        source_url=job.source_url, ats_platform=job.ats_platform,
                        title=job.title, description_html=job.description_html,
                        description_text=job.description_text,
                        employer_name=job.employer_name, employer_domain=job.employer_domain,
                        employer_logo_url=job.employer_logo_url,
                        location_raw=job.location_raw, location_city=job.location_city,
                        location_state=job.location_state, location_country=job.location_country,
                        location_lat=job.location_lat, location_lng=job.location_lng,
                        is_remote=job.is_remote, remote_type=job.remote_type,
                        salary_min=job.salary_min, salary_max=job.salary_max,
                        salary_currency=job.salary_currency, salary_period=job.salary_period,
                        salary_raw=job.salary_raw, employment_type=job.employment_type,
                        categories=job.categories, seniority=job.seniority,
                        date_posted=job.date_posted, date_expires=job.date_expires,
                        date_crawled=job.date_crawled, date_updated=job.date_updated,
                        status=job.status, raw_data=job.raw_data,
                    ).on_conflict_do_update(
                        constraint="uq_source",
                        set_={
                            "title": job.title,
                            "description_html": job.description_html,
                            "description_text": job.description_text,
                            "location_raw": job.location_raw,
                            "salary_raw": job.salary_raw,
                            "date_updated": datetime.utcnow(),
                            "status": "active",
                            "raw_data": job.raw_data,
                        },
                    )
                    session.execute(stmt)
                    new_count += 1
                except Exception as e:
                    logger.warning("Upsert failed: %s", str(e)[:120])
            session.commit()
        logger.info("Persisted %d jobs to DB", new_count)

    # Summary
    countries = {}
    ats_platforms = {}
    for job in normalized:
        c = job.location_country or "Unknown"
        countries[c] = countries.get(c, 0) + 1
        a = job.ats_platform or "unknown"
        ats_platforms[a] = ats_platforms.get(a, 0) + 1

    logger.info("\n=== CRAWL SUMMARY ===")
    logger.info("Total jobs: %d", len(normalized))
    logger.info("\nBy ATS platform:")
    for ats, count in sorted(ats_platforms.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", ats, count)
    logger.info("\nTop countries:")
    for country, count in sorted(countries.items(), key=lambda x: -x[1])[:15]:
        logger.info("  %s: %d", country, count)

    return normalized


def _arg_int(flag: str, default: int) -> int:
    for a in sys.argv:
        if a.startswith(flag + "="):
            try:
                return int(a.split("=", 1)[1])
            except ValueError:
                return default
    return default


async def main():
    quick = "--quick" in sys.argv
    greenhouse_only = "--greenhouse" in sys.argv
    workday_only = "--workday" in sys.argv
    full = "--full" in sys.argv
    gh_max = _arg_int("--gh-max", 0)  # 0 = no limit (all seeded boards)
    wd_max = _arg_int("--wd-max", 0)

    all_raw = []

    if quick:
        logger.info("Quick crawl — free sources only")
        all_raw = await crawl_free_sources()
    elif greenhouse_only:
        n = gh_max or 10_000
        logger.info("Greenhouse crawl (max %d boards)", n)
        all_raw = await crawl_greenhouse(max_boards=n)
    elif workday_only:
        n = wd_max or 10_000
        logger.info("Workday crawl (max %d instances)", n)
        all_raw = await crawl_workday(max_instances=n)
    elif full:
        gh_n = gh_max or 10_000
        wd_n = wd_max or 10_000
        logger.info("FULL crawl — free + Greenhouse(%d) + Workday(%d)", gh_n, wd_n)
        all_raw.extend(await crawl_free_sources())
        all_raw.extend(await crawl_greenhouse(max_boards=gh_n))
        all_raw.extend(await crawl_workday(max_instances=wd_n))
    else:
        # Conservative default for first-run smoke testing
        logger.info("Default crawl — free + Greenhouse(50) + Workday(20). Use --full for everything.")
        all_raw.extend(await crawl_free_sources())
        all_raw.extend(await crawl_greenhouse(max_boards=gh_max or 50))
        all_raw.extend(await crawl_workday(max_instances=wd_max or 20))

    logger.info("\nTotal raw jobs fetched: %d", len(all_raw))
    await normalize_and_count(all_raw)


if __name__ == "__main__":
    asyncio.run(main())
