"""Main normalization pipeline.

Converts RawJob instances from connectors/crawlers into
canonical Job model instances ready for database insertion.
"""

import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from src.connectors.base import RawJob
from src.models import Job
from src.normalizer.classification import (
    classify_categories,
    classify_employment_type,
    detect_remote,
    detect_seniority,
)
from src.normalizer.dedup import generate_content_hash
from src.normalizer.location import ParsedLocation, geocode, parse_location
from src.normalizer.salary import parse_salary


def strip_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())


async def normalize_job(raw: RawJob, do_geocode: bool = True) -> Job:
    """Normalize a RawJob into a canonical Job model instance.

    Pipeline steps:
    1. Strip HTML for description_text
    2. Parse location
    3. Geocode (if enabled)
    4. Parse salary
    5. Classify employment type
    6. Detect seniority
    7. Classify categories
    8. Detect remote work
    9. Generate content hash
    """
    # 1. Clean description
    description_text = strip_html(raw.description_html)

    # 2. Parse location
    location = parse_location(raw.location_raw or "")

    # 3. Geocode
    if do_geocode and (location.city or raw.location_raw):
        location = await geocode(location, raw.location_raw or "")

    # 4. Parse salary
    salary = parse_salary(raw.salary_raw or "")

    # 5. Employment type
    employment_type = classify_employment_type(raw.employment_type_raw)

    # 6. Seniority
    seniority = detect_seniority(raw.title)

    # 7. Categories (from ATS if available, else detect)
    categories = raw.categories if raw.categories else classify_categories(raw.title, description_text)

    # 8. Remote detection (merge with location parser result)
    is_remote_from_classification, remote_type = detect_remote(
        raw.title, raw.location_raw or "", description_text
    )
    is_remote = raw.is_remote or location.is_remote or is_remote_from_classification
    if location.remote_type != "onsite":
        remote_type = location.remote_type

    # 9. Content hash
    content_hash = generate_content_hash(
        title=raw.title,
        employer_domain=raw.employer_domain,
        location_country=location.country,
        location_city=location.city or "",
    )

    return Job(
        id=uuid.uuid4(),
        content_hash=content_hash,
        source_type=raw.source_type,
        source_id=raw.source_id,
        source_url=raw.source_url,
        ats_platform=raw.source_type.replace("_api", "").replace("_feed", ""),
        title=raw.title,
        description_html=raw.description_html,
        description_text=description_text,
        employer_name=raw.employer_name,
        employer_domain=raw.employer_domain,
        employer_logo_url=raw.employer_logo_url,
        location_raw=raw.location_raw,
        location_city=location.city,
        location_state=location.state,
        location_country=location.country or "US",
        location_lat=location.lat,
        location_lng=location.lng,
        is_remote=is_remote,
        remote_type=remote_type,
        salary_min=salary.min_value,
        salary_max=salary.max_value,
        salary_currency=salary.currency if salary.min_value else None,
        salary_period=salary.period if salary.min_value else None,
        salary_raw=raw.salary_raw,
        employment_type=employment_type,
        categories=categories,
        seniority=seniority,
        date_posted=raw.date_posted,
        date_expires=raw.date_expires,
        date_crawled=datetime.utcnow(),
        date_updated=datetime.utcnow(),
        status="active",
        raw_data=raw.raw_data,
    )
