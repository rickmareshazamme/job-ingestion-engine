"""Job classification — employment type, category, seniority, remote detection."""

from __future__ import annotations

import re

# Employment type mapping (reused from duda-job-schema)
EMPLOYMENT_TYPE_MAP = {
    "permanent": "FULL_TIME",
    "full_time": "FULL_TIME",
    "full-time": "FULL_TIME",
    "full time": "FULL_TIME",
    "regular": "FULL_TIME",
    "part_time": "PART_TIME",
    "part-time": "PART_TIME",
    "part time": "PART_TIME",
    "contract": "CONTRACTOR",
    "contractor": "CONTRACTOR",
    "freelance": "CONTRACTOR",
    "consulting": "CONTRACTOR",
    "temp": "TEMPORARY",
    "temporary": "TEMPORARY",
    "casual": "TEMPORARY",
    "seasonal": "TEMPORARY",
    "intern": "INTERN",
    "internship": "INTERN",
    "co-op": "INTERN",
    "apprentice": "INTERN",
    "apprenticeship": "INTERN",
    "volunteer": "VOLUNTEER",
    "per diem": "PER_DIEM",
}

# Seniority patterns
SENIORITY_PATTERNS = [
    (re.compile(r"\b(c-suite|chief|cto|cfo|ceo|coo|cio|cmo|vp|vice president)\b", re.I), "executive"),
    (re.compile(r"\b(director|head of|svp|senior vice president)\b", re.I), "director"),
    (re.compile(r"\b(principal|staff|distinguished|fellow)\b", re.I), "principal"),
    (re.compile(r"\b(lead|team lead|tech lead|engineering lead)\b", re.I), "lead"),
    (re.compile(r"\b(senior|sr\.?|snr\.?)\b", re.I), "senior"),
    (re.compile(r"\b(mid[- ]?level|intermediate)\b", re.I), "mid"),
    (re.compile(r"\b(junior|jr\.?|entry[- ]?level|associate|graduate|grad)\b", re.I), "junior"),
    (re.compile(r"\b(intern|internship|co-?op|apprentice|trainee|student)\b", re.I), "intern"),
]

# Category keywords mapped to normalized categories
CATEGORY_KEYWORDS = {
    "Engineering": [
        r"engineer", r"developer", r"programmer", r"software", r"devops",
        r"sre", r"platform", r"infrastructure", r"backend", r"frontend",
        r"full[- ]?stack", r"mobile", r"ios", r"android", r"embedded",
    ],
    "Data & Analytics": [
        r"data scien", r"data engineer", r"data analyst", r"machine learning",
        r"ml engineer", r"ai ", r"artificial intelligence", r"analytics",
        r"business intelligence", r"bi ", r"statistician",
    ],
    "Design": [
        r"designer", r"ux", r"ui", r"product design", r"graphic",
        r"visual design", r"interaction design", r"brand design",
    ],
    "Product": [
        r"product manager", r"product owner", r"program manager",
        r"scrum master", r"agile", r"project manager",
    ],
    "Marketing": [
        r"marketing", r"growth", r"seo", r"content", r"brand",
        r"communications", r"social media", r"digital marketing",
    ],
    "Sales": [
        r"sales", r"account executive", r"account manager", r"business development",
        r"bdr", r"sdr", r"revenue", r"partnerships",
    ],
    "Customer Success": [
        r"customer success", r"customer support", r"customer service",
        r"client success", r"support engineer", r"help desk",
    ],
    "Finance": [
        r"financ", r"accountant", r"accounting", r"controller",
        r"treasury", r"audit", r"tax ", r"bookkeep",
    ],
    "HR & People": [
        r"human resource", r"hr ", r"people ops", r"talent acquisition",
        r"recruiter", r"recruiting", r"people partner", r"compensation",
    ],
    "Legal": [
        r"legal", r"counsel", r"attorney", r"lawyer", r"compliance",
        r"paralegal", r"regulatory",
    ],
    "Operations": [
        r"operations", r"supply chain", r"logistics", r"procurement",
        r"warehouse", r"fleet", r"facilities",
    ],
    "Healthcare": [
        r"nurse", r"doctor", r"physician", r"pharmacist", r"clinical",
        r"medical", r"health", r"therapist", r"dentist",
    ],
    "Education": [
        r"teacher", r"professor", r"instructor", r"curriculum",
        r"education", r"training", r"learning",
    ],
    "Security": [
        r"security", r"cybersecurity", r"infosec", r"penetration",
        r"soc analyst", r"threat",
    ],
    "IT & Infrastructure": [
        r"system admin", r"sysadmin", r"network", r"it manager",
        r"helpdesk", r"it support", r"database admin", r"dba",
    ],
}


def classify_employment_type(raw: str | None) -> str:
    """Map raw employment type to Schema.org enum."""
    if not raw:
        return "FULL_TIME"
    key = raw.lower().strip()
    return EMPLOYMENT_TYPE_MAP.get(key, "FULL_TIME")


def detect_seniority(title: str) -> str | None:
    """Detect seniority level from job title."""
    if not title:
        return None
    for pattern, level in SENIORITY_PATTERNS:
        if pattern.search(title):
            return level
    return "mid"


def classify_categories(title: str, description: str = "") -> list[str]:
    """Classify job into categories based on title and description."""
    combined = f"{title} {description[:500]}".lower()
    matched = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, combined, re.IGNORECASE):
                matched.append(category)
                break

    return matched if matched else ["Other"]


def detect_remote(title: str, location: str = "", description: str = "") -> tuple[bool, str]:
    """Detect remote work from title, location, and description.

    Returns (is_remote, remote_type) where remote_type is onsite|hybrid|remote.
    """
    combined = f"{title} {location}".lower()

    hybrid_patterns = re.compile(r"\b(hybrid|flexible|partly remote)\b", re.I)
    remote_patterns = re.compile(
        r"\b(remote|work from home|wfh|telecommute|anywhere|distributed|fully remote)\b", re.I
    )

    if hybrid_patterns.search(combined):
        return True, "hybrid"
    if remote_patterns.search(combined):
        return True, "remote"

    # Check description (first 1000 chars) as fallback
    desc_start = description[:1000].lower()
    if remote_patterns.search(desc_start):
        return True, "remote"
    if hybrid_patterns.search(desc_start):
        return True, "hybrid"

    return False, "onsite"
