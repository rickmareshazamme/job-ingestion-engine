"""iCIMS Talent Platform connector.

iCIMS is a Tier-1 enterprise ATS (~11% market share, 4,000+ companies).
Career sites at:
    careers-{COMPANY}.icims.com
    {COMPANY}.icims.com/jobs

iCIMS is JS-rendered, but the portal exposes an undocumented JSON-wrapped
HTML search endpoint:

    POST https://careers-{company}.icims.com/jobs/search
    Body: {"in_iframe":1,"hashed":0,"searchKeyword":"","searchCategory":"",
           "searchLocation":"","mobile":false,"to_rows":50,"from_rows":1}

The response is a JSON envelope wrapping rendered HTML rows. We parse with
BeautifulSoup. If the unauthenticated POST is gated, fall back to Playwright.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from datetime import datetime
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector, PermanentError, RateLimitError, RawJob

logger = logging.getLogger("jobindex.connector.icims")


PAGE_SIZE = 50
MAX_PAGES = 50  # 2,500 listings per board cap; tunable


class iCIMSConnector(BaseConnector):
    SOURCE_TYPE = "icims_portal"
    ATS_PLATFORM = "icims"

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """Fetch all active jobs from an iCIMS portal.

        board_token: iCIMS subdomain — `philips`, `att`, etc.
        We try `careers-{token}.icims.com` first, then `{token}.icims.com`.
        """
        host = await self._resolve_host(board_token)
        if not host:
            logger.warning("iCIMS portal not reachable for %s", board_token)
            return []

        listings = await self._fetch_listings(host, board_token, employer_domain)
        if not listings:
            # Hidden API failed/empty → try Playwright fallback
            playwright_jobs = await self._fetch_via_playwright(host, board_token, employer_domain)
            if playwright_jobs:
                return playwright_jobs
            return []

        logger.info("iCIMS %s: %d listings, hydrating details", board_token, len(listings))

        # Hydrate full HTML descriptions per-job (best-effort)
        hydrated: list[RawJob] = []
        for raw in listings:
            try:
                detailed = await self._fetch_detail(raw, host)
                hydrated.append(detailed)
            except PermanentError:
                hydrated.append(raw)
            except Exception as e:
                logger.warning("iCIMS detail fetch failed for %s: %s", raw.source_id, str(e)[:120])
                hydrated.append(raw)

        logger.info("iCIMS %s: completed with %d jobs", board_token, len(hydrated))
        return hydrated

    async def _resolve_host(self, board_token: str) -> Optional[str]:
        """Probe both iCIMS host conventions and return the working host."""
        candidates = [
            f"careers-{board_token}.icims.com",
            f"{board_token}.icims.com",
        ]
        session = await self._get_session()
        for host in candidates:
            url = f"https://{host}/jobs/search"
            try:
                async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status < 500:
                        return host
            except Exception:
                continue
        return None

    async def _fetch_listings(
        self, host: str, board_token: str, employer_domain: str
    ) -> list[RawJob]:
        """Walk the paged JSON-wrapped HTML search endpoint."""
        url = f"https://{host}/jobs/search"
        all_jobs: list[RawJob] = []
        seen_ids: set[str] = set()

        for page in range(MAX_PAGES):
            from_row = 1 + page * PAGE_SIZE
            payload = {
                "in_iframe": 1,
                "hashed": 0,
                "searchKeyword": "",
                "searchCategory": "",
                "searchLocation": "",
                "mobile": False,
                "to_rows": PAGE_SIZE,
                "from_rows": from_row,
            }

            try:
                envelope = await self._post_envelope(url, payload)
            except PermanentError:
                logger.warning("iCIMS search 4xx on %s — aborting paging", host)
                break
            except RateLimitError:
                raise

            html_body = self._extract_html(envelope)
            if not html_body:
                break

            page_jobs = self._parse_listing_html(html_body, host, board_token, employer_domain)
            if not page_jobs:
                break

            new_jobs = [j for j in page_jobs if j.source_id not in seen_ids]
            if not new_jobs:
                break

            for j in new_jobs:
                seen_ids.add(j.source_id)
            all_jobs.extend(new_jobs)

            if len(page_jobs) < PAGE_SIZE:
                break

        return all_jobs

    async def _post_envelope(self, url: str, payload: dict) -> dict | list | str:
        """POST to iCIMS search and return parsed body.

        iCIMS sometimes responds with `application/json`, sometimes with raw
        HTML inside a `text/html` content-type. We accept both.
        """
        async with self._semaphore:
            session = await self._get_session()
            await self._throttle(url)
            headers = {
                "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            }
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 429:
                    retry_after = resp.headers.get("Retry-After")
                    raise RateLimitError(int(retry_after) if retry_after and retry_after.isdigit() else None)
                if resp.status in (404, 403, 401, 410):
                    raise PermanentError(f"HTTP {resp.status} from {url}")
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "")
                text = await resp.text()
                if "application/json" in ctype or text.lstrip().startswith("{"):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
                return text

    def _extract_html(self, envelope) -> str:
        """Pull the rendered listings HTML out of whatever iCIMS returned."""
        if isinstance(envelope, str):
            return envelope
        if isinstance(envelope, dict):
            for key in ("html", "results", "jobsTable", "data", "body", "content"):
                v = envelope.get(key)
                if isinstance(v, str) and v.strip():
                    return v
            # Some iCIMS variants nest HTML one level deeper.
            data = envelope.get("data")
            if isinstance(data, dict):
                for key in ("html", "results", "body"):
                    v = data.get(key)
                    if isinstance(v, str) and v.strip():
                        return v
        return ""

    def _parse_listing_html(
        self, html_text: str, host: str, board_token: str, employer_domain: str
    ) -> list[RawJob]:
        """Parse iCIMS listing rows out of rendered HTML."""
        # Some envelopes double-encode the HTML
        html_text = html_lib.unescape(html_text)
        soup = BeautifulSoup(html_text, "lxml")

        rows = soup.select("div.iCIMS_JobsTable, div.iCIMS_JobsTable div.row, tr.iCIMS_TableRow")
        # Fallback: any element with a data-id attribute
        if not rows:
            rows = soup.find_all(attrs={"data-id": True})

        jobs: list[RawJob] = []
        for row in rows:
            try:
                job_id = row.get("data-id") or row.get("data-job-id") or ""
                if not job_id:
                    a = row.find("a", href=re.compile(r"/jobs/(\d+)/"))
                    if a:
                        m = re.search(r"/jobs/(\d+)/", a["href"])
                        if m:
                            job_id = m.group(1)
                if not job_id:
                    continue

                title_el = row.find(class_=re.compile(r"title", re.I)) or row.find("a")
                title = (title_el.get_text(strip=True) if title_el else "").strip()
                if not title:
                    continue

                location_el = row.find(class_=re.compile(r"location", re.I))
                location_raw = location_el.get_text(" ", strip=True) if location_el else None

                date_el = row.find(class_=re.compile(r"posted|date", re.I))
                date_posted = self._parse_date(date_el.get_text(strip=True) if date_el else None)

                category_el = row.find(class_=re.compile(r"category|department", re.I))
                category = category_el.get_text(strip=True) if category_el else ""

                source_url = f"https://{host}/jobs/{job_id}/job"
                jobs.append(RawJob(
                    source_type=self.SOURCE_TYPE,
                    source_id=str(job_id),
                    source_url=source_url,
                    title=title,
                    description_html="",
                    employer_name=board_token,
                    employer_domain=employer_domain,
                    location_raw=location_raw,
                    date_posted=date_posted,
                    categories=[category] if category else [],
                    is_remote=("remote" in location_raw.lower()) if location_raw else None,
                    raw_data={"host": host, "data_id": job_id},
                ))
            except Exception as e:
                logger.warning("iCIMS row parse failed: %s", str(e)[:120])

        return jobs

    async def _fetch_detail(self, raw: RawJob, host: str) -> RawJob:
        """Fetch full job HTML from the per-job endpoint."""
        url = raw.source_url
        async with self._semaphore:
            await self._throttle(url)
            session = await self._get_session()
            try:
                async with session.get(
                    url,
                    headers={"Accept": "text/html, application/json;q=0.9"},
                ) as resp:
                    if resp.status in (404, 403, 401, 410):
                        raise PermanentError(f"HTTP {resp.status} from {url}")
                    resp.raise_for_status()
                    text = await resp.text()
            except aiohttp.ClientError as e:
                logger.warning("iCIMS detail GET failed for %s: %s", url, str(e)[:100])
                return raw

        # Detail responses can be JSON-wrapped or raw HTML
        body = text
        if text.lstrip().startswith("{"):
            try:
                env = json.loads(text)
                body = self._extract_html(env) or text
            except json.JSONDecodeError:
                pass

        body = html_lib.unescape(body)
        soup = BeautifulSoup(body, "lxml")

        # Description tends to live in #icims_content_iframe / .iCIMS_JobContent
        desc_el = (
            soup.select_one("div.iCIMS_JobContent")
            or soup.select_one("div.iCIMS_InfoMsg_Job")
            or soup.select_one("#icims_content_iframe")
            or soup.find("body")
        )
        if desc_el:
            raw.description_html = str(desc_el)

        if not raw.location_raw:
            loc = soup.find(class_=re.compile(r"location", re.I))
            if loc:
                raw.location_raw = loc.get_text(" ", strip=True)

        # JSON-LD JobPosting if iCIMS embedded one
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(ld, list):
                ld = next((x for x in ld if isinstance(x, dict) and x.get("@type") == "JobPosting"), None)
            if not ld or ld.get("@type") != "JobPosting":
                continue
            if not raw.title and ld.get("title"):
                raw.title = ld["title"]
            if ld.get("description") and not raw.description_html.strip():
                raw.description_html = html_lib.unescape(ld["description"])
            posted = ld.get("datePosted")
            if posted and not raw.date_posted:
                raw.date_posted = self._parse_date(posted)
            etype = ld.get("employmentType")
            if etype and not raw.employment_type_raw:
                raw.employment_type_raw = etype if isinstance(etype, str) else ", ".join(etype)
            base_salary = ld.get("baseSalary") or {}
            if base_salary and not raw.salary_raw:
                v = base_salary.get("value", {})
                if isinstance(v, dict):
                    parts = [str(v.get("minValue", "")), str(v.get("maxValue", ""))]
                    raw.salary_raw = " - ".join(p for p in parts if p) or None
            break

        return raw

    async def _fetch_via_playwright(
        self, host: str, board_token: str, employer_domain: str
    ) -> list[RawJob]:
        """Last-resort: render the careers homepage with Playwright."""
        try:
            from src.crawler.playwright_crawler import PlaywrightCrawler
        except Exception as e:
            logger.warning("iCIMS Playwright fallback unavailable: %s", str(e)[:100])
            return []

        url = f"https://{host}/jobs/search?ss=1"
        crawler = PlaywrightCrawler()
        try:
            jobs = await crawler.crawl_career_page(
                url=url,
                employer_domain=employer_domain,
                employer_name=board_token,
                max_jobs=500,
            )
        except Exception as e:
            logger.warning("iCIMS Playwright crawl failed for %s: %s", host, str(e)[:120])
            return []
        finally:
            try:
                await crawler.close()
            except Exception:
                pass

        # Tag with our source type
        for j in jobs:
            j.source_type = self.SOURCE_TYPE
            if j.raw_data is None:
                j.raw_data = {}
            j.raw_data["fallback"] = "playwright"
            j.raw_data["host"] = host
        return jobs

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        value = value.strip()
        # ISO 8601
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
        # Common iCIMS formats
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None
