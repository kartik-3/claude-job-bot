"""Lever application filler.

Lever apply pages live at: https://jobs.lever.co/{slug}/{job_id}/apply
Form fields are standard HTML inputs with well-known name attributes.
"""
import logging
import time
from pathlib import Path

from applier.base import _get_label, _unique_selector, take_screenshot
from applier.field_matcher import match

logger = logging.getLogger(__name__)

_KNOWN_FIELDS: list[tuple[str, str]] = [
    ("input[name='name']", "full_name"),
    ("input[name='email']", "email"),
    ("input[name='phone']", "phone"),
    ("input[name='location']", "location"),
    ("input[name='urls[LinkedIn]']", "linkedin_url"),
    ("input[name='urls[GitHub]']", "github_url"),
    ("input[name='urls[Portfolio]']", "portfolio_url"),
    ("input[name='urls[Other]']", "website"),
]


def apply_lever(
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

    # Standard known fields
    for selector, key in _KNOWN_FIELDS:
        el = page.query_selector(selector)
        if el is None:
            continue
        value = field_answers.get(key)
        required = el.get_attribute("required") is not None
        if value:
            el.fill(str(value))
        elif required:
            unresolved.append({"selector": selector, "label": key, "input_type": "text"})

    # Resume upload
    resume_input = page.query_selector("input[type='file'][name='resume']")
    if resume_input and resume_path and resume_path.exists():
        resume_input.set_input_files(str(resume_path))

    # Cover letter textarea (Lever uses a textarea, not file upload)
    cl_textarea = page.query_selector("textarea[name='comments']")
    if cl_textarea and cover_letter_path and cover_letter_path.exists():
        cl_text = cover_letter_path.read_text(encoding="utf-8")
        cl_textarea.fill(cl_text)

    # Additional custom fields
    custom_fields = page.query_selector_all(
        "[data-qa='additional-cards'] input, "
        "[data-qa='additional-cards'] textarea, "
        "[data-qa='additional-cards'] select"
    )
    for el in custom_fields:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        input_type = el.get_attribute("type") or tag
        required = el.get_attribute("required") is not None
        label = _get_label(page, el)
        if not label:
            continue
        value = match(label, field_answers, input_type=input_type, required=required)
        if value is not None:
            if tag == "select":
                _select_option(el, value)
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
