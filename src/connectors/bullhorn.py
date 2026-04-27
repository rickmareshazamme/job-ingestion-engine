"""Bullhorn Staffing ATS connector.

Bullhorn is the #1 staffing-agency ATS globally. Each staffing customer
exposes a public job board at:

    https://{company}.bullhornstaffing.com/jobs

That board is a thin React app that bootstraps with a `corporationId`
(also called `cluster_id`) and then pulls jobs from a public REST
endpoint:

    https://public-rest{N}.bullhornstaffing.com/rest-services/{corpId}/query/JobBoardPost
        ?fields=id,title,publicDescription,address,publishedCategory,
                publishedZip,salary,salaryUnit,dateLastPublished
        &where=isPublic=1
        &start=0&count=200

No auth required for the public board path. We:

1. Scrape the public job board HTML for `corporationId` + `swimlane`
   (which determines which `public-rest{N}` shard to use). Both are
   embedded in a config script tag the React widget reads at boot.
2. Hit the JobBoardPost query endpoint, paginated via `start=` until
   we exhaust the result set.

Volume: 500K-1M jobs across major staffing agencies (Adecco, Randstad,
Robert Half, Insight Global, Aerotek, etc).
"""

from __future__ import annotations

import csv
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp

from src.config import settings
from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.bullhorn")

# `data/bullhorn_corps.txt` is a CSV of pre-discovered (slug, corp_id,
# swimlane, public_url, name) tuples. Lets us skip the HTML scrape and
# hit public-rest directly. One line per staffing-agency board. Comments
# start with #. Created by scripts/discover_bullhorn.py.
_CORP_TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "bullhorn_corps.txt"


