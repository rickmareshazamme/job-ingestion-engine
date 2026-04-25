"""Adzuna job aggregator API connector.

Coverage: 16 countries (US, UK, AU, DE, FR, IN, BR, CA, NL, PL, ZA, SG, AT, CH, NZ, IT)
Free tier: 250 requests/day
Docs: https://developer.adzuna.com/

Endpoint: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
"""

import logging
from datetime import datetime
from typing import Optional

from src.config import settings
from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.adzuna")

ADZUNA_COUNTRIES = [
    "us", "gb", "au", "de", "fr", "in", "br", "ca",
    "nl", "pl", "za", "sg", "at", "ch", "nz", "it",
]


class AdzunaConnector(BaseConnector):
    SOURCE_TYPE = "adzuna_api"
    ATS_PLATFORM = "adzuna"
    BASE_URL = "https://api.adzuna.com/v1/api/jobs"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """board_token = country code (e.g. 'us', 'gb', 'au'). employer_domain ignored."""
        country = board_token.lower()
        if country not in ADZUNA_COUNTRIES:
            logger.warning("Adzuna: unsupported country %s", country)
            return []

        if not settings.adzuna_app_id or not settings.adzuna_app_key:
            logger.error("Adzuna API credentials not configured (ADZUNA_APP_ID, ADZUNA_APP_KEY)")
            return []

        all_jobs = []
        max_pages = 5  # 50 results per page = 250 jobs per country per run

        for page in range(1, max_pages + 1):
            url = (
                f"{self.BASE_URL}/{country}/search/{page}"
                f"?app_id={settings.adzuna_app_id}"
                f"&app_key={settings.adzuna_app_key}"
                f"&results_per_page=50"
                f"&content_type=application/json"
                f"&sort_by=date"
            )

            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("Adzuna %s page %d failed: %s", country, page, str(e)[:100])
                break

            results = data.get("results", [])
            if not results:
                break

            for job in results:
                try:
                    all_jobs.append(self._normalize(job, country))
                except Exception as e:
                    logger.warning("Adzuna normalize failed: %s", e)

        logger.info("Adzuna %s: fetched %d jobs", country.upper(), len(all_jobs))
        return all_jobs

    async def fetch_all_countries(self) -> list[RawJob]:
        """Fetch jobs from all supported countries."""
        all_jobs = []
        for country in ADZUNA_COUNTRIES:
            jobs = await self.fetch_jobs(country, "")
            all_jobs.extend(jobs)
        return all_jobs

    def _normalize(self, job: dict, country: str) -> RawJob:
        location_parts = []
        loc = job.get("location", {})
        for area in loc.get("area", []):
            if area:
                location_parts.append(area)
        location_raw = ", ".join(location_parts) if location_parts else ""

        date_posted = None
        created = job.get("created")
        if created:
            try:
                date_posted = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        salary_raw = None
        sal_min = job.get("salary_min")
        sal_max = job.get("salary_max")
        if sal_min or sal_max:
            salary_raw = f"{sal_min or '?'} - {sal_max or '?'}"

        company = job.get("company", {})
        employer_name = company.get("display_name", "Unknown")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("id", "")),
            source_url=job.get("redirect_url", ""),
            title=job.get("title", ""),
            description_html=job.get("description", ""),
            employer_name=employer_name,
            employer_domain=employer_name.lower().replace(" ", "") + ".com",
            location_raw=location_raw,
            salary_raw=salary_raw,
            date_posted=date_posted,
            categories=[job.get("category", {}).get("label", "")] if job.get("category") else [],
            is_remote=None,
            raw_data=job,
        )
