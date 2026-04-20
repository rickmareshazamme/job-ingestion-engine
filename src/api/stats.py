"""Stats and aggregate endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import StatsResponse
from src.db import get_session
from src.models import CrawlRun, Employer, Job

router = APIRouter(prefix="/api/v1", tags=["Stats"])


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Index statistics",
    description="Aggregate stats: total jobs, employers, breakdowns by country/ATS/category.",
)
async def get_stats(session: AsyncSession = Depends(get_session)):
    # Total and active jobs
    total_jobs_result = await session.execute(
        select(func.count()).select_from(Job)
    )
    total_jobs = total_jobs_result.scalar() or 0

    active_jobs_result = await session.execute(
        select(func.count()).select_from(Job).where(Job.status == "active")
    )
    active_jobs = active_jobs_result.scalar() or 0

    # Total employers
    total_employers_result = await session.execute(
        select(func.count()).select_from(Employer)
    )
    total_employers = total_employers_result.scalar() or 0

    # Jobs by country (top 20)
    country_result = await session.execute(
        select(Job.location_country, func.count(Job.id))
        .where(Job.status == "active")
        .group_by(Job.location_country)
        .order_by(func.count(Job.id).desc())
        .limit(20)
    )
    jobs_by_country = {row[0]: row[1] for row in country_result.all() if row[0]}

    # Jobs by ATS platform
    ats_result = await session.execute(
        select(Job.ats_platform, func.count(Job.id))
        .where(Job.status == "active")
        .group_by(Job.ats_platform)
        .order_by(func.count(Job.id).desc())
    )
    jobs_by_ats = {row[0]: row[1] for row in ats_result.all() if row[0]}

    # Last crawl
    last_crawl_result = await session.execute(
        select(CrawlRun.completed_at)
        .where(CrawlRun.status == "success")
        .order_by(CrawlRun.completed_at.desc())
        .limit(1)
    )
    last_crawl = last_crawl_result.scalar_one_or_none()

    return StatsResponse(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        total_employers=total_employers,
        jobs_by_country=jobs_by_country,
        jobs_by_ats=jobs_by_ats,
        last_crawl_at=last_crawl,
    )
