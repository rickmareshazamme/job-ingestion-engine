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
