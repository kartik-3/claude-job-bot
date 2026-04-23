"""Ashby application filler.

Ashby apply pages live at: https://jobs.ashbyhq.com/{slug}/{job_id}/application
Forms are React-rendered with aria labels — rely on field_matcher for all fields.
"""
import logging
import time
from pathlib import Path

from applier.base import _get_label, _unique_selector, take_screenshot
from applier.field_matcher import match

logger = logging.getLogger(__name__)


def apply_ashby(
    page: object,
    job: dict,
    field_answers: dict,
    resume_path: Path | None,
    cover_letter_path: Path | None,
    outputs_dir: Path,
    dry_run: bool = True,
) -> dict:
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
        page.goto(apply_url, timeout=30_000, wait_until="networkidle")
        time.sleep(1)
    except Exception as exc:
        result["notes"] = f"Navigation failed: {exc}"
        return result

    if _captcha_detected(page):
        result["status"] = "needs_manual"
        result["notes"] = "captcha_detected"
        take_screenshot(page, f"{company}_{title}_captcha")
        return result

    unresolved: list[dict] = []

    # Resume upload
    resume_input = page.query_selector("input[type='file']")
    if resume_input and resume_path and resume_path.exists():
        resume_input.set_input_files(str(resume_path))
        logger.debug("Uploaded resume: %s", resume_path)

    # All form inputs (Ashby renders them with aria-label)
    all_inputs = page.query_selector_all("input:not([type=hidden]):not([type=submit]):not([type=file]), textarea, select")
    for el in all_inputs:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        input_type = el.get_attribute("type") or tag
        required = el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true"
        label = _get_label(page, el)
        if not label:
            continue

        # Cover letter field — fill from file if available
        if "cover" in label.lower() and cover_letter_path and cover_letter_path.exists():
            cl_text = cover_letter_path.read_text(encoding="utf-8")
            el.fill(cl_text)
            continue

        value = match(label, field_answers, input_type=input_type, required=required)
        if value is not None:
            if tag == "select":
                _select_option(el, value)
            elif tag == "textarea":
                el.fill(str(value))
            else:
                el.fill(str(value))
        elif required:
            unresolved.append({
                "selector": _unique_selector(el),
                "label": label,
                "input_type": input_type,
            })

    result["unresolved_fields"] = unresolved

    if unresolved:
        result["status"] = "needs_manual"
        result["notes"] = f"unresolved required fields: {[f['label'] for f in unresolved]}"
        take_screenshot(page, f"{company}_{title}_needs_manual")
        return result

    pre_ss = take_screenshot(page, f"{company}_{title}_pre_submit")
    result["screenshot_pre"] = str(pre_ss)

    if dry_run:
        result["status"] = "dry_run"
        result["notes"] = "dry_run — form filled, not submitted"
        return result

    try:
        submit = page.query_selector("button[type='submit']")
        if submit is None:
            result["notes"] = "submit button not found"
            return result
        submit.click()
        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(2)
        post_ss = take_screenshot(page, f"{company}_{title}_post_submit")
        result["screenshot_post"] = str(post_ss)
        result["status"] = "applied"
        result["notes"] = "submitted"
    except Exception as exc:
        result["notes"] = f"submit failed: {exc}"

    return result


def _select_option(el: object, value: str) -> None:
    options = el.query_selector_all("option")
    for opt in options:
        if opt.inner_text().strip().lower() == value.lower():
            el.select_option(value=opt.get_attribute("value"))
            return
    for opt in options:
        if value.lower() in opt.inner_text().strip().lower():
            el.select_option(value=opt.get_attribute("value"))
            return


def _captcha_detected(page: object) -> bool:
    content = page.content().lower()
    return any(ind in content for ind in ["g-recaptcha", "h-captcha", "cf-turnstile", "captcha"])
