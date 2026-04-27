"""Server-side rendered frontend routes.

Produces SEO-friendly HTML pages with JobPosting JSON-LD schema
for Google Jobs, Bing, and AI search indexing.
"""

from __future__ import annotations

import json
import math
from typing import Optional
from uuid import UUID

import logging
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import JobLocation, JobSalary, JobSummary
from src.db import get_session
from src.models import Employer, Job

logger = logging.getLogger("zammejobs.frontend")

router = APIRouter(tags=["Frontend"])
templates = Jinja2Templates(directory="src/templates")


UTM_PARAMS = {
    "source": "zammejobs",
    "utm_source": "zammejobs",
    "utm_medium": "referral",
}


def _append_utm(url: str) -> str:
    """Append source=zammejobs + utm_source/utm_medium to an outbound apply URL.

    Idempotent: if the URL already has a `source` or `utm_source` param, it
    is overwritten with our value rather than duplicated.
    """
    if not url:
        return url
    try:
        parts = urlparse(url)
        if not parts.scheme or not parts.netloc:
            return url
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(UTM_PARAMS)
        return urlunparse(parts._replace(query=urlencode(query)))
    except Exception:
        return url


async def _is_url_alive(url: str, timeout: float = 5.0) -> bool:
    """HEAD-request the URL with a short timeout. Returns True if 2xx/3xx."""
    if not url:
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.head(url, allow_redirects=True) as resp:
                if resp.status < 400:
                    return True
                # Some sites reject HEAD; fall back to a tiny GET
                if resp.status in (405, 501):
                    async with s.get(url, allow_redirects=True) as gresp:
                        return gresp.status < 400
                return False
    except Exception:
        return False


def _employer_fallback_url(job: Job, employer: Employer | None) -> str:
    """Where to send a user when the job's apply URL is dead."""
    if employer and employer.career_page_url:
        return employer.career_page_url
    if employer and employer.domain:
        return f"https://{employer.domain}"
    if job.employer_domain:
        # Strip pseudo-domain suffixes our connectors generate when employer domain is unknown
        d = job.employer_domain
        for suffix in (".adzuna-source.invalid", ".remoteok-source.invalid", ".remotive-source.invalid",
                       ".jooble-source.invalid", ".themuse-source.invalid", ".reed-source.invalid",
                       ".arbeitnow-source.invalid"):
            if d.endswith(suffix):
                return "/"
        return f"https://{d}"
    return "/"


def _build_json_ld(job: Job) -> str:
    """Build JobPosting JSON-LD for a job detail page."""
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": job.title,
        "description": job.description_html or job.description_text or "",
        "datePosted": str(job.date_posted)[:10] if job.date_posted else "",
        "identifier": {
            "@type": "PropertyValue",
            "name": job.employer_name,
            "value": str(job.id),
        },
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
        "directApply": True,
    }

    if job.source_url:
        schema["url"] = job.source_url

    if job.date_expires:
        schema["validThrough"] = str(job.date_expires)[:10]

    if job.salary_min or job.salary_max:
        value = {"@type": "QuantitativeValue", "unitText": (job.salary_period or "YEAR").upper()}
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

    if job.categories:
        schema["industry"] = job.categories[0]
        schema["occupationalCategory"] = ", ".join(job.categories[:3])

    if job.seniority:
        schema["experienceRequirements"] = {
            "@type": "OccupationalExperienceRequirements",
            "monthsOfExperience": {
                "intern": 0, "junior": 0, "mid": 24, "senior": 60,
                "lead": 84, "principal": 96, "director": 120, "executive": 144,
            }.get(job.seniority.lower() if job.seniority else "", 0),
        }

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


_COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "AU": "Australia",
    "CA": "Canada", "DE": "Germany", "FR": "France", "NL": "Netherlands",
    "IE": "Ireland", "IN": "India", "SG": "Singapore", "BR": "Brazil",
    "JP": "Japan", "ES": "Spain", "IT": "Italy", "MX": "Mexico",
    "NZ": "New Zealand", "PL": "Poland", "ZA": "South Africa",
    "TW": "Taiwan", "HK": "Hong Kong", "IL": "Israel", "CN": "China",
}

