"""IndexNow protocol — instant URL submission to Bing, Yandex, Naver, Seznam.

Docs: https://www.indexnow.org/documentation
Free, no auth beyond a host-validated key file.

Usage:
    from src.indexing.indexnow import submit_urls
    await submit_urls(["https://zammejobs.com/jobs/abc-123", ...])
"""

from __future__ import annotations

import logging
from typing import Iterable

import aiohttp

from src.config import settings

logger = logging.getLogger("zammejobs.indexnow")

INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"
BATCH_SIZE = 10_000  # IndexNow accepts up to 10K URLs per call


async def submit_urls(urls: Iterable[str]) -> int:
    """Submit URLs to IndexNow. Returns number of URLs successfully submitted."""
    if not settings.indexnow_key:
        logger.debug("INDEXNOW_KEY not set — skipping IndexNow submission")
        return 0

    url_list = list(urls)
    if not url_list:
        return 0

    host = settings.site_domain or "zammejobs.com"
    submitted = 0

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        for i in range(0, len(url_list), BATCH_SIZE):
            batch = url_list[i:i + BATCH_SIZE]
            payload = {
                "host": host,
                "key": settings.indexnow_key,
                "keyLocation": f"https://{host}/indexnow-key.txt",
                "urlList": batch,
            }
            try:
                async with session.post(INDEXNOW_ENDPOINT, json=payload) as resp:
                    if 200 <= resp.status < 300:
                        submitted += len(batch)
                        logger.info("IndexNow accepted %d URLs (batch %d)", len(batch), i // BATCH_SIZE + 1)
                    else:
                        body = (await resp.text())[:200]
                        logger.warning("IndexNow rejected batch (%d): %s", resp.status, body)
            except (aiohttp.ClientError, TimeoutError) as e:
                logger.warning("IndexNow request failed: %s", e)

    return submitted


async def submit_url(url: str) -> bool:
    """Submit a single URL via the GET form."""
    if not settings.indexnow_key:
        return False
    host = settings.site_domain or "zammejobs.com"
    params = {
        "url": url,
        "key": settings.indexnow_key,
        "keyLocation": f"https://{host}/indexnow-key.txt",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        try:
            async with session.get(INDEXNOW_ENDPOINT, params=params) as resp:
                ok = 200 <= resp.status < 300
                if not ok:
                    logger.warning("IndexNow single submit rejected (%d) for %s", resp.status, url)
                return ok
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("IndexNow single submit failed: %s", e)
            return False
