"""LinkedIn XML Job Feed — /feeds/linkedin.xml

Generates a Basic Jobs XML feed per LinkedIn's Limited Listings spec so
LinkedIn's crawler can ingest jobs directly. No API key, no OAuth — once
the URL is registered with a LinkedIn rep, jobs surface in LinkedIn Search.

Spec: https://learn.microsoft.com/en-us/linkedin/talent/job-postings/xml-feeds-development-guide
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_session
from src.models import Employer, Job

router = APIRouter(tags=["Feeds"])


# LinkedIn enum mappings — keys are normalized lowercase values from our DB,
# values are the exact uppercase tokens LinkedIn's schema accepts.
EMPLOYMENT_TYPE_MAP = {
    "full_time": "FULL_TIME",
    "fulltime": "FULL_TIME",
    "full-time": "FULL_TIME",
    "permanent": "FULL_TIME",
    "part_time": "PART_TIME",
    "parttime": "PART_TIME",
    "part-time": "PART_TIME",
    "contract": "CONTRACT",
    "contractor": "CONTRACT",
    "temporary": "CONTRACT",
    "temp": "CONTRACT",
    "freelance": "CONTRACT",
    "internship": "INTERNSHIP",
    "intern": "INTERNSHIP",
    "volunteer": "VOLUNTEER",
}

EXPERIENCE_LEVEL_MAP = {
    "entry": "ENTRY_LEVEL",
    "entry_level": "ENTRY_LEVEL",
    "junior": "ENTRY_LEVEL",
    "associate": "ASSOCIATE",
    "mid": "MID_SENIOR_LEVEL",
    "mid_senior": "MID_SENIOR_LEVEL",
    "senior": "MID_SENIOR_LEVEL",
    "lead": "MID_SENIOR_LEVEL",
    "staff": "MID_SENIOR_LEVEL",
    "principal": "DIRECTOR",
    "director": "DIRECTOR",
    "vp": "EXECUTIVE",
    "executive": "EXECUTIVE",
    "c_level": "EXECUTIVE",
    "internship": "INTERNSHIP",
    "intern": "INTERNSHIP",
}

WORKPLACE_TYPE_MAP = {
    "onsite": "On-site",
    "on_site": "On-site",
    "on-site": "On-site",
    "office": "On-site",
    "hybrid": "Hybrid",
    "remote": "Remote",
}

SALARY_PERIOD_MAP = {
    "yearly": "YEARLY",
    "annual": "YEARLY",
    "annually": "YEARLY",
    "year": "YEARLY",
    "monthly": "MONTHLY",
    "month": "MONTHLY",
    "semimonthly": "SEMIMONTHLY",
    "biweekly": "BIWEEKLY",
    "fortnightly": "BIWEEKLY",
    "weekly": "WEEKLY",
    "week": "WEEKLY",
    "daily": "DAILY",
    "day": "DAILY",
    "hourly": "HOURLY",
    "hour": "HOURLY",
    "once": "ONCE",
}


def _cdata(parent: etree._Element, tag: str, value: str | None) -> etree._Element | None:
    """Append a child element wrapping value in a CDATA section. Returns None
    if value is empty/None — caller decides whether the field is mandatory."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    child = etree.SubElement(parent, tag)
    child.text = etree.CDATA(text)
    return child


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    return v or None


def _build_location_string(job: Job) -> str | None:
    """LinkedIn 'location' field. Prefer the raw string if present, else
    assemble from city/state/country. Returns None if nothing usable."""
    if job.location_raw and job.location_raw.strip():
        return job.location_raw.strip()
    parts = [p for p in (job.location_city, job.location_state, job.location_country) if p]
    return ", ".join(parts) if parts else None


def _format_date(dt: datetime | None) -> str | None:
    """LinkedIn requires MM/DD/YYYY."""
    if not dt:
        return None
    return dt.strftime("%m/%d/%Y")


def _job_passes_validation(job: Job, applyUrl: str | None, description: str | None) -> bool:
    """Skip jobs LinkedIn would reject anyway. Spec rules:
      - applyUrl must be HTTPS
      - description must be >= 100 chars
      - title must be present
      - some location info must exist
    """
    if not job.title or not job.title.strip():
        return False
    if not applyUrl or not applyUrl.startswith("https://"):
        return False
    if not description or len(description.strip()) < 100:
        return False
    if not _build_location_string(job) and not job.location_country:
        return False
    return True


