"""Lever ATS API connector.

Public API: https://api.lever.co/v0/postings/{company}?mode=json
No authentication required for public postings.
"""

from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, RawJob


class LeverConnector(BaseConnector):
    SOURCE_TYPE = "lever_api"
    ATS_PLATFORM = "lever"
    BASE_URL = "https://api.lever.co/v0/postings"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        url = f"{self.BASE_URL}/{board_token}?mode=json"
        jobs_data = await self._get_json(url)

        if not isinstance(jobs_data, list):
            return []

        raw_jobs = []
        for job in jobs_data:
            raw_jobs.append(self._normalize_job(job, board_token, employer_domain))

        return raw_jobs

    def _normalize_job(self, job: dict, board_token: str, employer_domain: str) -> RawJob:
        categories = job.get("categories", {})
        location_raw = categories.get("location", "")
        department = categories.get("department", "")
        team = categories.get("team", "")
        commitment = categories.get("commitment", "")

        cat_list = [c for c in [department, team] if c]

        description_parts = []
        lists = job.get("lists", [])
        for lst in lists:
            text = lst.get("text", "")
            content = lst.get("content", "")
            if text:
                description_parts.append(f"<h3>{text}</h3>")
            if content:
                description_parts.append(content)

        additional = job.get("additional", "")
        if additional:
            description_parts.append(additional)

        description_html = job.get("descriptionPlain", "")
        if description_parts:
            description_html = "\n".join(description_parts)

        created_at = job.get("createdAt")
        date_posted = None
        if created_at:
            try:
                date_posted = datetime.fromtimestamp(created_at / 1000)
            except (ValueError, TypeError, OSError):
                pass

        salary_raw = None
        salary_range = job.get("salaryRange", {})
        if salary_range:
            sr_min = salary_range.get("min")
            sr_max = salary_range.get("max")
            sr_currency = salary_range.get("currency", "")
            sr_interval = salary_range.get("interval", "")
            parts = []
            if sr_currency:
                parts.append(sr_currency)
            if sr_min:
                parts.append(str(sr_min))
            if sr_max:
                parts.append(f"- {sr_max}")
            if sr_interval:
                parts.append(sr_interval)
            salary_raw = " ".join(parts)

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job.get("id", ""),
            source_url=job.get("hostedUrl", f"https://jobs.lever.co/{board_token}/{job.get('id', '')}"),
            title=job.get("text", ""),
            description_html=description_html,
            employer_name=board_token,
            employer_domain=employer_domain,
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=commitment,
            date_posted=date_posted,
            categories=cat_list,
            is_remote="remote" in location_raw.lower() if location_raw else None,
            raw_data=job,
        )
