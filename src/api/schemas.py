"""Pydantic response/request schemas for the Job Index API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── Job Schemas ──────────────────────────────────────────────────────────────


class JobLocation(BaseModel):
    raw: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    is_remote: bool = False
    remote_type: str = "onsite"


class JobSalary(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    currency: Optional[str] = None
    period: Optional[str] = None
    raw: Optional[str] = None


class JobSummary(BaseModel):
    """Compact job representation for search results."""

    id: UUID
    title: str
    employer_name: str
    employer_domain: str
    employer_logo_url: Optional[str] = None
    location: JobLocation
    salary: JobSalary
    employment_type: Optional[str] = None
    seniority: Optional[str] = None
    categories: List[str] = []
    is_remote: bool = False
    remote_type: str = "onsite"
    date_posted: Optional[datetime] = None
    source_url: Optional[str] = None
    ats_platform: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class JobDetail(JobSummary):
    """Full job detail with description."""

    description_html: Optional[str] = None
    description_text: Optional[str] = None
    date_expires: Optional[datetime] = None
    date_crawled: Optional[datetime] = None
    date_updated: Optional[datetime] = None
    content_hash: str = ""
    status: str = "active"

    model_config = ConfigDict(from_attributes=True)


# ─── Employer Schemas ─────────────────────────────────────────────────────────


class EmployerSummary(BaseModel):
    id: UUID
    name: str
    domain: str
    logo_url: Optional[str] = None
    ats_platform: Optional[str] = None
    career_page_url: Optional[str] = None
    country: Optional[str] = None
    employee_count: Optional[str] = None
    claimed: bool = False
    job_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class EmployerDetail(EmployerSummary):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Search / Pagination ─────────────────────────────────────────────────────


class PaginationMeta(BaseModel):
    total: int
    page: int
    per_page: int
    total_pages: int


class JobSearchResponse(BaseModel):
    data: List[JobSummary]
    meta: PaginationMeta


class EmployerListResponse(BaseModel):
    data: List[EmployerSummary]
    meta: PaginationMeta


class StatsResponse(BaseModel):
    total_jobs: int = 0
    active_jobs: int = 0
    total_employers: int = 0
    jobs_by_country: dict = {}
    jobs_by_ats: dict = {}
    jobs_by_category: dict = {}
    last_crawl_at: Optional[datetime] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
