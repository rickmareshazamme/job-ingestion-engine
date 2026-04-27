"""Canada Job Bank XML feed connector — Government of Canada.

Job Bank publishes daily XML of all federal/provincial/private postings.
No auth required.

Endpoint: https://www.jobbank.gc.ca/xmlfeed-{lang}.xml
"""

import logging
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

import aiohttp

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.canada_jobbank")


class CanadaJobBankConnector(BaseConnector):
    SOURCE_TYPE = "canada_jobbank_xml"
    ATS_PLATFORM = "canada_jobbank"
    URL_TEMPLATE = "https://www.jobbank.gc.ca/xmlfeed-{lang}.xml"

    async def fetch_jobs(self, board_token: str = "eng", employer_domain: str = "jobbank.gc.ca") -> list[RawJob]:
        """board_token = language code ('eng' or 'fra'). employer_domain defaults to jobbank.gc.ca."""
        lang = (board_token or "eng").lower()
        if lang not in ("eng", "fra"):
            lang = "eng"
        url = self.URL_TEMPLATE.format(lang=lang)

        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status in (404, 403, 401, 410):
                    raise PermanentError(f"HTTP {resp.status} from {url}")
                resp.raise_for_status()
                xml_text = await resp.text()
        except (aiohttp.ClientError, PermanentError) as e:
            logger.error("Canada Job Bank fetch failed: %s", e)
            return []

        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.error("Canada Job Bank XML parse failed: %s", e)
            return []

        raw_jobs = []
        # Job Bank feed wraps each posting in <source>; fall back to <item> for RSS-style feeds
        elements = root.findall(".//source") or root.findall(".//item")
        for el in elements:
            try:
                raw_jobs.append(self._normalize(el, employer_domain or "jobbank.gc.ca"))
            except Exception as e:
                logger.warning("Canada Job Bank normalize failed: %s", e)

        logger.info("Canada Job Bank (%s): fetched %d jobs", lang, len(raw_jobs))
        return raw_jobs

    def _normalize(self, el: ElementTree.Element, employer_domain: str) -> RawJob:
        def text(tag: str) -> Optional[str]:
            child = el.find(tag)
            return child.text.strip() if child is not None and child.text else None

        date_posted = None
        date_str = text("date") or text("pubDate")
        if date_str:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
                try:
                    date_posted = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

        company = text("company") or "Government of Canada"
        url = text("url") or text("link") or ""
        location_raw = text("location") or ""
        title = text("title") or ""
        description = text("description") or ""

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=text("jobid") or text("guid") or url or title,
            source_url=url,
            title=title,
            description_html=description,
            employer_name=company,
            employer_domain=employer_domain,
            location_raw=location_raw,
            salary_raw=text("salary"),
            employment_type_raw=text("employmentType"),
            date_posted=date_posted,
            categories=[c for c in [text("category")] if c],
            is_remote="remote" in location_raw.lower() or "telework" in location_raw.lower(),
            raw_data={child.tag: (child.text or "")[:500] for child in el},
        )
