"""Careerjet API connector.

Coverage: 90+ countries, multilingual. Free for publishers.

Endpoint: GET https://public.api.careerjet.net/search
Docs: https://www.careerjet.com/partners/api/
"""

import logging
from datetime import datetime
from typing import Optional

from src.config import settings
from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.careerjet")

# Careerjet locale codes for major markets
CAREERJET_LOCALES = {
    "us": "en_US", "gb": "en_GB", "au": "en_AU", "ca": "en_CA",
    "de": "de_DE", "fr": "fr_FR", "nl": "nl_NL", "es": "es_ES",
    "it": "it_IT", "br": "pt_BR", "in": "en_IN", "sg": "en_SG",
    "nz": "en_NZ", "ie": "en_IE", "za": "en_ZA", "at": "de_AT",
    "ch": "de_CH", "se": "sv_SE", "no": "no_NO", "dk": "da_DK",
    "fi": "fi_FI", "pl": "pl_PL", "be": "fr_BE", "pt": "pt_PT",
    "jp": "ja_JP", "kr": "ko_KR", "mx": "es_MX", "ar": "es_AR",
}


class CareerjetConnector(BaseConnector):
    SOURCE_TYPE = "careerjet_api"
    ATS_PLATFORM = "careerjet"
    BASE_URL = "https://public.api.careerjet.net/search"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        """board_token = country code (e.g. 'us', 'gb')."""
        country = board_token.lower() if board_token else "us"
        locale = CAREERJET_LOCALES.get(country, "en_US")

        affid = getattr(settings, "careerjet_affid", "")
        if not affid:
            # Careerjet works without affid for testing
            affid = "jobindex"

        all_jobs = []
        for page in range(1, 6):
            url = (
                f"{self.BASE_URL}"
                f"?locale_code={locale}"
                f"&page={page}"
                f"&pagesize=99"
                f"&affid={affid}"
                f"&sort=date"
            )

            try:
                data = await self._get_json(url)
            except Exception as e:
                logger.warning("Careerjet %s page %d failed: %s", country, page, str(e)[:100])
                break

            jobs_data = data.get("jobs", [])
            if not jobs_data:
                break

            for job in jobs_data:
                try:
                    all_jobs.append(self._normalize(job, country))
                except Exception as e:
                    logger.warning("Careerjet normalize failed: %s", e)

        logger.info("Careerjet %s: fetched %d jobs", country.upper(), len(all_jobs))
        return all_jobs

    def _normalize(self, job: dict, country: str) -> RawJob:
        date_posted = None
        date_str = job.get("date")
        if date_str:
            try:
                date_posted = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S GMT")
            except (ValueError, AttributeError):
                try:
                    date_posted = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

        company = job.get("company", "Unknown")
        salary = job.get("salary", "")

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job.get("url", ""),
            source_url=job.get("url", ""),
            title=job.get("title", ""),
            description_html=job.get("description", ""),
            employer_name=company,
            employer_domain=company.lower().replace(" ", "") + ".com",
            location_raw=job.get("locations", ""),
            salary_raw=salary if salary else None,
            date_posted=date_posted,
            categories=[job.get("site", "")] if job.get("site") else [],
            is_remote=None,
            raw_data=job,
        )
