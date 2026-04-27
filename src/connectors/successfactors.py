"""SAP SuccessFactors connector.

SuccessFactors powers ~13% of Fortune 500 — second only to Workday.
Career sites typically live at:
    {company}.successfactors.com/career
    careers.{company}.com  (white-labelled)

Discovery strategies, in order:

1. **OData JobRequisition** — `/odata/v2/JobRequisition?$filter=isActive eq true`.
   Most instances reject anonymous OData but it's free to try.

2. **Sitemap** — SuccessFactors ships an undocumented sitemap at the
   intentionally misspelled `/sitemal.xml` (typo carried over from a 2008
   SAP release) plus Adobe-named variants `/sitemap_1.xml`, `/sitemap_2.xml`...
   Each `<loc>` in the sitemap is a job-detail page; we fetch each and
   parse the embedded JSON-LD JobPosting.

3. **Standard sitemap.xml** — fallback for instances that fixed the typo.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from datetime import datetime
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

import aiohttp
from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector, PermanentError, RateLimitError, RawJob

logger = logging.getLogger("jobindex.connector.successfactors")


SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MAX_DETAIL_FETCHES = 2_000  # per-employer cap to keep crawl bounded


class SuccessFactorsConnector(BaseConnector):
    SOURCE_TYPE = "successfactors_sitemap"
    ATS_PLATFORM = "successfactors"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fetch all active jobs from a SuccessFactors instance.

        board_token: SAP customer subdomain (e.g. `siemens`, `accenture`).
        """
        host = f"{board_token}.successfactors.com"

        # 1. Try OData first
        odata_jobs = await self._try_odata(host, board_token, employer_domain)
        if odata_jobs:
            logger.info("SuccessFactors %s: %d jobs via OData", board_token, len(odata_jobs))
            return odata_jobs

        # 2. Sitemap path
        urls = await self._collect_job_urls(host)
        if not urls:
            logger.warning("SuccessFactors %s: no sitemap/job URLs found", board_token)
            return []

        urls = urls[:MAX_DETAIL_FETCHES]
        logger.info("SuccessFactors %s: %d job URLs from sitemap, hydrating", board_token, len(urls))

        jobs: list[RawJob] = []
        for url in urls:
            try:
                job = await self._fetch_detail(url, board_token, employer_domain)
                if job:
                    jobs.append(job)
            except PermanentError:
                continue
            except Exception as e:
                logger.warning("SuccessFactors detail %s failed: %s", url, str(e)[:120])

        logger.info("SuccessFactors %s: completed with %d jobs", board_token, len(jobs))
        return jobs

    # -----------------------------------------------------------------
    # OData
    # -----------------------------------------------------------------

    async def _try_odata(
        self, host: str, board_token: str, employer_domain: str
    ) -> list[RawJob]:
        url = (
            f"https://{host}/odata/v2/JobRequisition"
            "?$filter=isActive eq true&$top=200&$format=json"
        )
        try:
            data = await self._get_json(url)
        except PermanentError:
            return []
        except Exception as e:
            logger.debug("SuccessFactors OData rejected for %s: %s", host, str(e)[:80])
            return []

        results = []
        if isinstance(data, dict):
            d = data.get("d") or data
            if isinstance(d, dict):
                results = d.get("results") or []
            elif isinstance(d, list):
                results = d
        elif isinstance(data, list):
            results = data

        jobs: list[RawJob] = []
        for r in results:
            try:
                jobs.append(self._normalize_odata(r, host, board_token, employer_domain))
            except Exception as e:
                logger.warning("SuccessFactors OData normalize failed: %s", str(e)[:100])
        return jobs

    def _normalize_odata(
        self, r: dict, host: str, board_token: str, employer_domain: str
    ) -> RawJob:
        job_id = str(r.get("jobReqId") or r.get("jobReqID") or r.get("jobRequisitionId") or "")
        title = r.get("jobTitle") or r.get("title") or ""
        location = r.get("location") or r.get("city") or ""
        if isinstance(location, dict):
            location = location.get("name") or location.get("city") or ""
        description = r.get("jobDescription") or r.get("description") or ""
        if isinstance(description, dict):
            description = description.get("__cdata") or description.get("value") or ""

        date_posted = self._parse_sf_date(r.get("postingStartDate") or r.get("createdDateTime"))
        date_expires = self._parse_sf_date(r.get("postingEndDate") or r.get("validUntil"))

        source_url = (
            r.get("applyUrl")
            or r.get("jobReqLocale", {}).get("externalUrl")
            if isinstance(r.get("jobReqLocale"), dict) else r.get("applyUrl")
        )
        if not source_url:
            source_url = f"https://{host}/career?career_job_req_id={job_id}"

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job_id,
            source_url=source_url,
            title=title,
            description_html=html_lib.unescape(description) if description else "",
            employer_name=board_token,
            employer_domain=employer_domain,
            location_raw=location if isinstance(location, str) else None,
            date_posted=date_posted,
            date_expires=date_expires,
            raw_data={"odata": r},
        )

    # -----------------------------------------------------------------
    # Sitemap discovery
    # -----------------------------------------------------------------

    async def _collect_job_urls(self, host: str) -> list[str]:
        """Walk every plausible sitemap variant for `host` and return job URLs."""
        candidate_paths = [
            "/sitemal.xml",  # SAP's famous typo
            "/sitemap.xml",
        ] + [f"/sitemap_{n}.xml" for n in range(1, 11)]

        seen_xml: set[str] = set()
        urls: set[str] = set()

        # Walk top-level candidates first; recurse into <sitemap> indexes.
        queue = [f"https://{host}{p}" for p in candidate_paths]
        while queue:
            sm_url = queue.pop(0)
            if sm_url in seen_xml:
                continue
            seen_xml.add(sm_url)

            text = await self._fetch_text(sm_url)
            if not text:
                continue

            sub_sitemaps, locs = self._parse_sitemap(text)
            for sub in sub_sitemaps:
                if sub not in seen_xml:
                    queue.append(sub)
            for loc in locs:
                if self._looks_like_job_url(loc):
                    urls.add(loc)

        return sorted(urls)

    def _parse_sitemap(self, text: str) -> tuple[list[str], list[str]]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [], []

        sub: list[str] = []
        for el in root.findall(".//sm:sitemap/sm:loc", SITEMAP_NS):
            if el.text:
                sub.append(el.text.strip())

        urls: list[str] = []
        for el in root.findall(".//sm:url/sm:loc", SITEMAP_NS):
            if el.text:
                urls.append(el.text.strip())

        return sub, urls

    @staticmethod
    def _looks_like_job_url(url: str) -> bool:
        u = url.lower()
        return (
            "career_job_req_id=" in u
            or "/job/" in u
            or "/jobs/" in u
            or "jobreqid=" in u
        )

    async def _fetch_text(self, url: str) -> Optional[str]:
        async with self._semaphore:
            await self._throttle(url)
            try:
                session = await self._get_session()
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status in (404, 403, 401, 410):
                        return None
                    if resp.status >= 500:
                        return None
                    return await resp.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.debug("SuccessFactors fetch %s failed: %s", url, str(e)[:80])
                return None

    # -----------------------------------------------------------------
    # Per-job detail
    # -----------------------------------------------------------------

    async def _fetch_detail(
        self, url: str, board_token: str, employer_domain: str
    ) -> Optional[RawJob]:
        text = await self._fetch_text(url)
        if not text:
            return None

        soup = BeautifulSoup(text, "lxml")

        # 1. JSON-LD JobPosting (preferred)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string or "{}")
            except json.JSONDecodeError:
                continue
            entries = ld if isinstance(ld, list) else [ld]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("@type") != "JobPosting":
                    continue
                return self._normalize_jsonld(entry, url, board_token, employer_domain)

        # 2. Fallback: scrape title + body
        title_el = soup.find("title") or soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        m = re.search(r"career_job_req_id=(\d+)", url) or re.search(r"/job/(\d+)", url)
        job_id = m.group(1) if m else url

        body_el = soup.find("body")
        description_html = str(body_el) if body_el else ""

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job_id),
            source_url=url,
            title=title,
            description_html=description_html,
            employer_name=board_token,
            employer_domain=employer_domain,
            raw_data={"sitemap_only": True},
        )

    def _normalize_jsonld(
        self, entry: dict, url: str, board_token: str, employer_domain: str
    ) -> RawJob:
        title = entry.get("title", "")
        description = entry.get("description", "") or ""
        description_html = html_lib.unescape(description) if description else ""

        # Identifier
        ident = entry.get("identifier")
        if isinstance(ident, dict):
            job_id = str(ident.get("value") or ident.get("name") or "")
        else:
            job_id = str(ident or "")
        if not job_id:
            m = re.search(r"career_job_req_id=(\d+)", url) or re.search(r"/job/(\d+)", url)
            job_id = m.group(1) if m else url

        # Location
        location_raw = None
        location_obj = entry.get("jobLocation") or {}
        if isinstance(location_obj, list):
            location_obj = location_obj[0] if location_obj else {}
        if isinstance(location_obj, dict):
            addr = location_obj.get("address") or {}
            if isinstance(addr, dict):
                parts = [
                    addr.get("addressLocality"),
                    addr.get("addressRegion"),
                    addr.get("addressCountry"),
                ]
                location_raw = ", ".join(p for p in parts if p) or None

        # Employment type
        etype = entry.get("employmentType")
        if isinstance(etype, list):
            etype = ", ".join(str(x) for x in etype if x)

        # Salary
        salary_raw = None
        bs = entry.get("baseSalary")
        if isinstance(bs, dict):
            v = bs.get("value")
            if isinstance(v, dict):
                lo, hi = v.get("minValue"), v.get("maxValue")
                if lo or hi:
                    salary_raw = f"{lo or ''} - {hi or ''}".strip(" -")
            elif v:
                salary_raw = str(v)

        date_posted = self._parse_sf_date(entry.get("datePosted"))
        date_expires = self._parse_sf_date(entry.get("validThrough"))

        is_remote = None
        loc_type = entry.get("jobLocationType")
        if isinstance(loc_type, str) and "telecommute" in loc_type.lower():
            is_remote = True

        org = entry.get("hiringOrganization") or {}
        employer_name = (org.get("name") if isinstance(org, dict) else None) or board_token

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=str(job_id),
            source_url=url,
            title=title,
            description_html=description_html,
            employer_name=employer_name,
            employer_domain=employer_domain,
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=etype if isinstance(etype, str) else None,
            date_posted=date_posted,
            date_expires=date_expires,
            is_remote=is_remote,
            raw_data={"jsonld": entry},
        )

    @staticmethod
    def _parse_sf_date(value) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            try:
                return datetime.utcfromtimestamp(float(value) / 1000.0)
            except (ValueError, OSError):
                return None
        if isinstance(value, str):
            # OData uses /Date(1234567890000)/
            m = re.match(r"/Date\((\d+)\)/", value)
            if m:
                try:
                    return datetime.utcfromtimestamp(int(m.group(1)) / 1000.0)
                except (ValueError, OSError):
                    return None
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
                try:
                    return datetime.strptime(value[:len(fmt) + 4], fmt)
                except ValueError:
                    continue
        return None
