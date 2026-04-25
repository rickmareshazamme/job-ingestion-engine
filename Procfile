web: uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8000}
worker: celery -A src.tasks.crawl worker --loglevel=info --concurrency=4
beat: celery -A src.scheduler beat --loglevel=info
