"""SmartRecruiters connector.

Top 7 ATS by revenue. Acquired by SAP in 2025.
Career sites have XML sitemaps at: careers.smartrecruiters.com/{company}/sitemap.xml
Public job pages at: careers.smartrecruiters.com/{company}/{jobId}

Endpoint: GET https://careers.smartrecruiters.com/{company}/sitemap.xml
"""

import logging
import re
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.smartrecruiters")


class SmartRecruitersConnector(BaseConnector):
    SOURCE_TYPE = "smartrecruiters_sitemap"
    ATS_PLATFORM = "smartrecruiters"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fetch jobs from SmartRecruiters by parsing their sitemap and API."""
        # Try the public API first
        api_url = f"https://api.smartrecruiters.com/v1/companies/{board_token}/postings"
        logger.info("Fetching jobs from SmartRecruiters: %s", board_token)

        all_jobs = []
        offset = 0
        limit = 100

        while True:
            url = f"{api_url}?offset={offset}&limit={limit}"
            try:
                data = await self._get_json(url)
            except PermanentError:
                logger.warning("SmartRecruiters API not available for %s, trying sitemap", board_token)
                return await self._fetch_from_sitemap(board_token, employer_domain)
            except Exception as e:
                logger.warning("SmartRecruiters API failed for %s: %s", board_token, str(e)[:100])
                break

            content = data.get("content", [])
            if not content:
                break

            for job in content:
                try:
                    all_jobs.append(self._normalize(job, board_token, employer_domain))
                except Exception as e:
                    logger.warning("SmartRecruiters normalize failed: %s", e)

            total = data.get("totalFound", 0)
            offset += limit
            if offset >= total:
                break

        logger.info("SmartRecruiters %s: fetched %d jobs", board_token, len(all_jobs))
        return all_jobs

    async def _fetch_from_sitemap(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fallback: parse sitemap XML for job URLs."""
        sitemap_url = f"https://careers.smartrecruiters.com/{board_token}/sitemap.xml"

        try:
            session = await self._get_session()
            async with session.get(sitemap_url) as resp:
                if resp.status != 200:
                    return []
                xml_text = await resp.text()
        except Exception as e:
            logger.warning("SmartRecruiters sitemap fetch failed for %s: %s", board_token, e)
            return []

        # Parse XML sitemap
        jobs = []
        try:
            root = ElementTree.fromstring(xml_text)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for url_el in root.findall(".//sm:url", ns):
                loc = url_el.find("sm:loc", ns)
                if loc is not None and loc.text:
                    job_url = loc.text
                    # Extract job title from URL slug
                    parts = job_url.rstrip("/").split("/")
                    if len(parts) >= 2:
                        title_slug = parts[-1]
                        title = title_slug.replace("-", " ").title()

                        lastmod = url_el.find("sm:lastmod", ns)
                        date_posted = None
                        if lastmod is not None and lastmod.text:
                            try:
                                date_posted = datetime.fromisoformat(lastmod.text[:10])
                            except (ValueError, AttributeError):
                                pass

                        jobs.append(RawJob(
                            source_type=self.SOURCE_TYPE,
                            source_id=job_url,
                            source_url=job_url,
                            title=title,
                            description_html="",
                            employer_name=board_token,
                            employer_domain=employer_domain,
                            date_posted=date_posted,
                            raw_data={"sitemap_url": job_url},
                        ))
        except ElementTree.ParseError as e:
            logger.warning("SmartRecruiters sitemap parse error for %s: %s", board_token, e)

        logger.info("SmartRecruiters %s (sitemap): found %d job URLs", board_token, len(jobs))
        return jobs

    def _normalize(self, job: dict, board_token: str, employer_domain: str) -> RawJob:
        location = job.get("location", {})
        location_parts = [
            location.get("city", ""),
            location.get("region", ""),
            location.get("country", ""),
        ]
        location_raw = ", ".join(p for p in location_parts if p)

        date_posted = None
        created = job.get("releasedDate") or job.get("createdOn")
        if created:
            try:
                date_posted = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        department = job.get("department", {}).get("label", "")
        employment_type = job.get("typeOfEmployment", {}).get("label", "")

        ref_url = job.get("ref", "")
        job_id = job.get("id", "")
        apply_url = f"https://careers.smartrecruiters.com/{board_token}/{job_id}" if job_id else ref_url

        company = job.get("company", {})
        company_name = company.get("name", board_token)

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job_id),
            source_url=apply_url,
            title=job.get("name", ""),
            description_html="",
            employer_name=company_name,
            employer_domain=employer_domain,
            location_raw=location_raw,
            employment_type_raw=employment_type,
            date_posted=date_posted,
            categories=[department] if department else [],
            is_remote=location.get("remote", False),
            raw_data=job,
        )
