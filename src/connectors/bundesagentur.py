"""Bundesagentur für Arbeit — German Federal Employment Agency.

Germany's official job board (~800K active vacancies). Free public API,
but a well-known OAuth client token is required in headers — it ships
in their public JS, not a secret.

Endpoint:
    GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs
        ?was={Q}&page=1&size=100

Required headers:
    OAuthAccessToken: <token>            (well-known public token)
    User-Agent:       <bot UA>

Response envelope:
    {"stellenangebote": [{...}], "maxErgebnisse": 800000}

`board_token` is an optional German keyword filter (e.g.
'softwareentwickler'). Empty means everything.

Throttled to ~5 req/sec via the BaseConnector default.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import aiohttp

from src.config import settings
from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.bundesagentur")


class BundesagenturConnector(BaseConnector):
    SOURCE_TYPE = "bundesagentur_api"
    ATS_PLATFORM = "bundesagentur"

    BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
    PAGE_SIZE = 100
    MAX_PAGES = 200  # 200 * 100 = 20,000 jobs per crawl per filter

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "OAuthAccessToken": settings.bundesagentur_token,
            }
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def fetch_jobs(
        self,
        board_token: str = "",
        employer_domain: str = "",
    ) -> list[RawJob]:
        keyword = (board_token or "").strip()
        all_jobs: list[RawJob] = []
        page = 1

        while page <= self.MAX_PAGES:
            url = f"{self.BASE_URL}?page={page}&size={self.PAGE_SIZE}"
            if keyword:
                url += f"&was={quote(keyword)}"

            logger.info("Bundesagentur (%s): page %d", keyword or "ALL", page)

            try:
                data = await self._get_json(url)
            except PermanentError as e:
                logger.warning("Bundesagentur page %d permanent error: %s", page, e)
                break
            except Exception as e:
                logger.warning("Bundesagentur page %d failed: %s", page, str(e)[:120])
                break

            items = data.get("stellenangebote") if isinstance(data, dict) else None
            if not items:
                break

            for item in items:
                try:
                    all_jobs.append(self._normalize(item))
                except Exception as e:
                    logger.warning("Bundesagentur normalize failed: %s", str(e)[:120])

            # Stop when we've drained the result set
            if len(items) < self.PAGE_SIZE:
                break
            page += 1

        logger.info("Bundesagentur: fetched %d jobs (keyword=%s)", len(all_jobs), keyword or "ALL")
        return all_jobs

    def _normalize(self, item: dict) -> RawJob:
        refnr = str(item.get("refnr") or item.get("hashId") or "")
        title = item.get("titel") or item.get("beruf") or ""

        employer_name = item.get("arbeitgeber") or "Bundesagentur für Arbeit"

        location_raw = ""
        arbeitsort = item.get("arbeitsort") or {}
        if isinstance(arbeitsort, dict):
            ort = arbeitsort.get("ort") or ""
            plz = arbeitsort.get("plz") or ""
            region = arbeitsort.get("region") or ""
            land = arbeitsort.get("land") or ""
            parts = [p for p in [ort, plz, region, land] if p]
            location_raw = ", ".join(parts)

        date_posted = self._parse_date(item.get("aktuelleVeroeffentlichungsdatum"))
        date_start = self._parse_date(item.get("eintrittsdatum"))

        emp_type_parts: list[str] = []
        befristung = item.get("befristung")
        if befristung:
            emp_type_parts.append(str(befristung))
        modelle = item.get("arbeitszeitmodelle") or []
        if isinstance(modelle, list):
            emp_type_parts.extend(str(m) for m in modelle if m)
        elif isinstance(modelle, str):
            emp_type_parts.append(modelle)
        emp_type = " / ".join(emp_type_parts) if emp_type_parts else None

        # External apply URL if provided, otherwise the public Bundesagentur listing
        external_url = item.get("externeUrl") or ""
        listing_url = (
            f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
            if refnr else ""
        )
        source_url = external_url or listing_url

        categories = []
        beruf = item.get("beruf")
        if beruf:
            categories.append(str(beruf))
        branche = item.get("branche") or item.get("branchengruppe")
        if branche:
            categories.append(str(branche))

        is_remote = None
        # Bundesagentur uses German keywords for remote work
        loc_lower = location_raw.lower()
        title_lower = title.lower()
        if (
            "homeoffice" in title_lower
            or "home office" in title_lower
            or "remote" in title_lower
            or "homeoffice" in loc_lower
        ):
            is_remote = True

        # Description: only short summary is in the list payload. The full body
        # requires a per-job fetch which is too expensive at scale — leave empty
        # and let downstream consumers click through to the listing.
        description = item.get("stellenbeschreibung") or ""

        employer_domain = "arbeitsagentur.de"
        if external_url:
            d = self._domain_from_url(external_url)
            if d:
                employer_domain = d

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=refnr,
            source_url=source_url,
            title=title,
            description_html=description,
            employer_name=employer_name,
            employer_domain=employer_domain,
            location_raw=location_raw,
            employment_type_raw=emp_type,
            date_posted=date_posted,
            date_expires=None,
            categories=categories,
            is_remote=is_remote,
            raw_data={
                "refnr": refnr,
                "eintrittsdatum": item.get("eintrittsdatum"),
                "arbeitsort": arbeitsort,
                "befristung": befristung,
                "arbeitszeitmodelle": modelle,
                "externeUrl": external_url,
            },
        )

    @staticmethod
    def _parse_date(value) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.utcfromtimestamp(value / 1000.0 if value > 1e12 else value)
            except (ValueError, OSError):
                return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d.%m.%Y"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _domain_from_url(url: str) -> Optional[str]:
        try:
            from urllib.parse import urlparse
            host = urlparse(url if "://" in url else f"https://{url}").netloc
            return host.lower().lstrip("www.") or None
        except Exception:
            return None
