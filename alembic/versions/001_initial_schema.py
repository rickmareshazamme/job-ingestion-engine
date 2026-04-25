"""Initial schema — employers, source_configs, jobs, crawl_runs

Revision ID: 001
Revises:
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), unique=True, nullable=False),
        sa.Column("logo_url", sa.Text()),
        sa.Column("ats_platform", sa.Text()),
        sa.Column("career_page_url", sa.Text()),
        sa.Column("country", sa.Text()),
        sa.Column("employee_count", sa.Text()),
        sa.Column("claimed", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "source_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employers.id")),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("crawl_interval_hours", sa.Integer(), server_default="6"),
        sa.Column("last_crawl_at", sa.DateTime(timezone=True)),
        sa.Column("last_crawl_status", sa.Text()),
        sa.Column("last_crawl_job_count", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("rate_limit_rpm", sa.Integer(), server_default="30"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("ats_platform", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description_html", sa.Text()),
        sa.Column("description_text", sa.Text()),
        sa.Column("employer_name", sa.Text(), nullable=False),
        sa.Column("employer_domain", sa.Text(), nullable=False),
        sa.Column("employer_logo_url", sa.Text()),
        sa.Column("employer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employers.id")),
        sa.Column("location_raw", sa.Text()),
        sa.Column("location_city", sa.Text()),
        sa.Column("location_state", sa.Text()),
        sa.Column("location_country", sa.Text(), nullable=False),
        sa.Column("location_lat", sa.Float()),
        sa.Column("location_lng", sa.Float()),
        sa.Column("is_remote", sa.Boolean(), server_default="false"),
        sa.Column("remote_type", sa.Text(), server_default="'onsite'"),
        sa.Column("salary_min", sa.Integer()),
        sa.Column("salary_max", sa.Integer()),
        sa.Column("salary_currency", sa.Text()),
        sa.Column("salary_period", sa.Text()),
        sa.Column("salary_raw", sa.Text()),
        sa.Column("employment_type", sa.Text()),
        sa.Column("categories", postgresql.ARRAY(sa.Text())),
        sa.Column("seniority", sa.Text()),
        sa.Column("date_posted", sa.DateTime()),
        sa.Column("date_expires", sa.DateTime()),
        sa.Column("date_crawled", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("date_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.Text(), server_default="'active'"),
        sa.Column("raw_data", postgresql.JSONB()),
        sa.UniqueConstraint("source_type", "source_id", name="uq_source"),
    )

    # Indexes
    op.create_index("idx_jobs_content_hash", "jobs", ["content_hash"])
    op.create_index("idx_jobs_employer_domain", "jobs", ["employer_domain"])
    op.create_index("idx_jobs_status", "jobs", ["status"])
    op.create_index("idx_jobs_country", "jobs", ["location_country"])
    op.create_index("idx_jobs_date_posted", "jobs", ["date_posted"])
    op.create_index("idx_jobs_categories", "jobs", ["categories"], postgresql_using="gin")

    op.create_table(
        "crawl_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_config_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_configs.id")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("jobs_found", sa.Integer(), server_default="0"),
        sa.Column("jobs_new", sa.Integer(), server_default="0"),
        sa.Column("jobs_updated", sa.Integer(), server_default="0"),
        sa.Column("jobs_removed", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_seconds", sa.Float()),
    )


def downgrade() -> None:
    op.drop_table("crawl_runs")
    op.drop_table("jobs")
    op.drop_table("source_configs")
    op.drop_table("employers")
