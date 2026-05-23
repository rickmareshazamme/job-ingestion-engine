#!/usr/bin/env sh
# Single entrypoint that branches based on Railway's RAILWAY_SERVICE_NAME.
# Avoids needing per-service Custom Start Commands in the dashboard.

set -e

case "${RAILWAY_SERVICE_NAME:-web}" in
  worker)
    exec celery -A src.tasks.crawl worker --loglevel=info --concurrency=4
    ;;
  beat)
    exec celery -A src.scheduler beat --loglevel=info
    ;;
  *)
    # Web boots own the schema. alembic_version table makes this idempotent
    # across rolling restarts; new migrations apply once on next deploy.
    alembic upgrade head
    exec uvicorn src.app:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
esac
