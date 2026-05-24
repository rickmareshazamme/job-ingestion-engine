"""Skill-entity pages: /skills/<slug>.

Same DB shape as /jobs/role/<slug> but framed as a *skill* — useful
because some long-tail intents read better as "X skill" than "X jobs"
(e.g. "Salesforce skill" vs "Salesforce jobs"). Emits DefinedTerm +
Occupation schema so AI engines can link the skill to the roles.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url
from src.api.landing import _matching_jobs, _role_match_clause, slug_to_phrase
from src.db import get_session
from src.models import Job

router = APIRouter(tags=["Skills"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/skills/{slug}", response_class=HTMLResponse)
async def skill_page(request: Request, slug: str, session: AsyncSession = Depends(get_session)):
    skill = slug_to_phrase(slug)
    total, jobs = await _matching_jobs(session, role_slug=slug, limit=40)
    if total == 0:
        raise HTTPException(404, f"No jobs requiring {skill} indexed right now.")

    by_country = (await session.execute(
        select(Job.location_country, func.count()).where(
            and_(Job.status == "active", _role_match_clause(slug), Job.location_country.isnot(None))
        ).group_by(Job.location_country).order_by(func.count().desc()).limit(8)
    )).all()

    canonical = _canonical_url(f"/skills/{slug}")
    title = f"{skill} jobs — {total:,} open roles requiring {skill} | ZammeJobs"
    description = f"{total:,} live jobs that mention {skill} as a required or preferred skill. Updated every 12 hours. Direct apply on each employer's site."

    faqs = [
        {"q": f"How many jobs require {skill}?",
         "a": f"ZammeJobs currently lists {total:,} active jobs that mention {skill} in the title or skill tags."},
        {"q": f"What roles use {skill}?",
         "a": f"Browse the live list below for current titles, or visit /salaries/{slug} for compensation context."},
        {"q": "Where does this data come from?",
         "a": "Direct from employer ATSes via the Shazamme recruitment-agency network. No third-party form, no resume database."},
    ]

    defined_term = {
        "@type": "DefinedTerm",
        "@id": f"{canonical}#term",
        "name": skill, "termCode": slug, "inDefinedTermSet": _canonical_url("/skills"),
        "description": f"Job-market skill: {skill}",
    }
    item_list = {
        "@type": "ItemList",
        "@id": f"{canonical}#jobs",
        "numberOfItems": len(jobs),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": _canonical_url(f"/jobs/{j['id']}"), "name": j["title"]}
            for i, j in enumerate(jobs[:40])
        ],
    }
    faq_page = {
        "@type": "FAQPage", "@id": f"{canonical}#faq",
        "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs],
    }
    bc = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": _canonical_url("/")},
            {"@type": "ListItem", "position": 2, "name": "Skills", "item": _canonical_url("/skills")},
            {"@type": "ListItem", "position": 3, "name": skill, "item": canonical},
        ],
    }
    json_ld = json.dumps({"@context": "https://schema.org", "@graph": [defined_term, item_list, faq_page, bc]}, indent=2)

    return templates.TemplateResponse(request, "landing.html", {
        "h1": f"{skill} jobs",
        "subhead": f"{total:,} live openings that mention {skill}.",
        "title": title, "description": description, "canonical_url": canonical,
        "jobs": jobs, "total": total, "faqs": faqs, "json_ld": json_ld,
        "breadcrumbs": [
            ("Home", _canonical_url("/")),
            ("Skills", _canonical_url("/skills")),
            (skill, canonical),
        ],
    })
