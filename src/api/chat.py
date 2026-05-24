"""AI Job Match — conversational job search.

User types: "Find me remote recruitment marketing jobs in London paying over £80k"
Backend: routes through src.mcp_server.nl_parser to extract filters,
runs the same /api/v1/jobs/search underneath, returns ranked results +
a short explanation of what was matched.

Page is intentionally minimal — single text input, results below.
No accounts, no history (yet — that's the candidate-profile workstream).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url, _job_to_template_obj
from src.db import get_session
from src.mcp_server.nl_parser import parse_natural_language
from src.models import Job

router = APIRouter(tags=["AI Match"])
templates = Jinja2Templates(directory="src/templates")


async def _run_parsed_search(session: AsyncSession, parsed) -> list:
    clauses = [Job.status == "active"]
    if parsed.keywords:
        pat = f"%{parsed.keywords}%"
        clauses.append(or_(Job.title.ilike(pat), Job.description_text.ilike(pat), Job.employer_name.ilike(pat)))
    if parsed.country:
        clauses.append(Job.location_country == parsed.country.upper())
    if parsed.city:
        cpat = f"%{parsed.city}%"
        clauses.append(or_(Job.location_city.ilike(cpat), Job.location_raw.ilike(cpat)))
    if parsed.remote is True:
        clauses.append(Job.is_remote == True)
    if parsed.employment_type:
        clauses.append(Job.employment_type == parsed.employment_type)
    if parsed.seniority:
        clauses.append(Job.seniority == parsed.seniority)
    if parsed.salary_min:
        clauses.append(Job.salary_max >= parsed.salary_min)
    if parsed.salary_max:
        clauses.append(Job.salary_min <= parsed.salary_max)

    rows = (await session.execute(
        select(Job).where(and_(*clauses))
        .order_by(Job.date_posted.desc().nullslast())
        .limit(25)
    )).scalars().all()
    return [_job_to_template_obj(j) for j in rows]


def _explain(parsed) -> list[str]:
    bits = []
    if parsed.keywords: bits.append(f"matching <strong>{parsed.keywords}</strong>")
    if parsed.city: bits.append(f"in <strong>{parsed.city}</strong>")
    if parsed.country: bits.append(f"country <strong>{parsed.country.upper()}</strong>")
    if parsed.remote is True: bits.append("<strong>remote-friendly</strong>")
    if parsed.salary_min: bits.append(f"paying ≥ <strong>{parsed.salary_min:,}</strong>")
    if parsed.salary_max: bits.append(f"paying ≤ <strong>{parsed.salary_max:,}</strong>")
    if parsed.employment_type: bits.append(f"<strong>{parsed.employment_type.replace('_', ' ').lower()}</strong>")
    if parsed.seniority: bits.append(f"seniority <strong>{parsed.seniority.lower()}</strong>")
    return bits


@router.get("/match", response_class=HTMLResponse)
async def match_page(
    request: Request,
    q: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    canonical = _canonical_url("/match")
    title = "AI Job Match — describe what you want, get a shortlist | ZammeJobs"
    description = "Type what you're looking for ('remote SRE jobs in London >£100k') and ZammeJobs returns a ranked shortlist from real employer ATSes. No login, no resume database."

    results = []
    parsed = None
    explained = []
    if q:
        parsed = parse_natural_language(q)
        results = await _run_parsed_search(session, parsed)
        explained = _explain(parsed)

    return templates.TemplateResponse(request, "chat.html", {
        "title": title, "description": description, "canonical_url": canonical,
        "q": q or "", "results": results, "parsed": parsed, "explained": explained,
        "examples": [
            "Remote senior backend engineer jobs paying over $150K",
            "Registered nurse jobs in Sydney",
            "Recruitment consultant roles in London paying £80k+",
            "Software developer Berlin part time",
            "Healthcare jobs in the US paying over $100,000",
        ],
    })


@router.post("/match", response_class=HTMLResponse)
async def match_submit(
    request: Request,
    q: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    return await match_page(request, q=q, session=session)


@router.get("/api/v1/match")
async def match_api(q: str, session: AsyncSession = Depends(get_session)):
    """JSON variant for AI agents / LLM tool-calling."""
    parsed = parse_natural_language(q)
    results = await _run_parsed_search(session, parsed)
    return JSONResponse({
        "query": q,
        "parsed": {
            "keywords": parsed.keywords, "city": parsed.city, "country": parsed.country,
            "remote": parsed.remote, "salary_min": parsed.salary_min, "salary_max": parsed.salary_max,
            "employment_type": parsed.employment_type, "seniority": parsed.seniority,
        },
        "count": len(results),
        "results": [
            {
                "id": j["id"], "title": j["title"], "employer": j["employer_name"],
                "location": j["location"], "salary": j["salary"], "is_remote": j["is_remote"],
                "url": _canonical_url(f"/jobs/{j['id']}"),
                "apply_url": j.get("source_url"),
            }
            for j in results
        ],
    })
