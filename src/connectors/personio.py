"""Personio ATS connector.

European SMB HR platform. Exposes job listings as XML.

Endpoint: GET https://{company}.jobs.personio.de/xml?language=en
Some use: GET https://{company}.jobs.personio.com/xml?language=en
"""

import logging
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.personio")


class PersonioConnector(BaseConnector):
    SOURCE_TYPE = "personio_xml"
    ATS_PLATFORM = "personio"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        # Try .de first, then .com
        for domain in ["de", "com"]:
            url = f"https://{board_token}.jobs.personio.{domain}/xml?language=en"
            logger.info("Trying Personio: %s (.%s)", board_token, domain)

            try:
                session = await self._get_session()
                async with session.get(url) as resp:
                    if resp.status == 200:
                        xml_text = await resp.text()
                        return self._parse_xml(xml_text, board_token, employer_domain, domain)
            except Exception as e:
                logger.debug("Personio .%s failed for %s: %s", domain, board_token, str(e)[:50])

        logger.warning("Personio board not found: %s", board_token)
        return []

    def _parse_xml(self, xml_text: str, board_token: str, employer_domain: str, domain: str) -> list[RawJob]:
        jobs = []

        try:
            root = ElementTree.fromstring(xml_text)

            for position in root.findall(".//position"):
                try:
                    job_id = position.findtext("id", "")
                    title = position.findtext("name", "")
                    if not title:
                        continue

                    office = position.findtext("office", "")
                    department = position.findtext("department", "")
                    schedule = position.findtext("schedule", "")
                    seniority = position.findtext("seniority", "")
                    description = position.findtext("jobDescription", "") or position.findtext("description", "")

                    date_posted = None
                    created = position.findtext("createdAt")
                    if created:
                        try:
                            date_posted = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            pass

                    apply_url = f"https://{board_token}.jobs.personio.{domain}/job/{job_id}"

                    jobs.append(RawJob(
                        source_type=self.SOURCE_TYPE,
                        source_id=str(job_id),
                        source_url=apply_url,
                        title=title,
                        description_html=description,
                        employer_name=board_token,
                        employer_domain=employer_domain,
                        location_raw=office,
                        employment_type_raw=schedule,
                        date_posted=date_posted,
                        categories=[department] if department else [],
                        is_remote="remote" in office.lower() if office else None,
                        raw_data={"id": job_id, "office": office, "department": department, "schedule": schedule},
                    ))
                except Exception as e:
                    logger.warning("Personio XML position parse failed: %s", e)

        except ElementTree.ParseError as e:
            logger.error("Personio XML parse error for %s: %s", board_token, e)

        logger.info("Personio %s: parsed %d jobs from XML", board_token, len(jobs))
        return jobs
