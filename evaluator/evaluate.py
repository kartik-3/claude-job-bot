import json
import logging
import os
import subprocess
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from .prompts import EVALUATION_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


def _call_llm(system: str, user_msg: str, max_tokens: int = 1024) -> str | None:
    """Call Claude. Uses Anthropic API if ANTHROPIC_API_KEY is set, otherwise falls
    back to the `claude` CLI (already authenticated via Claude Code)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            response = client.messages.create(
                model=_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text
        except Exception as exc:
            logger.warning("Anthropic API call failed: %s", exc)
            return None

    # No API key — use the claude CLI (Claude Code's managed auth)
    full_prompt = f"{system}\n\n---\n\n{user_msg}"
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning("claude CLI non-zero exit: %s", result.stderr[:200])
    except FileNotFoundError:
        logger.error("No LLM available: set ANTHROPIC_API_KEY or install the claude CLI")
    except subprocess.TimeoutExpired:
        logger.error("claude CLI timed out")
    return None


def _extract_json(text: str) -> str:
    """Pull the first complete JSON object out of a response, tolerating any surrounding prose."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    # Find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text

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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SeniorityRange(BaseModel):
    min: str
    max: str


class SalaryConfig(BaseModel):
    min_inr: int | None = None
    currency: str = "INR"


class Preferences(BaseModel):
    target_roles: list[str]
    locations: list[str]
    remote_ok: bool
    seniority: SeniorityRange
    salary: SalaryConfig
    visa_sponsorship_needed: bool
    fit_score_threshold: int = 70
    non_negotiables: list[dict] = []
    excluded_industries: list[str] = []
    excluded_titles: list[str] = []
    tech_keywords: list[str] = []


class EvaluationResult(BaseModel):
    fit_score: int
    matched_requirements: list[str]
    missing_requirements: list[str]
    strengths_for_role: list[str]
    concerns: list[str]
    should_apply: bool
    reasoning: str


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_preferences(path: Path) -> Preferences:
    return Preferences(**yaml.safe_load(path.read_text()))


# ---------------------------------------------------------------------------
# Hard-gate filters (no LLM, runs first)
# ---------------------------------------------------------------------------

_INDIA_CITIES = (
    "india", "hyderabad", "bangalore", "bengaluru", "delhi", "ncr",
    "gurugram", "gurgaon", "noida", "mumbai", "pune", "chennai",
)


def _location_passes(job: dict, prefs: Preferences) -> bool:
    if prefs.remote_ok and job.get("remote"):
        return True
    loc = (job.get("location") or "").lower()
    if not loc:
        return True  # unknown — let LLM decide
    pref_locs = [p.lower() for p in prefs.locations]
    if "remote" in pref_locs and "remote" in loc:
        return True
    # "india" in prefs acts as a catch-all for any Indian city
    if "india" in pref_locs and any(city in loc for city in _INDIA_CITIES):
        return True
    for pref_loc in pref_locs:
        if pref_loc in loc or loc in pref_loc:
            return True
    return False


def _tokenize(text: str) -> set[str]:
    return set(text.lower().replace(",", " ").replace("-", " ").replace("/", " ").split())


def _role_relevant(title: str, prefs: Preferences) -> bool:
    """Return True if every token in at least one target_role appears in the title.

    "Software Engineer" matches "Senior Software Engineer" ✓
    "Software Engineer" does NOT match "Security Engineer" or "Finance Manager" ✗
    If target_roles is empty, all titles pass (no filter configured).
    """
    if not prefs.target_roles:
        return True
    title_tokens = _tokenize(title)
    for role in prefs.target_roles:
        role_tokens = _tokenize(role)
        if role_tokens and role_tokens.issubset(title_tokens):
            return True
    return False


def _keyword_matches(description: str | None, prefs: Preferences) -> bool:
    """Return True if the description contains at least one tech_keyword.

    Always returns True when tech_keywords is empty (filter disabled) or when
    the description is absent — we can't penalise jobs for missing JD text.
    """
    if not prefs.tech_keywords or not description:
        return True
    desc_lower = description.lower()
    return any(kw.lower() in desc_lower for kw in prefs.tech_keywords)


