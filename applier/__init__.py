"""Auto-apply module — Playwright-based form filling for Greenhouse, Lever, Ashby."""
import logging
import time
from pathlib import Path

import yaml

from applier.greenhouse import apply_greenhouse
from applier.lever import apply_lever
from applier.ashby import apply_ashby

logger = logging.getLogger(__name__)

_APPLY_FN = {
    "greenhouse": apply_greenhouse,
    "lever": apply_lever,
    "ashby": apply_ashby,
}

_RATE_LIMIT_SECS = 30  # minimum seconds between live submissions


def _load_field_answers(path: Path) -> dict:
    if not path.exists():
        logger.warning("field_answers not found at %s — using empty dict", path)
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _append_unknowns(unknowns_path: Path, job: dict, fields: list[dict]) -> None:
    unknowns_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if unknowns_path.exists():
        existing = yaml.safe_load(unknowns_path.read_text()) or []
    for f in fields:
        existing.append({
            "company": job["company"],
            "title": job["title"],
            "apply_url": job.get("apply_url") or job.get("url"),
            "field_label": f["label"],
            "field_type": f["input_type"],
        })
    unknowns_path.write_text(yaml.dump(existing, allow_unicode=True), encoding="utf-8")


def run_apply(
    field_answers_path: Path,
    outputs_dir: Path,
    ats_filter: str | None = None,
    dry_run: bool = True,
) -> tuple[int, int, int]:
    """Apply to all tailored jobs. Returns (applied, dry_run_count, needs_manual).

    Requires playwright to be installed: `playwright install chromium`
    """
    from db import get_jobs_by_status, update_job_applied

    from playwright.sync_api import sync_playwright

    field_answers = _load_field_answers(field_answers_path)
    unknowns_path = outputs_dir / "unknowns.yaml"

    jobs = get_jobs_by_status("tailored")
    if ats_filter:
        jobs = [j for j in jobs if j["ats"] == ats_filter]

    if not jobs:
        logger.info("No tailored jobs to apply to (ats_filter=%s)", ats_filter)
        return 0, 0, 0

    applied_count = dry_run_count = manual_count = 0
    last_submit_time = 0.0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        for job in jobs:
            ats = job["ats"]
            apply_fn = _APPLY_FN.get(ats)
            if apply_fn is None:
                logger.warning("No applier for ATS '%s' — skipping %s", ats, job["company"])
                continue

            # Resolve paths
            resume_path: Path | None = None
            if job.get("tailored_resume_path"):
                resume_path = Path(job["tailored_resume_path"])

            cover_letter_path: Path | None = None
            if job.get("cover_letter_path"):
                cover_letter_path = Path(job["cover_letter_path"])
            else:
                fallback = Path("profile_templates/cover_letter_fallback.md")
                if fallback.exists():
                    cover_letter_path = fallback

            # Rate limit for real submissions
            if not dry_run:
                elapsed = time.time() - last_submit_time
                if elapsed < _RATE_LIMIT_SECS:
                    wait = _RATE_LIMIT_SECS - elapsed
                    logger.info("Rate limiting: waiting %.0fs before next submission", wait)
                    time.sleep(wait)

            page = context.new_page()
            try:
                result = apply_fn(
                    page=page,
                    job=job,
                    field_answers=field_answers,
                    resume_path=resume_path,
                    cover_letter_path=cover_letter_path,
                    outputs_dir=outputs_dir,
                    dry_run=dry_run,
                )
            except Exception as exc:
                logger.error("Unexpected error applying to %s — %s: %s", job["company"], job["title"], exc)
                result = {"status": "error", "unresolved_fields": [], "notes": str(exc),
                          "screenshot_pre": None, "screenshot_post": None}
            finally:
                page.close()

            status = result["status"]
            notes = result.get("notes", "")

            if status == "applied":
                applied_count += 1
                last_submit_time = time.time()
                update_job_applied(job["id"], status="applied", notes=notes,
                                   screenshot_path=result.get("screenshot_post"))
                logger.info("Applied: %s — %s", job["company"], job["title"])

            elif status == "dry_run":
                dry_run_count += 1
                update_job_applied(job["id"], status="tailored", notes="dry_run complete",
                                   screenshot_path=result.get("screenshot_pre"))
                logger.info("Dry run complete: %s — %s", job["company"], job["title"])

            elif status == "needs_manual":
                manual_count += 1
                update_job_applied(job["id"], status="needs_manual", notes=notes)
                if result.get("unresolved_fields"):
                    _append_unknowns(unknowns_path, job, result["unresolved_fields"])
                logger.info("Needs manual: %s — %s (%s)", job["company"], job["title"], notes)

            else:  # error
                update_job_applied(job["id"], status="error", notes=notes)
                logger.error("Error applying to %s — %s: %s", job["company"], job["title"], notes)

        browser.close()

    return applied_count, dry_run_count, manual_count
