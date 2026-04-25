"""Workable ATS API connector.

Public API, no auth required. Mid-market, global presence.

Endpoint: GET https://www.workable.com/api/accounts/{subdomain}?details=true
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.workable")


class WorkableConnector(BaseConnector):
    SOURCE_TYPE = "workable_api"
    ATS_PLATFORM = "workable"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{board_token}"
        logger.info("Fetching jobs from Workable: %s", board_token)

        try:
            data = await self._get_json(url)
        except PermanentError:
            logger.error("Workable account not found: %s", board_token)
            return []

        jobs_data = data.get("jobs", [])
        logger.info("Workable %s: found %d jobs", board_token, len(jobs_data))

        raw_jobs = []
        for job in jobs_data:
            try:
                raw_jobs.append(self._normalize(job, board_token, employer_domain))
            except Exception as e:
                logger.warning("Workable normalize failed: %s", e)

        return raw_jobs

    def _normalize(self, job: dict, board_token: str, employer_domain: str) -> RawJob:
        location = job.get("location", {})
        if isinstance(location, dict):
            parts = [
                location.get("city", ""),
                location.get("region", ""),
                location.get("country", ""),
            ]
            location_raw = ", ".join(p for p in parts if p)
        else:
            location_raw = str(location)

        date_posted = None
        published = job.get("published_on") or job.get("created_at")
        if published:
            try:
                date_posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        department = job.get("department", "")
        employment_type = job.get("employment_type", "")
        workplace = job.get("workplace", "")

        is_remote = "remote" in str(workplace).lower() or "remote" in str(location_raw).lower()

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job.get("shortcode", str(job.get("id", ""))),
            source_url=job.get("url", f"https://apply.workable.com/{board_token}/j/{job.get('shortcode', '')}/"),
            title=job.get("title", ""),
            description_html=job.get("description", ""),
            employer_name=board_token,
            employer_domain=employer_domain,
            location_raw=location_raw,
            employment_type_raw=employment_type,
            date_posted=date_posted,
            categories=[department] if department else [],
            is_remote=is_remote,
            raw_data=job,
        )
