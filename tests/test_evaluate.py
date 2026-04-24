"""Tests for Phase 2 evaluation — hard gates and schema validation.
No live API calls; all LLM paths are tested via fixtures.
"""
import json

import pytest
from pydantic import ValidationError

from evaluator.evaluate import (
    EvaluationResult,
    Preferences,
    _location_passes,
    hard_gate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PREFS_DATA = {
    "target_roles": [
        "Software Engineer", "Software Developer",
        "Backend Engineer", "Backend Developer",
        "Frontend Engineer", "Frontend Developer",
        "Full Stack Engineer", "Full Stack Developer",
        "Platform Engineer", "Infrastructure Engineer",
        "Site Reliability Engineer", "DevOps Engineer", "Cloud Engineer",
        "ML Engineer", "Machine Learning Engineer", "AI Engineer",
        "Data Engineer", "Mobile Engineer", "iOS Engineer", "Android Engineer",
        "Python Engineer", "Python Developer",
        "Java Engineer", "Java Developer",
        "JavaScript Developer", "TypeScript Engineer", "Node Developer",
        "Software Development Engineer", "Member of Technical Staff",
    ],
    "locations": [
        "Hyderabad, India", "Bangalore/Bengaluru, India", "New Delhi, India",
        "India", "Remote",
    ],
    "remote_ok": True,
    "seniority": {"min": "mid", "max": "Senior"},
    "salary": {"min_inr": 200000, "currency": "INR"},
    "visa_sponsorship_needed": False,
    "fit_score_threshold": 70,
    "non_negotiables": [],
    "excluded_industries": [],
    "excluded_titles": ["QA Engineer", "Test Engineer"],
}


@pytest.fixture
def prefs() -> Preferences:
    return Preferences(**PREFS_DATA)


def make_job(**overrides) -> dict:
    base = {
        "id": "abc123",
        "company": "Acme",
        "title": "Software Engineer",
        "url": "https://example.com/job/1",
        "apply_url": None,
        "ats": "greenhouse",
        "description": None,
        "location": "Hyderabad, India",
        "remote": False,
        "posted_at": None,
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# Hard gate — excluded titles
# ---------------------------------------------------------------------------

def test_excluded_title_qa(prefs):
    passes, reason = hard_gate(make_job(title="QA Engineer"), prefs)
    assert not passes
    assert "excluded title" in reason


def test_excluded_title_test_engineer(prefs):
    passes, reason = hard_gate(make_job(title="Senior Test Engineer"), prefs)
    assert not passes
    assert "excluded title" in reason


def test_excluded_title_case_insensitive(prefs):
    passes, reason = hard_gate(make_job(title="qa engineer"), prefs)
    assert not passes


# ---------------------------------------------------------------------------
# Hard gate — seniority too high
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Staff Software Engineer",
    "Staff Engineer",
    "Principal Engineer",
    "Principal Software Engineer",
    "Director of Engineering",
    "VP Engineering",
    "VP, Engineering",
    "Vice President of Engineering",
])
def test_over_seniority(prefs, title):
    passes, reason = hard_gate(make_job(title=title), prefs)
    assert not passes, f"Expected rejection for: {title}"
    assert "seniority too high" in reason


# ---------------------------------------------------------------------------
# Hard gate — seniority too low
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Junior Software Engineer",
    "Jr. Software Engineer",
    "Entry Level Software Engineer",
    "Entry-Level Backend Engineer",
    "Software Engineering Intern",
])
def test_under_seniority(prefs, title):
    passes, reason = hard_gate(make_job(title=title), prefs)
    assert not passes, f"Expected rejection for: {title}"
    assert "seniority too low" in reason


# ---------------------------------------------------------------------------
# Hard gate — location
# ---------------------------------------------------------------------------

def test_location_mismatch_uk(prefs):
    passes, reason = hard_gate(make_job(location="London, UK", remote=False), prefs)
    assert not passes
    assert "location mismatch" in reason


def test_location_mismatch_us(prefs):
    passes, reason = hard_gate(make_job(location="San Francisco, CA", remote=False), prefs)
    assert not passes


