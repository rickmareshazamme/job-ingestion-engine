"""Server-side rendered frontend routes.

Produces SEO-friendly HTML pages with JobPosting JSON-LD schema
for Google Jobs, Bing, and AI search indexing.
"""

from __future__ import annotations

import json
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import JobLocation, JobSalary, JobSummary
from src.db import get_session
from src.models import Employer, Job

router = APIRouter(tags=["Frontend"])
templates = Jinja2Templates(directory="src/templates")


def _build_json_ld(job: Job) -> str:
    """Build JobPosting JSON-LD for a job detail page."""
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": job.title,
        "description": job.description_text or job.description_html or "",
        "datePosted": str(job.date_posted)[:10] if job.date_posted else "",
        "hiringOrganization": {
            "@type": "Organization",
            "name": job.employer_name,
            "sameAs": f"https://{job.employer_domain}" if job.employer_domain else "",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": job.location_city or "",
                "addressRegion": job.location_state or "",
                "addressCountry": job.location_country or "",
            },
        },
        "employmentType": job.employment_type or "FULL_TIME",
    }

    if job.source_url:
        schema["url"] = job.source_url

    if job.date_expires:
        schema["validThrough"] = str(job.date_expires)[:10]

    if job.salary_min or job.salary_max:
        value = {"@type": "QuantitativeValue", "unitText": job.salary_period or "YEAR"}
        if job.salary_min:
            value["minValue"] = job.salary_min
        if job.salary_max:
            value["maxValue"] = job.salary_max
        schema["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": job.salary_currency or "USD",
            "value": value,
        }

    if job.is_remote:
        schema["jobLocationType"] = "TELECOMMUTE"
        if job.location_country:
            schema["applicantLocationRequirements"] = {
                "@type": "Country",
                "name": job.location_country,
            }

    if job.employer_logo_url:
        schema["hiringOrganization"]["logo"] = job.employer_logo_url

    return json.dumps(schema, indent=2, ensure_ascii=False)


