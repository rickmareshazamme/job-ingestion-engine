"""Reed.co.uk API connector.

Free API key (register at reed.co.uk/developers).
Coverage: UK's #1 domestic job board, ~250K active jobs.

Endpoint: GET https://www.reed.co.uk/api/1.0/search
Auth: Basic auth with API key as username, empty password.
"""

import base64
import logging
from datetime import datetime
from typing import Optional

from src.config import settings
from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.reed")


class ReedConnector(BaseConnector):
    SOURCE_TYPE = "reed_api"
    ATS_PLATFORM = "reed"
    BASE_URL = "https://www.reed.co.uk/api/1.0"

    async def _get_session(self):
        import aiohttp
        if self._session is None or self._session.closed:
            auth_str = base64.b64encode(f"{settings.reed_api_key}:".encode()).decode()
            headers = {
                "User-Agent": settings.bot_user_agent,
                "Authorization": f"Basic {auth_str}",
            }
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        if not settings.reed_api_key:
            logger.error("Reed API key not configured (REED_API_KEY)")
            return []

        all_jobs = []
        results_to_skip = 0
        results_to_take = 100

        while True:
            url = (
                f"{self.BASE_URL}/search"
                f"?resultsToTake={results_to_take}"
                f"&resultsToSkip={results_to_skip}"
            )
            if board_token:
                url += f"&keywords={board_token}"

            logger.info("Fetching Reed jobs (skip=%d)", results_to_skip)

            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("Reed fetch failed at skip=%d: %s", results_to_skip, str(e)[:100])
                break

            results = data.get("results", [])
            if not results:
                break

            for job in results:
                try:
                    all_jobs.append(self._normalize(job))
                except Exception as e:
                    logger.warning("Reed normalize failed: %s", e)

            total = data.get("totalResults", 0)
            results_to_skip += results_to_take
            if results_to_skip >= total or results_to_skip >= 1000:
                break

        logger.info("Reed: fetched %d UK jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, job: dict) -> RawJob:
        date_posted = None
        date_str = job.get("date")
        if date_str:
            try:
                date_posted = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        date_expires = None
        exp_str = job.get("expirationDate")
        if exp_str:
            try:
                date_expires = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        salary_raw = None
        sal_min = job.get("minimumSalary")
        sal_max = job.get("maximumSalary")
        if sal_min or sal_max:
            salary_raw = f"GBP {sal_min or '?'} - {sal_max or '?'}"

        location = job.get("locationName", "")
        company = job.get("employerName", "Unknown")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("jobId", "")),
            source_url=job.get("jobUrl", ""),
            title=job.get("jobTitle", ""),
            description_html=job.get("jobDescription", ""),
            employer_name=company,
            employer_domain=company.lower().replace(" ", "") + ".co.uk",
            location_raw=location,
            salary_raw=salary_raw,
            employment_type_raw="CONTRACT" if job.get("contractType") == "contract" else "",
            date_posted=date_posted,
            date_expires=date_expires,
            categories=[],
            is_remote=None,
            raw_data=job,
        )
