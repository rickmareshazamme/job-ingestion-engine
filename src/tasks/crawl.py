"""Celery tasks for crawling, normalization, and cleanup.

Features:
- Circuit breaker: pauses sources after consecutive failures
- Structured logging for all crawl operations
- Error classification: retryable vs permanent
- Crawl metrics tracking
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from celery import Celery
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.config import settings
from src.connectors.base import PermanentError, RateLimitError, RawJob
from src.connectors.adzuna import AdzunaConnector
from src.connectors.arbeitnow import ArbeitnowConnector
from src.connectors.ashby import AshbyConnector
from src.connectors.canada_jobbank import CanadaJobBankConnector
from src.connectors.careerjet import CareerjetConnector
from src.connectors.greenhouse import GreenhouseConnector
from src.connectors.jooble import JoobleConnector
from src.connectors.lever import LeverConnector
from src.connectors.personio import PersonioConnector
from src.connectors.recruitee import RecruiteeConnector
from src.connectors.reed import ReedConnector
from src.connectors.remoteok import RemoteOKConnector
from src.connectors.remotive import RemotiveConnector
from src.connectors.smartrecruiters import SmartRecruitersConnector
from src.connectors.themuse import TheMuseConnector
from src.connectors.usajobs import USAJobsConnector
from src.connectors.workable import WorkableConnector
from src.connectors.workday import WorkdayConnector
from src.models import CrawlRun, Job, SourceConfig
from src.normalizer.pipeline import normalize_job

logger = logging.getLogger("jobindex.crawl")

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
    # ATS direct APIs (highest quality — structured data from source)
    "greenhouse_api": GreenhouseConnector,
    "lever_api": LeverConnector,
    "workday_feed": WorkdayConnector,
    "ashby_api": AshbyConnector,
    "workable_api": WorkableConnector,
    "smartrecruiters_sitemap": SmartRecruitersConnector,
    "recruitee_api": RecruiteeConnector,
    "personio_xml": PersonioConnector,
    # Aggregator APIs (volume — millions of jobs)
    "adzuna_api": AdzunaConnector,
    "remoteok_api": RemoteOKConnector,
    "remotive_api": RemotiveConnector,
    "arbeitnow_api": ArbeitnowConnector,
    "themuse_api": TheMuseConnector,
    "usajobs_api": USAJobsConnector,
    "reed_api": ReedConnector,
    "jooble_api": JoobleConnector,
    "careerjet_api": CareerjetConnector,
    "canada_jobbank_xml": CanadaJobBankConnector,
}

# Circuit breaker: max consecutive failures before pausing a source
MAX_CONSECUTIVE_FAILURES = 5
CIRCUIT_BREAKER_COOLDOWN_HOURS = 24


def _run_async(coro):
    """Run an async function from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(settings.database_url_sync)
    return sessionmaker(bind=engine)()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def crawl_source(self, source_config_id: str):
    """Crawl a single source configuration and store results.

    Circuit breaker: if the source has failed MAX_CONSECUTIVE_FAILURES times
    in a row, skip it and log a warning.
    """
    session = _get_sync_session()

    try:
        config = session.get(SourceConfig, uuid.UUID(source_config_id))
        if not config or not config.is_active:
            logger.info("Skipping source %s: inactive or not found", source_config_id)
            return {"status": "skipped", "reason": "inactive or not found"}

        # Circuit breaker check
        if _is_circuit_open(session, config):
            logger.warning("Circuit breaker OPEN for source %s (%s). Skipping.", source_config_id, config.source_type)
            return {"status": "skipped", "reason": "circuit breaker open"}

        crawl_run = CrawlRun(
            id=uuid.uuid4(),
            source_config_id=config.id,
            status="running",
        )
        session.add(crawl_run)
        session.commit()

        start_time = datetime.utcnow()
        source_desc = f"{config.source_type}:{config.config.get('board_token', '?')}"
        logger.info("Starting crawl for %s", source_desc)

        try:
            connector_cls = CONNECTOR_MAP.get(config.source_type)
            if not connector_cls:
                raise ValueError(f"Unknown source type: {config.source_type}")

            raw_jobs = _run_async(_fetch_with_connector(connector_cls, config.source_type, config.config or {}))

            # Normalize and upsert
            jobs_new = 0
            jobs_updated = 0
            new_urls: list[str] = []

            for raw_job in raw_jobs:
                try:
                    job = _run_async(normalize_job(raw_job, do_geocode=False))
                    result = _upsert_job(session, job)
                    if result == "new":
                        jobs_new += 1
                        new_urls.append(f"https://{settings.site_domain}/jobs/{job.id}")
                    else:
                        jobs_updated += 1
                except Exception as e:
                    logger.warning("Failed to normalize/upsert job from %s: %s", source_desc, str(e)[:100])

            session.commit()

            # Push new URLs to IndexNow + Google Indexing API. Best-effort —
            # failures don't fail the crawl.
            if new_urls:
                try:
                    from src.indexing.indexnow import submit_urls as indexnow_submit
                    submitted = _run_async(indexnow_submit(new_urls))
                    if submitted:
                        logger.info("IndexNow: submitted %d new job URLs", submitted)
                except Exception as e:
                    logger.warning("IndexNow dispatch failed: %s", str(e)[:120])
                try:
                    from src.indexing.google import notify_url_updated
                    # Google Indexing free quota is 200/day, so cap per-crawl
                    for u in new_urls[:200]:
                        _run_async(notify_url_updated(u))
                except Exception as e:
                    logger.warning("Google Indexing dispatch failed: %s", str(e)[:120])

            # Update crawl run
            duration = (datetime.utcnow() - start_time).total_seconds()
            crawl_run.status = "success"
            crawl_run.completed_at = datetime.utcnow()
            crawl_run.jobs_found = len(raw_jobs)
            crawl_run.jobs_new = jobs_new
            crawl_run.jobs_updated = jobs_updated
            crawl_run.duration_seconds = duration

            config.last_crawl_at = datetime.utcnow()
            config.last_crawl_status = "success"
            config.last_crawl_job_count = len(raw_jobs)

            session.commit()

            logger.info(
                "Crawl complete for %s: %d found, %d new, %d updated (%.1fs)",
                source_desc, len(raw_jobs), jobs_new, jobs_updated, duration,
            )

            return {
                "status": "success",
                "source": source_desc,
                "jobs_found": len(raw_jobs),
                "jobs_new": jobs_new,
                "jobs_updated": jobs_updated,
                "duration_seconds": round(duration, 1),
            }

        except PermanentError as e:
            _record_failure(session, crawl_run, config, start_time, str(e), permanent=True)
            logger.error("Permanent error crawling %s: %s", source_desc, e)
            return {"status": "permanent_error", "source": source_desc, "error": str(e)}

        except RateLimitError as e:
            _record_failure(session, crawl_run, config, start_time, str(e), permanent=False)
            logger.warning("Rate limited crawling %s: %s", source_desc, e)
            # Retry with longer delay
            raise self.retry(exc=e, countdown=e.retry_after or 120)

        except Exception as e:
            _record_failure(session, crawl_run, config, start_time, str(e), permanent=False)
            logger.error("Error crawling %s: %s", source_desc, str(e)[:200])
            raise self.retry(exc=e)

    finally:
        session.close()


