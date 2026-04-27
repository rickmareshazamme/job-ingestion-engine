"""Oracle Taleo connector.

Legacy enterprise ATS — ~5% market share but anchored at huge employers
(banks, retail, airlines). Two URL families:

    https://{company}.taleo.net/careersection/{section_id}/jobsearch.ftl
    https://{company}.taleo.net/careersection/{section_id}/jobsearch.ftl?lang=en

Most legacy instances render plain server-side HTML with `<table id="cs_jobsTable">`.
Pagination is `?page=2`, `?page=3`...

Per-job detail at:
    https://{company}.taleo.net/careersection/{section_id}/jobdetail.ftl?job={job_id}

Some Taleo instances iframe through session-bound URLs; for those we fall
back to Playwright via `src.crawler.playwright_crawler`.

board_token formats accepted:
    "{company}.taleo.net/{section_id}"
    "{company}|{section_id}"
    "{company}"   (auto-discover the section_id by HEAD-probing common values)
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector, PermanentError, RateLimitError, RawJob

logger = logging.getLogger("jobindex.connector.taleo")


COMMON_SECTION_IDS = ["1", "2", "3", "4", "5", "10", "100", "101", "1001", "1002"]
MAX_PAGES = 50
MAX_DETAIL_FETCHES = 2_000


class TaleoConnector(BaseConnector):
    SOURCE_TYPE = "taleo_html"
    ATS_PLATFORM = "taleo"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fetch all jobs from a Taleo career section.

        Accepts `{company}.taleo.net/{section_id}`, `{company}|{section_id}`,
        or just `{company}` (auto-discovers the section_id).
        """
        host, section_id = self._parse_token(board_token)

        if not section_id:
            section_id = await self._discover_section_id(host)
            if not section_id:
                logger.warning("Taleo section_id not discoverable for %s", host)
                return []

        listings = await self._fetch_listings(host, section_id, employer_domain)
        if not listings:
            # Try Playwright fallback (some instances iframe-render)
            return await self._fetch_via_playwright(host, section_id, employer_domain)

        logger.info("Taleo %s/%s: %d listings, hydrating", host, section_id, len(listings))

        # Hydrate per-job details
        hydrated: list[RawJob] = []
        for raw in listings[:MAX_DETAIL_FETCHES]:
            try:
                detail = await self._fetch_detail(raw, host, section_id)
                hydrated.append(detail)
            except PermanentError:
                hydrated.append(raw)
            except Exception as e:
                logger.warning("Taleo detail %s failed: %s", raw.source_url, str(e)[:120])
                hydrated.append(raw)

        logger.info("Taleo %s/%s: completed with %d jobs", host, section_id, len(hydrated))
        return hydrated

    # -----------------------------------------------------------------
    # Token parsing + section_id discovery
    # -----------------------------------------------------------------

    @staticmethod
    def _parse_token(board_token: str) -> tuple[str, Optional[str]]:
        token = board_token.strip().rstrip("/")
        section_id: Optional[str] = None

        if "|" in token:
            host_part, section_id = token.split("|", 1)
            token = host_part
        elif "/" in token:
            host_part, _, section_id = token.partition("/")
            token = host_part

        if not token.endswith(".taleo.net"):
            host = f"{token}.taleo.net"
        else:
            host = token

        return host, section_id or None

    async def _discover_section_id(self, host: str) -> Optional[str]:
        session = await self._get_session()
        for sid in COMMON_SECTION_IDS:
            url = f"https://{host}/careersection/{sid}/jobsearch.ftl"
            try:
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return sid
                    # Some Taleo respond 405 on HEAD — try GET on first hit
                    if resp.status in (405, 501):
                        async with session.get(
                            url,
                            allow_redirects=True,
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as g:
                            if g.status == 200:
                                return sid
            except Exception:
                continue
        return None

    # -----------------------------------------------------------------
    # Listings
    # -----------------------------------------------------------------

    async def _fetch_listings(
        self, host: str, section_id: str, employer_domain: str
    ) -> list[RawJob]:
        all_jobs: list[RawJob] = []
        seen: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            url = (
                f"https://{host}/careersection/{section_id}/jobsearch.ftl"
                f"?lang=en&page={page}"
            )
            text = await self._fetch_text(url)
            if not text:
                break

            page_jobs = self._parse_listings_html(text, host, section_id, employer_domain)
            if not page_jobs:
                break

            new_jobs = [j for j in page_jobs if j.source_id not in seen]
            if not new_jobs:
                break
            for j in new_jobs:
                seen.add(j.source_id)
            all_jobs.extend(new_jobs)

            # If page returned < a typical page, assume done
            if len(page_jobs) < 10:
                break

        return all_jobs

    def _parse_listings_html(
        self, text: str, host: str, section_id: str, employer_domain: str
    ) -> list[RawJob]:
        soup = BeautifulSoup(text, "lxml")
        rows = []

        table = soup.find("table", id="cs_jobsTable")
        if table:
            rows = table.find_all("tr")
        if not rows:
            rows = soup.select("tr.jobsTableRow, tr[id^='job']")
        # Generic fallback
        if not rows:
            rows = soup.select("a[href*='jobdetail.ftl']")
            return self._parse_anchor_rows(rows, host, section_id, employer_domain)

        jobs: list[RawJob] = []
        for row in rows:
            link = row.find("a", href=re.compile(r"jobdetail\.ftl"))
            if not link:
                continue
            href = link.get("href", "")
            m = re.search(r"job=(\d+)", href)
            if not m:
                continue
            job_id = m.group(1)
            title = link.get_text(strip=True)
            if not title:
                continue

            cells = row.find_all("td")
            location_raw = None
            date_posted = None
            if len(cells) >= 2:
                # Best-effort: location often in column 2 or 3, posted date in last
                texts = [c.get_text(" ", strip=True) for c in cells]
                # Drop the title cell
                texts = [t for t in texts if t and t != title]
                for t in texts:
                    if not location_raw and re.search(r"[A-Z][a-z]+,?\s*[A-Z]{2,}", t):
                        location_raw = t
                    if not date_posted:
                        date_posted = self._parse_date(t)

            source_url = urljoin(f"https://{host}/", href)
            jobs.append(RawJob(
                source_type=self.SOURCE_TYPE,
                source_id=str(job_id),
                source_url=source_url,
                title=title,
                description_html="",
                employer_name=host.split(".")[0],
                employer_domain=employer_domain,
                location_raw=location_raw,
                date_posted=date_posted,
                is_remote=("remote" in location_raw.lower()) if location_raw else None,
                raw_data={"host": host, "section_id": section_id},
            ))
        return jobs

    def _parse_anchor_rows(
        self, anchors, host: str, section_id: str, employer_domain: str
    ) -> list[RawJob]:
        out: list[RawJob] = []
        for a in anchors:
            href = a.get("href", "")
            m = re.search(r"job=(\d+)", href)
            if not m:
                continue
            job_id = m.group(1)
            title = a.get_text(strip=True)
            if not title:
                continue
            source_url = urljoin(f"https://{host}/", href)
            out.append(RawJob(
                source_type=self.SOURCE_TYPE,
                source_id=job_id,
                source_url=source_url,
                title=title,
                description_html="",
                employer_name=host.split(".")[0],
                employer_domain=employer_domain,
                raw_data={"host": host, "section_id": section_id, "anchor_only": True},
            ))
        return out

    # -----------------------------------------------------------------
    # Detail
    # -----------------------------------------------------------------

    async def _fetch_detail(self, raw: RawJob, host: str, section_id: str) -> RawJob:
        text = await self._fetch_text(raw.source_url)
        if not text:
            return raw

        soup = BeautifulSoup(text, "lxml")

        # JSON-LD JobPosting if present
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string or "{}")
            except json.JSONDecodeError:
                continue
            entries = ld if isinstance(ld, list) else [ld]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("@type") != "JobPosting":
                    continue
                desc = entry.get("description") or ""
                if desc:
                    raw.description_html = html_lib.unescape(desc)
                if not raw.title and entry.get("title"):
                    raw.title = entry["title"]
                if not raw.date_posted:
                    raw.date_posted = self._parse_date(entry.get("datePosted"))
                if not raw.location_raw:
                    loc = entry.get("jobLocation") or {}
                    if isinstance(loc, list):
                        loc = loc[0] if loc else {}
                    if isinstance(loc, dict):
                        addr = loc.get("address") or {}
                        if isinstance(addr, dict):
                            parts = [
                                addr.get("addressLocality"),
                                addr.get("addressRegion"),
                                addr.get("addressCountry"),
                            ]
                            raw.location_raw = ", ".join(p for p in parts if p) or None
                etype = entry.get("employmentType")
                if etype and not raw.employment_type_raw:
                    raw.employment_type_raw = etype if isinstance(etype, str) else ", ".join(etype)
                break
            if raw.description_html:
                return raw

        # Fallback: pull the descriptor div Taleo emits
        body_el = (
            soup.find("div", id=re.compile(r"requisitionDescriptionInterface", re.I))
            or soup.find("div", class_=re.compile(r"jobDescription", re.I))
            or soup.find("div", id="ftlform")
            or soup.find("body")
        )
        if body_el:
            raw.description_html = str(body_el)

        return raw

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

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
                logger.debug("Taleo fetch %s failed: %s", url, str(e)[:80])
                return None

    @staticmethod
    def _parse_date(value) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        s = str(value).strip()
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    async def _fetch_via_playwright(
        self, host: str, section_id: str, employer_domain: str
    ) -> list[RawJob]:
        try:
            from src.crawler.playwright_crawler import PlaywrightCrawler
        except Exception as e:
            logger.warning("Taleo Playwright fallback unavailable: %s", str(e)[:100])
            return []

        url = f"https://{host}/careersection/{section_id}/jobsearch.ftl?lang=en"
        crawler = PlaywrightCrawler()
        try:
            jobs = await crawler.crawl_career_page(
                url=url,
                employer_domain=employer_domain,
                employer_name=host.split(".")[0],
                max_jobs=500,
            )
        except Exception as e:
            logger.warning("Taleo Playwright failed for %s: %s", host, str(e)[:120])
            return []
        finally:
            try:
                await crawler.close()
            except Exception:
                pass

        for j in jobs:
            j.source_type = self.SOURCE_TYPE
            if j.raw_data is None:
                j.raw_data = {}
            j.raw_data["fallback"] = "playwright"
            j.raw_data["host"] = host
            j.raw_data["section_id"] = section_id
        return jobs
