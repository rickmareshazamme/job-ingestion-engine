"""Sitemap.xml, robots.txt, and AI well-known endpoints for AI/SEO discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_session
from src.models import Employer, Job

router = APIRouter(tags=["SEO"])


# Major AI training and live-search crawlers. We allow every one explicitly:
# silence in robots.txt is interpreted by some of them (Google-Extended,
# Applebot-Extended, anthropic-ai) as "default deny", so listing each is the
# only way to be sure they index us.
AI_ALLOWLIST = [
    # Anthropic
    "ClaudeBot", "ClaudeUser", "ClaudeWeb", "Claude-Web", "anthropic-ai",
    # OpenAI
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ChatGPTBot",
    # Google AI / Search
    "Googlebot", "Googlebot-Image", "Googlebot-News", "Google-Extended", "Storebot-Google",
    # Microsoft / Bing
    "Bingbot", "BingPreview", "MSNBot", "msnbot-media",
    # Apple
    "Applebot", "Applebot-Extended",
    # Perplexity
    "PerplexityBot", "Perplexity-User",
    # Common Crawl (foundation of many LLM training datasets)
    "CCBot",
    # Meta
    "FacebookBot", "facebookexternalhit", "meta-externalagent", "meta-externalfetcher",
    # Other engines / agents
    "DuckDuckBot", "YandexBot", "Baiduspider",
    "Diffbot", "Bytespider", "PetalBot",
    "Cohere-AI", "cohere-ai",
    "Mistral-AI",
    "YouBot",
    "Amazonbot",
    "Timpibot",
    "ImagesiftBot",
]


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt(request: Request):
    base = str(request.base_url).rstrip("/")
    blocks = [f"# ZammeJobs — every job, AI-indexable. Crawl us!"]
    for bot in AI_ALLOWLIST:
        blocks.append(f"\nUser-agent: {bot}\nAllow: /\nCrawl-delay: 0")
    blocks.append("\nUser-agent: *\nAllow: /")
    blocks.append(f"\nSitemap: {base}/sitemap.xml")
    blocks.append(f"Sitemap: {base}/sitemap-jobs.xml")
    blocks.append(f"Sitemap: {base}/sitemap-employers.xml")
    return "\n".join(blocks) + "\n"


@router.get("/indexnow-key.txt", response_class=PlainTextResponse, include_in_schema=False)
async def indexnow_key_file():
    """IndexNow ownership-verification key file. Set INDEXNOW_KEY env var to enable."""
    if not settings.indexnow_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return settings.indexnow_key


@router.get("/sitemap.xml", response_class=Response)
async def sitemap_index(request: Request):
    base = str(request.base_url).rstrip("/")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{base}/sitemap-jobs.xml</loc></sitemap>
  <sitemap><loc>{base}/sitemap-employers.xml</loc></sitemap>
  <sitemap><loc>{base}/sitemap-static.xml</loc></sitemap>
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
            f"    <priority>0.8</priority>\n"
            f"  </url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/sitemap-employers.xml", response_class=Response)
async def sitemap_employers(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    base = str(request.base_url).rstrip("/")
    result = await session.execute(
        select(Employer.id, Employer.updated_at)
        .order_by(Employer.updated_at.desc().nullslast())
        .limit(50000)
    )
    employers = result.all()

    urls = [f'  <url><loc>{base}/employers</loc><changefreq>daily</changefreq><priority>0.6</priority></url>']
    for emp_id, updated_at in employers:
        lastmod = updated_at.strftime("%Y-%m-%d") if updated_at else ""
        urls.append(
            f"  <url>\n"
            f"    <loc>{base}/employers/{emp_id}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"    <priority>0.5</priority>\n"
            f"  </url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/sitemap-static.xml", response_class=Response)
async def sitemap_static(request: Request):
    base = str(request.base_url).rstrip("/")
    static_routes = [
        ("/", "1.0", "hourly"),
        ("/search", "0.9", "hourly"),
        ("/employers", "0.7", "daily"),
        ("/docs", "0.4", "weekly"),
        ("/llms.txt", "0.5", "daily"),
    ]
    urls = "\n".join(
        f"  <url><loc>{base}{path}</loc><priority>{prio}</priority><changefreq>{cf}</changefreq></url>"
        for path, prio, cf in static_routes
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls
        + "\n</urlset>"
    )
    return Response(content=xml, media_type="application/xml")
