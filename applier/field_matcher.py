"""Map form field labels to field_answers.yaml entries.

Matching order:
1. Exact key match (case-insensitive, normalized)
2. Token-overlap heuristic
3. Claude-assisted semantic match (one API call per unknown field)
"""
import logging
import os
import re
import subprocess

from .prompts import FIELD_MATCH_PROMPT, FIELD_MATCH_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

UNKNOWN = "UNKNOWN"

_MODEL = "claude-haiku-4-5-20251001"  # cheap model for field matching

# Hand-coded aliases that cover the most common variations without a Claude call.
_ALIASES: dict[str, str] = {
    "first name": "first_name",
    "last name": "last_name",
    "surname": "last_name",
    "family name": "last_name",
    "full name": "full_name",
    "your name": "full_name",
    "name": "full_name",
    "email": "email",
    "email address": "email",
    "mobile": "phone",
    "mobile number": "phone",
    "phone": "phone",
    "phone number": "phone",
    "telephone": "phone",
    "cell": "phone",
    "city": "city",
    "state": "state",
    "country": "country",
    "zip": "zip_code",
    "zip code": "zip_code",
    "postal code": "zip_code",
    "location": "location",
    "current location": "location",
    "address": "location",
    "linkedin": "linkedin_url",
    "linkedin url": "linkedin_url",
    "linkedin profile": "linkedin_url",
    "github": "github_url",
    "github url": "github_url",
    "portfolio": "portfolio_url",
    "website": "website",
    "personal website": "website",
    "work authorization": "work_authorization",
    "authorized to work": "work_authorization",
    "sponsorship": "visa_sponsorship_needed",
    "require sponsorship": "require_sponsorship",
    "visa sponsorship": "visa_sponsorship_needed",
    "years of experience": "years_of_experience",
    "total experience": "years_of_experience",
    "expected salary": "expected_salary",
    "salary expectation": "salary_expectations",
    "salary expectations": "salary_expectations",
    "desired salary": "expected_salary",
    "current salary": "current_salary",
    "current ctc": "current_salary",
    "expected ctc": "expected_salary",
    "notice period": "notice_period",
    "notice": "notice_period",
    "available to start": "available_to_start",
    "start date": "earliest_start_date",
    "earliest start date": "earliest_start_date",
    "willing to relocate": "willing_to_relocate",
    "relocation": "willing_to_relocate",
    "pronouns": "pronouns",
    "gender": "gender",
    "race": "race_ethnicity",
    "ethnicity": "race_ethnicity",
    "race / ethnicity": "race_ethnicity",
    "veteran": "veteran_status",
    "disability": "disability_status",
    "how did you hear": "how_did_you_hear",
    "how did you find": "how_did_you_hear",
    "source": "how_did_you_hear",
    "referral": "how_did_you_hear",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _token_overlap(label: str, key: str) -> float:
    """Fraction of label tokens found in the key (0.0–1.0)."""
    label_tokens = set(_normalize(label).split())
    key_tokens = set(_normalize(key.replace("_", " ")).split())
    if not label_tokens:
        return 0.0
    return len(label_tokens & key_tokens) / len(label_tokens)


def _call_llm(system: str, user_msg: str) -> str | None:
    """Call Claude. Uses Anthropic API if ANTHROPIC_API_KEY is set, otherwise falls
    back to the `claude` CLI (already authenticated via Claude Code)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            response = client.messages.create(
                model=_MODEL,
                max_tokens=32,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text.strip()
        except Exception as exc:
            logger.warning("Anthropic API call failed: %s", exc)
            return None

    full_prompt = f"{system}\n\n---\n\n{user_msg}"
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning("claude CLI non-zero exit: %s", result.stderr[:200])
    except FileNotFoundError:
        logger.error("No LLM available: set ANTHROPIC_API_KEY or install the claude CLI")
    except subprocess.TimeoutExpired:
        logger.error("claude CLI timed out")
    return None


def _claude_match(label: str, input_type: str, required: bool, keys: list[str]) -> str:
    """Ask Claude to pick the best key. Returns a key name or UNKNOWN."""
    user_msg = FIELD_MATCH_PROMPT.format(
        label=label,
        input_type=input_type,
        required=required,
        keys="\n".join(f"- {k}" for k in keys),
    )
    for attempt in range(2):
        answer = _call_llm(FIELD_MATCH_SYSTEM_PROMPT, user_msg)
        if answer is not None:
            if answer in keys:
                return answer
            if answer.upper() == UNKNOWN:
                return UNKNOWN
            logger.debug("Claude returned unexpected value '%s' for label '%s'", answer, label)
        if attempt == 0:
            logger.warning("Field match Claude call failed (attempt 1)")
        else:
            logger.error("Field match Claude call failed (attempt 2)")
    return UNKNOWN


def match(
    label: str,
    field_answers: dict,
    input_type: str = "text",
    required: bool = False,
    use_claude: bool = True,
) -> str | None:
    """Return the answer value for a form field label, or None if unresolvable.

    Returns None (not UNKNOWN) so callers can use `if value is None`.
    Logs the decision at DEBUG level for auditability.
    """
    keys = list(field_answers.keys())
    norm_label = _normalize(label)

    # 1. Alias table
    if norm_label in _ALIASES:
        key = _ALIASES[norm_label]
        if key in field_answers:
            logger.debug("field_match: '%s' → alias '%s'", label, key)
            return field_answers[key]

    # 2. Exact key match
    for k in keys:
        if _normalize(k) == norm_label or _normalize(k.replace("_", " ")) == norm_label:
            logger.debug("field_match: '%s' → exact '%s'", label, k)
            return field_answers[k]

    # 3. Token overlap ≥ 0.7
    best_key = max(keys, key=lambda k: _token_overlap(label, k), default=None)
    if best_key and _token_overlap(label, best_key) >= 0.7:
        logger.debug("field_match: '%s' → token-overlap '%s'", label, best_key)
        return field_answers[best_key]

    # 4. Claude semantic match
    if use_claude:
        matched_key = _claude_match(label, input_type, required, keys)
        if matched_key != UNKNOWN:
            logger.debug("field_match: '%s' → claude '%s'", label, matched_key)
            return field_answers[matched_key]

    logger.debug("field_match: '%s' → UNKNOWN", label)
    return None
