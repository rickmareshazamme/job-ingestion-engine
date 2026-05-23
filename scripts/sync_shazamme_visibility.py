"""Reconcile job visibility with the shazamme_only_ingestion flag.

When the flag is ON:
  - jobs with source_type != 'shazamme_feed' that are 'active' -> 'hidden'
  - Shazamme jobs are left untouched.

When the flag is OFF:
  - jobs previously marked 'hidden' by this script (source_type !=
    'shazamme_feed') are restored to 'active'. Natural 'expired' rows
    stay expired.

Both directions are idempotent. Runs at web boot after db_upgrade.
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from src.config import settings


def main() -> None:
    engine = create_engine(settings.database_url_sync)
    with engine.begin() as conn:
        if settings.shazamme_only_ingestion:
            result = conn.execute(text("""
                UPDATE jobs
                SET status = 'hidden',
                    date_updated = NOW()
                WHERE source_type != 'shazamme_feed'
                  AND status = 'active'
            """))
            print(f"sync_shazamme_visibility: hid {result.rowcount} non-Shazamme jobs", flush=True)
        else:
            result = conn.execute(text("""
                UPDATE jobs
                SET status = 'active',
                    date_updated = NOW()
                WHERE source_type != 'shazamme_feed'
                  AND status = 'hidden'
            """))
            print(f"sync_shazamme_visibility: restored {result.rowcount} non-Shazamme jobs", flush=True)
    engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"sync_shazamme_visibility: FAILED — {e}", file=sys.stderr, flush=True)
        sys.exit(0)
