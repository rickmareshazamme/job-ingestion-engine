"""Ashby ATS API connector.

Public API, no auth required. Fast-growing, popular with startups.
Best compensation data of any ATS API.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{company}
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.ashby")


class AshbyConnector(BaseConnector):
    SOURCE_TYPE = "ashby_api"
    ATS_PLATFORM = "ashby"
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        url = f"{self.BASE_URL}/{board_token}?includeCompensation=true"
        logger.info("Fetching jobs from Ashby board: %s", board_token)

        try:
            data = await self._get_json(url)
        except PermanentError:
            logger.error("Ashby board not found: %s", board_token)
            return []

        jobs_data = data.get("jobs", [])
        logger.info("Ashby %s: found %d jobs", board_token, len(jobs_data))

        raw_jobs = []
        for job in jobs_data:
            try:
                raw_jobs.append(self._normalize(job, board_token, employer_domain))
            except Exception as e:
                logger.warning("Ashby normalize failed: %s", e)

        return raw_jobs

    def _normalize(self, job: dict, board_token: str, employer_domain: str) -> RawJob:
        location = job.get("location", "")
        if isinstance(location, dict):
            location = location.get("name", "")

        date_posted = None
        published = job.get("publishedAt") or job.get("updatedAt")
        if published:
            try:
                date_posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        salary_raw = None
        compensation = job.get("compensation")
        if compensation:
            comp_parts = []
            if compensation.get("currencyCode"):
                comp_parts.append(compensation["currencyCode"])
            if compensation.get("min"):
                comp_parts.append(str(compensation["min"]))
            if compensation.get("max"):
                comp_parts.append(f"- {compensation['max']}")
            if compensation.get("interval"):
                comp_parts.append(compensation["interval"])
            salary_raw = " ".join(comp_parts) if comp_parts else None

        department = job.get("department", "")
        team = job.get("team", "")
        categories = [c for c in [department, team] if c]

        employment_type = job.get("employmentType", "")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("id", "")),
            source_url=job.get("jobUrl", job.get("applyUrl", "")),
            title=job.get("title", ""),
            description_html=job.get("descriptionHtml", job.get("description", "")),
            employer_name=board_token,
            employer_domain=employer_domain,
            location_raw=location,
            salary_raw=salary_raw,
            employment_type_raw=employment_type,
            date_posted=date_posted,
            categories=categories,
            is_remote="remote" in str(location).lower() if location else None,
            raw_data=job,
        )
