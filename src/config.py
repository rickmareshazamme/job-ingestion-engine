import logging
import sys

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://jobindex:jobindex@localhost:5432/jobindex"
    database_url_sync: str = "postgresql://jobindex:jobindex@localhost:5432/jobindex"
    redis_url: str = "redis://localhost:6379/0"
    opencage_api_key: str = ""
    bot_user_agent: str = "ZammeJobsBot/1.0 (+https://zammejobs.com/bot)"

    # Crawl settings
    default_crawl_interval_hours: int = 6
    feed_crawl_interval_hours: int = 12
    headless_crawl_interval_hours: int = 24
    max_requests_per_second: float = 2.0
    stale_after_missed_runs: int = 3
    # When true, scheduled crawls only dispatch source_configs with
    # source_type='shazamme_feed' — i.e. ZammeJobs ingests Shazamme tenant
    # jobs only. Aggregators/ATS connectors stay registered but idle.
    shazamme_only_ingestion: bool = True

    # Aggregator API keys (all optional — connector self-disables if missing)
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    usajobs_api_key: str = ""
    usajobs_email: str = ""
    reed_api_key: str = ""
    jooble_api_key: str = ""
    rapidapi_key: str = ""
    careerjet_affid: str = ""
    bullhorn_partner_token: str = ""
    bundesagentur_token: str = "bf3a8b6e-7c8e-4e19-a3a8-1c4c2c4c2c4c"

    # Indexing
    # IndexNow keys are deliberately public — they're verified by hosting
    # them at https://<host>/indexnow-key.txt. Default value baked in so
    # bulk submit works out of the box; rotate via env if desired.
    indexnow_key: str = "f3a7c2e8b9d14f5e8a6c3b7d2e9f4a1c5b8e2d7f9a3c6b1e4d8f2a5c7b3e9d6"
    site_domain: str = "www.zammejobs.com"
    google_sa_file: str = ""

    # LinkedIn XML job feed
    # Fallback poster email when an employer has no linkedin_poster_email.
    # LinkedIn Jobs Trust & Safety uses this to verify the posting entity.
    linkedin_default_poster_email: str = "hello@zammejobs.com"
    # LinkedIn rejects feeds aggregated from third-party sites, so by default
    # the feed only includes jobs from claimed (self-registered) employers.
    linkedin_feed_claimed_only: bool = True

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