def hard_gate(job: dict, prefs: Preferences) -> tuple[bool, str]:
    """Return (passes, reason). passes=False means skip LLM evaluation."""
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


# ---------------------------------------------------------------------------
# LLM evaluation
# ---------------------------------------------------------------------------


def _call_claude(
    resume: str,
    job_description: str,
    prefs: Preferences,
) -> EvaluationResult | None:
    user_msg = EVALUATION_PROMPT.format(
        resume=resume,
        job_description=job_description or "(no description provided)",
        fit_score_threshold=prefs.fit_score_threshold,
        seniority_min=prefs.seniority.min,
        seniority_max=prefs.seniority.max,
        locations=", ".join(prefs.locations),
        remote_ok=prefs.remote_ok,
    )
    for attempt in range(2):
        try:
            raw = _call_llm(SYSTEM_PROMPT, user_msg, max_tokens=1024)
            if raw is None:
                raise RuntimeError("LLM returned no output")
            return EvaluationResult(**json.loads(_extract_json(raw)))
        except (ValidationError, json.JSONDecodeError, KeyError, IndexError, RuntimeError) as exc:
            if attempt == 0:
                logger.warning("Evaluation parse failed (attempt 1), retrying: %s", exc)
            else:
                logger.error("Evaluation parse failed (attempt 2), skipping: %s", exc)
    return None


def evaluate_job(
    resume: str,
    job_description: str,
    prefs: Preferences,
) -> EvaluationResult:
    """Evaluate a single job. Raises RuntimeError if LLM parse fails twice."""
    result = _call_claude(resume, job_description, prefs)
    if result is None:
        raise RuntimeError("LLM evaluation failed after 2 attempts")
    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_evaluation(prefs: Preferences, resume: str) -> tuple[int, int, int]:
    """Evaluate all status=new jobs. Returns (evaluated, should_apply, skipped)."""
    from db import get_jobs_by_status, update_job_evaluation

    jobs = get_jobs_by_status("new")
    if not jobs:
        logger.info("No new jobs to evaluate")
        return 0, 0, 0

    evaluated = should_apply_count = skipped_count = 0

    for job in jobs:
        passes, reason = hard_gate(job, prefs)
        if not passes:
            logger.info(
                "Hard gate: %s — %s [%s]", job["company"], job["title"], reason
            )
            update_job_evaluation(
                job["id"],
                fit_score=0,
                status="should_not_apply",
                evaluation_json=json.dumps({"hard_gate_reason": reason}),
                notes=f"hard gate: {reason}",
            )
            skipped_count += 1
            evaluated += 1
            continue

        if not _keyword_matches(job.get("description"), prefs):
            reason = "no tech keywords found in description"
            logger.info(
                "Keyword gate: %s — %s [%s]", job["company"], job["title"], reason
            )
            update_job_evaluation(
                job["id"],
                fit_score=0,
                status="should_not_apply",
                evaluation_json=json.dumps({"hard_gate_reason": reason}),
                notes=f"hard gate: {reason}",
            )
            skipped_count += 1
            evaluated += 1
            continue

        logger.info("Evaluating: %s — %s", job["company"], job["title"])
        result = _call_claude(resume, job.get("description") or "", prefs)

        if result is None:
            update_job_evaluation(
                job["id"],
                fit_score=0,
                status="error",
                evaluation_json=json.dumps({"error": "LLM parse failed after 2 attempts"}),
                notes="LLM evaluation failed",
            )
            evaluated += 1
            continue

        final_status = "should_apply" if result.should_apply else "should_not_apply"
        update_job_evaluation(
            job["id"],
            fit_score=result.fit_score,
            status=final_status,
            evaluation_json=result.model_dump_json(),
            notes=result.reasoning,
        )
        logger.info(
            "  score=%d should_apply=%s — %s",
            result.fit_score, result.should_apply, result.reasoning[:80],
        )

        if result.should_apply:
            should_apply_count += 1
        else:
            skipped_count += 1
        evaluated += 1

    return evaluated, should_apply_count, skipped_count
