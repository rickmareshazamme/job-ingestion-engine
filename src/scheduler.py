"""Celery Beat schedule configuration."""

from celery.schedules import crontab

from src.tasks.crawl import celery_app

celery_app.conf.beat_schedule = {
    "crawl-all-sources": {
        "task": "src.tasks.crawl.crawl_all_due_sources",
        "schedule": crontab(minute="*/30"),
    },
    "mark-stale-jobs": {
        "task": "src.tasks.crawl.mark_stale_jobs",
        "schedule": crontab(hour=3, minute=0),
    },
    # Hourly liveness sweep — HEAD-check ~500 random "active" jobs and mark
    # any that 404/410 as expired. Catches jobs filled between full crawls.
    "validate-active-jobs": {
        "task": "src.tasks.crawl.validate_active_job_urls",
        "schedule": crontab(minute=0),  # top of every hour
        "kwargs": {"sample_size": 500},
    },
    # Every 30 min: auto-create + link employers from unlinked jobs.
    # Keeps the /employers directory complete as new jobs come in.
    "link-employers": {
        "task": "src.tasks.crawl.link_employers",
        "schedule": crontab(minute="*/30"),
    },
    # Every 30 min: resolve city/country to lat/lng via GeoNames so jobs
    # show up on /map. Idempotent + bounded to 5K rows per run.
    "backfill-coords": {
        "task": "src.tasks.crawl.backfill_coords",
        "schedule": crontab(minute="*/30"),
        "kwargs": {"batch_size": 5000},
    },
    # Weekly Common Crawl JobPosting harvest — Sundays 04:00 UTC.
    # Heavy job: streams multi-GB WDC files, can take 1-3 hours.
    "harvest-common-crawl": {
        "task": "src.tasks.crawl.harvest_common_crawl",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),
        "kwargs": {
            "crawl_id": "2024-12",
            "max_files": 3,
            "max_records": 100_000,
        },
    },
}


@celery_app.task
def crawl_all_due_sources():
    """Find all source configs that are due for crawling and dispatch tasks."""
    import uuid
    from datetime import datetime, timedelta

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from src.config import settings
    from src.models import SourceConfig
    from src.tasks.crawl import crawl_source

    engine = create_engine(settings.database_url_sync)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        configs = session.execute(
            select(SourceConfig).where(SourceConfig.is_active == True)
        ).scalars().all()

        dispatched = 0
        for config in configs:
            if config.last_crawl_at is None:
                # Never crawled — dispatch immediately
                crawl_source.delay(str(config.id))
                dispatched += 1
            else:
                next_crawl = config.last_crawl_at + timedelta(hours=config.crawl_interval_hours)
                if datetime.utcnow() >= next_crawl:
                    crawl_source.delay(str(config.id))
                    dispatched += 1

        return {"dispatched": dispatched, "total_configs": len(configs)}
