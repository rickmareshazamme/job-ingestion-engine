"""Career page discovery via DNS + HTTP probing.

Given a list of company domains, finds their career pages and
detects which ATS they use. This is how we find career sites
that aren't in any known board token list.

Discovery methods:
1. Probe common career page paths (/careers, /jobs, etc.)
2. Check for known ATS subdomain patterns (careers.company.com)
3. Check for ATS-hosted career pages (boards.greenhouse.io/company)
4. Follow redirects to detect ATS
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import aiohttp

from src.config import settings
from src.discovery.ats_detector import detect_ats, detect_ats_for_domain, ATSDetection

logger = logging.getLogger("jobindex.discovery.finder")


@dataclass
class DiscoveredCareerSite:
    domain: str
    career_url: str
    ats_platform: Optional[str]
    connector_type: Optional[str]
    board_token: Optional[str]


async def probe_domain(domain: str, semaphore: asyncio.Semaphore) -> Optional[DiscoveredCareerSite]:
    """Probe a single domain for a career page and ATS."""
    async with semaphore:
        # Method 1: Check known ATS patterns first (fastest)
        ats_checks = await _check_ats_patterns(domain)
        if ats_checks:
            return ats_checks

        # Method 2: Probe common career paths on the domain
        detection = await detect_ats_for_domain(domain)
        if detection.ats_platform:
            return DiscoveredCareerSite(
                domain=domain,
                career_url=detection.url,
                ats_platform=detection.ats_platform,
                connector_type=detection.connector_type,
                board_token=detection.board_token,
            )

        # Method 3: Check subdomains
        subdomain_result = await _check_subdomains(domain)
        if subdomain_result:
            return subdomain_result

        return None


async def _check_ats_patterns(domain: str) -> Optional[DiscoveredCareerSite]:
    """Check if the company has ATS-hosted career pages at known patterns."""
    company_slug = domain.split(".")[0].lower()

    checks = [
        # Greenhouse
        (f"https://boards-api.greenhouse.io/v1/boards/{company_slug}", "greenhouse", "greenhouse_api", company_slug),
        # Lever
        (f"https://api.lever.co/v0/postings/{company_slug}?mode=json&limit=1", "lever", "lever_api", company_slug),
        # Ashby
        (f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}", "ashby", "ashby_api", company_slug),
        # Workable
        (f"https://apply.workable.com/api/v1/widget/accounts/{company_slug}", "workable", "workable_api", company_slug),
        # Recruitee
        (f"https://{company_slug}.recruitee.com/api/offers/", "recruitee", "recruitee_api", company_slug),
    ]

    async with aiohttp.ClientSession(
        headers={"User-Agent": settings.bot_user_agent},
        timeout=aiohttp.ClientTimeout(total=8),
    ) as session:
        for url, ats, connector, token in checks:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        logger.info("Found %s career page for %s via %s", ats, domain, url)
                        return DiscoveredCareerSite(
                            domain=domain,
                            career_url=url,
                            ats_platform=ats,
                            connector_type=connector,
                            board_token=token,
                        )
            except Exception:
                pass

    return None


async def _check_subdomains(domain: str) -> Optional[DiscoveredCareerSite]:
    """Check career-related subdomains."""
    subdomains = [
        f"careers.{domain}",
        f"jobs.{domain}",
        f"career.{domain}",
        f"hiring.{domain}",
        f"join.{domain}",
        f"talent.{domain}",
        f"work.{domain}",
    ]

    for subdomain in subdomains:
        url = f"https://{subdomain}"
        detection = await detect_ats(url, timeout=8)
        if detection.ats_platform:
            return DiscoveredCareerSite(
                domain=domain,
                career_url=url,
                ats_platform=detection.ats_platform,
                connector_type=detection.connector_type,
                board_token=detection.board_token,
            )

    return None


async def discover_career_sites(domains: list[str], concurrency: int = 10) -> list[DiscoveredCareerSite]:
    """Discover career sites for a list of company domains."""
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [probe_domain(d, semaphore) for d in domains]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def save_discoveries(discoveries: list[DiscoveredCareerSite], filename: str = "discovered_career_sites.json"):
    """Save discoveries to JSON."""
    data = [
        {
            "domain": d.domain,
            "career_url": d.career_url,
            "ats_platform": d.ats_platform,
            "connector_type": d.connector_type,
            "board_token": d.board_token,
        }
        for d in discoveries
    ]
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved %d discoveries to %s", len(data), filename)
