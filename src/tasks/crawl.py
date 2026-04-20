"""Celery tasks for crawling, normalization, and cleanup."""

import asyncio
import uuid
from datetime import datetime, timedelta

from celery import Celery
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.config import settings
from src.connectors.base import RawJob
from src.connectors.greenhouse import GreenhouseConnector
from src.connectors.lever import LeverConnector
from src.connectors.workday import WorkdayConnector
from src.models import CrawlRun, Job, SourceConfig
from src.normalizer.pipeline import normalize_job

celery_app = Celery("job_ingestion", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=300,
    task_time_limit=600,
)

CONNECTOR_MAP = {
    "greenhouse_api": GreenhouseConnector,
    "lever_api": LeverConnector,
    "workday_feed": WorkdayConnector,
}


def _run_async(coro):
    """Run an async function from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def crawl_source(self, source_config_id: str):
    """Crawl a single source configuration and store results."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.database_url_sync)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        config = session.get(SourceConfig, uuid.UUID(source_config_id))
        if not config or not config.is_active:
            return {"status": "skipped", "reason": "inactive or not found"}

        crawl_run = CrawlRun(
            id=uuid.uuid4(),
            source_config_id=config.id,
            status="running",
        )
        session.add(crawl_run)
        session.commit()

        start_time = datetime.utcnow()

        try:
            # Fetch jobs from source
            connector_cls = CONNECTOR_MAP.get(config.source_type)
            if not connector_cls:
                raise ValueError(f"Unknown source type: {config.source_type}")

            board_token = config.config.get("board_token", "")
            employer_domain = config.config.get("employer_domain", "")

            raw_jobs = _run_async(_fetch_with_connector(connector_cls, board_token, employer_domain))

            # Normalize and upsert
            jobs_new = 0
            jobs_updated = 0

            for raw_job in raw_jobs:
                job = _run_async(normalize_job(raw_job, do_geocode=False))

                # Upsert: insert or update on (source_type, source_id) conflict
                stmt = insert(Job).values(
                    id=job.id,
                    content_hash=job.content_hash,
                    source_type=job.source_type,
                    source_id=job.source_id,
                    source_url=job.source_url,
                    ats_platform=job.ats_platform,
                    title=job.title,
                    description_html=job.description_html,
                    description_text=job.description_text,
                    employer_name=job.employer_name,
                    employer_domain=job.employer_domain,
                    employer_logo_url=job.employer_logo_url,
                    location_raw=job.location_raw,
                    location_city=job.location_city,
                    location_state=job.location_state,
                    location_country=job.location_country,
                    location_lat=job.location_lat,
                    location_lng=job.location_lng,
                    is_remote=job.is_remote,
                    remote_type=job.remote_type,
                    salary_min=job.salary_min,
                    salary_max=job.salary_max,
                    salary_currency=job.salary_currency,
                    salary_period=job.salary_period,
                    salary_raw=job.salary_raw,
                    employment_type=job.employment_type,
                    categories=job.categories,
                    seniority=job.seniority,
                    date_posted=job.date_posted,
                    date_expires=job.date_expires,
                    date_crawled=job.date_crawled,
                    date_updated=job.date_updated,
                    status=job.status,
                    raw_data=job.raw_data,
                ).on_conflict_do_update(
                    constraint="uq_source",
                    set_={
                        "title": job.title,
                        "description_html": job.description_html,
                        "description_text": job.description_text,
                        "location_raw": job.location_raw,
                        "location_city": job.location_city,
                        "location_state": job.location_state,
                        "location_country": job.location_country,
                        "salary_raw": job.salary_raw,
                        "salary_min": job.salary_min,
                        "salary_max": job.salary_max,
                        "date_updated": datetime.utcnow(),
                        "status": "active",
                        "raw_data": job.raw_data,
                    },
                )

                result = session.execute(stmt)
                if result.inserted_primary_key:
                    jobs_new += 1
                else:
                    jobs_updated += 1

            session.commit()

            # Update crawl run
            duration = (datetime.utcnow() - start_time).total_seconds()
            crawl_run.status = "success"
            crawl_run.completed_at = datetime.utcnow()
            crawl_run.jobs_found = len(raw_jobs)
            crawl_run.jobs_new = jobs_new
            crawl_run.jobs_updated = jobs_updated
            crawl_run.duration_seconds = duration

            # Update source config
            config.last_crawl_at = datetime.utcnow()
            config.last_crawl_status = "success"
            config.last_crawl_job_count = len(raw_jobs)

            session.commit()

            return {
                "status": "success",
                "jobs_found": len(raw_jobs),
                "jobs_new": jobs_new,
                "jobs_updated": jobs_updated,
                "duration_seconds": duration,
            }

        except Exception as e:
            crawl_run.status = "failed"
            crawl_run.completed_at = datetime.utcnow()
            crawl_run.error_message = str(e)[:500]
            crawl_run.duration_seconds = (datetime.utcnow() - start_time).total_seconds()

            config.last_crawl_at = datetime.utcnow()
            config.last_crawl_status = "failed"

            session.commit()

            raise self.retry(exc=e)


async def _fetch_with_connector(connector_cls, board_token: str, employer_domain: str) -> list[RawJob]:
    """Async helper to fetch jobs using a connector."""
    async with connector_cls() as connector:
        return await connector.fetch_jobs(board_token, employer_domain)


@celery_app.task
def mark_stale_jobs():
    """Mark jobs as removed if not seen in recent crawl runs.

    A job is considered stale if its source_config has had N successful
    crawls since the job was last updated, and the job wasn't found.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.database_url_sync)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        threshold = datetime.utcnow() - timedelta(days=7)

        stmt = (
            update(Job)
            .where(Job.status == "active")
            .where(Job.date_updated < threshold)
            .values(status="expired", date_updated=datetime.utcnow())
        )

        result = session.execute(stmt)
        session.commit()

        return {"jobs_expired": result.rowcount}
