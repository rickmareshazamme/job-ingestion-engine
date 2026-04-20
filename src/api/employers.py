"""Employer list and detail API endpoints."""

from __future__ import annotations

import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    EmployerDetail,
    EmployerListResponse,
    EmployerSummary,
    ErrorResponse,
    PaginationMeta,
)
from src.db import get_session
from src.models import Employer, Job

router = APIRouter(prefix="/api/v1/employers", tags=["Employers"])


@router.get(
    "",
    response_model=EmployerListResponse,
    summary="List employers",
    description="List employers with optional search and filtering.",
)
async def list_employers(
    q: Optional[str] = Query(None, description="Search employer name or domain"),
    country: Optional[str] = Query(None, description="Filter by HQ country"),
    ats_platform: Optional[str] = Query(None, description="Filter by ATS platform"),
    sort: str = Query("name", description="Sort by: name, job_count, recent"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    # Subquery for job counts
    job_count_subq = (
        select(
            Job.employer_id,
            func.count(Job.id).label("job_count"),
        )
        .where(Job.status == "active")
        .group_by(Job.employer_id)
        .subquery()
    )

    stmt = (
        select(
            Employer,
            func.coalesce(job_count_subq.c.job_count, 0).label("job_count"),
        )
        .outerjoin(job_count_subq, Employer.id == job_count_subq.c.employer_id)
    )

    count_stmt = select(func.count()).select_from(Employer)

    if q:
        search_filter = or_(
            Employer.name.ilike(f"%{q}%"),
            Employer.domain.ilike(f"%{q}%"),
        )
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)

    if country:
        stmt = stmt.where(Employer.country == country.upper())
        count_stmt = count_stmt.where(Employer.country == country.upper())

    if ats_platform:
        stmt = stmt.where(Employer.ats_platform == ats_platform.lower())
        count_stmt = count_stmt.where(Employer.ats_platform == ats_platform.lower())

    # Sorting
    if sort == "job_count":
        stmt = stmt.order_by(text("job_count DESC"))
    elif sort == "recent":
        stmt = stmt.order_by(Employer.created_at.desc())
    else:
        stmt = stmt.order_by(Employer.name.asc())

    # Count
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))

    # Paginate
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    rows = result.all()

    data = []
    for row in rows:
        employer = row[0]
        jc = row[1]
        data.append(EmployerSummary(
            id=employer.id,
            name=employer.name,
            domain=employer.domain,
            logo_url=employer.logo_url,
            ats_platform=employer.ats_platform,
            career_page_url=employer.career_page_url,
            country=employer.country,
            employee_count=employer.employee_count,
            claimed=employer.claimed,
            job_count=jc,
        ))

    return EmployerListResponse(
        data=data,
        meta=PaginationMeta(
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        ),
    )


@router.get(
    "/{employer_id}",
    response_model=EmployerDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get employer details",
)
async def get_employer(
    employer_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Employer).where(Employer.id == employer_id))
    employer = result.scalar_one_or_none()
    if not employer:
        raise HTTPException(status_code=404, detail="Employer not found")

    # Get job count
    count_result = await session.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.employer_id == employer_id, Job.status == "active")
    )
    job_count = count_result.scalar() or 0

    return EmployerDetail(
        id=employer.id,
        name=employer.name,
        domain=employer.domain,
        logo_url=employer.logo_url,
        ats_platform=employer.ats_platform,
        career_page_url=employer.career_page_url,
        country=employer.country,
        employee_count=employer.employee_count,
        claimed=employer.claimed,
        job_count=job_count,
        created_at=employer.created_at,
        updated_at=employer.updated_at,
    )


@router.get(
    "/{employer_id}/jobs",
    summary="List jobs for a specific employer",
)
async def get_employer_jobs(
    employer_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    # Verify employer exists
    emp_result = await session.execute(select(Employer).where(Employer.id == employer_id))
    if not emp_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Employer not found")

    stmt = (
        select(Job)
        .where(Job.employer_id == employer_id, Job.status == "active")
        .order_by(Job.date_posted.desc().nullslast())
    )

    count_stmt = (
        select(func.count())
        .select_from(Job)
        .where(Job.employer_id == employer_id, Job.status == "active")
    )

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))

    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    jobs = result.scalars().all()

    from src.api.jobs import _job_to_summary

    return {
        "data": [_job_to_summary(j) for j in jobs],
        "meta": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        },
    }
