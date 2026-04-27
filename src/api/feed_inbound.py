"""Inbound XML/JSON job feed endpoint for distribution partners.

Accepts pushes from job-distribution platforms (VONQ, Broadbean, idibu,
eQuest, generic HR-XML feeds) so their customers' jobs flow into our
index automatically. Each partner gets a slug + shared secret. They POST
their feed; we normalize into the existing Job schema and upsert.

Partners we register with:
- VONQ            (https://www.vonq.com/become-channel-partner)
- Broadbean       (https://veritone.com/products/broadbean partner program)
- idibu           (https://idibu.com/partners)
- eQuest          (now part of VONQ — covered above)
- Generic HR-XML  (any ATS that posts the standard HR-XML 3.0 schema)

POST  /api/v1/feed/inbound/{partner_slug}
Headers:
  X-Feed-Secret: <shared secret for that partner>
  Content-Type:  application/xml | application/json | text/xml
Body:
  HR-XML / VONQ-XML / Broadbean-XML / idibu-XML / generic JSON

Returns 200 with {accepted, updated, errors} or 401 on bad secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Request
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.connectors.base import RawJob
from src.db import get_session
from src.models import Job
from src.normalizer.pipeline import normalize_job

logger = logging.getLogger("zammejobs.feed_inbound")

router = APIRouter(prefix="/api/v1/feed", tags=["Inbound Feed"])


# Each partner gets one env var: FEED_SECRET_<UPPERCASE_SLUG>=<secret>
# Examples:
#   FEED_SECRET_VONQ=abc123...
#   FEED_SECRET_BROADBEAN=def456...
#   FEED_SECRET_IDIBU=ghi789...
#   FEED_SECRET_EQUEST=jkl012...
#   FEED_SECRET_GENERIC=mno345...
KNOWN_PARTNERS = {"vonq", "broadbean", "idibu", "equest", "generic"}


def _verify_secret(partner_slug: str, presented: Optional[str]) -> bool:
    if not presented:
        return False
    expected = os.getenv(f"FEED_SECRET_{partner_slug.upper()}", "")
    if not expected:
        return False
    return hmac.compare_digest(expected, presented)


# ───────────────────────────────────────────────────────────────────────
# Parsers — each returns list[RawJob]
# ───────────────────────────────────────────────────────────────────────

def _text(el: ET.Element, *paths: str) -> str:
    """First non-empty text from any of the given XPath-ish tag paths."""
    for p in paths:
        found = el.find(p)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _parse_iso_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:25], fmt)
        except ValueError:
            continue
    return None


def parse_hrxml(xml_bytes: bytes, partner_slug: str) -> list[RawJob]:
    """HR-XML 3.0 / generic <PositionOpenings> or <jobs><job> schema.

    Tolerates the most common variants from VONQ/Broadbean/idibu/eQuest —
    they all derive from HR-XML and add their own envelope.
    """
    root = ET.fromstring(xml_bytes)
    # Strip XML namespaces — partners are inconsistent
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    # Find every job-like element
    job_nodes = (
        root.findall(".//job")
        + root.findall(".//Job")
        + root.findall(".//PositionOpening")
        + root.findall(".//Posting")
        + root.findall(".//vacancy")
    )
    raw_jobs: list[RawJob] = []
    for j in job_nodes:
        title = _text(j, "title", "Title", "JobTitle", "PositionTitle", "name")
        if not title:
            continue
        url = _text(j, "url", "URL", "ApplyURL", "applyUrl", "PositionURI", "link")
        source_id = _text(j, "id", "Id", "JobId", "ReferenceID", "reference") or url or f"{partner_slug}:{uuid4()}"
        company = _text(j, "company", "Company", "OrganizationName", "EmployerName", "hiringOrganization") or partner_slug
        domain = _text(j, "companyDomain", "EmployerDomain") or f"{company.lower().replace(' ', '')}.{partner_slug}-feed.invalid"
        location_raw = _text(j, "location", "Location", "PositionLocation", "city", "address")
        country = _text(j, "country", "Country", "CountryCode")
        date_posted = _parse_iso_date(_text(j, "datePosted", "DatePosted", "publishedAt", "PostingDate"))
        date_expires = _parse_iso_date(_text(j, "validThrough", "ExpiryDate", "ApplicationCloseDate"))
        emp_type = _text(j, "employmentType", "EmploymentType", "PositionSchedule", "jobType")
        salary_min = _text(j, "salaryMin", "SalaryMin", "MinimumPay")
        salary_max = _text(j, "salaryMax", "SalaryMax", "MaximumPay")
        salary_currency = _text(j, "salaryCurrency", "Currency") or "USD"
        salary_raw = f"{salary_currency} {salary_min}-{salary_max}".strip() if (salary_min or salary_max) else None
        description = _text(j, "description", "Description", "JobDescription", "PositionDescription", "longDescription")

        if location_raw and country and country.lower() not in location_raw.lower():
            location_raw = f"{location_raw}, {country}"

        raw_jobs.append(RawJob(
            source_type=f"{partner_slug}_feed",
            source_id=str(source_id)[:255],
            source_url=url or "",
            title=title[:500],
            description_html=description[:50000],
            employer_name=company,
            employer_domain=domain,
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=emp_type or None,
            date_posted=date_posted,
            date_expires=date_expires,
            categories=[],
            is_remote="remote" in (location_raw or "").lower() or "remote" in (emp_type or "").lower(),
            raw_data={"partner": partner_slug, "via": "feed_inbound"},
        ))
    return raw_jobs


def parse_json_feed(payload: bytes, partner_slug: str) -> list[RawJob]:
    """Generic JSON feed with a top-level `jobs` array of schema.org-ish records."""
    data = json.loads(payload)
    jobs_data = data.get("jobs") or data.get("postings") or data.get("items") or []
    if isinstance(data, list):
        jobs_data = data
    raw_jobs: list[RawJob] = []
    for j in jobs_data:
        if not isinstance(j, dict):
            continue
        title = j.get("title") or j.get("name")
        if not title:
            continue
        url = j.get("url") or j.get("applyUrl") or j.get("apply_url") or ""
        source_id = str(j.get("id") or j.get("identifier") or url or f"{partner_slug}:{uuid4()}")
        company = (j.get("hiringOrganization") or {}).get("name") if isinstance(j.get("hiringOrganization"), dict) else j.get("company") or partner_slug
        loc = j.get("jobLocation") or {}
        if isinstance(loc, list) and loc:
            loc = loc[0]
        addr = (loc or {}).get("address") if isinstance(loc, dict) else {}
        if not isinstance(addr, dict):
            addr = {}
        location_raw = ", ".join(
            v for v in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")] if v
        )
        salary = j.get("baseSalary") or {}
        if isinstance(salary, dict):
            value = salary.get("value") or {}
            if isinstance(value, dict):
                mn, mx, cur = value.get("minValue"), value.get("maxValue"), salary.get("currency", "USD")
                salary_raw = f"{cur} {mn}-{mx}".strip() if (mn or mx) else None
            else:
                salary_raw = None
        else:
            salary_raw = None

        raw_jobs.append(RawJob(
            source_type=f"{partner_slug}_feed",
            source_id=source_id[:255],
            source_url=url,
            title=str(title)[:500],
            description_html=(j.get("description") or "")[:50000],
            employer_name=company,
            employer_domain=j.get("companyDomain") or f"{(company or 'unknown').lower().replace(' ', '')}.{partner_slug}-feed.invalid",
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=j.get("employmentType"),
            date_posted=_parse_iso_date(j.get("datePosted") or ""),
            date_expires=_parse_iso_date(j.get("validThrough") or ""),
            categories=j.get("industry", []) if isinstance(j.get("industry"), list) else ([j["industry"]] if j.get("industry") else []),
            is_remote=bool(j.get("jobLocationType") == "TELECOMMUTE") if j.get("jobLocationType") else None,
            raw_data={"partner": partner_slug, "via": "feed_inbound"},
        ))
    return raw_jobs


# ───────────────────────────────────────────────────────────────────────
# Endpoint
# ───────────────────────────────────────────────────────────────────────

@router.post("/inbound/{partner_slug}", summary="Inbound feed from a distribution partner")
async def feed_inbound(
    request: Request,
    partner_slug: str = Path(..., regex="^[a-z0-9-]+$", max_length=40),
    x_feed_secret: Optional[str] = Header(None, alias="X-Feed-Secret"),
):
    """Accept a job feed from a registered distribution partner and upsert.

    Send the shared secret in the `X-Feed-Secret` header. Body can be
    HR-XML 3.0, VONQ/Broadbean/idibu XML, or a generic JSON feed with a
    top-level `jobs` array.

    Returns 200 with the count of inserted/updated rows on success.
    Returns 401 if the secret is missing or wrong.
    Returns 400 if the body cannot be parsed.
    """
    if partner_slug not in KNOWN_PARTNERS and not _verify_secret(partner_slug, x_feed_secret):
        # Unknown partner without a configured secret — reject early
        raise HTTPException(status_code=401, detail="Unknown partner or missing/invalid X-Feed-Secret")
    if not _verify_secret(partner_slug, x_feed_secret):
        raise HTTPException(status_code=401, detail="Invalid X-Feed-Secret for partner")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")

    content_type = (request.headers.get("content-type") or "").lower()
    raw_jobs: list[RawJob] = []

    try:
        if "json" in content_type or body.lstrip().startswith(b"{") or body.lstrip().startswith(b"["):
            raw_jobs = parse_json_feed(body, partner_slug)
        else:
            raw_jobs = parse_hrxml(body, partner_slug)
    except (ET.ParseError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Inbound feed parse error from %s: %s", partner_slug, str(e)[:200])
        raise HTTPException(status_code=400, detail=f"Could not parse feed body: {e}")

    if not raw_jobs:
        return {"accepted": 0, "updated": 0, "errors": 0, "message": "feed parsed but no jobs found"}

    # Persist via the existing upsert pipeline. Use a sync session because
    # normalize_job is async — simpler to do the persist in async too.
    accepted = 0
    updated = 0
    errors = 0
    new_urls: list[str] = []

    engine = create_engine(settings.database_url_sync)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as s:
        for raw in raw_jobs:
            try:
                job = await normalize_job(raw, do_geocode=False)
            except Exception as e:
                errors += 1
                logger.warning("Inbound normalize failed (%s): %s", partner_slug, str(e)[:120])
                continue

            try:
                stmt = insert(Job).values(
                    id=job.id, content_hash=job.content_hash,
                    source_type=job.source_type, source_id=job.source_id,
                    source_url=job.source_url, ats_platform=job.ats_platform,
                    title=job.title, description_html=job.description_html,
                    description_text=job.description_text,
                    employer_name=job.employer_name, employer_domain=job.employer_domain,
                    employer_logo_url=job.employer_logo_url,
                    location_raw=job.location_raw, location_city=job.location_city,
                    location_state=job.location_state, location_country=job.location_country,
                    location_lat=job.location_lat, location_lng=job.location_lng,
                    is_remote=job.is_remote, remote_type=job.remote_type,
                    salary_min=job.salary_min, salary_max=job.salary_max,
                    salary_currency=job.salary_currency, salary_period=job.salary_period,
                    salary_raw=job.salary_raw, employment_type=job.employment_type,
                    categories=job.categories, seniority=job.seniority,
                    date_posted=job.date_posted, date_expires=job.date_expires,
                    date_crawled=job.date_crawled, date_updated=job.date_updated,
                    status=job.status, raw_data=job.raw_data,
                ).on_conflict_do_update(
                    constraint="uq_source",
                    set_={
                        "title": job.title,
                        "description_html": job.description_html,
                        "salary_raw": job.salary_raw,
                        "date_updated": datetime.utcnow(),
                        "status": "active",
                        "raw_data": job.raw_data,
                    },
                )
                result = s.execute(stmt)
                if result.inserted_primary_key:
                    accepted += 1
                    new_urls.append(f"https://{settings.site_domain}/jobs/{job.id}")
                else:
                    updated += 1
            except Exception as e:
                errors += 1
                logger.warning("Inbound upsert failed (%s): %s", partner_slug, str(e)[:120])

        s.commit()

    # Best-effort AI ping for new URLs
    if new_urls:
        try:
            from src.indexing.indexnow import submit_urls as indexnow_submit
            await indexnow_submit(new_urls)
        except Exception as e:
            logger.warning("IndexNow dispatch failed for inbound feed: %s", str(e)[:120])
        try:
            from src.indexing.google import notify_url_updated
            for u in new_urls[:200]:
                await notify_url_updated(u)
        except Exception as e:
            logger.warning("Google Indexing dispatch failed for inbound feed: %s", str(e)[:120])

    logger.info("Inbound feed %s: %d new, %d updated, %d errors", partner_slug, accepted, updated, errors)
    return {"accepted": accepted, "updated": updated, "errors": errors, "partner": partner_slug}


@router.get("/inbound/{partner_slug}/health", summary="Partner-side healthcheck")
async def feed_inbound_health(partner_slug: str = Path(..., regex="^[a-z0-9-]+$", max_length=40)):
    """Partners use this to verify their secret is correctly configured.

    Returns 200 with the partner slug if the FEED_SECRET_<SLUG> env var is
    set on our side, 503 otherwise. Doesn't require the secret in the
    request — partners check this BEFORE pushing jobs.
    """
    configured = bool(os.getenv(f"FEED_SECRET_{partner_slug.upper()}"))
    if not configured:
        raise HTTPException(status_code=503, detail=f"Partner '{partner_slug}' not yet configured. Email hello@zammejobs.com")
    return {
        "partner": partner_slug,
        "endpoint": f"/api/v1/feed/inbound/{partner_slug}",
        "auth": "Send shared secret in X-Feed-Secret header",
        "accepted_formats": ["application/xml (HR-XML 3.0, VONQ, Broadbean, idibu)", "application/json"],
        "status": "ready",
    }