def _job_to_template_obj(job: Job) -> dict:
    """Convert a Job model to a dict suitable for templates."""
    return {
        "id": str(job.id),
        "title": job.title,
        "employer_name": job.employer_name,
        "employer_domain": job.employer_domain,
        "employer_logo_url": job.employer_logo_url,
        "location": {
            "raw": job.location_raw,
            "city": job.location_city,
            "state": job.location_state,
            "country": job.location_country,
        },
        "salary": {
            "min": job.salary_min,
            "max": job.salary_max,
            "currency": job.salary_currency,
            "period": job.salary_period,
        },
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "categories": job.categories or [],
        "is_remote": job.is_remote,
        "remote_type": job.remote_type,
        "date_posted": job.date_posted,
        "source_url": job.source_url,
        "ats_platform": job.ats_platform,
        "description_html": job.description_html,
        "description_text": job.description_text,
    }


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request, session: AsyncSession = Depends(get_session)):
    # Fetch stats
    total_result = await session.execute(select(func.count()).select_from(Job))
    active_result = await session.execute(
        select(func.count()).select_from(Job).where(Job.status == "active")
    )
    employer_result = await session.execute(select(func.count()).select_from(Employer))

    country_result = await session.execute(
        select(Job.location_country, func.count(Job.id))
        .where(Job.status == "active")
        .group_by(Job.location_country)
        .order_by(func.count(Job.id).desc())
        .limit(20)
    )
    ats_result = await session.execute(
        select(Job.ats_platform, func.count(Job.id))
        .where(Job.status == "active")
        .group_by(Job.ats_platform)
        .order_by(func.count(Job.id).desc())
    )

    stats = {
        "total_jobs": total_result.scalar() or 0,
        "active_jobs": active_result.scalar() or 0,
        "total_employers": employer_result.scalar() or 0,
        "jobs_by_country": {r[0]: r[1] for r in country_result.all() if r[0]},
        "jobs_by_ats": {r[0]: r[1] for r in ats_result.all() if r[0]},
    }

    return templates.TemplateResponse("home.html", {"request": request, "stats": stats})


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    remote: Optional[bool] = None,
    employment_type: Optional[str] = None,
    seniority: Optional[str] = None,
    employer: Optional[str] = None,
    salary_min: Optional[int] = None,
    sort: str = "date",
    page: int = Query(1, ge=1),
    per_page: int = 20,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Job).where(Job.status == "active")
    count_stmt = select(func.count()).select_from(Job).where(Job.status == "active")

    if q:
        kw = or_(Job.title.ilike(f"%{q}%"), Job.description_text.ilike(f"%{q}%"), Job.employer_name.ilike(f"%{q}%"))
        stmt = stmt.where(kw)
        count_stmt = count_stmt.where(kw)

    if country:
        stmt = stmt.where(Job.location_country == country.upper())
        count_stmt = count_stmt.where(Job.location_country == country.upper())
    if city:
        stmt = stmt.where(Job.location_city.ilike(f"%{city}%"))
        count_stmt = count_stmt.where(Job.location_city.ilike(f"%{city}%"))
    if remote:
        stmt = stmt.where(Job.is_remote == True)
        count_stmt = count_stmt.where(Job.is_remote == True)
    if employment_type:
        stmt = stmt.where(Job.employment_type == employment_type)
        count_stmt = count_stmt.where(Job.employment_type == employment_type)
    if seniority:
        stmt = stmt.where(Job.seniority == seniority)
        count_stmt = count_stmt.where(Job.seniority == seniority)
    if employer:
        emp_f = or_(Job.employer_domain.ilike(f"%{employer}%"), Job.employer_name.ilike(f"%{employer}%"))
        stmt = stmt.where(emp_f)
        count_stmt = count_stmt.where(emp_f)
    if salary_min:
        stmt = stmt.where(Job.salary_max >= salary_min)
        count_stmt = count_stmt.where(Job.salary_max >= salary_min)

    if sort == "salary_desc":
        stmt = stmt.order_by(Job.salary_max.desc().nullslast())
    else:
        stmt = stmt.order_by(Job.date_posted.desc().nullslast())

    total = (await session.execute(count_stmt)).scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    jobs = [_job_to_template_obj(j) for j in result.scalars().all()]

    # Build query string for pagination (excluding page)
    params = {k: v for k, v in request.query_params.items() if k != "page" and v}
    query_string = "&".join(f"{k}={v}" for k, v in params.items())

    filters = {
        "country": country,
        "remote": remote,
        "employment_type": employment_type,
        "seniority": seniority,
    }

    return templates.TemplateResponse("search.html", {
        "request": request,
        "jobs": jobs,
        "q": q,
        "filters": filters,
        "meta": {"total": total, "page": page, "per_page": per_page, "total_pages": total_pages},
        "query_string": query_string,
    })


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(
    request: Request,
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        uid = UUID(job_id)
    except ValueError:
        return HTMLResponse("<h1>Invalid job ID</h1>", status_code=400)

    result = await session.execute(select(Job).where(Job.id == uid))
    job = result.scalar_one_or_none()

    if not job:
        return HTMLResponse("<h1>Job not found</h1>", status_code=404)

    job_obj = _job_to_template_obj(job)
    json_ld = _build_json_ld(job)

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job_obj,
        "json_ld": json_ld,
    })


@router.get("/employers", response_class=HTMLResponse)
async def employers_page(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = 30,
    session: AsyncSession = Depends(get_session),
):
    job_count_subq = (
        select(Job.employer_id, func.count(Job.id).label("job_count"))
        .where(Job.status == "active")
        .group_by(Job.employer_id)
        .subquery()
    )

    stmt = (
        select(Employer, func.coalesce(job_count_subq.c.job_count, 0).label("job_count"))
        .outerjoin(job_count_subq, Employer.id == job_count_subq.c.employer_id)
    )
    count_stmt = select(func.count()).select_from(Employer)

    if q:
        qf = or_(Employer.name.ilike(f"%{q}%"), Employer.domain.ilike(f"%{q}%"))
        stmt = stmt.where(qf)
        count_stmt = count_stmt.where(qf)

    stmt = stmt.order_by(func.coalesce(job_count_subq.c.job_count, 0).desc())

    total = (await session.execute(count_stmt)).scalar() or 0
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await session.execute(stmt)
    rows = result.all()

    employers = [
        {
            "id": str(row[0].id),
            "name": row[0].name,
            "domain": row[0].domain,
            "logo_url": row[0].logo_url,
            "ats_platform": row[0].ats_platform,
            "career_page_url": row[0].career_page_url,
            "country": row[0].country,
            "job_count": row[1],
        }
        for row in rows
    ]

    return templates.TemplateResponse("employers.html", {
        "request": request,
        "employers": employers,
        "q": q,
        "meta": {"total": total, "page": page, "per_page": per_page, "total_pages": total_pages},
    })
