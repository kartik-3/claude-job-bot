"""Cheap pre-filters applied before any LLM call.

Used by both cmd_discover (scrape-time) and run_evaluation (eval-time) so
irrelevant jobs are dropped as early as possible.
"""

from __future__ import annotations

import re

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


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens extracted via regex (handles punctuation cleanly)."""
    return set(re.findall(r'\b\w+\b', text.lower()))


def _location_passes(job: dict, prefs) -> bool:
    if prefs.remote_ok and job.get("remote"):
        return True
    loc = (job.get("location") or "").lower()
    if not loc:
        return True  # unknown location — let LLM decide
    loc_tokens = _tokens(loc)
    for pref_loc in prefs.locations:
        pref_lower = pref_loc.lower()
        if pref_lower == "remote" and "remote" in loc_tokens:
            return True
        # "india" pref matches any known India city even when country isn't in location string
        if pref_lower == "india" and any(city in loc for city in _INDIA_CITIES):
            return True
        # All pref tokens must appear in loc tokens (word-level, not character-level)
        pref_tokens = _tokens(pref_loc)
        if pref_tokens and pref_tokens.issubset(loc_tokens):
            return True
    return False


def _role_relevant(title: str, prefs) -> bool:
    """True if every word token in at least one target_role appears in the title.

    "Software Engineer" matches "Senior Software Engineer" ✓
    "Software Engineer" does NOT match "Security Engineer" ✗
    Empty target_roles → all titles pass.
    """
    if not prefs.target_roles:
        return True
    title_tokens = _tokens(title)
    for role in prefs.target_roles:
        role_tokens = _tokens(role)
        if role_tokens and role_tokens.issubset(title_tokens):
            return True
    return False


def keyword_matches(description: str | None, prefs) -> bool:
    """True if description matches at least one tech_keyword pattern.

    Keywords are treated as regex patterns (case-insensitive); plain strings
    work as before. Use patterns like 'react(js)?' or 'node\\.?js' for
    variations. Falls back to literal substring if the pattern is invalid.

    Always True when tech_keywords is empty or description is absent.
    """
    if not prefs.tech_keywords or not description:
        return True
    for kw in prefs.tech_keywords:
        try:
            if re.search(kw, description, re.IGNORECASE):
                return True
        except re.error:
            if kw.lower() in description.lower():
                return True
    return False


def hard_gate(job: dict, prefs) -> tuple[bool, str]:
    """Return (passes, reason). passes=False means skip this job entirely."""
    title = job.get("title", "")
    title_lower = title.lower()

    title_tokens = _tokens(title)

    for excluded in prefs.excluded_titles:
        if _tokens(excluded).issubset(title_tokens):
            return False, f"excluded title: {excluded}"

    # Seniority is a global gate — runs before role relevance so titles like
    # "Staff Engineer" or "VP Engineering" are caught here, not misclassified
    # as "irrelevant role".
    for token in _OVER_SENIORITY:
        if re.search(r'\b' + re.escape(token.strip()) + r'\b', title_lower):
            return False, f"seniority too high: matched '{token}' in title"

    if prefs.seniority.min.lower() not in ("junior",):
        for token in _UNDER_SENIORITY:
            if re.search(r'\b' + re.escape(token.strip()) + r'\b', title_lower):
                return False, f"seniority too low: matched '{token}' in title"

    if not _role_relevant(title, prefs):
        return False, f"title not relevant to target roles: {title}"

    if not _location_passes(job, prefs):
        return False, f"location mismatch: {job.get('location', 'unknown')}"

    return True, ""
