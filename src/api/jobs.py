"""Job search and detail API endpoints."""

from __future__ import annotations

import math
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    ErrorResponse,
    JobDetail,
    JobLocation,
    JobSalary,
    JobSearchResponse,
    JobSummary,
    PaginationMeta,
)
from src.db import get_session
from src.models import Job

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


def _job_to_summary(job: Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        title=job.title,
        employer_name=job.employer_name,
        employer_domain=job.employer_domain,
        employer_logo_url=job.employer_logo_url,
        location=JobLocation(
            raw=job.location_raw,
            city=job.location_city,
            state=job.location_state,
            country=job.location_country,
            lat=job.location_lat,
            lng=job.location_lng,
            is_remote=job.is_remote,
            remote_type=job.remote_type,
        ),
        salary=JobSalary(
            min=job.salary_min,
            max=job.salary_max,
            currency=job.salary_currency,
            period=job.salary_period,
            raw=job.salary_raw,
        ),
        employment_type=job.employment_type,
        seniority=job.seniority,
        categories=job.categories or [],
        is_remote=job.is_remote,
        remote_type=job.remote_type,
        date_posted=job.date_posted,
        source_url=job.source_url,
        ats_platform=job.ats_platform,
    )


def _job_to_detail(job: Job) -> JobDetail:
    return JobDetail(
        id=job.id,
        title=job.title,
        employer_name=job.employer_name,
        employer_domain=job.employer_domain,
        employer_logo_url=job.employer_logo_url,
        location=JobLocation(
            raw=job.location_raw,
            city=job.location_city,
            state=job.location_state,
            country=job.location_country,
            lat=job.location_lat,
            lng=job.location_lng,
            is_remote=job.is_remote,
            remote_type=job.remote_type,
        ),
        salary=JobSalary(
            min=job.salary_min,
            max=job.salary_max,
            currency=job.salary_currency,
            period=job.salary_period,
            raw=job.salary_raw,
        ),
        employment_type=job.employment_type,
        seniority=job.seniority,
        categories=job.categories or [],
        is_remote=job.is_remote,
        remote_type=job.remote_type,
        date_posted=job.date_posted,
        source_url=job.source_url,
        ats_platform=job.ats_platform,
        description_html=job.description_html,
        description_text=job.description_text,
        date_expires=job.date_expires,
        date_crawled=job.date_crawled,
        date_updated=job.date_updated,
        content_hash=job.content_hash,
        status=job.status,
    )


@router.get(
    "/search",
    response_model=JobSearchResponse,
    summary="Search jobs with filters",
    description="Full-text search with location, salary, remote, category, and seniority filters.",
)
async def search_jobs(
    q: Optional[str] = Query(None, description="Search query (title, description, employer)"),
    country: Optional[str] = Query(None, description="ISO 3166-1 alpha-2 country code"),
    city: Optional[str] = Query(None, description="City name"),
    remote: Optional[bool] = Query(None, description="Filter remote jobs only"),
    remote_type: Optional[str] = Query(None, description="onsite, hybrid, or remote"),
    employment_type: Optional[str] = Query(None, description="FULL_TIME, PART_TIME, CONTRACTOR, TEMPORARY, INTERN"),
    seniority: Optional[str] = Query(None, description="intern, junior, mid, senior, lead, principal, director, executive"),
    category: Optional[str] = Query(None, description="Job category (Engineering, Data & Analytics, etc.)"),
    employer: Optional[str] = Query(None, description="Employer domain or name"),
    salary_min: Optional[int] = Query(None, ge=0, description="Minimum salary"),
    salary_max: Optional[int] = Query(None, ge=0, description="Maximum salary"),
    salary_currency: Optional[str] = Query(None, description="Salary currency code (USD, EUR, GBP, AUD)"),
    ats_platform: Optional[str] = Query(None, description="ATS platform (greenhouse, lever, workday)"),
    sort: str = Query("relevance", description="Sort by: relevance, date, salary_desc, salary_asc"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Results per page"),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Job).where(Job.status == "active")
    count_stmt = select(func.count()).select_from(Job).where(Job.status == "active")

    # Full-text search
    if q:
        search_filter = or_(
            Job.title.ilike(f"%{q}%"),
            Job.description_text.ilike(f"%{q}%"),
            Job.employer_name.ilike(f"%{q}%"),
        )
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)

    # Location filters
    if country:
        stmt = stmt.where(Job.location_country == country.upper())
        count_stmt = count_stmt.where(Job.location_country == country.upper())
    if city:
        stmt = stmt.where(Job.location_city.ilike(f"%{city}%"))
        count_stmt = count_stmt.where(Job.location_city.ilike(f"%{city}%"))

    # Remote filters
    if remote is not None:
        stmt = stmt.where(Job.is_remote == remote)
        count_stmt = count_stmt.where(Job.is_remote == remote)
    if remote_type:
        stmt = stmt.where(Job.remote_type == remote_type)
        count_stmt = count_stmt.where(Job.remote_type == remote_type)

    # Classification filters
    if employment_type:
        stmt = stmt.where(Job.employment_type == employment_type)
        count_stmt = count_stmt.where(Job.employment_type == employment_type)
    if seniority:
        stmt = stmt.where(Job.seniority == seniority)
        count_stmt = count_stmt.where(Job.seniority == seniority)
    if category:
        stmt = stmt.where(Job.categories.any(category))
        count_stmt = count_stmt.where(Job.categories.any(category))

    # Employer filter
    if employer:
        employer_filter = or_(
            Job.employer_domain.ilike(f"%{employer}%"),
            Job.employer_name.ilike(f"%{employer}%"),
        )
        stmt = stmt.where(employer_filter)
        count_stmt = count_stmt.where(employer_filter)

    # Salary filters
    if salary_min is not None:
        stmt = stmt.where(Job.salary_max >= salary_min)
        count_stmt = count_stmt.where(Job.salary_max >= salary_min)
    if salary_max is not None:
        stmt = stmt.where(Job.salary_min <= salary_max)
        count_stmt = count_stmt.where(Job.salary_min <= salary_max)
    if salary_currency:
        stmt = stmt.where(Job.salary_currency == salary_currency.upper())
        count_stmt = count_stmt.where(Job.salary_currency == salary_currency.upper())

    # ATS platform filter
    if ats_platform:
        stmt = stmt.where(Job.ats_platform == ats_platform.lower())
        count_stmt = count_stmt.where(Job.ats_platform == ats_platform.lower())

    # Sorting
    if sort == "date":
        stmt = stmt.order_by(Job.date_posted.desc().nullslast())
    elif sort == "salary_desc":
        stmt = stmt.order_by(Job.salary_max.desc().nullslast())
    elif sort == "salary_asc":
        stmt = stmt.order_by(Job.salary_min.asc().nullslast())
    else:
        # Default: newest first (relevance would need full-text ranking)
        stmt = stmt.order_by(Job.date_posted.desc().nullslast())

    # Count total
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))

    # Paginate
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    jobs = result.scalars().all()

    return JobSearchResponse(
        data=[_job_to_summary(j) for j in jobs],
        meta=PaginationMeta(
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        ),
    )


@router.get(
    "/{job_id}",
    response_model=JobDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get job details",
)
async def get_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_detail(job)