def test_location_passes_hyderabad(prefs):
    passes, _ = hard_gate(make_job(location="Hyderabad, Telangana"), prefs)
    assert passes


def test_location_passes_bangalore(prefs):
    passes, _ = hard_gate(make_job(location="Bangalore, Karnataka"), prefs)
    assert passes


def test_location_passes_bengaluru(prefs):
    passes, _ = hard_gate(make_job(location="Bengaluru"), prefs)
    assert passes


def test_location_passes_gurugram(prefs):
    passes, _ = hard_gate(make_job(location="Gurugram, Haryana"), prefs)
    assert passes


def test_location_passes_remote_flag(prefs):
    passes, _ = hard_gate(make_job(location="Anywhere", remote=True), prefs)
    assert passes


def test_location_passes_unknown(prefs):
    passes, _ = hard_gate(make_job(location=None, remote=None), prefs)
    assert passes


# ---------------------------------------------------------------------------
# Hard gate — good jobs pass through
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Software Engineer",
    "Senior Software Engineer",
    "Backend Engineer",
    "Full Stack Engineer",
    "Software Engineer 2",
    "Software Engineer II",
    "Associate Software Engineer",
    "Python Engineer",
    "Python Developer",
    "Platform Engineer",
    "DevOps Engineer",
    "ML Engineer",
    "Data Engineer",
    "Software Development Engineer",
])
def test_good_title_passes(prefs, title):
    passes, reason = hard_gate(make_job(title=title), prefs)
    assert passes, f"Expected pass for '{title}', got: {reason}"


# ---------------------------------------------------------------------------
# Hard gate — irrelevant roles rejected by role-relevance check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Finance & Strategy, GTM",
    "Account Executive",
    "Marketing Manager",
    "Security Engineer",
    "Data Center Engineer",
    "Sales Development Representative",
    "Product Operations Manager",
    "Recruiter",
    "Legal Counsel",
    "Business Analyst",
])
def test_irrelevant_title_rejected(prefs, title):
    passes, reason = hard_gate(make_job(title=title), prefs)
    assert not passes, f"Expected rejection for '{title}'"
    assert "not relevant" in reason


# ---------------------------------------------------------------------------
# EvaluationResult schema
# ---------------------------------------------------------------------------

VALID_EVAL = {
    "fit_score": 82,
    "matched_requirements": ["Java", "Spring Boot", "AWS"],
    "missing_requirements": ["Kubernetes"],
    "strengths_for_role": ["5+ years Java", "Snowflake/Spark experience"],
    "concerns": ["No K8s experience mentioned"],
    "should_apply": True,
    "reasoning": "Strong backend match with relevant fintech pipeline experience.",
}


def test_evaluation_result_valid():
    result = EvaluationResult(**VALID_EVAL)
    assert result.fit_score == 82
    assert result.should_apply is True
    assert len(result.matched_requirements) == 3


def test_evaluation_result_roundtrip_json():
    result = EvaluationResult(**VALID_EVAL)
    restored = EvaluationResult(**json.loads(result.model_dump_json()))
    assert restored == result


def test_evaluation_result_rejects_bad_fit_score():
    with pytest.raises(ValidationError):
        EvaluationResult(**{**VALID_EVAL, "fit_score": "not-a-number"})


def test_evaluation_result_rejects_missing_field():
    data = {k: v for k, v in VALID_EVAL.items() if k != "reasoning"}
    with pytest.raises(ValidationError):
        EvaluationResult(**data)


# ---------------------------------------------------------------------------
# Preferences schema
# ---------------------------------------------------------------------------

def test_preferences_loads():
    prefs = Preferences(**PREFS_DATA)
    assert prefs.fit_score_threshold == 70
    assert prefs.seniority.min == "mid"
    assert "India" in prefs.locations


def test_preferences_defaults():
    minimal = {**PREFS_DATA}
    del minimal["fit_score_threshold"]
    prefs = Preferences(**minimal)
    assert prefs.fit_score_threshold == 70