def _load_corp_table() -> dict[str, dict]:
    """Load Bullhorn customer table from data/bullhorn_corps.txt.

    Format: slug,public_corp_token,swimlane,public_url,name,internal_cluster_id

    The PUBLIC_CORP_TOKEN (column 2, e.g. "51ha21") is what works on the
    public-rest API. The internal_cluster_id is the numeric admin-panel
    ID — it's stored for reference but cannot be used directly without
    a Partner BhRestToken.

    Rows missing the public_corp_token are skipped — they need the token
    obtained from each customer first.
    """
    if not _CORP_TABLE_PATH.exists():
        return {}
    table: dict[str, dict] = {}
    skipped = 0
    with open(_CORP_TABLE_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(
            (l for l in f if l.strip() and not l.startswith("#")),
            fieldnames=["slug", "public_corp_token", "swimlane", "public_url", "name", "internal_cluster_id"],
        )
        for row in reader:
            slug = (row.get("slug") or "").strip().lower()
            token = (row.get("public_corp_token") or "").strip()
            if not slug:
                continue
            if not token:
                skipped += 1
                continue
            table[slug] = {
                "corp_id": token,  # what we send to public-rest
                "swimlane": (row.get("swimlane") or "").strip() or None,
                "public_url": (row.get("public_url") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "internal_cluster_id": (row.get("internal_cluster_id") or "").strip(),
            }
    logger.info("Bullhorn corp table: loaded %d entries (%d skipped — missing public_corp_token)", len(table), skipped)
    return table


# Loaded once at import — refresh by restarting the worker.
CORP_TABLE = _load_corp_table()


class BullhornConnector(BaseConnector):
    SOURCE_TYPE = "bullhorn_api"
    ATS_PLATFORM = "bullhorn"

    PAGE_SIZE = 200
    MAX_PAGES = 50  # cap any single board at 10K jobs per crawl

    FIELDS = ",".join([
        "id",
        "title",
        "publicDescription",
        "address",
        "publishedCategory",
        "publishedZip",
        "salary",
        "salaryUnit",
        "dateLastPublished",
        "employmentType",
        "isOpen",
        "isPublic",
    ])

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
            }
            if settings.bullhorn_partner_token:
                headers["BhRestToken"] = settings.bullhorn_partner_token
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def fetch_jobs(self, board_token: str, employer_domain: str) -> list[RawJob]:
        """board_token can be:
          - a slug listed in data/bullhorn_corps.txt → fast path, skip HTML scrape
          - a bare slug → fall back to scraping {slug}.bullhornstaffing.com/jobs
          - a literal "corp_id@swimlane" pair → hit REST directly with that tuple
        """
        if not board_token:
            logger.warning("Bullhorn: no board_token provided")
            return []

        corp_id: Optional[str] = None
        swimlane: Optional[str] = None
        public_url: Optional[str] = None

        # 1. Fast path: literal "corp_token@swimlane" passed in (corp_token may be
        #    alphanumeric like "51ha21" — only the swimlane must be a number)
        if "@" in board_token and board_token.rsplit("@", 1)[1].isdigit():
            corp_id, swimlane = board_token.rsplit("@", 1)
        # 2. Fast path: slug exists in data/bullhorn_corps.txt
        elif board_token.lower() in CORP_TABLE:
            row = CORP_TABLE[board_token.lower()]
            corp_id = row.get("corp_id") or None
            swimlane = row.get("swimlane")
            public_url = row.get("public_url") or None
        # 3. Slow path: scrape the public board
        else:
            try:
                corp_id, swimlane = await self._discover_board(board_token)
            except PermanentError as e:
                logger.warning("Bullhorn board %s unavailable: %s", board_token, e)
                return []
            except Exception as e:
                logger.error("Bullhorn board %s discovery failed: %s", board_token, str(e)[:200])
                return []

        if not corp_id:
            logger.warning("Bullhorn board %s: corporationId not found", board_token)
            return []

        rest_host = f"public-rest{swimlane}.bullhornstaffing.com" if swimlane else "public-rest40.bullhornstaffing.com"
        all_jobs: list[RawJob] = []
        start = 0
        page = 0

        while page < self.MAX_PAGES:
            url = (
                f"https://{rest_host}/rest-services/{corp_id}/query/JobBoardPost"
                f"?fields={self.FIELDS}"
                f"&where=isPublic%3D1%20AND%20isOpen%3Dtrue"
                f"&start={start}&count={self.PAGE_SIZE}"
                f"&orderBy=-dateLastPublished"
            )
            logger.info("Bullhorn %s: page %d (start=%d)", board_token, page + 1, start)

            try:
                data = await self._get_json(url)
            except PermanentError as e:
                logger.warning("Bullhorn %s page %d permanent error: %s", board_token, page + 1, e)
                break
            except Exception as e:
                logger.warning("Bullhorn %s page %d failed: %s", board_token, page + 1, str(e)[:120])
                break

            items = data.get("data") if isinstance(data, dict) else None
            if not items:
                break

            for item in items:
                try:
                    all_jobs.append(self._normalize(item, board_token, employer_domain, corp_id))
                except Exception as e:
                    logger.warning("Bullhorn normalize failed for %s: %s", board_token, str(e)[:120])

            if len(items) < self.PAGE_SIZE:
                break

            start += self.PAGE_SIZE
            page += 1

        logger.info("Bullhorn %s: fetched %d jobs", board_token, len(all_jobs))
        return all_jobs

    async def _discover_board(self, board_token: str) -> tuple[Optional[str], Optional[str]]:
        """Scrape the public board HTML for corporationId + swimlane.

        Returns (corp_id, swimlane). swimlane may be None — caller defaults.
        """
        url = f"https://{board_token}.bullhornstaffing.com/jobs"
        session = await self._get_session()
        async with session.get(url) as resp:
            if resp.status in (404, 403, 410):
                raise PermanentError(f"HTTP {resp.status} from {url}")
            resp.raise_for_status()
            html = await resp.text()

        corp_id = None
        swimlane = None

        m = re.search(r'["\']corporationId["\']\s*:\s*["\']?(\d+)', html)
        if m:
            corp_id = m.group(1)
        else:
            m = re.search(r'corporationId\s*=\s*["\']?(\d+)', html)
            if m:
                corp_id = m.group(1)

        m = re.search(r'["\']swimlane["\']\s*:\s*["\']?(\d+)', html)
        if m:
            swimlane = m.group(1)
        else:
            m = re.search(r'public-rest(\d+)\.bullhornstaffing\.com', html)
            if m:
                swimlane = m.group(1)

        return corp_id, swimlane

    def _normalize(
        self,
        item: dict,
        board_token: str,
        employer_domain: str,
        corp_id: str,
    ) -> RawJob:
        job_id = str(item.get("id", ""))

        date_posted: Optional[datetime] = None
        ts = item.get("dateLastPublished")
        if ts:
            try:
                # Bullhorn uses unix epoch in ms
                date_posted = datetime.utcfromtimestamp(int(ts) / 1000.0)
            except (ValueError, TypeError, OSError):
                pass

        address = item.get("address") or {}
        city = address.get("city") or ""
        state = address.get("state") or ""
        country = address.get("countryName") or address.get("countryCode") or ""
        zip_code = item.get("publishedZip") or address.get("zip") or ""
        location_parts = [p for p in [city, state, country] if p]
        location_raw = ", ".join(location_parts) if location_parts else (zip_code or "")

        salary_raw: Optional[str] = None
        sal = item.get("salary")
        sal_unit = item.get("salaryUnit") or ""
        if sal:
            try:
                sal_n = float(sal)
                if sal_n > 0:
                    salary_raw = f"{sal_n:.0f} {sal_unit}".strip()
            except (TypeError, ValueError):
                pass

        category = item.get("publishedCategory") or {}
        category_name = category.get("name") if isinstance(category, dict) else None

        emp_type = item.get("employmentType") or ""

        # Source URL: the public-facing job detail page on the company board
        source_url = f"https://{board_token}.bullhornstaffing.com/jobs/{job_id}"

        is_remote = None
        loc_lower = location_raw.lower()
        desc_text = (item.get("publicDescription") or "").lower()
        if "remote" in loc_lower or "work from home" in desc_text or "remote" in desc_text[:500]:
            is_remote = True

        # Employer: a Bullhorn corporate board lists the staffing agency itself
        # as employer. The agency is the recruiter — actual end-client is often
        # confidential. Use the board_token as employer name.
        employer_name = board_token.replace("-", " ").title()

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job_id,
            source_url=source_url,
            title=item.get("title", ""),
            description_html=item.get("publicDescription", "") or "",
            employer_name=employer_name,
            employer_domain=employer_domain or f"{board_token}.bullhornstaffing.com",
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=emp_type,
            date_posted=date_posted,
            categories=[category_name] if category_name else [],
            is_remote=is_remote,
            raw_data={
                "id": job_id,
                "corp_id": corp_id,
                "address": address,
                "category": category_name,
                "salary": sal,
                "salaryUnit": sal_unit,
            },
        )
