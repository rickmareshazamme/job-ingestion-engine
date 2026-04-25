"""Arbeitnow API connector.

Free, no auth required. Europe-focused (DACH region strong).
Volume: 5K-15K active jobs.

Endpoint: GET https://www.arbeitnow.com/api/job-board-api
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.arbeitnow")


class ArbeitnowConnector(BaseConnector):
    SOURCE_TYPE = "arbeitnow_api"
    ATS_PLATFORM = "arbeitnow"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        all_jobs = []
        page = 1
        max_pages = 20

        while page <= max_pages:
            url = f"https://www.arbeitnow.com/api/job-board-api?page={page}"
            logger.info("Fetching Arbeitnow page %d", page)

            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("Arbeitnow page %d failed: %s", page, str(e)[:100])
                break

            jobs_data = data.get("data", [])
            if not jobs_data:
                break

            for job in jobs_data:
                try:
                    all_jobs.append(self._normalize(job))
                except Exception as e:
                    logger.warning("Arbeitnow normalize failed: %s", e)

            # Check pagination
            links = data.get("links", {})
            if not links.get("next"):
                break
            page += 1

        logger.info("Arbeitnow: fetched %d jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, job: dict) -> RawJob:
        date_posted = None
        created = job.get("created_at")
        if created:
            try:
                date_posted = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        tags = job.get("tags", [])
        location = job.get("location", "")
        remote = job.get("remote", False)
        company = job.get("company_name", "Unknown")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("slug", job.get("title", ""))),
            source_url=job.get("url", ""),
            title=job.get("title", ""),
            description_html=job.get("description", ""),
            employer_name=company,
            employer_domain=company.lower().replace(" ", "").replace(",", "") + ".com",
            employer_logo_url=job.get("company_logo"),
            location_raw=location,
            date_posted=date_posted,
            categories=tags[:5] if tags else [],
            is_remote=remote,
            raw_data=job,
        )
