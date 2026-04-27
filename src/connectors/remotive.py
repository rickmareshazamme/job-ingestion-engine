"""Remotive API connector — curated remote jobs.

Free, no auth required.
Endpoint: GET https://remotive.com/api/remote-jobs
Optional category filter via board_token.
"""

import logging
from datetime import datetime
from urllib.parse import urlparse

from src.connectors.base import BaseConnector, RawJob

logger = logging.getLogger("jobindex.connector.remotive")


class RemotiveConnector(BaseConnector):
    SOURCE_TYPE = "remotive_api"
    ATS_PLATFORM = "remotive"
    URL = "https://remotive.com/api/remote-jobs"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        """board_token (optional) = category filter (e.g. 'software-dev'). employer_domain ignored."""
        url = f"{self.URL}?limit=1000"
        if board_token:
            url += f"&category={board_token}"

        try:
            data = await self._get_json(url)
        except Exception as e:
            logger.error("Remotive fetch failed: %s", str(e)[:200])
            return []

        jobs_data = data.get("jobs", []) if isinstance(data, dict) else []
        raw_jobs = []
        for job in jobs_data:
            try:
                raw_jobs.append(self._normalize(job))
            except Exception as e:
                logger.warning("Remotive normalize failed: %s", e)

        logger.info("Remotive: fetched %d jobs", len(raw_jobs))
        return raw_jobs

    def _normalize(self, job: dict) -> RawJob:
        company_name = job.get("company_name") or "Unknown"
        url = job.get("url") or ""

        date_posted = None
        date_str = job.get("publication_date")
        if date_str:
            try:
                date_posted = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        category = job.get("category")
        tags = job.get("tags") or []
        categories = [c for c in [category] if c]
        categories += [t for t in tags if isinstance(t, str)]

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job.get("id") or url),
            source_url=url,
            title=job.get("title", ""),
            description_html=job.get("description", ""),
            employer_name=company_name,
            employer_domain=self._guess_domain(company_name, url),
            employer_logo_url=job.get("company_logo_url") or job.get("company_logo"),
            location_raw=job.get("candidate_required_location") or "Remote",
            salary_raw=job.get("salary") or None,
            employment_type_raw=job.get("job_type"),
            date_posted=date_posted,
            categories=categories,
            is_remote=True,
            raw_data=job,
        )

    def _guess_domain(self, company_name: str, url: str) -> str:
        try:
            host = urlparse(url).netloc
            if host and "remotive" not in host:
                return host
        except Exception:
            pass
        slug = "".join(c.lower() for c in company_name if c.isalnum() or c == "-")[:60] or "unknown"
        return f"{slug}.remotive-source.invalid"