_ISO_TO_PATH = {
    "US": "us", "GB": "gb", "AU": "au", "CA": "ca", "DE": "de", "FR": "fr",
    "NL": "nl", "IE": "ie", "IN": "in", "SG": "sg", "BR": "br", "JP": "jp",
    "ES": "es", "IT": "it", "MX": "mx", "NZ": "nz", "PL": "pl", "ZA": "za",
    "TW": "tw", "HK": "hk", "IL": "il", "CN": "cn",
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

    # Recent jobs for ticker (5 most recent)
    recent_result = await session.execute(
        select(Job).where(Job.status == "active")
        .order_by(Job.date_posted.desc().nullslast())
        .limit(5)
    )
    recent_jobs = [_job_to_template_obj(j) for j in recent_result.scalars().all()]

    # Top employers by active job count
    job_count_subq = (
        select(Job.employer_id, func.count(Job.id).label("job_count"))
        .where(Job.status == "active")
        .group_by(Job.employer_id)
        .subquery()
    )
    top_emp_result = await session.execute(
        select(Employer, func.coalesce(job_count_subq.c.job_count, 0).label("job_count"))
        .join(job_count_subq, Employer.id == job_count_subq.c.employer_id)
        .order_by(job_count_subq.c.job_count.desc())
        .limit(12)
    )
    top_employers = [
        {
            "id": str(row[0].id),
            "name": row[0].name,
            "domain": row[0].domain,
            "logo_url": row[0].logo_url,
            "ats_platform": row[0].ats_platform,
            "job_count": row[1],
            "initial": (row[0].name[:1] or "?").upper(),
        }
        for row in top_emp_result.all()
    ]

    jobs_by_country = {r[0]: r[1] for r in country_result.all() if r[0]}

    # Build top-8 country cards with names + path slugs
    country_cards = []
    for iso, count in list(jobs_by_country.items())[:8]:
        slug = _ISO_TO_PATH.get(iso)
        if not slug:
            continue
        country_cards.append({
            "iso": iso,
            "slug": slug,
            "name": _COUNTRY_NAMES.get(iso, iso),
            "count": count,
        })

    stats = {
        "total_jobs": total_result.scalar() or 0,
        "active_jobs": active_result.scalar() or 0,
        "total_employers": employer_result.scalar() or 0,
        "jobs_by_country": jobs_by_country,
        "jobs_by_ats": {r[0]: r[1] for r in ats_result.all() if r[0]},
    }

    return templates.TemplateResponse(request, "home.html", {
        "stats": stats,
        "recent_jobs": recent_jobs,
        "top_employers": top_employers,
        "country_cards": country_cards,
    })


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
    salary_max: Optional[int] = None,
    posted_within: Optional[str] = None,  # "1d", "7d", "30d"
    sort: str = "date",
    page: int = Query(1, ge=1),
    per_page: int = 20,
    session: AsyncSession = Depends(get_session),
):
    from datetime import timedelta

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
    if salary_max:
        stmt = stmt.where(Job.salary_min <= salary_max)
        count_stmt = count_stmt.where(Job.salary_min <= salary_max)

    if posted_within:
        days_map = {"1d": 1, "7d": 7, "30d": 30}
        days = days_map.get(posted_within)
        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            stmt = stmt.where(Job.date_posted >= cutoff)
            count_stmt = count_stmt.where(Job.date_posted >= cutoff)

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
        "city": city,
        "remote": remote,
        "employment_type": employment_type,
        "seniority": seniority,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "posted_within": posted_within,
    }

    # Empty-state suggestions: top employers / categories when no results
    suggestions = []
    if total == 0 and q:
        # Find similar titles by trigram-ish ilike on word fragments
        words = [w for w in q.split() if len(w) >= 4]
        if words:
            sug_kw = or_(*[Job.title.ilike(f"%{w}%") for w in words])
            sug_result = await session.execute(
                select(Job.title, Job.id, Job.employer_name)
                .where(Job.status == "active")
                .where(sug_kw)
                .limit(5)
            )
            suggestions = [
                {"title": r[0], "id": str(r[1]), "employer_name": r[2]}
                for r in sug_result.all()
            ]

    return templates.TemplateResponse(request, "search.html", {
        "jobs": jobs,
        "q": q,
        "filters": filters,
        "meta": {"total": total, "page": page, "per_page": per_page, "total_pages": total_pages},
        "query_string": query_string,
        "suggestions": suggestions,
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

    # Similar jobs — same employer first; if not enough, top up with same primary category
    similar_stmt = (
        select(Job)
        .where(Job.status == "active")
        .where(Job.id != job.id)
        .where(Job.employer_id == job.employer_id)
        .order_by(Job.date_posted.desc().nullslast())
        .limit(5)
    )
    similar_rows = (await session.execute(similar_stmt)).scalars().all()
    if len(similar_rows) < 5 and job.categories:
        primary_cat = job.categories[0]
        topup_stmt = (
            select(Job)
            .where(Job.status == "active")
            .where(Job.id != job.id)
            .where(Job.categories.any(primary_cat))
            .order_by(Job.date_posted.desc().nullslast())
            .limit(5 - len(similar_rows))
        )
        topup_rows = (await session.execute(topup_stmt)).scalars().all()
        existing_ids = {r.id for r in similar_rows}
        for r in topup_rows:
            if r.id not in existing_ids:
                similar_rows.append(r)
                if len(similar_rows) >= 5:
                    break
    similar_jobs = [_job_to_template_obj(r) for r in similar_rows[:5]]

    # Employer panel
    employer_panel = None
    if job.employer_id:
        emp_result = await session.execute(select(Employer).where(Employer.id == job.employer_id))
        emp = emp_result.scalar_one_or_none()
        if emp:
            emp_jobs = (await session.execute(
                select(func.count()).select_from(Job)
                .where(Job.status == "active")
                .where(Job.employer_id == emp.id)
            )).scalar() or 0
            employer_panel = {
                "id": str(emp.id),
                "name": emp.name,
                "domain": emp.domain,
                "logo_url": emp.logo_url,
                "ats_platform": emp.ats_platform,
                "career_page_url": emp.career_page_url,
                "country": emp.country,
                "job_count": emp_jobs,
                "initial": (emp.name[:1] or "?").upper(),
            }

    return templates.TemplateResponse(request, "job_detail.html", {
        "job": job_obj,
        "json_ld": json_ld,
        "similar_jobs": similar_jobs,
        "employer_panel": employer_panel,
    })


@router.get("/for-ai", response_class=HTMLResponse)
async def for_ai_page(request: Request, session: AsyncSession = Depends(get_session)):
    """Integration paths for AI assistants (ChatGPT, Claude, MCP) and AI labs."""
    active_result = await session.execute(
        select(func.count()).select_from(Job).where(Job.status == "active")
    )
    employer_result = await session.execute(select(func.count()).select_from(Employer))
    countries_result = await session.execute(
        select(func.count(func.distinct(Job.location_country)))
        .where(Job.status == "active")
        .where(Job.location_country.is_not(None))
    )
    stats = {
        "active_jobs": active_result.scalar() or 0,
        "total_employers": employer_result.scalar() or 0,
        "countries": countries_result.scalar() or 0,
    }
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(request, "for_ai.html", {
        "stats": stats,
        "base": base,
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

    return templates.TemplateResponse(request, "employers.html", {
        "employers": employers,
        "q": q,
        "meta": {"total": total, "page": page, "per_page": per_page, "total_pages": total_pages},
    })


@router.get("/apply/{job_id}")
async def apply_redirect(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Live-check the job's apply URL. If it 404s or times out, mark expired
    and redirect the user to the employer's career page (or homepage)."""
    try:
        uid = UUID(job_id)
    except ValueError:
        return RedirectResponse("/", status_code=302)

    result = await session.execute(select(Job).where(Job.id == uid))
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse("/", status_code=302)

    employer = None
    if job.employer_id:
        emp_result = await session.execute(select(Employer).where(Employer.id == job.employer_id))
        employer = emp_result.scalar_one_or_none()

    target = job.source_url
    alive = await _is_url_alive(target) if target else False

    if alive:
        return RedirectResponse(_append_utm(target), status_code=302)

    # Mark the job expired and redirect to the employer's site instead.
    try:
        await session.execute(
            update(Job).where(Job.id == uid).values(status="expired", date_updated=datetime.utcnow())
        )
        await session.commit()
        logger.info("Job %s marked expired (apply URL dead): %s", job_id, target)
    except Exception as e:
        logger.warning("Failed to mark job %s expired: %s", job_id, e)

    fallback = _employer_fallback_url(job, employer)
    return RedirectResponse(_append_utm(fallback), status_code=302)
