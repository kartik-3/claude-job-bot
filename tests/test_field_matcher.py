"""Tests for Phase 4 field_matcher — no live browser or API calls."""
import pytest

from applier.field_matcher import UNKNOWN, _normalize, _token_overlap, match

FIELD_ANSWERS = {
    "full_name": "Kartik Sehgal",
    "first_name": "Kartik",
    "last_name": "Sehgal",
    "email": "kartiksehgal3@gmail.com",
    "phone": "+919958571972",
    "location": "Hyderabad, Telangana",
    "city": "Hyderabad",
    "state": "Telangana",
    "country": "India",
    "zip_code": "500089",
    "linkedin_url": "https://linkedin.com/in/sehgal-kartik",
    "github_url": "https://github.com/kartik-3",
    "portfolio_url": "",
    "website": "",
    "work_authorization": "Yes, I am authorized to work in India",
    "visa_sponsorship_needed": "No",
    "require_sponsorship": "No",
    "years_of_experience": "7",
    "expected_salary": "40 LPA",
    "salary_expectations": "Open to discussion based on total compensation",
    "notice_period": "2 weeks",
    "earliest_start_date": "2 weeks from offer",
    "available_to_start": "2 weeks from offer",
    "willing_to_relocate": "Yes",
    "pronouns": "He/Him",
    "gender": "Male",
    "race_ethnicity": "Asian",
    "veteran_status": "I am not a veteran",
    "disability_status": "No, I do not have a disability",
    "how_did_you_hear": "LinkedIn",
}


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

def test_normalize_strips_punctuation():
    assert _normalize("First Name*") == "first name"


def test_normalize_lowercases():
    assert _normalize("Email Address") == "email address"


# ---------------------------------------------------------------------------
# _token_overlap
# ---------------------------------------------------------------------------

def test_token_overlap_full_match():
    assert _token_overlap("years of experience", "years_of_experience") == 1.0


def test_token_overlap_partial():
    score = _token_overlap("phone number", "phone")
    assert score > 0.0


def test_token_overlap_no_match():
    assert _token_overlap("banana split", "email") == 0.0


# ---------------------------------------------------------------------------
# match — alias table (no Claude call)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label, expected_value", [
    ("Full Name", "Kartik Sehgal"),
    ("Email", "kartiksehgal3@gmail.com"),
    ("Email Address", "kartiksehgal3@gmail.com"),
    ("Phone", "+919958571972"),
    ("Mobile Number", "+919958571972"),
    ("Phone Number", "+919958571972"),
    ("Location", "Hyderabad, Telangana"),
    ("Current Location", "Hyderabad, Telangana"),
    ("LinkedIn", "https://linkedin.com/in/sehgal-kartik"),
    ("LinkedIn URL", "https://linkedin.com/in/sehgal-kartik"),
    ("GitHub", "https://github.com/kartik-3"),
    ("Notice Period", "2 weeks"),
    ("Years of Experience", "7"),
    ("Visa Sponsorship", "No"),
    ("How did you hear", "LinkedIn"),
    ("Gender", "Male"),
])
def test_alias_matches(label, expected_value):
    result = match(label, FIELD_ANSWERS, use_claude=False)
    assert result == expected_value, f"label='{label}' expected '{expected_value}', got '{result}'"


# ---------------------------------------------------------------------------
# match — exact key match
# ---------------------------------------------------------------------------

def test_exact_key_match():
    result = match("email", FIELD_ANSWERS, use_claude=False)
    assert result == "kartiksehgal3@gmail.com"


def test_exact_key_with_underscores():
    result = match("zip code", FIELD_ANSWERS, use_claude=False)
    assert result == "500089"


# ---------------------------------------------------------------------------
# match — token overlap
# ---------------------------------------------------------------------------

def test_token_overlap_match_relocate():
    # "willing to relocate anywhere" → 3/4 tokens match willing_to_relocate → ≥ 0.7
    result = match("willing to relocate anywhere", FIELD_ANSWERS, use_claude=False)
    assert result == "Yes"


# ---------------------------------------------------------------------------
# match — UNKNOWN fallback (no Claude)
# ---------------------------------------------------------------------------

def test_unknown_when_no_match():
    result = match("secret_proprietary_field_xyz", FIELD_ANSWERS, use_claude=False)
    assert result is None


def test_unknown_empty_label():
    result = match("", FIELD_ANSWERS, use_claude=False)
    assert result is None


# ---------------------------------------------------------------------------
# match — field_answers values
# ---------------------------------------------------------------------------

def test_returns_value_not_key():
    result = match("first name", FIELD_ANSWERS, use_claude=False)
    assert result == "Kartik"


def test_empty_value_returned_as_is():
    result = match("portfolio", FIELD_ANSWERS, use_claude=False)
    assert result == ""
