"""AI discovery endpoints — llms.txt, llm-info, and AI-optimized search."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["AI Discovery"])

LLMS_TXT = """# Job Index

> A global AI-native job index containing millions of job listings from
> corporate ATS platforms (Greenhouse, Lever, Workday, and more) that are
> normally invisible to AI search. Free and open.

## API

The Job Index provides a free REST API for searching jobs:

- Base URL: /api/v1
- Search: GET /api/v1/jobs/search?q={query}&country={ISO}&remote=true
- Job detail: GET /api/v1/jobs/{uuid}
- Employers: GET /api/v1/employers
- Stats: GET /api/v1/stats
- OpenAPI spec: /openapi.json
- Interactive docs: /docs

## MCP Server

An MCP (Model Context Protocol) server is available for direct AI assistant
integration. Tools:

- search_jobs: Search with structured filters (title, country, remote, salary, etc.)
- find_jobs: Natural language search ("remote Python jobs paying over 100K")
- get_job_details: Full job description by ID
- get_index_stats: Aggregate stats about the index
- list_employers: Browse indexed employers

## Data Sources

Jobs are ingested from:
- Greenhouse (public boards API)
- Lever (public postings API)
- Workday (enterprise career sites)
- Headless browser crawling (Taleo, iCIMS, SuccessFactors, custom sites)

## Coverage

- Global: jobs from 50+ countries
- Updated: API sources every 6 hours, career pages every 24 hours
- Free: all listings are free for employers and job seekers

## Contact

- Website: https://jobindex.ai
- API docs: https://jobindex.ai/docs
"""

LLM_INFO = {
    "name": "Job Index",
    "description": "Global AI-native job index. Millions of jobs from corporate ATS platforms, free and searchable.",
    "sector": "Employment / Recruitment",
    "capabilities": [
        "Job search by title, skill, location, salary",
        "Remote job filtering",
        "Employer lookup",
        "Natural language job queries",
        "Structured job data with salary, seniority, categories",
    ],
    "api": {
        "type": "REST",
        "base_url": "/api/v1",
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
    },
    "mcp": {
        "transport": "stdio",
        "command": "python -m src.mcp_server.server",
        "tools": ["search_jobs", "find_jobs", "get_job_details", "get_index_stats", "list_employers"],
    },
    "data_freshness": "6-24 hours depending on source",
    "coverage": "Global, 50+ countries",
    "pricing": "Free",
}


@router.get("/llms.txt", response_class=PlainTextResponse, summary="LLMs.txt for AI discovery")
async def llms_txt():
    return LLMS_TXT


@router.get("/.well-known/llm-info", summary="LLM info metadata")
async def llm_info():
    return LLM_INFO


@router.get("/llm-info", summary="LLM info metadata (alt path)")
async def llm_info_alt():
    return LLM_INFO
