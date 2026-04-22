import json
import logging
import os
from pathlib import Path

import yaml
from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from .prompts import EVALUATION_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

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


def hard_gate(job: dict, prefs: Preferences) -> tuple[bool, str]:
    """Return (passes, reason). passes=False means skip LLM evaluation."""
    title = job.get("title", "")
    title_lower = title.lower()

    for excluded in prefs.excluded_titles:
        if excluded.lower() in title_lower:
            return False, f"excluded title: {excluded}"

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

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _call_claude(
    resume: str,
    job_description: str,
    prefs: Preferences,
) -> EvaluationResult | None:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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
            response = client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = _strip_fences(response.content[0].text)
            return EvaluationResult(**json.loads(raw))
        except (ValidationError, json.JSONDecodeError, KeyError, IndexError) as exc:
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
