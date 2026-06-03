"""Make sure ZammeJobs has a Shazamme feed SourceConfig + queued first crawl.

Idempotent boot-time setup:
  - If no SourceConfig with source_type='shazamme_feed' exists, INSERT one
    pointing at the default Shazamme XML URL.
  - If no jobs with source_type='shazamme_feed' exist yet, dispatch a
    Celery crawl_source task immediately so the worker pulls the feed
    instead of waiting up to 30 min for the next beat tick.

Safe to run on every web boot — both branches are no-ops once the
Shazamme data is in the DB.
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy import create_engine, text

from src.config import settings
from src.connectors.shazamme import DEFAULT_FEED_URL


def main() -> None:
    engine = create_engine(settings.database_url_sync)
    source_id: str | None = None
    with engine.begin() as conn:
        existing = conn.execute(text(
            "SELECT id FROM source_configs WHERE source_type = 'shazamme_feed' LIMIT 1"
        )).scalar()

        if existing:
            source_id = str(existing)
            # Keep the source's interval in sync with the configured cadence —
            # an older row may still carry the previous 12h default.
            conn.execute(
                text("""
                    UPDATE source_configs
                    SET crawl_interval_hours = :interval
                    WHERE id = :id
                      AND crawl_interval_hours > :interval
                """),
                {"interval": settings.feed_crawl_interval_hours, "id": existing},
            )
            print(
                f"ensure_shazamme_source: source_config exists ({source_id}), "
                f"interval pinned to {settings.feed_crawl_interval_hours}h",
                flush=True,
            )
        else:
            new_id = uuid.uuid4()
            conn.execute(text("""
                INSERT INTO source_configs
                    (id, source_type, config, crawl_interval_hours, is_active, rate_limit_rpm)
                VALUES
                    (:id, 'shazamme_feed',
                     CAST(:cfg AS JSONB),
                     :interval, TRUE, :rpm)
            """), {
                "id": new_id,
                "cfg": '{"board_token": "' + DEFAULT_FEED_URL + '"}',
                "interval": settings.feed_crawl_interval_hours,
                "rpm": 30,
            })
            source_id = str(new_id)
            print(f"ensure_shazamme_source: created source_config {source_id}", flush=True)

        shazamme_jobs = conn.execute(text(
            "SELECT COUNT(*) FROM jobs WHERE source_type = 'shazamme_feed'"
        )).scalar() or 0

        last_crawl = conn.execute(text(
            "SELECT last_crawl_at FROM source_configs WHERE source_type = 'shazamme_feed' LIMIT 1"
        )).scalar()

    engine.dispose()

    # Decide whether to (re)dispatch the import. We don't trust Celery beat
    # to be running on Railway (worker/beat services aren't always
    # provisioned), so the web boot owns refresh: if the latest crawl is
    # older than feed_crawl_interval_hours, kick a fresh import.
    needs_dispatch = False
    if shazamme_jobs == 0:
        needs_dispatch = True
        reason = "no Shazamme jobs in DB yet"
    elif last_crawl is None:
        needs_dispatch = True
        reason = "last_crawl_at is null"
    else:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.utcnow() - timedelta(hours=settings.feed_crawl_interval_hours)
        # last_crawl comes back tz-aware (timestamptz column); normalize to
        # naive UTC so it compares against naive utcnow() without raising.
        if last_crawl.tzinfo is not None:
            last_crawl = last_crawl.astimezone(timezone.utc).replace(tzinfo=None)
        if last_crawl < cutoff:
            needs_dispatch = True
            reason = f"last crawl {last_crawl} is older than {settings.feed_crawl_interval_hours}h"
        else:
            print(
                f"ensure_shazamme_source: {shazamme_jobs} jobs present, last crawl "
                f"{last_crawl} within {settings.feed_crawl_interval_hours}h — no dispatch",
                flush=True,
            )
            return

    # Spawn the import as a detached subprocess so the web container
    # finishes booting in milliseconds while the 250MB feed downloads
    # in the background. We bypass Celery (v0.7.1 dispatch never
    # actually picked up — likely Redis env mismatch from the web
    # process) and run scripts.import_shazamme directly.
    import os
    import subprocess
    log_path = "/tmp/shazamme_import.log"
    proc = subprocess.Popen(
        ["python3", "-m", "scripts.import_shazamme"],
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=os.environ.copy(),
    )
    print(
        f"ensure_shazamme_source: launched scripts.import_shazamme pid={proc.pid} "
        f"({reason}), logging to {log_path}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ensure_shazamme_source: FAILED — {e}", file=sys.stderr, flush=True)
        sys.exit(0)
