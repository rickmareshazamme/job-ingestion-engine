"""MCP Server for the Job Index.

Exposes job search and retrieval as tools that AI assistants
(Claude, ChatGPT, etc.) can call directly via the Model Context Protocol.

Usage:
    # stdio (for Claude Desktop / local MCP clients)
    python -m src.mcp_server.server

    # HTTP (for remote/deployed access)
    python -m src.mcp_server.server --transport http --port 8001
"""

from __future__ import annotations

import json
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from src.mcp_server.nl_parser import parse_natural_language

mcp = FastMCP(
    name="job-index",
    instructions=(
        "This server provides access to a global job index containing millions of "
        "job listings from corporate ATS platforms (Greenhouse, Lever, Workday, etc.) "
        "that are normally invisible to AI search. Use these tools to find jobs for users."
    ),
)


def _get_db_session():
    """Create a sync database session for MCP tool calls."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.config import settings

    engine = create_engine(settings.database_url_sync)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _search_jobs_db(
    keywords: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    is_remote: Optional[bool] = None,
    remote_type: Optional[str] = None,
    employment_type: Optional[str] = None,
    seniority: Optional[str] = None,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    salary_currency: Optional[str] = None,
    employer: Optional[str] = None,
    category: Optional[str] = None,
    ats_platform: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    """Execute a job search against the database."""
    from sqlalchemy import func, or_, select

    from src.models import Job

    session = _get_db_session()
    try:
        stmt = select(Job).where(Job.status == "active")
        count_stmt = select(func.count()).select_from(Job).where(Job.status == "active")

        if keywords:
            kw_filter = or_(
                Job.title.ilike(f"%{keywords}%"),
                Job.description_text.ilike(f"%{keywords}%"),
                Job.employer_name.ilike(f"%{keywords}%"),
            )
            stmt = stmt.where(kw_filter)
            count_stmt = count_stmt.where(kw_filter)

        if country:
            stmt = stmt.where(Job.location_country == country.upper())
            count_stmt = count_stmt.where(Job.location_country == country.upper())

        if city:
            stmt = stmt.where(Job.location_city.ilike(f"%{city}%"))
            count_stmt = count_stmt.where(Job.location_city.ilike(f"%{city}%"))

        if is_remote is not None:
            stmt = stmt.where(Job.is_remote == is_remote)
            count_stmt = count_stmt.where(Job.is_remote == is_remote)

        if remote_type:
            stmt = stmt.where(Job.remote_type == remote_type)
            count_stmt = count_stmt.where(Job.remote_type == remote_type)

        if employment_type:
            stmt = stmt.where(Job.employment_type == employment_type)
            count_stmt = count_stmt.where(Job.employment_type == employment_type)

        if seniority:
            stmt = stmt.where(Job.seniority == seniority)
            count_stmt = count_stmt.where(Job.seniority == seniority)

        if salary_min is not None:
            stmt = stmt.where(Job.salary_max >= salary_min)
            count_stmt = count_stmt.where(Job.salary_max >= salary_min)

        if salary_max is not None:
            stmt = stmt.where(Job.salary_min <= salary_max)
            count_stmt = count_stmt.where(Job.salary_min <= salary_max)

        if salary_currency:
            stmt = stmt.where(Job.salary_currency == salary_currency.upper())
            count_stmt = count_stmt.where(Job.salary_currency == salary_currency.upper())

        if employer:
            emp_filter = or_(
                Job.employer_domain.ilike(f"%{employer}%"),
                Job.employer_name.ilike(f"%{employer}%"),
            )
            stmt = stmt.where(emp_filter)
            count_stmt = count_stmt.where(emp_filter)

        if category:
            stmt = stmt.where(Job.categories.any(category))
            count_stmt = count_stmt.where(Job.categories.any(category))

        if ats_platform:
            stmt = stmt.where(Job.ats_platform == ats_platform.lower())
            count_stmt = count_stmt.where(Job.ats_platform == ats_platform.lower())

        total = session.execute(count_stmt).scalar() or 0
        stmt = stmt.order_by(Job.date_posted.desc().nullslast()).offset(offset).limit(limit)
        jobs = session.execute(stmt).scalars().all()

        results = []
        for job in jobs:
            entry = {
                "id": str(job.id),
                "title": job.title,
                "employer": job.employer_name,
                "employer_domain": job.employer_domain,
                "location": job.location_raw or f"{job.location_city or ''}, {job.location_country or ''}".strip(", "),
                "country": job.location_country,
                "is_remote": job.is_remote,
                "remote_type": job.remote_type,
                "employment_type": job.employment_type,
                "seniority": job.seniority,
                "categories": job.categories or [],
                "date_posted": str(job.date_posted) if job.date_posted else None,
                "source_url": job.source_url,
                "ats_platform": job.ats_platform,
            }

            if job.salary_min or job.salary_max:
                entry["salary"] = {
                    "min": job.salary_min,
                    "max": job.salary_max,
                    "currency": job.salary_currency,
                    "period": job.salary_period,
                }

            results.append(entry)

        return {"total": total, "returned": len(results), "jobs": results}

    finally:
        session.close()


@mcp.tool()
def search_jobs(
    query: str,
    country: Optional[str] = None,
    city: Optional[str] = None,
    remote_only: Optional[bool] = None,
    employment_type: Optional[str] = None,
    seniority: Optional[str] = None,
    salary_min: Optional[int] = None,
    salary_currency: Optional[str] = None,
    employer: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    Search the global job index for matching positions.

    This searches millions of jobs from corporate ATS platforms (Greenhouse,
    Lever, Workday, etc.) that are normally invisible to AI search.

    Args:
        query: Job title, skill, or keyword (e.g. "Python developer", "data engineer", "marketing").
        country: ISO 3166-1 alpha-2 country code (e.g. "US", "GB", "AU", "DE").
        city: City name (e.g. "San Francisco", "London", "Sydney").
        remote_only: Set to true to only show remote jobs.
        employment_type: One of FULL_TIME, PART_TIME, CONTRACTOR, TEMPORARY, INTERN.
        seniority: One of intern, junior, mid, senior, lead, principal, director, executive.
        salary_min: Minimum annual salary in the specified currency.
        salary_currency: ISO 4217 currency code (USD, EUR, GBP, AUD). Defaults to USD.
        employer: Company name or domain to filter by.
        limit: Number of results (1-50, default 10).
    """
    limit = min(max(limit, 1), 50)

    results = _search_jobs_db(
        keywords=query,
        country=country,
        city=city,
        is_remote=remote_only,
        employment_type=employment_type,
        seniority=seniority,
        salary_min=salary_min,
        salary_currency=salary_currency,
        employer=employer,
        limit=limit,
    )

    return json.dumps(results, default=str)


