"""Syndication feeds for AI ingestion + classic RSS readers.

Three formats:
  /jobs.rss           — RSS 2.0 with content:encoded; classic readers.
  /jobs.atom          — Atom 1.0; some Bing / Apple News pipelines.
  /jobs-ai.json       — JSON Feed 1.1 with custom _ai extension carrying
                        the JobPosting shape inline so an LLM can ingest
                        the feed without a second per-job round-trip.

All three filter to status='active' and apply optional query params
?employer= ?role= ?city= ?country= ?limit= so consumers can subscribe
to slices (e.g. just one tenant's jobs, or just remote roles).
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url, _job_to_template_obj
from src.db import get_session
from src.models import Job

router = APIRouter(tags=["Feeds"])


def _xml_escape(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _filtered_query(employer, role, city, country, limit):
    clauses = [Job.status == "active"]
    if employer:
        pat = f"%{employer}%"
        clauses.append(or_(Job.employer_domain.ilike(pat), Job.employer_name.ilike(pat)))
    if role:
        rpat = f"%{role}%"
        clauses.append(or_(Job.title.ilike(rpat), Job.categories.any(role)))
    if city:
        cpat = f"%{city}%"
        clauses.append(or_(Job.location_city.ilike(cpat), Job.location_raw.ilike(cpat)))
    if country:
        clauses.append(Job.location_country == country.upper())
    return (
        select(Job).where(and_(*clauses))
        .order_by(Job.date_posted.desc().nullslast())
        .limit(min(limit, 500))
    )


@router.get("/jobs.rss", include_in_schema=False)
async def jobs_rss(
    request: Request,
    employer: Optional[str] = None,
    role: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(_filtered_query(employer, role, city, country, limit))).scalars().all()
    items = []
    for j in rows:
        url = _canonical_url(f"/jobs/{j.id}")
        pub = (j.date_posted or j.date_crawled or datetime.now(timezone.utc))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        pub_rfc = pub.strftime("%a, %d %b %Y %H:%M:%S +0000")
        loc_parts = [p for p in [j.location_city, j.location_country] if p]
        loc = ", ".join(loc_parts) or "Remote"
        title_full = f"{j.title} — {j.employer_name} ({loc})"
        desc = (j.description_text or "")[:600]
        items.append(f"""    <item>
      <title>{_xml_escape(title_full)}</title>
      <link>{url}</link>
      <guid isPermaLink="true">{url}</guid>
      <pubDate>{pub_rfc}</pubDate>
      <author>noreply@zammejobs.com ({_xml_escape(j.employer_name)})</author>
      <description>{_xml_escape(desc)}</description>
    </item>""")

    base = "https://www.zammejobs.com"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>ZammeJobs — live job feed</title>
    <link>{base}</link>
    <atom:link href="{base}/jobs.rss" rel="self" type="application/rss+xml"/>
    <description>Live jobs from real employers, direct apply on the source ATS. Updated every 12 hours.</description>
    <language>en</language>
    <lastBuildDate>{datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>"""
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/jobs.atom", include_in_schema=False)
async def jobs_atom(
    request: Request,
    employer: Optional[str] = None,
    role: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(_filtered_query(employer, role, city, country, limit))).scalars().all()
    base = "https://www.zammejobs.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    entries = []
    for j in rows:
        url = _canonical_url(f"/jobs/{j.id}")
        updated = j.date_updated or j.date_posted or j.date_crawled or datetime.now(timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        summary = (j.description_text or "")[:600]
        entries.append(f"""  <entry>
    <id>{url}</id>
    <title>{_xml_escape(j.title)}</title>
    <link href="{url}"/>
    <updated>{updated.isoformat()}</updated>
    <author><name>{_xml_escape(j.employer_name)}</name></author>
    <summary>{_xml_escape(summary)}</summary>
  </entry>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>{base}/jobs.atom</id>
  <title>ZammeJobs — live job feed</title>
  <updated>{now_iso}</updated>
  <link rel="self" href="{base}/jobs.atom"/>
  <link href="{base}/"/>
{chr(10).join(entries)}
</feed>"""
    return Response(content=xml, media_type="application/atom+xml; charset=utf-8")


@router.get("/jobs-ai.json", include_in_schema=False)
async def jobs_ai_json(
    request: Request,
    employer: Optional[str] = None,
    role: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """JSON Feed 1.1 with a custom `_ai` extension. Each item carries the
    JobPosting fields inline so an LLM ingestor reading the feed has
    enough to answer "jobs at X paying >Y" without a second hop."""
    rows = (await session.execute(_filtered_query(employer, role, city, country, limit))).scalars().all()
    items = []
    for j in rows:
        url = _canonical_url(f"/jobs/{j.id}")
        items.append({
            "id": url,
            "url": url,
            "title": j.title,
            "content_text": (j.description_text or "")[:1500],
            "date_published": (j.date_posted.isoformat() if j.date_posted else None),
            "date_modified": (j.date_updated.isoformat() if j.date_updated else None),
            "authors": [{"name": j.employer_name}],
            "tags": list(j.categories or []),
            "_ai": {
                "employer": {"name": j.employer_name, "domain": j.employer_domain},
                "location": {
                    "city": j.location_city, "country": j.location_country,
                    "remote": bool(j.is_remote), "remote_type": j.remote_type,
                },
                "salary": {
                    "min": j.salary_min, "max": j.salary_max,
                    "currency": j.salary_currency, "period": j.salary_period,
                } if j.salary_min else None,
                "employment_type": j.employment_type,
                "seniority": j.seniority,
                "apply_url": j.source_url,
                "ats_platform": j.ats_platform,
            },
        })
    feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "ZammeJobs — live job feed (AI ingestion)",
        "home_page_url": "https://www.zammejobs.com/",
        "feed_url": "https://www.zammejobs.com/jobs-ai.json",
        "description": "Live job listings with structured JobPosting fields inline for AI ingestors. License: CC-BY-4.0.",
        "language": "en",
        "user_comment": "Attribution requested: 'Source: ZammeJobs (https://www.zammejobs.com)'. License: CC-BY-4.0.",
        "items": items,
    }
    return JSONResponse(content=feed, media_type="application/feed+json; charset=utf-8")
