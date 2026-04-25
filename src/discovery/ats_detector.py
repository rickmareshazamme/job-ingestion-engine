"""ATS platform detection from any URL.

Ported from career-site-grader/grader.py _detect_ats().
Given a URL, fetches the page, detects which ATS platform is used,
and returns the appropriate connector type + board token if extractable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from src.config import settings

logger = logging.getLogger("jobindex.discovery.ats")

ATS_PATTERNS = {
    "greenhouse": r"greenhouse\.io|boards\.greenhouse|grnh\.se|boards-api\.greenhouse",
    "lever": r"lever\.co|jobs\.lever\.co",
    "workday": r"workday\.com|myworkdayjobs\.com|wd\d+\.myworkdayjobs",
    "taleo": r"taleo\.net|oracle.*taleo",
    "icims": r"icims\.com|careers-.*\.icims",
    "smartrecruiters": r"smartrecruiters\.com|jobs\.smartrecruiters",
    "bamboohr": r"bamboohr\.com",
    "jobvite": r"jobvite\.com|jobs\.jobvite",
    "ashby": r"ashbyhq\.com|jobs\.ashbyhq",
    "breezy": r"breezy\.hr",
    "workable": r"workable\.com|apply\.workable",
    "jazzhr": r"jazzhr\.com|app\.jazz\.co",
    "recruitee": r"recruitee\.com",
    "pinpoint": r"pinpointhq\.com",
    "personio": r"personio\.(de|com)|jobs\.personio",
    "successfactors": r"successfactors\.com|sap\.com/career",
    "bullhorn": r"bullhorn\.com|bullhornstaffing",
}

# Maps detected ATS to connector source_type
ATS_TO_CONNECTOR = {
    "greenhouse": "greenhouse_api",
    "lever": "lever_api",
    "workday": "workday_feed",
    "ashby": "ashby_api",
    "workable": "workable_api",
    "smartrecruiters": "smartrecruiters_sitemap",
    "recruitee": "recruitee_api",
    "personio": "personio_xml",
}

# Regex to extract board tokens from URLs
TOKEN_EXTRACTORS = {
    "greenhouse": [
        re.compile(r"boards\.greenhouse\.io/(\w+)"),
        re.compile(r"boards-api\.greenhouse\.io/v1/boards/(\w+)"),
        re.compile(r"grnh\.se/(\w+)"),
    ],
    "lever": [
        re.compile(r"jobs\.lever\.co/(\w+)"),
    ],
    "ashby": [
        re.compile(r"jobs\.ashbyhq\.com/(\w+)"),
    ],
    "workable": [
        re.compile(r"apply\.workable\.com/(\w+)"),
    ],
    "recruitee": [
        re.compile(r"(\w+)\.recruitee\.com"),
    ],
    "smartrecruiters": [
        re.compile(r"careers\.smartrecruiters\.com/(\w+)"),
        re.compile(r"jobs\.smartrecruiters\.com/(\w+)"),
    ],
    "workday": [
        re.compile(r"(\w+)\.wd(\d+)\.myworkdayjobs\.com"),
    ],
}


@dataclass
class ATSDetection:
    """Result of ATS detection on a URL."""
    url: str
    ats_platform: Optional[str] = None
    connector_type: Optional[str] = None
    board_token: Optional[str] = None
    confidence: float = 0.0
    raw_html_size: int = 0


async def detect_ats(url: str, timeout: int = 15) -> ATSDetection:
    """Fetch a URL and detect which ATS platform it uses.

    Returns ATSDetection with platform, connector type, and board token if extractable.
    """
    result = ATSDetection(url=url)

    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": settings.bot_user_agent},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return result

                html = await resp.text()
                result.raw_html_size = len(html)
                final_url = str(resp.url)

    except Exception as e:
        logger.debug("Failed to fetch %s: %s", url, str(e)[:100])
        return result

    # Check the final URL first (redirects often reveal the ATS)
    combined = f"{html.lower()} {final_url.lower()}"

    # Also extract iframe sources
    soup = BeautifulSoup(html, "lxml")
    iframes = soup.find_all("iframe")
    iframe_srcs = " ".join((f.get("src", "") or "") for f in iframes).lower()
    combined = f"{combined} {iframe_srcs}"

    # Detect ATS
    for ats_name, pattern in ATS_PATTERNS.items():
        if re.search(pattern, combined, re.I):
            result.ats_platform = ats_name
            result.connector_type = ATS_TO_CONNECTOR.get(ats_name)
            result.confidence = 0.9

            # Try to extract board token
            extractors = TOKEN_EXTRACTORS.get(ats_name, [])
            for extractor in extractors:
                match = extractor.search(combined)
                if match:
                    if ats_name == "workday":
                        # Workday needs company|instance|site
                        company = match.group(1)
                        instance = match.group(2)
                        result.board_token = f"{company}|{instance}|External"
                    else:
                        result.board_token = match.group(1)
                    result.confidence = 1.0
                    break

            logger.info("Detected %s at %s (token: %s)", ats_name, url, result.board_token)
            return result

    return result


async def detect_ats_for_domain(domain: str) -> ATSDetection:
    """Try common career page paths for a domain and detect ATS.

    Checks: /careers, /jobs, /about/careers, /join-us, etc.
    """
    career_paths = [
        "/careers",
        "/jobs",
        "/career",
        "/join",
        "/join-us",
        "/about/careers",
        "/company/careers",
        "/work-with-us",
        "/open-positions",
        "/vacancies",
    ]

    for path in career_paths:
        url = f"https://{domain}{path}"
        result = await detect_ats(url, timeout=10)
        if result.ats_platform:
            return result

    # Try the homepage as fallback
    result = await detect_ats(f"https://{domain}", timeout=10)
    return result
