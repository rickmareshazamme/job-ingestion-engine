"""RemoteOK API connector.

Free, no auth required. Single JSON endpoint.
Coverage: Global remote jobs, tech-heavy.
Volume: 5K-10K active jobs.

Endpoint: GET https://remoteok.com/api
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.remoteok")


class RemoteOKConnector(BaseConnector):
    SOURCE_TYPE = "remoteok_api"
    ATS_PLATFORM = "remoteok"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        url = "https://remoteok.com/api"
        logger.info("Fetching all jobs from RemoteOK")

        try:
            data = await self._get_json(url)
        except Exception as e:
            logger.error("RemoteOK fetch failed: %s", str(e)[:200])
            return []

        if not isinstance(data, list):
            return []

        # First item is metadata, skip it
        jobs_data = [j for j in data if isinstance(j, dict) and j.get("id")]

        raw_jobs = []
        for job in jobs_data:
            try:
                raw_jobs.append(self._normalize(job))
            except Exception as e:
                logger.warning("RemoteOK normalize failed: %s", e)

        logger.info("RemoteOK: fetched %d jobs", len(raw_jobs))
        return raw_jobs

    def _normalize(self, job: dict) -> RawJob:
        date_posted = None
        epoch = job.get("epoch")
        if epoch:
            try:
                date_posted = datetime.fromtimestamp(int(epoch))
            except (ValueError, TypeError, OSError):
                pass

        date_str = job.get("date")
        if not date_posted and date_str:
            try:
                date_posted = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        salary_raw = None
        sal_min = job.get("salary_min")
        sal_max = job.get("salary_max")
        if sal_min or sal_max:
            salary_raw = f"${sal_min or '?'} - ${sal_max or '?'}"

        tags = job.get("tags", [])
        location_raw = job.get("location", "Remote")
        company = job.get("company", "Unknown")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("id", "")),
            source_url=job.get("url", f"https://remoteok.com/remote-jobs/{job.get('slug', '')}"),
            title=job.get("position", ""),
            description_html=job.get("description", ""),
            employer_name=company,
            employer_domain=company.lower().replace(" ", "") + ".com",
            employer_logo_url=job.get("company_logo"),
            location_raw=location_raw,
            salary_raw=salary_raw,
            date_posted=date_posted,
            categories=tags[:5] if tags else [],
            is_remote=True,
            raw_data=job,
        )
