"""Recruitee ATS API connector.

Public API, no auth required. SMB/mid-market, strong in Europe.

Endpoint: GET https://{company}.recruitee.com/api/offers/
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.recruitee")


class RecruiteeConnector(BaseConnector):
    SOURCE_TYPE = "recruitee_api"
    ATS_PLATFORM = "recruitee"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        url = f"https://{board_token}.recruitee.com/api/offers/"
        logger.info("Fetching jobs from Recruitee: %s", board_token)

        try:
            data = await self._get_json(url)
        except PermanentError:
            logger.error("Recruitee board not found: %s", board_token)
            return []

        offers = data.get("offers", [])
        logger.info("Recruitee %s: found %d jobs", board_token, len(offers))

        raw_jobs = []
        for job in offers:
            try:
                raw_jobs.append(self._normalize(job, board_token, employer_domain))
            except Exception as e:
                logger.warning("Recruitee normalize failed: %s", e)

        return raw_jobs

    def _normalize(self, job: dict, board_token: str, employer_domain: str) -> RawJob:
        location = job.get("location", "")
        city = job.get("city", "")
        country = job.get("country", "")

        if city and country:
            location_raw = f"{city}, {country}"
        elif location:
            location_raw = location
        else:
            location_raw = city or country or ""

        date_posted = None
        published = job.get("published_at") or job.get("created_at")
        if published:
            try:
                date_posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        department = job.get("department", "")
        tags = job.get("tags", [])
        categories = [department] if department else []
        if tags:
            categories.extend(tags[:3])

        employment_type = job.get("employment_type_code", "")
        remote = job.get("remote", False)

        salary_raw = None
        sal_min = job.get("min_salary")
        sal_max = job.get("max_salary")
        sal_currency = job.get("salary_currency", "")
        if sal_min or sal_max:
            salary_raw = f"{sal_currency} {sal_min or '?'} - {sal_max or '?'}"

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("id", job.get("slug", ""))),
            source_url=job.get("careers_url", f"https://{board_token}.recruitee.com/o/{job.get('slug', '')}"),
            title=job.get("title", ""),
            description_html=job.get("description", ""),
            employer_name=job.get("company_name", board_token),
            employer_domain=employer_domain,
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=employment_type,
            date_posted=date_posted,
            categories=categories,
            is_remote=remote,
            raw_data=job,
        )
