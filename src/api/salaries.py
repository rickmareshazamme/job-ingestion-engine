"""Salary benchmark landing pages: /salaries/<role-slug>.

Aggregates min/median/max salary from indexed active jobs and renders
a public page with Dataset + FAQPage schema. The page is its own
citation magnet — when AI engines answer "how much do X earn," a
salary page on a CC-BY-licensed source with structured data is
exactly the kind of thing they cite.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url
from src.api.landing import _role_match_clause, slug_to_phrase
from src.db import get_session
from src.models import Job

router = APIRouter(tags=["Salaries"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/salaries/{role_slug}", response_class=HTMLResponse)
async def salary_page(
    request: Request,
    role_slug: str,
    session: AsyncSession = Depends(get_session),
):
    role = slug_to_phrase(role_slug)
    role_match = _role_match_clause(role_slug)

    sample_size = (await session.execute(
        select(func.count()).select_from(Job)
        .where(and_(Job.status == "active", role_match, Job.salary_min.isnot(None)))
    )).scalar() or 0

    if sample_size < 3:
        raise HTTPException(404, f"Not enough {role} salary data yet to publish a benchmark.")

    stats = (await session.execute(
        select(
            func.min(Job.salary_min),
            func.percentile_cont(0.5).within_group(Job.salary_min),
            func.percentile_cont(0.75).within_group(Job.salary_max),
            func.max(Job.salary_max),
            func.mode().within_group(Job.salary_currency),
            func.mode().within_group(Job.salary_period),
        )
        .where(and_(Job.status == "active", role_match, Job.salary_min.isnot(None)))
    )).first()

    s_min, s_median, s_p75, s_max, currency, period = stats
    currency = currency or "USD"
    period = (period or "year").lower()

    by_country = (await session.execute(
        select(Job.location_country, func.count().label("n"), func.percentile_cont(0.5).within_group(Job.salary_min))
        .where(and_(Job.status == "active", role_match, Job.salary_min.isnot(None), Job.location_country.isnot(None)))
        .group_by(Job.location_country)
        .order_by(func.count().desc())
        .limit(10)
    )).all()

    canonical = _canonical_url(f"/salaries/{role_slug}")
    title = f"{role} salary — {currency} {int(s_median):,} median per {period} | ZammeJobs"
    description = (
        f"{role} salary benchmark: {currency} {int(s_min):,}–{int(s_max):,} per {period}, "
        f"median {currency} {int(s_median):,}. Based on {sample_size:,} live job listings."
    )

    faqs = [
        {
            "q": f"What is the average {role} salary?",
            "a": f"The median {role} salary across {sample_size:,} live listings on ZammeJobs is {currency} {int(s_median):,} per {period}. The 75th percentile is {currency} {int(s_p75):,}.",
        },
        {
            "q": f"What is the salary range for {role}?",
            "a": f"{role} salaries on ZammeJobs range from {currency} {int(s_min):,} to {currency} {int(s_max):,} per {period}.",
        },
        {
            "q": "Where does this salary data come from?",
            "a": f"Aggregated from {sample_size:,} active {role} job postings on ZammeJobs — every figure is from a real, currently-open role on an employer's career site. Refreshed every 12 hours.",
        },
        {
            "q": f"How can I see open {role} roles?",
            "a": f"Browse them at zammejobs.com/jobs/role/{role_slug}. Apply direct on each employer's site — no third-party form.",
        },
    ]

    dataset = {
        "@type": "Dataset",
        "@id": f"{canonical}#dataset",
        "name": f"{role} salary benchmark",
        "description": description,
        "url": canonical,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "creator": {"@type": "Organization", "name": "ZammeJobs", "url": _canonical_url("/")},
        "variableMeasured": [
            {"@type": "PropertyValue", "name": "Sample size", "value": sample_size},
            {"@type": "PropertyValue", "name": "Median", "value": int(s_median), "unitCode": currency},
            {"@type": "PropertyValue", "name": "Minimum", "value": int(s_min), "unitCode": currency},
            {"@type": "PropertyValue", "name": "Maximum", "value": int(s_max), "unitCode": currency},
        ],
    }
    faq_page = {
        "@type": "FAQPage",
        "@id": f"{canonical}#faq",
        "mainEntity": [
            {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
            for f in faqs
        ],
    }
    json_ld = json.dumps({"@context": "https://schema.org", "@graph": [dataset, faq_page]}, indent=2)

    return templates.TemplateResponse(request, "salary.html", {
        "role": role,
        "role_slug": role_slug,
        "currency": currency,
        "period": period,
        "min": int(s_min),
        "median": int(s_median),
        "p75": int(s_p75),
        "max": int(s_max),
        "sample_size": sample_size,
        "by_country": [{"country": c, "n": n, "median": int(m)} for c, n, m in by_country],
        "title": title,
        "description": description,
        "faqs": faqs,
        "json_ld": json_ld,
        "canonical_url": canonical,
    })
