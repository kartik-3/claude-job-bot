"""Shared Playwright session, field detection, and screenshot helpers."""
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SCREENSHOT_DIR = Path("outputs/screenshots")

_OVER_SENIORITY_TOKENS = {
    "staff", "principal", "distinguished", "fellow",
    "director", "vp", "vice president", "head of",
}

_INPUT_TYPES = {"text", "email", "tel", "number", "url", "date", "textarea", "select", "file", "checkbox", "radio"}


def screenshot_dir() -> Path:
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SCREENSHOT_DIR


def take_screenshot(page: object, label: str) -> Path:
    """Save a screenshot with a timestamped filename."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = label.replace("/", "-").replace(" ", "_")[:60]
    path = screenshot_dir() / f"{ts}_{safe_label}.png"
    page.screenshot(path=str(path))
    logger.debug("Screenshot: %s", path)
    return path


def detect_fields(page: object) -> list[dict]:
    """Return all visible form fields as a list of dicts.

    Each dict has keys: label, input_type, required, selector, element_type.
    """
    fields: list[dict] = []

    # Text-like inputs
    inputs = page.query_selector_all("input:not([type=hidden]):not([type=submit]):not([type=button])")
    for el in inputs:
        input_type = el.get_attribute("type") or "text"
        if input_type not in _INPUT_TYPES:
            continue
        label = _get_label(page, el)
        required = el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true"
        selector = _unique_selector(el)
        fields.append({
            "label": label,
            "input_type": input_type,
            "required": required,
            "selector": selector,
            "element_type": "input",
        })

    # Textareas
    for el in page.query_selector_all("textarea"):
        label = _get_label(page, el)
        required = el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true"
        selector = _unique_selector(el)
        fields.append({
            "label": label,
            "input_type": "textarea",
            "required": required,
            "selector": selector,
            "element_type": "textarea",
        })

    # Select dropdowns
    for el in page.query_selector_all("select"):
        label = _get_label(page, el)
        required = el.get_attribute("required") is not None
        selector = _unique_selector(el)
        fields.append({
            "label": label,
            "input_type": "select",
            "required": required,
            "selector": selector,
            "element_type": "select",
        })

    return fields


def _get_label(page: object, el: object) -> str:
    """Best-effort label extraction: aria-label → <label for> → placeholder → name."""
    # aria-label
    aria = el.get_attribute("aria-label")
    if aria:
        return aria.strip()

    # <label for="id">
    el_id = el.get_attribute("id")
    if el_id:
        label_el = page.query_selector(f"label[for='{el_id}']")
        if label_el:
            text = label_el.inner_text().strip()
            if text:
                return text

    # aria-labelledby
    labelledby = el.get_attribute("aria-labelledby")
    if labelledby:
        ref = page.query_selector(f"#{labelledby}")
        if ref:
            text = ref.inner_text().strip()
            if text:
                return text

    # placeholder fallback
    placeholder = el.get_attribute("placeholder")
    if placeholder:
        return placeholder.strip()

    # name attribute as last resort
    name = el.get_attribute("name") or ""
    return name.replace("_", " ").replace("-", " ").strip()


def _unique_selector(el: object) -> str:
    """Return a usable CSS selector for this element."""
    el_id = el.get_attribute("id")
    if el_id:
        return f"#{el_id}"
    name = el.get_attribute("name")
    if name:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        return f"{tag}[name='{name}']"
    # fallback: let playwright identify by position (caller must handle)
    return el.evaluate(
        """el => {
            const path = [];
            let node = el;
            while (node && node.nodeType === 1) {
                let idx = 1;
                let sibling = node.previousElementSibling;
                while (sibling) { if (sibling.tagName === node.tagName) idx++; sibling = sibling.previousElementSibling; }
                path.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + idx + ')');
                node = node.parentElement;
            }
            return path.join(' > ');
        }"""
    )
