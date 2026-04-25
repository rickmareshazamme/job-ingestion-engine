import logging
import sys

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://jobindex:jobindex@localhost:5432/jobindex"
    database_url_sync: str = "postgresql://jobindex:jobindex@localhost:5432/jobindex"
    redis_url: str = "redis://localhost:6379/0"
    opencage_api_key: str = ""
    bot_user_agent: str = "JobIndexBot/1.0 (+https://jobindex.ai/bot)"

    # Crawl settings
    default_crawl_interval_hours: int = 6
    feed_crawl_interval_hours: int = 12
    headless_crawl_interval_hours: int = 24
    max_requests_per_second: float = 2.0
    stale_after_missed_runs: int = 3

    # Aggregator API keys
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    usajobs_api_key: str = ""
    usajobs_email: str = ""
    reed_api_key: str = ""

    # Indexing
    indexnow_key: str = ""
    site_domain: str = "jobindex.ai"
    google_sa_file: str = ""

    # Logging
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


def setup_logging():
    """Configure structured logging for the application."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Quiet noisy libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


setup_logging()
