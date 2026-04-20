"""Deduplication engine for cross-source job matching."""

from __future__ import annotations

import hashlib
import re
import unicodedata


TITLE_ABBREVIATIONS = {
    r"\bsr\.?\b": "senior",
    r"\bjr\.?\b": "junior",
    r"\bmgr\.?\b": "manager",
    r"\beng\.?\b": "engineer",
    r"\bdev\.?\b": "developer",
    r"\bsnr\.?\b": "senior",
    r"\bassoc\.?\b": "associate",
    r"\bexec\.?\b": "executive",
    r"\bdir\.?\b": "director",
    r"\badmin\.?\b": "administrator",
    r"\bcoord\.?\b": "coordinator",
}


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip accents, expand abbreviations."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Expand common job title abbreviations before stripping punctuation
    for pattern, replacement in TITLE_ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_content_hash(title: str, employer_domain: str, location_country: str, location_city: str = "") -> str:
    """Generate SHA-256 content hash for deduplication.

    Hash components:
    - Normalized title
    - Employer domain (canonical)
    - Country code
    - City (if available)
    """
    normalized_title = _normalize_text(title)
    normalized_domain = employer_domain.lower().strip()
    normalized_country = (location_country or "").upper().strip()
    normalized_city = _normalize_text(location_city or "")

    content = f"{normalized_title}|{normalized_domain}|{normalized_country}|{normalized_city}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def titles_match_fuzzy(title1: str, title2: str, threshold: float = 0.85) -> bool:
    """Check if two titles are similar enough to be the same job.

    Uses normalized Levenshtein similarity.
    """
    t1 = _normalize_text(title1)
    t2 = _normalize_text(title2)

    if t1 == t2:
        return True

    max_len = max(len(t1), len(t2))
    if max_len == 0:
        return True

    distance = levenshtein_distance(t1, t2)
    similarity = 1 - (distance / max_len)

    return similarity >= threshold
