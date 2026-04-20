"""Salary string parser.

Handles global salary formats:
- "$120k", "$120,000", "$120K - $150K"
- "AUD 80,000 - 100,000 p.a."
- "EUR 50/hr", "GBP 45 per hour"
- "Competitive", "DOE", "Negotiable"
- "Rs 15,00,000" (Indian format)
- Range formats with various separators
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedSalary:
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    currency: str = "USD"
    period: str = "YEAR"
    raw: str = ""


# Currency symbols and codes
CURRENCY_SYMBOLS = {
    "$": "USD", "USD": "USD", "US$": "USD",
    "£": "GBP", "GBP": "GBP",
    "€": "EUR", "EUR": "EUR",
    "A$": "AUD", "AU$": "AUD", "AUD": "AUD",
    "C$": "CAD", "CA$": "CAD", "CAD": "CAD",
    "NZ$": "NZD", "NZD": "NZD",
    "CHF": "CHF",
    "¥": "JPY", "JPY": "JPY",
    "₹": "INR", "INR": "INR", "Rs": "INR",
    "R": "ZAR", "ZAR": "ZAR",
    "SGD": "SGD", "S$": "SGD",
    "HKD": "HKD", "HK$": "HKD",
    "SEK": "SEK", "NOK": "NOK", "DKK": "DKK",
    "PLN": "PLN", "CZK": "CZK",
    "BRL": "BRL", "R$": "BRL",
    "MXN": "MXN",
    "AED": "AED",
    "SAR": "SAR",
}

# Period indicators
ANNUAL_PATTERNS = re.compile(
    r"\b(per annum|p\.?a\.?|per year|yearly|annual|annually|yr|/year|/yr)\b",
    re.IGNORECASE,
)
MONTHLY_PATTERNS = re.compile(
    r"\b(per month|monthly|p\.?m\.?|/month|/mo)\b",
    re.IGNORECASE,
)
HOURLY_PATTERNS = re.compile(
    r"\b(per hour|hourly|p\.?h\.?|/hour|/hr|an hour)\b",
    re.IGNORECASE,
)
DAILY_PATTERNS = re.compile(
    r"\b(per day|daily|p\.?d\.?|/day)\b",
    re.IGNORECASE,
)

# Non-numeric salary indicators
NON_NUMERIC = re.compile(
    r"^(competitive|negotiable|doe|dob|market rate|tbd|tbr|not disclosed|undisclosed|n/a)$",
    re.IGNORECASE,
)

# Number extraction: handles "120k", "120,000", "120.000", "15,00,000" (Indian)
NUMBER_PATTERN = re.compile(r"[\d]+(?:[,.\s]\d+)*(?:k)?", re.IGNORECASE)


def _extract_currency(text: str) -> str:
    """Extract currency from text."""
    # Check for multi-char symbols first (to avoid matching $ in AU$)
    for symbol in sorted(CURRENCY_SYMBOLS.keys(), key=len, reverse=True):
        if symbol in text or symbol.lower() in text.lower():
            return CURRENCY_SYMBOLS[symbol]
    return "USD"


def _parse_number(num_str: str) -> Optional[int]:
    """Parse a number string into an integer value."""
    if not num_str:
        return None

    cleaned = num_str.strip()
    has_k = cleaned.lower().endswith("k")
    if has_k:
        cleaned = cleaned[:-1]

    # Remove spaces
    cleaned = cleaned.replace(" ", "")

    # Handle Indian numbering (15,00,000)
    if re.match(r"^\d{1,2}(,\d{2})*(,\d{3})$", cleaned):
        cleaned = cleaned.replace(",", "")
    # Handle standard comma separators (120,000)
    elif "," in cleaned and "." in cleaned:
        # European style: 120.000,50 or US style: 120,000.50
        if cleaned.index(",") > cleaned.index("."):
            # European: dots are thousands, comma is decimal
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: commas are thousands, dot is decimal
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Could be thousand separator or decimal
        parts = cleaned.split(",")
        if len(parts[-1]) == 3:
            cleaned = cleaned.replace(",", "")
        elif len(parts[-1]) <= 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts[-1]) == 3 and len(parts) > 2:
            # European thousands separator
            cleaned = cleaned.replace(".", "")

    try:
        value = float(cleaned)
        if has_k:
            value *= 1000
        return int(value)
    except ValueError:
        return None


def _detect_period(text: str) -> str:
    """Detect salary period from text."""
    if HOURLY_PATTERNS.search(text):
        return "HOUR"
    if DAILY_PATTERNS.search(text):
        return "DAY"
    if MONTHLY_PATTERNS.search(text):
        return "MONTH"
    if ANNUAL_PATTERNS.search(text):
        return "YEAR"

    # Heuristic: if values are small, likely hourly
    numbers = NUMBER_PATTERN.findall(text)
    if numbers:
        first_val = _parse_number(numbers[0])
        if first_val is not None:
            if first_val < 200:
                return "HOUR"
            if first_val < 15000:
                return "MONTH"

    return "YEAR"


def parse_salary(raw: str) -> ParsedSalary:
    """Parse a raw salary string into structured components."""
    result = ParsedSalary(raw=raw)

    if not raw or not raw.strip():
        return result

    cleaned = raw.strip()

    # Check for non-numeric indicators
    if NON_NUMERIC.match(cleaned):
        return result

    result.currency = _extract_currency(cleaned)
    result.period = _detect_period(cleaned)

    # Extract all numbers
    numbers = NUMBER_PATTERN.findall(cleaned)
    parsed_numbers = [_parse_number(n) for n in numbers]
    parsed_numbers = [n for n in parsed_numbers if n is not None and n > 0]

    if len(parsed_numbers) >= 2:
        result.min_value = min(parsed_numbers[0], parsed_numbers[1])
        result.max_value = max(parsed_numbers[0], parsed_numbers[1])
    elif len(parsed_numbers) == 1:
        result.min_value = parsed_numbers[0]
        result.max_value = parsed_numbers[0]

    return result
