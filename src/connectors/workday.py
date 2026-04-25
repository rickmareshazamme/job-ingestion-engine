"""Workday ATS connector.

Workday exposes an undocumented JSON API for public career sites:
POST https://{company}.wd{instance}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs

This is the highest-value connector — covers ~40% of Fortune 500.
The API accepts POST with pagination params and returns job listings.
"""

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.workday")


class WorkdayConnector(BaseConnector):
    SOURCE_TYPE = "workday_feed"
    ATS_PLATFORM = "workday"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """
        board_token format: "{company}|{instance}|{site}"
        Example: "microsoft|5|External"
        """
        parts = board_token.split("|")
        if len(parts) != 3:
            raise ValueError(f"Workday board_token must be 'company|instance|site', got: {board_token}")

        company, instance, site = parts
        base_url = f"https://{company}.wd{instance}.myworkdayjobs.com"
        jobs_url = f"{base_url}/wday/cxs/{company}/{site}/jobs"

        logger.info("Fetching jobs from Workday: %s (instance wd%s)", company, instance)

        all_jobs: list[RawJob] = []
        offset = 0
        limit = 20

        while True:
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }

            try:
                data = await self._post_json(jobs_url, payload)
            except PermanentError:
                logger.error("Workday career site not found: %s", jobs_url)
                return []

            job_postings = data.get("jobPostings", [])
            total = data.get("total", 0)

            for job in job_postings:
                try:
                    raw_job = self._normalize_listing(job, company, instance, site, base_url, employer_domain)
                    all_jobs.append(raw_job)
                except Exception as e:
                    logger.warning("Failed to normalize Workday listing: %s", e)

            offset += limit
            if offset >= total or not job_postings:
                break

        logger.info("Workday %s: found %d listings, fetching details...", company, len(all_jobs))

        # Fetch full details for each job
        detailed_jobs = []
        for raw_job in all_jobs:
            detailed = await self._fetch_detail(raw_job, base_url, company, site)
            detailed_jobs.append(detailed)

        logger.info("Workday %s: completed with %d jobs", company, len(detailed_jobs))
        return detailed_jobs

    async def _fetch_detail(
        self, raw_job: RawJob, base_url: str, company: str, site: str
    ) -> RawJob:
        """Fetch full job details from the detail endpoint."""
        external_path = raw_job.raw_data.get("externalPath", "")
        if not external_path:
            return raw_job

        detail_url = f"{base_url}/wday/cxs/{company}/{site}{external_path}"
        try:
            data = await self._get_json(detail_url)
            job_detail = data.get("jobPostingInfo", {})

            raw_job.description_html = job_detail.get("jobDescription", raw_job.description_html)
            raw_job.location_raw = job_detail.get("location", raw_job.location_raw)

            posted_on = job_detail.get("postedOn")
            if posted_on:
                try:
                    raw_job.date_posted = datetime.fromisoformat(posted_on.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            end_date = job_detail.get("endDate")
            if end_date:
                try:
                    raw_job.date_expires = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            time_type = job_detail.get("timeType", "")
            if time_type:
                raw_job.employment_type_raw = time_type

            remote_type = job_detail.get("remoteType", "")
            if remote_type and "remote" in remote_type.lower():
                raw_job.is_remote = True

            raw_job.raw_data.update({"jobPostingInfo": job_detail})

        except PermanentError:
            logger.warning("Job detail not found: %s", detail_url)
        except Exception as e:
            logger.warning("Failed to fetch Workday job detail %s: %s", external_path, str(e)[:100])

        return raw_job

    def _normalize_listing(
        self,
        job: dict,
        company: str,
        instance: str,
        site: str,
        base_url: str,
        employer_domain: str,
    ) -> RawJob:
        """Normalize a job listing from the search results."""
        title = job.get("title", "")
        external_path = job.get("externalPath", "")
        source_url = f"{base_url}/en-US{external_path}" if external_path else ""
        posted_on = job.get("postedOn", "")

        bullet_fields = job.get("bulletFields", [])
        location_raw = bullet_fields[0] if bullet_fields else ""

        date_posted = None
        if posted_on:
            try:
                date_posted = datetime.fromisoformat(posted_on.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=external_path or title,
            source_url=source_url,
            title=title,
            description_html="",
            employer_name=company,
            employer_domain=employer_domain,
            location_raw=location_raw,
            date_posted=date_posted,
            is_remote="remote" in location_raw.lower() if location_raw else None,
            raw_data=job,
        )
