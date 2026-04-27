"""Import Shazamme's full LinkedIn-format XML feed into ZammeJobs.

Streams the 250 MB UTF-16 XML, parses each <job>, normalizes, and upserts.
Use this for the initial backfill; the Celery beat schedule should keep
it fresh after that.

Usage:
    python3 -m scripts.import_shazamme
    python3 -m scripts.import_shazamme --url https://other.example.com/feed.xml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.connectors.shazamme import DEFAULT_FEED_URL, ShazammeConnector
from src.models import Job
from src.normalizer.pipeline import normalize_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_shazamme")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=DEFAULT_FEED_URL, help="Override feed URL")
    args = p.parse_args()

    async with ShazammeConnector() as c:
        raw_jobs = await c.fetch_jobs(args.url, "")

    logger.info("Fetched %d raw jobs — normalizing + persisting", len(raw_jobs))

    engine = create_engine(settings.database_url_sync)
    Session = sessionmaker(bind=engine)

    new = upd = errs = 0
    new_urls: list[str] = []

    for raw in raw_jobs:
        try:
            job = await normalize_job(raw, do_geocode=False)
        except Exception as e:
            errs += 1
            logger.warning("Normalize failed: %s", str(e)[:150])
            continue

        with Session() as s:
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
                    set_={"title": job.title, "description_html": job.description_html,
                          "salary_raw": job.salary_raw, "date_updated": datetime.utcnow(),
                          "status": "active", "raw_data": job.raw_data},
                )
                result = s.execute(stmt)
                if result.inserted_primary_key:
                    new += 1
                    new_urls.append(f"https://{settings.site_domain}/jobs/{job.id}")
                else:
                    upd += 1
                s.commit()
            except Exception as e:
                errs += 1
                logger.warning("Upsert failed: %s", str(e)[:150])

        if (new + upd) % 1000 == 0 and (new + upd) > 0:
            logger.info("  progress: %d new + %d updated (%d errors)", new, upd, errs)

    logger.info("Shazamme import done: %d new, %d updated, %d errors", new, upd, errs)

    # Best-effort AI ping for new URLs
    if new_urls:
        try:
            from src.indexing.indexnow import submit_urls as indexnow_submit
            await indexnow_submit(new_urls[:10000])  # IndexNow batch cap
        except Exception as e:
            logger.warning("IndexNow dispatch failed: %s", str(e)[:120])


if __name__ == "__main__":
    asyncio.run(main())
