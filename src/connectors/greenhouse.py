"""Greenhouse ATS API connector.

Public API docs: https://developers.greenhouse.io/job-board.html
No authentication required for public job board API.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.greenhouse")


class GreenhouseConnector(BaseConnector):
    SOURCE_TYPE = "greenhouse_api"
    ATS_PLATFORM = "greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        url = f"{self.BASE_URL}/{board_token}/jobs?content=true"
        logger.info("Fetching jobs from Greenhouse board: %s", board_token)

        try:
            data = await self._get_json(url)
        except PermanentError:
            logger.error("Board not found or access denied: %s", board_token)
            return []

        jobs_data = data.get("jobs", [])
        logger.info("Greenhouse %s: found %d jobs", board_token, len(jobs_data))

        raw_jobs = []
        for job in jobs_data:
            try:
                raw_jobs.append(self._normalize_job(job, board_token, employer_domain))
            except Exception as e:
                logger.warning("Failed to normalize Greenhouse job %s: %s", job.get("id", "?"), e)

        return raw_jobs

    async def fetch_company_info(self, board_token: str) -> Optional[dict]:
        url = f"{self.BASE_URL}/{board_token}"
        try:
            return await self._get_json(url)
        except Exception as e:
            logger.warning("Failed to fetch company info for %s: %s", board_token, e)
            return None

    def _normalize_job(self, job: dict, board_token: str, employer_domain: str) -> RawJob:
        location = job.get("location", {})
        location_name = location.get("name", "") if isinstance(location, dict) else str(location)

        departments = job.get("departments") or []
        categories = [d.get("name", "") for d in departments if isinstance(d, dict) and d.get("name")]

        metadata = job.get("metadata", [])
        salary_raw = None
        employment_type_raw = None
        for meta in metadata:
            name_lower = (meta.get("name") or "").lower()
            if "salary" in name_lower or "compensation" in name_lower:
                salary_raw = str(meta.get("value", ""))
            if "employment" in name_lower or "type" in name_lower:
                employment_type_raw = str(meta.get("value", ""))

        posted_at = job.get("updated_at") or job.get("created_at")
        date_posted = None
        if posted_at:
            try:
                date_posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job["id"]),
            source_url=job.get("absolute_url", f"https://boards.greenhouse.io/{board_token}/jobs/{job['id']}"),
            title=job.get("title", ""),
            description_html=job.get("content", ""),
            employer_name=board_token,
            employer_domain=employer_domain,
            location_raw=location_name,
            salary_raw=salary_raw,
            employment_type_raw=employment_type_raw,
            date_posted=date_posted,
            categories=categories,
            is_remote="remote" in location_name.lower() if location_name else None,
            raw_data=job,
        )
