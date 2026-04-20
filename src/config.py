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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
