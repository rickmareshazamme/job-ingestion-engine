"""EURES — European Job Mobility Portal.

Operated by the European Commission. ~3M active jobs across 31 EU/EEA
countries. Free, no auth required, but a soft global rate limit of
~30 requests/sec. We throttle to ~5 req/sec via the BaseConnector
default.

Endpoint: GET https://europa.eu/eures/eures-apps/searchengine/page/jobs/search

Each call returns up to 50 vacancies in a JSON envelope:

    {"jvs": [{...}, ...], "totalCount": 1234567}

Pagination is `&page=N` (zero-indexed). We bound this with `MAX_PAGES`
to avoid runaway crawls — at 100 pages * 50 = 5,000 jobs/country/run,
which is enough for steady-state delta crawls when run frequently.

`board_token` is an optional ISO alpha-2 country code ('DE', 'FR', etc).
If empty, fan out across all 31 EU/EEA countries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("jobindex.connector.eures")


# EU + EEA countries supported by EURES
EU_EEA_COUNTRIES = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    # EEA / EFTA
    "IS", "LI", "NO", "CH",
]


class EuresConnector(BaseConnector):
    SOURCE_TYPE = "eures_api"
    ATS_PLATFORM = "eures"

    BASE_URL = "https://europa.eu/eures/eures-apps/searchengine/page/jobs/search"
    PAGE_SIZE = 50
    MAX_PAGES_PER_COUNTRY = 100  # 5,000 jobs/country/run — safe steady-state cap
    MAX_PAGES_GLOBAL = 200  # if no country filter, hard cap

    async def fetch_jobs(
        self,
        board_token: str = "",
        employer_domain: str = "",
    ) -> list[RawJob]:
        """board_token is an optional ISO alpha-2 country code ('DE', 'FR').

        If empty, iterate across all EU/EEA countries with per-country caps.
        """
        country = (board_token or "").strip().upper()
        all_jobs: list[RawJob] = []

        if country:
            jobs = await self._fetch_country(country, self.MAX_PAGES_PER_COUNTRY)
            all_jobs.extend(jobs)
        else:
            for c in EU_EEA_COUNTRIES:
                try:
                    jobs = await self._fetch_country(c, self.MAX_PAGES_PER_COUNTRY)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning("EURES country %s failed: %s", c, str(e)[:120])
                    continue

        logger.info("EURES: fetched %d jobs (country=%s)", len(all_jobs), country or "ALL")
        return all_jobs

    async def _fetch_country(self, country: str, max_pages: int) -> list[RawJob]:
        jobs: list[RawJob] = []
        page = 0

        while page < max_pages:
            url = (
                f"{self.BASE_URL}"
                f"?index=jv-se-job-search"
                f"&page={page}"
                f"&resultsPerPage={self.PAGE_SIZE}"
                f"&sortField=PUBLICATION_DATE_DESC"
            )
            if country:
                url += f"&country={country}"

            logger.info("EURES %s: page %d", country or "ALL", page + 1)

            try:
                data = await self._get_json(url)
            except PermanentError as e:
                logger.warning("EURES %s page %d permanent error: %s", country, page + 1, e)
                break
            except Exception as e:
                logger.warning("EURES %s page %d failed: %s", country, page + 1, str(e)[:120])
                break

            jvs = data.get("jvs") if isinstance(data, dict) else None
            if not jvs:
                break

            for jv in jvs:
                try:
                    jobs.append(self._normalize(jv))
                except Exception as e:
                    logger.warning("EURES normalize failed: %s", str(e)[:120])

            if len(jvs) < self.PAGE_SIZE:
                break
            page += 1

        return jobs

    def _normalize(self, jv: dict) -> RawJob:
        job_id = str(jv.get("id") or jv.get("reference") or "")

        title = jv.get("title") or ""
        desc_short = jv.get("descriptionShort") or ""
        desc_full = jv.get("descriptionFull") or jv.get("description") or ""
        description = desc_full or desc_short

        employer = jv.get("employer") or {}
        if isinstance(employer, dict):
            employer_name = employer.get("name") or ""
        else:
            employer_name = ""
        if not employer_name:
            employer_name = "EURES Employer"

        # Domain fallback to europa.eu if employer has none
        employer_domain = "europa.eu"
        if isinstance(employer, dict):
            site = employer.get("website") or employer.get("url") or ""
            if site:
                employer_domain = self._domain_from_url(site) or employer_domain

        # Location
        locations = jv.get("locations") or []
        loc_parts: list[str] = []
        country_code: Optional[str] = None
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            city = (loc.get("city") or {}).get("name") if isinstance(loc.get("city"), dict) else loc.get("city")
            region = (loc.get("region") or {}).get("name") if isinstance(loc.get("region"), dict) else loc.get("region")
            country = (loc.get("country") or {})
            country_alpha = country.get("alpha2Code") if isinstance(country, dict) else None
            country_name = country.get("name") if isinstance(country, dict) else None
            country_code = country_code or country_alpha
            piece = ", ".join([p for p in [city, region, country_name or country_alpha] if p])
            if piece:
                loc_parts.append(piece)
        location_raw = " | ".join(loc_parts) if loc_parts else (country_code or "")

        date_posted = self._parse_date(jv.get("releaseDate") or jv.get("publicationDate"))
        date_expires = self._parse_date(jv.get("expiryDate") or jv.get("endDate"))

        salary_raw: Optional[str] = None
        sal = jv.get("salary")
        if isinstance(sal, dict):
            mn = sal.get("min")
            mx = sal.get("max")
            cur = sal.get("currency") or ""
            period = sal.get("period") or ""
            if mn or mx:
                salary_raw = f"{mn or ''}-{mx or ''} {cur} {period}".strip()
        elif isinstance(sal, str):
            salary_raw = sal

        emp_type_codes = jv.get("positionScheduleCodes") or jv.get("positionScheduleCode") or []
        if isinstance(emp_type_codes, list):
            emp_type = ",".join(str(c) for c in emp_type_codes)
        else:
            emp_type = str(emp_type_codes)

        # Construct source URL
        source_url = jv.get("url") or jv.get("vacancyUrl") or ""
        if not source_url and job_id:
            source_url = f"https://europa.eu/eures/portal/jv-se/jv-details/{job_id}"

        categories: list[str] = []
        sectors = jv.get("nace") or jv.get("sectors") or []
        if isinstance(sectors, list):
            for s in sectors[:5]:
                if isinstance(s, dict):
                    name = s.get("name") or s.get("code")
                    if name:
                        categories.append(str(name))
                elif isinstance(s, str):
                    categories.append(s)

        is_remote = None
        if isinstance(jv.get("teleworking"), bool):
            is_remote = jv["teleworking"]
        elif "remote" in (description or "").lower()[:500]:
            is_remote = True

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=job_id,
            source_url=source_url,
            title=title,
            description_html=description,
            employer_name=employer_name,
            employer_domain=employer_domain,
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=emp_type,
            date_posted=date_posted,
            date_expires=date_expires,
            categories=categories,
            is_remote=is_remote,
            raw_data={
                "id": job_id,
                "country": country_code,
                "employer": employer if isinstance(employer, dict) else None,
                "education_level": jv.get("requiredEducationLevelCode"),
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
            for fmt in (None,):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    pass
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
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
