"""Location parsing and geocoding.

Parses raw location strings into structured components and optionally
geocodes them via OpenCage API for lat/lng coordinates.
"""

import re
from dataclasses import dataclass
from typing import Optional

import httpx

from src.config import settings


@dataclass
class ParsedLocation:
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    is_remote: bool = False
    remote_type: str = "onsite"


# Common remote indicators
REMOTE_PATTERNS = re.compile(
    r"\b(remote|work from home|wfh|telecommute|anywhere|distributed)\b",
    re.IGNORECASE,
)

HYBRID_PATTERNS = re.compile(
    r"\b(hybrid|flexible location|partly remote|partial remote)\b",
    re.IGNORECASE,
)

# Country code mapping for common country names
COUNTRY_MAP = {
    "united states": "US", "usa": "US", "u.s.a.": "US", "u.s.": "US",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "australia": "AU", "aus": "AU",
    "canada": "CA", "can": "CA",
    "new zealand": "NZ",
    "germany": "DE", "deutschland": "DE",
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
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "belgium": "BE",
    "portugal": "PT",
    "poland": "PL",
    "czech republic": "CZ", "czechia": "CZ",
    "israel": "IL",
    "south korea": "KR", "korea": "KR",
    "china": "CN",
    "hong kong": "HK",
    "taiwan": "TW",
    "mexico": "MX",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "south africa": "ZA",
    "united arab emirates": "AE", "uae": "AE",
    "saudi arabia": "SA",
    "philippines": "PH",
    "indonesia": "ID",
    "thailand": "TH",
    "vietnam": "VN",
    "malaysia": "MY",
}

# US state abbreviations
US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
US_STATE_ABBREVS = {v for v in US_STATES.values()}

# Australian states
AU_STATES = {
    "new south wales": "NSW", "victoria": "VIC", "queensland": "QLD",
    "south australia": "SA", "western australia": "WA", "tasmania": "TAS",
    "northern territory": "NT", "australian capital territory": "ACT",
}
AU_STATE_ABBREVS = {v for v in AU_STATES.values()}


def parse_location(raw: str) -> ParsedLocation:
    """Parse a raw location string into structured components."""
    if not raw or not raw.strip():
        return ParsedLocation()

    result = ParsedLocation()
    cleaned = raw.strip()

    # Check remote
    if REMOTE_PATTERNS.search(cleaned):
        result.is_remote = True
        result.remote_type = "remote"
    if HYBRID_PATTERNS.search(cleaned):
        result.is_remote = True
        result.remote_type = "hybrid"

    # Remove remote indicators for further parsing
    location_text = REMOTE_PATTERNS.sub("", cleaned).strip()
    location_text = HYBRID_PATTERNS.sub("", location_text).strip()
    location_text = re.sub(r"^[\s,\-/|]+|[\s,\-/|]+$", "", location_text)

    if not location_text:
        return result

    # Split by common delimiters
    parts = re.split(r"[,\|/]+", location_text)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return result

    # When there's only one part and it's a 2-letter code, treat as country code
    # (e.g., "DE" = Germany, not Delaware). State disambiguation requires a city.
    last_part_lower = parts[-1].lower().strip()
    last_part_upper = parts[-1].strip().upper()

    if len(parts) == 1 and len(last_part_upper) == 2 and last_part_upper.isalpha():
        # Single 2-letter code: treat as country
        if last_part_lower in COUNTRY_MAP:
            result.country = COUNTRY_MAP[last_part_lower]
        else:
            result.country = last_part_upper
        return result

    # Try to identify state BEFORE country to avoid "CA" being matched as country
    if last_part_upper in US_STATE_ABBREVS:
        result.state = last_part_upper
        result.country = "US"
        parts = parts[:-1]
    elif last_part_upper in AU_STATE_ABBREVS:
        result.state = last_part_upper
        result.country = "AU"
        parts = parts[:-1]
    elif last_part_lower in US_STATES:
        result.state = US_STATES[last_part_lower]
        result.country = "US"
        parts = parts[:-1]
    elif last_part_lower in AU_STATES:
        result.state = AU_STATES[last_part_lower]
        result.country = "AU"
        parts = parts[:-1]
    elif last_part_lower in COUNTRY_MAP:
        result.country = COUNTRY_MAP[last_part_lower]
        parts = parts[:-1]
    elif len(last_part_lower) == 2 and last_part_lower.upper().isalpha():
        result.country = last_part_lower.upper()
        parts = parts[:-1]

    # Try to identify state from remaining parts (if not already found)
    if parts and not result.state:
        last_part_lower = parts[-1].lower().strip()
        last_part_upper = parts[-1].strip().upper()

        if last_part_lower in US_STATES:
            result.state = US_STATES[last_part_lower]
            if not result.country:
                result.country = "US"
            parts = parts[:-1]
        elif last_part_upper in US_STATE_ABBREVS:
            result.state = last_part_upper
            if not result.country:
                result.country = "US"
            parts = parts[:-1]
        elif last_part_lower in AU_STATES:
            result.state = AU_STATES[last_part_lower]
            if not result.country:
                result.country = "AU"
            parts = parts[:-1]
        elif last_part_upper in AU_STATE_ABBREVS:
            result.state = last_part_upper
            if not result.country:
                result.country = "AU"
            parts = parts[:-1]

    # Remaining is the city
    if parts:
        result.city = parts[0].strip()

    return result


async def geocode(location: ParsedLocation, raw: str) -> ParsedLocation:
    """Geocode a parsed location using OpenCage API."""
    if not settings.opencage_api_key:
        return location

    query_parts = []
    if location.city:
        query_parts.append(location.city)
    if location.state:
        query_parts.append(location.state)
    if location.country:
        query_parts.append(location.country)

    query = ", ".join(query_parts) if query_parts else raw
    if not query:
        return location

    url = "https://api.opencagedata.com/geocode/v1/json"
    params = {
        "q": query,
        "key": settings.opencage_api_key,
        "limit": 1,
        "no_annotations": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return location

        result = results[0]
        geometry = result.get("geometry", {})
        components = result.get("components", {})

        location.lat = geometry.get("lat")
        location.lng = geometry.get("lng")

        if not location.country:
            location.country = (components.get("country_code") or "").upper()
        if not location.city:
            location.city = (
                components.get("city")
                or components.get("town")
                or components.get("village")
                or ""
            )
        if not location.state:
            location.state = components.get("state_code") or components.get("state") or ""

    except Exception:
        pass

    return location
