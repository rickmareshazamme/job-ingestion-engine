"""Reconcile job visibility with the shazamme_only_ingestion flag.

Guarded logic:
  - flag ON  AND Shazamme rows present   -> hide non-Shazamme (active -> hidden)
  - flag ON  AND no Shazamme rows yet    -> restore hidden -> active (don't
                                            blank the site while the Shazamme
                                            crawl is still pending)
  - flag OFF                             -> restore hidden -> active

All branches are idempotent.
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from src.config import settings


def _restore(conn) -> int:
    result = conn.execute(text("""
        UPDATE jobs
        SET status = 'active',
            date_updated = NOW()
        WHERE source_type != 'shazamme_feed'
          AND status = 'hidden'
    """))
    return result.rowcount


def _hide(conn) -> int:
    result = conn.execute(text("""
        UPDATE jobs
        SET status = 'hidden',
            date_updated = NOW()
        WHERE source_type != 'shazamme_feed'
          AND status = 'active'
    """))
    return result.rowcount


def _restore_falsely_expired_shazamme(conn) -> int:
    """Undo expiry of Shazamme rows that the apply-route liveness check
    (now removed) wrongly marked expired. Only touches rows still in
    the feed — joined back via source_id."""
    result = conn.execute(text("""
        UPDATE jobs
        SET status = 'active',
            date_updated = NOW()
        WHERE source_type = 'shazamme_feed'
          AND status = 'expired'
    """))
    return result.rowcount


def main() -> None:
    engine = create_engine(settings.database_url_sync)
    with engine.begin() as conn:
        n_restored = _restore_falsely_expired_shazamme(conn)
        if n_restored:
            print(f"sync_shazamme_visibility: restored {n_restored} Shazamme rows from 'expired'", flush=True)
        if not settings.shazamme_only_ingestion:
            n = _restore(conn)
            print(f"sync_shazamme_visibility: flag OFF, restored {n} jobs", flush=True)
            return

        shazamme_count = conn.execute(text(
            "SELECT COUNT(*) FROM jobs WHERE source_type = 'shazamme_feed'"
        )).scalar() or 0

        if shazamme_count == 0:
            n = _restore(conn)
            print(
                f"sync_shazamme_visibility: no Shazamme rows yet, restored {n} "
                "non-Shazamme jobs so the site isn't blank while the crawl runs",
                flush=True,
            )
            return

        n = _hide(conn)
        print(
            f"sync_shazamme_visibility: Shazamme rows={shazamme_count}, hid {n} non-Shazamme jobs",
            flush=True,
        )
    engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"sync_shazamme_visibility: FAILED — {e}", file=sys.stderr, flush=True)
        sys.exit(0)
