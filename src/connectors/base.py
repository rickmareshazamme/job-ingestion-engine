"""Base connector interface for ATS API integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import aiohttp

from src.config import settings


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


class BaseConnector(ABC):
    """Abstract base class for ATS API connectors."""

    SOURCE_TYPE: str = ""
    ATS_PLATFORM: str = ""

    def __init__(self):
        self.user_agent = settings.bot_user_agent
        self._session: Optional[aiohttp.ClientSession] = None

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

    async def _get_json(self, url: str) -> dict | list:
        session = await self._get_session()
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    @abstractmethod
    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fetch all active jobs for a given employer/board."""
        ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
