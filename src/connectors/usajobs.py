"""USAJobs API connector.

Free API key required (register at developer.usajobs.gov).
Coverage: US federal government jobs (~30K active).

Endpoint: GET https://data.usajobs.gov/api/search
"""

import logging
from datetime import datetime
from typing import Optional

from src.config import settings
from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.usajobs")


class USAJobsConnector(BaseConnector):
    SOURCE_TYPE = "usajobs_api"
    ATS_PLATFORM = "usajobs"
    BASE_URL = "https://data.usajobs.gov/api/search"

    async def _get_session(self):
        import aiohttp
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": settings.usajobs_email or settings.bot_user_agent,
                "Authorization-Key": settings.usajobs_api_key,
                "Host": "data.usajobs.gov",
            }
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        if not settings.usajobs_api_key:
            logger.error("USAJobs API key not configured (USAJOBS_API_KEY)")
            return []

        all_jobs = []
        page = 1
        results_per_page = 250

        while True:
            url = f"{self.BASE_URL}?ResultsPerPage={results_per_page}&Page={page}"
            if board_token:
                url += f"&Keyword={board_token}"

            logger.info("Fetching USAJobs page %d", page)

            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("USAJobs page %d failed: %s", page, str(e)[:100])
                break

            search_result = data.get("SearchResult", {})
            items = search_result.get("SearchResultItems", [])

            if not items:
                break

            for item in items:
                try:
                    all_jobs.append(self._normalize(item))
                except Exception as e:
                    logger.warning("USAJobs normalize failed: %s", e)

            count = int(search_result.get("SearchResultCount", 0))
            total = int(search_result.get("SearchResultCountAll", 0))
            if page * results_per_page >= total or page >= 4:
                break
            page += 1

        logger.info("USAJobs: fetched %d jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, item: dict) -> RawJob:
        job = item.get("MatchedObjectDescriptor", {})

        date_posted = None
        pub_date = job.get("PublicationStartDate")
        if pub_date:
            try:
                date_posted = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        date_expires = None
        close_date = job.get("ApplicationCloseDate")
        if close_date:
            try:
                date_expires = datetime.fromisoformat(close_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        locations = job.get("PositionLocation", [])
        location_raw = ", ".join(
            loc.get("LocationName", "") for loc in locations
        ) if locations else ""

        salary_raw = None
        remuneration = job.get("PositionRemuneration", [])
        if remuneration:
            r = remuneration[0]
            sal_min = r.get("MinimumRange", "")
            sal_max = r.get("MaximumRange", "")
            rate = r.get("RateIntervalCode", "")
            salary_raw = f"${sal_min} - ${sal_max} {rate}" if sal_min else None

        org = job.get("OrganizationName", "US Federal Government")
        dept = job.get("DepartmentName", "")

        schedule = job.get("PositionSchedule", [])
        emp_type = schedule[0].get("Name", "") if schedule else ""

        categories_raw = job.get("JobCategory", [])
        categories = [c.get("Name", "") for c in categories_raw if c.get("Name")]

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job.get("PositionID", ""),
            source_url=job.get("PositionURI", ""),
            title=job.get("PositionTitle", ""),
            description_html=job.get("UserArea", {}).get("Details", {}).get("MajorDuties", [""])[0] if job.get("UserArea") else "",
            employer_name=f"{org} - {dept}" if dept else org,
            employer_domain="usajobs.gov",
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=emp_type,
            date_posted=date_posted,
            date_expires=date_expires,
            categories=categories,
            is_remote="telework" in str(job).lower() or "remote" in location_raw.lower(),
            raw_data=job,
        )
