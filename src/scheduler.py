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
    # Send job alerts to subscribers. Runs hourly; per-row cadence
    # (instant / daily / weekly) is enforced inside the task by checking
    # last_sent_at vs the cadence interval.
    "send-due-alerts": {
        "task": "src.tasks.crawl.send_due_alerts",
        "schedule": crontab(minute=10),  # 10 past every hour
    },
    # Common Crawl harvest is DISABLED for live ingestion — WDC's
    # 2024-12 extract is from October 2024, so every JobPosting in it is
    # at least 18 months old by the time we'd ingest it. We only want
    # live jobs in the active index.
    #
    # CC remains useful as a DISCOVERY source: scan the lookup file for
    # employer domains we don't yet crawl, then add them to source_configs
    # so the Tier-1 connectors fetch their LIVE jobs. Run that manually
    # via scripts.harvest_common_crawl --discovery (TODO).
    #
    # "harvest-common-crawl": disabled
}


# NOTE: crawl_all_due_sources lives in src/tasks/crawl.py so Celery workers
# (which only import that module) can find it. The beat schedule above
# references src.tasks.crawl.crawl_all_due_sources accordingly.