@mcp.tool()
def find_jobs(query: str) -> str:
    """
    Find jobs using natural language. Automatically extracts location, salary,
    seniority, and other filters from your query.

    Args:
        query: A natural language job search query. Examples:
            - "remote Python jobs paying over 100K USD"
            - "senior data engineer in San Francisco"
            - "part-time marketing roles in London"
            - "junior developer at Google"
            - "contract DevOps engineer in Australia AUD 120k-150k"
    """
    parsed = parse_natural_language(query)

    results = _search_jobs_db(
        keywords=parsed.keywords or None,
        country=parsed.country,
        city=parsed.city,
        is_remote=parsed.is_remote,
        remote_type=parsed.remote_type,
        employment_type=parsed.employment_type,
        seniority=parsed.seniority,
        salary_min=parsed.salary_min,
        salary_max=parsed.salary_max,
        salary_currency=parsed.salary_currency,
        employer=parsed.employer,
        limit=10,
    )

    # Include the parsed interpretation so the AI can verify
    results["parsed_query"] = {
        "keywords": parsed.keywords,
        "country": parsed.country,
        "city": parsed.city,
        "is_remote": parsed.is_remote,
        "seniority": parsed.seniority,
        "salary_min": parsed.salary_min,
        "salary_max": parsed.salary_max,
        "salary_currency": parsed.salary_currency,
        "employer": parsed.employer,
        "employment_type": parsed.employment_type,
    }

    return json.dumps(results, default=str)


