import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.sql import func

from src.db import Base


class Employer(Base):
    __tablename__ = "employers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    domain = Column(Text, unique=True, nullable=False)
    logo_url = Column(Text)
    ats_platform = Column(Text)
    career_page_url = Column(Text)
    country = Column(Text)
    employee_count = Column(Text)
    claimed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SourceConfig(Base):
    __tablename__ = "source_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employer_id = Column(UUID(as_uuid=True), ForeignKey("employers.id"))
    source_type = Column(Text, nullable=False)
    config = Column(JSONB, nullable=False)
    crawl_interval_hours = Column(Integer, default=6)
    last_crawl_at = Column(DateTime(timezone=True))
    last_crawl_status = Column(Text)
    last_crawl_job_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    rate_limit_rpm = Column(Integer, default=30)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_hash = Column(Text, nullable=False, index=True)

    # Source
    source_type = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    source_url = Column(Text)
    ats_platform = Column(Text)

    # Content
    title = Column(Text, nullable=False)
    description_html = Column(Text)
    description_text = Column(Text)

    # Employer
    employer_name = Column(Text, nullable=False)
    employer_domain = Column(Text, nullable=False, index=True)
    employer_logo_url = Column(Text)
    employer_id = Column(UUID(as_uuid=True), ForeignKey("employers.id"))

    # Location
    location_raw = Column(Text)
    location_city = Column(Text)
    location_state = Column(Text)
    location_country = Column(Text, nullable=False, index=True)
    location_lat = Column(Float)
    location_lng = Column(Float)
    is_remote = Column(Boolean, default=False)
    remote_type = Column(Text, default="onsite")

    # Salary
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_currency = Column(Text)
    salary_period = Column(Text)
    salary_raw = Column(Text)

    # Classification
    employment_type = Column(Text)
    categories = Column(ARRAY(Text))
    seniority = Column(Text)

    # Dates
    date_posted = Column(DateTime)
    date_expires = Column(DateTime)
    date_crawled = Column(DateTime(timezone=True), server_default=func.now())
    date_updated = Column(DateTime(timezone=True), server_default=func.now())

    # Status + raw
    status = Column(Text, default="active", index=True)
    raw_data = Column(JSONB)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_source"),
        Index("idx_jobs_date_posted", "date_posted"),
        Index("idx_jobs_categories", "categories", postgresql_using="gin"),
    )


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_config_id = Column(UUID(as_uuid=True), ForeignKey("source_configs.id"))
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False)
    jobs_found = Column(Integer, default=0)
    jobs_new = Column(Integer, default=0)
    jobs_updated = Column(Integer, default=0)
    jobs_removed = Column(Integer, default=0)
    error_message = Column(Text)
    duration_seconds = Column(Float)
