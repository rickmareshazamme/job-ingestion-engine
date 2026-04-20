"""Natural language query parser for job search.

Converts free-form queries like "remote Python jobs in Europe paying over 100K EUR"
into structured search parameters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedQuery:
    """Structured search parameters extracted from natural language."""

    keywords: str = ""
    country: Optional[str] = None
    city: Optional[str] = None
    is_remote: Optional[bool] = None
    remote_type: Optional[str] = None
    employment_type: Optional[str] = None
    seniority: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    employer: Optional[str] = None
    category: Optional[str] = None


# Region to country code mappings
REGION_MAP = {
    "europe": None,  # Multiple countries — handled specially
    "asia": None,
    "north america": None,
    "south america": None,
    "middle east": None,
    "africa": None,
    "oceania": None,
}

COUNTRY_KEYWORDS = {
    "us": "US", "usa": "US", "united states": "US", "america": "US",
    "uk": "GB", "united kingdom": "GB", "england": "GB", "britain": "GB",
    "australia": "AU", "aus": "AU",
    "canada": "CA",
    "germany": "DE",
    "france": "FR",
    "netherlands": "NL", "holland": "NL",
    "ireland": "IE",
    "singapore": "SG",
    "japan": "JP",
    "india": "IN",
    "brazil": "BR",
    "spain": "ES",
    "italy": "IT",
    "sweden": "SE",
    "switzerland": "CH",
    "new zealand": "NZ",
    "israel": "IL",
    "south korea": "KR",
    "china": "CN",
    "mexico": "MX",
    "uae": "AE",
    "south africa": "ZA",
    "portugal": "PT",
    "poland": "PL",
    "denmark": "DK",
    "norway": "NO",
    "finland": "FI",
    "austria": "AT",
    "belgium": "BE",
}

SENIORITY_KEYWORDS = {
    "intern": "intern", "internship": "intern",
    "junior": "junior", "entry level": "junior", "entry-level": "junior", "graduate": "junior",
    "mid level": "mid", "mid-level": "mid", "intermediate": "mid",
    "senior": "senior",
    "lead": "lead", "team lead": "lead",
    "principal": "principal", "staff": "principal",
    "director": "director",
    "executive": "executive", "vp": "executive", "c-level": "executive",
}

EMPLOYMENT_KEYWORDS = {
    "full time": "FULL_TIME", "full-time": "FULL_TIME", "permanent": "FULL_TIME",
    "part time": "PART_TIME", "part-time": "PART_TIME",
    "contract": "CONTRACTOR", "contractor": "CONTRACTOR", "freelance": "CONTRACTOR",
    "temporary": "TEMPORARY", "temp": "TEMPORARY",
    "internship": "INTERN",
}

CURRENCY_KEYWORDS = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "£": "GBP",
    "aud": "AUD", "a$": "AUD",
    "cad": "CAD", "c$": "CAD",
    "chf": "CHF",
    "inr": "INR", "rupee": "INR", "rupees": "INR",
    "sgd": "SGD",
    "nzd": "NZD",
    "jpy": "JPY", "yen": "JPY",
}

# Major cities for detection
CITY_KEYWORDS = {
    "san francisco": "San Francisco", "sf": "San Francisco",
    "new york": "New York", "nyc": "New York",
    "los angeles": "Los Angeles", "la": "Los Angeles",
    "chicago": "Chicago", "seattle": "Seattle", "austin": "Austin",
    "boston": "Boston", "denver": "Denver", "miami": "Miami",
    "london": "London", "manchester": "Manchester",
    "berlin": "Berlin", "munich": "Munich", "hamburg": "Hamburg",
    "paris": "Paris", "amsterdam": "Amsterdam",
    "sydney": "Sydney", "melbourne": "Melbourne", "brisbane": "Brisbane",
    "toronto": "Toronto", "vancouver": "Vancouver", "montreal": "Montreal",
    "tokyo": "Tokyo", "singapore": "Singapore",
    "dublin": "Dublin", "zurich": "Zurich",
    "bangalore": "Bangalore", "mumbai": "Mumbai", "delhi": "Delhi",
    "tel aviv": "Tel Aviv",
    "dubai": "Dubai",
    "sao paulo": "Sao Paulo",
}


def parse_natural_language(query: str) -> ParsedQuery:
    """Parse a natural language job search query into structured parameters.

    Examples:
        "remote Python jobs in Europe paying over 100K EUR"
        "senior data engineer in San Francisco $150k+"
        "part-time marketing jobs in London"
        "junior developer roles at Google"
        "contract DevOps engineer, Australia, AUD 120k-150k"
    """
    result = ParsedQuery()
    q = query.lower().strip()
    remaining = q

    # Detect remote
    if re.search(r"\b(remote|wfh|work from home|telecommute)\b", q):
        result.is_remote = True
        result.remote_type = "remote"
        remaining = re.sub(r"\b(remote|wfh|work from home|telecommute)\b", "", remaining)

    if re.search(r"\bhybrid\b", q):
        result.is_remote = True
        result.remote_type = "hybrid"
        remaining = re.sub(r"\bhybrid\b", "", remaining)

    # Detect salary with "over/above/more than" or "under/below/less than"
    over_match = re.search(
        r"(?:over|above|more than|at least|minimum|min|\+)\s*\$?(\d+)\s*k?\b",
        remaining
    )
    if over_match:
        val = int(over_match.group(1))
        result.salary_min = val * 1000 if val < 1000 else val
        remaining = remaining[:over_match.start()] + remaining[over_match.end():]

    under_match = re.search(
        r"(?:under|below|less than|up to|maximum|max)\s*\$?(\d+)\s*k?\b",
        remaining
    )
    if under_match:
        val = int(under_match.group(1))
        result.salary_max = val * 1000 if val < 1000 else val
        remaining = remaining[:under_match.start()] + remaining[under_match.end():]

    # Detect salary range "120k-150k" or "$120,000 - $150,000"
    range_match = re.search(
        r"\$?(\d+)\s*k?\s*[-–to]+\s*\$?(\d+)\s*k?\b",
        remaining
    )
    if range_match and result.salary_min is None:
        v1 = int(range_match.group(1))
        v2 = int(range_match.group(2))
        result.salary_min = v1 * 1000 if v1 < 1000 else v1
        result.salary_max = v2 * 1000 if v2 < 1000 else v2
        remaining = remaining[:range_match.start()] + remaining[range_match.end():]

    # Detect currency
    for kw, code in CURRENCY_KEYWORDS.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", q):
            result.salary_currency = code
            remaining = re.sub(r"\b" + re.escape(kw) + r"\b", "", remaining)
            break

    # Detect employer with "at <company>"
    at_match = re.search(r"\bat\s+([a-z][a-z0-9\s]+?)(?:\s+in\b|\s*$|,)", remaining)
    if at_match:
        employer_name = at_match.group(1).strip()
        if len(employer_name) > 1 and employer_name not in {"least", "most"}:
            result.employer = employer_name
            remaining = remaining[:at_match.start()] + remaining[at_match.end():]

    # Detect seniority (check longer phrases first)
    for kw in sorted(SENIORITY_KEYWORDS.keys(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(kw) + r"\b", remaining):
            result.seniority = SENIORITY_KEYWORDS[kw]
            remaining = re.sub(r"\b" + re.escape(kw) + r"\b", "", remaining)
            break

    # Detect employment type
    for kw in sorted(EMPLOYMENT_KEYWORDS.keys(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(kw) + r"\b", remaining):
            result.employment_type = EMPLOYMENT_KEYWORDS[kw]
            remaining = re.sub(r"\b" + re.escape(kw) + r"\b", "", remaining)
            break

    # Detect city (check longer names first)
    for kw in sorted(CITY_KEYWORDS.keys(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(kw) + r"\b", remaining):
            result.city = CITY_KEYWORDS[kw]
            remaining = re.sub(r"\b" + re.escape(kw) + r"\b", "", remaining)
            break

    # Detect country
    for kw in sorted(COUNTRY_KEYWORDS.keys(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(kw) + r"\b", remaining):
            result.country = COUNTRY_KEYWORDS[kw]
            remaining = re.sub(r"\b" + re.escape(kw) + r"\b", "", remaining)
            break

    # Clean remaining text as keywords
    remaining = re.sub(r"\b(jobs?|roles?|positions?|openings?|opportunities?|vacancies?|hiring|paying)\b", "", remaining)
    remaining = re.sub(r"\b(in|for|with|and|the|a|an|or)\b", "", remaining)
    remaining = re.sub(r"[,\-|/\$+]+", " ", remaining)
    remaining = re.sub(r"\s+", " ", remaining).strip()

    result.keywords = remaining

    return result
