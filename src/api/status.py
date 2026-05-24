"""Public /status — index freshness, sample size, uptime hint.

Two reasons this page matters strategically:
  1. AI engines + curious users land here when evaluating data quality.
     A live, transparent freshness signal is exactly what they cite.
  2. Beats Indeed's well-known stale-listing problem in head-to-head
     comparisons ("Y% verified live in the last 24h").

Renders both as HTML at /status and machine-readable JSON at /status.json.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src._version import __version__
from src.api.frontend import _canonical_url
from src.db import get_session
from src.models import CrawlRun, Job, SourceConfig

router = APIRouter(tags=["Status"])
templates = Jinja2Templates(directory="src/templates")


async def _gather(session: AsyncSession) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)

    total = (await session.execute(select(func.count()).select_from(Job))).scalar() or 0
    active = (await session.execute(
        select(func.count()).select_from(Job).where(Job.status == "active")
    )).scalar() or 0
    fresh_24h = (await session.execute(
        select(func.count()).select_from(Job).where(Job.date_updated >= h24)
    )).scalar() or 0
    new_7d = (await session.execute(
        select(func.count()).select_from(Job).where(Job.date_crawled >= d7)
    )).scalar() or 0
    sources = (await session.execute(
        select(func.count()).select_from(SourceConfig).where(SourceConfig.is_active == True)
    )).scalar() or 0
    last_crawl = (await session.execute(
        select(func.max(CrawlRun.completed_at))
    )).scalar()

    by_country = (await session.execute(
        select(Job.location_country, func.count())
        .where(Job.status == "active")
        .group_by(Job.location_country)
        .order_by(func.count().desc())
        .limit(8)
    )).all()

    freshness_pct = round((fresh_24h / max(active, 1)) * 100, 1) if active else 0.0

    return {
        "version": __version__,
        "checked_at": now.isoformat() + "Z",
        "jobs": {
            "total": total,
            "active": active,
            "verified_in_24h": fresh_24h,
            "freshness_pct_24h": freshness_pct,
            "new_in_7d": new_7d,
        },
        "sources": {
            "active": sources,
            "last_crawl_at": last_crawl.isoformat() + "Z" if last_crawl else None,
        },
        "coverage": {"by_country_top": [{"country": c or "?", "active": n} for c, n in by_country]},
    }


@router.get("/status", response_class=HTMLResponse)
async def status_html(request: Request, session: AsyncSession = Depends(get_session)):
    data = await _gather(session)
    canonical = _canonical_url("/status")
    return templates.TemplateResponse(request, "status.html", {
        "data": data,
        "title": f"ZammeJobs status — {data['jobs']['freshness_pct_24h']}% verified in the last 24h",
        "description": f"Live freshness of the ZammeJobs index: {data['jobs']['active']:,} active jobs, {data['jobs']['freshness_pct_24h']}% verified in the last 24 hours.",
        "canonical_url": canonical,
    })


@router.get("/status.json")
async def status_json(session: AsyncSession = Depends(get_session)):
    return JSONResponse(await _gather(session))
