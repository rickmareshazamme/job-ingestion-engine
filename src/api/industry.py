"""Industry hub pages: /industry/<slug>.

Topical authority pages that group roles, employers, and salary
context for one vertical. Each hub renders:
  - market snapshot (open roles, top employers, top cities)
  - role table linking to /jobs/role/<slug>
  - sample of latest openings
  - FAQ + CollectionPage + ItemList JSON-LD

Industries are fixed (curated taxonomy) — better than auto-grouping
because Shazamme tenants tag categories inconsistently.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url, _job_to_template_obj
from src.api.landing import slugify
from src.db import get_session
from src.models import Job

router = APIRouter(tags=["Industry"])
templates = Jinja2Templates(directory="src/templates")


# Curated taxonomy. Each industry resolves to a set of ILIKE patterns
# matched against title + categories. Slug-stable (URL contract).
INDUSTRIES: dict[str, dict] = {
    "healthcare": {
        "name": "Healthcare",
        "tagline": "Clinical, allied health, and care delivery roles",
        "patterns": ["nurse", "physician", "doctor", "therapist", "radiology",
                     "medical", "healthcare", "clinical", "surgeon", "dentist",
                     "pharmacist", "paramedic", "midwife", "psychologist"],
        "intro": "Live healthcare openings sourced directly from hospital systems, clinics, and recruitment agencies on the Shazamme network. Direct apply on each employer's site — no third-party form, no resume database.",
    },
    "technology": {
        "name": "Technology",
        "tagline": "Software, data, infra, security, and product",
        "patterns": ["engineer", "developer", "software", "data scientist",
                     "devops", "sre", "security", "cloud", "frontend", "backend",
                     "fullstack", "qa", "tech lead", "architect", "ml", "ai"],
        "intro": "Live tech roles across software, data, infrastructure, security, and product. Updated every 12 hours from real employer ATSes.",
    },
    "recruitment": {
        "name": "Recruitment",
        "tagline": "Talent acquisition, RPO, and agency roles",
        "patterns": ["recruit", "talent", "ta partner", "headhunter",
                     "sourcer", "talent acquisition", "rpo", "executive search"],
        "intro": "Recruitment, talent acquisition, and agency-side openings — the meta-category. Sourced from the same Shazamme tenant network that powers ZammeJobs itself.",
    },
    "engineering": {
        "name": "Engineering",
        "tagline": "Mechanical, electrical, civil, and process engineering",
        "patterns": ["mechanical engineer", "electrical engineer", "civil engineer",
                     "process engineer", "structural", "manufacturing engineer",
                     "controls engineer", "automation", "cnc", "maintenance engineer"],
        "intro": "Engineering roles across mechanical, electrical, civil, and process disciplines. Hands-on shopfloor through senior design.",
    },
    "finance": {
        "name": "Finance",
        "tagline": "Accounting, audit, treasury, and FP&A",
        "patterns": ["accountant", "finance", "auditor", "treasury",
                     "controller", "fp&a", "tax", "cfo", "bookkeeper",
                     "financial analyst"],
        "intro": "Finance and accounting roles from controller to CFO, plus audit, tax, and treasury openings.",
    },
    "sales": {
        "name": "Sales",
        "tagline": "Account executives, BDRs, and sales leadership",
        "patterns": ["sales", "account executive", "account manager",
                     "bdr", "sdr", "business development", "revenue",
                     "sales engineer", "sales operations"],
        "intro": "Sales openings from BDR through enterprise AE and sales leadership.",
    },
    "construction": {
        "name": "Construction",
        "tagline": "Site, trades, project management, and surveying",
        "patterns": ["construction", "site manager", "project manager",
                     "quantity surveyor", "estimator", "foreman", "supervisor",
                     "scaffolder", "carpenter", "plumber", "electrician"],
        "intro": "Construction roles across trades, site management, surveying, and project delivery.",
    },
    "education": {
        "name": "Education",
        "tagline": "Teaching, lecturing, and education leadership",
        "patterns": ["teacher", "lecturer", "professor", "tutor",
                     "principal", "education", "academic", "instructor"],
        "intro": "Teaching, lecturing, and education-leadership roles from primary through tertiary.",
    },
    "logistics": {
        "name": "Logistics & Warehousing",
        "tagline": "Drivers, warehouse, supply chain, and operations",
        "patterns": ["driver", "warehouse", "logistics", "supply chain",
                     "forklift", "picker", "packer", "distribution",
                     "operations manager", "fleet"],
        "intro": "Logistics, warehousing, supply-chain, and operations roles across all shifts.",
    },
    "hospitality": {
        "name": "Hospitality",
        "tagline": "Chef, F&B, hotel, and events roles",
        "patterns": ["chef", "cook", "barista", "bartender",
                     "waiter", "waitress", "hotel", "concierge", "events",
                     "hospitality", "restaurant"],
        "intro": "Hospitality roles across kitchens, hotels, events, and front-of-house.",
    },
}


def _industry_clause(slug: str):
    cfg = INDUSTRIES[slug]
    title_or_cat = []
    for pat in cfg["patterns"]:
        like = f"%{pat}%"
        title_or_cat.append(Job.title.ilike(like))
        title_or_cat.append(Job.categories.any(pat))
    return or_(*title_or_cat)


@router.get("/industry/{slug}", response_class=HTMLResponse)
async def industry_hub(
    request: Request,
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    if slug not in INDUSTRIES:
        raise HTTPException(404, "Industry hub not found. See /industry for the directory.")
    cfg = INDUSTRIES[slug]
    clause = _industry_clause(slug)
    base = and_(Job.status == "active", clause)

    total = (await session.execute(select(func.count()).select_from(Job).where(base))).scalar() or 0
    if total == 0:
        raise HTTPException(404, f"No live {cfg['name']} jobs indexed right now.")

    sample = (await session.execute(
        select(Job).where(base).order_by(Job.date_posted.desc().nullslast()).limit(30)
    )).scalars().all()
    sample_jobs = [_job_to_template_obj(j) for j in sample]

    by_country = (await session.execute(
        select(Job.location_country, func.count()).where(base)
        .group_by(Job.location_country).order_by(func.count().desc()).limit(10)
    )).all()
    by_employer = (await session.execute(
        select(Job.employer_name, Job.employer_domain, func.count()).where(base)
        .group_by(Job.employer_name, Job.employer_domain).order_by(func.count().desc()).limit(12)
    )).all()
    by_city = (await session.execute(
        select(Job.location_city, func.count()).where(base, Job.location_city.isnot(None))
        .group_by(Job.location_city).order_by(func.count().desc()).limit(12)
    )).all()
    # Top roles within this industry — pulled from categories.
    by_role = (await session.execute(
        select(func.unnest(Job.categories).label("cat"), func.count().label("n"))
        .where(base).group_by("cat").order_by(func.count().desc()).limit(20)
    )).all()

    canonical = _canonical_url(f"/industry/{slug}")
    title = f"{cfg['name']} jobs — {total:,} live openings | ZammeJobs"
    description = f"{cfg['name']}: {total:,} live openings across the ZammeJobs network. {cfg['tagline']}."

    faqs = [
        {"q": f"How many {cfg['name']} jobs are live right now?",
         "a": f"{total:,} active {cfg['name']} roles across the Shazamme recruitment network, updated every 12 hours."},
        {"q": f"What kinds of {cfg['name']} roles are on ZammeJobs?",
         "a": f"{cfg['intro']} Top role types include {', '.join([slugify(r[0]).replace('-', ' ') for r in by_role[:6] if r[0]])}."},
        {"q": "Where can I find salary information?",
         "a": "Each /salaries/<role-slug> page publishes median + 75th-percentile + per-country medians for that role, based only on live listings."},
        {"q": "Can recruitment agencies list jobs here?",
         "a": "Yes. ZammeJobs is the distribution surface for the Shazamme agency network. If your agency uses Shazamme, your jobs publish automatically."},
    ]

    collection = {
        "@type": "CollectionPage",
        "@id": f"{canonical}#page",
        "name": title, "url": canonical, "description": description,
        "isPartOf": {"@type": "WebSite", "name": "ZammeJobs", "url": _canonical_url("/")},
    }
    item_list = {
        "@type": "ItemList",
        "@id": f"{canonical}#jobs",
        "numberOfItems": len(sample_jobs),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": _canonical_url(f"/jobs/{j['id']}"), "name": j["title"]}
            for i, j in enumerate(sample_jobs[:30])
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
            {"@type": "ListItem", "position": 2, "name": "Industries", "item": _canonical_url("/industry")},
            {"@type": "ListItem", "position": 3, "name": cfg["name"], "item": canonical},
        ],
    }
    json_ld = json.dumps({"@context": "https://schema.org", "@graph": [collection, item_list, faq_page, bc]}, indent=2)

    return templates.TemplateResponse(request, "industry.html", {
        "title": title, "description": description, "canonical_url": canonical,
        "industry": cfg["name"], "slug": slug, "tagline": cfg["tagline"], "intro": cfg["intro"],
        "total": total,
        "sample_jobs": sample_jobs,
        "by_country": [{"country": c, "n": n} for c, n in by_country if c],
        "by_employer": [{"name": e, "domain": d, "n": n} for e, d, n in by_employer if e],
        "by_city": [{"city": c, "n": n} for c, n in by_city],
        "by_role": [{"name": r, "slug": slugify(r), "n": n} for r, n in by_role if r and len(slugify(r)) >= 4],
        "faqs": faqs, "json_ld": json_ld,
    })


@router.get("/industry", response_class=HTMLResponse)
async def industry_directory(request: Request, session: AsyncSession = Depends(get_session)):
    """Directory of all industry hubs."""
    rows = []
    for slug, cfg in INDUSTRIES.items():
        clause = _industry_clause(slug)
        n = (await session.execute(
            select(func.count()).select_from(Job).where(and_(Job.status == "active", clause))
        )).scalar() or 0
        rows.append({"slug": slug, "name": cfg["name"], "tagline": cfg["tagline"], "n": n})
    rows.sort(key=lambda r: r["n"], reverse=True)
    canonical = _canonical_url("/industry")
    title = "Browse jobs by industry | ZammeJobs"
    description = f"Industry hubs covering {len(rows)} verticals — live job counts, top employers, top cities, and salary benchmarks."
    return templates.TemplateResponse(request, "industry_dir.html", {
        "industries": rows,
        "title": title, "description": description, "canonical_url": canonical,
    })
