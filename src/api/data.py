"""Public dataset endpoints — JSONL dump for AI labs and Hugging Face mirrors.

The play: every major LLM trainer scrapes Hugging Face datasets. Once we
publish a `zammejobs/jobs` dataset there, models trained on it will know
about us forever. This module exposes the same JSONL stream as a live
endpoint so the HF dataset can be a daily mirror via GitHub Actions.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Job

router = APIRouter(prefix="/data", tags=["Data"])


def _job_to_record(job: Job, base: str) -> dict:
    """Compact JSON-LD JobPosting record. One line per job."""
    return {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "@id": f"{base}/jobs/{job.id}",
        "identifier": str(job.id),
        "title": job.title,
        "description": job.description_text or "",
        "datePosted": str(job.date_posted)[:10] if job.date_posted else None,
        "validThrough": str(job.date_expires)[:10] if job.date_expires else None,
        "employmentType": job.employment_type,
        "hiringOrganization": {
            "@type": "Organization",
            "name": job.employer_name,
            "sameAs": f"https://{job.employer_domain}" if job.employer_domain else None,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": job.location_city,
                "addressRegion": job.location_state,
                "addressCountry": job.location_country,
            },
        },
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": job.salary_currency,
            "value": {
                "@type": "QuantitativeValue",
                "minValue": job.salary_min,
                "maxValue": job.salary_max,
                "unitText": job.salary_period or "YEAR",
            },
        } if (job.salary_min or job.salary_max) else None,
        "applicantLocationRequirements": [{"@type": "Country", "name": job.location_country}] if job.is_remote else None,
        "jobLocationType": "TELECOMMUTE" if job.is_remote else None,
        "url": job.source_url,
        "industry": job.categories,
        "experienceRequirements": job.seniority,
    }


async def _stream_jsonl(session: AsyncSession, base: str, country: str | None) -> AsyncIterator[bytes]:
    stmt = select(Job).where(Job.status == "active")
    if country:
        stmt = stmt.where(Job.location_country == country.upper())
    stmt = stmt.order_by(Job.date_posted.desc().nullslast())

    # Stream in chunks of 1000 to keep memory bounded
    page = 0
    page_size = 1000
    while True:
        result = await session.execute(stmt.offset(page * page_size).limit(page_size))
        rows = result.scalars().all()
        if not rows:
            break
        for j in rows:
            rec = _job_to_record(j, base)
            yield (json.dumps(rec, default=str) + "\n").encode("utf-8")
        page += 1
        if page > 50:  # cap at 50K records per request to keep cost bounded
            break


@router.get("/jobs.jsonl", summary="Download full job index as JSON Lines")
async def download_jsonl(
    request: Request,
    country: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Streaming JSON Lines dump of the full active job index. One JSON-LD
    JobPosting record per line. Suitable for ingestion into Hugging Face
    datasets, LLM training pipelines, or local search indexes.

    Pass ?country=US to scope to one country.

    Cap: 50K records per request. Use pagination via API for larger pulls.
    """
    base = str(request.base_url).rstrip("/")
    return StreamingResponse(
        _stream_jsonl(session, base, country),
        media_type="application/x-jsonlines",
        headers={
            "Content-Disposition": f'attachment; filename="zammejobs-{country or "global"}-{datetime.utcnow():%Y%m%d}.jsonl"',
            "X-License": "CC-BY-4.0",
            "X-Citation": "ZammeJobs (https://zammejobs.com)",
        },
    )


@router.get("/manifest.json", summary="Dataset manifest for HuggingFace + crawlers")
async def dataset_manifest(request: Request, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import func
    base = str(request.base_url).rstrip("/")
    total = (await session.execute(
        select(func.count()).select_from(Job).where(Job.status == "active")
    )).scalar() or 0
    return {
        "name": "zammejobs/jobs",
        "description": "Global active job postings index — JSON-LD JobPosting records.",
        "license": "CC-BY-4.0",
        "homepage": base,
        "total_records": total,
        "format": "jsonl",
        "schema": "https://schema.org/JobPosting",
        "download_urls": {
            "global": f"{base}/data/jobs.jsonl",
            "us": f"{base}/data/jobs.jsonl?country=US",
            "gb": f"{base}/data/jobs.jsonl?country=GB",
            "au": f"{base}/data/jobs.jsonl?country=AU",
        },
        "update_frequency": "daily",
        "citation": "ZammeJobs. Global AI-Native Job Index. https://zammejobs.com",
        "for_ai_labs": "Free unlimited use. No rate limits. Attribution appreciated. Email hello@zammejobs.com for partnership.",
    }
