"""Greenhouse application filler.

Greenhouse uses a predictable form structure at:
  https://boards.greenhouse.io/{slug}/jobs/{job_id}

The "Apply" button opens an iframe or a dedicated page at:
  https://boards.greenhouse.io/{slug}/jobs/{job_id}#app

Most Greenhouse forms have named inputs: first_name, last_name, email, phone,
resume (file upload), cover_letter (optional file upload), and a set of
custom_field[xxx] inputs for additional questions.
"""
import logging
import re
import time
from pathlib import Path

from applier.base import detect_fields, select_option, take_screenshot
from applier.field_matcher import match

logger = logging.getLogger(__name__)

_RATE_LIMIT_SECS = 30  # minimum gap between live submissions


def _fill_standard_fields(page: object, field_answers: dict) -> list[dict]:
    """Fill standard Greenhouse inputs. Returns list of unresolved required fields."""
    unresolved: list[dict] = []

    # Greenhouse has well-known name attributes for basic fields
    _KNOWN_SELECTORS: list[tuple[str, str]] = [
        ("input[name='job_application[first_name]']", "first_name"),
        ("input[name='job_application[last_name]']", "last_name"),
        ("input[name='job_application[email]']", "email"),
        ("input[name='job_application[phone]']", "phone"),
        ("input[name='job_application[location]']", "location"),
    ]

    for selector, key in _KNOWN_SELECTORS:
        el = page.query_selector(selector)
        if el is None:
            continue
        value = field_answers.get(key)
        if value:
            el.fill(str(value))
            logger.debug("Filled %s = %s", key, value)
        else:
            required = el.get_attribute("required") is not None
            if required:
                unresolved.append({"selector": selector, "label": key, "input_type": "text"})

    return unresolved


def _fill_custom_fields(
    page: object,
    field_answers: dict,
    unresolved: list[dict],
) -> None:
    """Fill custom_field[xxx] inputs using field_matcher."""
    custom_inputs = page.query_selector_all("input[name^='job_application[answers_attributes]'], "
                                            "textarea[name^='job_application[answers_attributes]'], "
                                            "select[name^='job_application[answers_attributes]']")
    for el in custom_inputs:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        input_type = el.get_attribute("type") or tag
        required = el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true"

        from applier.base import _get_label
        label = _get_label(page, el)
        if not label:
            continue

        from applier.base import _unique_selector
        selector = _unique_selector(el)

        value = match(label, field_answers, input_type=input_type, required=required)
        if value is not None:
            _set_field(page, el, tag, value)
        elif required:
            unresolved.append({"selector": selector, "label": label, "input_type": input_type})


def _set_field(page: object, el: object, tag: str, value: str) -> None:
    if tag == "select":
        select_option(el, value)
    else:
        el.fill(value)


def apply_greenhouse(
    page: object,
    job: dict,
    field_answers: dict,
    resume_path: Path | None,
    cover_letter_path: Path | None,
    outputs_dir: Path,
    dry_run: bool = True,
) -> dict:
    """Fill and optionally submit a Greenhouse application.

    Returns a result dict:
        status: "applied" | "dry_run" | "needs_manual" | "error"
        unresolved_fields: list of {label, input_type, selector} for UNKNOWN fields
        screenshot_pre: path to pre-submit screenshot
        screenshot_post: path to confirmation screenshot (only if submitted)
        notes: human-readable summary
    """
    result: dict = {
        "status": "error",
        "unresolved_fields": [],
        "screenshot_pre": None,
        "screenshot_post": None,
        "notes": "",
    }

    company = job["company"]
    title = job["title"]
    apply_url = job.get("apply_url") or job.get("url")

    try:
        logger.info("Navigating to %s", apply_url)
        page.goto(apply_url, timeout=30_000, wait_until="networkidle")
        time.sleep(1)  # let any JS settle
    except Exception as exc:
        result["notes"] = f"Navigation failed: {exc}"
        logger.error("Navigation failed for %s — %s: %s", company, title, exc)
        return result

    # Check for CAPTCHA
    if _captcha_detected(page):
        result["status"] = "needs_manual"
        result["notes"] = "captcha_detected"
        logger.warning("CAPTCHA detected: %s — %s", company, title)
        take_screenshot(page, f"{company}_{title}_captcha")
        return result

    # Fill standard fields
    unresolved = _fill_standard_fields(page, field_answers)

    # Upload resume
    resume_input = page.query_selector("input[type='file'][name*='resume']")
    if resume_input and resume_path and resume_path.exists():
        resume_input.set_input_files(str(resume_path))
        logger.debug("Uploaded resume: %s", resume_path)

    # Upload cover letter (optional)
    cl_input = page.query_selector("input[type='file'][name*='cover_letter']")
    if cl_input and cover_letter_path and cover_letter_path.exists():
        cl_input.set_input_files(str(cover_letter_path))
        logger.debug("Uploaded cover letter: %s", cover_letter_path)

    # Fill custom fields
    _fill_custom_fields(page, field_answers, unresolved)

    # Log every field decision
    for f in unresolved:
        logger.info("UNKNOWN field: label='%s' type='%s' selector='%s'",
                    f["label"], f["input_type"], f["selector"])

    result["unresolved_fields"] = unresolved

    if unresolved:
        result["status"] = "needs_manual"
        result["notes"] = f"unresolved required fields: {[f['label'] for f in unresolved]}"
        take_screenshot(page, f"{company}_{title}_needs_manual")
        return result

    # Pre-submit screenshot
    pre_ss = take_screenshot(page, f"{company}_{title}_pre_submit")
    result["screenshot_pre"] = str(pre_ss)

    if dry_run:
        result["status"] = "dry_run"
        result["notes"] = "dry_run — form filled, not submitted"
        logger.info("DRY RUN: %s — %s (screenshot: %s)", company, title, pre_ss)
        return result

    # Real submit
    try:
        submit_btn = page.query_selector("input[type='submit'], button[type='submit']")
        if submit_btn is None:
            result["notes"] = "submit button not found"
            return result
        submit_btn.click()
        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(2)
        post_ss = take_screenshot(page, f"{company}_{title}_post_submit")
        result["screenshot_post"] = str(post_ss)
        result["status"] = "applied"
        result["notes"] = "submitted"
        logger.info("APPLIED: %s — %s", company, title)
    except Exception as exc:
        result["notes"] = f"submit failed: {exc}"
        logger.error("Submit error for %s — %s: %s", company, title, exc)

    return result


def _captcha_detected(page: object) -> bool:
    """Heuristic: look for common CAPTCHA indicators."""
    content = page.content().lower()
    indicators = ["g-recaptcha", "h-captcha", "cf-turnstile", "captcha", "robot"]
    return any(ind in content for ind in indicators)
