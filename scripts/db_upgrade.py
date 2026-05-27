"""Idempotent schema upgrade for web boot.

Detects three states and acts:
  - fresh DB (no employers table)         -> alembic upgrade head
  - existing schema, no alembic_version   -> stamp 001 (baseline), upgrade head
  - alembic_version exists                -> upgrade head

The "existing schema, no version" branch is the v0.6.1 case: the DB was
hand-bootstrapped before alembic was ever wired in, so CREATE TABLE in
migration 001 would explode. Stamping it as already-applied skips 001
and lets 002+ run cleanly.
"""

from __future__ import annotations

import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from src.config import settings


def main() -> None:
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)
    has_employers = insp.has_table("employers")
    has_version = insp.has_table("alembic_version")
    engine.dispose()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url_sync)

    if has_employers and not has_version:
        print("db_upgrade: existing schema detected, stamping baseline 001", flush=True)
        command.stamp(cfg, "001")

    print("db_upgrade: running alembic upgrade head", flush=True)
    command.upgrade(cfg, "head")

    # Re-read alembic_version so logs show exactly where we landed.
    try:
        from sqlalchemy import text as sql_text
        engine2 = create_engine(settings.database_url_sync)
        with engine2.connect() as conn:
            rev = conn.execute(sql_text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        engine2.dispose()
        print(f"db_upgrade: done, alembic_version = {rev}", flush=True)
    except Exception as e:
        print(f"db_upgrade: done (could not read alembic_version: {e})", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"db_upgrade: FAILED — {e}", file=sys.stderr, flush=True)
        # Do not crash the web container on schema-tooling failure.
        # The app may still serve traffic for endpoints that don't need
        # the newer columns; logs will surface the issue.
        sys.exit(0)
