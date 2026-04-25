"""Cheap pre-filters applied before any LLM call.

Used by both cmd_discover (scrape-time) and run_evaluation (eval-time) so
irrelevant jobs are dropped as early as possible.
"""

from __future__ import annotations

# Title tokens that indicate a role above the candidate's max seniority
_OVER_SENIORITY = (
    "staff engineer", "staff software", "principal engineer", "principal software",
    "distinguished engineer", "fellow", "director of", "vp ", "vp,", "vice president",
    "head of engineering", "engineering manager", " em,", "cto",
)

# Title tokens that indicate a role below mid-level
_UNDER_SENIORITY = (
    "junior ", "jr.", "entry level", "entry-level", "intern", "internship",
    "graduate engineer", "associate engineer",
)

_INDIA_CITIES = (
    "india", "hyderabad", "bangalore", "bengaluru", "delhi", "ncr",
    "gurugram", "gurgaon", "noida", "mumbai", "pune", "chennai",
)


def _location_passes(job: dict, prefs) -> bool:
    if prefs.remote_ok and job.get("remote"):
        return True
    loc = (job.get("location") or "").lower()
    if not loc:
        return True  # unknown location — let LLM decide
    pref_locs = [p.lower() for p in prefs.locations]
    if "remote" in pref_locs and "remote" in loc:
        return True
    if "india" in pref_locs and any(city in loc for city in _INDIA_CITIES):
        return True
    for pref_loc in pref_locs:
        if pref_loc in loc or loc in pref_loc:
            return True
    return False


def _tokenize(text: str) -> set[str]:
    return set(text.lower().replace(",", " ").replace("-", " ").replace("/", " ").split())


def _role_relevant(title: str, prefs) -> bool:
    """True if every token in at least one target_role appears in the title.

    "Software Engineer" matches "Senior Software Engineer" ✓
    "Software Engineer" does NOT match "Security Engineer" ✗
    Empty target_roles → all titles pass.
    """
    if not prefs.target_roles:
        return True
    title_tokens = _tokenize(title)
    for role in prefs.target_roles:
        role_tokens = _tokenize(role)
        if role_tokens and role_tokens.issubset(title_tokens):
            return True
    return False


def keyword_matches(description: str | None, prefs) -> bool:
    """True if description contains at least one tech_keyword.

    Always True when tech_keywords is empty or description is absent.
    """
    if not prefs.tech_keywords or not description:
        return True
    desc_lower = description.lower()
    return any(kw.lower() in desc_lower for kw in prefs.tech_keywords)


def hard_gate(job: dict, prefs) -> tuple[bool, str]:
    """Return (passes, reason). passes=False means skip this job entirely."""
    title = job.get("title", "")
    title_lower = title.lower()

    for excluded in prefs.excluded_titles:
        if excluded.lower() in title_lower:
            return False, f"excluded title: {excluded}"

    if not _role_relevant(title, prefs):
        return False, f"title not relevant to target roles: {title}"

    for token in _OVER_SENIORITY:
        if token in title_lower:
            return False, f"seniority too high: matched '{token}' in title"

    if prefs.seniority.min.lower() not in ("junior",):
        for token in _UNDER_SENIORITY:
            if token in title_lower:
                return False, f"seniority too low: matched '{token}' in title"

    if not _location_passes(job, prefs):
        return False, f"location mismatch: {job.get('location', 'unknown')}"

    return True, ""