@mcp.tool()
def get_job_details(job_id: str) -> str:
    """
    Get full details for a specific job listing including the complete description.

    Args:
        job_id: The UUID of the job (from search results).
    """
    from sqlalchemy import select

    from src.models import Job

    session = _get_db_session()
    try:
        result = session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            return json.dumps({"error": f"Job '{job_id}' not found"})

        detail = {
            "id": str(job.id),
            "title": job.title,
            "employer": job.employer_name,
            "employer_domain": job.employer_domain,
            "employer_logo": job.employer_logo_url,
            "description": job.description_text or job.description_html or "",
            "location": {
                "raw": job.location_raw,
                "city": job.location_city,
                "state": job.location_state,
                "country": job.location_country,
                "is_remote": job.is_remote,
                "remote_type": job.remote_type,
            },
            "employment_type": job.employment_type,
            "seniority": job.seniority,
            "categories": job.categories or [],
            "date_posted": str(job.date_posted) if job.date_posted else None,
            "date_expires": str(job.date_expires) if job.date_expires else None,
            "source_url": job.source_url,
            "ats_platform": job.ats_platform,
            "apply_url": job.source_url,
        }

        if job.salary_min or job.salary_max:
            detail["salary"] = {
                "min": job.salary_min,
                "max": job.salary_max,
                "currency": job.salary_currency,
                "period": job.salary_period,
                "raw": job.salary_raw,
            }

        return json.dumps(detail, default=str)

    finally:
        session.close()


@mcp.tool()
def get_index_stats() -> str:
    """
    Get aggregate statistics about the job index — total jobs,
    employers, breakdowns by country and ATS platform.
    """
    from sqlalchemy import func, select

    from src.models import Employer, Job

    session = _get_db_session()
    try:
        total = session.execute(select(func.count()).select_from(Job)).scalar() or 0
        active = session.execute(
            select(func.count()).select_from(Job).where(Job.status == "active")
        ).scalar() or 0
        employers = session.execute(
            select(func.count()).select_from(Employer)
        ).scalar() or 0

        country_rows = session.execute(
            select(Job.location_country, func.count(Job.id))
            .where(Job.status == "active")
            .group_by(Job.location_country)
            .order_by(func.count(Job.id).desc())
            .limit(15)
        ).all()

        ats_rows = session.execute(
            select(Job.ats_platform, func.count(Job.id))
            .where(Job.status == "active")
            .group_by(Job.ats_platform)
            .order_by(func.count(Job.id).desc())
        ).all()

        stats = {
            "total_jobs": total,
            "active_jobs": active,
            "total_employers": employers,
            "jobs_by_country": {r[0]: r[1] for r in country_rows if r[0]},
            "jobs_by_ats_platform": {r[0]: r[1] for r in ats_rows if r[0]},
        }

        return json.dumps(stats, default=str)

    finally:
        session.close()


@mcp.tool()
def list_employers(
    query: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 20,
) -> str:
    """
    List employers in the job index with their job counts.

    Args:
        query: Search employer name or domain.
        country: Filter by HQ country (ISO 3166-1 alpha-2).
        limit: Number of results (1-50, default 20).
    """
    from sqlalchemy import func, or_, select

    from src.models import Employer, Job

    session = _get_db_session()
    try:
        limit = min(max(limit, 1), 50)

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
                Employer.name,
                Employer.domain,
                Employer.ats_platform,
                Employer.career_page_url,
                func.coalesce(job_count_subq.c.job_count, 0).label("job_count"),
            )
            .outerjoin(job_count_subq, Employer.id == job_count_subq.c.employer_id)
        )

        if query:
            stmt = stmt.where(or_(
                Employer.name.ilike(f"%{query}%"),
                Employer.domain.ilike(f"%{query}%"),
            ))

        if country:
            stmt = stmt.where(Employer.country == country.upper())

        stmt = stmt.order_by(func.coalesce(job_count_subq.c.job_count, 0).desc()).limit(limit)

        rows = session.execute(stmt).all()

        employers_list = [
            {
                "name": r[0],
                "domain": r[1],
                "ats_platform": r[2],
                "career_page": r[3],
                "active_jobs": r[4],
            }
            for r in rows
        ]

        return json.dumps({"total": len(employers_list), "employers": employers_list})

    finally:
        session.close()


if __name__ == "__main__":
    transport = "stdio"
    port = 8001

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--transport" and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run()
