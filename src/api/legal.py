"""Legal stub pages — /legal, /privacy, /terms.

Referenced from /.well-known/ai-plugin.json and footer links. Minimal
content for now; expand when we have actual legal review.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Legal"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/legal", response_class=HTMLResponse, summary="Legal overview")
async def legal(request: Request):
    return templates.TemplateResponse(request, "legal.html", {
        "page_title": "Legal",
        "page_intro": (
            "zammejobs is a free, AI-native job index licensed under "
            "CC-BY-4.0. Below: how we collect data, your privacy, and the "
            "terms under which the site is offered."
        ),
        "sections": [
            ("How we collect data", (
                "Jobs are crawled from public ATS APIs (Greenhouse, Workday, Lever, "
                "Ashby, SmartRecruiters, Recruitee, Personio, Workable, Bullhorn, "
                "iCIMS, Taleo, SuccessFactors), public aggregator APIs (Adzuna, "
                "USAJobs, Reed, Jooble, Careerjet, Canada Job Bank, RemoteOK, "
                "Remotive, Arbeitnow, The Muse), the Shazamme XML feed, and Common "
                "Crawl JobPosting structured data. We do not scrape sites that "
                "block crawlers via robots.txt."
            )),
            ("What we do not collect", (
                "No user accounts, no cookies (other than the theme preference), "
                "no analytics that fingerprint individuals, no third-party trackers, "
                "no email collection. We log standard request metadata "
                "(IP, user-agent) for 14 days for abuse mitigation, then discard."
            )),
            ("AI / LLM use", (
                "All public job-index data is licensed CC-BY-4.0. Training, "
                "fine-tuning, retrieval, embedding, and inference are explicitly "
                "permitted (see /ai.txt). Attribution preferred but not required. "
                "AI labs can email hello@zammejobs.com for a rate-limit-free "
                "allowlist."
            )),
            ("Employer content", (
                "Job descriptions, employer names, and apply URLs are public-facing "
                "data published by employers via their ATS or aggregator partners. "
                "We retain a snapshot until the source feed marks the job inactive, "
                "at which point we mark it expired (not deleted) so historical "
                "queries still work. Employers wishing to remove a posting can email "
                "hello@zammejobs.com or remove it from their source ATS."
            )),
            ("Outbound links", (
                "Apply links route through /apply/{job_id} which (1) HEAD-checks "
                "the destination URL, (2) appends source=zammejobs and utm_source/"
                "utm_medium parameters for attribution, (3) redirects you to the "
                "employer's ATS. We never inject affiliate links and never charge "
                "per click."
            )),
            ("Liability", (
                "Job descriptions and salaries are reproduced from the source feed. "
                "We do our best to keep them current, but always verify on the "
                "employer's site before applying. Use of zammejobs is at your own "
                "risk; the service is provided AS IS without warranty."
            )),
            ("Contact", (
                "Email hello@zammejobs.com for any legal, privacy, takedown, or "
                "partnership question."
            )),
        ],
    })


@router.get("/privacy", response_class=HTMLResponse, summary="Privacy policy")
async def privacy(request: Request):
    return templates.TemplateResponse(request, "legal.html", {
        "page_title": "Privacy",
        "page_intro": (
            "We collect as little as possible. You can browse zammejobs without "
            "signing up, providing email, or accepting cookies. The site uses "
            "exactly one localStorage key (theme preference) and zero third-party "
            "trackers."
        ),
        "sections": [
            ("Data we collect", "Standard server logs (IP, user-agent, timestamp, path) for 14 days for abuse mitigation. After 14 days the logs are aggregated into anonymous counts and the raw entries discarded."),
            ("What we don't collect", "No user accounts. No analytics cookies. No fingerprinting. No third-party trackers. No email collection. No marketing data."),
            ("Outbound clicks", "When you click Apply, we record nothing. The redirect goes through /apply/{job_id} which HEAD-checks the URL and appends source=zammejobs for the employer's analytics. We do not track which jobs you viewed or applied to."),
            ("AI/LLM access", "Bots are explicitly allowed (see /robots.txt and /ai.txt). They are subject to the same logging rules: 14-day retention, then discard."),
            ("Cookies", "Zero. The single localStorage key is `zammejobs-theme` to remember your dark/light preference. You can clear it any time via your browser settings."),
            ("Your rights", "Email hello@zammejobs.com for any data inquiry. We respond within 7 days. EU/UK/CA users have GDPR/UK-GDPR/PIPEDA rights — same email applies."),
        ],
    })


@router.get("/terms", response_class=HTMLResponse, summary="Terms of service")
async def terms(request: Request):
    return templates.TemplateResponse(request, "legal.html", {
        "page_title": "Terms of service",
        "page_intro": (
            "Plain-English terms. zammejobs is free to use, with a permissive "
            "license on the data and minimal restrictions on use."
        ),
        "sections": [
            ("Data license", "All public job-index data is licensed under Creative Commons Attribution 4.0 International (CC-BY-4.0). You may copy, redistribute, transform, and build upon the data for any purpose, including commercially, provided you give appropriate credit."),
            ("API & MCP", "The REST API at /api/v1 and the MCP server at /mcp are free to use without an account. AI assistants and AI labs have no rate limit; please email hello@zammejobs.com to be added to the priority allowlist with your User-Agent."),
            ("No warranty", "The service is provided AS IS, without warranty of any kind. Job descriptions, salaries, and posting status come from third-party feeds and may be stale."),
            ("Acceptable use", "Don't try to break the API, don't redistribute under a more restrictive license than CC-BY-4.0, don't impersonate zammejobs or its employers."),
            ("Changes", "These terms may update; the latest version is always at /terms. Material changes will be announced via the GitHub repo (rickmareshazamme/job-ingestion-engine) and the AI-distribution feeds."),
            ("Contact", "hello@zammejobs.com."),
        ],
    })