def _build_job_element(
    root: etree._Element,
    job: Job,
    employer: Employer | None,
) -> etree._Element | None:
    """Append a single <job> element. Returns the element or None if the
    job failed validation and was skipped."""
    apply_url = (job.source_url or "").strip() or None
    description = (job.description_html or job.description_text or "").strip() or None

    if not _job_passes_validation(job, apply_url, description):
        return None

    job_el = etree.SubElement(root, "job")

    # Mandatory fields
    _cdata(job_el, "partnerJobId", str(job.id))
    _cdata(job_el, "company", job.employer_name)
    _cdata(job_el, "title", job.title)
    _cdata(job_el, "description", description)
    _cdata(job_el, "applyUrl", apply_url)

    # Company ID — mandatory for ATS partner feeds. Pull from employer record.
    if employer and employer.linkedin_company_id:
        _cdata(job_el, "companyId", employer.linkedin_company_id)

    # Location — emit both location string AND structured city/state/country.
    # Per spec: structured fields take precedence when both are present.
    _cdata(job_el, "location", _build_location_string(job))
    _cdata(job_el, "city", job.location_city)
    _cdata(job_el, "state", job.location_state)
    _cdata(job_el, "country", job.location_country)

    # Workplace type — replaces deprecated isRemote.
    workplace = WORKPLACE_TYPE_MAP.get(_normalize(job.remote_type))
    if workplace:
        _cdata(job_el, "workplaceTypes", workplace)

    # Classification
    experience = EXPERIENCE_LEVEL_MAP.get(_normalize(job.seniority))
    if experience:
        _cdata(job_el, "experienceLevel", experience)

    jobtype = EMPLOYMENT_TYPE_MAP.get(_normalize(job.employment_type))
    if jobtype:
        _cdata(job_el, "jobtype", jobtype)

    # Salary
    period = SALARY_PERIOD_MAP.get(_normalize(job.salary_period))
    if (job.salary_min or job.salary_max) and job.salary_currency and period:
        salaries_el = etree.SubElement(job_el, "salaries")
        salary_el = etree.SubElement(salaries_el, "salary")
        if job.salary_max:
            high_el = etree.SubElement(salary_el, "highEnd")
            _cdata(high_el, "amount", str(int(job.salary_max)))
            _cdata(high_el, "currencyCode", job.salary_currency)
        if job.salary_min:
            low_el = etree.SubElement(salary_el, "lowEnd")
            _cdata(low_el, "amount", str(int(job.salary_min)))
            _cdata(low_el, "currencyCode", job.salary_currency)
        _cdata(salary_el, "period", period)
        _cdata(salary_el, "type", "BASE_SALARY")

    # Dates
    _cdata(job_el, "listDate", _format_date(job.date_posted))
    _cdata(job_el, "expirationDate", _format_date(job.date_expires))

    # Poster email — required. Per-employer override falls back to global default.
    poster_email = (employer and employer.linkedin_poster_email) or settings.linkedin_default_poster_email
    _cdata(job_el, "posterEmail", poster_email)

    return job_el


@router.get(
    "/feeds/linkedin.xml",
    response_class=Response,
    summary="LinkedIn XML Job Feed (Basic Jobs schema)",
    description=(
        "XML job feed in LinkedIn's Limited Listings format. Register this URL "
        "with your LinkedIn Talent Solutions partner contact and LinkedIn's "
        "crawler will ingest jobs daily. Defaults to claimed employers only "
        "(LinkedIn rejects aggregated/third-party-sourced feeds). Max 500K jobs "
        "per feed — split by country if you exceed that."
    ),
)
async def linkedin_feed(
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50000, ge=1, le=500000, description="Max jobs to include (LinkedIn cap is 500K)"),
    country: str | None = Query(None, description="ISO-3166 alpha-2 country code to scope the feed"),
    employer_id: str | None = Query(None, description="UUID of a single employer to scope the feed"),
    claimed_only: bool | None = Query(
        None,
        description="Override LINKEDIN_FEED_CLAIMED_ONLY. When true, only emits jobs from "
                    "self-registered employers (LinkedIn-compliant). When false, emits everything "
                    "(may be rejected as aggregated content).",
    ),
) -> Response:
    base_url = str(request.base_url).rstrip("/")
    only_claimed = settings.linkedin_feed_claimed_only if claimed_only is None else claimed_only

    stmt = (
        select(Job, Employer)
        .outerjoin(Employer, Job.employer_id == Employer.id)
        .where(Job.status == "active")
        .order_by(Job.date_posted.desc().nullslast())
        .limit(limit)
    )
    if country:
        stmt = stmt.where(Job.location_country == country.upper())
    if employer_id:
        stmt = stmt.where(Job.employer_id == employer_id)
    if only_claimed:
        stmt = stmt.where(Employer.claimed.is_(True))

    result = await session.execute(stmt)
    rows: Iterable[tuple[Job, Employer | None]] = result.all()

    root = etree.Element("source")
    etree.SubElement(root, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    etree.SubElement(root, "publisherUrl").text = base_url
    etree.SubElement(root, "publisher").text = "ZammeJobs"

    emitted = 0
    for job, employer in rows:
        if _build_job_element(root, job, employer) is not None:
            emitted += 1

    # Spec: emit expectedJobCount AFTER actual job emission so the value matches.
    expected = etree.Element("expectedJobCount")
    expected.text = etree.CDATA(str(emitted))
    # Insert after the publisher metadata so consumers see the count up front.
    root.insert(3, expected)

    xml_bytes = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )
    return Response(content=xml_bytes, media_type="application/xml")
