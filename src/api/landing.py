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


_COUNTRY_SLUG_TO_ISO = {
    "australia": "AU", "new-zealand": "NZ", "united-kingdom": "GB", "uk": "GB",
    "united-states": "US", "usa": "US", "us": "US",
    "canada": "CA", "ireland": "IE", "germany": "DE", "france": "FR",
    "netherlands": "NL", "spain": "ES", "italy": "IT", "singapore": "SG",
    "hong-kong": "HK", "japan": "JP", "india": "IN", "south-africa": "ZA",
    "brazil": "BR", "mexico": "MX",
}


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
    """Match a place-slug against city, state, country, or location_raw.

    City slugs lose punctuation too (e.g. "st-petersburg" vs "St. Petersburg"),
    so we tokenize. We also treat the whole slug as a country name (so
    "australia" matches location_country='AU') and as a state name (so
    "western-australia" matches location_state ILIKE 'western australia').
    """
    if not city_slug:
        return Job.id.is_(None)

    or_parts: list = []

    # Country-name fast path.
    iso = _COUNTRY_SLUG_TO_ISO.get(city_slug.lower())
    if iso:
        or_parts.append(Job.location_country == iso)

    # State-name fast path: match the de-slugged phrase against location_state.
    phrase = slug_to_phrase(city_slug)
    if phrase:
        or_parts.append(Job.location_state.ilike(f"%{phrase}%"))

    # Per-token fallback against city / raw / state / country-name.
    tokens = [t for t in city_slug.split("-") if t and len(t) >= 2]
    if tokens:
        per_token = [
            or_(
                Job.location_city.ilike(f"%{t}%"),
                Job.location_raw.ilike(f"%{t}%"),
                Job.location_state.ilike(f"%{t}%"),
            )
            for t in tokens
        ]
        or_parts.append(and_(*per_token))

    if not or_parts:
        return Job.id.is_(None)
    return or_(*or_parts)


async def _matching_jobs(
    session: AsyncSession,
    *,
    role_slug: Optional[str] = None,
    city_slug: Optional[str] = None,
    limit: int = 50,
):
    clauses = [Job.status == "active"]
    # "remote-<role>" prefix is a high-intent SEO pattern (e.g.
    # /jobs/remote-technology-in-australia). Strip the prefix and add a
    # remote filter so the page actually only lists remote roles.
    remote_only = False
    if role_slug and role_slug.startswith("remote-"):
        remote_only = True
        role_slug = role_slug[len("remote-"):] or role_slug
    if remote_only:
        clauses.append(Job.is_remote.is_(True))
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
            "a": "ZammeJobs pulls the Shazamme partner feed every few hours and drops expired roles automatically. Filled positions disappear within a day.",
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
        f"no third-party form. Updated every few hours."
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
        f"updated every few hours, no third-party form."
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
        f"updated every few hours."
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


# Curated high-intent SEO/AEO landing combos. These are the SERP-targeted
# pages we actively want indexed first — chosen for high search volume in
# Shazamme's recruitment-agency vertical. The combo path resolves via the
# existing /jobs/<role>-in-<city> route; this list is what feeds the
# /jobs/intent index and the curated entries in /sitemap-intent.xml.
CURATED_INTENT_PAGES: list[dict] = [
    {"label": "Nursing jobs in Australia", "slug": "nursing-in-australia"},
    {"label": "Mining jobs in Western Australia", "slug": "mining-in-western-australia"},
    {"label": "Procurement jobs in Melbourne", "slug": "procurement-in-melbourne"},
    {"label": "Remote technology jobs in Australia", "slug": "remote-technology-in-australia"},
    {"label": "Locum doctor jobs in Australia", "slug": "locum-doctor-in-australia"},
    {"label": "Engineering jobs in Brisbane", "slug": "engineering-in-brisbane"},
    {"label": "Recruitment jobs in Sydney", "slug": "recruitment-in-sydney"},
    {"label": "Healthcare jobs in Sydney", "slug": "healthcare-in-sydney"},
    {"label": "Construction jobs in Perth", "slug": "construction-in-perth"},
    {"label": "Finance jobs in Sydney", "slug": "finance-in-sydney"},
    {"label": "Marketing jobs in Melbourne", "slug": "marketing-in-melbourne"},
    {"label": "Hospitality jobs in Brisbane", "slug": "hospitality-in-brisbane"},
    {"label": "Aged care jobs in Australia", "slug": "aged-care-in-australia"},
    {"label": "IT jobs in New Zealand", "slug": "it-in-new-zealand"},
    {"label": "Engineering jobs in Auckland", "slug": "engineering-in-auckland"},
    {"label": "Technology jobs in London", "slug": "technology-in-london"},
    {"label": "Finance jobs in London", "slug": "finance-in-london"},
    {"label": "Remote engineering jobs in United Kingdom", "slug": "remote-engineering-in-united-kingdom"},
    {"label": "Software engineer jobs in United States", "slug": "software-engineer-in-united-states"},
    {"label": "Sales jobs in New York", "slug": "sales-in-new-york"},
]


@router.get("/jobs/intent", response_class=HTMLResponse)
async def intent_index(request: Request, session: AsyncSession = Depends(get_session)):
    """Curated index of high-intent SEO landing pages. One link per combo;
    each click routes through /jobs/<combo> to the live role+location page."""
    items: list[dict] = []
    for entry in CURATED_INTENT_PAGES:
        slug = entry["slug"]
        m = _ROLE_IN_CITY_RE.match(slug)
        total = 0
        if m:
            total, _ = await _matching_jobs(
                session,
                role_slug=m.group("role"),
                city_slug=m.group("city"),
                limit=1,
            )
        items.append({
            "label": entry["label"],
            "url": _canonical_url(f"/jobs/{slug}"),
            "path": f"/jobs/{slug}",
            "count": total,
        })

    canonical = _canonical_url("/jobs/intent")
    title = "High-intent job searches | ZammeJobs"
    description = (
        "Curated SEO/AEO landing pages for the most-searched job intents: nursing in "
        "Australia, mining in Western Australia, engineering in Brisbane, and more."
    )
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "@id": canonical,
        "name": title,
        "description": description,
        "hasPart": [
            {"@type": "WebPage", "name": it["label"], "url": it["url"]}
            for it in items
        ],
    }, ensure_ascii=False)

    return templates.TemplateResponse(request, "intent_index.html", {
        "title": title,
        "description": description,
        "items": items,
        "json_ld": json_ld,
        "canonical_url": canonical,
    })
