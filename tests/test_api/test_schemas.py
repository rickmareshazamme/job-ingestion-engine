"""Tests for API schemas — validates serialization and defaults."""

import uuid
from datetime import datetime

import pytest

from src.api.schemas import (
    EmployerSummary,
    JobDetail,
    JobLocation,
    JobSalary,
    JobSearchResponse,
    JobSummary,
    PaginationMeta,
    StatsResponse,
)


class TestJobSummary:
    def test_minimal(self):
        job = JobSummary(
            id=uuid.uuid4(),
            title="Software Engineer",
            employer_name="Acme",
            employer_domain="acme.com",
            location=JobLocation(country="US"),
            salary=JobSalary(),
        )
        assert job.title == "Software Engineer"
        assert job.is_remote is False
        assert job.categories == []
        assert job.location.country == "US"

    def test_full(self):
        job = JobSummary(
            id=uuid.uuid4(),
            title="Senior Backend Engineer",
            employer_name="Stripe",
            employer_domain="stripe.com",
            employer_logo_url="https://stripe.com/logo.png",
            location=JobLocation(
                raw="San Francisco, CA",
                city="San Francisco",
                state="CA",
                country="US",
                lat=37.7749,
                lng=-122.4194,
                is_remote=False,
                remote_type="onsite",
            ),
            salary=JobSalary(
                min=180000,
                max=250000,
                currency="USD",
                period="YEAR",
            ),
            employment_type="FULL_TIME",
            seniority="senior",
            categories=["Engineering"],
            is_remote=False,
            date_posted=datetime(2026, 4, 15),
            source_url="https://boards.greenhouse.io/stripe/jobs/123",
            ats_platform="greenhouse",
        )
        assert job.salary.min == 180000
        assert job.salary.currency == "USD"
        assert "Engineering" in job.categories

    def test_json_serialization(self):
        job = JobSummary(
            id=uuid.uuid4(),
            title="Test",
            employer_name="Test",
            employer_domain="test.com",
            location=JobLocation(country="US"),
            salary=JobSalary(),
        )
        data = job.model_dump()
        assert isinstance(data["id"], uuid.UUID)
        assert data["title"] == "Test"
        assert data["location"]["country"] == "US"


class TestJobDetail:
    def test_includes_description(self):
        job = JobDetail(
            id=uuid.uuid4(),
            title="Engineer",
            employer_name="Co",
            employer_domain="co.com",
            location=JobLocation(country="US"),
            salary=JobSalary(),
            description_html="<p>Great job</p>",
            description_text="Great job",
            content_hash="abc123",
            status="active",
        )
        assert job.description_html == "<p>Great job</p>"
        assert job.status == "active"


class TestSearchResponse:
    def test_empty_results(self):
        resp = JobSearchResponse(
            data=[],
            meta=PaginationMeta(total=0, page=1, per_page=20, total_pages=1),
        )
        assert resp.meta.total == 0
        assert len(resp.data) == 0

    def test_pagination_meta(self):
        meta = PaginationMeta(total=105, page=3, per_page=20, total_pages=6)
        assert meta.total_pages == 6


class TestEmployerSummary:
    def test_defaults(self):
        emp = EmployerSummary(
            id=uuid.uuid4(),
            name="Acme Corp",
            domain="acme.com",
        )
        assert emp.claimed is False
        assert emp.job_count == 0
        assert emp.ats_platform is None


class TestStatsResponse:
    def test_defaults(self):
        stats = StatsResponse()
        assert stats.total_jobs == 0
        assert stats.jobs_by_country == {}

    def test_populated(self):
        stats = StatsResponse(
            total_jobs=50000,
            active_jobs=48000,
            total_employers=500,
            jobs_by_country={"US": 25000, "GB": 8000, "AU": 5000},
            jobs_by_ats={"greenhouse": 20000, "workday": 15000, "lever": 10000},
        )
        assert stats.jobs_by_country["US"] == 25000
        assert stats.total_employers == 500
