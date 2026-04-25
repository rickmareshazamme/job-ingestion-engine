"""Base connector interface for ATS API integrations.

Provides rate limiting, retry logic, structured logging, and
error classification for all connectors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from src.config import settings

logger = logging.getLogger("jobindex.connector")


class RateLimitError(Exception):
    """Raised when we hit a rate limit (429)."""

    def __init__(self, retry_after: Optional[int] = None):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s" if retry_after else "Rate limited")


class PermanentError(Exception):
    """Raised for non-retryable errors (404, 403, auth failures)."""
    pass


@dataclass
class RawJob:
    """Raw job data from an ATS before normalization."""

    source_type: str
    source_id: str
    source_url: str
    title: str
    description_html: str
    employer_name: str
    employer_domain: str
    employer_logo_url: Optional[str] = None
    location_raw: Optional[str] = None
    salary_raw: Optional[str] = None
    employment_type_raw: Optional[str] = None
    date_posted: Optional[datetime] = None
    date_expires: Optional[datetime] = None
    categories: list[str] = field(default_factory=list)
    is_remote: Optional[bool] = None
    raw_data: Optional[dict] = None


@dataclass
class EmployerStub:
    """Minimal employer info discovered from an ATS platform."""

    name: str
    domain: str
    ats_platform: str
    board_token: str
    career_page_url: str
    logo_url: Optional[str] = None


# Per-domain request timestamps for rate limiting
_domain_last_request: dict[str, float] = {}
_domain_lock = asyncio.Lock()


class BaseConnector(ABC):
    """Abstract base class for ATS API connectors.

    Features:
    - Async semaphore limits concurrent requests (default 5)
    - Per-domain rate limiting (default 2 req/sec)
    - Retry-After header respect
    - Error classification (retryable vs permanent)
    - Structured logging for all requests
    """

    SOURCE_TYPE: str = ""
    ATS_PLATFORM: str = ""

    def __init__(self):
        self.user_agent = settings.bot_user_agent
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(5)
        self._max_rps = settings.max_requests_per_second

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": self.user_agent},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _throttle(self, url: str):
        """Per-domain rate limiting. Ensures min interval between requests to same domain."""
        domain = urlparse(url).netloc
        min_interval = 1.0 / self._max_rps

        async with _domain_lock:
            last = _domain_last_request.get(domain, 0)
            elapsed = time.monotonic() - last
            if elapsed < min_interval:
                wait = min_interval - elapsed
                logger.debug("Throttling %s for %.2fs", domain, wait)
                await asyncio.sleep(wait)
            _domain_last_request[domain] = time.monotonic()

    def _classify_error(self, status: int, url: str) -> Exception:
        """Classify HTTP errors as retryable or permanent."""
        if status == 429:
            logger.warning("Rate limited by %s (429)", urlparse(url).netloc)
            return RateLimitError()
        if status in (404, 403, 401, 410):
            logger.error("Permanent error %d from %s", status, url)
            return PermanentError(f"HTTP {status} from {url}")
        if status >= 500:
            logger.warning("Server error %d from %s (retryable)", status, url)
            return aiohttp.ClientResponseError(
                request_info=None, history=(), status=status, message=f"Server error {status}"
            )
        return aiohttp.ClientResponseError(
            request_info=None, history=(), status=status, message=f"HTTP {status}"
        )

    async def _get_json(self, url: str, retries: int = 2) -> dict | list:
        """GET a URL and return parsed JSON with rate limiting and retries."""
        async with self._semaphore:
            for attempt in range(retries + 1):
                await self._throttle(url)

                try:
                    session = await self._get_session()
                    async with session.get(url) as resp:
                        if resp.status == 429:
                            retry_after = resp.headers.get("Retry-After")
                            wait = int(retry_after) if retry_after and retry_after.isdigit() else 30
                            logger.warning("429 from %s, waiting %ds (attempt %d/%d)", url, wait, attempt + 1, retries + 1)
                            if attempt < retries:
                                await asyncio.sleep(wait)
                                continue
                            raise RateLimitError(wait)

                        if resp.status in (404, 403, 401, 410):
                            raise PermanentError(f"HTTP {resp.status} from {url}")

                        if resp.status >= 500 and attempt < retries:
                            logger.warning("Server error %d from %s (attempt %d/%d)", resp.status, url, attempt + 1, retries + 1)
                            await asyncio.sleep(2 ** attempt)
                            continue

                        resp.raise_for_status()
                        return await resp.json()

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < retries:
                        logger.warning("Request failed for %s: %s (attempt %d/%d)", url, str(e)[:100], attempt + 1, retries + 1)
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.error("Request failed permanently for %s: %s", url, str(e)[:200])
                    raise

        raise RuntimeError(f"Exhausted retries for {url}")

    async def _post_json(self, url: str, payload: dict, retries: int = 2) -> dict | list:
        """POST JSON and return parsed response with rate limiting and retries."""
        async with self._semaphore:
            for attempt in range(retries + 1):
                await self._throttle(url)

                try:
                    session = await self._get_session()
                    async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                        if resp.status == 429:
                            retry_after = resp.headers.get("Retry-After")
                            wait = int(retry_after) if retry_after and retry_after.isdigit() else 30
                            logger.warning("429 from %s, waiting %ds", url, wait)
                            if attempt < retries:
                                await asyncio.sleep(wait)
                                continue
                            raise RateLimitError(wait)

                        if resp.status in (404, 403, 401, 410):
                            raise PermanentError(f"HTTP {resp.status} from {url}")

                        if resp.status >= 500 and attempt < retries:
                            logger.warning("Server error %d from %s (attempt %d/%d)", resp.status, url, attempt + 1, retries + 1)
                            await asyncio.sleep(2 ** attempt)
                            continue

                        resp.raise_for_status()
                        return await resp.json()

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < retries:
                        logger.warning("POST failed for %s: %s (attempt %d/%d)", url, str(e)[:100], attempt + 1, retries + 1)
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.error("POST failed permanently for %s: %s", url, str(e)[:200])
                    raise

        raise RuntimeError(f"Exhausted retries for {url}")

    @abstractmethod
    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fetch all active jobs for a given employer/board."""
        ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