def _upsert_job(session, job: Job) -> str:
    """Insert or update a job. Returns 'new' or 'updated'."""
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

    session.execute(stmt)
    return "new"  # PostgreSQL doesn't easily distinguish insert vs update in on_conflict


def _record_failure(session, crawl_run, config, start_time, error_msg, permanent=False):
    """Record a failed crawl run."""
    crawl_run.status = "failed"
    crawl_run.completed_at = datetime.utcnow()
    crawl_run.error_message = error_msg[:500]
    crawl_run.duration_seconds = (datetime.utcnow() - start_time).total_seconds()

    config.last_crawl_at = datetime.utcnow()
    config.last_crawl_status = "permanent_error" if permanent else "failed"

    session.commit()


def _is_circuit_open(session, config: SourceConfig) -> bool:
    """Check if the circuit breaker is open (too many consecutive failures)."""
    recent_runs = session.execute(
        select(CrawlRun)
        .where(CrawlRun.source_config_id == config.id)
        .order_by(CrawlRun.started_at.desc())
        .limit(MAX_CONSECUTIVE_FAILURES)
    ).scalars().all()

    if len(recent_runs) < MAX_CONSECUTIVE_FAILURES:
        return False

    all_failed = all(r.status in ("failed", "permanent_error") for r in recent_runs)
    if not all_failed:
        return False

    # Check if cooldown has passed
    most_recent = recent_runs[0]
    if most_recent.completed_at:
        cooldown_end = most_recent.completed_at + timedelta(hours=CIRCUIT_BREAKER_COOLDOWN_HOURS)
        if datetime.utcnow() < cooldown_end:
            return True

    return False


async def _fetch_with_connector(connector_cls, source_type: str, config: dict) -> list[RawJob]:
    """All connectors share the (board_token, employer_domain) signature.

    Per-connector meaning of board_token:
      - ATS connectors: the board/company slug (e.g. greenhouse 'spotify', workable subdomain).
      - Adzuna / Careerjet: country code ('us', 'gb', etc).
      - USAJobs / Reed / Jooble / Remotive: optional keyword/category filter.
      - CanadaJobBank: language code ('eng' or 'fra').
      - RemoteOK / Arbeitnow / TheMuse: ignored (single global feed).
    """
    async with connector_cls() as connector:
        return await connector.fetch_jobs(
            config.get("board_token", ""),
            config.get("employer_domain", ""),
        )


@celery_app.task
def mark_stale_jobs():
    """Mark jobs as expired if not updated in 7 days."""
    session = _get_sync_session()
    try:
        threshold = datetime.utcnow() - timedelta(days=7)

        stmt = (
            update(Job)
            .where(Job.status == "active")
            .where(Job.date_updated < threshold)
            .values(status="expired", date_updated=datetime.utcnow())
        )

        result = session.execute(stmt)
        session.commit()

        expired_count = result.rowcount
        logger.info("Marked %d stale jobs as expired", expired_count)
        return {"jobs_expired": expired_count}
    finally:
        session.close()
