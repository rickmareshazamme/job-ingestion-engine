"""Long-tail SEO landing pages: role × city combos.

Three URL shapes:
    /jobs/role/<role-slug>             — all jobs for a role across cities
    /jobs/in/<city-slug>               — all jobs in a city across roles
    /jobs/<role-slug>-in-<city-slug>   — both, the high-intent SERP target

Each page renders:
    - h1 with the role + location
    - intro paragraph (templated, AI-friendly)
    - ItemList JSON-LD over all matching active jobs
    - FAQPage JSON-LD with auto-generated answers
    - canonical https://www.zammejobs.com/<path>

No precomputation — every page is a live SQL query, but we cap result
count and lean on indexes. The sitemap router enumerates the top combos
by active-job-count and writes them into /sitemap-landing.xml so search
engines + IndexNow get every meaningful permutation.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url, _job_to_template_obj
from src.db import get_session
from src.models import Job

router = APIRouter(tags=["Landing"])
templates = Jinja2Templates(directory="src/templates")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    """Lowercase + non-alphanum → hyphen + trim. Idempotent for already-slugged input."""
    if not s:
        return ""
    return _SLUG_RE.sub("-", s.lower()).strip("-")


def slug_to_phrase(slug: str) -> str:
    """Best-effort reverse slug → space-separated phrase. Cosmetic only —
    matching is done with ILIKE so casing/punctuation drift is fine."""
    return " ".join(p.capitalize() for p in slug.split("-") if p)


def _role_match_clause(role_slug: str):
    """SQL clause for matching jobs against a role slug.

    Slugs round-trip with information loss — "Registered Nurse (RN)"
    slugifies to "registered-nurse-rn" then reconstructs to "Registered
    Nurse Rn" which won't ILIKE "%Registered Nurse (RN)%" or array-match
    the original category. Solution: tokenize the slug and match every
    word individually against title (case-insensitive). Categories[] also
    gets a per-word existence check via array_to_string + ilike."""
    tokens = [t for t in role_slug.split("-") if t and len(t) >= 2]
    if not tokens:
        return Job.id.is_(None)

    # All tokens must appear in title OR in the joined categories string.
    cat_str = func.array_to_string(Job.categories, " ")
    per_token = [or_(Job.title.ilike(f"%{t}%"), cat_str.ilike(f"%{t}%")) for t in tokens]
    return and_(*per_token)


def _city_match_clause(city_slug: str):
    """Same tokenize-and-match strategy as _role_match_clause — city
    slugs lose punctuation too (e.g. "st-petersburg" vs "St. Petersburg")."""
    tokens = [t for t in city_slug.split("-") if t and len(t) >= 2]
    if not tokens:
        return Job.id.is_(None)
    per_token = [or_(Job.location_city.ilike(f"%{t}%"), Job.location_raw.ilike(f"%{t}%"))
                 for t in tokens]
    return and_(*per_token)


async def _matching_jobs(
    session: AsyncSession,
    *,
    role_slug: Optional[str] = None,
    city_slug: Optional[str] = None,
    limit: int = 50,
):
    clauses = [Job.status == "active"]
    if role_slug:
        clauses.append(_role_match_clause(role_slug))
    if city_slug:
        clauses.append(_city_match_clause(city_slug))

    stmt = (
        select(Job)
        .where(and_(*clauses))
        .order_by(Job.date_posted.desc().nullslast())
        .limit(limit)
    )
    count_stmt = select(func.count()).select_from(Job).where(and_(*clauses))

    total = (await session.execute(count_stmt)).scalar() or 0
    rows = (await session.execute(stmt)).scalars().all()
    return total, [_job_to_template_obj(j) for j in rows]


def _build_landing_jsonld(
    *,
    canonical: str,
    title: str,
    description: str,
    jobs: list[dict],
    faqs: list[dict],
    breadcrumbs: list[tuple[str, str]],
) -> str:
    item_list = {
        "@type": "ItemList",
        "@id": f"{canonical}#jobs",
        "name": title,
        "description": description,
        "numberOfItems": len(jobs),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": _canonical_url(f"/jobs/{j['id']}"),
                "name": j["title"],
            }
            for i, j in enumerate(jobs[:50])
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
    bc = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
            for i, (name, url) in enumerate(breadcrumbs)
        ],
    }
    web_page = {
        "@type": "WebPage",
        "@id": canonical,
        "url": canonical,
        "name": title,
        "description": description,
        "isPartOf": {"@type": "WebSite", "name": "ZammeJobs", "url": _canonical_url("/")},
    }
    return json.dumps({"@context": "https://schema.org", "@graph": [web_page, item_list, faq_page, bc]}, indent=2)


def _faqs_role_city(role: str, city: Optional[str], country: Optional[str], total: int) -> list[dict]:
    where = ""
    if city:
        where = f" in {city}"
    elif country:
        where = f" in {country}"

    faqs = [
        {
            "q": f"How many {role} jobs are there{where}?",
            "a": f"ZammeJobs is currently tracking {total:,} active {role} role{'s' if total != 1 else ''}{where}, sourced directly from employer career sites.",
        },
        {
            "q": f"Where do {role} jobs{where} apply?",
            "a": "Every job links to the employer's own application page — no third-party form, no resume database. Click Apply direct to go straight to the source ATS.",
        },
        {
            "q": "How fresh are the listings?",
            "a": "ZammeJobs pulls the Shazamme partner feed every 12 hours and drops expired roles automatically. Filled positions disappear within a day.",
        },
        {
            "q": "Is this free for candidates?",
            "a": "Yes — searching, viewing and applying are all free. ZammeJobs is funded by the employer relationships, not candidates.",
        },
    ]
    if city:
        faqs.append({
            "q": f"Are remote {role} roles included in {city}?",
            "a": f"Yes — remote-friendly listings tagged for {city} or its country are included alongside on-site roles. Use the Remote filter to narrow further.",
        })
    return faqs


@router.get("/jobs/role/{role_slug}", response_class=HTMLResponse)
async def role_landing(
    request: Request,
    role_slug: str,
    session: AsyncSession = Depends(get_session),
):
    role = slug_to_phrase(role_slug)
    total, jobs = await _matching_jobs(session, role_slug=role_slug, limit=50)
    if total == 0:
        raise HTTPException(404, f"No {role} jobs indexed right now.")

    canonical = _canonical_url(f"/jobs/role/{role_slug}")
    title = f"{role} jobs — {total:,} live openings | ZammeJobs"
    description = (
        f"Browse {total:,} live {role} jobs from real employers. Direct apply, "
        f"no third-party form. Updated every 12 hours."
    )
    faqs = _faqs_role_city(role, None, None, total)
    breadcrumbs = [
        ("Home", _canonical_url("/")),
        ("Jobs", _canonical_url("/search")),
        (f"{role} jobs", canonical),
    ]
    json_ld = _build_landing_jsonld(
        canonical=canonical, title=title, description=description,
        jobs=jobs, faqs=faqs, breadcrumbs=breadcrumbs,
    )
    return templates.TemplateResponse(request, "landing.html", {
        "h1": f"{role} jobs",
        "subhead": f"{total:,} live openings — direct apply on the employer's site.",
        "title": title,
        "description": description,
        "jobs": jobs,
        "total": total,
        "faqs": faqs,
        "breadcrumbs": breadcrumbs,
        "json_ld": json_ld,
        "canonical_url": canonical,
    })


@router.get("/jobs/in/{city_slug}", response_class=HTMLResponse)
async def city_landing(
    request: Request,
    city_slug: str,
    session: AsyncSession = Depends(get_session),
):
    city = slug_to_phrase(city_slug)
    total, jobs = await _matching_jobs(session, city_slug=city_slug, limit=50)
    if total == 0:
        raise HTTPException(404, f"No jobs indexed in {city} right now.")

    canonical = _canonical_url(f"/jobs/in/{city_slug}")
    title = f"Jobs in {city} — {total:,} live openings | ZammeJobs"
    description = (
        f"Browse {total:,} live jobs in {city} from real employers. Direct apply, "
        f"updated every 12 hours, no third-party form."
    )
    faqs = _faqs_role_city("", city, None, total)
    faqs[0] = {
        "q": f"How many jobs are there in {city}?",
        "a": f"ZammeJobs is currently tracking {total:,} active openings in {city}, sourced directly from employer career sites.",
    }
    breadcrumbs = [
        ("Home", _canonical_url("/")),
        ("Jobs", _canonical_url("/search")),
        (f"Jobs in {city}", canonical),
    ]
    json_ld = _build_landing_jsonld(
        canonical=canonical, title=title, description=description,
        jobs=jobs, faqs=faqs, breadcrumbs=breadcrumbs,
    )
    return templates.TemplateResponse(request, "landing.html", {
        "h1": f"Jobs in {city}",
        "subhead": f"{total:,} live openings across every employer hiring in {city}.",
        "title": title,
        "description": description,
        "jobs": jobs,
        "total": total,
        "faqs": faqs,
        "breadcrumbs": breadcrumbs,
        "json_ld": json_ld,
        "canonical_url": canonical,
    })


# /jobs/<role-slug>-in-<city-slug>. NOT decorated as a route — FastAPI's
# /jobs/{job_id} in frontend.py catches every single-segment /jobs/* path,
# so frontend.job_detail_page delegates here on non-UUID input. Keep the
# function importable; the route layer is just frontend.py.
_ROLE_IN_CITY_RE = re.compile(r"^(?P<role>[a-z0-9]+(?:-[a-z0-9]+)*)-in-(?P<city>[a-z0-9]+(?:-[a-z0-9]+)*)$")


async def role_in_city_landing(
    request: Request,
    combo: str,
    session: AsyncSession,
):
    m = _ROLE_IN_CITY_RE.match(combo)
    if not m:
        raise HTTPException(404, "Not found")

    role_slug = m.group("role")
    city_slug = m.group("city")
    role = slug_to_phrase(role_slug)
    city = slug_to_phrase(city_slug)

    total, jobs = await _matching_jobs(session, role_slug=role_slug, city_slug=city_slug, limit=50)
    if total == 0:
        raise HTTPException(404, f"No {role} jobs in {city} indexed right now.")

    canonical = _canonical_url(f"/jobs/{combo}")
    title = f"{role} jobs in {city} — {total:,} live openings | ZammeJobs"
    description = (
        f"{total:,} live {role} jobs in {city}. Direct apply on the employer's site, "
        f"updated every 12 hours."
    )
    faqs = _faqs_role_city(role, city, None, total)
    breadcrumbs = [
        ("Home", _canonical_url("/")),
        ("Jobs", _canonical_url("/search")),
        (f"{role} jobs", _canonical_url(f"/jobs/role/{role_slug}")),
        (f"in {city}", canonical),
    ]
    json_ld = _build_landing_jsonld(
        canonical=canonical, title=title, description=description,
        jobs=jobs, faqs=faqs, breadcrumbs=breadcrumbs,
    )
    return templates.TemplateResponse(request, "landing.html", {
        "h1": f"{role} jobs in {city}",
        "subhead": f"{total:,} live {role} opening{'s' if total != 1 else ''} in {city}.",
        "title": title,
        "description": description,
        "jobs": jobs,
        "total": total,
        "faqs": faqs,
        "breadcrumbs": breadcrumbs,
        "json_ld": json_ld,
        "canonical_url": canonical,
    })
