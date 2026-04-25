"""Employer self-registration API.

Allows employers to:
1. Submit their career page URL for indexing
2. Claim their auto-indexed company profile
3. Verify domain ownership via DNS TXT record
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Employer, SourceConfig

logger = logging.getLogger("jobindex.api.employer_register")

router = APIRouter(prefix="/api/v1/employers", tags=["Employer Registration"])


class SubmitCareerPageRequest(BaseModel):
    career_url: str
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    contact_email: Optional[str] = None


class SubmitCareerPageResponse(BaseModel):
    status: str
    message: str
    employer_id: Optional[str] = None
    detected_ats: Optional[str] = None


@router.post(
    "/submit",
    response_model=SubmitCareerPageResponse,
    summary="Submit a career page for indexing",
    description=(
        "Submit your company's career page URL. We'll detect your ATS platform, "
        "index your jobs, and make them visible to AI search — for free."
    ),
)
async def submit_career_page(
    req: SubmitCareerPageRequest,
    session: AsyncSession = Depends(get_session),
):
    from urllib.parse import urlparse

    from src.discovery.ats_detector import detect_ats

    # Extract domain from URL
    parsed = urlparse(req.career_url)
    domain = req.company_domain or parsed.netloc.replace("www.", "")

    if not domain:
        raise HTTPException(status_code=400, detail="Could not determine company domain")

    # Check if employer already exists
    existing = await session.execute(
        select(Employer).where(Employer.domain == domain)
    )
    existing_employer = existing.scalar_one_or_none()

    if existing_employer:
        return SubmitCareerPageResponse(
            status="already_indexed",
            message=f"{domain} is already indexed with {existing_employer.ats_platform or 'unknown'} ATS.",
            employer_id=str(existing_employer.id),
            detected_ats=existing_employer.ats_platform,
        )

    # Detect ATS
    detection = await detect_ats(req.career_url)

    # Create employer
    employer = Employer(
        id=uuid.uuid4(),
        name=req.company_name or domain.split(".")[0].title(),
        domain=domain,
        ats_platform=detection.ats_platform,
        career_page_url=req.career_url,
        claimed=False,
    )
    session.add(employer)
    await session.flush()

    # Create source config if we know the connector
    if detection.connector_type and detection.board_token:
        source = SourceConfig(
            id=uuid.uuid4(),
            employer_id=employer.id,
            source_type=detection.connector_type,
            config={
                "board_token": detection.board_token,
                "employer_domain": domain,
            },
            crawl_interval_hours=6,
        )
        session.add(source)

    await session.commit()

    logger.info(
        "New employer submitted: %s (%s, ATS: %s, token: %s)",
        domain, req.career_url, detection.ats_platform, detection.board_token,
    )

    return SubmitCareerPageResponse(
        status="submitted",
        message=(
            f"Career page submitted for indexing. "
            f"{'Detected ATS: ' + detection.ats_platform + '. ' if detection.ats_platform else 'ATS not detected — we will crawl the page directly. '}"
            f"Jobs will appear in the index within 24 hours."
        ),
        employer_id=str(employer.id),
        detected_ats=detection.ats_platform,
    )


class ClaimCompanyRequest(BaseModel):
    domain: str
    contact_email: str


@router.post(
    "/claim",
    summary="Claim your company profile",
    description="Start the domain verification process to claim your company's profile.",
)
async def claim_company(
    req: ClaimCompanyRequest,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Employer).where(Employer.domain == req.domain)
    )
    employer = result.scalar_one_or_none()

    if not employer:
        raise HTTPException(status_code=404, detail=f"Company {req.domain} not found in index")

    if employer.claimed:
        return {"status": "already_claimed", "message": f"{req.domain} is already claimed."}

    # Generate verification token
    verify_token = str(uuid.uuid4())[:8]

    return {
        "status": "verification_required",
        "message": (
            f"To verify ownership of {req.domain}, add a DNS TXT record:\n\n"
            f"  jobindex-verify={verify_token}\n\n"
            f"Then call POST /api/v1/employers/verify with your domain."
        ),
        "verification_token": verify_token,
    }
