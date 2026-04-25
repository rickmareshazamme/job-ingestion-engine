"""Jooble API connector.

Coverage: 71 countries. Free for publishers.
Requires API key (register at jooble.org/api/about).

Endpoint: POST https://jooble.org/api/{api_key}
"""

import logging
from datetime import datetime
from typing import Optional

from src.config import settings
from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.jooble")


class JoobleConnector(BaseConnector):
    SOURCE_TYPE = "jooble_api"
    ATS_PLATFORM = "jooble"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        """board_token can be a search keyword. employer_domain is the API key override."""
        api_key = employer_domain or getattr(settings, "jooble_api_key", "")
        if not api_key:
            logger.error("Jooble API key not configured")
            return []

        url = f"https://jooble.org/api/{api_key}"
        all_jobs = []

        for page in range(1, 11):
            payload = {
                "keywords": board_token or "",
                "page": str(page),
            }

            try:
                data = await self._post_json(url, payload)
            except Exception as e:
                logger.warning("Jooble page %d failed: %s", page, str(e)[:100])
                break

            jobs_data = data.get("jobs", [])
            if not jobs_data:
                break

            for job in jobs_data:
                try:
                    all_jobs.append(self._normalize(job))
                except Exception as e:
                    logger.warning("Jooble normalize failed: %s", e)

            total = data.get("totalCount", 0)
            if page * 20 >= total:
                break

        logger.info("Jooble: fetched %d jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, job: dict) -> RawJob:
        date_posted = None
        updated = job.get("updated")
        if updated:
            try:
                date_posted = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        company = job.get("company", "Unknown")
        location = job.get("location", "")
        salary = job.get("salary", "")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job.get("id", job.get("link", "")),
            source_url=job.get("link", ""),
            title=job.get("title", ""),
            description_html=job.get("snippet", ""),
            employer_name=company,
            employer_domain=company.lower().replace(" ", "") + ".com",
            location_raw=location,
            salary_raw=salary if salary else None,
            date_posted=date_posted,
            categories=[job.get("type", "")] if job.get("type") else [],
            is_remote=None,
            raw_data=job,
        )
