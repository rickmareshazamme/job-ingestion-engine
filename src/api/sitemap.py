"""Sitemap.xml and robots.txt for search engine indexing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Job

router = APIRouter(tags=["SEO"])


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt(request: Request):
    base = str(request.base_url).rstrip("/")
    return f"""User-agent: *
Allow: /

Sitemap: {base}/sitemap.xml
Sitemap: {base}/sitemap-jobs.xml
"""


@router.get("/sitemap.xml", response_class=Response)
async def sitemap_index(request: Request):
    base = str(request.base_url).rstrip("/")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>{base}/sitemap-jobs.xml</loc>
  </sitemap>
</sitemapindex>"""
    return Response(content=xml, media_type="application/xml")


@router.get("/sitemap-jobs.xml", response_class=Response)
async def sitemap_jobs(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    base = str(request.base_url).rstrip("/")

    result = await session.execute(
        select(Job.id, Job.date_updated)
        .where(Job.status == "active")
        .order_by(Job.date_posted.desc().nullslast())
        .limit(50000)
    )
    jobs = result.all()

    urls = []
    for job_id, date_updated in jobs:
        lastmod = date_updated.strftime("%Y-%m-%d") if date_updated else ""
        urls.append(
            f"  <url>\n"
            f"    <loc>{base}/jobs/{job_id}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>daily</changefreq>\n"
            f"  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml")
