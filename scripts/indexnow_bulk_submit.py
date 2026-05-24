"""Bulk-submit every active job URL to IndexNow.

IndexNow notifies Bing, Yandex, Naver, Seznam (and any participating
search engine) immediately about new/changed URLs. Google does NOT
participate, but Bing's index is consumed by ChatGPT search, Copilot,
DuckDuckGo, and several enterprise crawlers — so this is meaningful
distribution for AEO/GEO, not just SEO.

Usage:
    python3 -m scripts.indexnow_bulk_submit            # submit all active jobs
    python3 -m scripts.indexnow_bulk_submit --limit 5  # smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import create_engine, text

from src.config import settings
from src.indexing.indexnow import submit_urls

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("indexnow_bulk")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="Only submit first N URLs (0 = all)")
    args = p.parse_args()

    host = settings.site_domain or "www.zammejobs.com"
    engine = create_engine(settings.database_url_sync)
    with engine.begin() as conn:
        sql = "SELECT id FROM jobs WHERE status = 'active' ORDER BY date_posted DESC NULLS LAST"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = conn.execute(text(sql)).fetchall()
    engine.dispose()

    urls = [f"https://{host}/jobs/{r[0]}" for r in rows]
    # Static pages worth including in the same push
    urls = [f"https://{host}/", f"https://{host}/search"] + urls

    logger.info("Submitting %d URLs to IndexNow (host=%s)", len(urls), host)
    submitted = await submit_urls(urls)
    logger.info("IndexNow done: %d URLs accepted across all batches", submitted)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"indexnow_bulk_submit: FAILED — {e}", file=sys.stderr, flush=True)
        sys.exit(1)
