"""The Muse API connector.

Free, no auth required. US-focused, curated employer profiles.
Volume: 5K-10K active jobs.

Endpoint: GET https://www.themuse.com/api/public/jobs
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.themuse")


class TheMuseConnector(BaseConnector):
    SOURCE_TYPE = "themuse_api"
    ATS_PLATFORM = "themuse"
    BASE_URL = "https://www.themuse.com/api/public/jobs"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        all_jobs = []
        max_pages = 20

        for page in range(max_pages):
            url = f"{self.BASE_URL}?page={page}&descending=true"
            logger.info("Fetching The Muse page %d", page)

            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("The Muse page %d failed: %s", page, str(e)[:100])
                break

            results = data.get("results", [])
            if not results:
                break

            for job in results:
                try:
                    all_jobs.append(self._normalize(job))
                except Exception as e:
                    logger.warning("The Muse normalize failed: %s", e)

        logger.info("The Muse: fetched %d jobs", len(all_jobs))
        return all_jobs

    def _normalize(self, job: dict) -> RawJob:
        date_posted = None
        pub_date = job.get("publication_date")
        if pub_date:
            try:
                date_posted = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        company = job.get("company", {})
        company_name = company.get("name", "Unknown")
        locations = job.get("locations", [])
        location_raw = ", ".join(loc.get("name", "") for loc in locations) if locations else ""

        categories = [cat.get("name", "") for cat in job.get("categories", []) if cat.get("name")]
        levels = [lvl.get("name", "") for lvl in job.get("levels", []) if lvl.get("name")]

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("id", "")),
            source_url=f"https://www.themuse.com/jobs/{job.get('id', '')}",
            title=job.get("name", ""),
            description_html=job.get("contents", ""),
            employer_name=company_name,
            employer_domain=company_name.lower().replace(" ", "") + ".com",
            location_raw=location_raw,
            employment_type_raw=job.get("type", ""),
            date_posted=date_posted,
            categories=categories,
            is_remote="remote" in location_raw.lower() if location_raw else None,
            raw_data=job,
        )
